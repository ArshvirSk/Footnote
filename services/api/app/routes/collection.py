"""Collection routes: Run now, collection health, per-prompt runs (Milestone 2).

- ``POST /clients/{id}/collection/run`` — manual trigger for one prompt or the
  whole website; schedules queued answer rows (idempotent per day) and fans the
  jobs out in-process, then returns what was scheduled.
- ``GET /clients/{id}/collection/health`` — runs succeeded / runs scheduled for
  a window, per engine, with the failed runs listed (error + attempts).
- ``GET /clients/{id}/prompts/{pid}/answers`` — every run with its raw answer,
  citations and mentions (FR-11).
- ``GET /clients/{id}/prompts/{pid}/series`` — daily runs/mentions for sparklines.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from services.api.app.auth import (
    AuthUser,
    MemberRole,
    get_current_user,
    has_client_access,
    require_roles,
)
from services.api.app.db import get_db
from services.api.app.logging import get_logger
from services.api.app.schemas import EngineType
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

router = APIRouter(prefix="/clients/{client_id}", tags=["collection"])

_ANSWERS_WINDOW_SQL = "coalesce(a.run_day, (a.collected_at AT TIME ZONE 'UTC')::date)"


def _window_start(days: int) -> date:
    """UTC window start — matches the UTC ``run_day`` the scheduler writes."""
    return datetime.now(UTC).date() - timedelta(days=max(1, days) - 1)


# ───────────── In-process job queue (Redis-less Run now) ─────────────

_queue: Any = None


def _get_queue() -> Any:
    global _queue
    if _queue is None:
        from services.workers.app.runner import InProcessQueue

        _queue = InProcessQueue()
    return _queue


async def _drain_queue() -> None:
    try:
        await _get_queue().drain()
    except Exception:  # individual runs record their own failures
        logger.exception("run_now_job_failed")


# ───────────── Run now ─────────────

class RunNowRequest(BaseModel):
    prompt_id: UUID | None = None


class ScheduledAnswer(BaseModel):
    answer_id: UUID
    prompt_id: UUID
    engine: EngineType
    run_index: int


class RunNowResponse(BaseModel):
    day: str
    trigger: str = "manual"
    scheduled: int
    already_scheduled: int
    enqueued: int
    skipped_cap: int
    answers: list[ScheduledAnswer]


@router.post("/collection/run", response_model=RunNowResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_collection_now(
    client_id: UUID,
    body: RunNowRequest,
    background: BackgroundTasks,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN, MemberRole.STRATEGIST))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RunNowResponse:
    """Collect now: one prompt when ``prompt_id`` is given, else the website.

    Today's runs are never overwritten — when the day's k runs already exist,
    one extra run index is scheduled per prompt/engine, so every raw answer
    stays intact (idempotency key: client, prompt, engine, run_index, day).
    """
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if body.prompt_id is not None:
        prompt = (
            await db.execute(
                text("SELECT 1 FROM prompts WHERE id = :pid AND client_id = :cid AND is_active = true"),
                {"pid": str(body.prompt_id), "cid": str(client_id)},
            )
        ).first()
        if prompt is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active prompt not found for this website")

    from services.workers.app.worker import schedule_collection

    summary = await schedule_collection(
        {"redis": _get_queue()},
        str(client_id),
        prompt_id=str(body.prompt_id) if body.prompt_id else None,
        trigger="manual",
        jitter_seconds=0.0,
    )
    background.add_task(_drain_queue)

    return RunNowResponse(
        day=str(summary["day"]),
        scheduled=int(summary["scheduled"]),
        already_scheduled=int(summary["already_scheduled"]),
        enqueued=int(summary["enqueued"]),
        skipped_cap=int(summary["skipped_cap"]),
        answers=[ScheduledAnswer(**a) for a in summary["answers"]],
    )


# ───────────── Collection health ─────────────

class EngineHealth(BaseModel):
    engine: EngineType
    scheduled: int
    succeeded: int
    failed: int
    queued: int


class FailedRun(BaseModel):
    answer_id: UUID
    prompt_id: UUID
    prompt_text: str | None
    engine: EngineType
    run_index: int
    day: str | None
    attempts: int
    error: str | None
    collected_at: str | None


class CollectionHealthResponse(BaseModel):
    client_id: UUID
    days: int
    scheduled: int
    succeeded: int
    failed: int
    queued: int
    running: int
    mock_runs: int
    rate: float | None
    per_engine: list[EngineHealth]
    failures: list[FailedRun]
    last_collection_at: str | None
    # True when runs are being served by the mock adapter (no provider keys).
    mock_mode: bool


@router.get("/collection/health", response_model=CollectionHealthResponse)
async def collection_health(
    client_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = 7,
) -> CollectionHealthResponse:
    """Collection health = runs succeeded / runs scheduled, failures listed."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    days = max(1, min(days, 90))
    start = _window_start(days)
    params = {"cid": str(client_id), "from": start}

    totals = (
        await db.execute(
            text(
                f"""
                SELECT COUNT(*) AS scheduled,
                       COUNT(*) FILTER (WHERE status = 'succeeded') AS succeeded,
                       COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                       COUNT(*) FILTER (WHERE status = 'queued') AS queued,
                       COUNT(*) FILTER (WHERE status = 'running') AS running,
                       COUNT(*) FILTER (WHERE raw_json->>'mock' = 'true') AS mock_runs,
                       MAX(collected_at) AS last_at
                FROM answers a
                WHERE a.client_id = :cid AND {_ANSWERS_WINDOW_SQL} >= :from
                """
            ),
            params,
        )
    ).one()

    per_engine_rows = (
        await db.execute(
            text(
                f"""
                SELECT engine,
                       COUNT(*) AS scheduled,
                       COUNT(*) FILTER (WHERE status = 'succeeded') AS succeeded,
                       COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                       COUNT(*) FILTER (WHERE status IN ('queued', 'running')) AS queued
                FROM answers a
                WHERE a.client_id = :cid AND {_ANSWERS_WINDOW_SQL} >= :from
                GROUP BY engine ORDER BY engine
                """
            ),
            params,
        )
    ).all()

    failure_rows = (
        await db.execute(
            text(
                f"""
                SELECT a.id, a.prompt_id, p.text AS prompt_text, a.engine, a.run_index,
                       a.attempts, a.error, a.status,
                       to_char(a.run_day, 'YYYY-MM-DD') AS day,
                       to_char(a.collected_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS collected_at
                FROM answers a
                LEFT JOIN prompts p ON p.id = a.prompt_id
                WHERE a.client_id = :cid AND a.status = 'failed' AND {_ANSWERS_WINDOW_SQL} >= :from
                ORDER BY a.collected_at DESC NULLS LAST, a.run_day DESC
                LIMIT 50
                """
            ),
            params,
        )
    ).all()

    scheduled = int(totals.scheduled or 0)
    succeeded = int(totals.succeeded or 0)

    from services.api.app.routes.websites import configured_engine_providers

    return CollectionHealthResponse(
        client_id=client_id,
        days=days,
        scheduled=scheduled,
        succeeded=succeeded,
        failed=int(totals.failed or 0),
        queued=int(totals.queued or 0),
        running=int(totals.running or 0),
        mock_runs=int(totals.mock_runs or 0),
        rate=(succeeded / scheduled if scheduled else None),
        per_engine=[
            EngineHealth(
                engine=EngineType(r.engine),
                scheduled=int(r.scheduled),
                succeeded=int(r.succeeded),
                failed=int(r.failed),
                queued=int(r.queued),
            )
            for r in per_engine_rows
        ],
        failures=[
            FailedRun(
                answer_id=r.id,
                prompt_id=r.prompt_id,
                prompt_text=r.prompt_text,
                engine=EngineType(r.engine),
                run_index=int(r.run_index),
                day=r.day,
                attempts=int(r.attempts or 0),
                error=r.error,
                collected_at=r.collected_at,
            )
            for r in failure_rows
        ],
        last_collection_at=str(totals.last_at) if totals.last_at else None,
        mock_mode=bool(not configured_engine_providers()),
    )


