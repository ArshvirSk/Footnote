"""Brand memory routes: profile, aliases and document/URL ingestion (Milestone 1).

- ``GET/PUT /clients/{id}/brand-profile`` — voice, positioning, products, ICP,
  proof points, banned claims, theme.
- ``GET/POST/DELETE /clients/{id}/brand-aliases`` — alternate brand names used
  by mention detection.
- ``GET /clients/{id}/brand-memory`` + ``POST …/ingest`` + ``DELETE …/{chunk}``
  — text/URL documents chunked and embedded into pgvector with a real
  embeddings provider (configuration error if the provider key is missing).

All queries are scoped by ``client_id``.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

import httpx
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
from services.api.app.embeddings import (
    EMBEDDING_MODEL,
    EmbeddingNotConfigured,
    embed_texts,
    embedding_cost_usd,
)
from services.api.app.logging import get_logger
from services.api.app.text import chunk_text, html_to_text
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

router = APIRouter(prefix="/clients/{client_id}", tags=["brand"])

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

WRITE_ROLES = (MemberRole.OWNER, MemberRole.ADMIN, MemberRole.STRATEGIST)


# ──── Brand profile ────


class BrandProfileBody(BaseModel):
    voice: str | None = None
    positioning: str | None = None
    products: list[dict[str, Any]] = Field(default_factory=list)
    icp: dict[str, Any] = Field(default_factory=dict)
    proof_points: list[dict[str, Any]] = Field(default_factory=list)
    banned_claims: list[str] = Field(default_factory=list)
    theme_html: str | None = None
    theme_css: str | None = None
    # Aliases are edited together with the profile (one save).
    aliases: list[str] | None = None


class BrandProfileResponse(BrandProfileBody):
    client_id: UUID
    updated_at: datetime | None = None
    aliases: list[str] = Field(default_factory=list)


def _profile_payload(row: Any) -> BrandProfileResponse:
    return BrandProfileResponse(
        client_id=row.client_id,
        voice=row.voice,
        positioning=row.positioning,
        products=row.products or [],
        icp=row.icp or {},
        proof_points=row.proof_points or [],
        banned_claims=list(row.banned_claims or []),
        theme_html=row.theme_html,
        theme_css=row.theme_css,
        updated_at=row.updated_at,
        aliases=[],
    )


@router.get("/brand-profile", response_model=BrandProfileResponse)
async def get_brand_profile(
    client_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BrandProfileResponse:
    """Read the brand profile (empty defaults when never saved)."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    result = await db.execute(
        text(
            """
            SELECT client_id, voice, positioning, products, icp, proof_points,
                   banned_claims, theme_html, theme_css, updated_at
            FROM brand_profiles WHERE client_id = :cid
            """
        ),
        {"cid": str(client_id)},
    )
    row = result.first()

    alias_res = await db.execute(
        text("SELECT alias FROM brand_aliases WHERE client_id = :cid ORDER BY alias"),
        {"cid": str(client_id)},
    )
    aliases = [r.alias for r in alias_res.all()]

    if row is None:
        return BrandProfileResponse(client_id=client_id, aliases=aliases)
    profile = _profile_payload(row)
    profile.aliases = aliases
    return profile


