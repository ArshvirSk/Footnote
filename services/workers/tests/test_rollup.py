"""Integration tests for the nightly rollup math (PRD §1.7) against the configured database.

Builds a controlled fixture (3 prompts, 7 runs for the target day) with known
expected metric values, runs compute_rollup_for_day, and asserts exact numbers.
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import psycopg2
import pytest
from services.api.app.db import engine
from services.api.tests.conftest import get_admin_dsn
from services.workers.app.worker import compute_rollup_for_day

ORG_ID = UUID("f0000000-0000-0000-0000-000000000001")
CLIENT_ID = UUID("f0000000-0000-0000-0000-00000000cafe")
COMP_ID = UUID("f0000000-0000-0000-0000-000000000021")
P_VISIBLE = UUID("f0000000-0000-0000-0000-000000000011")
P_COMP = UUID("f0000000-0000-0000-0000-000000000012")
P_SLIP = UUID("f0000000-0000-0000-0000-000000000013")
BRAND_DOMAIN = "rollup-brand-test.example"
COMP_DOMAIN = "rollup-competitor-test.example"

DAY = datetime.now(UTC).date()
PREV_DAY = DAY - timedelta(days=3)


def _add_answer(
    cur: psycopg2.extensions.cursor,
    prompt_id: UUID,
    run_index: int,
    batch_day: date,
    *,
    mention: tuple[str, str, bool] | None = None,
    cite: str | None = None,
) -> None:
    """Insert one succeeded answer. mention = (entity_kind, sentiment, linked); cite = brand|competitor."""
    cur.execute(
        """
        INSERT INTO answers (batch_id, client_id, prompt_id, engine, mode, run_index, status, collected_at)
        SELECT b.id, b.client_id, %s, 'chatgpt', 'api', %s, 'succeeded',
               CAST(b.scheduled_for AS date) + interval '12 hours'
        FROM collection_batches b
        WHERE b.client_id = %s AND b.scheduled_for = %s
        RETURNING id
        """,
        (str(prompt_id), run_index, str(CLIENT_ID), batch_day),
    )
    answer_id = cur.fetchone()[0]

    if mention:
        kind, sentiment, linked = mention
        cur.execute(
            """
            INSERT INTO brand_mentions (answer_id, client_id, entity_kind, competitor_id, linked, recommended, sentiment)
            VALUES (%s, %s, %s, %s, %s, true, %s)
            """,
            (
                str(answer_id),
                str(CLIENT_ID),
                kind,
                str(COMP_ID) if kind == "competitor" else None,
                linked,
                sentiment,
            ),
        )

    if cite == "brand":
        cur.execute(
            """
            INSERT INTO answer_citations (answer_id, client_id, url, domain_id, position, is_brand_owned)
            VALUES (%s, %s, %s, (SELECT id FROM domains WHERE domain = %s), 1, true)
            """,
            (str(answer_id), str(CLIENT_ID), f"https://{BRAND_DOMAIN}/page", BRAND_DOMAIN),
        )
    elif cite == "competitor":
        cur.execute(
            """
            INSERT INTO answer_citations (answer_id, client_id, url, domain_id, position, is_brand_owned, competitor_id)
            VALUES (%s, %s, %s, (SELECT id FROM domains WHERE domain = %s), 1, false, %s)
            """,
            (
                str(answer_id),
                str(CLIENT_ID),
                f"https://{COMP_DOMAIN}/page",
                COMP_DOMAIN,
                str(COMP_ID),
            ),
        )


@pytest.fixture()
def rollup_db() -> Generator[psycopg2.extensions.connection, None, None]:
    """Create fixture tenants/data for DAY, and clean everything up afterwards."""
    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = False
    cur = conn.cursor()

    def wipe() -> None:
        conn.rollback()
        # Deleting the org cascades to client-scoped rows (answers, metrics, gaps, ...)
        cur.execute("DELETE FROM organizations WHERE id = %s", (str(ORG_ID),))
        cur.execute("DELETE FROM domains WHERE domain IN (%s, %s)", (BRAND_DOMAIN, COMP_DOMAIN))
        conn.commit()

    wipe()  # idempotent re-runs after a failed test

    cur.execute(
        "INSERT INTO organizations (id, name, slug) VALUES (%s, 'Rollup Test Org', 'rollup-test-org') "
        "ON CONFLICT (id) DO NOTHING",
        (str(ORG_ID),),
    )
    cur.execute(
        "INSERT INTO clients (id, org_id, name, primary_domain, status) VALUES (%s, %s, 'Rollup Brand', %s, 'active')",
        (str(CLIENT_ID), str(ORG_ID), BRAND_DOMAIN),
    )
    cur.execute(
        "INSERT INTO competitors (id, client_id, name, domain) VALUES (%s, %s, 'RollupRival', %s)",
        (str(COMP_ID), str(CLIENT_ID), COMP_DOMAIN),
    )
    for pid, prompt_text in [
        (P_VISIBLE, "rollup: visible prompt"),
        (P_COMP, "rollup: competitor-cited prompt"),
        (P_SLIP, "rollup: slipping prompt"),
    ]:
        cur.execute(
            "INSERT INTO prompts (id, client_id, text, engines) VALUES (%s, %s, %s, '{chatgpt}')",
            (str(pid), str(CLIENT_ID), prompt_text),
        )
    cur.execute(
        "INSERT INTO collection_batches (client_id, scheduled_for) VALUES (%s, %s), (%s, %s)",
        (str(CLIENT_ID), DAY, str(CLIENT_ID), PREV_DAY),
    )
    for dom in (BRAND_DOMAIN, COMP_DOMAIN):
        cur.execute("INSERT INTO domains (domain) VALUES (%s) ON CONFLICT (domain) DO NOTHING", (dom,))
    conn.commit()

    yield conn
    wipe()
    conn.close()


def _run_rollup(day_str: str) -> dict[str, int]:
    """Run the rollup on its own event loop, disposing pooled asyncpg connections.

    Each asyncio.run() creates a fresh loop; pooled connections from the previous
    loop are unusable, so the engine is disposed at the end of every run.
    """

    async def _inner() -> dict[str, int]:
        try:
            return await compute_rollup_for_day(day_str)
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


def test_rollup_math_matches_prd_definitions(rollup_db: psycopg2.extensions.connection) -> None:
    cur = rollup_db.cursor()

    # P1 (visible): 4 runs today, brand mentioned in 3 -> visible (3*2 >= 4)
    _add_answer(cur, P_VISIBLE, 1, DAY, mention=("brand", "positive", True), cite="brand")
    _add_answer(cur, P_VISIBLE, 2, DAY, mention=("brand", "positive", False), cite="competitor")
    _add_answer(cur, P_VISIBLE, 3, DAY, mention=("brand", "negative", True), cite="brand")
    _add_answer(cur, P_VISIBLE, 4, DAY)

    # P2 (gap): competitor cited + mentioned, brand absent both runs
    _add_answer(cur, P_COMP, 1, DAY, mention=("competitor", "neutral", False), cite="competitor")
    _add_answer(cur, P_COMP, 2, DAY, cite="competitor")

    # P3 (slip): visible 3 days ago, ran today without a mention
    _add_answer(cur, P_SLIP, 1, PREV_DAY, mention=("brand", "positive", True), cite="brand")
    _add_answer(cur, P_SLIP, 1, DAY)
    rollup_db.commit()  # make fixtures visible to the rollup's own connection

    stats = _run_rollup(DAY.isoformat())
    assert stats["daily_metrics_rows"] >= 1

    cur.execute(
        """
        SELECT prompts_tracked, prompts_visible, mention_rate, linked_rate,
               brand_citations, total_citations, citation_share, share_of_voice, avg_sentiment
        FROM daily_metrics
        WHERE client_id = %s AND day = %s AND engine = 'chatgpt'
        """,
        (str(CLIENT_ID), DAY),
    )
    row = cur.fetchone()
    assert row is not None, "daily_metrics row missing for fixture client"
    tracked, visible, mention_rate, linked_rate, brand_cites, total_cites, cite_share, sov, avg_sent = row
    # numeric columns come back as Decimal; compare as floats
    mention_rate, linked_rate, cite_share, sov, avg_sent = map(
        float, (mention_rate, linked_rate, cite_share, sov, avg_sent)
    )

    assert (tracked, visible) == (3, 1)
    assert mention_rate == pytest.approx(3 / 7)  # 3 brand-mention runs of 7 succeeded runs
    assert linked_rate == pytest.approx(2 / 3)  # 2 of 3 brand mentions link to our domain
    assert (brand_cites, total_cites) == (2, 5)  # no join fan-out: 5 citations total
    assert cite_share == pytest.approx(2 / 5)
    assert sov == pytest.approx(3 / 4)  # 3 brand vs 1 competitor mention
    assert avg_sent == pytest.approx((1 + 1 - 1) / 3)  # positive, positive, negative

    # Gap detection: exactly one slip (P3) and one competitor gap (P2)
    cur.execute("SELECT gap_type, prompt_id FROM gaps WHERE client_id = %s", (str(CLIENT_ID),))
    # psycopg2 returns uuid columns as str unless extras.register_uuid is used
    gaps = {(gap_type, str(prompt)) for gap_type, prompt in cur.fetchall()}
    assert gaps == {("slipped", str(P_SLIP)), ("competitor_cited", str(P_COMP))}

    # Domain rollup: brand domain cited twice and flagged is_brand
    cur.execute(
        """
        SELECT dcd.citations, dcd.is_brand
        FROM domain_citation_daily dcd
        JOIN domains d ON d.id = dcd.domain_id
        WHERE dcd.client_id = %s AND dcd.day = %s AND d.domain = %s
        """,
        (str(CLIENT_ID), DAY, BRAND_DOMAIN),
    )
    drow = cur.fetchone()
    assert drow is not None
    assert (drow[0], drow[1]) == (2, True)

    # Idempotency: re-running must not duplicate gaps or drift metrics
    _run_rollup(DAY.isoformat())
    cur.execute("SELECT COUNT(*) FROM gaps WHERE client_id = %s", (str(CLIENT_ID),))
    assert cur.fetchone()[0] == 2
    cur.execute(
        "SELECT mention_rate, citation_share, share_of_voice FROM daily_metrics "
        "WHERE client_id = %s AND day = %s AND engine = 'chatgpt'",
        (str(CLIENT_ID), DAY),
    )
    again = cur.fetchone()
    assert again is not None
    again = tuple(float(x) for x in again)
    assert again[0] == pytest.approx(mention_rate)
    assert again[1] == pytest.approx(cite_share)
    assert again[2] == pytest.approx(sov)
