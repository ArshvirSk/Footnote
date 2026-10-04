"""Gaps + daily metrics read routes, gap status transitions and evidence (M2)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from services.api.app.auth import AuthUser, MemberRole, get_current_user, has_client_access, require_roles
from services.api.app.db import get_db
from services.api.app.logging import get_logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

router = APIRouter(prefix="/clients/{client_id}", tags=["gaps"])


class GapResponse(BaseModel):
    id: UUID
    client_id: UUID
    prompt_id: UUID | None
    prompt_text: str | None
    gap_type: str
    details: dict[str, Any]
    status: str
    detected_at: str | None


class DailyMetricResponse(BaseModel):
    day: str
    engine: str
    prompts_tracked: int
    prompts_visible: int
    mention_rate: float
    linked_rate: float
    brand_citations: int
    total_citations: int
    citation_share: float
    share_of_voice: float
    avg_sentiment: float


@router.get("/gaps", response_model=list[GapResponse])
async def list_gaps(
    client_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[GapResponse]:
    """Open+closed gaps for a client, newest first, joined with prompt text."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    result = await db.execute(
        text(
            """
            SELECT g.id, g.client_id, g.prompt_id, p.text AS prompt_text,
                   g.gap_type, g.details, g.status,
                   to_char(g.detected_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS detected_at
            FROM gaps g
            LEFT JOIN prompts p ON p.id = g.prompt_id
            WHERE g.client_id = :cid
            ORDER BY g.detected_at DESC
            LIMIT 200
            """
        ),
        {"cid": str(client_id)},
    )
    return [
        GapResponse(
            id=r.id,
            client_id=r.client_id,
            prompt_id=r.prompt_id,
            prompt_text=r.prompt_text,
            gap_type=r.gap_type,
            details=r.details or {},
            status=r.status,
            detected_at=r.detected_at,
        )
        for r in result.all()
    ]


@router.get("/metrics/daily", response_model=list[DailyMetricResponse])
async def list_daily_metrics(
    client_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = 14,
) -> list[DailyMetricResponse]:
    """Daily metric rows (all engines) for the last N days."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    cutoff = date.today() - timedelta(days=max(1, min(days, 90)))
    result = await db.execute(
        text(
            """
            SELECT day, engine, prompts_tracked, prompts_visible,
                   mention_rate, linked_rate, brand_citations, total_citations,
                   citation_share, share_of_voice, avg_sentiment
            FROM daily_metrics
            WHERE client_id = :cid AND day > :cutoff
            ORDER BY day DESC, engine
            """
        ),
        {"cid": str(client_id), "cutoff": cutoff},
    )
    return [
        DailyMetricResponse(
            day=r.day.isoformat() if isinstance(r.day, date) else str(r.day),
            engine=r.engine,
            prompts_tracked=r.prompts_tracked,
            prompts_visible=r.prompts_visible,
            mention_rate=float(r.mention_rate),
            linked_rate=float(r.linked_rate),
            brand_citations=r.brand_citations,
            total_citations=r.total_citations,
            citation_share=float(r.citation_share),
            share_of_voice=float(r.share_of_voice),
            avg_sentiment=float(r.avg_sentiment),
        )
        for r in result.all()
    ]


# ───────────── Gap transitions + evidence (Milestone 2) ─────────────

_GAP_STATUSES = ("open", "in_progress", "won", "dismissed")


class GapStatusRequest(BaseModel):
    status: str = Field(pattern="^(open|in_progress|won|dismissed)$")


class EvidenceAnswer(BaseModel):
    answer_id: UUID
    engine: str
    run_index: int
    day: str | None
    collected_at: str | None
    brand_mentioned: bool
    competitor_mentioned: bool
    excerpt: str | None
    citations: list[dict[str, Any]]


class GapDetailResponse(GapResponse):
    evidence: list[EvidenceAnswer]
    why: str


def _gap_explanation(gap_type: str) -> str:
    if gap_type == "slipped":
        return (
            "This prompt was visible (brand mentioned in >= 50% of runs) in the previous 7-day "
            "window but is not visible on the detected day. Evidence shows the raw answers from both sides."
        )
    if gap_type == "competitor_cited":
        return (
            "A competitor was mentioned or cited for this prompt while the brand did not appear in "
            "the same day's answers. Evidence shows the answers that cited the competitor."
        )
    if gap_type == "absent":
        return "The brand never appeared for this prompt while competitors did."
    if gap_type == "source_missing":
        return "The brand is mentioned but not linked/cited; a source on the site is missing."
    return "Detected by the nightly rollup from collected answers."


@router.patch("/gaps/{gap_id}", response_model=GapResponse)
async def update_gap_status(
    client_id: UUID,
    gap_id: UUID,
    body: GapStatusRequest,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN, MemberRole.STRATEGIST))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GapResponse:
    """Move a gap through open → in_progress → won (or dismissed)."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    if body.status not in _GAP_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown gap status")

    result = await db.execute(
        text(
            """
            UPDATE gaps SET
                status = :st,
                closed_at = CASE WHEN :st IN ('won', 'dismissed') THEN now() ELSE NULL END
            WHERE id = :gid AND client_id = :cid
            RETURNING id, client_id, prompt_id, gap_type, details, status,
                      to_char(detected_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS detected_at
            """
        ),
        {"st": body.status, "gid": str(gap_id), "cid": str(client_id)},
    )
    row = result.first()
    await db.commit()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gap not found")
    prompt_text = (
        await db.execute(text("SELECT text FROM prompts WHERE id = :pid"), {"pid": str(row.prompt_id)})
    ).scalar() if row.prompt_id else None
    return GapResponse(
        id=row.id,
        client_id=row.client_id,
        prompt_id=row.prompt_id,
        prompt_text=prompt_text,
        gap_type=row.gap_type,
        details=row.details or {},
        status=row.status,
        detected_at=row.detected_at,
    )


