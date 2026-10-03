"""Arq worker configuration and task definitions for Phase 1.

Implements daily batch fan-out, engine collection, parsing, and rollups.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import text

from services.api.app.config import settings
from services.api.app.logging import get_logger, setup_logging
from services.api.app.db import engine
from services.api.app.schemas import EngineType
from services.workers.app.adapters import get_adapter
from services.workers.app.parser import extract_citations, evaluate_mention, normalize_domain
from services.workers.app.sync import sync_gsc_data, sync_ga4_data, send_weekly_digest
from services.workers.app.publisher import run_publisher, verify_publication
from services.workers.app.embedder import embed_publication

logger = get_logger(__name__)


async def collect_and_parse(ctx: dict[str, Any], batch_id: str, client_id: str, prompt_id: str, engine_val: str, run_index: int, prompt_text: str, geo: str) -> None:
    """Collect answer from engine and run parser."""
    logger.info("collecting", prompt_id=prompt_id, engine=engine_val, run_index=run_index)
    
    redis = ctx["redis"]
    adapter = get_adapter(EngineType(engine_val), redis)
    
    # 1. Collect
    start_time = time.time()
    try:
        raw_answer = await adapter.ask(prompt_text, geo=geo, run_index=run_index)
        error = None
        status = "succeeded"
    except Exception as e:
        raw_answer = None
        error = str(e)
        status = "failed"
    latency = int((time.time() - start_time) * 1000)

    # 2. Save Answer
    answer_id = str(uuid4())
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                INSERT INTO answers (id, batch_id, client_id, prompt_id, engine, mode, run_index, geo, status, raw_text, raw_json, model_label, latency_ms, error, collected_at)
                VALUES (:aid, :bid, :cid, :pid, :eng, :mode, :idx, :geo, :stat, :text, :json, :model, :lat, :err, now())
                ON CONFLICT (id) DO NOTHING
            """),
            {
                "aid": answer_id, "bid": batch_id, "cid": client_id, "pid": prompt_id, "eng": engine_val, 
                "mode": adapter.mode, "idx": run_index, "geo": geo, "stat": status,
                "text": raw_answer.text if raw_answer else None,
                "json": json.dumps(raw_answer.raw_json) if raw_answer else None,
                "model": raw_answer.model_label if raw_answer else None,
                "lat": latency, "err": error
            }
        )
    
    if status == "failed" or not raw_answer:
        return

    # 3. Parse Citations
    citations = extract_citations(raw_answer.text, raw_answer.raw_json)
    
    async with engine.begin() as conn:
        for cit in citations:
            norm_domain = normalize_domain(cit["url"])
            # Upsert domain
            await conn.execute(
                text("INSERT INTO domains (domain) VALUES (:dom) ON CONFLICT (domain) DO NOTHING"),
                {"dom": norm_domain}
            )
            res = await conn.execute(text("SELECT id FROM domains WHERE domain = :dom"), {"dom": norm_domain})
            domain_id = res.scalar()
            
            # Save answer_citation
            await conn.execute(
                text("""
                    INSERT INTO answer_citations (answer_id, client_id, url, title, domain_id, position)
                    VALUES (:aid, :cid, :url, :title, :did, :pos)
                """),
                {"aid": answer_id, "cid": client_id, "url": cit["url"], "title": cit["title"], "did": str(domain_id), "pos": cit["position"]}
            )

        # 4. Parse Mentions (LLM Judge)
        # Fetch brand info
        brand_res = await conn.execute(
            text("SELECT c.name FROM clients c WHERE c.id = :cid"), {"cid": client_id}
        )
        brand_name = brand_res.scalar()
        
        judge_res = await evaluate_mention(raw_answer.text, brand_name, [])
        if judge_res:
            await conn.execute(
                text("""
                    INSERT INTO brand_mentions (answer_id, client_id, entity_kind, rank_in_answer, recommended, sentiment, excerpt)
                    VALUES (:aid, :cid, 'brand', :rank, :rec, :sent, :exc)
                """),
                {
                    "aid": answer_id, "cid": client_id, "rank": judge_res.rank_in_answer,
                    "rec": judge_res.recommended, "sent": judge_res.sentiment, "exc": judge_res.excerpt
                }
            )
        
        # Mark parsed
        await conn.execute(text("UPDATE answers SET parsed_at = now() WHERE id = :aid"), {"aid": answer_id})
        

async def run_daily_batch(ctx: dict[str, Any], client_id: str | None = None) -> dict[str, str]:
    """Create batch and fan out collection jobs."""
    logger.info("daily_batch_started", client_id=client_id or "all")
    today = date.today().isoformat()
    
    async with engine.begin() as conn:
        # Get active prompts
        query = "SELECT p.id, p.client_id, p.text, p.engines, c.settings FROM prompts p JOIN clients c ON p.client_id = c.id WHERE p.is_active = true"
        if client_id:
            query += " AND p.client_id = :cid"
        
        res = await conn.execute(text(query), {"cid": client_id} if client_id else {})
        prompts = res.fetchall()

    for p in prompts:
        cid = str(p.client_id)
        pid = str(p.id)
        settings = p.settings or {}
        k_runs = settings.get("run_count", 3)
        geo = settings.get("geo", "IN")
        
        # Ensure batch exists for client+day
        async with engine.begin() as conn:
            batch_id = str(uuid4())
            await conn.execute(
                text("""
                    INSERT INTO collection_batches (id, client_id, scheduled_for, status, started_at)
                    VALUES (:bid, :cid, :day, 'running', now())
                    ON CONFLICT (client_id, scheduled_for) DO UPDATE SET status = 'running'
                    RETURNING id
                """),
                {"bid": batch_id, "cid": cid, "day": today}
            )
            res = await conn.execute(text("SELECT id FROM collection_batches WHERE client_id = :cid AND scheduled_for = :day"), {"cid": cid, "day": today})
            actual_batch_id = str(res.scalar())

        for eng in p.engines:
            for run_index in range(1, k_runs + 1):
                job_id = f"collect:{cid}:{pid}:{eng}:{today}:{run_index}"
                await ctx["redis"].enqueue_job(
                    "collect_and_parse",
                    actual_batch_id, cid, pid, eng, run_index, p.text, geo,
                    _job_id=job_id
                )

    return {"status": "fanned_out"}


