"""Data retention and database maintenance service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from services.api.app.logging import get_logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


async def get_table_counts(db: AsyncSession) -> dict[str, int]:
    """Retrieve row counts for primary system tables for health and maintenance monitoring."""
    tables = [
        "answers",
        "collection_batches",
        "agent_runs",
        "audit_log",
        "content_items",
        "model_release_events",
        "prompts",
    ]
    counts: dict[str, int] = {}
    for tbl in tables:
        try:
            val = (await db.execute(text(f"SELECT COUNT(*) FROM {tbl}"))).scalar()
            counts[tbl] = int(val or 0)
        except Exception:
            counts[tbl] = 0
    return counts


async def prune_database_records(
    db: AsyncSession,
    failed_answers_days: int = 30,
    historical_answers_days: int = 365,
    agent_runs_days: int = 90,
    audit_logs_days: int = 180,
    client_id: UUID | None = None,
) -> dict[str, Any]:
    """Prune expired error logs, failed runs, and stale answers beyond retention thresholds.
    
    Preserves all aggregated daily metrics and content inventory.
    """
    now = datetime.now(UTC)
    failed_cutoff = now - timedelta(days=failed_answers_days)
    answers_cutoff = now - timedelta(days=historical_answers_days)
    runs_cutoff = now - timedelta(days=agent_runs_days)
    audit_cutoff = now - timedelta(days=audit_logs_days)

    params: dict[str, Any] = {
        "failed_cutoff": failed_cutoff,
        "answers_cutoff": answers_cutoff,
        "runs_cutoff": runs_cutoff,
        "audit_cutoff": audit_cutoff,
    }

    client_filter = ""
    if client_id:
        client_filter = " AND client_id = :cid"
        params["cid"] = str(client_id)

    # 1. Prune failed or error answers older than failed_answers_days
    q_failed_answers = f"""
        DELETE FROM answers
        WHERE status = 'failed'
          AND (collected_at < :failed_cutoff OR collected_at IS NULL)
          {client_filter}
    """
    res_failed = await db.execute(text(q_failed_answers), params)
    pruned_failed_answers = int(res_failed.rowcount or 0)

    # 2. Prune old historical answers older than historical_answers_days
    q_old_answers = f"""
        DELETE FROM answers
        WHERE collected_at < :answers_cutoff
          {client_filter}
    """
    res_old = await db.execute(text(q_old_answers), params)
    pruned_old_answers = int(res_old.rowcount or 0)

    # 3. Prune old agent runs older than agent_runs_days
    q_runs = f"""
        DELETE FROM agent_runs
        WHERE started_at < :runs_cutoff
          {client_filter}
    """
    res_runs = await db.execute(text(q_runs), params)
    pruned_runs = int(res_runs.rowcount or 0)

    # 4. Prune old audit logs older than audit_logs_days (if no client filter)
    pruned_audits = 0
    if not client_id:
        q_audits = """
            DELETE FROM audit_log
            WHERE at < :audit_cutoff
        """
        res_audits = await db.execute(text(q_audits), params)
        pruned_audits = int(res_audits.rowcount or 0)

    total_pruned = pruned_failed_answers + pruned_old_answers + pruned_runs + pruned_audits

    logger.info(
        "database_retention_prune_completed",
        total_pruned=total_pruned,
        failed_answers=pruned_failed_answers,
        old_answers=pruned_old_answers,
        agent_runs=pruned_runs,
        audit_logs=pruned_audits,
    )

    return {
        "pruned_failed_answers": pruned_failed_answers,
        "pruned_historical_answers": pruned_old_answers,
        "pruned_agent_runs": pruned_runs,
        "pruned_audit_logs": pruned_audits,
        "total_pruned": total_pruned,
        "retention_cutoffs": {
            "failed_answers_cutoff": failed_cutoff.isoformat(),
            "historical_answers_cutoff": answers_cutoff.isoformat(),
            "agent_runs_cutoff": runs_cutoff.isoformat(),
            "audit_logs_cutoff": audit_cutoff.isoformat(),
        },
    }
