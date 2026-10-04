"""Arq worker configuration and task definitions.

Milestone 2 collection pipeline:

- **Schedule first**: every run gets an ``answers`` row with ``status='queued'``
  keyed by the idempotency key ``(client, prompt, engine, run_index, run_day)``,
  so "runs scheduled" is measurable, fan-out is deduplicated, and a second
  batch for the same day is a no-op.
- **Fan-out**: nightly batches with jittered enqueue delays, per-provider
  token buckets (in adapters), retries with exponential backoff, and a
  per-website daily call cap (``clients.settings.billing_limits.max_daily_calls``).
- **Explicit mock opt-in**: a missing provider key fails the run with an
  actionable error unless ``ALLOW_MOCK_ENGINES=true``.
- **Parse**: citations (adapter-normalized, regex fallback), domain taxonomy,
  brand judge (version recorded per answer) and competitor mentions.
- **Rollups**: daily_metrics, domain_citation_daily and gap/slip detection.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from datetime import UTC, date, datetime
from typing import Any, ClassVar
from uuid import uuid4

import httpx
from arq import cron
from arq.connections import RedisSettings
from services.api.app.config import settings
from services.api.app.db import engine
from services.api.app.logging import get_logger, setup_logging
from services.api.app.schemas import EngineType
from services.workers.app.adapters import EngineNotConfiguredError, get_adapter
from services.workers.app.embedder import embed_publication
from services.workers.app.parser import (
    classify_domain,
    extract_citations,
    find_mention,
    judge_mention,
    normalize_domain,
)
from services.workers.app.publisher import run_publisher, verify_publication
from services.workers.app.sync import send_weekly_digest, sync_ga4_data, sync_gsc_data
from sqlalchemy import text

logger = get_logger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
_DEFAULT_K_RUNS = 3


def _retry_base_delay(ctx: dict[str, Any]) -> float:
    """Seconds before the first retry (tests inject 0 to stay fast)."""
    return float(ctx.get("retry_base_delay_seconds", 2.0))


def _jitter(delay: float) -> float:
    if delay <= 0:
        return 0.0
    return delay + random.uniform(0.0, delay * 0.25)


# ───────────── Scheduling (FR-8) ─────────────

async def schedule_collection(
    ctx: dict[str, Any],
    client_id: str | None = None,
    *,
    prompt_id: str | None = None,
    day: str | None = None,
    trigger: str = "cron",
    jitter_seconds: float | None = None,
) -> dict[str, Any]:
    """Create/update the day's batch, insert queued answer rows, fan out jobs.

    Idempotency key: ``(client_id, prompt_id, engine, run_index, run_day)`` —
    a row already scheduled for today is never re-inserted or re-enqueued, so
    cron and manual triggers can overlap safely.

    ``trigger='cron'`` schedules the configured ``k`` runs per prompt/engine
    (default 3). ``trigger='manual'`` ("Run now") schedules those ``k`` runs
    when none exist for today, otherwise a single extra run per pair so fresh
    data is collected without destroying the day's earlier raw answers.
    """
    today_date = date.fromisoformat(day) if day else datetime.now(UTC).date()
    day_str = today_date.isoformat()
    if jitter_seconds is None:
        jitter_seconds = float(settings.collection_jitter_seconds)

    # 1. Prompts to schedule (active only; optionally one prompt / one client).
    query = (
        "SELECT p.id, p.client_id, p.text, p.engines, c.settings "
        "FROM prompts p JOIN clients c ON p.client_id = c.id WHERE p.is_active = true"
    )
    params: dict[str, Any] = {}
    if client_id:
        query += " AND p.client_id = :cid"
        params["cid"] = client_id
    if prompt_id:
        query += " AND p.id = :pid"
        params["pid"] = prompt_id

    async with engine.begin() as conn:
        rows = (await conn.execute(text(query), params)).all()

    by_client: dict[str, list[Any]] = {}
    for row in rows:
        by_client.setdefault(str(row.client_id), []).append(row)

    summary: dict[str, Any] = {
        "day": day_str,
        "trigger": trigger,
        "batches": [],
        "scheduled": 0,
        "already_scheduled": 0,
        "enqueued": 0,
        "skipped_cap": 0,
        "answers": [],
    }

    for cid, plist in by_client.items():
        client_settings = plist[0].settings or {}
        k_runs = int(client_settings.get("run_count", _DEFAULT_K_RUNS)) or _DEFAULT_K_RUNS
        geo = str(client_settings.get("geo", "IN"))
        billing = client_settings.get("billing_limits") or {}
        cap = int(billing.get("max_daily_calls", settings.default_daily_call_cap))

        async with engine.begin() as conn:
            # Batch row for (client, day).
            await conn.execute(
                text(
                    """
                    INSERT INTO collection_batches (id, client_id, scheduled_for, status, started_at, stats)
                    VALUES (:bid, :cid, :day, 'running', now(), '{}'::jsonb)
                    ON CONFLICT (client_id, scheduled_for) DO UPDATE
                    SET status = 'running',
                        stats = collection_batches.stats || EXCLUDED.stats
                    """
                ),
                {"bid": str(uuid4()), "cid": cid, "day": today_date},
            )
            batch_id = str(
                (
                    await conn.execute(
                        text("SELECT id FROM collection_batches WHERE client_id = :cid AND scheduled_for = :day"),
                        {"cid": cid, "day": today_date},
                    )
                ).scalar()
            )

            used_today = (
                await conn.execute(
                    text("SELECT COUNT(*) FROM answers WHERE client_id = :cid AND run_day = :day"),
                    {"cid": cid, "day": today_date},
                )
            ).scalar() or 0
            budget = max(0, int(cap) - int(used_today))

            # Which run indexes already exist today, per (prompt, engine).
            existing: dict[tuple[str, str], set[int]] = {}
            for r in (
                await conn.execute(
                    text(
                        "SELECT prompt_id, engine, array_agg(run_index) AS idxs "
                        "FROM answers WHERE client_id = :cid AND run_day = :day GROUP BY 1, 2"
                    ),
                    {"cid": cid, "day": today_date},
                )
            ).all():
                existing[(str(r.prompt_id), str(r.engine))] = set(r.idxs or [])

            inserted: list[dict[str, Any]] = []
            scheduled = already = skipped_cap = 0
            jobs: list[tuple[Any, ...]] = []

            for p in plist:
                pid = str(p.id)
                prompt_text = p.text
                for eng in p.engines:
                    engine_val = str(eng)
                    have = existing.get((pid, engine_val), set())
                    # Run now: one extra fresh run when today's runs already exist.
                    plan = [max(have) + 1] if trigger == "manual" and have else list(range(1, k_runs + 1))

                    for run_index in plan:
                        res = await conn.execute(
                            text(
                                """
                                INSERT INTO answers (id, batch_id, client_id, prompt_id, engine, mode,
                                    run_index, geo, status, run_day)
                                VALUES (:aid, :bid, :cid, :pid, :eng, 'api', :idx, :geo, 'queued', :day)
                                ON CONFLICT (client_id, prompt_id, engine, run_index, run_day)
                                    WHERE run_day IS NOT NULL DO NOTHING
                                RETURNING id
                                """
                            ),
                            {
                                "aid": str(uuid4()), "bid": batch_id, "cid": cid, "pid": pid,
                                "eng": engine_val, "idx": run_index, "geo": geo, "day": today_date,
                            },
                        )
                        inserted_row = res.first()
                        if inserted_row is None:
                            already += 1
                            continue
                        if scheduled >= budget:
                            # Over the daily call cap: drop the row we just added.
                            await conn.execute(
                                text(
                                    "DELETE FROM answers WHERE id = :aid AND status = 'queued'"
                                ),
                                {"aid": str(inserted_row.id)},
                            )
                            skipped_cap += 1
                            continue
                        scheduled += 1
                        answer_id = str(inserted_row.id)
                        inserted.append(
                            {
                                "answer_id": answer_id,
                                "prompt_id": pid,
                                "engine": engine_val,
                                "run_index": run_index,
                                "text": prompt_text,
                            }
                        )
                        jobs.append((batch_id, cid, pid, engine_val, run_index, prompt_text, geo, day_str))

            await conn.execute(
                text(
                    "UPDATE collection_batches SET stats = stats || CAST(:stats AS jsonb) WHERE id = :bid"
                ),
                {
                    "bid": batch_id,
                    "stats": json.dumps(
                        {
                            "trigger": trigger,
                            "scheduled": scheduled,
                            "already_scheduled": already,
                            "skipped_cap": skipped_cap,
                            "cap": cap,
                        }
                    ),
                },
            )

        # 2. Fan out with jittered delays; job id doubles as the dedupe key.
        enqueued = 0
        for i, job in enumerate(jobs):
            delay = random.uniform(0.0, jitter_seconds) if jitter_seconds else 0.0
            job_id = f"collect:{cid}:{job[2]}:{job[3]}:{day_str}:{job[4]}"
            await ctx["redis"].enqueue_job(
                "collect_and_parse", *job, _job_id=job_id, _defer_by=delay
            )
            enqueued += 1
            logger.info(
                "collect_enqueued",
                client_id=cid, prompt_id=job[2], engine=job[3], run_index=job[4],
                day=day_str, defer_s=round(delay, 2), seq=i,
            )

        summary["batches"].append(batch_id)
        summary["scheduled"] += scheduled
        summary["already_scheduled"] += already
        summary["enqueued"] += enqueued
        summary["skipped_cap"] += skipped_cap
        summary["answers"].extend(inserted)

    logger.info("schedule_collection_done", **{k: v for k, v in summary.items() if k != "answers"})
    return summary


async def run_daily_batch(
    ctx: dict[str, Any],
    client_id: str | None = None,
    *,
    jitter_seconds: float | None = None,
) -> dict[str, Any]:
    """Nightly cron entry: schedule + fan out today's batch for all clients.

    ``jitter_seconds`` defaults to ``settings.collection_jitter_seconds``; the
    Redis-less runner passes 0 for immediate local runs.
    """
    logger.info("daily_batch_started", client_id=client_id or "all")
    return await schedule_collection(ctx, client_id, trigger="cron", jitter_seconds=jitter_seconds)


# ───────────── Collection + parsing (FR-9, FR-11..FR-13) ─────────────

async def collect_and_parse(
    ctx: dict[str, Any],
    batch_id: str,
    client_id: str,
    prompt_id: str,
    engine_val: str,
    run_index: int,
    prompt_text: str,
    geo: str,
    day: str,
) -> None:
    """Collect one scheduled answer row and parse it (retries with backoff)."""
    run_day = date.fromisoformat(day)

    async with engine.begin() as conn:
        res = await conn.execute(
            text(
                "SELECT id, status, parsed_at FROM answers "
                "WHERE client_id = :cid AND prompt_id = :pid AND engine = :eng "
                "  AND run_index = :idx AND run_day = :day"
            ),
            {"cid": client_id, "pid": prompt_id, "eng": engine_val, "idx": run_index, "day": run_day},
        )
        row = res.first()
        if row is None:
            logger.warning("collect_missing_row", prompt_id=prompt_id, engine=engine_val, run_index=run_index)
            return
        answer_id = str(row.id)
        if row.status == "succeeded" and row.parsed_at is not None:
            logger.info("collect_idempotent_skip", answer_id=answer_id)
            return
        await conn.execute(text("UPDATE answers SET status = 'running' WHERE id = :aid"), {"aid": answer_id})

    # 1. Adapter (explicit: real key, mock opt-in, or a hard, actionable error).
    adapter = None
    error: str | None = None
    raw_answer = None
    attempts = 0
    mode = "api"
    start_time = time.time()
    try:
        adapter = get_adapter(EngineType(engine_val), ctx.get("redis"))
    except EngineNotConfiguredError as exc:
        error = str(exc)

    if adapter is not None:
        while attempts < MAX_ATTEMPTS:
            attempts += 1
            try:
                raw_answer = await adapter.ask(prompt_text, geo=geo, run_index=run_index)
                mode = adapter.mode
                error = None
                break
            except httpx.HTTPStatusError as exc:
                error = f"HTTP {exc.response.status_code}: {exc.response.text[:300]}"
                if exc.response.status_code not in RETRYABLE_STATUS:
                    break
            except httpx.TransportError as exc:
                error = f"{type(exc).__name__}: {exc}"
            except EngineNotConfiguredError as exc:
                error = str(exc)
                break
            except Exception as exc:  # record, don't crash the batch
                error = f"{type(exc).__name__}: {exc}"
                break
            if attempts < MAX_ATTEMPTS:
                await asyncio.sleep(_jitter(_retry_base_delay(ctx) * (2 ** (attempts - 1))))

    latency = int((time.time() - start_time) * 1000)
    status = "succeeded" if raw_answer is not None else "failed"
    if status == "failed" and not error:
        error = "empty answer"

    # 2. Persist the raw response (source of truth) on the scheduled row.
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                UPDATE answers SET status = :stat, mode = :mode, raw_text = :text, raw_json = :json,
                    model_label = :model, latency_ms = :lat, error = :err,
                    collected_at = now(), attempts = :attempts
                WHERE id = :aid
                """
            ),
            {
                "stat": status, "mode": mode,
                "text": raw_answer.text if raw_answer else None,
                "json": json.dumps(raw_answer.raw_json) if raw_answer else None,
                "model": raw_answer.model_label if raw_answer else None,
                "lat": latency, "err": error, "attempts": max(attempts, 1 if error else 0),
                "aid": answer_id,
            },
        )

    if raw_answer is None:
        logger.warning(
            "collect_failed", answer_id=answer_id, engine=engine_val,
            error=(error or "")[:200], attempts=attempts, latency_ms=latency,
        )
        return

    await _store_parsed_answer(answer_id=answer_id, client_id=client_id, raw_answer=raw_answer)
    logger.info(
        "collect_succeeded", answer_id=answer_id, engine=engine_val,
        model=raw_answer.model_label, attempts=attempts, latency_ms=latency,
        citations=len(raw_answer.citations),
    )


