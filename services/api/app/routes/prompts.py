"""Prompts CRUD + enriched list (sparkline, per-engine status) routes."""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

router = APIRouter(prefix="/clients/{client_id}/prompts", tags=["prompts"])


MAX_ACTIVE_PROMPTS = 125


class PromptCreateRequest(BaseModel):
    text: str
    kind: str = "ai_prompt"
    funnel_stage: str | None = None
    lead_intent_score: int | None = None
    engines: list[EngineType] = [EngineType.CHATGPT, EngineType.GEMINI, EngineType.PERPLEXITY, EngineType.GROK]
    source: str | None = "manual"
    persona_id: UUID | None = None


class PromptUpdateRequest(BaseModel):
    text: str | None = None
    kind: str | None = None
    funnel_stage: str | None = None
    lead_intent_score: int | None = None
    engines: list[EngineType] | None = None
    persona_id: UUID | None = None
    is_active: bool | None = None


class PromptResponse(BaseModel):
    id: UUID
    client_id: UUID
    text: str
    kind: str
    funnel_stage: str | None
    lead_intent_score: int | None
    engines: list[EngineType]
    source: str | None
    is_active: bool


class PromptSeriesPoint(BaseModel):
    day: str
    runs: int
    mentioned: int


class EngineRunStatus(BaseModel):
    engine: EngineType
    status: str  # queued | running | succeeded | failed | none
    last_at: str | None  # schedule day (YYYY-MM-DD) of the latest run


class PromptListItem(PromptResponse):
    created_at: str | None = None
    retired_at: str | None = None
    persona_id: UUID | None = None
    last_run_at: str | None = None
    series: list[PromptSeriesPoint] = []
    engine_status: list[EngineRunStatus] = []


async def require_prompt_cap(db: AsyncSession, client_id: UUID) -> int:
    """Enforce the active-prompt cap (product cap 125; billing may lower it).

    Shared by manual creation and the research agent's accept step.
    Raises 400 when the website is at its cap.
    """
    count_res = await db.execute(
        text("""
            SELECT
                (SELECT COUNT(*) FROM prompts WHERE client_id = :cid AND is_active = true) as current_count,
                LEAST(COALESCE((settings->'billing_limits'->>'max_prompts')::int, :cap), :cap) as max_prompts
            FROM clients WHERE id = :cid
        """),
        {"cid": str(client_id), "cap": MAX_ACTIVE_PROMPTS}
    )
    row = count_res.first()
    if not row:
        raise HTTPException(status_code=404, detail="Client not found")
    if row.current_count >= row.max_prompts:
        raise HTTPException(
            status_code=400,
            detail=f"Website has reached the {row.max_prompts} active prompts limit. Retire one or contact your operator.",
        )
    return int(row.max_prompts)


_SERIES_WINDOW_SQL = "coalesce(a.run_day, (a.collected_at AT TIME ZONE 'UTC')::date)"


