"""Three-pass content draft generator: strategist → writer → editor.

Each pass is a separate LLM call grounded in the brief, brand memory, and
prior pass output.  Falls back to a deterministic template when no API key
is configured.

PRD §2.5: Content agent outputs versions (strategist → writer → editor) with
interrupt nodes at every human gate.  PRD §2.5 grounding rules: answer in
first 2-3 sentences, specific claims with sources, JSON-LD, respect banned_claims.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from services.api.app.config import settings
from services.api.app.db import engine
from services.api.app.logging import get_logger
from sqlalchemy import text

logger = get_logger(__name__)

# ──── System prompts for each pass ────

STRATEGIST_SYSTEM = """\
You are a senior AEO/SEO strategist.  Given a content brief, produce a
detailed outline with:
- A compelling title and meta description
- H2/H3 structure with key points under each
- For each section, list the claims that must be included and their sources
- Identify the primary target prompt/query this must answer
- Specify the JSON-LD schema type and key fields

Output valid JSON:
{
  "title": "...",
  "meta_description": "...",
  "sections": [
    { "heading": "H2", "level": 2, "points": ["..."], "claims": ["claim (source: ...)"] }
  ],
  "target_query": "...",
  "json_ld_type": "Article",
  "word_count_target": 1500
}
"""

WRITER_SYSTEM = """\
You are an expert content writer.  Given a strategist outline and brand
context, produce the full article in Markdown format.

Rules:
- Answer the target query directly in the first 2-3 sentences
- Every factual claim must reference its source in parentheses
- Use the brand voice described in the profile
- Include specific numbers, names, and evidence — never be vague
- Do NOT include any banned claims
- Target the specified word count (±10%)
- Use proper H2/H3 structure matching the outline

Output the article as clean Markdown text (no JSON wrapper).
"""

EDITOR_SYSTEM = """\
You are a meticulous editor and fact-checker.  Given a draft article, brand
profile, and brief:

1. Check every factual claim — flag any that lack a source or use a banned claim
2. Verify the article answers the target query in the first 2-3 sentences
3. Check brand voice consistency
4. Generate the JSON-LD (Schema.org) for this content
5. Produce a cleaned final version with any corrections applied

Output valid JSON:
{
  "body_md": "... final markdown ...",
  "body_html": null,
  "title": "...",
  "meta_description": "...",
  "json_ld": { ... Schema.org JSON-LD ... },
  "claims": [
    { "text": "claim text", "source": "source url or proof point", "status": "verified | unsourced | banned" }
  ],
  "word_count": 1234,
  "issues": ["list of remaining issues if any"]
}
"""


async def _llm_call(
    system: str, user_msg: str, json_mode: bool = True
) -> tuple[str, dict[str, int]]:
    """Single OpenAI chat completion call."""
    payload: dict[str, Any] = {
        "model": "gpt-5-mini",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.7,
        "max_tokens": 4000,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=120.0) as client:
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
    return content, {
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
    }


async def _pass_strategist(
    brief: dict[str, Any], brand_profile: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, int]]:
    """Pass 1: Strategist produces a detailed outline from the brief."""
    user_msg = f"""## Brief
Title: {brief.get('title', '')}
Angle: {brief.get('angle', '')}
Outline: {json.dumps(brief.get('outline', []))}
Target keywords: {json.dumps(brief.get('grounding', {}).get('target_keywords', []))}
Required claims: {json.dumps(brief.get('grounding', {}).get('required_claims', []))}
Content type: {brief.get('grounding', {}).get('content_type', 'article')}
Word count target: {brief.get('grounding', {}).get('word_count_target', 1500)}

## Brand
Voice: {brand_profile.get('voice', 'professional')}
Positioning: {brand_profile.get('positioning', '')}
Products: {json.dumps(brand_profile.get('products', []))}
Proof points: {json.dumps(brand_profile.get('proof_points', []))}
Banned claims: {json.dumps(brand_profile.get('banned_claims', []))}
"""
    content, usage = await _llm_call(STRATEGIST_SYSTEM, user_msg, json_mode=True)
    return json.loads(content), usage


async def _pass_writer(
    outline: dict[str, Any],
    brief: dict[str, Any],
    brand_profile: dict[str, Any],
) -> tuple[str, dict[str, int]]:
    """Pass 2: Writer produces the full markdown article."""
    user_msg = f"""## Strategist Outline
{json.dumps(outline, indent=2)}

