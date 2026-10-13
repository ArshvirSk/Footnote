"""Executive Monthly Client Memo Generator.

Aggregates 30-day tracking data (daily_metrics, closed gaps, citations won,
competitive shifts) and produces an executive-ready Markdown memo with ROI
metrics and strategic recommendations.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from services.api.app.config import settings
from services.api.app.logging import get_logger

logger = get_logger(__name__)


async def _get_engine() -> AsyncEngine:
    return create_async_engine(settings.database_url, echo=False)


async def generate_client_memo(
    client_id: str | UUID,
    period_days: int = 30,
) -> dict[str, Any]:
    """Generate an executive memo for a client covering the last N days.

    Returns the memo record including draft_md.
    """
    client_id = str(client_id)
    engine = await _get_engine()
    now = datetime.now(UTC)
    period_end = now.date()
    period_start = period_end - timedelta(days=period_days)
    prev_start = period_start - timedelta(days=period_days)
    start_dt = datetime.combine(period_start, datetime.min.time(), tzinfo=UTC)

    async with AsyncSession(engine) as session:
        # ── 1. Client info ──
        client_res = await session.execute(
            text("SELECT name, primary_domain FROM clients WHERE id = :cid"),
            {"cid": client_id},
        )
        client = client_res.one_or_none()
        client_name = client[0] if client else "Unknown Client"
        client_domain = client[1] if client else "unknown.com"

        # ── 2. Overall visibility & trend ──
        vis_res = await session.execute(
            text("""
                SELECT
                    ROUND(AVG(mention_rate) * 100, 2) AS avg_mention_rate,
                    ROUND(AVG(citation_share) * 100, 2) AS avg_citation_share,
                    SUM(prompts_visible) AS total_visible,
                    SUM(prompts_tracked) AS total_tracked,
                    SUM(brand_citations) AS brand_cit,
                    SUM(total_citations) AS total_cit
                FROM daily_metrics
                WHERE client_id = :cid
                  AND day >= :start AND day <= :end
            """),
            {"cid": client_id, "start": period_start, "end": period_end},
        )
        vis = vis_res.one()
        mention_rate = float(vis[0] or 0)
        citation_share = float(vis[1] or 0)
        total_visible = int(vis[2] or 0)
        total_tracked = int(vis[3] or 0)
        brand_citations = int(vis[4] or 0)
        total_citations = int(vis[5] or 0)

        # Previous period for trend
        prev_res = await session.execute(
            text("""
                SELECT
                    ROUND(AVG(mention_rate) * 100, 2) AS avg_mention_rate,
                    ROUND(AVG(citation_share) * 100, 2) AS avg_citation_share
                FROM daily_metrics
                WHERE client_id = :cid
                  AND day >= :start AND day < :end
            """),
            {"cid": client_id, "start": prev_start, "end": period_start},
        )
        prev = prev_res.one()
        prev_mention = float(prev[0] or 0)
        prev_share = float(prev[1] or 0)

        mention_delta = round(mention_rate - prev_mention, 2)
        share_delta = round(citation_share - prev_share, 2)

        # ── 3. Engine breakdown ──
        eng_res = await session.execute(
            text("""
                SELECT
                    engine::text,
                    ROUND(AVG(mention_rate) * 100, 2) AS mention_rate,
                    ROUND(AVG(citation_share) * 100, 2) AS citation_share,
                    SUM(brand_citations) AS brand_cit
                FROM daily_metrics
                WHERE client_id = :cid
                  AND day >= :start AND day <= :end
                GROUP BY engine
                ORDER BY AVG(mention_rate) DESC
            """),
            {"cid": client_id, "start": period_start, "end": period_end},
        )
        engines = eng_res.all()

        # ── 4. Won gaps ──
        gap_res = await session.execute(
            text("""
                SELECT count(*) FROM gaps
                WHERE client_id = :cid AND status = 'won'
                  AND closed_at >= :start
            """),
            {"cid": client_id, "start": start_dt},
        )
        won_gaps = gap_res.scalar_one_or_none() or 0

        open_gap_res = await session.execute(
            text("SELECT count(*) FROM gaps WHERE client_id = :cid AND status = 'open'"),
            {"cid": client_id},
        )
        open_gaps = open_gap_res.scalar_one_or_none() or 0

        # ── 5. Content shipped ──
        content_res = await session.execute(
            text("""
                SELECT count(*) FROM content_items
                WHERE client_id = :cid AND status = 'published'
                  AND published_at >= :start
            """),
            {"cid": client_id, "start": start_dt},
        )
        content_shipped = content_res.scalar_one_or_none() or 0

        # Live verification stats
        verify_res = await session.execute(
            text("""
                SELECT
                    count(*) FILTER (WHERE status = 'succeeded') AS verified,
                    count(*) AS total
                FROM publications
                WHERE client_id = :cid
                  AND published_at >= :start
            """),
            {"cid": client_id, "start": start_dt},
        )
        vr = verify_res.one()
        verified = int(vr[0] or 0)
        total_pubs = int(vr[1] or 0)

        # ── 6. Competitor citation share ──
        comp_res = await session.execute(
            text("""
                SELECT c.name, count(bm.id) AS mentions
                FROM brand_mentions bm
                JOIN answers a ON a.id = bm.answer_id
                JOIN competitors c ON c.id = bm.competitor_id
                WHERE bm.client_id = :cid
                  AND bm.entity_kind = 'competitor'
                  AND a.collected_at >= :start
                GROUP BY c.name
                ORDER BY count(bm.id) DESC
                LIMIT 5
            """),
            {"cid": client_id, "start": start_dt},
        )
        competitors = comp_res.all()

        # ── Build Markdown memo ──
        mention_trend = f"+{mention_delta}" if mention_delta >= 0 else str(mention_delta)
        share_trend = f"+{share_delta}" if share_delta >= 0 else str(share_delta)

        engine_table = "| Engine | Mention Rate | Citation Share | Brand Citations |\n"
        engine_table += "|--------|-------------|---------------|----------------|\n"
        for e in engines:
            engine_table += f"| {e[0]} | {e[1]}% | {e[2]}% | {e[3] or 0} |\n"

        comp_table = ""
        if competitors:
            comp_table = "\n| Competitor | AI Mentions |\n|-----------|------------|\n"
            for c in competitors:
                comp_table += f"| {c[0]} | {c[1]} |\n"

        estimated_value = round(brand_citations * 2.50, 2)

        draft_md = f"""# Executive Monthly Memo: {client_name}
