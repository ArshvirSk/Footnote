"""Edge search route: keyword search over published content for the Feeds edge proxy.

Service-to-service only: callers must present the shared edge service token.
The API's DB connection bypasses RLS (superuser), so tenant scoping is enforced
explicitly here via client_id filters plus the service token check.
"""

import hmac
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from services.api.app.config import settings
from services.api.app.db import get_db
from services.api.app.logging import get_logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

router = APIRouter(prefix="/clients/{client_id}/edge", tags=["edge"])


async def require_edge_service(
    x_internal_service: Annotated[str | None, Header()] = None,
) -> None:
    """Validate the edge worker's shared service token (service-to-service auth)."""
    if not settings.edge_service_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Edge service token not configured",
        )
    if not x_internal_service or not hmac.compare_digest(x_internal_service, settings.edge_service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid edge service credentials")


@router.get("/search")
async def edge_search(
    client_id: UUID,
    q: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_edge_service)],
) -> dict[str, Any]:
    """Keyword search over the client's published content, returned as a JSON-LD graph."""
    if not q:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing query parameter 'q'")

    pattern = f"%{q}%"
    res = await db.execute(
        text(
            """
            SELECT cv.title, ci.published_url, cv.body_md
            FROM content_items ci
            JOIN content_versions cv ON cv.id = ci.current_version_id
            WHERE ci.client_id = :cid
              AND ci.status = 'published'
              AND ci.published_url IS NOT NULL
              AND (cv.body_md ILIKE :pat OR cv.title ILIKE :pat)
            ORDER BY ci.published_at DESC NULLS LAST
            LIMIT 5
            """
        ),
        {"cid": str(client_id), "pat": pattern},
    )
    rows = res.fetchall()

    items = [
        {
            "@type": "Article",
            "headline": r.title,
            "url": r.published_url,
            "text": (r.body_md or "")[:2000],
        }
        for r in rows
    ]

    logger.info("edge_search_executed", client_id=str(client_id), query=q, matches=len(items))

    return {"@context": "https://schema.org", "@graph": items}
