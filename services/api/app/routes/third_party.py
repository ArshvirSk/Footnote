"""Third-party task board API: off-site authority building.

Full CRUD for third-party platform tasks (Reddit, Quora, HN, forums) with
AI-assisted draft generation and lifecycle management.
Status flow: todo → drafting → review → posted
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.app.auth import (
    AuthUser,
    MemberRole,
    has_client_access,
    require_roles,
)
from services.api.app.db import get_db
from services.api.app.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/clients/{client_id}/third-party", tags=["third-party"])

OPS_ROLES = (
    MemberRole.STRATEGIST,
    MemberRole.EDITOR,
    MemberRole.ADMIN,
    MemberRole.OWNER,
)

VALID_PLATFORMS = {"reddit", "quora", "hackernews", "forum", "other"}
VALID_STATUSES = {"todo", "drafting", "review", "posted", "archived"}


# ───────────── Schemas ─────────────

class ThirdPartyTaskCreate(BaseModel):
    platform: str = Field(..., description="reddit | quora | hackernews | forum | other")
    target_url: str | None = None
    thread_title: str | None = None
    brief: str | None = None
    assignee: UUID | None = None
    due_at: str | None = None


class ThirdPartyTaskUpdate(BaseModel):
    target_url: str | None = None
    thread_title: str | None = None
    brief: str | None = None
    draft: str | None = None
    assignee: UUID | None = None
    status: str | None = None
    posted_url: str | None = None
    due_at: str | None = None


class ThirdPartyTaskResponse(BaseModel):
    id: UUID
    client_id: UUID
    platform: str
    target_url: str | None = None
    thread_title: str | None = None
    brief: str | None = None
    draft: str | None = None
    assignee: UUID | None = None
    status: str
    posted_url: str | None = None
    due_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class DraftRequest(BaseModel):
    """Request body for AI draft generation."""
    context: str | None = Field(None, description="Additional context for draft generation")


# ───────────── Routes ─────────────

@router.get("/tasks", response_model=list[ThirdPartyTaskResponse])
async def list_third_party_tasks(
    client_id: UUID,
    task_status: str | None = Query(None, alias="status"),
    platform: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    user: AuthUser = Depends(require_roles(*OPS_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> list[ThirdPartyTaskResponse]:
    """List third-party tasks, optionally filtered by status and platform."""
    await has_client_access(client_id, user, db)

    conditions = ["t.client_id = :cid"]
    params: dict[str, Any] = {"cid": str(client_id), "limit": limit}

    if task_status:
        conditions.append("t.status = :status")
        params["status"] = task_status
    if platform:
        conditions.append("t.platform = :platform")
        params["platform"] = platform

    where = " AND ".join(conditions)
    result = await db.execute(
        text(f"""
            SELECT
                t.id, t.client_id, t.platform, t.target_url, t.thread_title,
                t.brief, t.draft, t.assignee, t.status, t.posted_url,
                CAST(t.due_at AS text), CAST(t.created_at AS text), CAST(t.updated_at AS text)
            FROM third_party_tasks t
            WHERE {where}
            ORDER BY
                CASE t.status
                    WHEN 'todo' THEN 1
                    WHEN 'drafting' THEN 2
                    WHEN 'review' THEN 3
                    WHEN 'posted' THEN 4
                    WHEN 'archived' THEN 5
                END,
                t.due_at ASC NULLS LAST
            LIMIT :limit
        """),
        params,
    )
    rows = result.all()

    return [
        ThirdPartyTaskResponse(
            id=r[0], client_id=r[1], platform=r[2], target_url=r[3],
            thread_title=r[4], brief=r[5], draft=r[6], assignee=r[7],
            status=r[8], posted_url=r[9], due_at=r[10],
            created_at=r[11], updated_at=r[12],
        )
        for r in rows
    ]


@router.post("/tasks", response_model=ThirdPartyTaskResponse, status_code=status.HTTP_201_CREATED)
async def create_third_party_task(
    client_id: UUID,
    body: ThirdPartyTaskCreate,
    user: AuthUser = Depends(require_roles(*OPS_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> ThirdPartyTaskResponse:
    """Create a new third-party task."""
    await has_client_access(client_id, user, db)

    if body.platform not in VALID_PLATFORMS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Invalid platform. Must be one of: {', '.join(sorted(VALID_PLATFORMS))}",
        )

    result = await db.execute(
        text("""
            INSERT INTO third_party_tasks
                (client_id, platform, target_url, thread_title, brief, assignee, due_at)
            VALUES
                (:cid, :platform, :target_url, :thread_title, :brief, :assignee,
                 CAST(:due_at AS timestamptz))
            RETURNING id, client_id, platform, target_url, thread_title, brief,
                      draft, assignee, status, posted_url,
                      CAST(due_at AS text), CAST(created_at AS text), CAST(updated_at AS text)
        """),
        {
            "cid": str(client_id),
            "platform": body.platform,
            "target_url": body.target_url,
            "thread_title": body.thread_title,
            "brief": body.brief,
            "assignee": str(body.assignee) if body.assignee else None,
            "due_at": body.due_at,
        },
    )
    r = result.one()
    await db.commit()

    logger.info("third_party_task_created", task_id=str(r[0]), platform=body.platform)

    return ThirdPartyTaskResponse(
        id=r[0], client_id=r[1], platform=r[2], target_url=r[3],
        thread_title=r[4], brief=r[5], draft=r[6], assignee=r[7],
        status=r[8], posted_url=r[9], due_at=r[10],
        created_at=r[11], updated_at=r[12],
    )


@router.get("/tasks/{task_id}", response_model=ThirdPartyTaskResponse)
async def get_third_party_task(
    client_id: UUID,
    task_id: UUID,
    user: AuthUser = Depends(require_roles(*OPS_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> ThirdPartyTaskResponse:
    """Get a single third-party task."""
    await has_client_access(client_id, user, db)

    result = await db.execute(
        text("""
            SELECT
                id, client_id, platform, target_url, thread_title,
                brief, draft, assignee, status, posted_url,
                CAST(due_at AS text), CAST(created_at AS text), CAST(updated_at AS text)
            FROM third_party_tasks
            WHERE id = :tid AND client_id = :cid
        """),
        {"tid": str(task_id), "cid": str(client_id)},
    )
    r = result.one_or_none()
    if not r:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")

    return ThirdPartyTaskResponse(
        id=r[0], client_id=r[1], platform=r[2], target_url=r[3],
        thread_title=r[4], brief=r[5], draft=r[6], assignee=r[7],
        status=r[8], posted_url=r[9], due_at=r[10],
        created_at=r[11], updated_at=r[12],
    )


@router.patch("/tasks/{task_id}", response_model=ThirdPartyTaskResponse)
async def update_third_party_task(
    client_id: UUID,
    task_id: UUID,
    body: ThirdPartyTaskUpdate,
    user: AuthUser = Depends(require_roles(*OPS_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> ThirdPartyTaskResponse:
    """Update a third-party task. Validates status transitions."""
    await has_client_access(client_id, user, db)

    if body.status and body.status not in VALID_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
        )

    # Validate posted status requires posted_url
    if body.status == "posted" and not body.posted_url:
        # Check existing posted_url
        existing = await db.execute(
            text("SELECT posted_url FROM third_party_tasks WHERE id = :tid AND client_id = :cid"),
            {"tid": str(task_id), "cid": str(client_id)},
        )
        row = existing.one_or_none()
        if not row or not row[0]:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Cannot mark as posted without a posted_url",
            )

    # Build dynamic SET clause
    updates: list[str] = ["updated_at = now()"]
    params: dict[str, Any] = {"tid": str(task_id), "cid": str(client_id)}
    field_map = {
        "target_url": body.target_url,
        "thread_title": body.thread_title,
        "brief": body.brief,
        "draft": body.draft,
        "status": body.status,
        "posted_url": body.posted_url,
    }
    for col, val in field_map.items():
        if val is not None:
            updates.append(f"{col} = :{col}")
            params[col] = val
    if body.assignee is not None:
        updates.append("assignee = :assignee")
        params["assignee"] = str(body.assignee)
    if body.due_at is not None:
        updates.append("due_at = CAST(:due_at AS timestamptz)")
        params["due_at"] = body.due_at

    set_clause = ", ".join(updates)
    result = await db.execute(
        text(f"""
            UPDATE third_party_tasks
            SET {set_clause}
            WHERE id = :tid AND client_id = :cid
            RETURNING id, client_id, platform, target_url, thread_title,
                      brief, draft, assignee, status, posted_url,
                      CAST(due_at AS text), CAST(created_at AS text), CAST(updated_at AS text)
        """),
        params,
    )
    r = result.one_or_none()
    if not r:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    await db.commit()

    return ThirdPartyTaskResponse(
        id=r[0], client_id=r[1], platform=r[2], target_url=r[3],
        thread_title=r[4], brief=r[5], draft=r[6], assignee=r[7],
        status=r[8], posted_url=r[9], due_at=r[10],
        created_at=r[11], updated_at=r[12],
    )


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_third_party_task(
    client_id: UUID,
    task_id: UUID,
    user: AuthUser = Depends(require_roles(*OPS_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a third-party task."""
    await has_client_access(client_id, user, db)

    result = await db.execute(
        text("DELETE FROM third_party_tasks WHERE id = :tid AND client_id = :cid RETURNING id"),
        {"tid": str(task_id), "cid": str(client_id)},
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    await db.commit()


@router.post("/tasks/{task_id}/generate-draft")
@router.post("/tasks/{task_id}/draft")
async def generate_task_draft(
    client_id: UUID,
    task_id: UUID,
    body: DraftRequest | None = None,
    user: AuthUser = Depends(require_roles(*OPS_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Generate an AI-assisted draft for a third-party task.

    Uses the brand profile proof points and task brief to generate a
    value-first, non-promotional response draft.
    """
    await has_client_access(client_id, user, db)

    # Get task and brand context
    task_result = await db.execute(
        text("""
            SELECT t.platform, t.target_url, t.thread_title, t.brief,
                   bp.voice, bp.positioning, bp.proof_points
            FROM third_party_tasks t
            LEFT JOIN brand_profiles bp ON bp.client_id = t.client_id
            WHERE t.id = :tid AND t.client_id = :cid
        """),
        {"tid": str(task_id), "cid": str(client_id)},
    )
    task = task_result.one_or_none()
    if not task:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")

    platform, target_url, thread_title, brief = task[0], task[1], task[2], task[3]
    voice, positioning, proof_points = task[4], task[5], task[6]

    # Build a grounded draft template (production would use LLM here)
    proof_list = proof_points if isinstance(proof_points, list) else []
    proof_text = ""
    if proof_list:
        proof_text = "\n".join(f"- {p}" if isinstance(p, str) else f"- {p.get('text', str(p))}" for p in proof_list[:3])

    draft = f"""## Response Draft for {platform.title()}

**Thread**: {thread_title or 'N/A'}
**URL**: {target_url or 'N/A'}

---

{brief or 'No brief provided — add context about the thread topic.'}

### Key Points to Cover:
{proof_text or '- (Add brand proof points in Brand Profile)'}

### Suggested Response:
Based on my experience, {positioning or 'our approach focuses on delivering measurable results'}. \
Here are some concrete data points that might be helpful:

{proof_text or '(Proof points will be auto-inserted from Brand Profile)'}

---
*Voice: {voice or 'Professional, helpful, non-promotional'}*
*Remember: Lead with value, cite specifics, avoid self-promotion.*
"""

    # Update task with draft and transition to drafting
    await db.execute(
        text("""
            UPDATE third_party_tasks
            SET draft = :draft,
                status = CASE WHEN status = 'todo' THEN 'drafting' ELSE status END,
                updated_at = now()
            WHERE id = :tid AND client_id = :cid
        """),
        {"draft": draft, "tid": str(task_id), "cid": str(client_id)},
    )
    await db.commit()

    logger.info("third_party_draft_generated", task_id=str(task_id), platform=platform)

    return {"task_id": str(task_id), "status": "drafting", "draft": draft}