async def _store_parsed_answer(*, answer_id: str, client_id: str, raw_answer: Any) -> None:
    """Citations, domain taxonomy, brand judge + competitor mentions, parsed_at.

    Re-running a parse replaces the previous parsed rows for this answer
    (raw_json is never touched), so manual re-parses stay idempotent.
    """
    # Real adapters normalize provider citations into raw_answer.citations;
    # only fall back to generic extraction when the adapter didn't supply them.
    citations = raw_answer.citations or extract_citations(raw_answer.text, raw_answer.raw_json)

    async with engine.begin() as conn:
        meta_res = await conn.execute(
            text("SELECT name, primary_domain FROM clients WHERE id = :cid"), {"cid": client_id}
        )
        meta = meta_res.first()
        if not meta:
            return
        brand_name = meta.name
        brand_domain = normalize_domain(f"https://{meta.primary_domain}")

        alias_res = await conn.execute(
            text("SELECT alias FROM brand_aliases WHERE client_id = :cid"), {"cid": client_id}
        )
        aliases = [r.alias for r in alias_res.all()]

        comp_res = await conn.execute(
            text("SELECT id, name, domain, aliases FROM competitors WHERE client_id = :cid"),
            {"cid": client_id},
        )
        competitors = [
            (str(r.id), r.name, list(r.aliases or []), normalize_domain(f"https://{r.domain}") if r.domain else "")
            for r in comp_res.all()
        ]

        def _matches(domain: str, root: str) -> bool:
            return bool(root) and (domain == root or domain.endswith("." + root))

        # Idempotent re-parse: replace derived rows, keep the raw answer.
        await conn.execute(text("DELETE FROM answer_citations WHERE answer_id = :aid"), {"aid": answer_id})
        await conn.execute(text("DELETE FROM brand_mentions WHERE answer_id = :aid"), {"aid": answer_id})

        has_brand_citation = False
        for cit in citations:
            norm_domain = normalize_domain(cit["url"])
            await conn.execute(
                text("INSERT INTO domains (domain, domain_type) VALUES (:dom, :cls) ON CONFLICT (domain) DO NOTHING"),
                {"dom": norm_domain, "cls": classify_domain(norm_domain)},
            )
            res = await conn.execute(text("SELECT id FROM domains WHERE domain = :dom"), {"dom": norm_domain})
            domain_id = res.scalar()

            is_brand_owned = _matches(norm_domain, brand_domain)
            has_brand_citation = has_brand_citation or is_brand_owned
            competitor_id = next((cid for cid, _n, _a, cdom in competitors if cdom and _matches(norm_domain, cdom)), None)

            await conn.execute(
                text(
                    """
                    INSERT INTO answer_citations (answer_id, client_id, url, title, domain_id, position, is_brand_owned, competitor_id)
                    VALUES (:aid, :cid, :url, :title, :did, :pos, :owned, :comp)
                    """
                ),
                {
                    "aid": answer_id, "cid": client_id, "url": cit["url"], "title": cit.get("title", ""),
                    "did": str(domain_id), "pos": cit.get("position"),
                    "owned": is_brand_owned, "comp": str(competitor_id) if competitor_id else None,
                },
            )

        # Domain taxonomy (owned / competitor) so rollups and gap queries can use it.
        if brand_domain:
            await conn.execute(
                text(
                    """
                    UPDATE domains SET domain_type = 'owned'
                    WHERE domain_type = 'other' AND (domain = :d OR domain LIKE '%.' || :d)
                    """
                ),
                {"d": brand_domain},
            )
        for _cid, _name, _aliases, cdom in competitors:
            if not cdom:
                continue
            await conn.execute(
                text(
                    """
                    UPDATE domains SET domain_type = 'competitor'
                    WHERE domain_type <> 'owned' AND (domain = :d OR domain LIKE '%.' || :d)
                    """
                ),
                {"d": cdom},
            )

        # Brand mention via the configured judge (aliases + fuzzy variants included);
        # linked = the answer cites our own domain.
        judge_res = await judge_mention(raw_answer.text, brand_name, aliases)
        if judge_res:
            await conn.execute(
                text(
                    """
                    INSERT INTO brand_mentions (answer_id, client_id, entity_kind, rank_in_answer, linked, recommended, sentiment, excerpt)
                    VALUES (:aid, :cid, 'brand', :rank, :linked, :rec, :sent, :exc)
                    """
                ),
                {
                    "aid": answer_id, "cid": client_id, "rank": judge_res.rank_in_answer,
                    "linked": has_brand_citation, "rec": judge_res.recommended,
                    "sent": judge_res.sentiment, "exc": judge_res.excerpt,
                },
            )

        # Competitor mentions (needed for share of voice, FR-10/13).
        for competitor_id, name, comp_aliases, _cdom in competitors:
            if name == brand_name:
                continue
            hit = find_mention(raw_answer.text, name, *comp_aliases)
            if hit is None:
                continue
            await conn.execute(
                text(
                    """
                    INSERT INTO brand_mentions (answer_id, client_id, entity_kind, competitor_id, rank_in_answer, linked, recommended, excerpt)
                    VALUES (:aid, :cid, 'competitor', :comp, NULL, false, NULL, :exc)
                    """
                ),
                {"aid": answer_id, "cid": client_id, "comp": competitor_id, "exc": hit.excerpt},
            )

        await conn.execute(
            text("UPDATE answers SET parsed_at = now(), judge_version = :jv WHERE id = :aid"),
            {"aid": answer_id, "jv": judge_res.judge_version if judge_res else None},
        )


