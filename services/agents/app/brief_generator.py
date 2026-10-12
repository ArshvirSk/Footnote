"""Content brief generator: turns gaps into structured content briefs.

Grounded in brand memory (pgvector cosine search), gap evidence, competitor
citations, and the brand profile.  Uses OpenAI when available, falls back to
a deterministic template generator.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
from services.api.app.config import settings
from services.api.app.db import engine
from services.api.app.embeddings import embed_texts
from services.api.app.logging import get_logger
from sqlalchemy import text

logger = get_logger(__name__)

# ──── Types ────

BRIEF_SYSTEM_PROMPT = """\
You are a senior SEO/AEO content strategist at Footnote.  Given:
- A brand profile (voice, positioning, products, proof points)
- A gap: a prompt where the brand is absent but a competitor is cited
- Evidence: raw AI answers showing the competitor but not the brand
- Brand memory passages relevant to this topic

Produce a JSON content brief with these fields:
{
  "title": "Article / page title (compelling, SEO-optimized)",
  "angle": "The unique angle or thesis for this piece",
  "outline": [
    { "heading": "H2 heading", "points": ["key point 1", "..."], "sources_needed": ["type of source"] }
  ],
  "target_keywords": ["primary keyword", "secondary keywords..."],
  "competitor_urls_to_displace": ["urls the engines currently cite instead"],
  "required_claims": ["specific claims that must appear, each with a source"],
  "proof_points_to_use": ["from brand memory / brand profile"],
  "content_type": "article | faq | comparison | landing",
  "word_count_target": 1500,
  "json_ld_type": "Article | FAQPage | HowTo"
}