**Period**: {period_start} → {period_end} ({period_days} days)
**Generated**: {now.strftime('%B %d, %Y')}

---

## Executive Summary & Overall Health

{client_name} ({client_domain}) achieved a **{mention_rate}%** AI mention rate ({mention_trend}pp vs prior period) and **{citation_share}%** citation share ({share_trend}pp vs prior period) across all tracked AI engines.

- **AI Mentions Captured**: {brand_citations} brand citations out of {total_citations} total
- **Prompts With Visibility**: {total_visible} / {total_tracked} tracked
- **Estimated Referral Value**: ${estimated_value:,.2f}

---

## AI Engine Visibility Breakdown

{engine_table}

---

## Competitive Movements & Captured Territory

- **Gaps Won This Period**: {won_gaps}
- **Open Gaps Remaining**: {open_gaps}
{comp_table}

---

## Content & Off-Site Milestones

- **Content Pieces Published**: {content_shipped}
- **Publications Verified Live**: {verified} / {total_pubs}
- **Verification Rate**: {round(verified / total_pubs * 100, 1) if total_pubs else 0}%

---

## Strategic Recommendations for the Next 30 Days

1. {"**Accelerate content production** — current output is strong; maintain or increase cadence to capitalize on momentum." if content_shipped >= 3 else "**Scale content pipeline** — publish more pieces targeting open gaps to improve citation share."}
2. {"**Focus on citation defense** — citation share is declining; prioritize refresh of top-performing pages." if share_delta < 0 else "**Expand to new engines** — citation share is growing; consider targeting underperforming engines."}
3. **Close remaining {open_gaps} gaps** through targeted content and off-site authority building.
4. {"**Launch outreach campaign** — high-authority domains are citing competitors but not the brand." if won_gaps < open_gaps else "**Maintain outreach cadence** — gap closure rate is healthy."}

---

*This report was generated by Footnote's Executive Memo Engine. All metrics are sourced from live AI engine monitoring data.*
"""

        # ── Save memo to database ──
        memo_id = str(uuid4())
        metrics_json = {
            "mention_rate": mention_rate,
            "citation_share": citation_share,
            "mention_delta": mention_delta,
            "share_delta": share_delta,
            "brand_citations": brand_citations,
            "total_citations": total_citations,
            "won_gaps": won_gaps,
            "open_gaps": open_gaps,
            "content_shipped": content_shipped,
            "verified_publications": verified,
            "estimated_value": estimated_value,
        }

        await session.execute(
            text("""
                INSERT INTO memos
                    (id, client_id, title, period_start, period_end, metrics, draft_md, status)
                VALUES
                    (:id, :cid, :title, :pstart, :pend, :metrics, :draft, 'draft')
            """),
            {
                "id": memo_id,
                "cid": client_id,
                "title": f"Executive Monthly Memo: {client_name} ({period_start} → {period_end})",
                "pstart": period_start,
                "pend": period_end,
                "metrics": json.dumps(metrics_json),
                "draft": draft_md,
            },
        )

        # Create approval record
        approval_id = str(uuid4())
        await session.execute(
            text("""
                INSERT INTO approvals (id, client_id, subject_type, subject_id, status)
                VALUES (:id, :cid, 'memo', :subject_id, 'pending')
            """),
            {"id": approval_id, "cid": client_id, "subject_id": memo_id},
        )

        await session.commit()

    await engine.dispose()

    logger.info(
        "memo_generated",
        client_id=client_id,
        memo_id=memo_id,
        period=f"{period_start} → {period_end}",
    )

    return {
        "id": memo_id,
        "memo_id": memo_id,
        "approval_id": approval_id,
        "title": f"Executive Monthly Memo: {client_name} ({period_start} → {period_end})",
        "draft_md": draft_md,
        "metrics": metrics_json,
        "status": "draft",
    }