# ───────────── Batch finalization ─────────────

async def finalize_daily_batches(ctx: dict[str, Any], client_id: str | None = None) -> dict[str, str]:
    """Mark today's collection batches succeeded once their collect jobs finished."""
    day = datetime.now(UTC).date()
    async with engine.begin() as conn:
        query = (
            "UPDATE collection_batches SET status = 'succeeded', finished_at = now() "
            "WHERE scheduled_for = :day AND status = 'running'"
        )
        params: dict[str, Any] = {"day": day}
        if client_id:
            query += " AND client_id = :cid"
            params["cid"] = client_id
        result = await conn.execute(text(query), params)
    logger.info("daily_batches_finalized", rows=result.rowcount or 0, day=day.isoformat())
    return {"status": "finalized"}


# ───────────── Rollups (PRD 1.7) ─────────────

async def compute_rollup_for_day(day: str) -> dict[str, int]:
    """Roll up daily_metrics, domain_citation_daily and gaps for one UTC day (PRD 1.7).

    - prompt visible (day, engine): brand mentioned in >= 50% of that prompt's runs
    - mention rate: runs with a brand mention / total runs
    - linked rate: brand mentions linked to our domain / brand mentions
    - citation share: brand-owned citations / all citations (no join fan-out)
    - share of voice: brand mentions / (brand + competitor mentions)
    - avg sentiment: positive=1, mixed=0.5, neutral=0, negative=-1 (brand mentions)
    - slipped: visible in the previous 7-day window, not on this day
    - competitor_cited: competitor mentioned/cited while the brand is absent
    """
    stats: dict[str, int] = {}
    day_date = date.fromisoformat(day)  # asyncpg needs a real date for CAST($1 AS date)

    async with engine.begin() as conn:
        # 1. daily_metrics
        result = await conn.execute(
            text(
                """
                WITH runs AS (
                    SELECT a.client_id, a.prompt_id, a.engine,
                           COUNT(*) AS runs,
                           COUNT(*) FILTER (WHERE EXISTS (
                               SELECT 1 FROM brand_mentions bm
                               WHERE bm.answer_id = a.id AND bm.entity_kind = 'brand'
                           )) AS mentioned
                    FROM answers a
                    WHERE a.status = 'succeeded'
                      AND a.collected_at >= CAST(:day AS date)
                      AND a.collected_at < CAST(:day AS date) + 1
                    GROUP BY 1, 2, 3
                ),
                mention_stats AS (
                    SELECT a.client_id, a.engine,
                           COUNT(*) AS mentions,
                           COUNT(*) FILTER (WHERE bm.linked) AS linked,
                           AVG(CASE bm.sentiment WHEN 'positive' THEN 1.0
                                   WHEN 'mixed' THEN 0.5
                                   WHEN 'negative' THEN -1.0
                                   ELSE 0.0 END) AS avg_sentiment
                    FROM brand_mentions bm
                    JOIN answers a ON a.id = bm.answer_id
                    WHERE bm.entity_kind = 'brand'
                      AND a.collected_at >= CAST(:day AS date)
                      AND a.collected_at < CAST(:day AS date) + 1
                    GROUP BY 1, 2
                ),
                voice AS (
                    SELECT a.client_id, a.engine,
                           COUNT(*) FILTER (WHERE bm.entity_kind = 'brand') AS brand,
                           COUNT(*) FILTER (WHERE bm.entity_kind = 'competitor') AS competitor
                    FROM brand_mentions bm
                    JOIN answers a ON a.id = bm.answer_id
                    WHERE a.collected_at >= CAST(:day AS date)
                      AND a.collected_at < CAST(:day AS date) + 1
                    GROUP BY 1, 2
                ),
                cites AS (
                    SELECT a.client_id, a.engine,
                           COUNT(*) AS total,
                           COUNT(*) FILTER (WHERE ac.is_brand_owned) AS brand
                    FROM answer_citations ac
                    JOIN answers a ON a.id = ac.answer_id
                    WHERE a.collected_at >= CAST(:day AS date)
                      AND a.collected_at < CAST(:day AS date) + 1
                    GROUP BY 1, 2
                )
                INSERT INTO daily_metrics (
                    client_id, day, engine, prompts_tracked, prompts_visible,
                    mention_rate, linked_rate, brand_citations, total_citations,
                    citation_share, share_of_voice, avg_sentiment
                )
                SELECT
                    r.client_id, CAST(:day AS date), r.engine,
                    COUNT(*)::int,
                    COUNT(*) FILTER (WHERE r.mentioned * 2 >= r.runs)::int,
                    COALESCE(SUM(r.mentioned)::numeric / NULLIF(SUM(r.runs), 0), 0),
                    COALESCE(ms.linked::numeric / NULLIF(ms.mentions, 0), 0),
                    COALESCE(ct.brand, 0),
                    COALESCE(ct.total, 0),
                    COALESCE(ct.brand::numeric / NULLIF(ct.total, 0), 0),
                    COALESCE(v.brand::numeric / NULLIF(v.brand + v.competitor, 0), 0),
                    COALESCE(ms.avg_sentiment, 0)
                FROM runs r
                LEFT JOIN mention_stats ms ON ms.client_id = r.client_id AND ms.engine = r.engine
                LEFT JOIN voice v ON v.client_id = r.client_id AND v.engine = r.engine
                LEFT JOIN cites ct ON ct.client_id = r.client_id AND ct.engine = r.engine
                GROUP BY r.client_id, r.engine,
                         ms.linked, ms.mentions, ms.avg_sentiment,
                         v.brand, v.competitor, ct.brand, ct.total
                ON CONFLICT (client_id, day, engine) DO UPDATE SET
                    prompts_tracked = EXCLUDED.prompts_tracked,
                    prompts_visible = EXCLUDED.prompts_visible,
                    mention_rate = EXCLUDED.mention_rate,
                    linked_rate = EXCLUDED.linked_rate,
                    brand_citations = EXCLUDED.brand_citations,
                    total_citations = EXCLUDED.total_citations,
                    citation_share = EXCLUDED.citation_share,
                    share_of_voice = EXCLUDED.share_of_voice,
                    avg_sentiment = EXCLUDED.avg_sentiment
                """
            ),
            {"day": day_date},
        )
        stats["daily_metrics_rows"] = result.rowcount or 0

        # 2. domain_citation_daily
        result = await conn.execute(
            text(
                """
                INSERT INTO domain_citation_daily (client_id, day, domain_id, citations, is_brand)
                SELECT a.client_id, CAST(:day AS date), ac.domain_id,
                       COUNT(*)::int, BOOL_OR(ac.is_brand_owned)
                FROM answer_citations ac
                JOIN answers a ON a.id = ac.answer_id
                WHERE ac.domain_id IS NOT NULL
                  AND a.collected_at >= CAST(:day AS date)
                  AND a.collected_at < CAST(:day AS date) + 1
                GROUP BY 1, 3
                ON CONFLICT (client_id, day, domain_id) DO UPDATE SET
                    citations = EXCLUDED.citations,
                    is_brand = EXCLUDED.is_brand
                """
            ),
            {"day": day_date},
        )
        stats["domain_rollup_rows"] = result.rowcount or 0

        # 3. slipped gaps
        result = await conn.execute(
            text(
                """
                WITH today AS (
                    SELECT a.client_id, a.prompt_id, COUNT(*) AS runs,
                           COUNT(*) FILTER (WHERE EXISTS (
                               SELECT 1 FROM brand_mentions bm
                               WHERE bm.answer_id = a.id AND bm.entity_kind = 'brand'
                           )) AS mentioned
                    FROM answers a
                    WHERE a.status = 'succeeded'
                      AND a.collected_at >= CAST(:day AS date)
                      AND a.collected_at < CAST(:day AS date) + 1
                    GROUP BY 1, 2
                ),
                prior_days AS (
                    SELECT a.client_id, a.prompt_id, a.collected_at::date AS d,
                           COUNT(*) AS runs,
                           COUNT(*) FILTER (WHERE EXISTS (
                               SELECT 1 FROM brand_mentions bm
                               WHERE bm.answer_id = a.id AND bm.entity_kind = 'brand'
                           )) AS mentioned
                    FROM answers a
                    WHERE a.status = 'succeeded'
                      AND a.collected_at >= CAST(:day AS date) - 7
                      AND a.collected_at < CAST(:day AS date)
                    GROUP BY 1, 2, 3
                ),
                prior_visible AS (
                    SELECT DISTINCT client_id, prompt_id
                    FROM prior_days WHERE mentioned * 2 >= runs
                ),
                today_hidden AS (
                    SELECT client_id, prompt_id
                    FROM today WHERE mentioned * 2 < runs
                )
                INSERT INTO gaps (client_id, prompt_id, gap_type, details, status, detected_at)
                SELECT pv.client_id, pv.prompt_id, 'slipped',
                       jsonb_build_object('day', CAST(:day AS date)), 'open', now()
                FROM prior_visible pv
                JOIN today_hidden th ON th.client_id = pv.client_id AND th.prompt_id = pv.prompt_id
                WHERE NOT EXISTS (
                    SELECT 1 FROM gaps g
                    WHERE g.client_id = pv.client_id AND g.prompt_id = pv.prompt_id
                      AND g.gap_type = 'slipped' AND g.status = 'open'
                )
                """
            ),
            {"day": day_date},
        )
        stats["slipped_gaps"] = result.rowcount or 0

        # 4. competitor_cited gaps
        result = await conn.execute(
            text(
                """
                WITH comp_cited AS (
                    SELECT DISTINCT a.client_id, a.prompt_id
                    FROM answers a
                    WHERE a.status = 'succeeded'
                      AND a.collected_at >= CAST(:day AS date)
                      AND a.collected_at < CAST(:day AS date) + 1
                      AND (
                        EXISTS (SELECT 1 FROM brand_mentions bm
                                WHERE bm.answer_id = a.id AND bm.entity_kind = 'competitor')
                        OR EXISTS (SELECT 1 FROM answer_citations ac
                                   WHERE ac.answer_id = a.id AND ac.competitor_id IS NOT NULL)
                      )
                ),
                brand_present AS (
                    SELECT DISTINCT a.client_id, a.prompt_id
                    FROM answers a
                    WHERE a.status = 'succeeded'
                      AND a.collected_at >= CAST(:day AS date)
                      AND a.collected_at < CAST(:day AS date) + 1
                      AND (
                        EXISTS (SELECT 1 FROM brand_mentions bm
                                WHERE bm.answer_id = a.id AND bm.entity_kind = 'brand')
                        OR EXISTS (SELECT 1 FROM answer_citations ac
                                   WHERE ac.answer_id = a.id AND ac.is_brand_owned)
                      )
                )
                INSERT INTO gaps (client_id, prompt_id, gap_type, details, status, detected_at)
                SELECT cc.client_id, cc.prompt_id, 'competitor_cited',
                       jsonb_build_object('day', CAST(:day AS date)), 'open', now()
                FROM comp_cited cc
                WHERE NOT EXISTS (
                    SELECT 1 FROM brand_present bp
                    WHERE bp.client_id = cc.client_id AND bp.prompt_id = cc.prompt_id
                )
                AND NOT EXISTS (
                    SELECT 1 FROM gaps g
                    WHERE g.client_id = cc.client_id AND g.prompt_id = cc.prompt_id
                      AND g.gap_type = 'competitor_cited' AND g.status = 'open'
                )
                """
            ),
            {"day": day_date},
        )
        stats["competitor_gaps"] = result.rowcount or 0

    return stats