Rules:
- Every claim must trace to a source URL or a brand proof point.
- Respect banned_claims — never include them.
- Write for the brand voice described in the profile.
- The piece must answer the gap prompt directly in the first 2-3 sentences.
"""


async def _retrieve_brand_memory(
    client_id: str, query: str, limit: int = 5
) -> list[dict[str, Any]]:
    """Cosine-similarity search over brand_memory_chunks."""
    try:
        vectors, _ = await embed_texts([query])
        if not vectors:
            return []
    except Exception:
        logger.warning("brand_memory_embed_failed", client_id=client_id)
        return []

    vec_literal = "[" + ",".join(str(v) for v in vectors[0]) + "]"

    async with engine.begin() as conn:
        res = await conn.execute(
            text(
                """
                SELECT id, source, title, chunk_text,
                       1 - (embedding <=> CAST(:vec AS vector)) AS similarity
                FROM brand_memory_chunks
                WHERE client_id = :cid
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT :lim
                """
            ),
            {"cid": client_id, "vec": vec_literal, "lim": limit},
        )
        return [
            {
                "id": str(r.id),
                "source": r.source,
                "title": r.title,
                "text": r.chunk_text,
                "similarity": float(r.similarity) if r.similarity else 0,
            }
            for r in res.all()
        ]


async def _get_brand_profile(client_id: str) -> dict[str, Any]:
    """Fetch the brand profile for context."""
    async with engine.begin() as conn:
        res = await conn.execute(
            text(
                """
                SELECT voice, positioning, products, icp,
                       proof_points, banned_claims
                FROM brand_profiles
                WHERE client_id = :cid
                """
            ),
            {"cid": client_id},
        )
        row = res.first()
        if not row:
            return {}
        return {
            "voice": row.voice,
            "positioning": row.positioning,
            "products": row.products or [],
            "icp": row.icp or {},
            "proof_points": row.proof_points or [],
            "banned_claims": row.banned_claims or [],
        }


async def _get_gap_evidence(
    client_id: str, gap_id: str
) -> dict[str, Any]:
    """Fetch gap details + raw answer evidence."""
    async with engine.begin() as conn:
        gap_res = await conn.execute(
            text(
                """
                SELECT g.id, g.prompt_id, g.gap_type, g.details,
                       p.text AS prompt_text
                FROM gaps g
                LEFT JOIN prompts p ON p.id = g.prompt_id
                WHERE g.id = :gid AND g.client_id = :cid
                """
            ),
            {"gid": gap_id, "cid": client_id},
        )
        gap_row = gap_res.first()
        if not gap_row:
            return {}

        # Get recent evidence answers for this prompt
        evidence_res = await conn.execute(
            text(
                """
                SELECT a.id, a.engine, a.raw_text, a.run_index,
                       to_char(a.run_day, 'YYYY-MM-DD') AS day
                FROM answers a
                WHERE a.client_id = :cid
                  AND a.prompt_id = :pid
                  AND a.status = 'succeeded'
                ORDER BY a.collected_at DESC
                LIMIT 6
                """
            ),
            {"cid": client_id, "pid": str(gap_row.prompt_id)},
        )

        # Get competitor citations for this prompt
        citation_res = await conn.execute(
            text(
                """
                SELECT DISTINCT ac.url, ac.title, d.host, d.domain_type
                FROM answer_citations ac
                JOIN answers a ON a.id = ac.answer_id
                JOIN domains d ON d.id = ac.domain_id
                WHERE a.client_id = :cid
                  AND a.prompt_id = :pid
                  AND d.is_brand_owned = false
                ORDER BY d.host
                LIMIT 20
                """
            ),
            {"cid": client_id, "pid": str(gap_row.prompt_id)},
        )

        return {
            "gap_id": str(gap_row.id),
            "prompt_id": str(gap_row.prompt_id),
            "prompt_text": gap_row.prompt_text,
            "gap_type": gap_row.gap_type,
            "details": gap_row.details or {},
            "evidence_answers": [
                {
                    "engine": r.engine,
                    "text": (r.raw_text or "")[:500],
                    "run_index": r.run_index,
                    "day": r.day,
                }
                for r in evidence_res.all()
            ],
            "competitor_citations": [
                {
                    "url": r.url,
                    "title": r.title,
                    "domain": r.host,
                    "type": r.domain_type,
                }
                for r in citation_res.all()
            ],
        }


async def _generate_brief_llm(
    prompt_text: str,
    brand_profile: dict[str, Any],
    evidence: dict[str, Any],
    memory_passages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Call OpenAI to generate a structured brief (JSON mode)."""
    import json

    user_msg = f"""## Gap prompt
"{prompt_text}"

## Brand profile
Voice: {brand_profile.get('voice', 'N/A')}
Positioning: {brand_profile.get('positioning', 'N/A')}
Products: {json.dumps(brand_profile.get('products', []))}
Proof points: {json.dumps(brand_profile.get('proof_points', []))}
Banned claims: {json.dumps(brand_profile.get('banned_claims', []))}

## Gap evidence
Type: {evidence.get('gap_type', 'unknown')}
Competitor citations engines currently show:
{json.dumps(evidence.get('competitor_citations', [])[:10], indent=2)}

Sample answers (brand absent):
{chr(10).join(a.get('text', '')[:300] for a in evidence.get('evidence_answers', [])[:3])}

## Relevant brand memory
{chr(10).join(f"- [{p.get('title', 'untitled')}]: {p.get('text', '')[:200]}" for p in memory_passages[:5])}
"""

    payload = {
        "model": "gpt-5-mini",
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": BRIEF_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.7,
        "max_tokens": 2000,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    brief_data = json.loads(content)
    brief_data["_usage"] = {
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "model": "gpt-5-mini",
    }
    return brief_data


def _generate_brief_template(
    prompt_text: str,
    brand_profile: dict[str, Any],
    evidence: dict[str, Any],
    memory_passages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Deterministic template-based brief (no API key needed)."""
    competitor_urls = [
        c.get("url", "") for c in evidence.get("competitor_citations", [])[:5]
    ]
    proof_points = [
        p.get("claim", p.get("text", ""))[:100]
        for p in (brand_profile.get("proof_points") or [])[:3]
    ]
    memory_refs = [
        p.get("title") or p.get("source", "untitled")
        for p in memory_passages[:3]
    ]

    return {
        "title": f"Expert Guide: {prompt_text[:80]}",
        "angle": f"Address the query '{prompt_text[:60]}' with brand expertise and proof points",
        "outline": [
            {
                "heading": "Introduction — Direct Answer",
                "points": [
                    f"Answer '{prompt_text[:50]}' in 2-3 sentences",
                    "Establish brand authority",
                ],
                "sources_needed": ["brand proof points"],
            },
            {
                "heading": "Deep Dive — Key Considerations",
                "points": [
                    "Expand on the core topic",
                    "Include specific data and examples",
                ],
                "sources_needed": ["industry data", "case studies"],
            },
            {
                "heading": "How [Brand] Approaches This",
                "points": [
                    "Product/service positioning",
                    "Differentiation from competitors",
                ],
                "sources_needed": ["brand memory", "product docs"],
            },
            {
                "heading": "Frequently Asked Questions",
                "points": ["3-5 related FAQs with concise answers"],
                "sources_needed": ["brand knowledge base"],
            },
        ],
        "target_keywords": [prompt_text[:60]],
        "competitor_urls_to_displace": competitor_urls,
        "required_claims": proof_points,
        "proof_points_to_use": memory_refs,
        "content_type": "article",
        "word_count_target": 1500,
        "json_ld_type": "Article",
        "_generator": "template",
    }


async def generate_brief_from_gap(
    client_id: str,
    gap_id: str,
) -> dict[str, Any]:
    """Generate a content brief from a gap.

    Uses LLM when OPENAI_API_KEY is set, otherwise falls back to template.
    Returns the structured brief data + metadata.
    """
    # 1. Gather context
    evidence = await _get_gap_evidence(client_id, gap_id)
    if not evidence:
        raise ValueError(f"Gap {gap_id} not found for client {client_id}")

    prompt_text = evidence.get("prompt_text", "")
    brand_profile = await _get_brand_profile(client_id)
    memory_passages = await _retrieve_brand_memory(client_id, prompt_text)

    # 2. Generate the brief
    usage: dict[str, Any] = {}
    if settings.openai_api_key:
        try:
            brief_data = await _generate_brief_llm(
                prompt_text, brand_profile, evidence, memory_passages
            )
            usage = brief_data.pop("_usage", {})
            generator = "llm"
            model = usage.get("model", "gpt-5-mini")
        except Exception as e:
            logger.warning("brief_llm_failed_falling_back", error=str(e))
            brief_data = _generate_brief_template(
                prompt_text, brand_profile, evidence, memory_passages
            )
            generator = brief_data.pop("_generator", "template")
            model = None
    else:
        brief_data = _generate_brief_template(
            prompt_text, brand_profile, evidence, memory_passages
        )
        generator = brief_data.pop("_generator", "template")
        model = None

    # 3. Persist the brief
    title = brief_data.get("title", f"Brief: {prompt_text[:60]}")
    angle = brief_data.get("angle", "")
    outline = brief_data.get("outline", [])
    grounding = {
        "target_keywords": brief_data.get("target_keywords", []),
        "competitor_urls_to_displace": brief_data.get("competitor_urls_to_displace", []),
        "required_claims": brief_data.get("required_claims", []),
        "proof_points_to_use": brief_data.get("proof_points_to_use", []),
        "content_type": brief_data.get("content_type", "article"),
        "word_count_target": brief_data.get("word_count_target", 1500),
        "json_ld_type": brief_data.get("json_ld_type", "Article"),
    }

    import json as json_mod

    async with engine.begin() as conn:
        # Log agent run
        agent_run_id = None
        if usage:
            ar_res = await conn.execute(
                text(
                    """
                    INSERT INTO agent_runs (client_id, agent, model, tokens_in, tokens_out)
                    VALUES (:cid, 'brief_generator', :model, :tin, :tout)
                    RETURNING id
                    """
                ),
                {
                    "cid": client_id,
                    "model": model,
                    "tin": usage.get("prompt_tokens", 0),
                    "tout": usage.get("completion_tokens", 0),
                },
            )
            agent_run_id = ar_res.scalar()

        # Create the brief
        brief_res = await conn.execute(
            text(
                """
                INSERT INTO content_briefs
                    (client_id, title, angle, outline, sources, status,
                     gap_ids, grounding_rules, agent_run_id)
                VALUES
                    (:cid, :title, :angle, CAST(:outline AS jsonb),
                     CAST(:sources AS jsonb), 'draft',
                     :gap_ids, CAST(:grounding AS jsonb), :arid)
                RETURNING id
                """
            ),
            {
                "cid": client_id,
                "title": title,
                "angle": angle,
                "outline": json_mod.dumps(outline),
                "sources": json_mod.dumps(brief_data.get("required_claims", [])),
                "gap_ids": [gap_id],
                "grounding": json_mod.dumps(grounding),
                "arid": str(agent_run_id) if agent_run_id else None,
            },
        )
        brief_id = brief_res.scalar()

        # Link brief to target prompts
        prompt_id = evidence.get("prompt_id")
        if prompt_id:
            await conn.execute(
                text(
                    """
                    INSERT INTO content_brief_prompts (brief_id, prompt_id)
                    VALUES (:bid, :pid)
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"bid": str(brief_id), "pid": prompt_id},
            )

    logger.info(
        "brief_generated",
        brief_id=str(brief_id),
        gap_id=gap_id,
        generator=generator,
        model=model,
    )

    return {
        "brief_id": str(brief_id),
        "title": title,
        "angle": angle,
        "outline": outline,
        "grounding": grounding,
        "generator": generator,
        "model": model,
        "memory_passages_used": len(memory_passages),
    }