@router.get("", response_model=list[PromptListItem])
async def list_prompts(
    client_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[PromptListItem]:
    """Prompt set with 14-day mention series and latest per-engine run status."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    result = await db.execute(
        text(
            "SELECT id, client_id, text, kind, funnel_stage, lead_intent_score, "
            "engines, source, is_active, persona_id, created_at, retired_at "
            "FROM prompts WHERE client_id = :cid ORDER BY created_at DESC"
        ),
        {"cid": str(client_id)},
    )
    rows = result.all()
    if not rows:
        return []

    days = 14
    start = datetime.now(UTC).date() - timedelta(days=days - 1)

    # Latest run per (prompt, engine) — drives the per-engine status chip.
    latest: dict[tuple[str, str], EngineRunStatus] = {}
    for r in (
        await db.execute(
            text(
                """
                SELECT DISTINCT ON (prompt_id, engine)
                       prompt_id, engine, status, run_day
                FROM answers
                WHERE client_id = :cid AND run_day >= :from
                ORDER BY prompt_id, engine, run_day DESC, run_index DESC
                """
            ),
            {"cid": str(client_id), "from": start},
        )
    ).all():
        latest[(str(r.prompt_id), str(r.engine))] = EngineRunStatus(
            engine=EngineType(r.engine),
            status=str(r.status),
            last_at=r.run_day.isoformat() if isinstance(r.run_day, date) else str(r.run_day),
        )

    # Daily runs + brand mentions per prompt — the sparkline.
    series: dict[str, list[PromptSeriesPoint]] = {}
    for r in (
        await db.execute(
            text(
                f"""
                SELECT prompt_id, {_SERIES_WINDOW_SQL} AS day,
                       COUNT(*) FILTER (WHERE a.status = 'succeeded') AS runs,
                       COUNT(*) FILTER (WHERE a.status = 'succeeded' AND EXISTS (
                           SELECT 1 FROM brand_mentions bm
                           WHERE bm.answer_id = a.id AND bm.entity_kind = 'brand'
                       )) AS mentioned
                FROM answers a
                WHERE client_id = :cid AND {_SERIES_WINDOW_SQL} >= :from
                GROUP BY 1, 2 ORDER BY 1, 2
                """
            ),
            {"cid": str(client_id), "from": start},
        )
    ).all():
        series.setdefault(str(r.prompt_id), []).append(
            PromptSeriesPoint(day=str(r.day), runs=int(r.runs), mentioned=int(r.mentioned))
        )

    last_run: dict[str, str] = {}
    for r in (
        await db.execute(
            text(
                "SELECT prompt_id, MAX(collected_at) AS last_at FROM answers "
                "WHERE client_id = :cid AND collected_at IS NOT NULL GROUP BY 1"
            ),
            {"cid": str(client_id)},
        )
    ).all():
        last_run[str(r.prompt_id)] = str(r.last_at)

    out: list[PromptListItem] = []
    for row in rows:
        pid = str(row.id)
        out.append(
            PromptListItem(
                id=row.id, client_id=row.client_id, text=row.text, kind=row.kind,
                funnel_stage=row.funnel_stage, lead_intent_score=row.lead_intent_score,
                engines=[EngineType(e) for e in row.engines], source=row.source,
                is_active=row.is_active, persona_id=row.persona_id,
                created_at=str(row.created_at) if row.created_at else None,
                retired_at=str(row.retired_at) if row.retired_at else None,
                last_run_at=last_run.get(pid),
                series=series.get(pid, []),
                engine_status=[
                    status_item
                    for (prompt_id, _eng), status_item in latest.items()
                    if prompt_id == pid
                ],
            )
        )
    return out


@router.post("", response_model=PromptResponse, status_code=status.HTTP_201_CREATED)
async def create_prompt(
    client_id: UUID,
    body: PromptCreateRequest,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN, MemberRole.STRATEGIST))],
    db: Annotated[AsyncSession, Depends(get_db)],    ) -> PromptResponse:
    """Create a prompt. Active prompts are capped at 125 per website (product cap)."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if body.persona_id is not None:
        await _require_persona(db, client_id, body.persona_id)

    # Active cap: billing override may lower it, the product cap is 125.
    await require_prompt_cap(db, client_id)

    result = await db.execute(
        text(
            "INSERT INTO prompts (client_id, text, kind, funnel_stage, lead_intent_score, engines, source, persona_id) "
            "VALUES (:cid, :txt, :kind, :stage, :score, CAST(:engines AS engine_t[]), :source, :persona) "
            "RETURNING id, client_id, text, kind, funnel_stage, lead_intent_score, engines, source, is_active"
        ),
        {
            "cid": str(client_id), "txt": body.text, "kind": body.kind,
            "stage": body.funnel_stage, "score": body.lead_intent_score,
            "engines": [e.value for e in body.engines], "source": body.source,
            "persona": str(body.persona_id) if body.persona_id else None,
        },
    )
    await db.commit()
    row = result.first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create prompt")
    return PromptResponse(
        id=row.id, client_id=row.client_id, text=row.text, kind=row.kind,
        funnel_stage=row.funnel_stage, lead_intent_score=row.lead_intent_score,
        engines=[EngineType(e) for e in row.engines], source=row.source, is_active=row.is_active
    )


async def _require_persona(db: AsyncSession, client_id: UUID, persona_id: UUID) -> None:
    """404 unless the persona belongs to this client."""
    res = await db.execute(
        text("SELECT 1 FROM personas WHERE id = :pid AND client_id = :cid"),
        {"pid": str(persona_id), "cid": str(client_id)},
    )
    if res.first() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Persona not found for this website")


@router.patch("/{prompt_id}", response_model=PromptResponse)
async def update_prompt(
    client_id: UUID,
    prompt_id: UUID,
    body: PromptUpdateRequest,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN, MemberRole.STRATEGIST))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PromptResponse:
    """Edit a prompt or retire/reactivate it (sets ``retired_at``)."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    if body.persona_id is not None:
        await _require_persona(db, client_id, body.persona_id)

    result = await db.execute(
        text(
            """
            UPDATE prompts SET
                text = COALESCE(:txt, text),
                kind = COALESCE(:kind, kind),
                funnel_stage = COALESCE(:stage, funnel_stage),
                lead_intent_score = COALESCE(:score, lead_intent_score),
                engines = COALESCE(CAST(:engines AS engine_t[]), engines),
                persona_id = COALESCE(:persona, persona_id),
                is_active = COALESCE(:active, is_active),
                retired_at = CASE
                    WHEN CAST(:active AS boolean) IS FALSE THEN COALESCE(retired_at, now())
                    WHEN CAST(:active AS boolean) IS TRUE THEN NULL
                    ELSE retired_at
                END
            WHERE id = :pid AND client_id = :cid
            RETURNING id, client_id, text, kind, funnel_stage, lead_intent_score, engines, source, is_active
            """
        ),
        {
            "txt": body.text,
            "kind": body.kind,
            "stage": body.funnel_stage,
            "score": body.lead_intent_score,
            "engines": [e.value for e in body.engines] if body.engines is not None else None,
            "persona": str(body.persona_id) if body.persona_id else None,
            "active": body.is_active,
            "pid": str(prompt_id),
            "cid": str(client_id),
        },
    )
    row = result.first()
    await db.commit()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt not found")
    return PromptResponse(
        id=row.id, client_id=row.client_id, text=row.text, kind=row.kind,
        funnel_stage=row.funnel_stage, lead_intent_score=row.lead_intent_score,
        engines=[EngineType(e) for e in row.engines], source=row.source, is_active=row.is_active
    )
