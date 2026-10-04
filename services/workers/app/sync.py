"""Sync workers for Google Search Console and GA4."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

from services.api.app.db import engine
from services.api.app.logging import get_logger
from sqlalchemy import text

logger = get_logger(__name__)

# Referrer patterns to classify traffic as AI referrals
AI_REFERRER_REGEX = r'(chatgpt\.com|perplexity\.ai|gemini\.google\.com|claude\.ai|grok\.com|copilot\.microsoft\.com)'


async def sync_gsc_data(ctx: dict[str, Any]) -> dict[str, str]:
    """Pull clicks and impressions from Google Search Console."""
    logger.info("sync_gsc_started")
    yesterday = date.today() - timedelta(days=1)

    async with engine.begin() as conn:
        # Get active GSC integrations
        res = await conn.execute(text("SELECT client_id FROM integrations WHERE provider = 'gsc' AND status = 'active'"))
        clients = res.fetchall()

        for (client_id,) in clients:
            # 1. Decrypt token and refresh if needed (mocked)
            # 2. Call Google Search Analytics API
            # 3. Store in gsc_daily and gsc_query_daily

            # Mocking the data insertion
            await conn.execute(
                text("""
                    INSERT INTO gsc_daily (client_id, day, clicks, impressions, ctr, position, aio_impressions)
                    VALUES (:cid, :day, 120, 1500, 0.08, 12.5, 300)
                    ON CONFLICT (client_id, day) DO UPDATE SET
                        clicks = EXCLUDED.clicks,
                        impressions = EXCLUDED.impressions
                """),
                {"cid": client_id, "day": yesterday.isoformat()}
            )

            # Update last synced
            await conn.execute(
                text("UPDATE integrations SET last_synced_at = now() WHERE client_id = :cid AND provider = 'gsc'"),
                {"cid": client_id}
            )

    logger.info("sync_gsc_completed")
    return {"status": "completed"}


async def sync_ga4_data(ctx: dict[str, Any]) -> dict[str, str]:
    """Pull session data and AI referrals from GA4."""
    logger.info("sync_ga4_started")
    yesterday = date.today() - timedelta(days=1)

    async with engine.begin() as conn:
        res = await conn.execute(text("SELECT client_id FROM integrations WHERE provider = 'ga4' AND status = 'active'"))
        clients = res.fetchall()

        for (client_id,) in clients:
            # 1. Call GA4 Data API filtering by source matching AI_REFERRER_REGEX
            # 2. Store in ga4_daily

            await conn.execute(
                text("""
                    INSERT INTO ga4_daily (client_id, day, source, medium, sessions, engaged_sessions, conversions)
                    VALUES (:cid, :day, 'chatgpt.com', 'referral', 45, 30, 2)
                    ON CONFLICT (client_id, day, source, medium) DO NOTHING
                """),
                {"cid": client_id, "day": yesterday.isoformat()}
            )

            await conn.execute(
                text("UPDATE integrations SET last_synced_at = now() WHERE client_id = :cid AND provider = 'ga4'"),
                {"cid": client_id}
            )

    logger.info("sync_ga4_completed")
    return {"status": "completed"}


async def send_weekly_digest(ctx: dict[str, Any]) -> dict[str, str]:
    """Generate and send weekly email digest to operators."""
    logger.info("weekly_digest_started")
    # Stub: query weekly metrics and gap counts, assemble HTML email, send via SMTP/Resend.
    await asyncio.sleep(0.1)
    logger.info("weekly_digest_completed")
    return {"status": "completed"}
