"""Content pipeline routes: briefs, drafts, versions, approvals, and lifecycle management.

Full implementation for Milestone 4 (Content Engine):
- Briefs: manual creation, gap-to-brief agent generation, detail, update.
- Drafts: 3-pass agent generator (strategist -> writer -> editor) with claim extraction.
- Items: list, get with version history, update with hard approval gate enforcement.
- Versions: list, get, manual version creation (human edits), diff between versions.
- Approvals: list with subject metadata, approve / reject / request changes.
- Pipeline: Kanban board aggregation across all content stages.
"""

from __future__ import annotations

import difflib
import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.agents.app.brief_generator import generate_brief_from_gap
from services.agents.app.draft_generator import generate_draft_from_brief
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

# Action mapping for approvals
ACTION_TO_STATUS = {
    "approve": "approved",
    "reject": "rejected",
    "request_changes": "changes_requested",
}

OPS_CONTENT_ROLES = (
    MemberRole.STRATEGIST,
    MemberRole.EDITOR,
    MemberRole.ADMIN,
    MemberRole.OWNER,
)


# ─── Pydantic Models ─────────────────────────────────────────────────────────

class BriefCreateRequest(BaseModel):
    title: str | None = None
    angle: str | None = None
    prompt_ids: list[UUID] = Field(default_factory=list)
    gap_ids: list[UUID] = Field(default_factory=list)
    outline: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    grounding_rules: dict[str, Any] = Field(default_factory=dict)


class BriefGenerateRequest(BaseModel):
    gap_id: UUID


class BriefUpdateRequest(BaseModel):
    title: str | None = None
    angle: str | None = None
    outline: list[dict[str, Any]] | None = None
    sources: list[str] | None = None
    grounding_rules: dict[str, Any] | None = None
    status: str | None = None


class DraftGenerateRequest(BaseModel):
    brief_id: UUID
    content_item_id: UUID | None = None


class ContentItemCreateRequest(BaseModel):
    brief_id: UUID | None = None
    type: str = "article"  # article | faq | comparison | landing
    slug: str | None = None
    title: str | None = None
    prompt_ids: list[UUID] = Field(default_factory=list)


class ContentItemUpdateRequest(BaseModel):
    slug: str | None = None
    type: str | None = None
    status: str | None = None
    publish_target_id: UUID | None = None


class VersionCreateRequest(BaseModel):
    title: str
    body_md: str
    body_html: str | None = None
    jsonld: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None
    claims: list[dict[str, Any]] = Field(default_factory=list)


class ApprovalActionRequest(BaseModel):
    action: str  # "approve" | "reject" | "request_changes"
    comment: str | None = None


# ─── Content Briefs ──────────────────────────────────────────────────────────

