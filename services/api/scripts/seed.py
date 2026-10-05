"""Seed script: creates a demo organization, client, prompts, and fixture answers.

Run with: python -m services.api.scripts.seed
"""

from __future__ import annotations

import json
import os
from datetime import date
from urllib.parse import urlsplit
from uuid import UUID, uuid4, uuid5

import psycopg2

# Fixed UUIDs for reproducible seeding
DEMO_ORG_ID = UUID("10000000-0000-0000-0000-000000000001")
DEMO_USER_ID = UUID("20000000-0000-0000-0000-000000000001")
DEMO_CLIENT_ID = UUID("30000000-0000-0000-0000-000000000001")
DEMO_CLIENT_VIEWER_ID = UUID("20000000-0000-0000-0000-000000000002")
DEMO_COMPETITOR_ID = UUID("40000000-0000-0000-0000-000000000001")
DEMO_BATCH_ID = UUID("50000000-0000-0000-0000-000000000001")

# Deterministic id namespace so re-running the seed is idempotent
# (random uuid4 + ON CONFLICT (id) DO NOTHING would duplicate rows each run).
_SEED_NS = UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def _sid(*parts: object) -> UUID:
    """Stable UUID5 from the given parts."""
    return uuid5(_SEED_NS, "|".join(str(p) for p in parts))


DEMO_PROMPTS = [
    ("What is the best project management tool for startups?", "consideration", 75, "manual"),
    ("How to choose a CRM for small business?", "awareness", 60, "manual"),
    ("Top AI-powered marketing platforms 2025", "awareness", 55, "manual"),
    ("Best email marketing tool for e-commerce", "consideration", 80, "manual"),
    ("What is AEO and why does it matter?", "awareness", 40, "gsc"),
    ("How to appear in ChatGPT recommendations", "decision", 90, "llm"),
    ("Best SEO tools compared", "consideration", 65, "manual"),
    ("How to improve Google AI Overview visibility", "awareness", 70, "gsc"),
    ("What CRM integrates with Gmail best?", "consideration", 72, "paa"),
    ("AI answer engine optimization guide", "awareness", 45, "llm"),
    ("Best analytics platform for SaaS", "consideration", 68, "manual"),
    ("How to get cited by Perplexity AI", "decision", 85, "llm"),
    ("What is the best helpdesk software?", "consideration", 62, "manual"),
    ("How to optimize content for AI search", "awareness", 50, "llm"),
    ("Best project management tool for remote teams", "consideration", 74, "manual"),
    ("Enterprise CRM comparison 2025", "consideration", 66, "manual"),
    ("How do AI search engines rank sources?", "awareness", 42, "llm"),
    ("Best marketing automation for B2B", "consideration", 70, "manual"),
    ("How to track brand mentions in AI answers", "decision", 88, "llm"),
    ("What makes a website AI-crawlable?", "awareness", 48, "gsc"),
]


def get_connection_string() -> str:
    """Sync DSN: env override first, then the project .env (via pydantic-settings).

    The .env written by the Neon CLI carries DATABASE_URL[_UNPOOLED]; the
    Settings model normalizes it (sslmode, driver prefix) for psycopg2.
    """
    dsn = os.environ.get("DATABASE_URL_SYNC")
    if dsn:
        return dsn.replace("postgresql+asyncpg://", "postgresql://")
    from services.api.app.config import settings

    return settings.database_url_sync


