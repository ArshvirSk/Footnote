"""Tests for Milestone 1: derived website status, setup checklist, dashboard,
brand profile, brand memory ingestion, competitors/personas and prompt lifecycle.

Pure-logic tests run without a database; API tests exercise the real routes
against the configured database and clean up every row they create.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from uuid import uuid4

import psycopg2
import pytest
from fastapi.testclient import TestClient
from services.api.app.db import engine
from services.api.app.main import app
from services.api.app.website_status import (
    SETUP_TOTAL,
    WebsiteFacts,
    checklist,
    derive_status,
)
from services.api.tests.conftest import CLIENT_A_ID, get_admin_dsn

BRAND_DOMAIN = "m1-dashboard.example"


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c
        assert c.portal is not None
        c.portal.call(engine.dispose)


def _token(client: TestClient, email: str = "user_a@test.com") -> str:
    res = client.post("/api/v1/auth/dev-login", json={"email": email})
    assert res.status_code == 200, res.text
    token: str = res.json()["access_token"]
    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def fixture_client(client: TestClient) -> Generator[str, None, None]:
    """A fresh website owned by org A, deleted (cascade) after the test.

    Real client rows let cap/lifecycle tests start from a known-empty state
    instead of depending on rows left by other test runs.
    """
    token = _token(client)
    res = client.post(
        "/api/v1/clients",
        headers=_auth(token),
        json={"name": "M1 Fixture Site", "primary_domain": "m1-fixture.example"},
    )
    assert res.status_code == 201, res.text
    client_id = res.json()["id"]
    yield client_id
    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = True
    conn.cursor().execute("DELETE FROM clients WHERE id = %s", (client_id,))
    conn.close()


# ──── Pure logic: checklist + derived status ────


class TestChecklistLogic:
    def test_fresh_website_is_empty_onboarding(self) -> None:
        facts = WebsiteFacts()
        assert facts.setup_progress == 0
        assert derive_status(facts, "onboarding") == "onboarding"
        assert facts.visibility_pct is None
        assert all(not item["done"] for item in checklist(facts, "abc"))

    def test_complete_website_is_active(self) -> None:
        facts = WebsiteFacts(
            brand_profile_items=1,
            competitors_count=2,
            personas_count=1,
            active_prompts=25,
            succeeded_answers=10,
            finished_audits=1,
            publish_targets=1,
        )
        assert facts.setup_progress == SETUP_TOTAL
        assert derive_status(facts, "onboarding") == "active"

    def test_lifecycle_status_wins_over_checklist(self) -> None:
        complete = WebsiteFacts(
            brand_profile_items=1, competitors_count=1, personas_count=1,
            active_prompts=25, succeeded_answers=1, finished_audits=1, publish_targets=1,
        )
        assert derive_status(complete, "paused") == "paused"
        assert derive_status(complete, "churned") == "churned"

    def test_visibility_pct_and_zero_denominator(self) -> None:
        # Ratio 0..1 (the client formats as a percentage).
        assert WebsiteFacts(visible_7d=3, tracked_7d=4).visibility_pct == 0.75
        assert WebsiteFacts(visible_7d=0, tracked_7d=0).visibility_pct is None

    def test_prompt_item_requires_25_active(self) -> None:
        facts = WebsiteFacts(active_prompts=24)
        item = next(i for i in checklist(facts) if i["key"] == "prompts")
        assert item["done"] is False
        assert "24 of 25" in item["detail"]
        assert WebsiteFacts(active_prompts=25).setup_progress == 1

    def test_checklist_links_include_client_id(self) -> None:
        item = next(i for i in checklist(WebsiteFacts(), "cid-1") if i["key"] == "brand_profile")
        assert item["href"] == "/ops/websites/cid-1#brand"


# ──── API: list, demo filter, setup ────


class TestWebsiteList:
    def test_demo_websites_hidden_by_default(self, client: TestClient) -> None:
        token = _token(client)
        res = client.get("/api/v1/clients", headers=_auth(token))
        assert res.status_code == 200, res.text
        rows = res.json()
        # Client A is a fixture website and is flagged demo by migration 0002.
        assert "Client A" not in {r["name"] for r in rows}
        assert all(r["is_demo"] is False for r in rows)

    def test_include_demo_returns_them_with_flag(self, client: TestClient) -> None:
        token = _token(client)
        res = client.get("/api/v1/clients", headers=_auth(token), params={"include_demo": "true"})
        assert res.status_code == 200, res.text
        rows = res.json()
        row = next(r for r in rows if r["name"] == "Client A")
        assert row["is_demo"] is True
        assert row["derived_status"] == "onboarding"
        assert row["setup_total"] == SETUP_TOTAL
        assert len(row["checklist"]) == SETUP_TOTAL
        # conftest seeds a brand profile + one prompt for Client A.
        brand = next(i for i in row["checklist"] if i["key"] == "brand_profile")
        assert brand["done"] is True
        assert row["setup_progress"] >= 1

    def test_setup_endpoint_matches_list(self, client: TestClient) -> None:
        token = _token(client)
        res = client.get(f"/api/v1/clients/{CLIENT_A_ID}/setup", headers=_auth(token))
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["total"] == SETUP_TOTAL
        assert body["status"] == "onboarding"
        assert {i["key"] for i in body["items"]} == {
            "brand_profile", "competitors", "personas", "prompts",
            "baseline", "site_audit", "publish_target",
        }

    def test_setup_cross_tenant_is_forbidden(self, client: TestClient) -> None:
        token = _token(client, "user_b@test.com")
        res = client.get(f"/api/v1/clients/{CLIENT_A_ID}/setup", headers=_auth(token))
        assert res.status_code == 403


# ──── API: competitors + personas CRUD ────


class TestEntities:
    def test_competitor_crud_roundtrip(self, client: TestClient) -> None:
        token = _token(client)
        created = client.post(
            f"/api/v1/clients/{CLIENT_A_ID}/competitors",
            headers=_auth(token),
            json={"name": "M1 Rival", "domain": "www.m1rival.example", "aliases": ["M1R"]},
        )
        assert created.status_code == 201, created.text
        comp = created.json()
        assert comp["domain"] == "m1rival.example"
        assert comp["aliases"] == ["M1R"]

        updated = client.patch(
            f"/api/v1/clients/{CLIENT_A_ID}/competitors/{comp['id']}",
            headers=_auth(token),
            json={"name": "M1 Rival Renamed"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["name"] == "M1 Rival Renamed"

        deleted = client.delete(
            f"/api/v1/clients/{CLIENT_A_ID}/competitors/{comp['id']}", headers=_auth(token)
        )
        assert deleted.status_code == 204

    def test_persona_crud_roundtrip(self, client: TestClient) -> None:
        token = _token(client)
        created = client.post(
            f"/api/v1/clients/{CLIENT_A_ID}/personas",
            headers=_auth(token),
            json={"name": "M1 Persona", "description": "Ops manager evaluating tools"},
        )
        assert created.status_code == 201, created.text
        persona = created.json()

        listed = client.get(f"/api/v1/clients/{CLIENT_A_ID}/personas", headers=_auth(token))
        assert any(p["id"] == persona["id"] for p in listed.json())

        deleted = client.delete(
            f"/api/v1/clients/{CLIENT_A_ID}/personas/{persona['id']}", headers=_auth(token)
        )
        assert deleted.status_code == 204

    def test_cross_tenant_write_is_forbidden(self, client: TestClient) -> None:
        token = _token(client, "user_b@test.com")
        res = client.post(
            f"/api/v1/clients/{CLIENT_A_ID}/competitors",
            headers=_auth(token),
            json={"name": "Should not exist"},
        )
        assert res.status_code == 403

    def test_prompt_with_foreign_persona_is_rejected(self, client: TestClient) -> None:
        token = _token(client)
        res = client.post(
            f"/api/v1/clients/{CLIENT_A_ID}/prompts",
            headers=_auth(token),
            json={"text": "M1 prompt with bad persona", "persona_id": str(uuid4())},
        )
        assert res.status_code == 404


# ──── API: prompt cap + retire ────


class TestPromptLifecycle:
    @pytest.fixture()
    def small_cap(self, fixture_client: str) -> Generator[str, None, None]:
        """A fresh website with a lowered active-prompt cap (2)."""
        conn = psycopg2.connect(get_admin_dsn())
        conn.autocommit = True
        conn.cursor().execute(
            "UPDATE clients SET settings = jsonb_set(coalesce(settings, '{}'::jsonb), "
            "'{billing_limits}', '{\"max_prompts\": 2}'::jsonb) WHERE id = %s",
            (fixture_client,),
        )
        conn.close()
        yield fixture_client

    def test_active_cap_enforced(self, client: TestClient, small_cap: str) -> None:
        """Cap=2: two prompts fit, the third is rejected, retiring frees a slot."""
        token = _token(client)
        base = f"/api/v1/clients/{small_cap}/prompts"
        first = client.post(base, headers=_auth(token), json={"text": "M1 cap prompt one"})
        assert first.status_code == 201, first.text
        second = client.post(base, headers=_auth(token), json={"text": "M1 cap prompt two"})
        assert second.status_code == 201, second.text

        third = client.post(base, headers=_auth(token), json={"text": "M1 cap prompt three"})
        assert third.status_code == 400
        assert "active prompts limit" in third.json()["detail"]

        # Retiring one frees a slot.
        retired = client.patch(
            f"{base}/{second.json()['id']}", headers=_auth(token), json={"is_active": False}
        )
        assert retired.status_code == 200, retired.text
        assert retired.json()["is_active"] is False

        fourth = client.post(base, headers=_auth(token), json={"text": "M1 cap prompt four"})
        assert fourth.status_code == 201, fourth.text

    def test_retired_at_is_set_when_retired(self, client: TestClient, fixture_client: str) -> None:
        token = _token(client)
        created = client.post(
            f"/api/v1/clients/{fixture_client}/prompts",
            headers=_auth(token),
            json={"text": "M1 retire prompt"},
        )
        assert created.status_code == 201, created.text
        pid = created.json()["id"]

        patched = client.patch(
            f"/api/v1/clients/{fixture_client}/prompts/{pid}",
            headers=_auth(token),
            json={"is_active": False},
        )
        assert patched.status_code == 200

        conn = psycopg2.connect(get_admin_dsn())
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT retired_at FROM prompts WHERE id = %s", (pid,))
        assert cur.fetchone()[0] is not None
        conn.close()

    def test_patch_cross_tenant_is_forbidden(self, client: TestClient) -> None:
        token = _token(client, "user_b@test.com")
        res = client.patch(
            f"/api/v1/clients/{CLIENT_A_ID}/prompts/{uuid4()}",
            headers=_auth(token),
            json={"text": "nope"},
        )
        assert res.status_code == 403


# ──── API: brand profile + aliases + memory ────


class TestBrandProfile:
    def test_profile_roundtrip_and_aliases(self, client: TestClient) -> None:
        token = _token(client)
        original = client.get(f"/api/v1/clients/{CLIENT_A_ID}/brand-profile", headers=_auth(token)).json()

        payload = {
            "voice": "Plain-spoken, evidence-led",
            "positioning": "M1 test positioning",
            "products": [{"name": "M1 Product", "category": "Testing"}],
            "icp": {"summary": "Ops leads at mid-size firms"},
            "proof_points": [{"claim": "99% uptime", "source": "https://client-a.com/status"}],
            "banned_claims": ["guaranteed #1"],
            "aliases": ["ClientA", "Client A"] + (original.get("aliases") or []),
        }
        saved = client.put(f"/api/v1/clients/{CLIENT_A_ID}/brand-profile", headers=_auth(token), json=payload)
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["voice"] == "Plain-spoken, evidence-led"
        assert body["products"][0]["name"] == "M1 Product"
        assert body["banned_claims"] == ["guaranteed #1"]
        assert set(body["aliases"]) >= {"ClientA", "Client A"}

        # restore
        client.put(
            f"/api/v1/clients/{CLIENT_A_ID}/brand-profile",
            headers=_auth(token),
            json={
                "voice": original["voice"],
                "positioning": original["positioning"],
                "products": original["products"],
                "icp": original["icp"],
                "proof_points": original["proof_points"],
                "banned_claims": original["banned_claims"],
                "aliases": original["aliases"],
            },
        )

    def test_alias_add_and_delete(self, client: TestClient) -> None:
        token = _token(client)
        created = client.post(
            f"/api/v1/clients/{CLIENT_A_ID}/brand-aliases",
            headers=_auth(token),
            json={"alias": "M1 Alias"},
        )
        assert created.status_code == 201, created.text
        alias_id = created.json()["id"]
        deleted = client.delete(
            f"/api/v1/clients/{CLIENT_A_ID}/brand-aliases/{alias_id}", headers=_auth(token)
        )
        assert deleted.status_code == 204

    def test_cross_tenant_profile_write_is_forbidden(self, client: TestClient) -> None:
        token = _token(client, "user_b@test.com")
        res = client.put(
            f"/api/v1/clients/{CLIENT_A_ID}/brand-profile", headers=_auth(token), json={"voice": "hacked"}
        )
        assert res.status_code == 403


class TestBrandMemory:
    def test_ingest_without_provider_is_explicit_503(self, client: TestClient) -> None:
        """No embedding key => 503; never a placeholder vector."""
        token = _token(client)
        res = client.post(
            f"/api/v1/clients/{CLIENT_A_ID}/brand-memory/ingest",
            headers=_auth(token),
            json={"kind": "text", "text": "A document long enough to be chunked and embedded. " * 4},
        )
        assert res.status_code == 503
        assert "OPENAI_API_KEY" in res.json()["detail"]

    def test_ingest_stores_chunks_and_lists_deletes(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With the provider stubbed, the full write/read/delete path runs."""
        from services.api.app.routes import brand as brand_module

        async def fake_embed(texts: list[str], transport: object = None) -> tuple[list[list[float]], int]:
            return [[0.001] * 1536 for _ in texts], 123

        monkeypatch.setattr(brand_module, "embed_texts", fake_embed)

        token = _token(client)
        res = client.post(
            f"/api/v1/clients/{CLIENT_A_ID}/brand-memory/ingest",
            headers=_auth(token),
            json={"kind": "text", "title": "M1 Doc", "text": "Word " * 1200},
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["chunks"] >= 2
        assert body["tokens"] == 123
        assert body["cost_usd"] > 0

        listed = client.get(f"/api/v1/clients/{CLIENT_A_ID}/brand-memory", headers=_auth(token)).json()
        mine = [c for c in listed if c["title"] == "M1 Doc"]
        assert len(mine) == body["chunks"]

        for chunk in mine:
            deleted = client.delete(
                f"/api/v1/clients/{CLIENT_A_ID}/brand-memory/{chunk['id']}", headers=_auth(token)
            )
            assert deleted.status_code == 204

        # cost logged to agent_runs
        conn = psycopg2.connect(get_admin_dsn())
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            "SELECT tokens_in, cost_usd, status FROM agent_runs "
            "WHERE client_id = %s AND agent = 'brand_ingest' ORDER BY started_at DESC LIMIT 1",
            (str(CLIENT_A_ID),),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 123 and row[2] == "succeeded"
        # agent_runs.cost_usd is numeric(10,4); sub-$0.0001 embedding calls round to 0.
        assert float(row[1]) >= 0
        cur.execute(
            "DELETE FROM agent_runs WHERE client_id = %s AND agent = 'brand_ingest' AND input->>'title' = 'M1 Doc'",
            (str(CLIENT_A_ID),),
        )
        conn.close()


# ──── API: dashboard with real collected data ────


@pytest.fixture()
def dashboard_data() -> Generator[tuple[str, str], None, None]:
    """A dedicated website (org A) with known last-7-days runs.

    Created fresh so exact assertions can't be polluted by rows other test
    runs left behind; the whole website is deleted (cascade) afterwards.

    P1: 3 runs, brand mentioned in all 3 (visible), brand cited 2x, 1 third-party citation.
    P2: 2 runs, no brand mention (not visible), competitor mentioned once.
    """
    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = True
    cur = conn.cursor()
    from services.api.tests.conftest import ORG_A_ID

    dash_id = uuid4()
    p1, p2 = uuid4(), uuid4()
    comp_id = uuid4()
    try:
        cur.execute(
            "INSERT INTO clients (id, org_id, name, primary_domain) VALUES (%s, %s, 'M1 Dashboard Site', %s)",
            (str(dash_id), str(ORG_A_ID), BRAND_DOMAIN),
        )
        cur.execute(
            "INSERT INTO domains (domain) VALUES (%s) ON CONFLICT (domain) DO NOTHING", (BRAND_DOMAIN,),
        )
        cur.execute(
            "INSERT INTO prompts (id, client_id, text, engines) VALUES (%s, %s, 'M1 dashboard prompt A', '{chatgpt}'), "
            "(%s, %s, 'M1 dashboard prompt B', '{chatgpt}')",
            (str(p1), str(dash_id), str(p2), str(dash_id)),
        )
        cur.execute(
            "INSERT INTO competitors (id, client_id, name, domain) VALUES (%s, %s, 'M1 Dash Rival', 'm1dashrival.example')",
            (str(comp_id), str(dash_id)),
        )
        cur.execute(
            "INSERT INTO collection_batches (client_id, scheduled_for) VALUES (%s, current_date)",
            (str(dash_id),),
        )
        cur.execute(
            "SELECT id FROM collection_batches WHERE client_id = %s AND scheduled_for = current_date",
            (str(dash_id),),
        )
        batch_id = cur.fetchone()[0]
        # P1 runs: 3 mentioned (2 linked), 2 brand citations + 1 other-domain citation
        for i, linked in enumerate((True, True, False), start=1):
            cur.execute(
                "INSERT INTO answers (batch_id, client_id, prompt_id, engine, mode, run_index, status, collected_at) "
                "VALUES (%s, %s, %s, 'chatgpt', 'api', %s, 'succeeded', now() - interval '1 day') RETURNING id",
                (batch_id, str(dash_id), str(p1), i),
            )
            aid = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO brand_mentions (answer_id, client_id, entity_kind, linked, recommended, sentiment) "
                "VALUES (%s, %s, 'brand', %s, true, 'positive')",
                (aid, str(dash_id), linked),
            )
            domain = BRAND_DOMAIN if i <= 2 else "m1-thirdparty.example"
            cur.execute("INSERT INTO domains (domain) VALUES (%s) ON CONFLICT (domain) DO NOTHING", (domain,))
            cur.execute(
                "INSERT INTO answer_citations (answer_id, client_id, url, domain_id, position, is_brand_owned) "
                "VALUES (%s, %s, %s, (SELECT id FROM domains WHERE domain = %s), 1, %s)",
                (aid, str(dash_id), f"https://{domain}/p", domain, i <= 2),
            )
        # P2 runs: no brand mention, competitor mentioned once
        for i in (1, 2):
            cur.execute(
                "INSERT INTO answers (batch_id, client_id, prompt_id, engine, mode, run_index, status, collected_at) "
                "VALUES (%s, %s, %s, 'chatgpt', 'api', %s, 'succeeded', now() - interval '1 day') RETURNING id",
                (batch_id, str(dash_id), str(p2), i),
            )
            aid = cur.fetchone()[0]
            if i == 1:
                cur.execute(
                    "INSERT INTO brand_mentions (answer_id, client_id, entity_kind, competitor_id, linked, recommended, sentiment) "
                    "VALUES (%s, %s, 'competitor', %s, false, true, 'neutral')",
                    (aid, str(dash_id), str(comp_id)),
                )
        # one failed run to prove failures are surfaced
        cur.execute(
            "INSERT INTO answers (batch_id, client_id, prompt_id, engine, mode, run_index, status, collected_at, error) "
            "VALUES (%s, %s, %s, 'gemini', 'api', 1, 'failed', now() - interval '1 day', 'provider 500')",
            (batch_id, str(dash_id), str(p1)),
        )
        yield str(dash_id), str(p1)
    finally:
        # Deleting the website cascades to prompts/answers/mentions/citations.
        cur.execute("DELETE FROM clients WHERE id = %s", (str(dash_id),))
        cur.execute(
            "DELETE FROM domains WHERE domain IN (%s, 'm1-thirdparty.example')",
            (BRAND_DOMAIN,),
        )
        cur.close()
        conn.close()


