"""Background worker daemon and scheduler.

Provides a resilient background automation runner without requiring external Redis
in self-hosted/local deployments. Orchestrates:
1. Daily prompt collection dispatch
2. Nightly rollups & gap calculations
3. Content decay scanning & refresh proposal generation
4. Model release drift detection
5. Data retention pruning
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from services.api.app.logging import get_logger
from services.api.app.model_detector import detect_model_releases
from services.api.app.retention import prune_database_records
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class DaemonScheduler:
    """Manages daemon state, task dispatches, and periodic cycle executions."""

    def __init__(self) -> None:
        self.started_at: datetime = datetime.now(UTC)
        self.is_active: bool = True
        self.last_run: dict[str, str] = {}
        self.task_counts: dict[str, int] = {
            "daily_batch": 0,
            "nightly_rollup": 0,
            "decay_scan": 0,
            "model_release_check": 0,
            "retention_prune": 0,
        }
        self.last_errors: dict[str, str] = {}
        self.queue_depth: int = 0

    def get_status(self) -> dict[str, Any]:
        """Return operational telemetry, uptime, and last-run timestamps."""
        uptime_seconds = int((datetime.now(UTC) - self.started_at).total_seconds())
        return {
            "status": "active" if self.is_active else "paused",
            "uptime_seconds": uptime_seconds,
            "started_at": self.started_at.isoformat(),
            "last_run": self.last_run,
            "task_counts": self.task_counts,
            "last_errors": self.last_errors,
            "queue_depth": self.queue_depth,
            "supported_tasks": [
                "daily_batch",
                "nightly_rollup",
                "decay_scan",
                "model_release_check",
                "retention_prune",
            ],
        }

    async def execute_task(self, task_name: str, db: AsyncSession) -> dict[str, Any]:
        """Execute a single named background task safely and update state."""
        now_iso = datetime.now(UTC).isoformat()
        res: dict[str, Any] = {"task": task_name, "status": "succeeded", "executed_at": now_iso}

        try:
            if task_name == "daily_batch":
                # Ensure today's collection batches exist for active clients
                today = date.today()
                client_rows = (
                    await db.execute(
                        text("SELECT id FROM clients WHERE status IN ('active', 'onboarding')")
                    )
                ).mappings().all()

                created_batches = 0
                for c in client_rows:
                    cid = c["id"]
                    # Insert batch if not already present
                    ins = await db.execute(
                        text("""
                            INSERT INTO collection_batches (client_id, scheduled_for, status)
                            VALUES (:cid, :today, 'queued')
                            ON CONFLICT (client_id, scheduled_for) DO NOTHING
                        """),
                        {"cid": str(cid), "today": today},
                    )
                    if ins.rowcount and ins.rowcount > 0:
                        created_batches += 1
                res["created_batches"] = created_batches
                res["clients_checked"] = len(client_rows)

            elif task_name == "nightly_rollup":
                # Aggregate daily metric rows for completed batches
                today = date.today()
                rollup_res = await db.execute(
                    text("""
                        INSERT INTO daily_metrics (
                            client_id, day, prompt_count, share_of_voice_pct,
                            avg_sentiment, verified_citations_count
                        )
                        SELECT
                            c.id,
                            :today,
                            COUNT(p.id) as prompt_count,
                            0.0,
                            0.0,
                            0
                        FROM clients c
                        LEFT JOIN prompts p ON p.client_id = c.id AND p.is_active = true
                        WHERE c.status IN ('active', 'onboarding')
                        GROUP BY c.id
                        ON CONFLICT (client_id, day) DO UPDATE
                        SET prompt_count = EXCLUDED.prompt_count
                    """),
                    {"today": today},
                )
                res["rollups_updated"] = rollup_res.rowcount or 0

            elif task_name == "decay_scan":
                # Scan published content for decay
                client_rows = (
                    await db.execute(
                        text("SELECT id FROM clients WHERE status IN ('active', 'onboarding')")
                    )
                ).mappings().all()

                from services.workers.app.refresh_scanner import scan_client_content

                scanned_total = 0
                flagged_total = 0
                proposals_total = 0
                for c in client_rows:
                    try:
                        scan_res = await scan_client_content(c["id"])
                        scanned_total += scan_res.get("scanned", 0)
                        flagged_total += scan_res.get("flagged", 0)
                        proposals_total += scan_res.get("proposals_created", 0)
                    except Exception as scan_err:
                        logger.warning("decay_scan_client_failed", client_id=str(c["id"]), error=str(scan_err))

                res["clients_scanned"] = len(client_rows)
                res["content_scanned"] = scanned_total
                res["content_flagged"] = flagged_total
                res["proposals_created"] = proposals_total

            elif task_name == "model_release_check":
                # Check for model releases
                new_events = await detect_model_releases(db)
                res["new_models_detected"] = len(new_events)
                res["events"] = new_events

            elif task_name == "retention_prune":
                # Prune old mock/failed answers and expired agent runs
                prune_res = await prune_database_records(db)
                res["prune_results"] = prune_res

            else:
                res["status"] = "skipped"
                res["message"] = f"Unknown task: {task_name}"

            # Update success counters
            self.last_run[task_name] = now_iso
            self.task_counts[task_name] = self.task_counts.get(task_name, 0) + 1
            if task_name in self.last_errors:
                del self.last_errors[task_name]

        except Exception as e:
            logger.error("daemon_task_failed", task=task_name, error=str(e))
            res["status"] = "failed"
            res["error"] = str(e)
            self.last_errors[task_name] = str(e)

        return res

    async def run_cycle(
        self,
        db: AsyncSession,
        tasks: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run a full scheduled cycle or a specific subset of tasks."""
        if tasks is None:
            tasks = ["daily_batch", "nightly_rollup", "decay_scan", "model_release_check", "retention_prune"]

        results: dict[str, Any] = {}
        for t in tasks:
            results[t] = await self.execute_task(t, db)

        await db.commit()
        return {
            "cycle_status": "completed",
            "executed_at": datetime.now(UTC).isoformat(),
            "tasks": results,
        }


# Global singleton instance
daemon_instance = DaemonScheduler()


def get_daemon_status() -> dict[str, Any]:
    """Retrieve the singleton daemon's operational status."""
    return daemon_instance.get_status()


async def execute_daemon_cycle(
    db: AsyncSession,
    tasks: list[str] | None = None,
) -> dict[str, Any]:
    """Execute maintenance cycle through the singleton daemon."""
    return await daemon_instance.run_cycle(db, tasks=tasks)
