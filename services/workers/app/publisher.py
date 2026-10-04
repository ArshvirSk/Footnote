"""CMS Publisher and Verification Workers.

Phase 1/4 state: CMS calls are still mocked (clearly marked), but all database
writes target the real schema (content_items, publications, content_prompt_map, gaps).
"""

import asyncio
from typing import Any

import httpx
from services.api.app.db import engine
from services.api.app.logging import get_logger
from sqlalchemy import text

logger = get_logger(__name__)


async def publish_to_webflow(draft_content: str, cms_settings: dict[str, Any]) -> str:
    """Mock Webflow publisher (real API lands in Phase 4)."""
    logger.info("webflow_publish_started", site_id=cms_settings.get("site_id"))
    await asyncio.sleep(1)
    # In reality, this posts to https://api.webflow.com/collections/{collection_id}/items
    slug = "generated-post-" + str(asyncio.get_event_loop().time()).replace(".", "")
    return f"https://{cms_settings.get('domain', 'example.com')}/blog/{slug}"


async def publish_to_wordpress(draft_content: str, cms_settings: dict[str, Any]) -> str:
    """Mock WordPress publisher (real REST + application passwords lands in Phase 4)."""
    logger.info("wordpress_publish_started", endpoint=cms_settings.get("endpoint"))
    await asyncio.sleep(1)
    # Posts to wp-json/wp/v2/posts using Application Passwords
    slug = "generated-post-" + str(asyncio.get_event_loop().time()).replace(".", "")
    return f"{cms_settings.get('endpoint', '')}/{slug}"


async def run_publisher(ctx: dict[str, Any], draft_id: str, client_id: str) -> dict[str, str]:
    """Publish the current version of a content item to the client's CMS.

    ``draft_id`` is a ``content_items.id``.
    """
    logger.info("publisher_job_started", content_item_id=draft_id)

    async with engine.begin() as conn:
        res = await conn.execute(
            text(
                """
                SELECT ci.current_version_id, ci.publish_target_id, cv.body_md, c.settings
                FROM content_items ci
                JOIN clients c ON c.id = ci.client_id
                LEFT JOIN content_versions cv ON cv.id = ci.current_version_id
                WHERE ci.id = :did AND ci.client_id = :cid
                """
            ),
            {"did": draft_id, "cid": client_id},
        )
        row = res.first()
        if not row or not row.current_version_id:
            return {"status": "error", "error": "Content item or version not found"}

        content = row.body_md or ""
        client_settings = row.settings or {}
        target_id = row.publish_target_id
        version_id = row.current_version_id

    cms_type = client_settings.get("cms_type", "wordpress")
    try:
        if cms_type == "webflow":
            live_url = await publish_to_webflow(content, client_settings)
        else:
            live_url = await publish_to_wordpress(content, client_settings)

        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO publications (content_item_id, client_id, version_id, target_id, url, status, published_at)
                    VALUES (:did, :cid, :vid, :tid, :url, 'running', now())
                    """
                ),
                {"did": draft_id, "cid": client_id, "vid": str(version_id), "tid": str(target_id), "url": live_url},
            )
            await conn.execute(
                text(
                    """
                    UPDATE content_items
                    SET published_url = :url, published_at = now(), status = 'published'
                    WHERE id = :did AND client_id = :cid
                    """
                ),
                {"url": live_url, "did": draft_id, "cid": client_id},
            )

        await ctx["redis"].enqueue_job(
            "verify_publication",
            client_id,
            draft_id,
            live_url,
            _defer_by=300,  # wait 5 minutes before checking
        )

        logger.info("published_successfully", url=live_url)
        return {"status": "published", "url": live_url}

    except Exception as e:
        logger.error("publish_failed", error=str(e))
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO publications (content_item_id, client_id, version_id, target_id, url, status, error)
                    VALUES (:did, :cid, :vid, :tid, NULL, 'failed', :err)
                    """
                ),
                {"did": draft_id, "cid": client_id, "vid": str(version_id), "tid": str(target_id), "err": str(e)},
            )
        return {"status": "error", "error": str(e)}


async def verify_publication(ctx: dict[str, Any], client_id: str, draft_id: str, url: str) -> dict[str, str]:
    """Check that the published URL is live, then close the gaps this item addresses."""
    logger.info("verify_publication_started", url=url)

    try:
        is_live = False
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url)
            is_live = resp.status_code == 200

        if not is_live:
            raise RuntimeError(f"Published URL not live (status {resp.status_code})")

        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    UPDATE publications
                    SET status = 'succeeded'
                    WHERE content_item_id = :did AND client_id = :cid AND url = :url
                    """
                ),
                {"did": draft_id, "cid": client_id, "url": url},
            )

            # Close open gaps this content item maps to via content_prompt_map.
            await conn.execute(
                text(
                    """
                    UPDATE gaps
                    SET status = 'won', closed_at = now()
                    WHERE client_id = :cid
                      AND status = 'open'
                      AND prompt_id IN (
                        SELECT prompt_id FROM content_prompt_map WHERE content_item_id = :did
                      )
                    """
                ),
                {"cid": client_id, "did": draft_id},
            )

        logger.info("publication_verified", url=url, is_live=True)
        return {"status": "verified", "is_live": "true"}

    except Exception as e:
        logger.error("verify_failed", error=str(e))
        # Arq retries the job; it fails and retries based on worker settings.
        raise
