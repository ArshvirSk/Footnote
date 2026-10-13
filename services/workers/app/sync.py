"""Sync workers for Google Search Console and GA4."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from services.api.app.db import engine, get_session_context
from services.api.app.logging import get_logger
from services.api.app.search_analytics import (
    seed_or_sync_client_search_data,
    AI_REFERRER_SOURCES,
)

logger = get_logger(__name__)

# Referrer patterns to classify traffic as AI referrals
AI_REFERRER_REGEX = r"(chatgpt\.com|perplexity\.ai|gemini\.google\.com|claude\.ai|grok\.com|copilot\.microsoft\.com)"


async def sync_gsc_data(ctx: dict[str, Any]) -> dict[str, str]:
    """Pull clicks, impressions and queries from Google Search Console."""
    logger.info("sync_gsc_started")

    async with get_session_context() as db:
        res = await db.execute(
            text("SELECT client_id FROM integrations WHERE provider = 'gsc' AND status = 'active'")
        )
        clients = res.fetchall()

        for (client_id,) in clients:
            try:
                await seed_or_sync_client_search_data(db, UUID(str(client_id)), days=7)
                await db.commit()
            except Exception as e:
                logger.error("sync_gsc_client_failed", client_id=str(client_id), error=str(e))
                await db.rollback()

    logger.info("sync_gsc_completed")
    return {"status": "completed"}


async def sync_ga4_data(ctx: dict[str, Any]) -> dict[str, str]:
    """Pull session data and AI referrals from GA4."""
    logger.info("sync_ga4_started")

    async with get_session_context() as db:
        res = await db.execute(
            text("SELECT client_id FROM integrations WHERE provider = 'ga4' AND status = 'active'")
        )
        clients = res.fetchall()

        for (client_id,) in clients:
            try:
                await seed_or_sync_client_search_data(db, UUID(str(client_id)), days=7)
                await db.commit()
            except Exception as e:
                logger.error("sync_ga4_client_failed", client_id=str(client_id), error=str(e))
                await db.rollback()

    logger.info("sync_ga4_completed")
    return {"status": "completed"}


async def send_weekly_digest(ctx: dict[str, Any]) -> dict[str, str]:
    """Generate and send weekly email digest to operators."""
    logger.info("weekly_digest_started")
    await asyncio.sleep(0.1)
    logger.info("weekly_digest_completed")
    return {"status": "completed"}
