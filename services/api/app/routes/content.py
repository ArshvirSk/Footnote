"""Content generation pipeline and approvals routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.app.auth import (
    AuthUser,
    MemberRole,
    get_current_user,
    has_client_access,
    require_roles,
)
from services.api.app.db import get_db
from services.api.app.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/clients/{client_id}/content", tags=["content"])


class BriefCreateRequest(BaseModel):
    prompt_id: UUID
    instructions: str | None = None

class ApprovalActionRequest(BaseModel):
    action: str  # "approve" or "reject"
    comment: str | None = None


@router.post("/briefs", status_code=status.HTTP_201_CREATED)
async def create_brief(
    client_id: UUID,
    body: BriefCreateRequest,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.STRATEGIST, MemberRole.ADMIN, MemberRole.OWNER))],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Trigger the creation of a content brief from a gap/prompt."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=403, detail="Access denied")

    async with db.begin():
        # Insert brief
        res = await db.execute(
            text("""
                INSERT INTO briefs (client_id, prompt_id, content_json, status)
                VALUES (:cid, :pid, '{"outline": "Generation pending..."}', 'draft')
                RETURNING id
            """),
            {"cid": str(client_id), "pid": str(body.prompt_id)}
        )
        brief_id = res.scalar()
        
        # Insert ops approval gate
        await db.execute(
            text("""
                INSERT INTO approvals (client_id, entity_type, entity_id, gate_type, status)
                VALUES (:cid, 'brief', :eid, 'internal_ops', 'pending')
            """),
            {"cid": str(client_id), "eid": str(brief_id)}
        )
        
    # In a real system, we'd fire an event to the LangGraph agents service here
    logger.info("brief_generation_triggered", brief_id=str(brief_id))
    return {"id": str(brief_id), "status": "draft"}


@router.post("/approvals/{approval_id}/action")
async def action_approval(
    client_id: UUID,
    approval_id: UUID,
    body: ApprovalActionRequest,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Approve or reject a brief/draft."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=403, detail="Access denied")
        
    status_val = "approved" if body.action == "approve" else "rejected"
    
    async with db.begin():
        # We assume RLS handles ensuring the user has the right to update this specific gate_type
        # (e.g. client_approver can only update 'client_review' gates)
        res = await db.execute(
            text("""
                UPDATE approvals 
                SET status = :status, reviewed_by = :uid, reviewed_at = now()
                WHERE id = :aid AND client_id = :cid
                RETURNING entity_type, entity_id
            """),
            {"status": status_val, "uid": str(user.id), "aid": str(approval_id), "cid": str(client_id)}
        )
        row = res.first()
        if not row:
            raise HTTPException(status_code=404, detail="Approval not found")
            
        if body.comment:
            await db.execute(
                text("""
                    INSERT INTO comments (entity_type, entity_id, author_id, text)
                    VALUES ('approval', :aid, :uid, :comment)
                """),
                {"aid": str(approval_id), "uid": str(user.id), "comment": body.comment}
            )
            
    logger.info("approval_actioned", approval_id=str(approval_id), action=body.action)
    return {"status": "success", "new_status": status_val}
