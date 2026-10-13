"""Role-gated Client Portal API: authenticated dashboard, approvals, content, and brand settings."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from services.api.app.audit_trail import record_audit_event
from services.api.app.auth import (
    INTERNAL_ROLES,
    PORTAL_ROLES,
    AuthUser,
    MemberRole,
    get_current_user,
)
from services.api.app.db import get_db
from services.api.app.logging import get_logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

router = APIRouter(prefix="/portal", tags=["portal"])


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Schemas
# ─────────────────────────────────────────────────────────────────────────────

class ClientPortalRef(BaseModel):
    id: UUID
    name: str
    primary_domain: str
    industry: str | None = None
    status: str


class PortalMeResponse(BaseModel):
    user_id: UUID
    email: str
    role: str
    active_client_id: UUID | None = None
    active_client_name: str | None = None
    is_preview: bool
    clients: list[ClientPortalRef]


class RecentMentionItem(BaseModel):
    engine: str
    query_text: str
    snippet: str
    collected_at: str | None = None


class PortalDashboardResponse(BaseModel):
    client_id: UUID
    client_name: str
    primary_domain: str
    visibility_pct: float
    citation_share_pct: float
    content_shipped: int
    pending_actions: int
    recent_mentions: list[RecentMentionItem]


class ApprovalSubjectPreview(BaseModel):
    excerpt: str | None = None
    word_count: int | None = None
    angle: str | None = None
    url: str | None = None
    diff_summary: str | None = None


class PortalApprovalItem(BaseModel):
    id: UUID
    subject_type: str
    subject_id: UUID
    status: str
    title: str
    subtitle: str | None = None
    requested_at: str
    comment: str | None = None
    preview: ApprovalSubjectPreview = Field(default_factory=ApprovalSubjectPreview)


class ApprovalDecideRequest(BaseModel):
    decision: str  # approved | rejected | changes_requested
    comment: str | None = None


class PortalContentItem(BaseModel):
    id: UUID
    slug: str | None = None
    type: str
    status: str
    title: str
    word_count: int
    published_url: str | None = None
    published_at: str | None = None
    created_at: str


class PortalPublishTargetItem(BaseModel):
    kind: str
    status: str


class PortalSettingsResponse(BaseModel):
    client_id: UUID
    name: str
    primary_domain: str
    industry: str | None = None
    status: str
    voice: str | None = None
    positioning: str | None = None
    products_count: int
    proof_points_count: int
    banned_claims_count: int
    publish_targets: list[PortalPublishTargetItem]
    competitor_domains: list[str]


# ─────────────────────────────────────────────────────────────────────────────
# Role & Access Resolution Helper
# ─────────────────────────────────────────────────────────────────────────────

async def _resolve_portal_access(
    user: AuthUser,
    client_id: UUID | None,
    db: AsyncSession,
) -> tuple[UUID, bool]:
    """Validate user's role and return (effective_client_id, is_preview).

    - Portal roles (client_approver, client_viewer) are strictly restricted to assigned client_ids.
    - Internal roles (owner, admin, strategist, editor) preview as a client.
    """
    if user.role not in PORTAL_ROLES and user.role not in INTERNAL_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role {user.role} is not permitted to access the client portal",
        )

    is_preview = user.role in INTERNAL_ROLES

    if is_preview:
        if client_id:
            c_res = await db.execute(
                text("SELECT id FROM clients WHERE id = :cid AND (org_id = :oid OR :oid IS NULL)"),
                {"cid": str(client_id), "oid": str(user.org_id) if user.org_id else None},
            )
            if not c_res.first():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Client not accessible in your organization",
                )
            return client_id, True
        else:
            c_res = await db.execute(
                text("SELECT id FROM clients WHERE org_id = :oid ORDER BY name LIMIT 1"),
                {"oid": str(user.org_id) if user.org_id else None},
            )
            row = c_res.first()
            if not row:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No clients found")
            return row.id, True
    else:
        # Regular client portal user
        if not user.client_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No clients assigned to your account",
            )
        if client_id:
            if client_id not in user.client_ids:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied for this client",
                )
            return client_id, False
        return user.client_ids[0], False


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/me", response_model=PortalMeResponse)
async def get_portal_me(
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    client_id: UUID | None = None,
) -> PortalMeResponse:
    """Return identity, assigned clients, active client scope, and preview state."""
    if user.role not in PORTAL_ROLES and user.role not in INTERNAL_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have portal access permissions",
        )

    is_preview = user.role in INTERNAL_ROLES
    clients_list: list[ClientPortalRef] = []

    if is_preview:
        q = text(
            """
            SELECT id, name, primary_domain, industry, status
            FROM clients
            WHERE (org_id = :oid OR :oid IS NULL)
            ORDER BY name
            """
        )
        c_res = await db.execute(q, {"oid": str(user.org_id) if user.org_id else None})
    else:
        q = text(
            """
            SELECT id, name, primary_domain, industry, status
            FROM clients
            WHERE id = ANY(:cids)
            ORDER BY name
            """
        )
        c_res = await db.execute(q, {"cids": [str(c) for c in user.client_ids]})

    for r in c_res.all():
        clients_list.append(
            ClientPortalRef(
                id=r.id,
                name=r.name,
                primary_domain=r.primary_domain,
                industry=r.industry,
                status=r.status,
            )
        )

    active_cid: UUID | None = None
    active_name: str | None = None
    if clients_list:
        if client_id and any(c.id == client_id for c in clients_list):
            active_cid = client_id
        else:
            active_cid = clients_list[0].id
        active_match = next((c for c in clients_list if c.id == active_cid), None)
        active_name = active_match.name if active_match else None

    return PortalMeResponse(
        user_id=user.user_id,
        email=user.email,
        role=user.role.value if user.role else "unknown",
        active_client_id=active_cid,
        active_client_name=active_name,
        is_preview=is_preview,
        clients=clients_list,
    )


@router.get("/dashboard", response_model=PortalDashboardResponse)
async def get_portal_dashboard(
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    client_id: UUID | None = None,
) -> PortalDashboardResponse:
    """Client-facing dashboard: 30d visibility %, citation share, shipped pieces, pending actions, and quotes."""
    eff_cid, _ = await _resolve_portal_access(user, client_id, db)

    # 1. Client basic info
    c_res = await db.execute(
        text("SELECT name, primary_domain FROM clients WHERE id = :cid"),
        {"cid": str(eff_cid)},
    )
    c_row = c_res.first()
    if not c_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    client_name = c_row.name
    primary_domain = c_row.primary_domain

    # 2. Daily metrics rollup (last 30 days)
    m_res = await db.execute(
        text(
            """
            SELECT
                AVG(mention_rate) as avg_mention,
                AVG(citation_share) as avg_citation
            FROM daily_metrics
            WHERE client_id = :cid AND day >= CURRENT_DATE - INTERVAL '30 days'
            """
        ),
        {"cid": str(eff_cid)},
    )
    m_row = m_res.first()
    visibility_pct = round(float(m_row.avg_mention or 0.0) * 100, 1) if m_row and m_row.avg_mention is not None else 0.0
    citation_share_pct = round(float(m_row.avg_citation or 0.0) * 100, 1) if m_row and m_row.avg_citation is not None else 0.0

    # Fallback to direct calculation if daily_metrics hasn't run yet
    if visibility_pct == 0.0:
        ans_res = await db.execute(
            text(
                """
                SELECT
                    COUNT(a.id) as total,
                    COUNT(bm.id) as mentions
                FROM answers a
                LEFT JOIN brand_mentions bm ON (bm.answer_id = a.id AND bm.entity_kind = 'brand')
                WHERE a.client_id = :cid
                """
            ),
            {"cid": str(eff_cid)},
        )
        ans_row = ans_res.first()
        if ans_row and ans_row.total and ans_row.total > 0:
            visibility_pct = round((ans_row.mentions / ans_row.total) * 100, 1)

    # 3. Content shipped
    ship_res = await db.execute(
        text(
            """
            SELECT COUNT(*)
            FROM content_items
            WHERE client_id = :cid AND status IN ('approved', 'scheduled', 'published')
            """
        ),
        {"cid": str(eff_cid)},
    )
    content_shipped = int(ship_res.scalar() or 0)

    # 4. Pending actions
    act_res = await db.execute(
        text("SELECT COUNT(*) FROM approvals WHERE client_id = :cid AND status = 'pending'"),
        {"cid": str(eff_cid)},
    )
    pending_actions = int(act_res.scalar() or 0)

    # 5. Recent mentions / quotes
    quotes_res = await db.execute(
        text(
            """
            SELECT a.engine, a.raw_text, p.text as query_text, a.collected_at
            FROM answers a
            JOIN prompts p ON p.id = a.prompt_id
            WHERE a.client_id = :cid AND a.raw_text IS NOT NULL
            ORDER BY a.collected_at DESC NULLS LAST
            LIMIT 5
            """
        ),
        {"cid": str(eff_cid)},
    )
    recent_mentions: list[RecentMentionItem] = []
    for qr in quotes_res.all():
        raw = qr.raw_text or ""
        snippet = raw[:220] + "..." if len(raw) > 220 else raw
        recent_mentions.append(
            RecentMentionItem(
                engine=str(qr.engine),
                query_text=qr.query_text or "General Query",
                snippet=snippet,
                collected_at=qr.collected_at.isoformat() if qr.collected_at else None,
            )
        )

    return PortalDashboardResponse(
        client_id=eff_cid,
        client_name=client_name,
        primary_domain=primary_domain,
        visibility_pct=visibility_pct,
        citation_share_pct=citation_share_pct,
        content_shipped=content_shipped,
        pending_actions=pending_actions,
        recent_mentions=recent_mentions,
    )


@router.get("/approvals", response_model=list[PortalApprovalItem])
async def list_portal_approvals(
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    client_id: UUID | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> list[PortalApprovalItem]:
    """Pending content, briefs, memos, and outreach proposals awaiting client review."""
    eff_cid, _ = await _resolve_portal_access(user, client_id, db)

    where_clauses = ["ap.client_id = :cid"]
    params: dict[str, Any] = {"cid": str(eff_cid)}

    if status_filter and isinstance(status_filter, str):
        where_clauses.append("ap.status = CAST(:st AS approval_status_t)")
        params["st"] = status_filter

    where_sql = "WHERE " + " AND ".join(where_clauses)

    query = text(
        f"""
        SELECT ap.id, ap.subject_type, ap.subject_id, ap.status, ap.comment, ap.requested_at,
               cb.title as brief_title, cb.angle as brief_angle,
               cv.title as version_title, cv.version_no, cv.word_count, cv.body_md,
               m.title as memo_title,
               rp.diff_summary,
               ci.slug as item_slug, ci.published_url
        FROM approvals ap
        LEFT JOIN content_briefs cb ON (ap.subject_type = 'brief' AND cb.id = ap.subject_id)
        LEFT JOIN content_versions cv ON (ap.subject_type = 'version' AND cv.id = ap.subject_id)
        LEFT JOIN content_items ci ON (ap.subject_type = 'version' AND ci.id = cv.content_item_id)
        LEFT JOIN memos m ON (ap.subject_type = 'memo' AND m.id = ap.subject_id)
        LEFT JOIN refresh_proposals rp ON (ap.subject_type = 'refresh' AND rp.id = ap.subject_id)
        {where_sql}
        ORDER BY ap.requested_at DESC
        """
    )
    rows = (await db.execute(query, params)).all()

    items: list[PortalApprovalItem] = []
    for r in rows:
        title = r.version_title or r.brief_title or r.memo_title or f"{r.subject_type.capitalize()} Approval"
        subtitle = (
            r.brief_angle
            or (f"Version {r.version_no} ({r.word_count} words)" if r.version_no else None)
            or r.diff_summary
        )

        body_excerpt = None
        if r.body_md:
            body_excerpt = (r.body_md[:240] + "...") if len(r.body_md) > 240 else r.body_md

        preview = ApprovalSubjectPreview(
            excerpt=body_excerpt,
            word_count=r.word_count,
            angle=r.brief_angle,
            url=r.published_url,
            diff_summary=r.diff_summary,
        )

        items.append(
            PortalApprovalItem(
                id=r.id,
                subject_type=r.subject_type,
                subject_id=r.subject_id,
                status=str(r.status),
                title=title,
                subtitle=subtitle,
                requested_at=r.requested_at.isoformat() if r.requested_at else "",
                comment=r.comment,
                preview=preview,
            )
        )

    return items


@router.post("/approvals/{approval_id}/decide", response_model=PortalApprovalItem)
async def decide_portal_approval(
    approval_id: UUID,
    body: ApprovalDecideRequest,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PortalApprovalItem:
    """Approve or reject a pending approval. Client Viewers are strictly blocked (403)."""
    # 1. Role enforcement
    if user.role == MemberRole.CLIENT_VIEWER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client viewers have read-only access and cannot decide approvals",
        )

    if user.role not in (MemberRole.CLIENT_APPROVER, *INTERNAL_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have approval permissions",
        )

    valid_decisions = {"approved", "rejected", "changes_requested"}
    if body.decision not in valid_decisions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"decision must be one of {sorted(valid_decisions)}",
        )

    # 2. Fetch approval
    ap_res = await db.execute(
        text("SELECT id, client_id, subject_type, subject_id, status FROM approvals WHERE id = :aid"),
        {"aid": str(approval_id)},
    )
    ap_row = ap_res.first()
    if not ap_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval item not found")

    # Verify access to this approval's client
    await _resolve_portal_access(user, ap_row.client_id, db)

    # 3. Update approval
    await db.execute(
        text(
            """
            UPDATE approvals
            SET status = CAST(:st AS approval_status_t),
                reviewer_id = :uid,
                comment = :comment,
                decided_at = now()
            WHERE id = :aid
            """
        ),
        {
            "aid": str(approval_id),
            "st": body.decision,
            "uid": str(user.user_id),
            "comment": body.comment,
        },
    )

    # 4. Cascade to subject item
    if ap_row.subject_type == "version":
        new_content_status = "approved" if body.decision == "approved" else ("in_review" if body.decision == "changes_requested" else "drafting")
        await db.execute(
            text(
                """
                UPDATE content_items
                SET status = CAST(:cst AS content_status_t)
                FROM content_versions cv
                WHERE cv.id = :vid AND content_items.id = cv.content_item_id
                """
            ),
            {"vid": str(ap_row.subject_id), "cst": new_content_status},
        )
    elif ap_row.subject_type == "memo":
        new_memo_status = "approved" if body.decision == "approved" else "rejected"
        await db.execute(
            text("UPDATE memos SET status = :mst, reviewer_id = :uid WHERE id = :mid"),
            {"mst": new_memo_status, "uid": str(user.user_id), "mid": str(ap_row.subject_id)},
        )

    # 5. Audit log
    await record_audit_event(
        db,
        org_id=user.org_id,
        actor=user.user_id,
        action="approval.decided",
        entity="approval",
        entity_id=approval_id,
        meta={"decision": body.decision, "subject_type": ap_row.subject_type, "comment": body.comment},
    )
    await db.commit()

    # Re-fetch updated item
    updated_items = await list_portal_approvals(user, db, client_id=ap_row.client_id, status_filter=None)
    match = next((item for item in updated_items if item.id == approval_id), None)
    if not match:
        raise HTTPException(status_code=500, detail="Failed to reload approval item")
    return match


@router.get("/content", response_model=list[PortalContentItem])
async def list_portal_content(
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    client_id: UUID | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> list[PortalContentItem]:
    """Inventory of published, scheduled, and drafted content for the client."""
    eff_cid, _ = await _resolve_portal_access(user, client_id, db)

    where_clauses = ["ci.client_id = :cid"]
    params: dict[str, Any] = {"cid": str(eff_cid)}

    if status_filter and isinstance(status_filter, str):
        where_clauses.append("ci.status = CAST(:st AS content_status_t)")
        params["st"] = status_filter

    where_sql = "WHERE " + " AND ".join(where_clauses)

    query = text(
        f"""
        SELECT ci.id, ci.slug, ci.type, ci.status, ci.published_url, ci.published_at, ci.created_at,
               COALESCE(cv.title, ci.slug, 'Untitled Content') as title,
               COALESCE(cv.word_count, 0) as word_count
        FROM content_items ci
        LEFT JOIN content_versions cv ON cv.id = ci.current_version_id
        {where_sql}
        ORDER BY ci.published_at DESC NULLS LAST, ci.created_at DESC
        """
    )
    rows = (await db.execute(query, params)).all()
    return [
        PortalContentItem(
            id=r.id,
            slug=r.slug,
            type=r.type,
            status=str(r.status),
            title=r.title,
            word_count=int(r.word_count),
            published_url=r.published_url,
            published_at=r.published_at.isoformat() if r.published_at else None,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]


@router.get("/settings", response_model=PortalSettingsResponse)
async def get_portal_settings(
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    client_id: UUID | None = None,
) -> PortalSettingsResponse:
    """Client brand profile, target publishing channels, and tracked domains."""
    eff_cid, _ = await _resolve_portal_access(user, client_id, db)

    # 1. Client & Brand Profile
    c_res = await db.execute(
        text(
            """
            SELECT c.name, c.primary_domain, c.industry, c.status,
                   bp.voice, bp.positioning, bp.products, bp.proof_points, bp.banned_claims
            FROM clients c
            LEFT JOIN brand_profiles bp ON bp.client_id = c.id
            WHERE c.id = :cid
            """
        ),
        {"cid": str(eff_cid)},
    )
    c_row = c_res.first()
    if not c_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    products = c_row.products or []
    proof_points = c_row.proof_points or []
    banned_claims = c_row.banned_claims or []

    # 2. Publish Targets
    pt_res = await db.execute(
        text("SELECT kind, status FROM publish_targets WHERE client_id = :cid"),
        {"cid": str(eff_cid)},
    )
    publish_targets = [
        PortalPublishTargetItem(kind=r.kind, status=r.status or "active")
        for r in pt_res.all()
    ]

    # 3. Competitor Domains
    comp_res = await db.execute(
        text("SELECT domain FROM competitors WHERE client_id = :cid AND domain IS NOT NULL"),
        {"cid": str(eff_cid)},
    )
    competitors = [r.domain for r in comp_res.all() if r.domain]

    return PortalSettingsResponse(
        client_id=eff_cid,
        name=c_row.name,
        primary_domain=c_row.primary_domain,
        industry=c_row.industry,
        status=c_row.status,
        voice=c_row.voice,
        positioning=c_row.positioning,
        products_count=len(products) if isinstance(products, list) else 0,
        proof_points_count=len(proof_points) if isinstance(proof_points, list) else 0,
        banned_claims_count=len(banned_claims) if isinstance(banned_claims, list) else 0,
        publish_targets=publish_targets,
        competitor_domains=competitors,
    )