class TestDashboard:
    def test_kpis_match_collected_data(self, client: TestClient, dashboard_data: tuple[str, str]) -> None:
        dash_id, _ = dashboard_data
        token = _token(client)
        res = client.get(f"/api/v1/clients/{dash_id}/dashboard", headers=_auth(token))
        assert res.status_code == 200, res.text
        body = res.json()
        kpis = body["kpis"]

        # visibility: 1 of 2 tracked prompt-engine pairs (P1 visible, P2 not)
        vis = kpis["visibility"]
        assert vis["current"] == 1 and vis["base"] == 2
        assert vis["value"] == pytest.approx(0.5)

        # mention rate: 3 brand mentions of 5 succeeded runs (failed run excluded)
        mr = kpis["mention_rate"]
        assert mr["current"] == 3 and mr["base"] == 5

        # linked rate: 2 of 3 linked
        assert kpis["linked_rate"]["current"] == 2 and kpis["linked_rate"]["base"] == 3

        # citation share: 2 brand-owned of 3 citations
        assert kpis["citation_share"]["current"] == 2 and kpis["citation_share"]["base"] == 3

        # share of voice: 3 brand vs 1 competitor mention
        assert kpis["share_of_voice"]["current"] == 3 and kpis["share_of_voice"]["base"] == 4

        assert kpis["runs_7d"] == 5
        assert kpis["failed_7d"] == 1
        assert kpis["collection_health"] == pytest.approx(5 / 6)
        assert kpis["data_source"] == "footnote_collection"
        assert kpis["last_collection_at"] is not None

        # Failed runs and missing setup must be in the action queue.
        kinds = {item["kind"] for item in body["needs_attention"]}
        assert "collection_failures" in kinds
        assert "setup" in kinds
        # Severity-ordered.
        severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        ranks = [severity_rank[i["severity"]] for i in body["needs_attention"]]
        assert ranks == sorted(ranks)
        assert body["correlation_note"].startswith("These metrics show correlation")

    def test_dashboard_cross_tenant_is_forbidden(self, client: TestClient) -> None:
        token = _token(client, "user_b@test.com")
        res = client.get(f"/api/v1/clients/{CLIENT_A_ID}/dashboard", headers=_auth(token))
        assert res.status_code == 403

    def test_fresh_website_dashboard_is_honest_empty(
        self, client: TestClient, fixture_client: str
    ) -> None:
        """A website with no collection shows null rates, not zeros-as-data."""
        token = _token(client)
        res = client.get(f"/api/v1/clients/{fixture_client}/dashboard", headers=_auth(token))
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["kpis"]["visibility"]["value"] is None
        assert body["kpis"]["runs_7d"] == 0
        assert body["kpis"]["collection_health"] is None
        assert body["kpis"]["last_collection_at"] is None
        assert body["recent_wins"] == []
        assert body["status"] == "onboarding"
        assert body["client_name"] == "M1 Fixture Site"
