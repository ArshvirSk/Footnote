"""Competitors and personas CRUD (Milestone 1).

Both are client-scoped entities used by collection (competitor citation
ownership) and the prompt research agent (personas). Every query is scoped by
``client_id`` and every write checks client access + operator role.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

router = APIRouter(prefix="/clients/{client_id}", tags=["entities"])

WRITE_ROLES = (MemberRole.OWNER, MemberRole.ADMIN, MemberRole.STRATEGIST)


async def _check(db: AsyncSession, user: AuthUser, client_id: UUID) -> None:
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")


# ──── Competitors ────


class CompetitorBody(BaseModel):
    name: str
    domain: str | None = None
    aliases: list[str] = Field(default_factory=list)


class CompetitorUpdate(BaseModel):
    name: str | None = None
    domain: str | None = None
    aliases: list[str] | None = None


class CompetitorResponse(BaseModel):
    id: UUID
    name: str
    domain: str | None
    aliases: list[str]


@router.get("/competitors", response_model=list[CompetitorResponse])
async def list_competitors(
    client_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[CompetitorResponse]:
    await _check(db, user, client_id)
    result = await db.execute(
        text("SELECT id, name, domain, aliases FROM competitors WHERE client_id = :cid ORDER BY name"),
        {"cid": str(client_id)},
    )
    return [
        CompetitorResponse(id=r.id, name=r.name, domain=r.domain, aliases=list(r.aliases or []))
        for r in result.all()
    ]


@router.post("/competitors", response_model=CompetitorResponse, status_code=status.HTTP_201_CREATED)
async def create_competitor(
    client_id: UUID,
    body: CompetitorBody,
    user: Annotated[AuthUser, Depends(require_roles(*WRITE_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CompetitorResponse:
    await _check(db, user, client_id)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name must not be empty")
    domain = (body.domain or "").strip().lower().removeprefix("www.") or None
    competitor_id = uuid4()
    await db.execute(
        text(
            "INSERT INTO competitors (id, client_id, name, domain, aliases) "
            "VALUES (:id, :cid, :name, :domain, CAST(:aliases AS text[]))"
        ),
        {
            "id": str(competitor_id),
            "cid": str(client_id),
            "name": name,
            "domain": domain,
            "aliases": [a.strip() for a in body.aliases if a.strip()],
        },
    )
    await db.commit()
    logger.info("competitor_created", client_id=str(client_id), competitor_id=str(competitor_id))
    return CompetitorResponse(id=competitor_id, name=name, domain=domain, aliases=body.aliases)


@router.patch("/competitors/{competitor_id}", response_model=CompetitorResponse)
async def update_competitor(
    client_id: UUID,
    competitor_id: UUID,
    body: CompetitorUpdate,
    user: Annotated[AuthUser, Depends(require_roles(*WRITE_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CompetitorResponse:
    await _check(db, user, client_id)
    result = await db.execute(
        text(
            """
            UPDATE competitors SET
                name = COALESCE(:name, name),
                domain = CASE WHEN :domain_set THEN :domain ELSE domain END,
                aliases = COALESCE(CAST(:aliases AS text[]), aliases)
            WHERE id = :id AND client_id = :cid
            RETURNING id, name, domain, aliases
            """
        ),
        {
            "name": body.name.strip() if body.name else None,
            "domain_set": body.domain is not None,
            "domain": (body.domain or "").strip().lower().removeprefix("www.") or None,
            "aliases": [a.strip() for a in body.aliases if a.strip()] if body.aliases is not None else None,
            "id": str(competitor_id),
            "cid": str(client_id),
        },
    )
    row = result.first()
    await db.commit()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Competitor not found")
    return CompetitorResponse(id=row.id, name=row.name, domain=row.domain, aliases=list(row.aliases or []))


@router.delete("/competitors/{competitor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_competitor(
    client_id: UUID,
    competitor_id: UUID,
    user: Annotated[AuthUser, Depends(require_roles(*WRITE_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await _check(db, user, client_id)
    result = await db.execute(
        text("DELETE FROM competitors WHERE id = :id AND client_id = :cid RETURNING id"),
        {"id": str(competitor_id), "cid": str(client_id)},
    )
    deleted = result.first()
    await db.commit()
    if deleted is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Competitor not found")


# ──── Personas ────


class PersonaBody(BaseModel):
    name: str
    description: str | None = None


class PersonaUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class PersonaResponse(BaseModel):
    id: UUID
    name: str
    description: str | None


@router.get("/personas", response_model=list[PersonaResponse])
async def list_personas(
    client_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[PersonaResponse]:
    await _check(db, user, client_id)
    result = await db.execute(
        text("SELECT id, name, description FROM personas WHERE client_id = :cid ORDER BY name"),
        {"cid": str(client_id)},
    )
    return [PersonaResponse(id=r.id, name=r.name, description=r.description) for r in result.all()]


@router.post("/personas", response_model=PersonaResponse, status_code=status.HTTP_201_CREATED)
async def create_persona(
    client_id: UUID,
    body: PersonaBody,
    user: Annotated[AuthUser, Depends(require_roles(*WRITE_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PersonaResponse:
    await _check(db, user, client_id)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name must not be empty")
    persona_id = uuid4()
    await db.execute(
        text("INSERT INTO personas (id, client_id, name, description) VALUES (:id, :cid, :name, :description)"),
        {"id": str(persona_id), "cid": str(client_id), "name": name, "description": body.description},
    )
    await db.commit()
    return PersonaResponse(id=persona_id, name=name, description=body.description)


@router.patch("/personas/{persona_id}", response_model=PersonaResponse)
async def update_persona(
    client_id: UUID,
    persona_id: UUID,
    body: PersonaUpdate,
    user: Annotated[AuthUser, Depends(require_roles(*WRITE_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PersonaResponse:
    await _check(db, user, client_id)
    result = await db.execute(
        text(
            """
            UPDATE personas SET
                name = COALESCE(:name, name),
                description = CASE WHEN :desc_set THEN :description ELSE description END
            WHERE id = :id AND client_id = :cid
            RETURNING id, name, description
            """
        ),
        {
            "name": body.name.strip() if body.name else None,
            "desc_set": body.description is not None,
            "description": body.description,
            "id": str(persona_id),
            "cid": str(client_id),
        },
    )
    row = result.first()
    await db.commit()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Persona not found")
    return PersonaResponse(id=row.id, name=row.name, description=row.description)


@router.delete("/personas/{persona_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_persona(
    client_id: UUID,
    persona_id: UUID,
    user: Annotated[AuthUser, Depends(require_roles(*WRITE_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await _check(db, user, client_id)
    result = await db.execute(
        text("DELETE FROM personas WHERE id = :id AND client_id = :cid RETURNING id"),
        {"id": str(persona_id), "cid": str(client_id)},
    )
    deleted = result.first()
    await db.commit()
    if deleted is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Persona not found")
