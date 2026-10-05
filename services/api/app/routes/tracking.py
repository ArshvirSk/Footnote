"""Tracking routes: domain citation ranking and competitor intelligence (FR-12/13).

- ``GET /clients/{id}/citations/domains`` — who gets cited, with the taxonomy
  (owned / competitor / forum / review_site / wiki / news / …) and share of
  all citations in the window.
- ``GET /clients/{id}/competitors/matrix`` - prompt x entity presence: brand
  visible? which competitors showed up? (the table behind the Tracking screen).
- ``GET /clients/{id}/competitors/intelligence`` (M3) — per-competitor page map:
  mentions, citations, top cited URLs, share of voice, and the prompts where the
  competitor shows up while the brand is absent (gap briefs).
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


class CompetitorPage(BaseModel):
    url: str
    title: str | None
    citations: int


class CompetitorPrompt(BaseModel):
    prompt_id: UUID
    prompt_text: str
    hits: int


class CompetitorIntel(BaseModel):
    competitor_id: UUID
    name: str
    domain: str | None
    mentions: int
    prompts_present: int
    citations: int
    share_of_voice: float | None
    top_pages: list[CompetitorPage]
    gap_prompts: list[CompetitorPrompt]


class CompetitorIntelligenceResponse(BaseModel):
    days: int
    total_brand_mentions: int
    total_competitor_mentions: int
    competitors: list[CompetitorIntel]


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


@router.get("/competitors/intelligence", response_model=CompetitorIntelligenceResponse)
async def competitor_intelligence(
    client_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = 7,
) -> CompetitorIntelligenceResponse:
    """Per-competitor page map + gap briefs over the window (M3).

    For every tracked competitor: mentions in answers, citations of their
    domains (with the most-cited URLs), share of voice vs the brand, and the
    prompts where they appear while the brand is absent.
    """
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    days = max(1, min(days, 90))
    start = _window_start(days)

    competitor_rows = (
        await db.execute(
            text("SELECT id, name, domain FROM competitors WHERE client_id = :cid ORDER BY name"),
            {"cid": str(client_id)},
        )
    ).all()

    mention_rows = (
        await db.execute(
            text(
                f"""
                SELECT bm.competitor_id AS cid, COUNT(*) AS mentions
                FROM brand_mentions bm
                JOIN answers a ON a.id = bm.answer_id
                WHERE bm.client_id = :cid AND bm.entity_kind = 'competitor'
                  AND bm.competitor_id IS NOT NULL AND a.status = 'succeeded'
                  AND {_WINDOW_SQL} >= :from
                GROUP BY 1
                """
            ),
            {"cid": str(client_id), "from": start},
        )
    ).all()
    mentions_by = {str(r.cid): int(r.mentions) for r in mention_rows}

    citation_rows = (
        await db.execute(
            text(
                f"""
                SELECT ac.competitor_id AS cid, COUNT(*) AS citations
                FROM answer_citations ac
                JOIN answers a ON a.id = ac.answer_id
                WHERE ac.client_id = :cid AND ac.competitor_id IS NOT NULL
                  AND a.status = 'succeeded' AND {_WINDOW_SQL} >= :from
                GROUP BY 1
                """
            ),
            {"cid": str(client_id), "from": start},
        )
    ).all()
    citations_by = {str(r.cid): int(r.citations) for r in citation_rows}

    page_rows = (
        await db.execute(
            text(
                f"""
                SELECT ac.competitor_id AS cid, ac.url, max(ac.title) AS title, COUNT(*) AS citations
                FROM answer_citations ac
                JOIN answers a ON a.id = ac.answer_id
                WHERE ac.client_id = :cid AND ac.competitor_id IS NOT NULL
                  AND a.status = 'succeeded' AND {_WINDOW_SQL} >= :from
                GROUP BY 1, 2
                ORDER BY citations DESC
                """
            ),
            {"cid": str(client_id), "from": start},
        )
    ).all()

    prompt_hit_rows = (
        await db.execute(
            text(
                f"""
                SELECT cid, prompt_id, COUNT(*) AS hits FROM (
                    SELECT bm.competitor_id AS cid, a.prompt_id
                    FROM brand_mentions bm JOIN answers a ON a.id = bm.answer_id
                    WHERE bm.client_id = :cid AND bm.entity_kind = 'competitor'
                      AND bm.competitor_id IS NOT NULL AND a.status = 'succeeded'
                      AND {_WINDOW_SQL} >= :from
                    UNION ALL
                    SELECT ac.competitor_id AS cid, a.prompt_id
                    FROM answer_citations ac JOIN answers a ON a.id = ac.answer_id
                    WHERE ac.client_id = :cid AND ac.competitor_id IS NOT NULL
                      AND a.status = 'succeeded' AND {_WINDOW_SQL} >= :from
                ) see
                GROUP BY 1, 2
                """
            ),
            {"cid": str(client_id), "from": start},
        )
    ).all()

    brand_present_rows = (
        await db.execute(
            text(
                f"""
                SELECT DISTINCT a.prompt_id
                FROM answers a
                WHERE a.client_id = :cid AND a.status = 'succeeded'
                  AND {_WINDOW_SQL} >= :from
                  AND (
                    EXISTS (SELECT 1 FROM brand_mentions bm
                            WHERE bm.answer_id = a.id AND bm.entity_kind = 'brand')
                    OR EXISTS (SELECT 1 FROM answer_citations ac
                               WHERE ac.answer_id = a.id AND ac.is_brand_owned)
                  )
                """
            ),
            {"cid": str(client_id), "from": start},
        )
    ).all()
    brand_present = {str(r.prompt_id) for r in brand_present_rows}

    totals = (
        await db.execute(
            text(
                f"""
                SELECT COUNT(*) FILTER (WHERE bm.entity_kind = 'brand') AS brand,
                       COUNT(*) FILTER (WHERE bm.entity_kind = 'competitor') AS competitor
                FROM brand_mentions bm
                JOIN answers a ON a.id = bm.answer_id
                WHERE bm.client_id = :cid AND a.status = 'succeeded'
                  AND {_WINDOW_SQL} >= :from
                """
            ),
            {"cid": str(client_id), "from": start},
        )
    ).one()
    total_brand = int(totals.brand or 0)
    total_comp = int(totals.competitor or 0)

    # Prompt texts for every prompt that showed a competitor.
    prompt_ids = {str(r.prompt_id) for r in prompt_hit_rows}
    prompt_text: dict[str, str] = {}
    if prompt_ids:
        text_rows = (
            await db.execute(
                text("SELECT id, text FROM prompts WHERE client_id = :cid AND id = ANY(:ids)"),
                {"cid": str(client_id), "ids": list(prompt_ids)},
            )
        ).all()
        prompt_text = {str(r.id): str(r.text) for r in text_rows}

    pages_by: dict[str, list[CompetitorPage]] = {}
    for r in page_rows:
        bucket = pages_by.setdefault(str(r.cid), [])
        if len(bucket) < 10:
            bucket.append(CompetitorPage(url=str(r.url), title=r.title, citations=int(r.citations)))

    hits_by: dict[str, list[tuple[str, int]]] = {}
    for r in prompt_hit_rows:
        hits_by.setdefault(str(r.cid), []).append((str(r.prompt_id), int(r.hits)))

    denom = total_brand + total_comp
    competitors: list[CompetitorIntel] = []
    for comp in competitor_rows:
        cid = str(comp.id)
        hits = sorted(hits_by.get(cid, []), key=lambda item: item[1], reverse=True)
        gap_prompts = [
            CompetitorPrompt(
                prompt_id=UUID(pid),
                prompt_text=prompt_text.get(pid, ""),
                hits=hits_count,
            )
            for pid, hits_count in hits
            if pid not in brand_present and pid in prompt_text
        ][:8]
        competitors.append(
            CompetitorIntel(
                competitor_id=comp.id,
                name=str(comp.name),
                domain=comp.domain,
                mentions=mentions_by.get(cid, 0),
                prompts_present=len(hits),
                citations=citations_by.get(cid, 0),
                share_of_voice=(mentions_by.get(cid, 0) / denom if denom else None),
                top_pages=pages_by.get(cid, []),
                gap_prompts=gap_prompts,
            )
        )
    competitors.sort(key=lambda c: (c.mentions + c.citations, c.name), reverse=True)

    return CompetitorIntelligenceResponse(
        days=days,
        total_brand_mentions=total_brand,
        total_competitor_mentions=total_comp,
        competitors=competitors,
    )
