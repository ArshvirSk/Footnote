"""Search Analytics routes for Google Search Console and GA4 AI referral attribution."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.app.auth import (
    AuthUser,
    get_current_user,
    has_client_access,
)
from services.api.app.db import get_db
from services.api.app.logging import get_logger
from services.api.app.search_analytics import (
    AIReferrerBreakdown,
    SearchSummary,
    SearchTimeseriesPoint,
    TopSearchQuery,
    get_ai_referral_breakdown,
    get_search_summary,
    get_search_timeseries,
    get_top_search_queries,
    seed_or_sync_client_search_data,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/clients/{client_id}/analytics/search", tags=["analytics"])


@router.get("/summary", response_model=SearchSummary)
async def search_summary(
    client_id: UUID,
    days: int = Query(30, ge=7, le=365),
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SearchSummary:
    """Get high-level Google Search Console and GA4 AI referral summary metrics."""
    await has_client_access(user, client_id, db)
    return await get_search_summary(db, client_id=client_id, days=days)


@router.get("/timeseries", response_model=list[SearchTimeseriesPoint])
async def search_timeseries(
    client_id: UUID,
    days: int = Query(30, ge=7, le=365),
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SearchTimeseriesPoint]:
    """Get daily performance trend combining GSC metrics and GA4 AI sessions."""
    await has_client_access(user, client_id, db)
    return await get_search_timeseries(db, client_id=client_id, days=days)


@router.get("/ai-referrals", response_model=list[AIReferrerBreakdown])
async def search_ai_referrals(
    client_id: UUID,
    days: int = Query(30, ge=7, le=365),
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AIReferrerBreakdown]:
    """Breakdown of incoming AI traffic by generative search engine provider."""
    await has_client_access(user, client_id, db)
    return await get_ai_referral_breakdown(db, client_id=client_id, days=days)


@router.get("/queries", response_model=list[TopSearchQuery])
async def search_queries(
    client_id: UUID,
    days: int = Query(30, ge=7, le=365),
    limit: int = Query(25, ge=1, le=100),
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TopSearchQuery]:
    """Get top performing organic search queries and correlate with tracked prompt sets."""
    await has_client_access(user, client_id, db)
    return await get_top_search_queries(db, client_id=client_id, days=days, limit=limit)


@router.post("/sync-now")
async def trigger_search_sync(
    client_id: UUID,
    days: int = Query(14, ge=1, le=90),
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Trigger an on-demand synchronization of search console and GA4 data."""
    await has_client_access(user, client_id, db)
    res = await seed_or_sync_client_search_data(db, client_id=client_id, days=days)
    await db.commit()
    return res