# ───────────── Prompt runs + series ─────────────

class CitationOut(BaseModel):
    url: str
    title: str | None
    position: int | None
    is_brand_owned: bool
    competitor_id: UUID | None


class MentionOut(BaseModel):
    entity_kind: str
    competitor_id: UUID | None
    recommended: bool | None
    sentiment: str | None
    linked: bool
    excerpt: str | None


class AnswerOut(BaseModel):
    id: UUID
    engine: EngineType
    run_index: int
    status: str
    geo: str | None
    day: str | None
    collected_at: str | None
    latency_ms: int | None
    model_label: str | None
    attempts: int
    error: str | None
    judge_version: str | None
    mock: bool
    raw_text: str | None
    citations: list[CitationOut]
    mentions: list[MentionOut]


class SeriesPoint(BaseModel):
    day: str
    runs: int
    mentioned: int


async def _require_prompt(db: AsyncSession, client_id: UUID, prompt_id: UUID) -> None:
    row = (
        await db.execute(
            text("SELECT 1 FROM prompts WHERE id = :pid AND client_id = :cid"),
            {"pid": str(prompt_id), "cid": str(client_id)},
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt not found")


@router.get("/prompts/{prompt_id}/answers", response_model=list[AnswerOut])
async def list_prompt_answers(
    client_id: UUID,
    prompt_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = 14,
    limit: int = 100,
) -> list[AnswerOut]:
    """Every run of one prompt with its raw answer, citations and mentions (FR-11)."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    await _require_prompt(db, client_id, prompt_id)

    days = max(1, min(days, 90))
    limit = max(1, min(limit, 300))
    start = _window_start(days)

    rows = (
        await db.execute(
            text(
                f"""
                SELECT id, engine, run_index, status, geo, raw_text, model_label, latency_ms,
                       error, attempts, judge_version, raw_json,
                       to_char(run_day, 'YYYY-MM-DD') AS day,
                       to_char(collected_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS collected_at
                FROM answers a
                WHERE a.client_id = :cid AND a.prompt_id = :pid AND {_ANSWERS_WINDOW_SQL} >= :from
                ORDER BY {_ANSWERS_WINDOW_SQL} DESC, a.run_index DESC, a.engine
                LIMIT :lim
                """
            ),
            {"cid": str(client_id), "pid": str(prompt_id), "from": start, "lim": limit},
        )
    ).all()
    if not rows:
        return []

    answer_ids = [str(r.id) for r in rows]
    cite_rows = (
        await db.execute(
            text(
                """
                SELECT answer_id, url, title, position, is_brand_owned, competitor_id
                FROM answer_citations
                WHERE answer_id IN :ids
                """
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": answer_ids},
        )
    ).all()
    mention_rows = (
        await db.execute(
            text(
                """
                SELECT answer_id, entity_kind, competitor_id, recommended, sentiment, linked, excerpt
                FROM brand_mentions
                WHERE answer_id IN :ids
                """
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": answer_ids},
        )
    ).all()

    cites_by_answer: dict[str, list[CitationOut]] = {aid: [] for aid in answer_ids}
    for c in cite_rows:
        cites_by_answer[str(c.answer_id)].append(
            CitationOut(
                url=c.url,
                title=c.title,
                position=int(c.position) if c.position is not None else None,
                is_brand_owned=bool(c.is_brand_owned),
                competitor_id=c.competitor_id,
            )
        )
    mentions_by_answer: dict[str, list[MentionOut]] = {aid: [] for aid in answer_ids}
    for m in mention_rows:
        mentions_by_answer[str(m.answer_id)].append(
            MentionOut(
                entity_kind=m.entity_kind,
                competitor_id=m.competitor_id,
                recommended=m.recommended,
                sentiment=m.sentiment,
                linked=bool(m.linked),
                excerpt=m.excerpt,
            )
        )

    out: list[AnswerOut] = []
    for r in rows:
        aid = str(r.id)
        out.append(
            AnswerOut(
                id=r.id,
                engine=EngineType(r.engine),
                run_index=int(r.run_index),
                status=r.status,
                geo=r.geo,
                day=r.day,
                collected_at=r.collected_at,
                latency_ms=r.latency_ms,
                model_label=r.model_label,
                attempts=int(r.attempts or 0),
                error=r.error,
                judge_version=r.judge_version,
                mock=bool((r.raw_json or {}).get("mock")) if isinstance(r.raw_json, dict) else False,
                raw_text=r.raw_text,
                citations=cites_by_answer.get(aid, []),
                mentions=mentions_by_answer.get(aid, []),
            )
        )
    return out


@router.get("/prompts/{prompt_id}/series", response_model=list[SeriesPoint])
async def prompt_series(
    client_id: UUID,
    prompt_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = 14,
) -> list[SeriesPoint]:
    """Daily succeeded runs and brand-mention counts for one prompt (sparkline)."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    await _require_prompt(db, client_id, prompt_id)

    days = max(1, min(days, 90))
    start = _window_start(days)
    rows = (
        await db.execute(
            text(
                f"""
                SELECT {_ANSWERS_WINDOW_SQL} AS day,
                       COUNT(*) AS runs,
                       COUNT(*) FILTER (WHERE EXISTS (
                           SELECT 1 FROM brand_mentions bm
                           WHERE bm.answer_id = a.id AND bm.entity_kind = 'brand'
                       )) AS mentioned
                FROM answers a
                WHERE a.client_id = :cid AND a.prompt_id = :pid AND a.status = 'succeeded'
                  AND {_ANSWERS_WINDOW_SQL} >= :from
                GROUP BY 1 ORDER BY 1
                """
            ),
            {"cid": str(client_id), "pid": str(prompt_id), "from": start},
        )
    ).all()
    return [
        SeriesPoint(day=str(r.day), runs=int(r.runs), mentioned=int(r.mentioned))
        for r in rows
    ]
