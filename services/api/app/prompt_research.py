"""Research agent: candidate prompt generation from a website's seed inputs (FR-5..FR-7).

Seeds are the real inputs we hold for the website: brand name + aliases,
competitors, personas, brand profile (products / ICP / positioning), crawled
page titles and the prompt set already tracked (for de-duplication).

Two generators:

- **template** (always available) — deterministic renders of buyer-intent
  query patterns over the seeds, each tagged with a funnel stage and a
  heuristic lead-intent score. Works with no API key, so onboarding is never
  blocked.
- **llm** (used when ``OPENAI_API_KEY`` is configured) — one Chat Completions
  call that proposes candidates from the same seeds; the raw usage is logged
  to ``agent_runs`` (tokens in/out; cost left null because we do not have a
  verified price for the model).

The operator then accepts / edits / rejects each candidate (routes in
``routes/research.py``); nothing becomes a tracked prompt without that gate.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, Field
from services.api.app.config import settings
from services.api.app.logging import get_logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

_TEMPLATE_MODEL = "research-template-v1"
_LLM_MODEL = "gpt-5-mini"
_MAX_PAGE_TITLES = 12
_MAX_COMPETITOR_TEMPLATES = 3
_MAX_PERSONA_TEMPLATES = 3


class SeedCompetitor(BaseModel):
    id: UUID
    name: str
    aliases: list[str] = []


class SeedPersona(BaseModel):
    id: UUID
    name: str
    description: str | None = None


class Seeds(BaseModel):
    """Everything the generator is allowed to use (no invented facts)."""

    brand: str
    domain: str
    industry: str | None = None
    country: str | None = None
    aliases: list[str] = []
    products: list[str] = []
    positioning: str | None = None
    icp: str | None = None
    competitors: list[SeedCompetitor] = []
    personas: list[SeedPersona] = []
    page_titles: list[str] = []
    existing_prompts: list[str] = []


class Candidate(BaseModel):
    text: str
    kind: str = "ai_prompt"
    funnel_stage: Literal["awareness", "consideration", "decision"]
    lead_intent_score: int = Field(ge=0, le=100)
    persona_id: UUID | None = None
    rationale: str
    generator: Literal["template", "llm"]
    model: str | None = None


class GenerationResult(BaseModel):
    generator: Literal["template", "llm"]
    model: str
    candidates: list[Candidate]
    warnings: list[str] = []


def _norm(text_value: str) -> str:
    """De-duplication key: case/punctuation/whitespace insensitive."""
    return re.sub(r"[^a-z0-9]+", " ", text_value.casefold()).strip()


async def load_seeds(db: AsyncSession, client_id: str) -> Seeds:
    client = (
        await db.execute(
            text("SELECT name, primary_domain, industry, country FROM clients WHERE id = :cid"),
            {"cid": client_id},
        )
    ).first()
    if client is None:
        raise ValueError("client not found")

    profile = (
        await db.execute(
            text(
                "SELECT positioning, products, icp FROM brand_profiles WHERE client_id = :cid"
            ),
            {"cid": client_id},
        )
    ).first()
    aliases = [
        r.alias
        for r in (
            await db.execute(text("SELECT alias FROM brand_aliases WHERE client_id = :cid"), {"cid": client_id})
        ).all()
    ]
    competitors = [
        SeedCompetitor(id=r.id, name=r.name, aliases=list(r.aliases or []))
        for r in (
            await db.execute(
                text("SELECT id, name, aliases FROM competitors WHERE client_id = :cid ORDER BY name"),
                {"cid": client_id},
            )
        ).all()
    ]
    personas = [
        SeedPersona(id=r.id, name=r.name, description=r.description)
        for r in (
            await db.execute(
                text("SELECT id, name, description FROM personas WHERE client_id = :cid ORDER BY name"),
                {"cid": client_id},
            )
        ).all()
    ]
    page_titles = [
        r.title
        for r in (
            await db.execute(
                text(
                    "SELECT title FROM site_pages WHERE client_id = :cid AND title IS NOT NULL "
                    "ORDER BY word_count DESC NULLS LAST LIMIT :lim"
                ),
                {"cid": client_id, "lim": _MAX_PAGE_TITLES},
            )
        ).all()
        if r.title
    ]
    existing = [
        r.text
        for r in (
            await db.execute(text("SELECT text FROM prompts WHERE client_id = :cid"), {"cid": client_id})
        ).all()
    ] + [
        r.text
        for r in (
            await db.execute(
                text(
                    "SELECT text FROM prompt_candidates WHERE client_id = :cid AND status = 'pending'"
                ),
                {"cid": client_id},
            )
        ).all()
    ]

    products: list[str] = []
    icp_text: str | None = None
    if profile is not None:
        raw_products = profile.products or []
        products = [str(p) for p in raw_products if isinstance(p, str) and p.strip()]
        icp = profile.icp
        if isinstance(icp, dict):
            icp_text = " ".join(str(v) for v in icp.values() if isinstance(v, str)).strip() or None
        elif isinstance(icp, str):
            icp_text = icp or None

    return Seeds(
        brand=client.name,
        domain=client.primary_domain,
        industry=client.industry,
        country=client.country,
        aliases=aliases,
        products=products,
        positioning=profile.positioning if profile is not None else None,
        icp=icp_text,
        competitors=competitors,
        personas=personas,
        page_titles=page_titles,
        existing_prompts=existing,
    )


def derive_category(seeds: Seeds) -> str | None:
    """The buying category these prompts are about, from real inputs only.

    Order: first product in the brand profile, the client's industry, else the
    non-brand segment of a crawled page title (``Brand | Category``).
    """
    if seeds.products:
        return seeds.products[0].strip().rstrip(".")
    if seeds.industry and seeds.industry.strip():
        return seeds.industry.strip().rstrip(".")

    brand_lower = seeds.brand.casefold()
    for title in seeds.page_titles:
        for segment in re.split(r"\s*[|\u2013\u2014]\s*", title):
            segment = segment.strip()
            if len(segment) < 4 or brand_lower in segment.casefold():
                continue
            # "Enterprise IT Consulting, Cloud Solutions" -> "Enterprise IT Consulting"
            segment = re.split(r"[,;:]", segment)[0].strip()
            if segment:
                return segment
    return None


def render_candidates(seeds: Seeds, limit: int) -> list[Candidate]:
    """Deterministic candidate prompts (generator=template) from the seeds."""
    category = derive_category(seeds)
    brand = seeds.brand.strip()
    year = datetime.now(UTC).year
    out: list[Candidate] = []

    def add(
        text_value: str,
        stage: Literal["awareness", "consideration", "decision"],
        score: int,
        rationale: str,
        persona_id: UUID | None = None,
    ) -> None:
        text_value = text_value.strip()
        if not text_value or len(out) >= limit:
            return
        out.append(
            Candidate(
                text=text_value,
                funnel_stage=stage,
                lead_intent_score=max(0, min(score, 100)),
                persona_id=persona_id,
                rationale=rationale,
                generator="template",
                model=_TEMPLATE_MODEL,
            )
        )

    # ── Decision stage: the queries closest to a buying decision ──
    if category:
        add(f"Best {category} companies", "decision", 85,
            f"Decision-stage: 'best <category>' queries are what buyers ask AI right before choosing ({category}).")
        add(f"Top rated {category} providers", "decision", 80,
            f"Decision-stage: shortlist query for {category}.")
        add(f"How much do {category} cost", "decision", 60,
            f"Decision-stage: pricing questions signal an active evaluation of {category}.")
        add("Alternatives to " + (seeds.competitors[0].name if seeds.competitors else category),
            "decision", 70,
            "Decision-stage: alternatives queries surface competitor-led shortlists where the brand must appear.")
    add(f"{brand} reviews", "decision", 70,
        "Decision-stage: buyers ask for reviews of the brand by name before committing.")
    add(f"Is {brand} a good choice", "decision", 65,
        "Decision-stage: direct validation query about the brand.")

    for comp in seeds.competitors[:_MAX_COMPETITOR_TEMPLATES]:
        add(f"{brand} vs {comp.name}", "decision", 75,
            f"Decision-stage: head-to-head comparison query naming the brand and competitor '{comp.name}'.")
    for comp in seeds.competitors[1:_MAX_COMPETITOR_TEMPLATES + 1]:
        add(f"Alternatives to {comp.name}", "decision", 70,
            f"Decision-stage: buyers switching away from '{comp.name}' are in-market leads.")

    # ── Consideration stage: narrowing options ──
    if category:
        add(f"How to choose a {category}", "consideration", 55,
            f"Consideration-stage: 'how to choose' queries are comparison research for {category}.")
        add(f"What to look for when hiring {category}", "consideration", 50,
            f"Consideration-stage: vendor evaluation checklist query for {category}.")
    for persona in seeds.personas[:_MAX_PERSONA_TEMPLATES]:
        if category:
            add(f"Best {category} for {persona.name}", "consideration", 75,
                f"Consideration-stage: persona '{persona.name}' shortlist query (bound to that persona).",
                persona_id=persona.id)
        elif persona.description:
            add(f"What should a {persona.name} look for", "consideration", 50,
                f"Consideration-stage: persona '{persona.name}' research query (bound to that persona).",
                persona_id=persona.id)

    # ── Awareness stage: top-of-funnel education ──
    if category:
        add(f"What is {category}", "awareness", 30,
            f"Awareness-stage: definition query for {category}; high volume, lower intent.")
        add(f"{category} trends in {year}", "awareness", 35,
            f"Awareness-stage: trend query for {category} in {year}.")
        if seeds.icp:
            add(f"Why {category} matter for {seeds.icp[:80]}", "awareness", 40,
                "Awareness-stage: problem-aware query framed around the ideal customer profile.")

    # De-duplicate against what is already tracked (and within the batch).
    seen = {_norm(t) for t in seeds.existing_prompts}
    unique: list[Candidate] = []
    for candidate in out:
        key = _norm(candidate.text)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique[:limit]


_LLM_SYSTEM = (
    "You are a B2B demand-gen strategist. Propose buyer-intent search prompts that a "
    "real buyer would type into an AI assistant when evaluating the client's category. "
    "Only use facts from the provided seeds; never invent product claims, customers, "
    "studies or numbers. Vary funnel stages. Reply with JSON only: "
    "{\"candidates\": [{\"text\": str, \"funnel_stage\": \"awareness|consideration|decision\", "
    "\"lead_intent_score\": 0-100, \"rationale\": str}]}"
)


async def _llm_candidates(db: AsyncSession, client_id: str, seeds: Seeds, limit: int) -> list[Candidate]:
    payload = {
        "model": _LLM_MODEL,
        "messages": [
            {"role": "system", "content": _LLM_SYSTEM},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "brand": seeds.brand,
                        "domain": seeds.domain,
                        "industry": seeds.industry,
                        "country": seeds.country,
                        "aliases": seeds.aliases,
                        "products": seeds.products,
                        "positioning": seeds.positioning,
                        "icp": seeds.icp,
                        "competitors": [{"name": c.name, "aliases": c.aliases} for c in seeds.competitors],
                        "personas": [{"name": p.name, "description": p.description} for p in seeds.personas],
                        "page_titles": seeds.page_titles,
                        "already_tracked": seeds.existing_prompts[:150],
                        "count": limit,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    usage = data.get("usage") or {}
    parsed = json.loads(data["choices"][0]["message"]["content"])
    candidates: list[Candidate] = []
    seen = {_norm(t) for t in seeds.existing_prompts}
    for item in parsed.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        text_value = str(item.get("text") or "").strip()
        key = _norm(text_value)
        if not text_value or key in seen:
            continue
        seen.add(key)
        raw_stage = item.get("funnel_stage")
        stage: Literal["awareness", "consideration", "decision"] = (
            raw_stage if raw_stage in ("awareness", "consideration", "decision") else "consideration"
        )
        try:
            score = int(item.get("lead_intent_score", 50))
        except (TypeError, ValueError):
            score = 50
        candidates.append(
            Candidate(
                text=text_value,
                funnel_stage=stage,
                lead_intent_score=max(0, min(score, 100)),
                rationale=str(item.get("rationale") or ""),
                generator="llm",
                model=_LLM_MODEL,
            )
        )
        if len(candidates) >= limit:
            break

    await _log_agent_run(
        db,
        client_id,
        model=_LLM_MODEL,
        tokens_in=int(usage.get("prompt_tokens") or 0),
        tokens_out=int(usage.get("completion_tokens") or 0),
        input_payload={"limit": limit, "seeds": {"brand": seeds.brand, "industry": seeds.industry}},
        output={"candidates": len(candidates)},
    )
    return candidates


async def _log_agent_run(
    db: AsyncSession,
    client_id: str,
    *,
    model: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float | None = None,
    input_payload: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
) -> None:
    """Record the run for cost tracking (FR-29). Tokens always recorded;
    cost stays null unless we have a verified price."""
    await db.execute(
        text(
            """
            INSERT INTO agent_runs (client_id, agent, input, output, model, tokens_in, tokens_out, cost_usd, status, started_at, finished_at)
            VALUES (:cid, 'research', CAST(:input AS jsonb), CAST(:output AS jsonb), :model, :tin, :tout, :cost, 'succeeded', now(), now())
            """
        ),
        {
            "cid": client_id,
            "input": json.dumps(input_payload or {}),
            "output": json.dumps(output or {}),
            "model": model,
            "tin": tokens_in,
            "tout": tokens_out,
            "cost": cost_usd,
        },
    )


async def generate_candidates(
    db: AsyncSession,
    client_id: str,
    limit: int = 20,
) -> GenerationResult:
    """Run the research agent for one website (llm when keyed, else template)."""
    limit = max(1, min(limit, 50))
    seeds = await load_seeds(db, client_id)
    warnings: list[str] = []

    candidates: list[Candidate] = []
    generator: Literal["template", "llm"] = "template"
    model = _TEMPLATE_MODEL

    if settings.openai_api_key:
        generator = "llm"
        model = _LLM_MODEL
        try:
            candidates = await _llm_candidates(db, client_id, seeds, limit)
        except Exception as exc:  # fall back to templates, but say so
            logger.warning("research_llm_failed", error=str(exc)[:300])
            warnings.append(f"LLM generation failed ({type(exc).__name__}); showing template candidates instead.")
            candidates = []
            generator = "template"
            model = _TEMPLATE_MODEL

    if not candidates:
        candidates = render_candidates(seeds, limit)
        await _log_agent_run(
            db,
            client_id,
            model=_TEMPLATE_MODEL,
            input_payload={"limit": limit, "brand": seeds.brand},
            output={"candidates": len(candidates)},
        )

    if not seeds.page_titles and not seeds.products and not seeds.industry:
        warnings.append("No site content, products or industry yet — add a brand profile or run a site audit for better candidates.")

    return GenerationResult(generator=generator, model=model, candidates=candidates, warnings=warnings)
