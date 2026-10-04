"""In-process job runner — executes worker jobs without Redis.

The Arq worker (``arq services.workers.app.worker.WorkerSettings``) is the
production path but needs a Redis server. This module runs the *same* job
functions in-process behind a duck-typed queue that stands in for
``ctx["redis"]``, so the daily batch -> collect -> parse pipeline and the
nightly rollup work on machines without Redis (local dev, CI, Windows).

Usage (from the repo root, PYTHONPATH=.):
  python -m services.workers.app.runner daily-batch [--client UUID] [--jitter SECONDS]
  python -m services.workers.app.runner run-now --client UUID [--prompt UUID]
  python -m services.workers.app.runner rollup [--day YYYY-MM-DD]
  python -m services.workers.app.runner all [--client UUID]   # batch then rollup

Add ``--mock`` to explicitly opt in to mock engines when provider keys are
missing (same as ``ALLOW_MOCK_ENGINES=true`` for this process).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from typing import Any

from services.api.app.config import settings
from services.api.app.db import engine
from services.api.app.logging import get_logger, setup_logging
from services.workers.app.worker import (
    compute_rollup_for_day,
    finalize_daily_batches,
    run_daily_batch,
    schedule_collection,
)

logger = get_logger(__name__)


class InProcessQueue:
    """Duck-typed stand-in for arq's Redis client in ``ctx["redis"]``.

    ``enqueue_job(name, *args, _defer_by=…)`` schedules the registered job
    function as an asyncio task in the current loop instead of pushing it to
    Redis; ``_defer_by`` is honoured with a real sleep so jittered fan-out
    behaves the same as the arq path. Tasks are tracked so callers can
    :meth:`drain` to wait for completion.
    """

    def __init__(self) -> None:
        self._tasks: list[asyncio.Task[Any]] = []

    async def enqueue_job(
        self,
        name: str,
        *args: Any,
        _job_id: str | None = None,
        _defer_by: float = 0.0,
        **kwargs: Any,
    ) -> None:
        from services.workers.app import worker as worker_mod

        func = getattr(worker_mod, name, None)
        if func is None or not callable(func):
            raise ValueError(f"Unknown job function: {name}")
        # arq control kwargs the in-process queue ignores (defer/id reuse)
        kwargs.pop("_expires", None)
        ctx = kwargs.pop("_ctx", None) or {"redis": self}
        delay = float(_defer_by or 0.0)

        async def _run() -> Any:
            if delay > 0:
                await asyncio.sleep(delay)
            return await func(ctx, *args)

        self._tasks.append(asyncio.create_task(_run()))

    async def drain(self) -> list[Any]:
        """Wait for all scheduled jobs; return results, re-raising failures."""
        results: list[Any] = []
        while self._tasks:
            pending = self._tasks
            self._tasks = []
            for task in asyncio.as_completed(pending):
                results.append(await task)
        return results


async def _run(args: argparse.Namespace) -> int:
    queue = InProcessQueue()
    ctx: dict[str, Any] = {
        "redis": queue,
        # Local/CLI runs retry quickly instead of waiting out production backoff.
        "retry_base_delay_seconds": 0.25,
    }
    failures = 0

    if args.command in ("daily-batch", "all"):
        result = await run_daily_batch(ctx, args.client, jitter_seconds=args.jitter)
        logger.info(
            "daily_batch_enqueued",
            scheduled=result.get("scheduled"),
            enqueued=result.get("enqueued"),
            skipped_cap=result.get("skipped_cap"),
        )
        try:
            await queue.drain()
            await finalize_daily_batches(ctx, args.client)
        except Exception:
            failures += 1
            logger.exception("collect_job_failed")

    if args.command == "run-now":
        result = await schedule_collection(
            ctx,
            args.client,
            prompt_id=args.prompt,
            trigger="manual",
            jitter_seconds=args.jitter,
        )
        logger.info(
            "run_now_scheduled",
            scheduled=result.get("scheduled"),
            enqueued=result.get("enqueued"),
            already_scheduled=result.get("already_scheduled"),
        )
        try:
            await queue.drain()
        except Exception:
            failures += 1
            logger.exception("collect_job_failed")

    if args.command in ("rollup", "all"):
        day = args.day or datetime.now(UTC).date().isoformat()
        stats = await compute_rollup_for_day(day)
        logger.info("rollup_completed", day=day, **stats)

    return 1 if failures else 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="worker-runner", description="Run Footnote worker jobs without Redis")
    sub = parser.add_subparsers(dest="command", required=True)

    p_batch = sub.add_parser("daily-batch", help="Fan out and run today's collection batch")
    p_batch.add_argument("--client", default=None, help="Limit to one client id")

    p_now = sub.add_parser("run-now", help="Manually collect now (one prompt or a whole website)")
    p_now.add_argument("--client", required=True, help="Client id to collect for")
    p_now.add_argument("--prompt", default=None, help="Limit to one prompt id")

    p_rollup = sub.add_parser("rollup", help="Compute daily metrics/gaps for a UTC day")
    p_rollup.add_argument("--day", default=None, help="YYYY-MM-DD (default: today UTC)")

    p_all = sub.add_parser("all", help="daily-batch then rollup")
    p_all.add_argument("--client", default=None, help="Limit to one client id")
    p_all.add_argument("--day", default=None, help="YYYY-MM-DD (default: today UTC)")

    for p in (p_batch, p_now, p_rollup, p_all):
        p.add_argument(
            "--jitter",
            type=float,
            default=0.0,
            help="Max enqueue jitter in seconds (default 0 for CLI; arq cron uses the settings value)",
        )
        p.add_argument(
            "--mock",
            action="store_true",
            help="Explicitly opt in to mock engines for this run (no provider keys needed)",
        )

    args = parser.parse_args(argv)
    if getattr(args, "mock", False):
        settings.allow_mock_engines = True
        logger_bootstrap = "mock_engines_opted_in"
    else:
        logger_bootstrap = "mock_engines_off"
    setup_logging(settings.log_level)
    logger.info(logger_bootstrap, allow_mock_engines=settings.allow_mock_engines)

    async def _wrapped() -> int:
        try:
            return await _run(args)
        finally:
            await engine.dispose()

    raise SystemExit(asyncio.run(_wrapped()))


if __name__ == "__main__":
    main(sys.argv[1:])
