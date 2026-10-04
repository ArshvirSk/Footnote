"""Website detail routes: derived setup checklist and dashboard (Milestone 1).

- ``GET /clients/{id}/setup`` — the 7-item checklist behind the derived status.
- ``GET /clients/{id}/dashboard`` — real KPIs (with numerators/denominators),
  a ranked "Needs attention" queue and "Recent wins", all computed from tables
  we collect (no Google data; correlation caveat is explicit).

Every query is scoped by ``client_id`` and the route checks client access.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from services.api.app.auth import AuthUser, get_current_user, has_client_access
from services.api.app.config import settings
from services.api.app.db import get_db
from services.api.app.logging import get_logger
from services.api.app.schemas import ChecklistItemResponse
from services.api.app.website_status import (
    SETUP_TOTAL,
    checklist,
    derive_status,
    facts_from_row,
    fetch_client_row,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

router = APIRouter(prefix="/clients/{client_id}", tags=["websites"])

WINDOW_CURRENT = "a.collected_at >= now() - interval '7 days'"
WINDOW_PRIOR = "a.collected_at >= now() - interval '14 days' AND a.collected_at < now() - interval '7 days'"

CORRELATION_NOTE = (
    "These metrics show correlation, not proof of causation. They are computed only from answers "
    "we collected and content we published; no Google Search Console / GA4 data is used."
)

VISIBILITY_SQL = """
WITH runs AS (
    SELECT a.prompt_id, a.engine, COUNT(*) AS runs,
           COUNT(*) FILTER (WHERE EXISTS (
               SELECT 1 FROM brand_mentions bm WHERE bm.answer_id = a.id AND bm.entity_kind = 'brand'
           )) AS mentioned
    FROM answers a
    WHERE a.client_id = :cid AND a.status = 'succeeded' AND {window}
    GROUP BY 1, 2
)
SELECT COUNT(*) AS tracked,
       COUNT(*) FILTER (WHERE mentioned * 2 >= runs) AS visible,
       COALESCE(SUM(runs), 0) AS runs
FROM runs
"""

MENTION_SQL = """
SELECT COUNT(*) AS mentions, COUNT(*) FILTER (WHERE bm.linked) AS linked
FROM brand_mentions bm
JOIN answers a ON a.id = bm.answer_id
WHERE bm.client_id = :cid AND bm.entity_kind = 'brand' AND a.status = 'succeeded' AND {window}
"""

VOICE_SQL = """
SELECT COUNT(*) FILTER (WHERE bm.entity_kind = 'brand') AS brand_mentions,
       COUNT(*) FILTER (WHERE bm.entity_kind = 'competitor') AS competitor_mentions
FROM brand_mentions bm
JOIN answers a ON a.id = bm.answer_id
WHERE bm.client_id = :cid AND a.status = 'succeeded' AND {window}
"""

CITATION_SQL = """
SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE ac.is_brand_owned) AS brand
FROM answer_citations ac
JOIN answers a ON a.id = ac.answer_id
WHERE ac.client_id = :cid AND a.status = 'succeeded' AND {window}
"""

RUNS_SQL = """
SELECT COUNT(*) AS scheduled,
       COUNT(*) FILTER (WHERE a.status = 'succeeded') AS succeeded,
       COUNT(*) FILTER (WHERE a.status IN ('failed', 'skipped')) AS failed
FROM answers a
WHERE a.client_id = :cid
  AND (a.run_day >= (now() - interval '7 days')::date
       OR (a.run_day IS NULL AND a.collected_at >= now() - interval '7 days'))