## Brief Context
Title: {brief.get('title', '')}
Angle: {brief.get('angle', '')}
Competitor URLs to displace: {json.dumps(brief.get('grounding', {}).get('competitor_urls_to_displace', []))}

## Brand
Voice: {brand_profile.get('voice', 'professional')}
Positioning: {brand_profile.get('positioning', '')}
Products: {json.dumps(brand_profile.get('products', []))}
Proof points: {json.dumps(brand_profile.get('proof_points', []))}
Banned claims (NEVER include): {json.dumps(brand_profile.get('banned_claims', []))}

Target word count: {outline.get('word_count_target', 1500)}
Target query to answer first: {outline.get('target_query', brief.get('title', ''))}
"""
    content, usage = await _llm_call(WRITER_SYSTEM, user_msg, json_mode=False)
    return content, usage


async def _pass_editor(
    draft_md: str,
    outline: dict[str, Any],
    brief: dict[str, Any],
    brand_profile: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, int]]:
    """Pass 3: Editor fact-checks, applies corrections, generates JSON-LD."""
    user_msg = f"""## Draft Article
{draft_md}

## Original Brief
Title: {brief.get('title', '')}
Required claims: {json.dumps(brief.get('grounding', {}).get('required_claims', []))}

## Brand Profile
Voice: {brand_profile.get('voice', 'professional')}
Banned claims: {json.dumps(brand_profile.get('banned_claims', []))}
Proof points: {json.dumps(brand_profile.get('proof_points', []))}

## Target query
{outline.get('target_query', brief.get('title', ''))}

