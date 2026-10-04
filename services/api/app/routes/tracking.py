"""Tracking routes: domain citation ranking and the competitor matrix (FR-12/13).

- ``GET /clients/{id}/citations/domains`` — who gets cited, with the taxonomy
  (owned / competitor / forum / review_site / wiki / news / …) and share of
  all citations in the window.
- ``GET /clients/{id}/competitors/matrix`` - prompt x entity presence: brand
  visible? which competitors showed up? (the table behind the Tracking screen).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from services.api.app.auth import AuthUser, get_current_user, has_client_access
from services.api.app.db import get_db
from services.api.app.logging import get_logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

router = APIRouter(prefix="/clients/{client_id}", tags=["tracking"])

_WINDOW_SQL = "coalesce(a.run_day, (a.collected_at AT TIME ZONE 'UTC')::date)"


def _window_start(days: int) -> date:
    return datetime.now(UTC).date() - timedelta(days=max(1, min(days, 90)) - 1)


class DomainCitation(BaseModel):
    domain: str
    domain_type: str
    citations: int
    answers: int
    is_brand: bool
    is_competitor: bool
    share: float


class DomainCitationsResponse(BaseModel):
    days: int
    total_citations: int
    brand_citations: int
    brand_share: float | None
    domains: list[DomainCitation]


@router.get("/citations/domains", response_model=DomainCitationsResponse)
async def citation_domains(
    client_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = 7,
    limit: int = 50,
) -> DomainCitationsResponse:
    """Domain citation ranking vs competitors over the window (FR-12)."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    days = max(1, min(days, 90))
    start = _window_start(days)
    limit = max(1, min(limit, 200))

    rows = (
        await db.execute(
            text(
                f"""
                SELECT d.domain, d.domain_type,
                       COUNT(*) AS citations,
                       COUNT(DISTINCT ac.answer_id) AS answers,
                       BOOL_OR(ac.is_brand_owned) AS is_brand,
                       BOOL_OR(d.domain_type = 'competitor') AS is_competitor
                FROM answer_citations ac
                JOIN answers a ON a.id = ac.answer_id
                JOIN domains d ON d.id = ac.domain_id
                WHERE ac.client_id = :cid AND a.status = 'succeeded'
                  AND {_WINDOW_SQL} >= :from
                GROUP BY d.domain, d.domain_type
                ORDER BY citations DESC
                LIMIT :lim
                """
            ),
            {"cid": str(client_id), "from": start, "lim": limit},
        )
    ).all()

    totals = (
        await db.execute(
            text(
                f"""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE ac.is_brand_owned) AS brand
                FROM answer_citations ac
                JOIN answers a ON a.id = ac.answer_id
                WHERE ac.client_id = :cid AND a.status = 'succeeded'
                  AND {_WINDOW_SQL} >= :from
                """
            ),
            {"cid": str(client_id), "from": start},
        )
    ).one()

    total = int(totals.total or 0)
    brand = int(totals.brand or 0)
    return DomainCitationsResponse(
        days=days,
        total_citations=total,
        brand_citations=brand,
        brand_share=(brand / total if total else None),
        domains=[
            DomainCitation(
                domain=r.domain,
                domain_type=str(r.domain_type),
                citations=int(r.citations),
                answers=int(r.answers),
                is_brand=bool(r.is_brand),
                is_competitor=bool(r.is_competitor),
                share=(int(r.citations) / total if total else 0.0),
            )
            for r in rows
        ],
    )


class MatrixCompetitor(BaseModel):
    competitor_id: UUID
    name: str
    runs_with_mention: int


class MatrixRow(BaseModel):
    prompt_id: UUID
    prompt_text: str
    funnel_stage: str | None
    runs: int
    brand_runs: int
    brand_visible: bool
    competitors: list[MatrixCompetitor]


class CompetitorMatrixResponse(BaseModel):
    days: int
    rows: list[MatrixRow]


@router.get("/competitors/matrix", response_model=CompetitorMatrixResponse)
async def competitor_matrix(
    client_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = 7,
) -> CompetitorMatrixResponse:
    """Prompt x entity matrix over the window (brand visibility + competitors)."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    days = max(1, min(days, 90))
    start = _window_start(days)

    runs_rows = (
        await db.execute(
            text(
                f"""
                SELECT a.prompt_id,
                       COUNT(*) AS runs,
                       COUNT(*) FILTER (WHERE EXISTS (
                           SELECT 1 FROM brand_mentions bm
                           WHERE bm.answer_id = a.id AND bm.entity_kind = 'brand'
                       )) AS brand_runs
                FROM answers a
                WHERE a.client_id = :cid AND a.status = 'succeeded'
                  AND {_WINDOW_SQL} >= :from
                GROUP BY 1
                """
            ),
            {"cid": str(client_id), "from": start},
        )
    ).all()

    mention_rows = (
        await db.execute(
            text(
                f"""
                SELECT a.prompt_id, bm.competitor_id, c.name,
                       COUNT(*) AS mentions
                FROM brand_mentions bm
                JOIN answers a ON a.id = bm.answer_id
                JOIN competitors c ON c.id = bm.competitor_id
                WHERE bm.client_id = :cid AND bm.entity_kind = 'competitor'
                  AND bm.competitor_id IS NOT NULL
                  AND a.status = 'succeeded'
                  AND {_WINDOW_SQL} >= :from
                GROUP BY 1, 2, 3
                """
            ),
            {"cid": str(client_id), "from": start},
        )
    ).all()

    prompt_rows = (
        await db.execute(
            text(
                "SELECT id, text, funnel_stage FROM prompts WHERE client_id = :cid ORDER BY created_at DESC"
            ),
            {"cid": str(client_id)},
        )
    ).all()

    runs_by_prompt = {str(r.prompt_id): r for r in runs_rows}
    comp_by_prompt: dict[str, list[MatrixCompetitor]] = {}
    for r in mention_rows:
        comp_by_prompt.setdefault(str(r.prompt_id), []).append(
            MatrixCompetitor(competitor_id=r.competitor_id, name=str(r.name), runs_with_mention=int(r.mentions))
        )

    rows: list[MatrixRow] = []
    for p in prompt_rows:
        runs_row = runs_by_prompt.get(str(p.id))
        runs = int(runs_row.runs) if runs_row else 0
        brand_runs = int(runs_row.brand_runs) if runs_row else 0
        rows.append(
            MatrixRow(
                prompt_id=p.id,
                prompt_text=p.text,
                funnel_stage=p.funnel_stage,
                runs=runs,
                brand_runs=brand_runs,
                brand_visible=(runs > 0 and brand_runs * 2 >= runs),
                competitors=comp_by_prompt.get(str(p.id), []),
            )
        )

    return CompetitorMatrixResponse(days=days, rows=rows)