"""

LATEST_AUDIT_SQL = """
SELECT score, finished_at FROM audits
WHERE client_id = :cid AND finished_at IS NOT NULL
ORDER BY started_at DESC LIMIT 1
"""


class SetupResponse(BaseModel):
    client_id: UUID
    status: str
    progress: int
    total: int
    items: list[ChecklistItemResponse]


class Metric(BaseModel):
    """A rate with its raw numerator/denominator so the UI can show sample size."""

    value: float | None
    current: int
    base: int
    prior_value: float | None = None
    prior_current: int | None = None
    prior_base: int | None = None
    formula: str


class KpiBlock(BaseModel):
    visibility: Metric
    mention_rate: Metric
    linked_rate: Metric
    citation_share: Metric
    share_of_voice: Metric
    open_gaps: int
    pending_approvals: int
    runs_7d: int
    failed_7d: int
    collection_health: float | None
    last_collection_at: datetime | None
    last_audit_score: float | None
    last_audit_at: datetime | None
    data_source: str = "footnote_collection"
    # Which engine providers have an API key configured (names only, no secrets).
    engine_providers_configured: list[str] = []


class AttentionItem(BaseModel):
    severity: str  # critical | high | medium | low
    kind: str
    title: str
    detail: str
    href: str


class WinItem(BaseModel):
    kind: str
    title: str
    detail: str
    at: datetime | None = None


class DashboardResponse(BaseModel):
    client_id: UUID
    client_name: str
    status: str
    setup: SetupResponse
    kpis: KpiBlock
    needs_attention: list[AttentionItem]
    recent_wins: list[WinItem]
    correlation_note: str


async def _require_client(db: AsyncSession, user: AuthUser, client_id: UUID) -> Any:
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    row = await fetch_client_row(db, str(client_id))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    return row


def _rate(current: int, base: int, formula: str) -> Metric:
    return Metric(value=(current / base if base else None), current=current, base=base, formula=formula)


async def _window_metrics(db: AsyncSession, client_id: str, window: str) -> dict[str, Any]:
    """Visibility / mention / link / citation / voice numbers for one window."""
    v = (await db.execute(text(VISIBILITY_SQL.format(window=window)), {"cid": client_id})).one()
    m = (await db.execute(text(MENTION_SQL.format(window=window)), {"cid": client_id})).one()
    voice = (await db.execute(text(VOICE_SQL.format(window=window)), {"cid": client_id})).one()
    cites = (await db.execute(text(CITATION_SQL.format(window=window)), {"cid": client_id})).one()
    return {
        "tracked": v.tracked or 0,
        "visible": v.visible or 0,
        "runs": v.runs or 0,
        "mentions": m.mentions or 0,
        "linked": m.linked or 0,
        "brand_mentions": voice.brand_mentions or 0,
        "competitor_mentions": voice.competitor_mentions or 0,
        "citations_total": cites.total or 0,
        "citations_brand": cites.brand or 0,
    }


async def _needs_attention(db: AsyncSession, client_id: str, facts: Any, missing_setup: list[str]) -> list[AttentionItem]:
    items: list[AttentionItem] = []

    # 1. Missing setup items — must be fixed before the site is fully tracked.
    if missing_setup:
        items.append(
            AttentionItem(
                severity="high" if facts.setup_progress < 4 else "medium",
                kind="setup",
                title=f"Setup incomplete ({facts.setup_progress}/{SETUP_TOTAL})",
                detail="Missing: " + ", ".join(missing_setup),
                href=f"/ops/websites/{client_id}",
            )
        )

    # 2. Failed / skipped collection runs in the last 7 days.
    runs = (await db.execute(text(RUNS_SQL), {"cid": client_id})).one()
    if (runs.failed or 0) > 0:
        items.append(
            AttentionItem(
                severity="high",
                kind="collection_failures",
                title=f"{runs.failed} failed or skipped collection run(s) in the last 7 days",
                detail="Failed runs are excluded from all rates until re-collected.",
                href="/ops/prompts",
            )
        )

    # 3. Critical/high findings in the latest audit.
    findings = (
        await db.execute(
            text(
                """
                SELECT af.severity, af.rule, af.detail, af.url
                FROM audit_findings af
                WHERE af.audit_id = (
                    SELECT id FROM audits WHERE client_id = :cid AND finished_at IS NOT NULL
                    ORDER BY started_at DESC LIMIT 1
                ) AND af.status = 'open' AND af.severity IN ('critical', 'high')
                ORDER BY CASE af.severity WHEN 'critical' THEN 0 ELSE 1 END
                LIMIT 5
                """
            ),
            {"cid": client_id},
        )
    ).all()
    if findings:
        worst = findings[0]
        items.append(
            AttentionItem(
                severity=worst.severity,
                kind="audit_findings",
                title=f"{len(findings)} critical/high audit finding(s) in the latest audit",
                detail=f"Top: {worst.rule.replace('_', ' ')} — {worst.detail}",
                href="/ops/site-audit",
            )
        )

    # 4. Slipped prompts.
    slipped = (
        await db.execute(
            text("SELECT COUNT(*) AS n FROM gaps WHERE client_id = :cid AND status = 'open' AND gap_type = 'slipped'"),
            {"cid": client_id},
        )
    ).one()
    if (slipped.n or 0) > 0:
        items.append(
            AttentionItem(
                severity="high",
                kind="slipped",
                title=f"{slipped.n} prompt(s) slipped out of AI answers",
                detail="The brand was visible in the prior 7 days and is absent now.",
                href="/ops/gaps",
            )
        )

    # 5. New gaps detected in the last 7 days (competitor cited, brand absent).
    new_gaps = (
        await db.execute(
            text(
                """
                SELECT COUNT(*) AS n FROM gaps
                WHERE client_id = :cid AND status = 'open'
                  AND gap_type = 'competitor_cited' AND detected_at >= now() - interval '7 days'
                """
            ),
            {"cid": client_id},
        )
    ).one()
    if (new_gaps.n or 0) > 0:
        items.append(
            AttentionItem(
                severity="medium",
                kind="new_gaps",
                title=f"{new_gaps.n} new gap(s): competitors cited where this brand is absent",
                detail="Detected by the nightly rollup from collected answers.",
                href="/ops/gaps",
            )
        )

    # 6. Pending approvals.
    if facts.pending_approvals > 0:
        items.append(
            AttentionItem(
                severity="medium",
                kind="approvals",
                title=f"{facts.pending_approvals} pending approval(s)",
                detail="Briefs and drafts waiting on a human decision.",
                href="/ops/pipeline",
            )
        )

    # 7. Content flagged for refresh.
    refresh = (
        await db.execute(
            text("SELECT COUNT(*) AS n FROM content_items WHERE client_id = :cid AND status = 'refresh_needed'"),
            {"cid": client_id},
        )
    ).one()
    if (refresh.n or 0) > 0:
        items.append(
            AttentionItem(
                severity="medium",
                kind="refresh",
                title=f"{refresh.n} content item(s) flagged for refresh",
                detail="Citation or freshness signals changed after publishing.",
                href="/ops/pipeline",
            )
        )

    # 8. Active prompts with no runs in the last 7 days.
    stale = (
        await db.execute(
            text(
                """
                SELECT COUNT(*) AS n FROM prompts p
                WHERE p.client_id = :cid AND p.is_active
                  AND NOT EXISTS (
                    SELECT 1 FROM answers a
                    WHERE a.prompt_id = p.id AND a.collected_at >= now() - interval '7 days'
                  )
                """
            ),
            {"cid": client_id},
        )
    ).one()
    if (stale.n or 0) > 0:
        items.append(
            AttentionItem(
                severity="medium",
                kind="stale_prompts",
                title=f"{stale.n} active prompt(s) have no runs in the last 7 days",
                detail="No collection coverage — check the scheduler or run them manually.",
                href="/ops/prompts",
            )
        )

    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    items.sort(key=lambda i: rank.get(i.severity, 4))
    return items


async def _recent_wins(db: AsyncSession, client_id: str) -> list[WinItem]:
    wins: list[WinItem] = []

    closed = (
        await db.execute(
            text(
                """
                SELECT g.id, p.text AS prompt_text, g.closed_at
                FROM gaps g LEFT JOIN prompts p ON p.id = g.prompt_id
                WHERE g.client_id = :cid AND g.status = 'won'
                  AND g.closed_at >= now() - interval '14 days'
                ORDER BY g.closed_at DESC LIMIT 5
                """
            ),
            {"cid": client_id},
        )
    ).all()
    for row in closed:
        wins.append(
            WinItem(
                kind="gap_won",
                title=f"Gap closed: {row.prompt_text or 'prompt'}",
                detail="A later collection proved the brand is now visible for this prompt.",
                at=row.closed_at,
            )
        )

    newly_visible = (
        await db.execute(
            text(
                """
                WITH cur AS (
                    SELECT a.prompt_id, a.engine, COUNT(*) AS runs,
                           COUNT(*) FILTER (WHERE EXISTS (
                               SELECT 1 FROM brand_mentions bm WHERE bm.answer_id = a.id AND bm.entity_kind = 'brand'
                           )) AS mentioned
                    FROM answers a
                    WHERE a.client_id = :cid AND a.status = 'succeeded'
                      AND a.collected_at >= now() - interval '7 days'
                    GROUP BY 1, 2
                ), prior AS (
                    SELECT a.prompt_id, a.engine, COUNT(*) AS runs,
                           COUNT(*) FILTER (WHERE EXISTS (
                               SELECT 1 FROM brand_mentions bm WHERE bm.answer_id = a.id AND bm.entity_kind = 'brand'
                           )) AS mentioned
                    FROM answers a
                    WHERE a.client_id = :cid AND a.status = 'succeeded'
                      AND a.collected_at >= now() - interval '14 days'
                      AND a.collected_at < now() - interval '7 days'
                    GROUP BY 1, 2
                )
                SELECT DISTINCT p.text
                FROM cur
                JOIN prior ON prior.prompt_id = cur.prompt_id AND prior.engine = cur.engine
                JOIN prompts p ON p.id = cur.prompt_id
                WHERE cur.mentioned * 2 >= cur.runs AND prior.mentioned * 2 < prior.runs
                LIMIT 5
                """
            ),
            {"cid": client_id},
        )
    ).all()
    for row in newly_visible:
        wins.append(
            WinItem(
                kind="visibility_gained",
                title=f"Now visible: {row.text}",
                detail="The brand was absent for this prompt in the prior 7-day window.",
                at=None,
            )
        )

    published = (
        await db.execute(
            text(
                """
                SELECT cv.title, ci.published_url, ci.published_at
                FROM content_items ci
                LEFT JOIN content_versions cv ON cv.id = ci.current_version_id
                WHERE ci.client_id = :cid AND ci.published_at >= now() - interval '14 days'
                ORDER BY ci.published_at DESC LIMIT 5
                """
            ),
            {"cid": client_id},
        )
    ).all()
    for row in published:
        wins.append(
            WinItem(
                kind="published",
                title=f"Published: {row.title or 'content item'}",
                detail=row.published_url or "Live URL recorded",
                at=row.published_at,
            )
        )

    return wins


async def _kpis(db: AsyncSession, client_id: str, facts: Any) -> KpiBlock:
    cur = await _window_metrics(db, client_id, WINDOW_CURRENT)
    prior = await _window_metrics(db, client_id, WINDOW_PRIOR)
    runs = (await db.execute(text(RUNS_SQL), {"cid": client_id})).one()
    audit = (await db.execute(text(LATEST_AUDIT_SQL), {"cid": client_id})).first()

    succeeded = runs.succeeded or 0
    failed = runs.failed or 0
    # Collection health = runs succeeded / runs scheduled (queued included).
    scheduled = runs.scheduled or 0

    visibility = Metric(
        value=(cur["visible"] / cur["tracked"] if cur["tracked"] else None),
        current=cur["visible"],
        base=cur["tracked"],
        prior_value=(prior["visible"] / prior["tracked"] if prior["tracked"] else None),
        prior_current=prior["visible"],
        prior_base=prior["tracked"],
        formula="visible prompts / tracked prompt-engine pairs; visible = brand mentioned in >=50% of runs (last 7 days vs prior 7)",
    )
    mention_rate = Metric(
        value=(cur["mentions"] / cur["runs"] if cur["runs"] else None),
        current=cur["mentions"],
        base=cur["runs"],
        prior_value=(prior["mentions"] / prior["runs"] if prior["runs"] else None),
        prior_current=prior["mentions"],
        prior_base=prior["runs"],
        formula="runs with a brand mention / succeeded runs (last 7 days vs prior 7)",
    )
    linked_rate = Metric(
        value=(cur["linked"] / cur["mentions"] if cur["mentions"] else None),
        current=cur["linked"],
        base=cur["mentions"],
        prior_value=(prior["linked"] / prior["mentions"] if prior["mentions"] else None),
        prior_current=prior["linked"],
        prior_base=prior["mentions"],
        formula="brand mentions linked to the brand's own domain / brand mentions",
    )
    citation_share = Metric(
        value=(cur["citations_brand"] / cur["citations_total"] if cur["citations_total"] else None),
        current=cur["citations_brand"],
        base=cur["citations_total"],
        prior_value=(prior["citations_brand"] / prior["citations_total"] if prior["citations_total"] else None),
        prior_current=prior["citations_brand"],
        prior_base=prior["citations_total"],
        formula="citations on brand-owned domains / all citations in collected answers",
    )
    sov_base = cur["brand_mentions"] + cur["competitor_mentions"]
    sov_prior_base = prior["brand_mentions"] + prior["competitor_mentions"]
    share_of_voice = Metric(
        value=(cur["brand_mentions"] / sov_base if sov_base else None),
        current=cur["brand_mentions"],
        base=sov_base,
        prior_value=(prior["brand_mentions"] / sov_prior_base if sov_prior_base else None),
        prior_current=prior["brand_mentions"],
        prior_base=sov_prior_base,
        formula="brand mentions / (brand + competitor mentions) across collected answers",
    )

    return KpiBlock(
        visibility=visibility,
        mention_rate=mention_rate,
        linked_rate=linked_rate,
        citation_share=citation_share,
        share_of_voice=share_of_voice,
        open_gaps=facts.open_gaps,
        pending_approvals=facts.pending_approvals,
        runs_7d=succeeded,
        failed_7d=failed,
        collection_health=(succeeded / scheduled if scheduled else None),
        last_collection_at=facts.last_collection_at,
        last_audit_score=float(audit.score) if audit and audit.score is not None else None,
        last_audit_at=audit.finished_at if audit else None,
        engine_providers_configured=configured_engine_providers(),
    )


# engine -> settings key holding its API credential
_ENGINE_KEY_FIELDS: dict[str, str] = {
    "chatgpt": "openai_api_key",
    "gemini": "gemini_api_key",
    "perplexity": "perplexity_api_key",
    "claude": "anthropic_api_key",
    "grok": "xai_api_key",
}


def configured_engine_providers() -> list[str]:
    """Engine names whose provider API key is configured (no secret values)."""
    return [
        engine
        for engine, field in _ENGINE_KEY_FIELDS.items()
        if getattr(settings, field, "")
    ]


@router.get("/setup", response_model=SetupResponse)
async def get_setup(
    client_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SetupResponse:
    """The derived setup checklist and status for one website."""
    row = await _require_client(db, user, client_id)
    facts = facts_from_row(row)
    return SetupResponse(
        client_id=client_id,
        status=derive_status(facts, row.status),
        progress=facts.setup_progress,
        total=SETUP_TOTAL,
        items=[ChecklistItemResponse(**item) for item in checklist(facts, str(client_id))],
    )


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    client_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DashboardResponse:
    """Action queue + portfolio-ready KPIs for the selected website."""
    row = await _require_client(db, user, client_id)
    facts = facts_from_row(row)
    items = [ChecklistItemResponse(**item) for item in checklist(facts, str(client_id))]
    missing = [i.label for i in items if not i.done]
    setup = SetupResponse(
        client_id=client_id,
        status=derive_status(facts, row.status),
        progress=facts.setup_progress,
        total=SETUP_TOTAL,
        items=items,
    )
    needs_attention = await _needs_attention(db, str(client_id), facts, missing)
    wins = await _recent_wins(db, str(client_id))
    kpis = await _kpis(db, str(client_id), facts)

    return DashboardResponse(
        client_id=client_id,
        client_name=row.name,
        status=setup.status,
        setup=setup,
        kpis=kpis,
        needs_attention=needs_attention,
        recent_wins=wins,
        correlation_note=CORRELATION_NOTE,
    )
