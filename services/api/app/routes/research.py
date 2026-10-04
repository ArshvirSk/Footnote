"""Research agent routes (FR-5..FR-7): propose → accept / edit / reject.

- ``POST /clients/{id}/research/generate`` — run the agent (LLM when keyed,
  otherwise the deterministic template generator) and persist the candidates
  as a pending queue. Nothing is tracked until an operator accepts it.
- ``GET  /clients/{id}/research/candidates`` — the queue (default: pending).
- ``POST .../candidates/{cid}/accept`` — create the prompt (cap enforced);
  optional ``text`` records an operator edit. The candidate keeps its original
  text and points at the created prompt (history).
- ``POST .../candidates/{cid}/reject`` — retire from the queue (kept as
  history, never deleted).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from services.api.app.auth import (
    AuthUser,
    MemberRole,
    get_current_user,
    has_client_access,
    require_roles,
)
from services.api.app.db import get_db
from services.api.app.logging import get_logger
from services.api.app.prompt_research import GenerationResult, generate_candidates
from services.api.app.routes.prompts import _require_persona, require_prompt_cap
from services.api.app.schemas import EngineType
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

router = APIRouter(prefix="/clients/{client_id}/research", tags=["research"])

DEFAULT_ENGINES = [EngineType.CHATGPT, EngineType.GEMINI, EngineType.PERPLEXITY, EngineType.GROK]


class GenerateRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=50)


class CandidateResponse(BaseModel):
    id: UUID
    text: str
    kind: str
    funnel_stage: str | None
    lead_intent_score: int | None
    persona_id: UUID | None
    rationale: str | None
    generator: str
    model: str | None
    status: str
    created_at: str
    resolved_at: str | None
    accepted_prompt_id: UUID | None


class GenerateResponse(BaseModel):
    generator: str
    model: str
    created: int
    warnings: list[str]
    candidates: list[CandidateResponse]


class AcceptRequest(BaseModel):
    """Accept a candidate; ``text`` optionally records the operator's edit."""

    text: str | None = None
    engines: list[EngineType] | None = None
    persona_id: UUID | None = None


class CandidateActionResponse(BaseModel):
    candidate: CandidateResponse
    prompt_id: UUID | None = None


def _candidate_out(r: Any) -> CandidateResponse:
    return CandidateResponse(
        id=r.id,
        text=r.text,
        kind=r.kind,
        funnel_stage=r.funnel_stage,
        lead_intent_score=r.lead_intent_score,
        persona_id=r.persona_id,
        rationale=r.rationale,
        generator=r.generator,
        model=r.model,
        status=r.status,
        created_at=str(r.created_at),
        resolved_at=str(r.resolved_at) if r.resolved_at else None,
        accepted_prompt_id=r.accepted_prompt_id,
    )


_CANDIDATE_COLS = (
    "id, text, kind, funnel_stage, lead_intent_score, persona_id, rationale, "
    "generator, model, status, created_at, resolved_at, accepted_prompt_id"
)


@router.post("/generate", response_model=GenerateResponse, status_code=status.HTTP_201_CREATED)
async def research_generate(
    client_id: UUID,
    body: GenerateRequest,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN, MemberRole.STRATEGIST))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GenerateResponse:
    """Run the research agent and persist new pending candidates."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    result: GenerationResult = await generate_candidates(db, str(client_id), limit=body.limit)

    created_ids: list[str] = []
    for candidate in result.candidates:
        res = await db.execute(
            text(
                """
                INSERT INTO prompt_candidates
                    (client_id, text, kind, funnel_stage, lead_intent_score, persona_id,
                     rationale, generator, model, status)
                VALUES (:cid, :text, :kind, :stage, :score, :persona,
                        :rationale, :generator, :model, 'pending')
                ON CONFLICT DO NOTHING
                RETURNING id
                """
            ),
            {
                "cid": str(client_id),
                "text": candidate.text,
                "kind": candidate.kind,
                "stage": candidate.funnel_stage,
                "score": candidate.lead_intent_score,
                "persona": str(candidate.persona_id) if candidate.persona_id else None,
                "rationale": candidate.rationale,
                "generator": candidate.generator,
                "model": candidate.model,
            },
        )
        row = res.first()
        if row is not None:
            created_ids.append(str(row.id))
    await db.commit()

    candidates: list[CandidateResponse] = []
    if created_ids:
        rows = (
            await db.execute(
                text(
                    f"SELECT {_CANDIDATE_COLS} FROM prompt_candidates WHERE id IN :ids ORDER BY created_at"
                ).bindparams(bindparam("ids", expanding=True)),
                {"ids": created_ids},
            )
        ).all()
        candidates = [_candidate_out(r) for r in rows]

    logger.info(
        "research_generated",
        client_id=str(client_id), generator=result.generator,
        created=len(candidates), warnings=len(result.warnings),
    )
    return GenerateResponse(
        generator=result.generator,
        model=result.model,
        created=len(candidates),
        warnings=result.warnings,
        candidates=candidates,
    )


@router.get("/candidates", response_model=list[CandidateResponse])
async def list_candidates(
    client_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: Annotated[
        Literal["pending", "accepted", "rejected", "all"], Query(alias="status")
    ] = "pending",
    limit: int = 100,
) -> list[CandidateResponse]:
    """The candidate queue (default: everything waiting for a decision)."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    query = f"SELECT {_CANDIDATE_COLS} FROM prompt_candidates WHERE client_id = :cid"
    params: dict[str, object] = {"cid": str(client_id)}
    if status_filter != "all":
        query += " AND status = :st"
        params["st"] = status_filter
    query += " ORDER BY created_at DESC LIMIT :lim"
    params["lim"] = max(1, min(limit, 500))

    rows = (await db.execute(text(query), params)).all()
    return [_candidate_out(r) for r in rows]