JSON-LD type: {brief.get('grounding', {}).get('json_ld_type', 'Article')}
"""
    content, usage = await _llm_call(EDITOR_SYSTEM, user_msg, json_mode=True)
    return json.loads(content), usage


def _template_draft(brief: dict[str, Any]) -> dict[str, Any]:
    """Deterministic template draft when no API key is available."""
    title = brief.get("title", "Untitled")
    angle = brief.get("angle", "")
    outline = brief.get("outline", [])
    grounding = brief.get("grounding", {})

    sections = []
    for section in outline:
        heading = section.get("heading", "Section")
        points = section.get("points", [])
        section_md = f"## {heading}\n\n"
        for point in points:
            section_md += f"- {point}\n"
        section_md += "\n"
        sections.append(section_md)

    body_md = f"# {title}\n\n{angle}\n\n" + "\n".join(sections)
    word_count = len(body_md.split())

    json_ld = {
        "@context": "https://schema.org",
        "@type": grounding.get("json_ld_type", "Article"),
        "headline": title,
        "description": angle,
    }

    return {
        "body_md": body_md,
        "body_html": None,
        "title": title,
        "meta_description": angle[:160],
        "json_ld": json_ld,
        "claims": [
            {"text": str(c), "source": "pending", "status": "unsourced"}
            for c in (
                grounding.get("required_claims")
                or brief.get("sources")
                or [p for s in outline for p in s.get("points", [])][:3]
                or ["Core claim"]
            )
        ],
        "word_count": word_count,
        "issues": ["Template-generated: all claims need human sourcing"],
        "_generator": "template",
        "_passes": 0,
    }


async def generate_draft(
    client_id: str,
    brief_id: str,
    content_item_id: str | None = None,
) -> dict[str, Any]:
    """Run the 3-pass content generation pipeline for a brief.

    Creates a content_item (if none exists) and a new content_version,
    then opens an approval gate.

    Returns the version data + metadata.
    """
    # 1. Load brief
    async with engine.begin() as conn:
        brief_res = await conn.execute(
            text(
                """
                SELECT id, title, angle, outline, sources, grounding_rules,
                       gap_ids, client_id
                FROM content_briefs
                WHERE id = :bid AND client_id = :cid
                """
            ),
            {"bid": brief_id, "cid": client_id},
        )
        brief_row = brief_res.first()
        if not brief_row:
            raise ValueError(f"Brief {brief_id} not found for client {client_id}")

        # Load brand profile
        bp_res = await conn.execute(
            text(
                """
                SELECT voice, positioning, products, icp,
                       proof_points, banned_claims
                FROM brand_profiles WHERE client_id = :cid
                """
            ),
            {"cid": client_id},
        )
        bp_row = bp_res.first()

    brief = {
        "title": brief_row.title,
        "angle": brief_row.angle,
        "outline": brief_row.outline or [],
        "sources": brief_row.sources or [],
        "grounding": brief_row.grounding_rules or {},
    }
    brand_profile = (
        {
            "voice": bp_row.voice if bp_row else None,
            "positioning": bp_row.positioning if bp_row else None,
            "products": (bp_row.products if bp_row else None) or [],
            "icp": (bp_row.icp if bp_row else None) or {},
            "proof_points": (bp_row.proof_points if bp_row else None) or [],
            "banned_claims": (bp_row.banned_claims if bp_row else None) or [],
        }
        if bp_row
        else {}
    )

    # 2. Run the passes
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0}

    if settings.openai_api_key:
        try:
            # Pass 1: Strategist
            logger.info("draft_pass_1_strategist", brief_id=brief_id)
            outline_data, usage1 = await _pass_strategist(brief, brand_profile)
            total_usage["prompt_tokens"] += usage1["prompt_tokens"]
            total_usage["completion_tokens"] += usage1["completion_tokens"]

            # Pass 2: Writer
            logger.info("draft_pass_2_writer", brief_id=brief_id)
            draft_md, usage2 = await _pass_writer(outline_data, brief, brand_profile)
            total_usage["prompt_tokens"] += usage2["prompt_tokens"]
            total_usage["completion_tokens"] += usage2["completion_tokens"]

            # Pass 3: Editor
            logger.info("draft_pass_3_editor", brief_id=brief_id)
            editor_result, usage3 = await _pass_editor(
                draft_md, outline_data, brief, brand_profile
            )
            total_usage["prompt_tokens"] += usage3["prompt_tokens"]
            total_usage["completion_tokens"] += usage3["completion_tokens"]

            generator = "llm"
            model = "gpt-5-mini"
            passes = 3
        except Exception as e:
            logger.warning("draft_llm_failed_falling_back", error=str(e))
            editor_result = _template_draft(brief)
            generator = "template"
            model = None
            passes = 0
    else:
        editor_result = _template_draft(brief)
        generator = editor_result.pop("_generator", "template")
        passes = editor_result.pop("_passes", 0)
        model = None

    # 3. Persist: create content_item + version
    body_md = editor_result.get("body_md", "")
    body_html = editor_result.get("body_html")
    title = editor_result.get("title", brief.get("title", "Untitled"))
    claims = editor_result.get("claims", [])
    json_ld = editor_result.get("json_ld")
    word_count = editor_result.get("word_count") or len(body_md.split())
    reading_time = round(word_count / 250, 1) if word_count else None

    async with engine.begin() as conn:
        # Log agent run
        agent_run_id = None
        if total_usage["prompt_tokens"] > 0:
            ar_res = await conn.execute(
                text(
                    """
                    INSERT INTO agent_runs (client_id, agent, model, tokens_in, tokens_out)
                    VALUES (:cid, 'draft_generator', :model, :tin, :tout)
                    RETURNING id
                    """
                ),
                {
                    "cid": client_id,
                    "model": model,
                    "tin": total_usage["prompt_tokens"],
                    "tout": total_usage["completion_tokens"],
                },
            )
            agent_run_id = ar_res.scalar()

        # Check for existing content_item for this brief
        if not content_item_id:
            existing = await conn.execute(
                text(
                    "SELECT id FROM content_items WHERE brief_id = :bid AND client_id = :cid"
                ),
                {"bid": brief_id, "cid": client_id},
            )
            item_row = existing.first()
            if item_row:
                content_item_id = item_row.id

        if content_item_id:
            # Get next version number
            ver_res = await conn.execute(
                text(
                    """
                    SELECT COALESCE(MAX(version_no), 0) + 1 AS next_ver
                    FROM content_versions
                    WHERE content_item_id = :iid
                    """
                ),
                {"iid": str(content_item_id)},
            )
            next_ver = ver_res.scalar() or 1
        else:
            # Create new content_item
            ci_res = await conn.execute(
                text(
                    """
                    INSERT INTO content_items
                        (client_id, brief_id, type, slug, status)
                    VALUES
                        (:cid, :bid, :ctype, :slug, 'drafting')
                    RETURNING id
                    """
                ),
                {
                    "cid": client_id,
                    "bid": brief_id,
                    "ctype": brief.get("grounding", {}).get("content_type", "article"),
                    "slug": title.lower()
                    .replace(" ", "-")[:60]
                    .strip("-"),
                },
            )
            content_item_id = ci_res.scalar()
            next_ver = 1

            # Map content item to the brief's target prompts
            prompt_res = await conn.execute(
                text(
                    "SELECT prompt_id FROM content_brief_prompts WHERE brief_id = :bid"
                ),
                {"bid": brief_id},
            )
            for pr in prompt_res.all():
                await conn.execute(
                    text(
                        """
                        INSERT INTO content_prompt_map (content_item_id, prompt_id, is_primary)
                        VALUES (:iid, :pid, true)
                        ON CONFLICT DO NOTHING
                        """
                    ),
                    {"iid": str(content_item_id), "pid": str(pr.prompt_id)},
                )

        # Create the version
        ver_insert = await conn.execute(
            text(
                """
                INSERT INTO content_versions
                    (content_item_id, client_id, version_no, title, body_md, body_html,
                     jsonld, meta, author_kind, agent_run_id, claims, word_count,
                     reading_time_min)
                VALUES
                    (:iid, :cid, :ver, :title, :body_md, :body_html,
                     CAST(:jsonld AS jsonb), CAST(:meta AS jsonb), 'agent', :arid,
                     CAST(:claims AS jsonb), :wc, :rt)
                RETURNING id
                """
            ),
            {
                "iid": str(content_item_id),
                "cid": client_id,
                "ver": next_ver,
                "title": title,
                "body_md": body_md,
                "body_html": body_html,
                "jsonld": json.dumps(json_ld) if json_ld else None,
                "meta": json.dumps({"meta_description": editor_result.get("meta_description", "")}),
                "claims": json.dumps(claims),
                "wc": word_count,
                "rt": reading_time,
                "arid": str(agent_run_id) if agent_run_id else None,
            },
        )
        version_id = ver_insert.scalar()

        # Update content_item to point to latest version
        await conn.execute(
            text(
                """
                UPDATE content_items
                SET current_version_id = :vid, status = 'in_review'
                WHERE id = :iid AND client_id = :cid
                """
            ),
            {"vid": str(version_id), "iid": str(content_item_id), "cid": client_id},
        )

        # Update brief status
        await conn.execute(
            text(
                """
                UPDATE content_briefs SET status = 'drafted'
                WHERE id = :bid AND client_id = :cid
                """
            ),
            {"bid": brief_id, "cid": client_id},
        )

        # Open approval gate for the draft
        await conn.execute(
            text(
                """
                INSERT INTO approvals (client_id, subject_type, subject_id, status)
                VALUES (:cid, 'version', :vid, 'pending')
                """
            ),
            {"cid": client_id, "vid": str(version_id)},
        )

    logger.info(
        "draft_generated",
        content_item_id=str(content_item_id),
        version_id=str(version_id),
        version_no=next_ver,
        generator=generator,
        passes=passes,
    )

    return {
        "content_item_id": str(content_item_id),
        "version_id": str(version_id),
        "version_no": next_ver,
        "title": title,
        "body_md": body_md,
        "claims": claims,
        "word_count": word_count,
        "reading_time_min": reading_time,
        "json_ld": json_ld,
        "generator": generator,
        "model": model,
        "passes": passes,
        "issues": editor_result.get("issues", []),
    }


# Backwards-compatible / descriptive alias
generate_draft_from_brief = generate_draft