@router.get("/briefs")
async def list_briefs(
    client_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: str | None = Query(None, alias="status"),
    gap_id: UUID | None = Query(None),
) -> list[dict[str, Any]]:
    """List content briefs for a client."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    query = """
        SELECT cb.id, cb.client_id, cb.title, cb.angle, cb.outline, cb.sources,
               cb.status, cb.gap_ids, cb.grounding_rules, cb.agent_run_id,
               cb.created_by, cb.created_at,
               (SELECT count(*) FROM content_items ci WHERE ci.brief_id = cb.id) as item_count,
               (SELECT ap.status FROM approvals ap
                WHERE ap.subject_type = 'brief' AND ap.subject_id = cb.id
                ORDER BY ap.requested_at DESC LIMIT 1) as approval_status
        FROM content_briefs cb
        WHERE cb.client_id = :cid
    """
    params: dict[str, Any] = {"cid": str(client_id)}

    if status_filter:
        query += " AND cb.status = :st"
        params["st"] = status_filter
    if gap_id:
        query += " AND :gid = ANY(cb.gap_ids)"
        params["gid"] = str(gap_id)

    query += " ORDER BY cb.created_at DESC"

    result = await db.execute(text(query), params)
    rows = result.all()

    return [
        {
            "id": str(r.id),
            "client_id": str(r.client_id),
            "title": r.title,
            "angle": r.angle,
            "outline": r.outline or [],
            "sources": r.sources or [],
            "status": r.status or "draft",
            "gap_ids": [str(g) for g in (r.gap_ids or [])],
            "grounding_rules": r.grounding_rules or {},
            "agent_run_id": str(r.agent_run_id) if r.agent_run_id else None,
            "created_by": str(r.created_by) if r.created_by else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "item_count": int(r.item_count or 0),
            "approval_status": r.approval_status or "pending",
        }
        for r in rows
    ]


@router.post("/briefs", status_code=status.HTTP_201_CREATED)
async def create_brief(
    client_id: UUID,
    body: BriefCreateRequest,
    user: Annotated[AuthUser, Depends(require_roles(*OPS_CONTENT_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Manually create a content brief and register approval gate."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    res = await db.execute(
        text(
            """
            INSERT INTO content_briefs
                (client_id, title, angle, outline, sources, status, gap_ids, grounding_rules, created_by)
            VALUES
                (:cid, :title, :angle, CAST(:outline AS jsonb), CAST(:sources AS jsonb),
                 'draft', :gap_ids, CAST(:grounding AS jsonb), :uid)
            RETURNING id, created_at
            """
        ),
        {
            "cid": str(client_id),
            "title": body.title or "Untitled Brief",
            "angle": body.angle or "",
            "outline": json.dumps(body.outline),
            "sources": json.dumps(body.sources),
            "gap_ids": [str(g) for g in body.gap_ids],
            "grounding": json.dumps(body.grounding_rules),
            "uid": str(user.user_id),
        },
    )
    row = res.first()
    brief_id = row.id

    # Link target prompts
    for pid in body.prompt_ids:
        await db.execute(
            text(
                """
                INSERT INTO content_brief_prompts (brief_id, prompt_id)
                VALUES (:bid, :pid)
                ON CONFLICT DO NOTHING
                """
            ),
            {"bid": str(brief_id), "pid": str(pid)},
        )

    # Open approval record for ops review
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

    logger.info("brief_created_manually", brief_id=str(brief_id), client_id=str(client_id))
    return {"id": str(brief_id), "status": "draft", "created_at": row.created_at.isoformat()}


@router.post("/briefs/generate", status_code=status.HTTP_201_CREATED)
async def generate_brief(
    client_id: UUID,
    body: BriefGenerateRequest,
    user: Annotated[AuthUser, Depends(require_roles(*OPS_CONTENT_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Trigger the brief generator agent from a detected gap."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    try:
        result = await generate_brief_from_gap(str(client_id), str(body.gap_id))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error("brief_generator_failed", error=str(e), client_id=str(client_id), gap_id=str(body.gap_id))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Brief generation failed: {e}",
        )

    # Automatically open an approval gate for this newly generated brief
    brief_id = result["brief_id"]
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

    logger.info("brief_generated_via_api", brief_id=brief_id, gap_id=str(body.gap_id))
    return result


@router.get("/briefs/{brief_id}")
async def get_brief(
    client_id: UUID,
    brief_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Retrieve full brief details including linked prompts and approvals."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    res = await db.execute(
        text(
            """
            SELECT cb.id, cb.client_id, cb.title, cb.angle, cb.outline, cb.sources,
                   cb.status, cb.gap_ids, cb.grounding_rules, cb.agent_run_id,
                   cb.created_by, cb.created_at,
                   ap.id as approval_id, ap.status as approval_status, ap.comment as approval_comment
            FROM content_briefs cb
            LEFT JOIN approvals ap ON (ap.subject_type = 'brief' AND ap.subject_id = cb.id)
            WHERE cb.id = :bid AND cb.client_id = :cid
            ORDER BY ap.requested_at DESC
            LIMIT 1
            """
        ),
        {"bid": str(brief_id), "cid": str(client_id)},
    )
    row = res.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brief not found")

    # Linked prompts
    prompts_res = await db.execute(
        text(
            """
            SELECT p.id, p.text, p.funnel_stage, p.kind
            FROM content_brief_prompts cbp
            JOIN prompts p ON p.id = cbp.prompt_id
            WHERE cbp.brief_id = :bid
            """
        ),
        {"bid": str(brief_id)},
    )
    prompts = [
        {"id": str(p.id), "text": p.text, "funnel_stage": p.funnel_stage, "kind": p.kind}
        for p in prompts_res.all()
    ]

    return {
        "id": str(row.id),
        "client_id": str(row.client_id),
        "title": row.title,
        "angle": row.angle,
        "outline": row.outline or [],
        "sources": row.sources or [],
        "status": row.status or "draft",
        "gap_ids": [str(g) for g in (row.gap_ids or [])],
        "grounding_rules": row.grounding_rules or {},
        "agent_run_id": str(row.agent_run_id) if row.agent_run_id else None,
        "created_by": str(row.created_by) if row.created_by else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "approval_id": str(row.approval_id) if row.approval_id else None,
        "approval_status": row.approval_status or "pending",
        "approval_comment": row.approval_comment,
        "prompts": prompts,
    }


@router.patch("/briefs/{brief_id}")
async def update_brief(
    client_id: UUID,
    brief_id: UUID,
    body: BriefUpdateRequest,
    user: Annotated[AuthUser, Depends(require_roles(*OPS_CONTENT_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Update brief fields."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    updates = []
    params: dict[str, Any] = {"bid": str(brief_id), "cid": str(client_id)}

    if body.title is not None:
        updates.append("title = :title")
        params["title"] = body.title
    if body.angle is not None:
        updates.append("angle = :angle")
        params["angle"] = body.angle
    if body.outline is not None:
        updates.append("outline = CAST(:outline AS jsonb)")
        params["outline"] = json.dumps(body.outline)
    if body.sources is not None:
        updates.append("sources = CAST(:sources AS jsonb)")
        params["sources"] = json.dumps(body.sources)
    if body.grounding_rules is not None:
        updates.append("grounding_rules = CAST(:grounding AS jsonb)")
        params["grounding"] = json.dumps(body.grounding_rules)
    if body.status is not None:
        updates.append("status = :status")
        params["status"] = body.status

    if not updates:
        return {"status": "no_changes"}

    query = f"""
        UPDATE content_briefs
        SET {", ".join(updates)}
        WHERE id = :bid AND client_id = :cid
        RETURNING id
    """
    res = await db.execute(text(query), params)
    if not res.first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brief not found")
    await db.commit()

    return {"status": "updated", "id": str(brief_id)}


# ─── Draft Generator (3-Pass Agent) ──────────────────────────────────────────

@router.post("/drafts/generate", status_code=status.HTTP_201_CREATED)
async def generate_draft(
    client_id: UUID,
    body: DraftGenerateRequest,
    user: Annotated[AuthUser, Depends(require_roles(*OPS_CONTENT_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Run the 3-pass draft generator agent (strategist -> writer -> editor)."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    try:
        result = await generate_draft_from_brief(
            str(client_id),
            str(body.brief_id),
            str(body.content_item_id) if body.content_item_id else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error("draft_generator_failed", error=str(e), client_id=str(client_id), brief_id=str(body.brief_id))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Draft generation failed: {e}",
        )

    logger.info(
        "draft_generated_via_api",
        content_item_id=result["content_item_id"],
        version_id=result["version_id"],
        brief_id=str(body.brief_id),
    )
    return result


# ─── Content Items & Versions ────────────────────────────────────────────────

@router.get("/items")
async def list_content_items(
    client_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: str | None = Query(None, alias="status"),
    type_filter: str | None = Query(None, alias="type"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    """List content items with current version, brief info, and approval status."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    query = """
        SELECT ci.id, ci.client_id, ci.brief_id, ci.type, ci.slug, ci.status,
               ci.current_version_id, ci.publish_target_id, ci.published_url,
               ci.published_at, ci.decay_score, ci.created_at,
               cb.title as brief_title,
               cv.title as version_title, cv.version_no, cv.word_count,
               cv.reading_time_min, cv.claims,
               ap.id as approval_id, ap.status as approval_status,
               pt.kind as target_kind
        FROM content_items ci
        LEFT JOIN content_briefs cb ON cb.id = ci.brief_id
        LEFT JOIN content_versions cv ON cv.id = ci.current_version_id
        LEFT JOIN approvals ap ON (ap.subject_type = 'version' AND ap.subject_id = ci.current_version_id)
        LEFT JOIN publish_targets pt ON pt.id = ci.publish_target_id
        WHERE ci.client_id = :cid
    """
    params: dict[str, Any] = {"cid": str(client_id), "limit": limit, "offset": offset}

    if status_filter:
        query += " AND ci.status = CAST(:st AS content_status_t)"
        params["st"] = status_filter
    if type_filter:
        query += " AND ci.type = :tp"
        params["tp"] = type_filter

    query += " ORDER BY ci.created_at DESC LIMIT :limit OFFSET :offset"

    result = await db.execute(text(query), params)
    rows = result.all()

    return [
        {
            "id": str(r.id),
            "client_id": str(r.client_id),
            "brief_id": str(r.brief_id) if r.brief_id else None,
            "brief_title": r.brief_title,
            "type": r.type,
            "slug": r.slug,
            "status": r.status,
            "title": r.version_title or r.brief_title or "Untitled",
            "current_version_id": str(r.current_version_id) if r.current_version_id else None,
            "version_no": r.version_no,
            "word_count": r.word_count,
            "reading_time_min": float(r.reading_time_min) if r.reading_time_min else None,
            "claims_count": len(r.claims or []) if r.claims else 0,
            "approval_id": str(r.approval_id) if r.approval_id else None,
            "approval_status": r.approval_status or "pending",
            "publish_target_kind": r.target_kind,
            "published_url": r.published_url,
            "published_at": r.published_at.isoformat() if r.published_at else None,
            "decay_score": float(r.decay_score) if r.decay_score else 0.0,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.post("/items", status_code=status.HTTP_201_CREATED)
async def create_content_item(
    client_id: UUID,
    body: ContentItemCreateRequest,
    user: Annotated[AuthUser, Depends(require_roles(*OPS_CONTENT_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Create a new content item container (idea or briefed state)."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    slug = body.slug
    if not slug and body.title:
        slug = body.title.lower().replace(" ", "-")[:60].strip("-")

    initial_status = "briefed" if body.brief_id else "idea"

    res = await db.execute(
        text(
            """
            INSERT INTO content_items (client_id, brief_id, type, slug, status)
            VALUES (:cid, :bid, :tp, :slug, CAST(:st AS content_status_t))
            RETURNING id, created_at
            """
        ),
        {
            "cid": str(client_id),
            "bid": str(body.brief_id) if body.brief_id else None,
            "tp": body.type,
            "slug": slug,
            "st": initial_status,
        },
    )
    row = res.first()
    item_id = row.id

    for pid in body.prompt_ids:
        await db.execute(
            text(
                """
                INSERT INTO content_prompt_map (content_item_id, prompt_id, is_primary)
                VALUES (:iid, :pid, true)
                ON CONFLICT DO NOTHING
                """
            ),
            {"iid": str(item_id), "pid": str(pid)},
        )

    await db.commit()
    logger.info("content_item_created", item_id=str(item_id), client_id=str(client_id))

    return {
        "id": str(item_id),
        "client_id": str(client_id),
        "status": initial_status,
        "created_at": row.created_at.isoformat(),
    }


@router.get("/items/{item_id}")
async def get_content_item(
    client_id: UUID,
    item_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Retrieve full content item details, current version, version history, and prompts."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    res = await db.execute(
        text(
            """
            SELECT ci.id, ci.client_id, ci.brief_id, ci.type, ci.slug, ci.status,
                   ci.current_version_id, ci.publish_target_id, ci.published_url,
                   ci.published_at, ci.decay_score, ci.created_at,
                   cb.title as brief_title, cb.angle as brief_angle, cb.outline as brief_outline,
                   cb.sources as brief_sources,
                   cv.id as v_id, cv.version_no, cv.title as v_title, cv.body_md, cv.body_html,
                   cv.jsonld, cv.meta, cv.author_kind, cv.claims, cv.word_count,
                   cv.reading_time_min, cv.created_at as v_created_at,
                   ap.id as approval_id, ap.status as approval_status, ap.comment as approval_comment
            FROM content_items ci
            LEFT JOIN content_briefs cb ON cb.id = ci.brief_id
            LEFT JOIN content_versions cv ON cv.id = ci.current_version_id
            LEFT JOIN approvals ap ON (ap.subject_type = 'version' AND ap.subject_id = ci.current_version_id)
            WHERE ci.id = :iid AND ci.client_id = :cid
            ORDER BY ap.requested_at DESC
            LIMIT 1
            """
        ),
        {"iid": str(item_id), "cid": str(client_id)},
    )
    row = res.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content item not found")

    # Fetch version history
    versions_res = await db.execute(
        text(
            """
            SELECT id, version_no, title, author_kind, word_count, reading_time_min, created_at
            FROM content_versions
            WHERE content_item_id = :iid
            ORDER BY version_no DESC
            """
        ),
        {"iid": str(item_id)},
    )
    versions = [
        {
            "id": str(v.id),
            "version_no": v.version_no,
            "title": v.title,
            "author_kind": v.author_kind,
            "word_count": v.word_count,
            "reading_time_min": float(v.reading_time_min) if v.reading_time_min else None,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in versions_res.all()
    ]

    # Fetch mapped prompts
    prompts_res = await db.execute(
        text(
            """
            SELECT p.id, p.text, p.funnel_stage, p.kind, cpm.is_primary
            FROM content_prompt_map cpm
            JOIN prompts p ON p.id = cpm.prompt_id
            WHERE cpm.content_item_id = :iid
            """
        ),
        {"iid": str(item_id)},
    )
    prompts = [
        {"id": str(p.id), "text": p.text, "funnel_stage": p.funnel_stage, "is_primary": p.is_primary}
        for p in prompts_res.all()
    ]

    # Fetch publications
    pubs_res = await db.execute(
        text(
            """
            SELECT id, version_id, target_id, external_id, url, status, error, published_at
            FROM publications
            WHERE content_item_id = :iid
            ORDER BY published_at DESC NULLS LAST
            """
        ),
        {"iid": str(item_id)},
    )
    publications = [
        {
            "id": str(pb.id),
            "version_id": str(pb.version_id) if pb.version_id else None,
            "target_id": str(pb.target_id) if pb.target_id else None,
            "external_id": pb.external_id,
            "url": pb.url,
            "status": pb.status,
            "error": pb.error,
            "published_at": pb.published_at.isoformat() if pb.published_at else None,
        }
        for pb in pubs_res.all()
    ]

    current_version = None
    if row.current_version_id:
        current_version = {
            "id": str(row.v_id),
            "version_no": row.version_no,
            "title": row.v_title,
            "body_md": row.body_md,
            "body_html": row.body_html,
            "jsonld": row.jsonld or {},
            "meta": row.meta or {},
            "author_kind": row.author_kind,
            "claims": row.claims or [],
            "word_count": row.word_count,
            "reading_time_min": float(row.reading_time_min) if row.reading_time_min else None,
            "created_at": row.v_created_at.isoformat() if row.v_created_at else None,
            "approval_id": str(row.approval_id) if row.approval_id else None,
            "approval_status": row.approval_status or "pending",
            "approval_comment": row.approval_comment,
        }

    brief = None
    if row.brief_id:
        brief = {
            "id": str(row.brief_id),
            "title": row.brief_title,
            "angle": row.brief_angle,
            "outline": row.brief_outline or [],
            "sources": row.brief_sources or [],
        }

    return {
        "id": str(row.id),
        "client_id": str(row.client_id),
        "brief_id": str(row.brief_id) if row.brief_id else None,
        "brief": brief,
        "type": row.type,
        "slug": row.slug,
        "status": row.status,
        "current_version_id": str(row.current_version_id) if row.current_version_id else None,
        "current_version": current_version,
        "versions": versions,
        "prompts": prompts,
        "publications": publications,
        "publish_target_id": str(row.publish_target_id) if row.publish_target_id else None,
        "published_url": row.published_url,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "decay_score": float(row.decay_score) if row.decay_score else 0.0,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.patch("/items/{item_id}")
async def update_content_item(
    client_id: UUID,
    item_id: UUID,
    body: ContentItemUpdateRequest,
    user: Annotated[AuthUser, Depends(require_roles(*OPS_CONTENT_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Update content item fields with hard approval gate enforcement."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Fetch current item state to verify gates
    cur = await db.execute(
        text("SELECT id, status, current_version_id FROM content_items WHERE id = :iid AND client_id = :cid"),
        {"iid": str(item_id), "cid": str(client_id)},
    )
    current_item = cur.first()
    if not current_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content item not found")

    # ─── HARD APPROVAL GATE ENFORCEMENT ───────────────────────────────────────
    # Under PRD §1.4 & §2, content CANNOT transition to approved, scheduled, or
    # published without an explicitly approved approval record for the current version.
    if body.status in ("approved", "scheduled", "published"):
        if not current_item.current_version_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Approval gate not satisfied: Item has no generated draft version to approve.",
            )

        appr_check = await db.execute(
            text(
                """
                SELECT id, status FROM approvals
                WHERE client_id = :cid AND subject_type = 'version' AND subject_id = :vid
                ORDER BY requested_at DESC LIMIT 1
                """
            ),
            {"cid": str(client_id), "vid": str(current_item.current_version_id)},
        )
        appr_row = appr_check.first()
        if not appr_row or appr_row.status != "approved":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Approval gate violation: Current draft (version {current_item.current_version_id}) "
                    f"has approval status '{appr_row.status if appr_row else 'none'}'. "
                    "An approved signoff from an authorized reviewer is strictly required."
                ),
            )

    updates = []
    params: dict[str, Any] = {"iid": str(item_id), "cid": str(client_id)}

    if body.slug is not None:
        updates.append("slug = :slug")
        params["slug"] = body.slug
    if body.type is not None:
        updates.append("type = :tp")
        params["tp"] = body.type
    if body.publish_target_id is not None:
        updates.append("publish_target_id = :ptid")
        params["ptid"] = str(body.publish_target_id)
    if body.status is not None:
        updates.append("status = CAST(:st AS content_status_t)")
        params["st"] = body.status
        if body.status == "published":
            updates.append("published_at = COALESCE(published_at, now())")

    if not updates:
        return {"status": "no_changes"}

    query = f"""
        UPDATE content_items
        SET {", ".join(updates)}
        WHERE id = :iid AND client_id = :cid
        RETURNING id, status
    """
    res = await db.execute(text(query), params)
    row = res.first()
    await db.commit()

    logger.info("content_item_updated", item_id=str(item_id), status=row.status)
    return {"id": str(item_id), "status": row.status}


# ─── Versions & Diffing ──────────────────────────────────────────────────────

@router.get("/items/{item_id}/versions")
async def list_versions(
    client_id: UUID,
    item_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict[str, Any]]:
    """List all versions of a content item."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    res = await db.execute(
        text(
            """
            SELECT cv.id, cv.version_no, cv.title, cv.author_kind, cv.word_count,
                   cv.reading_time_min, cv.created_at,
                   ap.status as approval_status
            FROM content_versions cv
            LEFT JOIN approvals ap ON (ap.subject_type = 'version' AND ap.subject_id = cv.id)
            WHERE cv.content_item_id = :iid AND cv.client_id = :cid
            ORDER BY cv.version_no DESC
            """
        ),
        {"iid": str(item_id), "cid": str(client_id)},
    )
    return [
        {
            "id": str(r.id),
            "version_no": r.version_no,
            "title": r.title,
            "author_kind": r.author_kind,
            "word_count": r.word_count,
            "reading_time_min": float(r.reading_time_min) if r.reading_time_min else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "approval_status": r.approval_status or "pending",
        }
        for r in res.all()
    ]