@router.put("/brand-profile", response_model=BrandProfileResponse)
async def put_brand_profile(
    client_id: UUID,
    body: BrandProfileBody,
    user: Annotated[AuthUser, Depends(require_roles(*WRITE_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BrandProfileResponse:
    """Upsert the brand profile (and aliases when provided)."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    await db.execute(
        text(
            """
            INSERT INTO brand_profiles (
                client_id, voice, positioning, products, icp, proof_points,
                banned_claims, theme_html, theme_css, updated_at
            )
            VALUES (
                :cid, :voice, :positioning, CAST(:products AS jsonb), CAST(:icp AS jsonb),
                CAST(:proof_points AS jsonb), CAST(:banned_claims AS text[]), :theme_html, :theme_css, now()
            )
            ON CONFLICT (client_id) DO UPDATE SET
                voice = EXCLUDED.voice,
                positioning = EXCLUDED.positioning,
                products = EXCLUDED.products,
                icp = EXCLUDED.icp,
                proof_points = EXCLUDED.proof_points,
                banned_claims = EXCLUDED.banned_claims,
                theme_html = EXCLUDED.theme_html,
                theme_css = EXCLUDED.theme_css,
                updated_at = now()
            """
        ),
        {
            "cid": str(client_id),
            "voice": body.voice,
            "positioning": body.positioning,
            "products": json.dumps(body.products),
            "icp": json.dumps(body.icp),
            "proof_points": json.dumps(body.proof_points),
            "banned_claims": body.banned_claims,
            "theme_html": body.theme_html,
            "theme_css": body.theme_css,
        },
    )

    if body.aliases is not None:
        cleaned = sorted({a.strip() for a in body.aliases if a and a.strip()})
        await db.execute(text("DELETE FROM brand_aliases WHERE client_id = :cid"), {"cid": str(client_id)})
        client_res = await db.execute(text("SELECT name FROM clients WHERE id = :cid"), {"cid": str(client_id)})
        brand_name = client_res.scalar() or ""
        for alias in cleaned:
            await db.execute(
                text(
                    "INSERT INTO brand_aliases (id, client_id, alias, is_primary) "
                    "VALUES (:id, :cid, :alias, :primary)"
                ),
                {
                    "id": str(uuid4()),
                    "cid": str(client_id),
                    "alias": alias,
                    "primary": alias.lower() == brand_name.lower(),
                },
            )

    await db.commit()
    logger.info("brand_profile_saved", client_id=str(client_id))
    return await get_brand_profile(client_id, user, db)


# ──── Aliases ────


class AliasBody(BaseModel):
    alias: str
    is_primary: bool = False


class AliasResponse(BaseModel):
    id: UUID
    alias: str
    is_primary: bool


@router.get("/brand-aliases", response_model=list[AliasResponse])
async def list_aliases(
    client_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AliasResponse]:
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    result = await db.execute(
        text("SELECT id, alias, is_primary FROM brand_aliases WHERE client_id = :cid ORDER BY alias"),
        {"cid": str(client_id)},
    )
    return [AliasResponse(id=r.id, alias=r.alias, is_primary=bool(r.is_primary)) for r in result.all()]


@router.post("/brand-aliases", response_model=AliasResponse, status_code=status.HTTP_201_CREATED)
async def add_alias(
    client_id: UUID,
    body: AliasBody,
    user: Annotated[AuthUser, Depends(require_roles(*WRITE_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AliasResponse:
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    alias = body.alias.strip()
    if not alias:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="alias must not be empty")

    if body.is_primary:
        await db.execute(
            text("UPDATE brand_aliases SET is_primary = false WHERE client_id = :cid"), {"cid": str(client_id)}
        )
    alias_id = uuid4()
    await db.execute(
        text(
            "INSERT INTO brand_aliases (id, client_id, alias, is_primary) VALUES (:id, :cid, :alias, :primary)"
        ),
        {"id": str(alias_id), "cid": str(client_id), "alias": alias, "primary": body.is_primary},
    )
    await db.commit()
    return AliasResponse(id=alias_id, alias=alias, is_primary=body.is_primary)


@router.delete("/brand-aliases/{alias_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alias(
    client_id: UUID,
    alias_id: UUID,
    user: Annotated[AuthUser, Depends(require_roles(*WRITE_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    result = await db.execute(
        text("DELETE FROM brand_aliases WHERE id = :aid AND client_id = :cid RETURNING id"),
        {"aid": str(alias_id), "cid": str(client_id)},
    )
    deleted = result.first()
    await db.commit()
    if deleted is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alias not found")


# ──── Brand memory (chunk + embed) ────


class IngestBody(BaseModel):
    kind: str  # "url" | "text"
    url: str | None = None
    text: str | None = None
    title: str | None = None
    source: str | None = None  # site | asset | brief | study


class MemoryChunk(BaseModel):
    id: UUID
    source: str
    title: str | None
    preview: str
    created_at: datetime | None


class IngestResponse(BaseModel):
    chunks: int
    tokens: int
    cost_usd: float
    title: str


@router.get("/brand-memory", response_model=list[MemoryChunk])
async def list_brand_memory(
    client_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[MemoryChunk]:
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    result = await db.execute(
        text(
            """
            SELECT id, source, title, left(content, 240) AS preview, created_at
            FROM brand_memory_chunks WHERE client_id = :cid
            ORDER BY created_at DESC LIMIT 200
            """
        ),
        {"cid": str(client_id)},
    )
    return [
        MemoryChunk(id=r.id, source=r.source, title=r.title, preview=r.preview, created_at=r.created_at)
        for r in result.all()
    ]


@router.post("/brand-memory/ingest", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
async def ingest_brand_memory(
    client_id: UUID,
    body: IngestBody,
    user: Annotated[AuthUser, Depends(require_roles(*WRITE_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IngestResponse:
    """Fetch/paste a document, chunk it and store real embeddings.

    Idempotent per (client, source, title): re-ingesting replaces the chunks.
    """
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if body.kind not in ("url", "text"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="kind must be 'url' or 'text'")

    title = body.title
    if body.kind == "url":
        if not body.url:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="url is required for kind=url")
        try:
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                res = await client.get(body.url, headers={"User-Agent": "FootnoteBot/1.0 (+brand-memory)"})
                res.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Could not fetch URL: {exc}") from exc
        raw = res.text
        content = html_to_text(raw)
        if not title:
            match = _TITLE_RE.search(raw)
            title = match.group(1).strip() if match else body.url
        source = body.source or "site"
    else:
        content = (body.text or "").strip()
        source = body.source or "asset"
        title = title or "Pasted document"

    if len(content) < 40:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document has too little text (<40 characters) to ingest",
        )

    chunks = chunk_text(content)
    try:
        vectors, tokens = await embed_texts(chunks)
    except EmbeddingNotConfigured as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    # Idempotent per (client, source, title): re-ingesting replaces the chunks.
    await db.execute(
        text(
            "DELETE FROM brand_memory_chunks WHERE client_id = :cid AND source = :source AND title = :title"
        ),
        {"cid": str(client_id), "source": source, "title": title},
    )
    for chunk, vector in zip(chunks, vectors, strict=True):
        await db.execute(
            text(
                """
                INSERT INTO brand_memory_chunks (id, client_id, source, title, content, embedding)
                VALUES (:id, :cid, :source, :title, :content, CAST(:vec AS vector))
                """
            ),
            {
                "id": str(uuid4()),
                "cid": str(client_id),
                "source": source,
                "title": title,
                "content": chunk,
                "vec": f"[{','.join(map(str, vector))}]",
            },
        )

    await db.execute(
        text(
            """
            INSERT INTO agent_runs (id, client_id, agent, input, output, model, tokens_in, tokens_out, cost_usd, status, started_at, finished_at)
            VALUES (:id, :cid, 'brand_ingest', CAST(:input AS jsonb), CAST(:output AS jsonb), :model, :tin, 0, :cost, 'succeeded', now(), now())
            """
        ),
        {
            "id": str(uuid4()),
            "cid": str(client_id),
            "input": json.dumps({"kind": body.kind, "title": title, "source": source}),
            "output": json.dumps({"chunks": len(chunks)}),
            "model": EMBEDDING_MODEL,
            "tin": tokens,
            "cost": embedding_cost_usd(tokens),
        },
    )
    await db.commit()

    logger.info(
        "brand_memory_ingested", client_id=str(client_id), chunks=len(chunks), tokens=tokens, source=source
    )
    return IngestResponse(chunks=len(chunks), tokens=tokens, cost_usd=embedding_cost_usd(tokens), title=title or "")


@router.delete("/brand-memory/{chunk_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_brand_memory(
    client_id: UUID,
    chunk_id: UUID,
    user: Annotated[AuthUser, Depends(require_roles(*WRITE_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    result = await db.execute(
        text("DELETE FROM brand_memory_chunks WHERE id = :id AND client_id = :cid RETURNING id"),
        {"id": str(chunk_id), "cid": str(client_id)},
    )
    deleted = result.first()
    await db.commit()
    if deleted is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chunk not found")