async def run_nightly_rollup(ctx: dict[str, Any]) -> dict[str, str]:
    """Compute daily metrics and gaps."""
    logger.info("nightly_rollup_started")
    today = date.today().isoformat()
    
    async with engine.begin() as conn:
        # SQL Rollup into daily_metrics
        await conn.execute(text("""
            INSERT INTO daily_metrics (client_id, day, engine, prompts_tracked, prompts_visible, mention_rate, linked_rate, brand_citations, total_citations, citation_share, share_of_voice, avg_sentiment)
            SELECT 
                a.client_id, 
                :day as day, 
                a.engine,
                COUNT(DISTINCT a.prompt_id) as prompts_tracked,
                COUNT(DISTINCT CASE WHEN bm.id IS NOT NULL THEN a.prompt_id END) as prompts_visible,
                COUNT(bm.id)::numeric / GREATEST(COUNT(a.id), 1) as mention_rate,
                0 as linked_rate,
                COUNT(CASE WHEN ac.is_brand_owned THEN 1 END) as brand_citations,
                COUNT(ac.id) as total_citations,
                COUNT(CASE WHEN ac.is_brand_owned THEN 1 END)::numeric / GREATEST(COUNT(ac.id), 1) as citation_share,
                0 as share_of_voice,
                0 as avg_sentiment
            FROM answers a
            LEFT JOIN brand_mentions bm ON bm.answer_id = a.id AND bm.entity_kind = 'brand'
            LEFT JOIN answer_citations ac ON ac.answer_id = a.id
            WHERE DATE(a.collected_at) = :day
            GROUP BY a.client_id, a.engine
            ON CONFLICT (client_id, day, engine) DO UPDATE SET
                prompts_tracked = EXCLUDED.prompts_tracked,
                prompts_visible = EXCLUDED.prompts_visible,
                mention_rate = EXCLUDED.mention_rate,
                brand_citations = EXCLUDED.brand_citations,
                total_citations = EXCLUDED.total_citations,
                citation_share = EXCLUDED.citation_share
        """), {"day": today})

        # GAP DETECTION: Identify slips and new competitor gaps
        await conn.execute(text("""
            -- Slip detection: prompt was visible in last 7 days, but not today
            INSERT INTO gaps (client_id, prompt_id, gap_type, status, detected_at)
            SELECT dm.client_id, a.prompt_id, 'slipped', 'open', now()
            FROM daily_metrics dm
            JOIN answers a ON a.client_id = dm.client_id AND a.engine = dm.engine AND DATE(a.collected_at) = :day
            WHERE dm.day = :day AND dm.prompts_visible = 0
            AND EXISTS (
                SELECT 1 FROM daily_metrics dm2 
                WHERE dm2.client_id = dm.client_id AND dm2.day >= :day::date - interval '7 days' 
                AND dm2.prompts_visible > 0
            )
            ON CONFLICT DO NOTHING;
            
            -- Gap detection: Competitor was cited but brand was not
            INSERT INTO gaps (client_id, prompt_id, gap_type, status, detected_at)
            SELECT a.client_id, a.prompt_id, 'competitor_cited', 'open', now()
            FROM answers a
            JOIN answer_citations ac ON ac.answer_id = a.id
            JOIN domains d ON d.id = ac.domain_id
            WHERE DATE(a.collected_at) = :day 
              AND d.domain_type = 'competitor'
              AND NOT EXISTS (
                  SELECT 1 FROM answer_citations ac2 
                  WHERE ac2.answer_id = a.id AND ac2.is_brand_owned = true
              )
            ON CONFLICT DO NOTHING;
        """), {"day": today})
        
    return {"status": "completed"}


async def startup(ctx: dict[str, Any]) -> None:
    setup_logging(settings.log_level)
    logger.info("worker_started", environment=settings.environment)

async def shutdown(ctx: dict[str, Any]) -> None:
    logger.info("worker_shutdown")

class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    functions = [
        run_daily_batch, collect_and_parse, run_nightly_rollup, 
        sync_gsc_data, sync_ga4_data, send_weekly_digest,
        run_publisher, verify_publication, embed_publication
    ]
    cron_jobs = [
        cron(run_daily_batch, hour=0, minute=0, run_at_startup=False),
        cron(run_nightly_rollup, hour=6, minute=0, run_at_startup=False),
        cron(sync_gsc_data, hour=7, minute=0, run_at_startup=False),
        cron(sync_ga4_data, hour=7, minute=15, run_at_startup=False),
        cron(send_weekly_digest, day_of_week=0, hour=8, minute=0, run_at_startup=False),
    ]
    on_startup = startup
    on_shutdown = shutdown
    allow_abort_jobs = True
    max_jobs = 10
    job_timeout = 3600