@router.get("/items/{item_id}/versions/{version_id}")
async def get_version(
    client_id: UUID,
    item_id: UUID,
    version_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Retrieve full text and metadata for a specific version."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    res = await db.execute(
        text(
            """
            SELECT cv.id, cv.content_item_id, cv.version_no, cv.title, cv.body_md,
                   cv.body_html, cv.jsonld, cv.meta, cv.author_kind, cv.claims,
                   cv.word_count, cv.reading_time_min, cv.created_at,
                   ap.id as approval_id, ap.status as approval_status, ap.comment as approval_comment
            FROM content_versions cv
            LEFT JOIN approvals ap ON (ap.subject_type = 'version' AND ap.subject_id = cv.id)
            WHERE cv.id = :vid AND cv.content_item_id = :iid AND cv.client_id = :cid
            ORDER BY ap.requested_at DESC LIMIT 1
            """
        ),
        {"vid": str(version_id), "iid": str(item_id), "cid": str(client_id)},
    )
    row = res.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    return {
        "id": str(row.id),
        "content_item_id": str(row.content_item_id),
        "version_no": row.version_no,
        "title": row.title,
        "body_md": row.body_md,
        "body_html": row.body_html,
        "jsonld": row.jsonld or {},
        "meta": row.meta or {},
        "author_kind": row.author_kind,
        "claims": row.claims or [],
        "word_count": row.word_count,
        "reading_time_min": float(row.reading_time_min) if row.reading_time_min else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "approval_id": str(row.approval_id) if row.approval_id else None,
        "approval_status": row.approval_status or "pending",
        "approval_comment": row.approval_comment,
    }