def seed() -> None:
    """Run the seed script."""
    conn = psycopg2.connect(get_connection_string())
    conn.autocommit = True
    cur = conn.cursor()

    print("Seeding Footnote database...")

    # ── Auth user (simulated) ──
    cur.execute(
        """
        INSERT INTO auth.users (id, email, raw_user_meta_data)
        VALUES (%s, %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        (str(DEMO_USER_ID), "operator@footnote.dev", json.dumps({"name": "Demo Operator"})),
    )
    cur.execute(
        """
        INSERT INTO auth.users (id, email, raw_user_meta_data)
        VALUES (%s, %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        (str(DEMO_CLIENT_VIEWER_ID), "client@example.com", json.dumps({"name": "Demo Client Viewer"})),
    )

    # ── Organization ──
    cur.execute(
        """
        INSERT INTO organizations (id, name, slug)
        VALUES (%s, %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        (str(DEMO_ORG_ID), "Footnote Demo", "footnote-demo"),
    )

    # ── Org member (operator role) ──
    cur.execute(
        """
        INSERT INTO org_members (org_id, user_id, role)
        VALUES (%s, %s, 'owner')
        ON CONFLICT (org_id, user_id) DO NOTHING
        """,
        (str(DEMO_ORG_ID), str(DEMO_USER_ID)),
    )

    # ── Client ──
    cur.execute(
        """
        INSERT INTO clients (id, org_id, name, primary_domain, industry, country, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        (
            str(DEMO_CLIENT_ID), str(DEMO_ORG_ID),
            "Acme Corp", "acmecorp.com", "SaaS", "IN", "active",
        ),
    )

    # ── Client member (portal viewer) ──
    cur.execute(
        """
        INSERT INTO client_members (client_id, user_id, role)
        VALUES (%s, %s, 'client_viewer')
        ON CONFLICT (client_id, user_id) DO NOTHING
        """,
        (str(DEMO_CLIENT_ID), str(DEMO_CLIENT_VIEWER_ID)),
    )

    # ── Brand profile ──
    cur.execute(
        """
        INSERT INTO brand_profiles (client_id, voice, positioning, products, proof_points, banned_claims)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (client_id) DO UPDATE SET voice = EXCLUDED.voice
        """,
        (
            str(DEMO_CLIENT_ID),
            "Professional, data-driven, approachable",
            "The leading AI-visibility platform for modern brands",
            json.dumps([
                {"name": "AcmeTrack", "category": "AI Visibility Tracker"},
                {"name": "AcmeContent", "category": "Content Engine"},
            ]),
            json.dumps([
                {"type": "study", "claim": "92% citation accuracy", "source": "https://acmecorp.com/study-2024"},
                {"type": "certification", "claim": "ISO 27001 certified", "source": "https://acmecorp.com/security"},
            ]),
            ["#1 in the market", "guaranteed results", "beat all competitors"],
        ),
    )

    # ── Brand aliases ──
    for alias, is_primary in [("Acme Corp", True), ("Acme", False), ("AcmeCorp", False)]:
        cur.execute(
            """
            INSERT INTO brand_aliases (id, client_id, alias, is_primary)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (str(uuid4()), str(DEMO_CLIENT_ID), alias, is_primary),
        )

    # ── Competitors ──
    cur.execute(
        """
        INSERT INTO competitors (id, client_id, name, domain, aliases)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        (
            str(DEMO_COMPETITOR_ID), str(DEMO_CLIENT_ID),
            "RivalTech", "rivaltech.io", ["Rival", "RivalTech Inc"],
        ),
    )

    # ── Personas ──
    persona_id = uuid4()
    cur.execute(
        """
        INSERT INTO personas (id, client_id, name, description)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        (str(persona_id), str(DEMO_CLIENT_ID), "Startup Founder", "Early-stage tech founder evaluating tools"),
    )

    # ── Prompts (20) ──
    prompt_ids: list[UUID] = []
    for text_val, funnel, intent, source in DEMO_PROMPTS:
        pid = _sid("prompt", DEMO_CLIENT_ID, text_val)
        prompt_ids.append(pid)
        cur.execute(
            """
            INSERT INTO prompts (id, client_id, text, funnel_stage, lead_intent_score, source)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (str(pid), str(DEMO_CLIENT_ID), text_val, funnel, intent, source),
        )

    # ── Seed domains (before citations so they can link domain_id/competitor_id) ──
    domains = [
        ("acmecorp.com", "owned"),
        ("rivaltech.io", "competitor"),
        ("techcrunch.com", "news"),
        ("reddit.com", "forum"),
        ("g2.com", "review_site"),
    ]
    for domain_val, dtype in domains:
        cur.execute(
            """
            INSERT INTO domains (id, domain, domain_type)
            VALUES (%s, %s, %s)
            ON CONFLICT (domain) DO NOTHING
            """,
            (str(uuid4()), domain_val, dtype),
        )
    cur.execute(
        "SELECT domain, id FROM domains WHERE domain = ANY(%s)",
        ([d for d, _t in domains],),
    )
    domain_ids: dict[str, str] = {row[0]: str(row[1]) for row in cur.fetchall()}

    # ── Collection batch + fixture answers ──
    # The seed owns the demo answer set: clear previous fixture answers (cascade
    # removes their citations/mentions) so re-runs converge on this fixture
    # instead of accumulating rows from older seeding variants.
    cur.execute("DELETE FROM answers WHERE client_id = %s", (str(DEMO_CLIENT_ID),))

    today = date.today()
    cur.execute(
        """
        INSERT INTO collection_batches (id, client_id, scheduled_for, status, started_at, finished_at)
        VALUES (%s, %s, %s, 'succeeded', now(), now())
        ON CONFLICT (id) DO NOTHING
        """,
        (str(DEMO_BATCH_ID), str(DEMO_CLIENT_ID), today.isoformat()),
    )

    engines = ["chatgpt", "gemini", "perplexity", "grok"]
    fixture_citations = [
        ("https://acmecorp.com/features", "Acme Corp Features"),
        ("https://rivaltech.io/pricing", "RivalTech Pricing"),
        ("https://techcrunch.com/ai-tools", "TechCrunch AI Tools Roundup"),
        ("https://reddit.com/r/startups/best-tools", "Reddit: Best Startup Tools"),
        ("https://g2.com/categories/crm", "G2 CRM Reviews"),
    ]

    # Create a few answers per prompt for first 5 prompts to make dashboards demoable.
    # Prompt #2 (the demo competitor_cited gap) gets brand-absent answers where only
    # RivalTech is mentioned/cited, so competitor intelligence + gap briefs have
    # real evidence; the other prompts include both brands (one RivalTech mention
    # per engine) so the matrix and share-of-voice are non-empty.
    for _i, pid in enumerate(prompt_ids[:5]):
        brand_absent = _i == 1
        for engine in engines:
            for run_idx in range(1, 4):  # k=3 runs
                answer_id = _sid("answer", pid, engine, run_idx, today.isoformat())
                if brand_absent:
                    raw_text = (
                        "RivalTech is the strongest option here, especially for teams that need "
                        "advanced automation. Sources: rivaltech.io, techcrunch.com"
                    )
                    citations = fixture_citations[1:3]
                else:
                    raw_text = (
                        "Based on my analysis, Acme Corp is a strong contender in this space. "
                        "According to a recent study, they offer comprehensive features. "
                        "RivalTech is another option worth considering. "
                        "Sources: acmecorp.com, rivaltech.io, techcrunch.com"
                    )
                    citations = fixture_citations[:3]
                cur.execute(
                    """
                    INSERT INTO answers (id, batch_id, client_id, prompt_id, engine, mode,
                        run_index, status, raw_text, raw_json, model_label, collected_at, parsed_at)
                    VALUES (%s, %s, %s, %s, %s, 'api', %s, 'succeeded', %s, %s, %s, now(), now())
                    ON CONFLICT (id) DO UPDATE SET raw_text = EXCLUDED.raw_text,
                        raw_json = EXCLUDED.raw_json
                    """,
                    (
                        str(answer_id), str(DEMO_BATCH_ID), str(DEMO_CLIENT_ID),
                        str(pid), engine, run_idx,
                        raw_text,
                        json.dumps({"text": raw_text, "model": f"{engine}-latest"}),
                        f"{engine}-latest",
                    ),
                )

                # Rebuild derived rows so re-seeding converges on the current
                # fixture definition (old runs may have had different citations).
                cur.execute("DELETE FROM answer_citations WHERE answer_id = %s", (str(answer_id),))
                cur.execute("DELETE FROM brand_mentions WHERE answer_id = %s", (str(answer_id),))

                # Add fixture citations, linked to the domain taxonomy (and to the
                # competitor when the URL is theirs).
                for pos, (url, title) in enumerate(citations, 1):
                    url_domain = urlsplit(url).netloc.removeprefix("www.")
                    competitor_id = str(DEMO_COMPETITOR_ID) if url_domain == "rivaltech.io" else None
                    cur.execute(
                        """
                        INSERT INTO answer_citations (id, answer_id, client_id, url, title, domain_id,
                            position, is_brand_owned, competitor_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET domain_id = EXCLUDED.domain_id,
                            competitor_id = EXCLUDED.competitor_id,
                            is_brand_owned = EXCLUDED.is_brand_owned
                        """,
                        (
                            str(_sid("cite", answer_id, pos, url)), str(answer_id), str(DEMO_CLIENT_ID),
                            url, title, domain_ids.get(url_domain), pos,
                            url.startswith("https://acmecorp"), competitor_id,
                        ),
                    )

                # Brand mention (absent on the competitor_cited demo prompt).
                if not brand_absent:
                    cur.execute(
                        """
                        INSERT INTO brand_mentions (id, answer_id, client_id, entity_kind,
                            rank_in_answer, linked, recommended, sentiment)
                        VALUES (%s, %s, %s, 'brand', 1, true, true, 'positive')
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (str(_sid("mention", answer_id)), str(answer_id), str(DEMO_CLIENT_ID)),
                    )

                # Competitor mentions: every run on the brand-absent prompt, one per
                # engine elsewhere (so share of voice has a denominator).
                if brand_absent or run_idx == 1:
                    cur.execute(
                        """
                        INSERT INTO brand_mentions (id, answer_id, client_id, entity_kind, competitor_id,
                            rank_in_answer, linked, recommended, sentiment, excerpt)
                        VALUES (%s, %s, %s, 'competitor', %s, %s, false, %s, 'neutral', %s)
                        ON CONFLICT (id) DO UPDATE SET competitor_id = EXCLUDED.competitor_id
                        """,
                        (
                            str(_sid("comp-mention", answer_id)), str(answer_id), str(DEMO_CLIENT_ID),
                            str(DEMO_COMPETITOR_ID), 1 if brand_absent else 2,
                            brand_absent, "RivalTech is the strongest option here" if brand_absent
                            else "RivalTech is another option worth considering",
                        ),
                    )

    # ── Seed demo gaps (slipped + competitor_cited) ──
    demo_gaps = [
        ("slipped", prompt_ids[0], {"day": today.isoformat(), "previous_rank": 3}),
        ("competitor_cited", prompt_ids[1], {"day": today.isoformat(), "competitor_domain": "rivaltech.io"}),
        ("slipped", prompt_ids[2], {"day": today.isoformat(), "previous_rank": 5}),
    ]
    for gap_type, pid, details in demo_gaps:
        cur.execute(
            """
            INSERT INTO gaps (id, client_id, prompt_id, gap_type, details, status)
            SELECT %s, %s, %s, %s, %s, 'open'
            WHERE NOT EXISTS (
                SELECT 1 FROM gaps WHERE client_id = %s AND prompt_id = %s AND gap_type = %s AND status = 'open'
            )
            """,
            (str(uuid4()), str(DEMO_CLIENT_ID), str(pid), gap_type, json.dumps(details),
             str(DEMO_CLIENT_ID), str(pid), gap_type),
        )

    # ── Seed daily_metrics for last 7 days ──
    for day_offset in range(7):
        d = date.fromordinal(today.toordinal() - day_offset)
        for engine in engines:
            cur.execute(
                """
                INSERT INTO daily_metrics (client_id, day, engine, prompts_tracked, prompts_visible,
                    mention_rate, linked_rate, brand_citations, total_citations, citation_share,
                    share_of_voice, avg_sentiment)
                VALUES (%s, %s, %s, 20, %s, %s, %s, %s, %s, %s, %s, 0.7)
                ON CONFLICT (client_id, day, engine) DO NOTHING
                """,
                (
                    str(DEMO_CLIENT_ID), d.isoformat(), engine,
                    12 + (day_offset % 5),                    # prompts_visible
                    round(0.65 + (day_offset % 3) * 0.05, 2), # mention_rate
                    round(0.40 + (day_offset % 4) * 0.08, 2), # linked_rate
                    15 + day_offset,                           # brand_citations
                    45 + day_offset * 2,                       # total_citations
                    round(0.33 + (day_offset % 3) * 0.04, 2), # citation_share
                    round(0.45 + (day_offset % 2) * 0.05, 2), # share_of_voice
                ),
            )

    cur.close()
    conn.close()
    print("Seed complete!")
    print(f"   Org: {DEMO_ORG_ID}")
    print(f"   User (operator): {DEMO_USER_ID} / operator@footnote.dev")
    print(f"   User (client viewer): {DEMO_CLIENT_VIEWER_ID} / client@example.com")
    print(f"   Client: {DEMO_CLIENT_ID} / Acme Corp")
    print(f"   Prompts: {len(DEMO_PROMPTS)}")
    print(f"   Answers: {5 * 4 * 3} (5 prompts x 4 engines x 3 runs)")


if __name__ == "__main__":
    seed()
