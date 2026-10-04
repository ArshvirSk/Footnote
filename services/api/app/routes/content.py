"""Content pipeline routes: briefs and approval gates (ops side).

Rewritten against the real schema: content_briefs + approvals(subject_type/subject_id).
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from services.api.app.auth import (
    AuthUser,
    MemberRole,
    get_current_user,
    has_client_access,
    require_roles,
)
from services.api.app.db import get_db
from services.api.app.logging import get_logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

router = APIRouter(prefix="/clients/{client_id}/content", tags=["content"])

# action -> approval_status_t value
ACTION_TO_STATUS = {
    "approve": "approved",
    "reject": "rejected",
    "request_changes": "changes_requested",
}


class BriefCreateRequest(BaseModel):
    prompt_id: UUID
    title: str | None = None
    angle: str | None = None


class ApprovalActionRequest(BaseModel):
    action: str  # "approve" | "reject" | "request_changes"
    comment: str | None = None


@router.post("/briefs", status_code=status.HTTP_201_CREATED)
async def create_brief(
    client_id: UUID,
    body: BriefCreateRequest,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.STRATEGIST, MemberRole.ADMIN, MemberRole.OWNER))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Create a content brief mapped to a prompt and open the internal approval gate."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # The prompt must belong to this client (tenant-safe even without RLS).
    prompt = await db.execute(
        text("SELECT id FROM prompts WHERE id = :pid AND client_id = :cid"),
        {"pid": str(body.prompt_id), "cid": str(client_id)},
    )
    if prompt.first() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt not found for this client")

    res = await db.execute(
        text(
            """
            INSERT INTO content_briefs (client_id, title, angle, outline, created_by)
            VALUES (:cid, :title, :angle, '{}'::jsonb, :uid)
            RETURNING id
            """
        ),
        {
            "cid": str(client_id),
            "title": body.title or "Brief (generation pending)",
            "angle": body.angle,
            "uid": str(user.user_id),
        },
    )
    brief_id = res.scalar()

    await db.execute(
        text(
            """
            INSERT INTO approvals (client_id, subject_type, subject_id, status, requested_by)
            VALUES (:cid, 'brief', :sid, 'pending', :uid)
            """
        ),
        {"cid": str(client_id), "sid": str(brief_id), "uid": str(user.user_id)},
    )
    await db.commit()

    logger.info("brief_created", brief_id=str(brief_id), client_id=str(client_id))
    return {"id": str(brief_id), "status": "draft"}


@router.get("/approvals")
async def list_approvals(
    client_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict[str, Any]]:
    """List pending approvals for a client (ops or portal)."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    result = await db.execute(
        text(
            """
            SELECT id, subject_type, subject_id, status, requested_by, reviewer_id,
                   comment, requested_at, decided_at
            FROM approvals
            WHERE client_id = :cid
            ORDER BY requested_at DESC
            """
        ),
        {"cid": str(client_id)},
    )
    return [
        {
            "id": str(r.id),
            "subject_type": r.subject_type,
            "subject_id": str(r.subject_id),
            "status": r.status,
            "comment": r.comment,
            "requested_at": r.requested_at.isoformat() if r.requested_at else None,
            "decided_at": r.decided_at.isoformat() if r.decided_at else None,
        }
        for r in result.all()
    ]


@router.post("/approvals/{approval_id}/action")
async def action_approval(
    client_id: UUID,
    approval_id: UUID,
    body: ApprovalActionRequest,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Approve, reject, or request changes on a brief/draft approval record."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    new_status = ACTION_TO_STATUS.get(body.action)
    if new_status is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="action must be one of: approve, reject, request_changes",
        )

    # client_viewer is read-only in the portal (PRD §1.4).
    if user.role == MemberRole.CLIENT_VIEWER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Read-only role cannot decide approvals")

    result = await db.execute(
        text(
            """
            UPDATE approvals
            SET status = :status,
                reviewer_id = :uid,
                comment = COALESCE(:comment, comment),
                decided_at = now()
            WHERE id = :aid AND client_id = :cid AND status = 'pending'
            RETURNING subject_type, subject_id
            """
        ),
        {
            "status": new_status,
            "uid": str(user.user_id),
            "comment": body.comment,
            "aid": str(approval_id),
            "cid": str(client_id),
        },
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending approval not found")
    await db.commit()

    logger.info("approval_actioned", approval_id=str(approval_id), action=body.action)
    return {"status": "success", "new_status": new_status}