async def run_nightly_rollup(ctx: dict[str, Any]) -> dict[str, str]:
    """Compute daily metrics and gaps for the current UTC day."""
    logger.info("nightly_rollup_started")
    day = datetime.now(UTC).date().isoformat()
    stats = await compute_rollup_for_day(day)
    logger.info("nightly_rollup_completed", day=day, **stats)
    return {"status": "completed"}


async def startup(ctx: dict[str, Any]) -> None:
    setup_logging(settings.log_level)
    logger.info("worker_started", environment=settings.environment)


async def shutdown(ctx: dict[str, Any]) -> None:
    logger.info("worker_shutdown")


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    functions: ClassVar[list[Any]] = [
        run_daily_batch, schedule_collection, collect_and_parse, finalize_daily_batches, run_nightly_rollup,
        sync_gsc_data, sync_ga4_data, send_weekly_digest,
        run_publisher, verify_publication, embed_publication
    ]
    cron_jobs: ClassVar[list[Any]] = [
        cron(run_daily_batch, hour=0, minute=0, run_at_startup=False),
        cron(run_nightly_rollup, hour=6, minute=0, run_at_startup=False),
        cron(sync_gsc_data, hour=7, minute=0, run_at_startup=False),
        cron(sync_ga4_data, hour=7, minute=15, run_at_startup=False),
        cron(send_weekly_digest, weekday=0, hour=8, minute=0, run_at_startup=False),
    ]
    on_startup = startup
    on_shutdown = shutdown
    allow_abort_jobs = True
    max_jobs = 10
    job_timeout = 3600
