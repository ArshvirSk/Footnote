"""Model release detection and engine prompt re-baselining service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from services.api.app.logging import get_logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# Known baseline catalog of LLM engine models and official announcement sources
DEFAULT_ENGINE_CATALOG: dict[str, list[dict[str, str]]] = {
    "chatgpt": [
        {"model_label": "gpt-4o", "source_url": "https://openai.com/index/hello-gpt-4o/"},
        {"model_label": "o3-mini", "source_url": "https://openai.com/index/openai-o3-mini/"},
        {"model_label": "gpt-4.5-preview", "source_url": "https://openai.com/index/introducing-gpt-4-5/"},
    ],
    "gemini": [
        {"model_label": "gemini-1.5-pro", "source_url": "https://deepmind.google/technologies/gemini/gemini-1-5/"},
        {"model_label": "gemini-2.0-flash", "source_url": "https://deepmind.google/technologies/gemini/flash/"},
        {"model_label": "gemini-2.5-pro", "source_url": "https://deepmind.google/technologies/gemini/"},
    ],
    "perplexity": [
        {"model_label": "sonar-medium", "source_url": "https://docs.perplexity.ai"},
        {"model_label": "sonar-pro", "source_url": "https://docs.perplexity.ai"},
        {"model_label": "sonar-deep-research", "source_url": "https://docs.perplexity.ai"},
    ],
    "claude": [
        {"model_label": "claude-3-5-sonnet", "source_url": "https://www.anthropic.com/news/claude-3-5-sonnet"},
        {"model_label": "claude-3-7-sonnet", "source_url": "https://www.anthropic.com/news/claude-3-7-sonnet"},
    ],
    "grok": [
        {"model_label": "grok-2", "source_url": "https://x.ai/blog/grok-2"},
        {"model_label": "grok-3", "source_url": "https://x.ai/blog/grok-3"},
    ],
    "google_aio": [
        {"model_label": "google-aio-gemini-v2", "source_url": "https://blog.google/products/search/"},
    ],
}


async def get_model_release_events(
    db: AsyncSession,
    limit: int = 50,
    engine: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve recorded model release events sorted by detection time descending."""
    query = """
        SELECT id, engine::text, model_label, detected_at, source_url
        FROM model_release_events
    """
    params: dict[str, Any] = {"limit": limit}
    if engine:
        query += " WHERE engine = :engine::engine_t"
        params["engine"] = engine
    query += " ORDER BY detected_at DESC LIMIT :limit"

    rows = (await db.execute(text(query), params)).mappings().all()
    return [
        {
            "id": str(r["id"]),
            "engine": r["engine"],
            "model_label": r["model_label"],
            "detected_at": r["detected_at"].isoformat() if r["detected_at"] else None,
            "source_url": r["source_url"],
        }
        for r in rows
    ]


