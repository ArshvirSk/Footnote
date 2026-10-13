"""Analytics API: real KPI aggregations, time-series, won gaps, and engine share.

Replaces all hardcoded/mock numbers in the dashboard with live database queries
against daily_metrics, brand_mentions, answer_citations, gaps, publications, and
content_items.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
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

router = APIRouter(prefix="/clients/{client_id}/analytics", tags=["analytics"])

OPS_ROLES = (
    MemberRole.STRATEGIST,
    MemberRole.EDITOR,
    MemberRole.ADMIN,
    MemberRole.OWNER,
)


# ───────────── Schemas ─────────────

class KPIOverview(BaseModel):
    published_content: int = 0
    won_gaps: int = 0
    ai_mentions: int = 0
    citation_share_pct: float = 0.0
    estimated_referral_value: float = 0.0
    days: int = 30


class TimeseriesPoint(BaseModel):
    day: str
    brand_mentions: int = 0
    competitor_mentions: int = 0
    citation_share: float = 0.0


class WonGap(BaseModel):
    id: UUID
    prompt_text: str | None = None
    gap_type: str
    closed_at: str | None = None
    proof_citations: list[dict[str, Any]] = Field(default_factory=list)
    published_url: str | None = None


class EngineShare(BaseModel):
    engine: str
    mention_rate: float = 0.0
    citation_share: float = 0.0
    prompts_visible: int = 0
    prompts_tracked: int = 0


# ───────────── Helpers ─────────────

def _date_range(days: int) -> tuple[date, date]:
    """Return (start_date, end_date) as date objects for the last N days."""
    end = datetime.now(UTC).date()
    start = end - timedelta(days=days)
    return start, end


# ───────────── Routes ─────────────

@router.get("/overview", response_model=KPIOverview)
async def analytics_overview(
    client_id: UUID,
    days: int = Query(30, ge=7, le=365),
    user: AuthUser = Depends(require_roles(*OPS_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> KPIOverview:
    """Real-time KPI overview cards for the dashboard."""
    await has_client_access(client_id, user, db)
    start, end = _date_range(days)

    # Published content in period
    pub_res = await db.execute(
        text("""
            SELECT count(*) AS cnt
            FROM content_items
            WHERE client_id = :cid
              AND status = 'published'
              AND published_at >= :start
        """),
        {"cid": str(client_id), "start": start},
    )
    published_content = pub_res.scalar_one_or_none() or 0

    # Won gaps in period
    won_res = await db.execute(
        text("""
            SELECT count(*) AS cnt
            FROM gaps
            WHERE client_id = :cid
              AND status = 'won'
              AND closed_at >= :start
        """),
        {"cid": str(client_id), "start": start},
    )
    won_gaps = won_res.scalar_one_or_none() or 0

    # Total brand mentions in period
    mention_res = await db.execute(
        text("""
            SELECT count(*) AS cnt
            FROM brand_mentions bm
            JOIN answers a ON a.id = bm.answer_id
            WHERE bm.client_id = :cid
              AND bm.entity_kind = 'brand'
              AND a.collected_at >= :start
        """),
        {"cid": str(client_id), "start": start},
    )
    ai_mentions = mention_res.scalar_one_or_none() or 0

    # Citation share (brand_citations / total_citations) averaged across engines
    share_res = await db.execute(
        text("""
            SELECT
              COALESCE(SUM(brand_citations), 0) AS brand_total,
              COALESCE(SUM(total_citations), 0) AS all_total
            FROM daily_metrics
            WHERE client_id = :cid
              AND day >= :start AND day <= :end
        """),
        {"cid": str(client_id), "start": start, "end": end},
    )
    row = share_res.one()
    brand_total = row[0] or 0
    all_total = row[1] or 0
    citation_share_pct = round((brand_total / all_total * 100) if all_total > 0 else 0, 2)

    # Estimated referral value: brand citations * $2.50 heuristic (conservative CPC proxy)
    estimated_referral_value = round(float(brand_total) * 2.50, 2)

    return KPIOverview(
        published_content=published_content,
        won_gaps=won_gaps,
        ai_mentions=ai_mentions,
        citation_share_pct=citation_share_pct,
        estimated_referral_value=estimated_referral_value,
        days=days,
    )


@router.get("/timeseries", response_model=list[TimeseriesPoint])
async def analytics_timeseries(
    client_id: UUID,
    days: int = Query(30, ge=7, le=365),
    user: AuthUser = Depends(require_roles(*OPS_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> list[TimeseriesPoint]:
    """Daily time-series of brand mentions, competitor mentions, and citation share."""
    await has_client_access(client_id, user, db)
    start, end = _date_range(days)

    result = await db.execute(
        text("""
            WITH daily AS (
                SELECT
                    a.collected_at::date AS day,
                    COUNT(*) FILTER (WHERE bm.entity_kind = 'brand') AS brand_mentions,
                    COUNT(*) FILTER (WHERE bm.entity_kind = 'competitor') AS competitor_mentions
                FROM brand_mentions bm
                JOIN answers a ON a.id = bm.answer_id
                WHERE bm.client_id = :cid
                  AND a.collected_at >= :start
                  AND a.collected_at <= :end
                GROUP BY a.collected_at::date
            ),
            share AS (
                SELECT
                    day,
                    CASE WHEN total_citations > 0
                         THEN ROUND(brand_citations::numeric / total_citations * 100, 2)
                         ELSE 0 END AS citation_share
                FROM daily_metrics
                WHERE client_id = :cid
                  AND day >= :start AND day <= :end
            )
            SELECT
                COALESCE(d.day, s.day) AS day,
                COALESCE(d.brand_mentions, 0) AS brand_mentions,
                COALESCE(d.competitor_mentions, 0) AS competitor_mentions,
                COALESCE(s.citation_share, 0) AS citation_share
            FROM daily d
            FULL OUTER JOIN share s ON d.day = s.day
            ORDER BY day
        """),
        {"cid": str(client_id), "start": start, "end": end},
    )
    rows = result.all()

    return [
        TimeseriesPoint(
            day=str(r[0]),
            brand_mentions=r[1] or 0,
            competitor_mentions=r[2] or 0,
            citation_share=float(r[3] or 0),
        )
        for r in rows
    ]


@router.get("/won-gaps", response_model=list[WonGap])
async def analytics_won_gaps(
    client_id: UUID,
    days: int = Query(90, ge=7, le=365),
    user: AuthUser = Depends(require_roles(*OPS_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> list[WonGap]:
    """List of verified won gaps with proof citation evidence."""
    await has_client_access(client_id, user, db)
    start, _ = _date_range(days)

    result = await db.execute(
        text("""
            SELECT
                g.id, p.text AS prompt_text, g.gap_type,
                g.closed_at::text,
                COALESCE(
                    (SELECT json_agg(json_build_object(
                        'url', ac.url,
                        'title', ac.title,
                        'is_brand_owned', ac.is_brand_owned
                    ))
                    FROM content_prompt_map cpm
                    JOIN content_items ci ON ci.id = cpm.content_item_id
                    JOIN answer_citations ac ON ac.client_id = g.client_id
                        AND ac.is_brand_owned = true
                    WHERE cpm.prompt_id = g.prompt_id
                      AND ci.status = 'published'
                    LIMIT 5),
                    '[]'::json
                ) AS proof_citations,
                ci2.published_url
            FROM gaps g
            LEFT JOIN prompts p ON p.id = g.prompt_id
            LEFT JOIN content_prompt_map cpm2 ON cpm2.prompt_id = g.prompt_id
            LEFT JOIN content_items ci2 ON ci2.id = cpm2.content_item_id
                AND ci2.status = 'published'
            WHERE g.client_id = :cid
              AND g.status = 'won'
              AND g.closed_at >= :start
            ORDER BY g.closed_at DESC
        """),
        {"cid": str(client_id), "start": start},
    )
    rows = result.all()

    won_gaps: list[WonGap] = []
    seen_ids: set[str] = set()
    for r in rows:
        gid = str(r[0])
        if gid in seen_ids:
            continue
        seen_ids.add(gid)
        proofs = r[4] if isinstance(r[4], list) else []
        won_gaps.append(WonGap(
            id=r[0],
            prompt_text=r[1],
            gap_type=r[2],
            closed_at=r[3],
            proof_citations=proofs,
            published_url=r[5],
        ))
    return won_gaps


@router.get("/engine-share", response_model=list[EngineShare])
async def analytics_engine_share(
    client_id: UUID,
    days: int = Query(30, ge=7, le=365),
    user: AuthUser = Depends(require_roles(*OPS_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> list[EngineShare]:
    """Distribution of brand visibility across AI engines."""
    await has_client_access(client_id, user, db)
    start, end = _date_range(days)

    result = await db.execute(
        text("""
            SELECT
                engine::text,
                ROUND(AVG(mention_rate) * 100, 2) AS mention_rate,
                ROUND(AVG(citation_share) * 100, 2) AS citation_share,
                SUM(prompts_visible) AS prompts_visible,
                SUM(prompts_tracked) AS prompts_tracked
            FROM daily_metrics
            WHERE client_id = :cid
              AND day >= :start AND day <= :end
            GROUP BY engine
            ORDER BY mention_rate DESC
        """),
        {"cid": str(client_id), "start": start, "end": end},
    )
    rows = result.all()

    return [
        EngineShare(
            engine=r[0],
            mention_rate=float(r[1] or 0),
            citation_share=float(r[2] or 0),
            prompts_visible=int(r[3] or 0),
            prompts_tracked=int(r[4] or 0),
        )
        for r in rows
    ]