@router.get("/gaps/{gap_id}", response_model=GapDetailResponse)
async def get_gap_detail(
    client_id: UUID,
    gap_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 12,
) -> GapDetailResponse:
    """One gap with the raw answer evidence behind it (FR-11/FR-13)."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    gap = (
        await db.execute(
            text(
                """
                SELECT g.id, g.client_id, g.prompt_id, p.text AS prompt_text,
                       g.gap_type, g.details, g.status,
                       to_char(g.detected_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS detected_at
                FROM gaps g
                LEFT JOIN prompts p ON p.id = g.prompt_id
                WHERE g.id = :gid AND g.client_id = :cid
                """
            ),
            {"gid": str(gap_id), "cid": str(client_id)},
        )
    ).first()
    if gap is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gap not found")

    evidence: list[EvidenceAnswer] = []
    if gap.prompt_id:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT a.id, a.engine, a.run_index, a.raw_text,
                           to_char(a.run_day, 'YYYY-MM-DD') AS day,
                           to_char(a.collected_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS collected_at,
                           EXISTS (SELECT 1 FROM brand_mentions bm
                                   WHERE bm.answer_id = a.id AND bm.entity_kind = 'brand') AS brand_mentioned,
                           EXISTS (SELECT 1 FROM brand_mentions bm
                                   WHERE bm.answer_id = a.id AND bm.entity_kind = 'competitor') AS competitor_mentioned,
                           (SELECT coalesce(jsonb_agg(
                                       jsonb_build_object('url', ac.url, 'title', ac.title, 'owned', ac.is_brand_owned)
                                       ORDER BY ac.position), '[]'::jsonb)
                            FROM answer_citations ac WHERE ac.answer_id = a.id) AS citations
                    FROM answers a
                    WHERE a.client_id = :cid AND a.prompt_id = :pid AND a.status = 'succeeded'
                    ORDER BY a.collected_at DESC NULLS LAST, a.run_day DESC
                    LIMIT :lim
                    """
                ),
                {"cid": str(client_id), "pid": str(gap.prompt_id), "lim": max(1, min(limit, 50))},
            )
        ).all()
        evidence = [
            EvidenceAnswer(
                answer_id=r.id,
                engine=str(r.engine),
                run_index=int(r.run_index),
                day=r.day,
                collected_at=r.collected_at,
                brand_mentioned=bool(r.brand_mentioned),
                competitor_mentioned=bool(r.competitor_mentioned),
                excerpt=(r.raw_text or "")[:400] or None,
                citations=list(r.citations or []),
            )
            for r in rows
        ]

    return GapDetailResponse(
        id=gap.id,
        client_id=gap.client_id,
        prompt_id=gap.prompt_id,
        prompt_text=gap.prompt_text,
        gap_type=gap.gap_type,
        details=gap.details or {},
        status=gap.status,
        detected_at=gap.detected_at,
        evidence=evidence,
        why=_gap_explanation(gap.gap_type),
    )
