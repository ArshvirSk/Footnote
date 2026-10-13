"""Content Refresh & Decay Detection Engine.

Scans published content for visibility decay signals (citation loss, slipped
gaps, temporal staleness) and creates refresh proposals with diagnostic data.
Runs as an in-process job or Arq cron task.

Decay score formula (0.0 → 1.0):
  citation_loss_weight * 0.45  +  slipped_gap_weight * 0.35  +  staleness_weight * 0.20
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

# Thresholds
DECAY_THRESHOLD = 0.40  # Score above which content is flagged for refresh
CITATION_DROP_THRESHOLD = 0.25  # 25% citation loss triggers decay signal
STALENESS_DAYS = 60  # Days without a refresh before staleness kicks in
SCAN_WINDOW_DAYS = 14  # Look-back window for citation comparison


async def _get_engine() -> AsyncEngine:
    """Get or create an async engine for direct DB access."""
    return create_async_engine(settings.database_url, echo=False)


async def scan_client_content(client_id: str | UUID) -> dict[str, Any]:
    """Scan all published content for a client and compute decay scores.

    Returns summary statistics: total scanned, flagged, proposals created.
    """
    client_id = str(client_id)
    engine = await _get_engine()
    stats = {"scanned": 0, "flagged": 0, "proposals_created": 0}

    async with AsyncSession(engine) as session:
        # Get published content items with their mapped prompts
        result = await session.execute(
            text("""
                SELECT
                    ci.id, ci.published_at, ci.last_refreshed_at,
                    ci.decay_score AS current_score,
                    ci.last_scanned_at,
                    array_agg(cpm.prompt_id) FILTER (WHERE cpm.prompt_id IS NOT NULL) AS prompt_ids
                FROM content_items ci
                LEFT JOIN content_prompt_map cpm ON cpm.content_item_id = ci.id
                WHERE ci.client_id = :cid
                  AND ci.status IN ('published', 'refresh_needed')
                GROUP BY ci.id
            """),
            {"cid": client_id},
        )
        items = result.all()
        now = datetime.now(UTC)

        for item in items:
            item_id = str(item[0])
            published_at = item[1]
            last_refreshed_at = item[2]
            prompt_ids = item[5] or []
            stats["scanned"] += 1

            # ── 1. Citation loss signal ──
            citation_loss_weight = 0.0
            if prompt_ids:
                cit_result = await session.execute(
                    text("""
                        WITH recent AS (
                            SELECT bm.answer_id
                            FROM brand_mentions bm
                            JOIN answers a ON a.id = bm.answer_id
                            WHERE bm.client_id = :cid
                              AND bm.entity_kind = 'brand'
                              AND a.prompt_id = ANY(:pids)
                              AND a.collected_at >= :recent_start
                        ),
                        historical AS (
                            SELECT bm.answer_id
                            FROM brand_mentions bm
                            JOIN answers a ON a.id = bm.answer_id
                            WHERE bm.client_id = :cid
                              AND bm.entity_kind = 'brand'
                              AND a.prompt_id = ANY(:pids)
                              AND a.collected_at >= :hist_start
                              AND a.collected_at < :recent_start
                        )
                        SELECT
                            (SELECT count(*) FROM recent) AS recent_count,
                            (SELECT count(*) FROM historical) AS hist_count
                    """),
                    {
                        "cid": client_id,
                        "pids": prompt_ids,
                        "recent_start": (now - timedelta(days=SCAN_WINDOW_DAYS)).isoformat(),
                        "hist_start": (now - timedelta(days=SCAN_WINDOW_DAYS * 2)).isoformat(),
                    },
                )
                cit_row = cit_result.one()
                recent_count = cit_row[0] or 0
                hist_count = cit_row[1] or 0
                if hist_count > 0:
                    drop_rate = 1.0 - (recent_count / hist_count)
                    if drop_rate >= CITATION_DROP_THRESHOLD:
                        citation_loss_weight = min(drop_rate, 1.0)

            # ── 2. Slipped gap signal ──
            slipped_weight = 0.0
            if prompt_ids:
                gap_result = await session.execute(
                    text("""
                        SELECT count(*) FROM gaps
                        WHERE client_id = :cid
                          AND prompt_id = ANY(:pids)
                          AND gap_type IN ('slipped', 'competitor_cited')
                          AND status = 'open'
                    """),
                    {"cid": client_id, "pids": prompt_ids},
                )
                open_gaps = gap_result.scalar_one_or_none() or 0
                if open_gaps > 0:
                    slipped_weight = min(open_gaps / 3.0, 1.0)  # Cap at 3 open gaps = full signal

            # ── 3. Staleness signal ──
            staleness_weight = 0.0
            last_touch = last_refreshed_at or published_at
            if last_touch:
                age_days = (now - last_touch).days if hasattr(last_touch, 'days') else (now.date() - last_touch.date()).days if hasattr(last_touch, 'date') else 0
                if age_days > STALENESS_DAYS:
                    staleness_weight = min((age_days - STALENESS_DAYS) / 120.0, 1.0)

            # ── Compute combined decay score ──
            decay_score = round(
                citation_loss_weight * 0.45
                + slipped_weight * 0.35
                + staleness_weight * 0.20,
                4,
            )

            # Update content item with computed score and scan timestamp
            await session.execute(
                text("""
                    UPDATE content_items
                    SET decay_score = :score,
                        last_scanned_at = :now,
                        status = CASE
                            WHEN :score > :threshold AND status = 'published' THEN 'refresh_needed'
                            ELSE status
                        END
                    WHERE id = :id AND client_id = :cid
                """),
                {
                    "score": decay_score,
                    "now": now.isoformat(),
                    "id": item_id,
                    "cid": client_id,
                    "threshold": DECAY_THRESHOLD,
                },
            )

            # If above threshold and not already flagged, create a refresh proposal
            if decay_score > DECAY_THRESHOLD:
                stats["flagged"] += 1

                # Check for existing pending proposal
                existing = await session.execute(
                    text("""
                        SELECT id FROM refresh_proposals
                        WHERE content_item_id = :item_id
                          AND client_id = :cid
                          AND status = 'pending'
                    """),
                    {"item_id": item_id, "cid": client_id},
                )
                if existing.scalar_one_or_none() is None:
                    proposal_id = str(uuid4())
                    reason = {
                        "citation_loss": round(citation_loss_weight, 4),
                        "slipped_gaps": round(slipped_weight, 4),
                        "staleness": round(staleness_weight, 4),
                        "total_decay": decay_score,
                    }

                    await session.execute(
                        text("""
                            INSERT INTO refresh_proposals (id, content_item_id, client_id, reason, status)
                            VALUES (:id, :item_id, :cid, :reason, 'pending')
                        """),
                        {
                            "id": proposal_id,
                            "item_id": item_id,
                            "cid": client_id,
                            "reason": json.dumps(reason),
                        },
                    )

                    # Create an approval record
                    await session.execute(
                        text("""
                            INSERT INTO approvals (id, client_id, subject_type, subject_id, status)
                            VALUES (:id, :cid, 'refresh', :subject_id, 'pending')
                        """),
                        {
                            "id": str(uuid4()),
                            "cid": client_id,
                            "subject_id": proposal_id,
                        },
                    )
                    stats["proposals_created"] += 1

                    logger.info(
                        "refresh_proposal_created",
                        content_item_id=item_id,
                        client_id=client_id,
                        decay_score=decay_score,
                        reason=reason,
                    )

        await session.commit()
    await engine.dispose()

    logger.info("refresh_scan_completed", client_id=client_id, **stats)
    return stats


async def approve_refresh_and_republish(
    proposal_id: str | UUID,
    client_id: str | UUID,
    reviewer_id: str | UUID | None = None,
) -> dict[str, Any]:
    """Handle approved refresh: swap version, enqueue republish.

    Called when an approval for subject_type='refresh' is approved.
    """
    proposal_id = str(proposal_id)
    client_id = str(client_id)
    now = datetime.now(UTC)
    engine = await _get_engine()

    async with AsyncSession(engine) as session:
        # Get the proposal
        prop_result = await session.execute(
            text("""
                SELECT content_item_id, proposed_version_id, status
                FROM refresh_proposals
                WHERE id = :pid AND client_id = :cid
            """),
            {"pid": proposal_id, "cid": client_id},
        )
        prop = prop_result.one_or_none()
        if not prop:
            return {"error": "Proposal not found"}

        content_item_id = str(prop[0])
        proposed_version_id = prop[1]

        # Mark proposal as approved
        await session.execute(
            text("""
                UPDATE refresh_proposals
                SET status = 'approved',
                    reviewer_id = :reviewer,
                    decided_at = :now
                WHERE id = :pid AND client_id = :cid
            """),
            {
                "pid": proposal_id,
                "cid": client_id,
                "reviewer": str(reviewer_id) if reviewer_id else None,
                "now": now.isoformat(),
            },
        )

        # If we have a proposed version, swap it to current
        if proposed_version_id:
            await session.execute(
                text("""
                    UPDATE content_items
                    SET current_version_id = :vid,
                        status = 'approved',
                        last_refreshed_at = :now,
                        decay_score = 0
                    WHERE id = :cid_item AND client_id = :cid
                """),
                {
                    "vid": str(proposed_version_id),
                    "cid_item": content_item_id,
                    "cid": client_id,
                    "now": now.isoformat(),
                },
            )

        # Transition content item back to approved for republishing
        await session.execute(
            text("""
                UPDATE content_items
                SET status = 'approved',
                    last_refreshed_at = :now,
                    decay_score = 0
                WHERE id = :item_id AND client_id = :cid
                  AND status = 'refresh_needed'
            """),
            {"item_id": content_item_id, "cid": client_id, "now": now.isoformat()},
        )

        await session.commit()

    await engine.dispose()

    logger.info(
        "refresh_approved",
        proposal_id=proposal_id,
        content_item_id=content_item_id,
        reviewer_id=str(reviewer_id) if reviewer_id else None,
    )

    return {
        "status": "approved",
        "content_item_id": content_item_id,
        "proposed_version_id": str(proposed_version_id) if proposed_version_id else None,
    }