async def detect_model_releases(
    db: AsyncSession,
    custom_candidates: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Scan provider models and answer logs to discover new or drifted model versions.
    
    Inserts newly discovered models into model_release_events.
    Returns the list of newly detected events.
    """
    # 1. Fetch currently recorded engine + model_label combinations
    existing_rows = (
        await db.execute(
            text("SELECT engine::text, model_label FROM model_release_events")
        )
    ).mappings().all()
    existing_set = {(r["engine"], r["model_label"]) for r in existing_rows}

    # 2. Gather candidates from default catalog + observed answers + custom candidates
    candidates: list[dict[str, str]] = []
    if custom_candidates:
        candidates.extend(custom_candidates)

    for eng, models in DEFAULT_ENGINE_CATALOG.items():
        for m in models:
            candidates.append({
                "engine": eng,
                "model_label": m["model_label"],
                "source_url": m.get("source_url", ""),
            })

    # Check observed answers in recent collection runs
    observed_rows = (
        await db.execute(
            text("""
                SELECT DISTINCT engine::text, model_label
                FROM answers
                WHERE model_label IS NOT NULL AND model_label <> ''
            """)
        )
    ).mappings().all()
    for obs in observed_rows:
        candidates.append({
            "engine": obs["engine"],
            "model_label": obs["model_label"],
            "source_url": "Observed via collection runner",
        })

    # 3. Filter for genuinely new releases
    new_events: list[dict[str, Any]] = []
    now = datetime.now(UTC)

    for c in candidates:
        eng = c.get("engine")
        label = c.get("model_label")
        url = c.get("source_url") or ""
        if not eng or not label:
            continue
        if (eng, label) in existing_set:
            continue

        # Insert new model release event
        event_id = uuid4()
        try:
            await db.execute(
                text("""
                    INSERT INTO model_release_events (id, engine, model_label, detected_at, source_url)
                    VALUES (:id, :engine::engine_t, :model_label, :detected_at, :source_url)
                """),
                {
                    "id": event_id,
                    "engine": eng,
                    "model_label": label,
                    "detected_at": now,
                    "source_url": url,
                },
            )
            existing_set.add((eng, label))
            new_events.append({
                "id": str(event_id),
                "engine": eng,
                "model_label": label,
                "detected_at": now.isoformat(),
                "source_url": url,
            })
            logger.info("Detected new model release", engine=eng, model_label=label)
        except Exception as e:
            logger.warning("Failed to insert model release event", error=str(e), engine=eng, model_label=label)

    return new_events


async def rebaseline_prompts(
    db: AsyncSession,
    engine: str | None = None,
    client_id: UUID | None = None,
    prompt_ids: list[UUID] | None = None,
) -> int:
    """Update last_baselined_at timestamp on prompts matching engine/client/ids.
    
    Returns the count of updated prompts.
    """
    clauses: list[str] = ["is_active = true"]
    params: dict[str, Any] = {"now": datetime.now(UTC)}

    if client_id:
        clauses.append("client_id = :client_id")
        params["client_id"] = str(client_id)

    if engine:
        clauses.append(":engine::engine_t = ANY(engines)")
        params["engine"] = engine

    if prompt_ids:
        clauses.append("id = ANY(:prompt_ids)")
        params["prompt_ids"] = [str(pid) for pid in prompt_ids]

    where_sql = " AND ".join(clauses)
    stmt = text(f"""
        UPDATE prompts
        SET last_baselined_at = :now
        WHERE {where_sql}
    """)

    result = await db.execute(stmt, params)
    return int(result.rowcount or 0)


async def get_model_drift_summary(
    db: AsyncSession,
    client_id: UUID | None = None,
) -> dict[str, Any]:
    """Calculate model release drift status, latest detections, and unbaselined prompt counts."""
    # 1. Total active prompts vs unbaselined prompts
    prompt_filter = "WHERE is_active = true"
    params: dict[str, Any] = {}
    if client_id:
        prompt_filter += " AND client_id = :cid"
        params["cid"] = str(client_id)

    prompt_counts = (
        await db.execute(
            text(f"""
                SELECT
                    COUNT(*) as total_active,
                    COUNT(*) FILTER (WHERE last_baselined_at IS NULL) as never_baselined,
                    COUNT(*) FILTER (WHERE last_baselined_at IS NOT NULL) as baselined
                FROM prompts
                {prompt_filter}
            """),
            params,
        )
    ).mappings().first()

    # 2. Latest model release event
    latest_event = (
        await db.execute(
            text("""
                SELECT id, engine::text, model_label, detected_at, source_url
                FROM model_release_events
                ORDER BY detected_at DESC
                LIMIT 1
            """)
        )
    ).mappings().first()

    # 3. Releases detected in the last 7 days
    recent_releases = (
        await db.execute(
            text("""
                SELECT COUNT(*) as recent_count
                FROM model_release_events
                WHERE detected_at >= NOW() - INTERVAL '7 days'
            """)
        )
    ).scalar() or 0

    return {
        "total_active_prompts": int(prompt_counts["total_active"] if prompt_counts else 0),
        "never_baselined_prompts": int(prompt_counts["never_baselined"] if prompt_counts else 0),
        "baselined_prompts": int(prompt_counts["baselined"] if prompt_counts else 0),
        "recent_releases_count": int(recent_releases),
        "has_unbaselined_drift": bool(prompt_counts and prompt_counts["never_baselined"] > 0),
        "latest_release": {
            "id": str(latest_event["id"]),
            "engine": latest_event["engine"],
            "model_label": latest_event["model_label"],
            "detected_at": latest_event["detected_at"].isoformat() if latest_event["detected_at"] else None,
            "source_url": latest_event["source_url"],
        } if latest_event else None,
    }