@router.post("/items/{item_id}/versions", status_code=status.HTTP_201_CREATED)
async def create_version(
    client_id: UUID,
    item_id: UUID,
    body: VersionCreateRequest,
    user: Annotated[AuthUser, Depends(require_roles(*OPS_CONTENT_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Human editor revision: creates a new version and re-opens approval gate."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Get next version number
    ver_res = await db.execute(
        text(
            """
            SELECT COALESCE(MAX(version_no), 0) + 1 AS next_ver
            FROM content_versions
            WHERE content_item_id = :iid
            """
        ),
        {"iid": str(item_id)},
    )
    next_ver = ver_res.scalar() or 1

    words = len(body.body_md.split())
    reading_time = round(words / 250, 1)

    ins_res = await db.execute(
        text(
            """
            INSERT INTO content_versions
                (content_item_id, client_id, version_no, title, body_md, body_html,
                 jsonld, meta, author_kind, claims, word_count, reading_time_min)
            VALUES
                (:iid, :cid, :vno, :title, :md, :html,
                 CAST(:jsonld AS jsonb), CAST(:meta AS jsonb), 'human',
                 CAST(:claims AS jsonb), :wc, :rt)
            RETURNING id, created_at
            """
        ),
        {
            "iid": str(item_id),
            "cid": str(client_id),
            "vno": next_ver,
            "title": body.title,
            "md": body.body_md,
            "html": body.body_html,
            "jsonld": json.dumps(body.jsonld) if body.jsonld else None,
            "meta": json.dumps(body.meta) if body.meta else None,
            "claims": json.dumps(body.claims),
            "wc": words,
            "rt": reading_time,
        },
    )
    vrow = ins_res.first()
    version_id = vrow.id

    # Update item pointer to new version and reset status to in_review
    await db.execute(
        text(
            """
            UPDATE content_items
            SET current_version_id = :vid, status = 'in_review'
            WHERE id = :iid AND client_id = :cid
            """
        ),
        {"vid": str(version_id), "iid": str(item_id), "cid": str(client_id)},
    )

    # Open approval gate for the newly edited version
    await db.execute(
        text(
            """
            INSERT INTO approvals (client_id, subject_type, subject_id, status, requested_by)
            VALUES (:cid, 'version', :vid, 'pending', :uid)
            """
        ),
        {"cid": str(client_id), "vid": str(version_id), "uid": str(user.user_id)},
    )
    await db.commit()

    logger.info("version_created_manually", item_id=str(item_id), version_no=next_ver, version_id=str(version_id))
    return {
        "id": str(version_id),
        "version_no": next_ver,
        "word_count": words,
        "reading_time_min": reading_time,
        "status": "in_review",
    }


@router.get("/items/{item_id}/diff")
async def diff_versions(
    client_id: UUID,
    item_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    v1: int = Query(..., description="First version number"),
    v2: int = Query(..., description="Second version number"),
) -> dict[str, Any]:
    """Calculate unified line diff between two versions of an item."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    res = await db.execute(
        text(
            """
            SELECT version_no, title, body_md, word_count, created_at
            FROM content_versions
            WHERE content_item_id = :iid AND client_id = :cid AND version_no IN (:v1, :v2)
            """
        ),
        {"iid": str(item_id), "cid": str(client_id), "v1": v1, "v2": v2},
    )
    rows = {r.version_no: r for r in res.all()}
    if v1 not in rows or v2 not in rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="One or both versions not found")

    text1 = (rows[v1].body_md or "").splitlines(keepends=True)
    text2 = (rows[v2].body_md or "").splitlines(keepends=True)

    diff = list(
        difflib.unified_diff(
            text1,
            text2,
            fromfile=f"v{v1} ({rows[v1].title})",
            tofile=f"v{v2} ({rows[v2].title})",
            lineterm="",
        )
    )

    return {
        "v1": v1,
        "v2": v2,
        "diff": diff,
        "word_count_change": (rows[v2].word_count or 0) - (rows[v1].word_count or 0),
    }


# ─── Approvals & Gates ───────────────────────────────────────────────────────

@router.get("/approvals")
async def list_approvals(
    client_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: str | None = Query(None, alias="status"),
) -> list[dict[str, Any]]:
    """List approvals for a client with detailed subject context."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    query = """
        SELECT ap.id, ap.subject_type, ap.subject_id, ap.status, ap.requested_by,
               ap.reviewer_id, ap.comment, ap.requested_at, ap.decided_at,
               cb.title as brief_title, cb.angle as brief_angle,
               cv.title as version_title, cv.version_no, cv.word_count,
               ci.id as item_id, ci.type as item_type, ci.status as item_status
        FROM approvals ap
        LEFT JOIN content_briefs cb ON (ap.subject_type = 'brief' AND cb.id = ap.subject_id)
        LEFT JOIN content_versions cv ON (ap.subject_type = 'version' AND cv.id = ap.subject_id)
        LEFT JOIN content_items ci ON (ap.subject_type = 'version' AND ci.id = cv.content_item_id)
        WHERE ap.client_id = :cid
    """
    params: dict[str, Any] = {"cid": str(client_id)}

    if status_filter:
        query += " AND ap.status = CAST(:st AS approval_status_t)"
        params["st"] = status_filter

    query += " ORDER BY ap.requested_at DESC"

    result = await db.execute(text(query), params)
    rows = result.all()

    items = []
    for r in rows:
        title = r.version_title or r.brief_title or "Untitled Approval Subject"
        items.append(
            {
                "id": str(r.id),
                "subject_type": r.subject_type,
                "subject_id": str(r.subject_id),
                "title": title,
                "subtitle": r.brief_angle or (f"v{r.version_no} ({r.word_count} words)" if r.version_no else None),
                "item_id": str(r.item_id) if r.item_id else None,
                "item_status": r.item_status,
                "status": r.status,
                "comment": r.comment,
                "requested_by": str(r.requested_by) if r.requested_by else None,
                "reviewer_id": str(r.reviewer_id) if r.reviewer_id else None,
                "requested_at": r.requested_at.isoformat() if r.requested_at else None,
                "decided_at": r.decided_at.isoformat() if r.decided_at else None,
            }
        )

    return items


@router.post("/approvals/{approval_id}/action")
async def action_approval(
    client_id: UUID,
    approval_id: UUID,
    body: ApprovalActionRequest,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Approve, reject, or request changes on an approval gate."""
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
            SET status = CAST(:status AS approval_status_t),
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

    subject_type = row.subject_type
    subject_id = row.subject_id

    # Automatically synchronize subject status
    if subject_type == "version":
        # Find corresponding content item
        ci_res = await db.execute(
            text("SELECT content_item_id FROM content_versions WHERE id = :vid"),
            {"vid": str(subject_id)},
        )
        ci_row = ci_res.first()
        if ci_row:
            if new_status == "approved":
                # Advance item to approved
                await db.execute(
                    text("UPDATE content_items SET status = 'approved' WHERE id = :iid"),
                    {"iid": str(ci_row.content_item_id)},
                )
            elif new_status == "changes_requested":
                await db.execute(
                    text("UPDATE content_items SET status = 'in_review' WHERE id = :iid"),
                    {"iid": str(ci_row.content_item_id)},
                )
    elif subject_type == "brief":
        if new_status == "approved":
            await db.execute(
                text("UPDATE content_briefs SET status = 'approved' WHERE id = :bid"),
                {"bid": str(subject_id)},
            )

    await db.commit()

    logger.info("approval_actioned", approval_id=str(approval_id), action=body.action, new_status=new_status)
    return {"status": "success", "new_status": new_status, "subject_type": subject_type, "subject_id": str(subject_id)}


# ─── Pipeline Kanban Aggregator ──────────────────────────────────────────────

@router.get("/pipeline")
async def get_pipeline_kanban(
    client_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Kanban aggregation for all stages of the content engine."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # 1. Detected gaps (candidates for briefing)
    gaps_res = await db.execute(
        text(
            """
            SELECT g.id, g.gap_type, g.details, g.status, p.text as prompt_text
            FROM gaps g
            JOIN prompts p ON p.id = g.prompt_id
            WHERE g.client_id = :cid AND g.status = 'open'
            ORDER BY g.detected_at DESC LIMIT 15
            """
        ),
        {"cid": str(client_id)},
    )
    gap_items = [
        {
            "id": str(r.id),
            "type": "Gap",
            "title": r.prompt_text or f"Gap ({r.gap_type})",
            "subtitle": (r.details or {}).get("reason") or (r.details or {}).get("competitor_domain") or f"Type: {r.gap_type}",
            "gap_id": str(r.id),
            "status": r.status,
        }
        for r in gaps_res.all()
    ]

    # 2. Briefs
    briefs_res = await db.execute(
        text(
            """
            SELECT cb.id, cb.title, cb.angle, cb.status,
                   ap.status as approval_status, ap.id as approval_id
            FROM content_briefs cb
            LEFT JOIN approvals ap ON (ap.subject_type = 'brief' AND ap.subject_id = cb.id)
            WHERE cb.client_id = :cid
            ORDER BY cb.created_at DESC LIMIT 30
            """
        ),
        {"cid": str(client_id)},
    )
    brief_items = []
    ops_review_briefs = []
    for b in briefs_res.all():
        card = {
            "id": str(b.id),
            "brief_id": str(b.id),
            "type": "Brief",
            "title": b.title or "Untitled Brief",
            "subtitle": b.angle,
            "status": b.status or "draft",
            "approval_id": str(b.approval_id) if b.approval_id else None,
            "approval_status": b.approval_status or "pending",
        }
        if b.approval_status == "pending":
            ops_review_briefs.append(card)
        else:
            brief_items.append(card)

    # 3. Content items categorized by status
    items_res = await db.execute(
        text(
            """
            SELECT ci.id, ci.type, ci.status, ci.slug, ci.published_url, ci.decay_score,
                   cv.id as version_id, cv.title as version_title, cv.version_no,
                   cv.word_count, cv.claims,
                   cb.id as brief_id, cb.title as brief_title,
                   ap.id as approval_id, ap.status as approval_status
            FROM content_items ci
            LEFT JOIN content_briefs cb ON cb.id = ci.brief_id
            LEFT JOIN content_versions cv ON cv.id = ci.current_version_id
            LEFT JOIN approvals ap ON (ap.subject_type = 'version' AND ap.subject_id = ci.current_version_id)
            WHERE ci.client_id = :cid
            ORDER BY ci.created_at DESC
            """
        ),
        {"cid": str(client_id)},
    )

    drafting_items = []
    ops_review_drafts = []
    client_review_items = []
    approved_items = []
    published_items = []
    refresh_items = []

    for ci in items_res.all():
        card = {
            "id": str(ci.id),
            "item_id": str(ci.id),
            "type": "Draft",
            "title": ci.version_title or ci.brief_title or "Untitled Item",
            "subtitle": f"v{ci.version_no or 1} • {ci.word_count or 0} words • {len(ci.claims or [])} claims",
            "status": ci.status,
            "brief_id": str(ci.brief_id) if ci.brief_id else None,
            "current_version_id": str(ci.version_id) if ci.version_id else None,
            "approval_id": str(ci.approval_id) if ci.approval_id else None,
            "approval_status": ci.approval_status,
            "published_url": ci.published_url,
            "decay_score": float(ci.decay_score) if ci.decay_score else 0.0,
        }

        if ci.status == "drafting":
            drafting_items.append(card)
        elif ci.status == "in_review":
            ops_review_drafts.append(card)
        elif ci.status == "client_review":
            client_review_items.append(card)
        elif ci.status in ("approved", "scheduled"):
            approved_items.append(card)
        elif ci.status == "published":
            published_items.append(card)
        elif ci.status == "refresh_needed":
            refresh_items.append(card)

    return {
        "columns": [
            {"id": "gap_detected", "name": "Gap Detected", "count": len(gap_items), "items": gap_items},
            {"id": "brief_gen", "name": "Briefs (Draft/Approved)", "count": len(brief_items), "items": brief_items},
            {"id": "ops_review_brief", "name": "Ops Review (Brief)", "count": len(ops_review_briefs), "items": ops_review_briefs},
            {"id": "draft_gen", "name": "Drafting", "count": len(drafting_items), "items": drafting_items},
            {"id": "ops_review_draft", "name": "Ops Review (Draft)", "count": len(ops_review_drafts), "items": ops_review_drafts},
            {"id": "client_review", "name": "Client Review", "count": len(client_review_items), "items": client_review_items},
            {"id": "approved", "name": "Approved & Ready", "count": len(approved_items), "items": approved_items},
            {"id": "published", "name": "Published", "count": len(published_items), "items": published_items},
            {"id": "refresh_needed", "name": "Refresh Needed", "count": len(refresh_items), "items": refresh_items},
        ]
    }
