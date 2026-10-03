"""Prompts CRUD routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
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

logger = get_logger(__name__)

router = APIRouter(prefix="/clients/{client_id}/prompts", tags=["prompts"])


class PromptCreateRequest(BaseModel):
    text: str
    kind: str = "ai_prompt"
    funnel_stage: str | None = None
    lead_intent_score: int | None = None
    engines: list[EngineType] = [EngineType.CHATGPT, EngineType.GEMINI, EngineType.PERPLEXITY, EngineType.GROK]
    source: str | None = "manual"


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


@router.get("", response_model=list[PromptResponse])
async def list_prompts(
    client_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> list[PromptResponse]:
    """List all prompts for a specific client."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    result = await db.execute(
        text(
            "SELECT id, client_id, text, kind, funnel_stage, lead_intent_score, "
            "engines, source, is_active "
            "FROM prompts WHERE client_id = :cid ORDER BY created_at DESC"
        ),
        {"cid": str(client_id)},
    )
    
    return [
        PromptResponse(
            id=r.id, client_id=r.client_id, text=r.text, kind=r.kind,
            funnel_stage=r.funnel_stage, lead_intent_score=r.lead_intent_score,
            engines=[EngineType(e) for e in r.engines], source=r.source, is_active=r.is_active
        )
        for r in result.all()
    ]


@router.post("", response_model=PromptResponse, status_code=status.HTTP_201_CREATED)
async def create_prompt(
    client_id: UUID,
    body: PromptCreateRequest,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN, MemberRole.STRATEGIST))],
    db: AsyncSession = Depends(get_db),
) -> PromptResponse:
    """Create a new prompt. Capped at 125 active per client (in real implementation)."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Enforce dynamic billing limit
    count_res = await db.execute(
        text("""
            SELECT 
                (SELECT COUNT(*) FROM prompts WHERE client_id = :cid AND is_active = true) as current_count,
                COALESCE((settings->'billing_limits'->>'max_prompts')::int, 25) as max_prompts
            FROM clients WHERE id = :cid
        """),
        {"cid": str(client_id)}
    )
    row = count_res.first()
    if not row:
        raise HTTPException(status_code=404, detail="Client not found")
        
    if row.current_count >= row.max_prompts:
        raise HTTPException(status_code=400, detail=f"Client has reached the {row.max_prompts} active prompts limit.")

    result = await db.execute(
        text(
            "INSERT INTO prompts (client_id, text, kind, funnel_stage, lead_intent_score, engines, source) "
            "VALUES (:cid, :txt, :kind, :stage, :score, :engines, :source) "
            "RETURNING id, client_id, text, kind, funnel_stage, lead_intent_score, engines, source, is_active"
        ),
        {
            "cid": str(client_id), "txt": body.text, "kind": body.kind,
            "stage": body.funnel_stage, "score": body.lead_intent_score,
            "engines": [e.value for e in body.engines], "source": body.source
        },
    )
    await db.commit()
    row = result.first()
    return PromptResponse(
        id=row.id, client_id=row.client_id, text=row.text, kind=row.kind,
        funnel_stage=row.funnel_stage, lead_intent_score=row.lead_intent_score,
        engines=[EngineType(e) for e in row.engines], source=row.source, is_active=row.is_active
    )
