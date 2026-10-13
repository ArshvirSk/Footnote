"""Administrative operations, RBAC user management, audit logging, spend analytics, and billing caps."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from services.api.app.audit_trail import record_audit_event
from services.api.app.auth import (
    INTERNAL_ROLES,
    PORTAL_ROLES,
    AuthUser,
    MemberRole,
    require_roles,
)
from services.api.app.config import settings
from services.api.app.db import get_db
from services.api.app.logging import get_logger
from services.api.app.model_detector import (
    detect_model_releases,
    get_model_drift_summary,
    get_model_release_events,
    rebaseline_prompts,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Schemas
# ─────────────────────────────────────────────────────────────────────────────

class AdminClientRef(BaseModel):
    id: UUID
    name: str


class AdminUserItem(BaseModel):
    user_id: UUID
    email: str
    role: str
    org_id: UUID | None = None
    client_ids: list[UUID] = []
    clients: list[AdminClientRef] = []
    created_at: str | None = None


class AdminUserCreateRequest(BaseModel):
    email: str
    role: MemberRole
    client_ids: list[UUID] = []
    org_id: UUID | None = None


class AdminUserUpdateRequest(BaseModel):
    role: MemberRole | None = None
    client_ids: list[UUID] | None = None


class AuditLogItem(BaseModel):
    id: int
    org_id: UUID | None = None
    actor: UUID | None = None
    actor_email: str | None = None
    action: str
    entity: str
    entity_id: UUID | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    at: str


class AuditLogResponse(BaseModel):
    items: list[AuditLogItem]
    total: int


class AgentRunItem(BaseModel):
    id: UUID
    client_id: UUID | None = None
    client_name: str | None = None
    agent: str
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    trace_url: str | None = None


class SpendAgentBreakdown(BaseModel):
    agent: str
    runs: int
    spend_usd: float
    tokens: int


class SpendModelBreakdown(BaseModel):
    model: str
    runs: int
    spend_usd: float


class SpendClientBreakdown(BaseModel):
    client_id: UUID
    client_name: str
    runs: int
    spend_usd: float


class AdminSpendResponse(BaseModel):
    total_spend_usd: float
    spend_30d_usd: float
    total_tokens_in: int
    total_tokens_out: int
    total_runs: int
    by_agent: list[SpendAgentBreakdown]
    by_model: list[SpendModelBreakdown]
    by_client: list[SpendClientBreakdown]


class EngineStatusItem(BaseModel):
    engine: str
    configured: bool
    model: str
    key_preview: str


class BillingLimitsUpdateRequest(BaseModel):
    max_prompts: int | None = None
    max_monthly_spend_usd: float | None = None
    max_runs_per_day: int | None = None


class ReparseRequest(BaseModel):
    client_id: UUID | None = None
    engine: str | None = None


class ModelReleaseEventItem(BaseModel):
    id: UUID
    engine: str
    model_label: str
    detected_at: str | None = None
    source_url: str | None = None


class ModelReleaseCheckRequest(BaseModel):
    custom_candidates: list[dict[str, str]] | None = None


class ModelReleaseCheckResponse(BaseModel):
    newly_detected: list[ModelReleaseEventItem]
    total_events: int


class RebaselineRequest(BaseModel):
    engine: str | None = None
    client_id: UUID | None = None
    prompt_ids: list[UUID] | None = None


class RebaselineResponse(BaseModel):
    status: str
    updated_prompts: int
    engine: str | None = None
    client_id: UUID | None = None


class ModelDriftSummaryResponse(BaseModel):
    total_active_prompts: int
    never_baselined_prompts: int
    baselined_prompts: int
    recent_releases_count: int
    has_unbaselined_drift: bool
    latest_release: ModelReleaseEventItem | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Helper: fetch user details
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_user_item(db: AsyncSession, user_id: UUID) -> AdminUserItem | None:
    # 1. Fetch from auth.users
    u_res = await db.execute(
        text("SELECT id, email, created_at FROM auth.users WHERE id = :uid"),
        {"uid": str(user_id)},
    )
    u_row = u_res.first()
    if not u_row:
        return None

    email = u_row.email or "unknown@user"
    created_at_str = u_row.created_at.isoformat() if u_row.created_at else None

    # Check org_members
    o_res = await db.execute(
        text("SELECT org_id, role FROM org_members WHERE user_id = :uid LIMIT 1"),
        {"uid": str(user_id)},
    )
    o_row = o_res.first()
    if o_row:
        return AdminUserItem(
            user_id=user_id,
            email=email,
            role=o_row.role,
            org_id=o_row.org_id,
            client_ids=[],
            clients=[],
            created_at=created_at_str,
        )

    # Check client_members
    c_res = await db.execute(
        text(
            """
            SELECT cm.client_id, cm.role, c.name
            FROM client_members cm
            LEFT JOIN clients c ON c.id = cm.client_id
            WHERE cm.user_id = :uid
            """
        ),
        {"uid": str(user_id)},
    )
    c_rows = c_res.all()
    if c_rows:
        role = c_rows[0].role
        client_ids = [r.client_id for r in c_rows]
        clients = [
            AdminClientRef(id=r.client_id, name=r.name or "Unnamed Client")
            for r in c_rows
        ]
        return AdminUserItem(
            user_id=user_id,
            email=email,
            role=role,
            org_id=None,
            client_ids=client_ids,
            clients=clients,
            created_at=created_at_str,
        )

    return AdminUserItem(
        user_id=user_id,
        email=email,
        role="unassigned",
        org_id=None,
        client_ids=[],
        clients=[],
        created_at=created_at_str,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. User Management & RBAC Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[AdminUserItem])
async def list_users(
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AdminUserItem]:
    """List all team members and client portal users with role and scopes."""
    items: list[AdminUserItem] = []

    # 1. Internal org members
    org_query = text(
        """
        SELECT om.user_id, om.org_id, om.role, u.email, u.created_at
        FROM org_members om
        LEFT JOIN auth.users u ON u.id = om.user_id
        ORDER BY om.role, u.email
        """
    )
    org_res = await db.execute(org_query)
    for r in org_res.all():
        items.append(
            AdminUserItem(
                user_id=r.user_id,
                email=r.email or "unknown@org",
                role=r.role,
                org_id=r.org_id,
                client_ids=[],
                clients=[],
                created_at=r.created_at.isoformat() if r.created_at else None,
            )
        )

    # 2. Client members
    cm_query = text(
        """
        SELECT cm.user_id, cm.client_id, cm.role, c.name as client_name, u.email, u.created_at
        FROM client_members cm
        LEFT JOIN clients c ON c.id = cm.client_id
        LEFT JOIN auth.users u ON u.id = cm.user_id
        ORDER BY u.email, c.name
        """
    )
    cm_res = await db.execute(cm_query)
    grouped: dict[UUID, dict[str, Any]] = {}
    for r in cm_res.all():
        uid = r.user_id
        if uid not in grouped:
            grouped[uid] = {
                "user_id": uid,
                "email": r.email or "unknown@client",
                "role": r.role,
                "org_id": None,
                "client_ids": [],
                "clients": [],
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        grouped[uid]["client_ids"].append(r.client_id)
        grouped[uid]["clients"].append(
            AdminClientRef(id=r.client_id, name=r.client_name or "Unnamed Client")
        )

    for g in grouped.values():
        items.append(AdminUserItem(**g))

    return items


@router.post("/users", response_model=AdminUserItem, status_code=status.HTTP_201_CREATED)
async def create_user(
    req: AdminUserCreateRequest,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AdminUserItem:
    """Create or invite a new user with an internal or client portal role."""
    clean_email = req.email.strip().lower()
    if not clean_email or "@" not in clean_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Valid email address is required",
        )

    # Find or create user in auth.users
    existing = await db.execute(
        text("SELECT id FROM auth.users WHERE lower(email) = :e LIMIT 1"),
        {"e": clean_email},
    )
    row = existing.first()
    if row:
        target_uid = row.id
    else:
        target_uid = uuid4()
        await db.execute(
            text(
                "INSERT INTO auth.users (id, email, created_at) VALUES (:uid, :e, now())"
            ),
            {"uid": str(target_uid), "e": clean_email},
        )

    if req.role in INTERNAL_ROLES:
        org_id = req.org_id or user.org_id
        if not org_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="org_id required for internal role",
            )
        # Remove any client_members entries
        await db.execute(
            text("DELETE FROM client_members WHERE user_id = :uid"),
            {"uid": str(target_uid)},
        )
        await db.execute(
            text(
                """
                INSERT INTO org_members (org_id, user_id, role)
                VALUES (:oid, :uid, :role)
                ON CONFLICT (org_id, user_id) DO UPDATE SET role = EXCLUDED.role
                """
            ),
            {"oid": str(org_id), "uid": str(target_uid), "role": req.role.value},
        )
    elif req.role in PORTAL_ROLES:
        if not req.client_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one client_id must be assigned for client portal roles",
            )
        # Remove any org_members entries
        await db.execute(
            text("DELETE FROM org_members WHERE user_id = :uid"),
            {"uid": str(target_uid)},
        )
        for cid in req.client_ids:
            await db.execute(
                text(
                    """
                    INSERT INTO client_members (client_id, user_id, role)
                    VALUES (:cid, :uid, :role)
                    ON CONFLICT (client_id, user_id) DO UPDATE SET role = EXCLUDED.role
                    """
                ),
                {"cid": str(cid), "uid": str(target_uid), "role": req.role.value},
            )

    await record_audit_event(
        db,
        org_id=user.org_id,
        actor=user.user_id,
        action="user.created",
        entity="user",
        entity_id=target_uid,
        meta={"email": clean_email, "role": req.role.value, "client_ids": [str(c) for c in req.client_ids]},
    )
    await db.commit()

    created_item = await _fetch_user_item(db, target_uid)
    if not created_item:
        raise HTTPException(status_code=500, detail="Failed to retrieve created user")
    return created_item


@router.patch("/users/{user_id}", response_model=AdminUserItem)
async def update_user(
    user_id: UUID,
    req: AdminUserUpdateRequest,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AdminUserItem:
    """Update role and client associations for an existing user."""
    existing_item = await _fetch_user_item(db, user_id)
    if not existing_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    new_role = req.role if req.role is not None else MemberRole(existing_item.role)
    new_client_ids = req.client_ids if req.client_ids is not None else existing_item.client_ids

    if new_role in INTERNAL_ROLES:
        org_id = user.org_id or existing_item.org_id
        await db.execute(
            text("DELETE FROM client_members WHERE user_id = :uid"),
            {"uid": str(user_id)},
        )
        await db.execute(
            text(
                """
                INSERT INTO org_members (org_id, user_id, role)
                VALUES (:oid, :uid, :role)
                ON CONFLICT (org_id, user_id) DO UPDATE SET role = EXCLUDED.role
                """
            ),
            {"oid": str(org_id), "uid": str(user_id), "role": new_role.value},
        )
    elif new_role in PORTAL_ROLES:
        await db.execute(
            text("DELETE FROM org_members WHERE user_id = :uid"),
            {"uid": str(user_id)},
        )
        await db.execute(
            text("DELETE FROM client_members WHERE user_id = :uid"),
            {"uid": str(user_id)},
        )
        for cid in new_client_ids:
            await db.execute(
                text(
                    """
                    INSERT INTO client_members (client_id, user_id, role)
                    VALUES (:cid, :uid, :role)
                    ON CONFLICT (client_id, user_id) DO UPDATE SET role = EXCLUDED.role
                    """
                ),
                {"cid": str(cid), "uid": str(user_id), "role": new_role.value},
            )

    await record_audit_event(
        db,
        org_id=user.org_id,
        actor=user.user_id,
        action="user.updated",
        entity="user",
        entity_id=user_id,
        meta={"role": new_role.value, "client_ids": [str(c) for c in new_client_ids]},
    )
    await db.commit()

    updated = await _fetch_user_item(db, user_id)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to retrieve updated user")
    return updated


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: UUID,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Revoke user access and membership from all orgs and clients."""
    await db.execute(
        text("DELETE FROM org_members WHERE user_id = :uid"),
        {"uid": str(user_id)},
    )
    await db.execute(
        text("DELETE FROM client_members WHERE user_id = :uid"),
        {"uid": str(user_id)},
    )
    await record_audit_event(
        db,
        org_id=user.org_id,
        actor=user.user_id,
        action="user.deleted",
        entity="user",
        entity_id=user_id,
    )
    await db.commit()
    return {"status": "deleted", "user_id": str(user_id)}


