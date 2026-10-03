"""Seed script: creates a demo organization, client, prompts, and fixture answers.

Run with: python -m services.api.scripts.seed
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import psycopg2

# Fixed UUIDs for reproducible seeding
DEMO_ORG_ID = UUID("10000000-0000-0000-0000-000000000001")
DEMO_USER_ID = UUID("20000000-0000-0000-0000-000000000001")
DEMO_CLIENT_ID = UUID("30000000-0000-0000-0000-000000000001")
DEMO_CLIENT_VIEWER_ID = UUID("20000000-0000-0000-0000-000000000002")
DEMO_COMPETITOR_ID = UUID("40000000-0000-0000-0000-000000000001")
DEMO_BATCH_ID = UUID("50000000-0000-0000-0000-000000000001")


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
    """Get the sync connection string for seeding."""
    return os.environ.get(
        "DATABASE_URL_SYNC",
        "postgresql://postgres:postgres@db:5432/footnote",
    )


def seed() -> None:
    """Run the seed script."""
    conn = psycopg2.connect(get_connection_string())
    conn.autocommit = True
    cur = conn.cursor()

    print("🌱 Seeding Footnote database...")

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
        pid = uuid4()
        prompt_ids.append(pid)
        cur.execute(
            """
            INSERT INTO prompts (id, client_id, text, funnel_stage, lead_intent_score, source)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (str(pid), str(DEMO_CLIENT_ID), text_val, funnel, intent, source),
        )

    # ── Collection batch + fixture answers ──
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

    # Create a few answers per prompt for first 5 prompts to make dashboards demoable
    for i, pid in enumerate(prompt_ids[:5]):
        for engine in engines:
            for run_idx in range(1, 4):  # k=3 runs
                answer_id = uuid4()
                raw_text = (
                    f"Based on my analysis, Acme Corp is a strong contender in this space. "
                    f"According to a recent study, they offer comprehensive features. "
                    f"RivalTech is another option worth considering. "
                    f"Sources: acmecorp.com, rivaltech.io, techcrunch.com"
                )
                cur.execute(
                    """
                    INSERT INTO answers (id, batch_id, client_id, prompt_id, engine, mode,
                        run_index, status, raw_text, raw_json, model_label, collected_at, parsed_at)
                    VALUES (%s, %s, %s, %s, %s, 'api', %s, 'succeeded', %s, %s, %s, now(), now())
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        str(answer_id), str(DEMO_BATCH_ID), str(DEMO_CLIENT_ID),
                        str(pid), engine, run_idx,
                        raw_text,
                        json.dumps({"text": raw_text, "model": f"{engine}-latest"}),
                        f"{engine}-latest",
                    ),
                )

                # Add fixture citations
                for pos, (url, title) in enumerate(fixture_citations[:3], 1):
                    cur.execute(
                        """
                        INSERT INTO answer_citations (id, answer_id, client_id, url, title, position,
                            is_brand_owned)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            str(uuid4()), str(answer_id), str(DEMO_CLIENT_ID),
                            url, title, pos, url.startswith("https://acmecorp"),
                        ),
                    )

                # Add brand mention
                cur.execute(
                    """
                    INSERT INTO brand_mentions (id, answer_id, client_id, entity_kind,
                        rank_in_answer, linked, recommended, sentiment)
                    VALUES (%s, %s, %s, 'brand', 1, true, true, 'positive')
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (str(uuid4()), str(answer_id), str(DEMO_CLIENT_ID)),
                )

    # ── Seed domains ──
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
    print("✅ Seed complete!")
    print(f"   Org: {DEMO_ORG_ID}")
    print(f"   User (operator): {DEMO_USER_ID} / operator@footnote.dev")
    print(f"   User (client viewer): {DEMO_CLIENT_VIEWER_ID} / client@example.com")
    print(f"   Client: {DEMO_CLIENT_ID} / Acme Corp")
    print(f"   Prompts: {len(DEMO_PROMPTS)}")
    print(f"   Answers: {5 * 4 * 3} (5 prompts × 4 engines × 3 runs)")


if __name__ == "__main__":
    seed()