async def _load_candidate(db: AsyncSession, client_id: UUID, candidate_id: UUID) -> Any:
    row = (
        await db.execute(
            text(f"SELECT {_CANDIDATE_COLS} FROM prompt_candidates WHERE id = :id AND client_id = :cid"),
            {"id": str(candidate_id), "cid": str(client_id)},
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    if row.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Candidate already {row.status}")
    return row


@router.post("/candidates/{candidate_id}/accept", response_model=CandidateActionResponse, status_code=status.HTTP_201_CREATED)
async def accept_candidate(
    client_id: UUID,
    candidate_id: UUID,
    body: AcceptRequest,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN, MemberRole.STRATEGIST))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CandidateActionResponse:
    """Accept a candidate into the tracked prompt set (cap enforced, edit kept)."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    candidate = await _load_candidate(db, client_id, candidate_id)
    await require_prompt_cap(db, client_id)

    persona_id = body.persona_id if body.persona_id is not None else candidate.persona_id
    if persona_id is not None:
        await _require_persona(db, client_id, persona_id)

    prompt_text = (body.text or candidate.text).strip()
    if not prompt_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Prompt text cannot be empty")

    result = await db.execute(
        text(
            """
            INSERT INTO prompts (client_id, text, kind, funnel_stage, lead_intent_score, engines, source, persona_id)
            VALUES (:cid, :txt, :kind, :stage, :score, CAST(:engines AS engine_t[]), :source, :persona)
            RETURNING id
            """
        ),
        {
            "cid": str(client_id),
            "txt": prompt_text,
            "kind": candidate.kind,
            "stage": candidate.funnel_stage,
            "score": candidate.lead_intent_score,
            "engines": [e.value for e in (body.engines or DEFAULT_ENGINES)],
            "source": f"research:{candidate.generator}",
            "persona": str(persona_id) if persona_id else None,
        },
    )
    prompt_row = result.first()
    if prompt_row is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create prompt")

    await db.execute(
        text(
            """
            UPDATE prompt_candidates
            SET status = 'accepted', resolved_at = now(), accepted_prompt_id = :pid
            WHERE id = :id
            """
        ),
        {"pid": str(prompt_row.id), "id": str(candidate_id)},
    )
    await db.commit()

    updated = await _load_candidate_resolved(db, client_id, candidate_id)
    return CandidateActionResponse(candidate=_candidate_out(updated), prompt_id=prompt_row.id)
@router.post("/candidates/{candidate_id}/reject", response_model=CandidateActionResponse)
async def reject_candidate(
    client_id: UUID,
    candidate_id: UUID,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN, MemberRole.STRATEGIST))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CandidateActionResponse:
    """Reject a candidate — kept as history, never tracked."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    await _load_candidate(db, client_id, candidate_id)
    await db.execute(
        text("UPDATE prompt_candidates SET status = 'rejected', resolved_at = now() WHERE id = :id"),
        {"id": str(candidate_id)},
    )
    await db.commit()

    updated = await _load_candidate_resolved(db, client_id, candidate_id)
    return CandidateActionResponse(candidate=_candidate_out(updated), prompt_id=None)


async def _load_candidate_resolved(db: AsyncSession, client_id: UUID, candidate_id: UUID) -> Any:
    row = (
        await db.execute(
            text(f"SELECT {_CANDIDATE_COLS} FROM prompt_candidates WHERE id = :id AND client_id = :cid"),
            {"id": str(candidate_id), "cid": str(client_id)},
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    return row

