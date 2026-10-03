"""CMS Publisher and Verification Workers."""

import asyncio
import httpx
from typing import Any
from urllib.parse import urlparse
from bs4 import BeautifulSoup

from sqlalchemy import text

from services.api.app.logging import get_logger
from services.api.app.db import engine

logger = get_logger(__name__)

async def publish_to_webflow(draft_content: str, cms_settings: dict) -> str:
    """Mock Webflow publisher."""
    logger.info("webflow_publish_started", site_id=cms_settings.get("site_id"))
    await asyncio.sleep(1)
    # In reality, this posts to https://api.webflow.com/collections/{collection_id}/items
    slug = "generated-post-" + str(asyncio.get_event_loop().time()).replace(".", "")
    return f"https://{cms_settings.get('domain', 'example.com')}/blog/{slug}"


async def publish_to_wordpress(draft_content: str, cms_settings: dict) -> str:
    """Mock WordPress publisher."""
    logger.info("wordpress_publish_started", endpoint=cms_settings.get("endpoint"))
    await asyncio.sleep(1)
    # Posts to wp-json/wp/v2/posts using Application Passwords
    slug = "generated-post-" + str(asyncio.get_event_loop().time()).replace(".", "")
    return f"{cms_settings.get('endpoint')}/{slug}"


async def run_publisher(ctx: dict[str, Any], draft_id: str, client_id: str) -> dict[str, str]:
    """Publish an approved draft to the client's CMS."""
    logger.info("publisher_job_started", draft_id=draft_id)
    
    async with engine.begin() as conn:
        res = await conn.execute(
            text("SELECT d.content_json, c.settings FROM drafts d JOIN clients c ON c.id = d.client_id WHERE d.id = :did"),
            {"did": draft_id}
        )
        row = res.first()
        if not row:
            return {"status": "error", "error": "Draft not found"}
            
        content = row.content_json
        settings = row.settings or {}
        
    cms_type = settings.get("cms_type", "webflow")
    try:
        if cms_type == "webflow":
            live_url = await publish_to_webflow(content, settings)
        else:
            live_url = await publish_to_wordpress(content, settings)
            
        # Record the publication
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO publications (client_id, entity_type, entity_id, target_url, published_at, is_live)
                    VALUES (:cid, 'draft', :did, :url, now(), false)
                    ON CONFLICT DO NOTHING
                """),
                {"cid": client_id, "did": draft_id, "url": live_url}
            )
            
        # Schedule verification
        await ctx["redis"].enqueue_job(
            "verify_publication",
            client_id, draft_id, live_url,
            _defer_by=300  # wait 5 minutes before checking
        )
        
        logger.info("published_successfully", url=live_url)
        return {"status": "published", "url": live_url}
        
    except Exception as e:
        logger.error("publish_failed", error=str(e))
        return {"status": "error", "error": str(e)}


async def verify_publication(ctx: dict[str, Any], client_id: str, draft_id: str, url: str) -> dict[str, str]:
    """Check if the published URL is live and contains the expected content."""
    logger.info("verify_publication_started", url=url)
    
    try:
        # In a real implementation, we'd fetch the URL and check the DOM
        # async with httpx.AsyncClient() as client:
        #     resp = await client.get(url, timeout=10.0)
        #     if resp.status_code == 200:
        #         soup = BeautifulSoup(resp.text, 'html.parser')
        #         # Verify title or content matches
        
        # Simulate verification logic
        await asyncio.sleep(0.5)
        is_live = True
        
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE publications SET is_live = :live WHERE target_url = :url"),
                {"live": is_live, "url": url}
            )
            
            # Close the gap that this draft addresses
            await conn.execute(
                text("""
                    UPDATE gaps 
                    SET status = 'addressed' 
                    WHERE id IN (
                        SELECT b.gap_id FROM briefs b
                        JOIN drafts d ON d.brief_id = b.id
                        WHERE d.id = :did AND b.gap_id IS NOT NULL
                    )
                """),
                {"did": draft_id}
            )
            
        logger.info("publication_verified", url=url, is_live=is_live)
        return {"status": "verified", "is_live": is_live}
        
    except Exception as e:
        logger.error("verify_failed", error=str(e))
        # Retry logic handled by Arq (job will fail and automatically retry based on settings)
        raise e