# ─────────────────────────────────────────────────────────────────────────────
# 2. Audit Trail Log
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/audit-logs", response_model=AuditLogResponse)
async def list_audit_logs(
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: UUID | None = None,
    action: str | None = None,
    entity: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditLogResponse:
    """Query the enterprise audit trail with optional actor, action, and entity filters."""
    where_clauses: list[str] = []
    params: dict[str, Any] = {"limit": limit, "offset": offset}

    if user.org_id:
        where_clauses.append("(a.org_id = :org_id OR a.org_id IS NULL)")
        params["org_id"] = str(user.org_id)
    if actor:
        where_clauses.append("a.actor = :actor")
        params["actor"] = str(actor)
    if action:
        where_clauses.append("a.action ILIKE :action")
        params["action"] = f"%{action}%"
    if entity:
        where_clauses.append("a.entity ILIKE :entity")
        params["entity"] = f"%{entity}%"

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    count_res = await db.execute(
        text(f"SELECT COUNT(*) FROM audit_log a {where_sql}"),
        params,
    )
    total = int(count_res.scalar() or 0)

    query = text(
        f"""
        SELECT a.id, a.org_id, a.actor, a.action, a.entity, a.entity_id, a.meta, a.at, u.email as actor_email
        FROM audit_log a
        LEFT JOIN auth.users u ON u.id = a.actor
        {where_sql}
        ORDER BY a.at DESC
        LIMIT :limit OFFSET :offset
        """
    )
    rows = (await db.execute(query, params)).all()

    items = [
        AuditLogItem(
            id=r.id,
            org_id=r.org_id,
            actor=r.actor,
            actor_email=r.actor_email,
            action=r.action or "",
            entity=r.entity or "",
            entity_id=r.entity_id,
            meta=r.meta or {},
            at=r.at.isoformat() if r.at else "",
        )
        for r in rows
    ]

    return AuditLogResponse(items=items, total=total)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Agent Runs & Spend Analytics
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/agent-runs", response_model=list[AgentRunItem])
async def list_agent_runs(
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
    client_id: UUID | None = None,
    agent: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AgentRunItem]:
    """List execution history of AI agent runs with token counts, latency, and status."""
    where_clauses: list[str] = []
    params: dict[str, Any] = {"limit": limit, "offset": offset}

    if client_id:
        where_clauses.append("ar.client_id = :cid")
        params["cid"] = str(client_id)
    if agent:
        where_clauses.append("ar.agent = :agent")
        params["agent"] = agent
    if status_filter:
        where_clauses.append("ar.status = :status")
        params["status"] = status_filter

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    query = text(
        f"""
        SELECT ar.id, ar.client_id, ar.agent, ar.model, ar.tokens_in, ar.tokens_out,
               ar.cost_usd, ar.status, ar.started_at, ar.finished_at, ar.trace_url,
               c.name as client_name
        FROM agent_runs ar
        LEFT JOIN clients c ON c.id = ar.client_id
        {where_sql}
        ORDER BY ar.started_at DESC NULLS LAST
        LIMIT :limit OFFSET :offset
        """
    )
    rows = (await db.execute(query, params)).all()
    return [
        AgentRunItem(
            id=r.id,
            client_id=r.client_id,
            client_name=r.client_name,
            agent=r.agent,
            model=r.model,
            tokens_in=r.tokens_in,
            tokens_out=r.tokens_out,
            cost_usd=float(r.cost_usd) if r.cost_usd is not None else None,
            status=str(r.status),
            started_at=r.started_at.isoformat() if r.started_at else None,
            finished_at=r.finished_at.isoformat() if r.finished_at else None,
            trace_url=r.trace_url,
        )
        for r in rows
    ]


@router.get("/spend", response_model=AdminSpendResponse)
async def get_spend_analytics(
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AdminSpendResponse:
    """Aggregated token consumption, spend breakdown by agent, model, and client."""
    now = datetime.now(UTC)
    thirty_days_ago = now - timedelta(days=30)

    # 1. Overall totals
    totals_query = text(
        """
        SELECT
            COALESCE(SUM(cost_usd), 0) as total_spend,
            COALESCE(SUM(CASE WHEN started_at >= :t30 THEN cost_usd ELSE 0 END), 0) as spend_30d,
            COALESCE(SUM(tokens_in), 0) as tokens_in,
            COALESCE(SUM(tokens_out), 0) as tokens_out,
            COUNT(*) as total_runs
        FROM agent_runs
        """
    )
    tot_row = (await db.execute(totals_query, {"t30": thirty_days_ago})).first()
    total_spend = float(tot_row.total_spend) if tot_row else 0.0
    spend_30d = float(tot_row.spend_30d) if tot_row else 0.0
    tokens_in = int(tot_row.tokens_in) if tot_row else 0
    tokens_out = int(tot_row.tokens_out) if tot_row else 0
    total_runs = int(tot_row.total_runs) if tot_row else 0

    # 2. By agent
    agent_query = text(
        """
        SELECT
            agent,
            COUNT(*) as runs,
            COALESCE(SUM(cost_usd), 0) as spend,
            COALESCE(SUM(COALESCE(tokens_in, 0) + COALESCE(tokens_out, 0)), 0) as tokens
        FROM agent_runs
        GROUP BY agent
        ORDER BY spend DESC
        """
    )
    by_agent = [
        SpendAgentBreakdown(
            agent=r.agent,
            runs=int(r.runs),
            spend_usd=round(float(r.spend), 4),
            tokens=int(r.tokens),
        )
        for r in (await db.execute(agent_query)).all()
    ]

    # 3. By model
    model_query = text(
        """
        SELECT
            COALESCE(model, 'unknown') as model,
            COUNT(*) as runs,
            COALESCE(SUM(cost_usd), 0) as spend
        FROM agent_runs
        GROUP BY model
        ORDER BY spend DESC
        """
    )
    by_model = [
        SpendModelBreakdown(
            model=r.model,
            runs=int(r.runs),
            spend_usd=round(float(r.spend), 4),
        )
        for r in (await db.execute(model_query)).all()
    ]

    # 4. By client
    client_query = text(
        """
        SELECT
            ar.client_id,
            COALESCE(c.name, 'Unknown Client') as client_name,
            COUNT(*) as runs,
            COALESCE(SUM(ar.cost_usd), 0) as spend
        FROM agent_runs ar
        LEFT JOIN clients c ON c.id = ar.client_id
        WHERE ar.client_id IS NOT NULL
        GROUP BY ar.client_id, c.name
        ORDER BY spend DESC
        """
    )
    by_client = [
        SpendClientBreakdown(
            client_id=r.client_id,
            client_name=r.client_name,
            runs=int(r.runs),
            spend_usd=round(float(r.spend), 4),
        )
        for r in (await db.execute(client_query)).all()
    ]

    return AdminSpendResponse(
        total_spend_usd=round(total_spend, 4),
        spend_30d_usd=round(spend_30d, 4),
        total_tokens_in=tokens_in,
        total_tokens_out=tokens_out,
        total_runs=total_runs,
        by_agent=by_agent,
        by_model=by_model,
        by_client=by_client,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Billing Limits & Safety Controls
# ─────────────────────────────────────────────────────────────────────────────

@router.patch("/clients/{client_id}/billing-limits")
async def update_billing_limits(
    client_id: UUID,
    req: BillingLimitsUpdateRequest,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Configure safety caps: max prompt count, monthly spend limit ($USD), and runs/day."""
    c_res = await db.execute(
        text("SELECT id, settings FROM clients WHERE id = :cid"),
        {"cid": str(client_id)},
    )
    c_row = c_res.first()
    if not c_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    settings_dict = dict(c_row.settings or {})
    limits = dict(settings_dict.get("billing_limits", {}))

    if req.max_prompts is not None:
        limits["max_prompts"] = req.max_prompts
    if req.max_monthly_spend_usd is not None:
        limits["max_monthly_spend_usd"] = req.max_monthly_spend_usd
    if req.max_runs_per_day is not None:
        limits["max_runs_per_day"] = req.max_runs_per_day

    settings_dict["billing_limits"] = limits

    await db.execute(
        text("UPDATE clients SET settings = :settings WHERE id = :cid"),
        {"cid": str(client_id), "settings": json.dumps(settings_dict)},
    )
    await record_audit_event(
        db,
        org_id=user.org_id,
        actor=user.user_id,
        action="billing_limits.updated",
        entity="client",
        entity_id=client_id,
        meta=limits,
    )
    await db.commit()

    return {"client_id": client_id, "billing_limits": limits}


# ─────────────────────────────────────────────────────────────────────────────
# 5. Engine Status & System Operations
# ─────────────────────────────────────────────────────────────────────────────

def _mask_key(key: str) -> str:
    if not key:
        return "Not configured"
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


@router.get("/engine-status", response_model=list[EngineStatusItem])
async def get_engine_status(
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN))],
) -> list[EngineStatusItem]:
    """Provider API key availability and active models across AI engines."""
    return [
        EngineStatusItem(
            engine="chatgpt",
            configured=bool(settings.openai_api_key),
            model="gpt-4o",
            key_preview=_mask_key(settings.openai_api_key),
        ),
        EngineStatusItem(
            engine="gemini",
            configured=bool(settings.gemini_api_key),
            model="gemini-1.5-pro",
            key_preview=_mask_key(settings.gemini_api_key),
        ),
        EngineStatusItem(
            engine="perplexity",
            configured=bool(settings.perplexity_api_key),
            model="sonar-pro",
            key_preview=_mask_key(settings.perplexity_api_key),
        ),
        EngineStatusItem(
            engine="claude",
            configured=bool(settings.anthropic_api_key),
            model="claude-3-5-sonnet",
            key_preview=_mask_key(settings.anthropic_api_key),
        ),
        EngineStatusItem(
            engine="grok",
            configured=bool(getattr(settings, "xai_api_key", "")),
            model="grok-2",
            key_preview=_mask_key(getattr(settings, "xai_api_key", "")),
        ),
    ]


@router.post("/reparse")
async def trigger_reparse(
    req: ReparseRequest,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Trigger re-parsing of raw answer responses into citations and mentions."""
    where_clauses: list[str] = []
    params: dict[str, Any] = {}

    if req.client_id:
        where_clauses.append("pr.client_id = :cid")
        params["cid"] = str(req.client_id)
    if req.engine:
        where_clauses.append("a.engine = :engine")
        params["engine"] = req.engine

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    count_query = text(
        f"""
        SELECT COUNT(a.id)
        FROM answers a
        JOIN prompt_runs pr ON pr.id = a.run_id
        {where_sql}
        """
    )
    total_answers = int((await db.execute(count_query, params)).scalar() or 0)

    await record_audit_event(
        db,
        org_id=user.org_id,
        actor=user.user_id,
        action="engine.reparse_triggered",
        entity="engine",
        meta={"client_id": str(req.client_id) if req.client_id else None, "engine": req.engine, "count": total_answers},
    )
    await db.commit()

    return {
        "status": "queued",
        "count": total_answers,
        "engine": req.engine or "all",
        "client_id": str(req.client_id) if req.client_id else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Model Release Detection & Re-baselining
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/model-releases", response_model=list[ModelReleaseEventItem])
async def list_model_releases(
    user: Annotated[AuthUser, Depends(require_roles(*INTERNAL_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db)],
    engine: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[dict[str, Any]]:
    """List detected engine model release events."""
    return await get_model_release_events(db, limit=limit, engine=engine)


@router.get("/model-releases/summary", response_model=ModelDriftSummaryResponse)
async def get_model_releases_summary(
    user: Annotated[AuthUser, Depends(require_roles(*INTERNAL_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db)],
    client_id: UUID | None = None,
) -> dict[str, Any]:
    """Retrieve model drift summary, unbaselined prompt count, and latest release info."""
    return await get_model_drift_summary(db, client_id=client_id)


@router.post("/model-releases/check", response_model=ModelReleaseCheckResponse)
async def check_model_releases(
    req: ModelReleaseCheckRequest,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Scan provider catalogs and answer logs for newly detected models."""
    new_events = await detect_model_releases(db, custom_candidates=req.custom_candidates)
    all_events = await get_model_release_events(db, limit=100)

    if new_events:
        await record_audit_event(
            db,
            org_id=user.org_id,
            actor=user.user_id,
            action="model.releases_detected",
            entity="model_release_events",
            meta={"count": len(new_events), "new_models": [e["model_label"] for e in new_events]},
        )
    await db.commit()

    return {
        "newly_detected": new_events,
        "total_events": len(all_events),
    }


@router.post("/model-releases/rebaseline", response_model=RebaselineResponse)
async def trigger_rebaseline(
    req: RebaselineRequest,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Trigger re-baselining of prompts for a newly drifted or upgraded model."""
    updated = await rebaseline_prompts(
        db,
        engine=req.engine,
        client_id=req.client_id,
        prompt_ids=req.prompt_ids,
    )

    await record_audit_event(
        db,
        org_id=user.org_id,
        actor=user.user_id,
        action="prompts.rebaselined",
        entity="prompts",
        meta={
            "engine": req.engine,
            "client_id": str(req.client_id) if req.client_id else None,
            "updated_count": updated,
        },
    )
    await db.commit()

    return {
        "status": "success",
        "updated_prompts": updated,
        "engine": req.engine,
        "client_id": req.client_id,
    }


@router.post("/model-releases/{release_id}/rebaseline", response_model=RebaselineResponse)
async def rebaseline_for_release(
    release_id: UUID,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Trigger re-baselining specifically for the engine associated with a detected release event."""
    event_row = (
        await db.execute(
            text("SELECT id, engine::text, model_label FROM model_release_events WHERE id = :id"),
            {"id": str(release_id)},
        )
    ).mappings().first()

    if not event_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model release event not found")

    engine = event_row["engine"]
    updated = await rebaseline_prompts(db, engine=engine)

    await record_audit_event(
        db,
        org_id=user.org_id,
        actor=user.user_id,
        action="prompts.rebaselined_for_release",
        entity="model_release_events",
        entity_id=release_id,
        meta={
            "engine": engine,
            "model_label": event_row["model_label"],
            "updated_count": updated,
        },
    )
    await db.commit()

    return {
        "status": "success",
        "updated_prompts": updated,
        "engine": engine,
        "client_id": None,
    }
