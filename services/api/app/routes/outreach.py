"""Digital PR & Citation Outreach API with hard approval gate.

Manages outreach targets (high-authority domains cited by AI engines where the
brand is absent), pitch message drafting, and dispatch. All messages require
explicit approval (approvals.status = 'approved') before they can be sent.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

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

router = APIRouter(prefix="/clients/{client_id}/outreach", tags=["outreach"])

OPS_ROLES = (
    MemberRole.STRATEGIST,
    MemberRole.EDITOR,
    MemberRole.ADMIN,
    MemberRole.OWNER,
)


# ───────────── Schemas ─────────────

class OutreachTargetCreate(BaseModel):
    domain_id: UUID | None = None
    domain_name: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    rationale: str | None = None


class OutreachTargetResponse(BaseModel):
    id: UUID
    client_id: UUID
    domain_id: UUID | None = None
    domain_name: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    rationale: str | None = None
    citation_frequency: int = 0
    status: str
    created_at: str | None = None


class OutreachMessageCreate(BaseModel):
    subject: str | None = None
    body: str | None = None
    pitch_type: str | None = None
    context: str | None = None


class OutreachMessageResponse(BaseModel):
    id: UUID
    target_id: UUID
    client_id: UUID
    subject: str | None = None
    body: str | None = None
    approval_id: UUID | None = None
    approval_status: str | None = None
    sent_at: str | None = None
    reply_status: str | None = None
    created_at: str | None = None


class DiscoverTargetsResponse(BaseModel):
    targets_found: int = 0
    targets_created: int = 0
    top_domains: list[dict[str, Any]] = Field(default_factory=list)


# ───────────── Routes: Targets ─────────────

@router.get("/targets", response_model=list[OutreachTargetResponse])
async def list_outreach_targets(
    client_id: UUID,
    target_status: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    user: AuthUser = Depends(require_roles(*OPS_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> list[OutreachTargetResponse]:
    """List outreach targets for a client."""
    await has_client_access(client_id, user, db)

    conditions = ["ot.client_id = :cid"]
    params: dict[str, Any] = {"cid": str(client_id), "limit": limit}
    if target_status:
        conditions.append("ot.status = :status")
        params["status"] = target_status

    where = " AND ".join(conditions)
    result = await db.execute(
        text(f"""
            SELECT
                ot.id, ot.client_id, ot.domain_id,
                d.domain AS domain_name,
                ot.contact_name, ot.contact_email, ot.rationale,
                ot.citation_frequency, ot.status, CAST(ot.created_at AS text)
            FROM outreach_targets ot
            LEFT JOIN domains d ON d.id = ot.domain_id
            WHERE {where}
            ORDER BY ot.citation_frequency DESC, ot.created_at DESC
            LIMIT :limit
        """),
        params,
    )
    rows = result.all()

    return [
        OutreachTargetResponse(
            id=r[0], client_id=r[1], domain_id=r[2], domain_name=r[3],
            contact_name=r[4], contact_email=r[5], rationale=r[6],
            citation_frequency=r[7] or 0, status=r[8], created_at=r[9],
        )
        for r in rows
    ]


@router.post("/targets", response_model=OutreachTargetResponse, status_code=status.HTTP_201_CREATED)
async def create_outreach_target(
    client_id: UUID,
    body: OutreachTargetCreate,
    user: AuthUser = Depends(require_roles(*OPS_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> OutreachTargetResponse:
    """Create a new outreach target."""
    await has_client_access(client_id, user, db)

    result = await db.execute(
        text("""
            INSERT INTO outreach_targets
                (client_id, domain_id, contact_name, contact_email, rationale)
            VALUES (:cid, :domain_id, :contact_name, :contact_email, :rationale)
            RETURNING id, client_id, domain_id, contact_name, contact_email,
                      rationale, citation_frequency, status, created_at::text
        """),
        {
            "cid": str(client_id),
            "domain_id": str(body.domain_id) if body.domain_id else None,
            "contact_name": body.contact_name,
            "contact_email": body.contact_email,
            "rationale": body.rationale,
        },
    )
    r = result.one()
    await db.commit()

    return OutreachTargetResponse(
        id=r[0], client_id=r[1], domain_id=r[2], domain_name=body.domain_name,
        contact_name=r[3], contact_email=r[4], rationale=r[5],
        citation_frequency=r[6] or 0, status=r[7], created_at=r[8],
    )


@router.post("/discover", response_model=DiscoverTargetsResponse)
async def discover_outreach_targets(
    client_id: UUID,
    days: int = Query(30, ge=7, le=180),
    min_citations: int = Query(3, ge=1),
    user: AuthUser = Depends(require_roles(*OPS_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> DiscoverTargetsResponse:
    """Auto-discover high-citation domains where the brand is absent.

    Mines domain_citation_daily and answer_citations to find domains frequently
    cited by AI engines where is_brand_owned = false and no competitor linkage.
    """
    await has_client_access(client_id, user, db)

    # Find high-citation non-brand domains
    result = await db.execute(
        text("""
            SELECT
                d.id AS domain_id,
                d.domain,
                SUM(dcd.citations) AS total_citations,
                d.authority_score
            FROM domain_citation_daily dcd
            JOIN domains d ON d.id = dcd.domain_id
            WHERE dcd.client_id = :cid
              AND dcd.day >= (current_date - :days * interval '1 day')
              AND dcd.is_brand = false
              AND d.domain_type NOT IN ('owned', 'wiki', 'gov_edu')
              AND d.id NOT IN (
                  SELECT domain_id FROM outreach_targets
                  WHERE client_id = :cid AND domain_id IS NOT NULL
              )
            GROUP BY d.id, d.domain, d.authority_score
            HAVING SUM(dcd.citations) >= :min_cit
            ORDER BY SUM(dcd.citations) DESC
            LIMIT 20
        """),
        {"cid": str(client_id), "days": days, "min_cit": min_citations},
    )
    domains = result.all()

    targets_created = 0
    top_domains: list[dict[str, Any]] = []

    for dom in domains:
        domain_id, domain_name, total_cit, authority = dom[0], dom[1], dom[2], dom[3]
        top_domains.append({
            "domain": domain_name,
            "citations": int(total_cit),
            "authority_score": float(authority) if authority else None,
        })

        # Auto-create outreach target
        await db.execute(
            text("""
                INSERT INTO outreach_targets
                    (client_id, domain_id, citation_frequency, rationale, status)
                VALUES
                    (:cid, :did, :freq, :rationale, 'identified')
                ON CONFLICT DO NOTHING
            """),
            {
                "cid": str(client_id),
                "did": str(domain_id),
                "freq": int(total_cit),
                "rationale": f"Cited {total_cit} times by AI engines in last {days} days. Brand not present.",
            },
        )
        targets_created += 1

    await db.commit()

    return DiscoverTargetsResponse(
        targets_found=len(domains),
        targets_created=targets_created,
        top_domains=top_domains,
    )


# ───────────── Routes: Messages (with hard approval gate) ─────────────

@router.get("/targets/{target_id}/messages", response_model=list[OutreachMessageResponse])
async def list_outreach_messages(
    client_id: UUID,
    target_id: UUID,
    user: AuthUser = Depends(require_roles(*OPS_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> list[OutreachMessageResponse]:
    """List messages for an outreach target."""
    await has_client_access(client_id, user, db)

    result = await db.execute(
        text("""
            SELECT
                om.id, om.target_id, om.client_id,
                om.subject, om.body, om.approval_id,
                a.status AS approval_status,
                CAST(om.sent_at AS text), om.reply_status, CAST(om.created_at AS text)
            FROM outreach_messages om
            LEFT JOIN approvals a ON a.id = om.approval_id
            WHERE om.target_id = :tid AND om.client_id = :cid
            ORDER BY om.created_at DESC
        """),
        {"tid": str(target_id), "cid": str(client_id)},
    )
    rows = result.all()

    return [
        OutreachMessageResponse(
            id=r[0], target_id=r[1], client_id=r[2],
            subject=r[3], body=r[4], approval_id=r[5],
            approval_status=r[6], sent_at=r[7],
            reply_status=r[8], created_at=r[9],
        )
        for r in rows
    ]


@router.post(
    "/targets/{target_id}/messages",
    response_model=OutreachMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_outreach_message(
    client_id: UUID,
    target_id: UUID,
    body: OutreachMessageCreate,
    user: AuthUser = Depends(require_roles(*OPS_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> OutreachMessageResponse:
    """Create a new outreach message and automatically create an approval record.

    The message CANNOT be sent until the approval is explicitly approved.
    """
    await has_client_access(client_id, user, db)

    # Verify target exists
    target_check = await db.execute(
        text("SELECT id FROM outreach_targets WHERE id = :tid AND client_id = :cid"),
        {"tid": str(target_id), "cid": str(client_id)},
    )
    if not target_check.scalar_one_or_none():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Outreach target not found")

    # Create the message
    msg_id = str(uuid4())
    approval_id = str(uuid4())

    subject = body.subject or f"Collaboration Inquiry: {body.pitch_type or 'Editorial addition'}"
    msg_body = (
        body.body
        or f"Hello,\n\nWe noticed your industry coverage and would love to suggest adding verified benchmarks: {body.context or 'Comprehensive data study'}.\n\nBest regards,\nFootnote Team"
    )

    # Create approval record first
    await db.execute(
        text("""
            INSERT INTO approvals (id, client_id, subject_type, subject_id, status, requested_by)
            VALUES (:id, :cid, 'outreach', :subject_id, 'pending', :requested_by)
        """),
        {
            "id": approval_id,
            "cid": str(client_id),
            "subject_id": msg_id,
            "requested_by": str(user.user_id),
        },
    )

    # Create the message with the approval link
    result = await db.execute(
        text("""
            INSERT INTO outreach_messages
                (id, target_id, client_id, subject, body, approval_id)
            VALUES (:id, :tid, :cid, :subject, :body, :approval_id)
            RETURNING id, target_id, client_id, subject, body, approval_id,
                      CAST(sent_at AS text), reply_status, CAST(created_at AS text)
        """),
        {
            "id": msg_id,
            "tid": str(target_id),
            "cid": str(client_id),
            "subject": subject,
            "body": msg_body,
            "approval_id": approval_id,
        },
    )
    r = result.one()
    await db.commit()

    logger.info("outreach_message_created", message_id=msg_id, approval_id=approval_id)

    return OutreachMessageResponse(
        id=r[0], target_id=r[1], client_id=r[2],
        subject=r[3], body=r[4], approval_id=r[5],
        approval_status="pending", sent_at=r[6],
        reply_status=r[7], created_at=r[8],
    )


class DraftPitchBody(BaseModel):
    pitch_type: str = "resource_addition"
    context: str | None = None


@router.post("/targets/{target_id}/draft-pitch", response_model=OutreachMessageResponse)
async def draft_pitch(
    client_id: UUID,
    target_id: UUID,
    body: DraftPitchBody,
    user: AuthUser = Depends(require_roles(*OPS_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> OutreachMessageResponse:
    """Draft a personalized pitch message for an outreach target and enqueue approval."""
    msg_create = OutreachMessageCreate(
        pitch_type=body.pitch_type,
        context=body.context,
    )
    return await create_outreach_message(client_id, target_id, msg_create, user, db)


@router.post("/targets/{target_id}/messages/{message_id}/send")
async def send_outreach_message(
    client_id: UUID,
    target_id: UUID,
    message_id: UUID,
    user: AuthUser = Depends(require_roles(*OPS_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Send an outreach message — BLOCKED until approval is 'approved'.

    This is the HARD APPROVAL GATE: messages cannot be dispatched without
    an explicit approval decision.
    """
    await has_client_access(client_id, user, db)

    # Get message and check approval status
    result = await db.execute(
        text("""
            SELECT
                om.id, om.subject, om.body, om.approval_id, om.sent_at,
                a.status AS approval_status
            FROM outreach_messages om
            LEFT JOIN approvals a ON a.id = om.approval_id
            WHERE om.id = :mid AND om.target_id = :tid AND om.client_id = :cid
        """),
        {"mid": str(message_id), "tid": str(target_id), "cid": str(client_id)},
    )
    msg = result.one_or_none()
    if not msg:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")

    if msg[4] is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Message already sent")

    # ══════════ HARD APPROVAL GATE ══════════
    approval_status = msg[5]
    if approval_status != "approved":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Cannot send message: approval status is '{approval_status}'. "
            "An explicit approval (approvals.status = 'approved') is required before dispatch.",
        )
    # ════════════════════════════════════════

    # Mark as sent
    now = datetime.now(UTC)
    await db.execute(
        text("""
            UPDATE outreach_messages
            SET sent_at = :now, reply_status = 'sent'
            WHERE id = :mid AND client_id = :cid
        """),
        {"now": now, "mid": str(message_id), "cid": str(client_id)},
    )

    # Update target status
    await db.execute(
        text("""
            UPDATE outreach_targets
            SET status = 'contacted'
            WHERE id = :tid AND client_id = :cid AND status = 'identified'
        """),
        {"tid": str(target_id), "cid": str(client_id)},
    )

    await db.commit()

    logger.info("outreach_message_sent", message_id=str(message_id), target_id=str(target_id))

    return {
        "status": "sent",
        "message_id": str(message_id),
        "sent_at": now.isoformat(),
        "detail": "Sent via hard approval gate",
    }


@router.post("/messages/{message_id}/dispatch")
async def dispatch_outreach_message(
    client_id: UUID,
    message_id: UUID,
    user: AuthUser = Depends(require_roles(*OPS_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Dispatch endpoint alias for frontend clients."""
    await has_client_access(client_id, user, db)

    # Lookup target_id
    res = await db.execute(
        text("SELECT target_id FROM outreach_messages WHERE id = :mid AND client_id = :cid"),
        {"mid": str(message_id), "cid": str(client_id)},
    )
    row = res.one_or_none()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")

    return await send_outreach_message(client_id, row[0], message_id, user, db)
