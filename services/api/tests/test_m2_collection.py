"""Milestone 2 API tests: collection run-now/health/idempotency/cap, prompt runs,
research agent, gap evidence + transitions, tracking endpoints.

Every row these tests create is deleted afterwards (client cascade + own domains).
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from datetime import UTC, datetime
from typing import Any

import psycopg2
import pytest
from fastapi.testclient import TestClient
from services.api.app.config import settings
from services.api.app.db import engine
from services.api.app.main import app
from services.api.tests.conftest import CLIENT_B_ID, get_admin_dsn
from services.workers.app.worker import schedule_collection

TODAY = datetime.now(UTC).date()


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


class RecordingQueue:
    """Stands in for ctx['redis'] in schedule tests: records jobs, never runs them."""

    def __init__(self) -> None:
        self.jobs: list[str] = []

    async def enqueue_job(
        self, name: str, *args: Any, _job_id: str | None = None, _defer_by: float = 0.0, **kwargs: Any
    ) -> None:
        self.jobs.append(_job_id or name)


def _psycopg() -> Any:
    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = True
    return conn


@pytest.fixture()
def m2_client(client: TestClient) -> Generator[str, None, None]:
    """A fresh website (org A) with an industry, so the research agent has seeds."""
    token = _token(client)
    res = client.post(
        "/api/v1/clients",
        headers=_auth(token),
        json={"name": "M2 Test Site", "primary_domain": "m2-test.example"},
    )
    assert res.status_code == 201, res.text
    client_id: str = res.json()["id"]

    conn = _psycopg()
    cur = conn.cursor()
    cur.execute("UPDATE clients SET industry = 'IT consulting' WHERE id = %s", (client_id,))
    cur.close()
    try:
        yield client_id
    finally:
        cur = conn.cursor()
        cur.execute("DELETE FROM clients WHERE id = %s", (client_id,))
        # Only this test's own domains; shared ones (g2.com...) are left alone.
        cur.execute(
            "DELETE FROM domains WHERE domain IN ('m2-brand.example', 'm2-rival.example')"
        )
        cur.close()
        conn.close()


def _add_prompt(
    client: TestClient, token: str, client_id: str, text: str, engines: list[str] | None = None
) -> str:
    payload: dict[str, Any] = {"text": text}
    if engines is not None:
        payload["engines"] = engines
    res = client.post(f"/api/v1/clients/{client_id}/prompts", headers=_auth(token), json=payload)
    assert res.status_code == 201, res.text
    return str(res.json()["id"])


# ──── Scheduling: idempotency, cap, manual runs ────


class TestScheduling:
    def test_cron_scheduling_is_idempotent_per_day(self, client: TestClient, m2_client: str) -> None:
        token = _token(client)
        _add_prompt(client, token, m2_client, "M2 cron prompt one")
        _add_prompt(client, token, m2_client, "M2 cron prompt two")

        queue = RecordingQueue()
        ctx: dict[str, Any] = {"redis": queue}

        first = client.portal.call(schedule_collection, ctx, m2_client)  # type: ignore[union-attr]
        assert first["scheduled"] == 2 * 4 * 3  # prompts x engines(default 4) x k=3
        assert first["enqueued"] == first["scheduled"]
        assert len(queue.jobs) == 24

        # Second cron pass for the same day: no new rows, no new jobs.
        second = client.portal.call(schedule_collection, ctx, m2_client)  # type: ignore[union-attr]
        assert second["scheduled"] == 0
        assert second["already_scheduled"] == 24
        assert second["enqueued"] == 0
        assert len(queue.jobs) == 24

        conn = _psycopg()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*), COUNT(*) FILTER (WHERE status = 'queued') "
            "FROM answers WHERE client_id = %s AND run_day = %s",
            (m2_client, TODAY),
        )
        count, queued = cur.fetchone()
        assert (count, queued) == (24, 24)
        cur.close()
        conn.close()

    def test_run_now_adds_one_fresh_run_without_clobbering(
        self, client: TestClient, m2_client: str
    ) -> None:
        """Run now never overwrites today's raw answers: it schedules run k+1."""
        token = _token(client)
        _add_prompt(client, token, m2_client, "M2 run-now prompt", engines=["chatgpt"])

        ctx: dict[str, Any] = {"redis": RecordingQueue()}
        first = client.portal.call(schedule_collection, ctx, m2_client)  # type: ignore[union-attr]
        assert first["scheduled"] == 3  # k=3 on one engine

        # Mock engines off + no keys: the API path records explicit failures.
        original_mock = settings.allow_mock_engines
        settings.allow_mock_engines = False
        try:
            res = client.post(
                f"/api/v1/clients/{m2_client}/collection/run", headers=_auth(token), json={}
            )
        finally:
            settings.allow_mock_engines = original_mock
        assert res.status_code == 202, res.text
        body = res.json()
        assert body["scheduled"] == 1  # exactly one extra run per prompt/engine
        assert body["answers"][0]["run_index"] == 4

        health = client.get(
            f"/api/v1/clients/{m2_client}/collection/health", headers=_auth(token)
        ).json()
        assert health["scheduled"] == 4
        assert health["failed"] == 1
        assert health["failures"], "failed runs must be listed"
        error = health["failures"][0]["error"]
        assert "OPENAI_API_KEY" in error or "ALLOW_MOCK_ENGINES" in error

    def test_daily_call_cap_is_enforced(self, client: TestClient, m2_client: str) -> None:
        token = _token(client)
        _add_prompt(client, token, m2_client, "M2 capped prompt A")
        _add_prompt(client, token, m2_client, "M2 capped prompt B")

        conn = _psycopg()
        cur = conn.cursor()
        cur.execute(
            "UPDATE clients SET settings = jsonb_set(coalesce(settings, '{}'::jsonb), "
            "'{billing_limits}', '{\"max_daily_calls\": 5}'::jsonb) WHERE id = %s",
            (m2_client,),
        )
        cur.close()
        conn.close()

        queue = RecordingQueue()
        ctx: dict[str, Any] = {"redis": queue}
        result = client.portal.call(schedule_collection, ctx, m2_client)  # type: ignore[union-attr]
        assert result["scheduled"] == 5
        assert result["skipped_cap"] == 24 - 5
        assert len(queue.jobs) == 5


# ──── Collection health ────


class TestCollectionHealth:
    def test_health_rate_and_failure_listing(self, client: TestClient, m2_client: str) -> None:
        token = _token(client)
        pid = _add_prompt(client, token, m2_client, "M2 health prompt", engines=["chatgpt"])

        conn = _psycopg()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO collection_batches (client_id, scheduled_for) VALUES (%s, %s)",
            (m2_client, TODAY),
        )
        cur.execute(
            "SELECT id FROM collection_batches WHERE client_id = %s AND scheduled_for = %s",
            (m2_client, TODAY),
        )
        batch = cur.fetchone()[0]

        # 2 succeeded (one mock), 1 failed, 1 still queued
        for run_index, status, raw_json in (
            (1, "succeeded", '{"model": "gpt-5-search-api"}'),
            (2, "succeeded", '{"mock": true, "model": "chatgpt-mock"}'),
            (3, "failed", None),
            (4, "queued", None),
        ):
            collected_sql = "NULL" if status == "queued" else "now()"
            cur.execute(
                "INSERT INTO answers (batch_id, client_id, prompt_id, engine, mode, run_index, status, "
                "run_day, collected_at, raw_text, raw_json, error, attempts) "
                f"VALUES (%s, %s, %s, 'chatgpt', 'api', %s, %s, %s, {collected_sql}, %s, %s, %s, %s)",
                (
                    batch, m2_client, pid, run_index, status, TODAY,
                    "answer text" if status == "succeeded" else None,
                    raw_json,
                    "HTTP 500: provider exploded" if status == "failed" else None,
                    3 if status == "failed" else 1,
                ),
            )
        cur.close()
        conn.close()

        res = client.get(
            f"/api/v1/clients/{m2_client}/collection/health?days=7", headers=_auth(token)
        )
        assert res.status_code == 200, res.text
        health = res.json()
        assert health["scheduled"] == 4
        assert health["succeeded"] == 2
        assert health["failed"] == 1
        assert health["queued"] == 1
        assert health["rate"] == pytest.approx(0.5)
        assert health["mock_runs"] == 1
        assert len(health["failures"]) == 1
        failure = health["failures"][0]
        assert "500" in failure["error"]
        assert failure["attempts"] == 3
        assert failure["prompt_text"] == "M2 health prompt"
        assert health["per_engine"][0]["engine"] == "chatgpt"
        assert health["per_engine"][0]["succeeded"] == 2
        assert isinstance(health["mock_mode"], bool)


# ──── Prompt runs (FR-11) + sparkline data ────


@pytest.fixture()
def answered_prompt(client: TestClient, m2_client: str) -> Generator[tuple[str, str], None, None]:
    """One prompt with two succeeded runs on different days (citations + mention)."""
    token = _token(client)
    pid = _add_prompt(client, token, m2_client, "M2 answered prompt", engines=["chatgpt"])

    conn = _psycopg()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO collection_batches (client_id, scheduled_for) VALUES (%s, %s) "
        "ON CONFLICT (client_id, scheduled_for) DO UPDATE SET status = 'running'",
        (m2_client, TODAY),
    )
    cur.execute(
        "SELECT id FROM collection_batches WHERE client_id = %s AND scheduled_for = %s",
        (m2_client, TODAY),
    )
    batch = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO domains (domain, domain_type) VALUES ('m2-brand.example', 'owned') "
        "ON CONFLICT (domain) DO NOTHING"
    )
    for days_ago in (0, 1):
        cur.execute(
            "INSERT INTO answers (batch_id, client_id, prompt_id, engine, mode, run_index, status, "
            "run_day, collected_at, raw_text, raw_json, model_label, latency_ms, judge_version, attempts) "
            "VALUES (%s, %s, %s, 'chatgpt', 'api', 1, 'succeeded', %s - %s, "
            "now() - %s * interval '1 day', 'M2 Test Site is excellent and reliable.', "
            "'{\"mock\": false}', 'gpt-5-search-api', 800, 'rules-v2', 1) RETURNING id",
            (batch, m2_client, pid, TODAY, days_ago, days_ago),
        )
        aid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO answer_citations (answer_id, client_id, url, title, domain_id, position, is_brand_owned) "
            "VALUES (%s, %s, 'https://m2-brand.example/page', 'M2 Brand', "
            "(SELECT id FROM domains WHERE domain = 'm2-brand.example'), 1, true)",
            (aid, m2_client),
        )
        cur.execute(
            "INSERT INTO brand_mentions (answer_id, client_id, entity_kind, linked, recommended, sentiment, excerpt) "
            "VALUES (%s, %s, 'brand', true, true, 'positive', 'M2 Test Site is excellent')",
            (aid, m2_client),
        )
    cur.close()
    conn.close()
    yield m2_client, pid
    # client cascade removes answers/mentions/citations/batches


class TestPromptRuns:
    def test_answers_include_raw_citations_and_mentions(
        self, client: TestClient, answered_prompt: tuple[str, str]
    ) -> None:
        cid, pid = answered_prompt
        token = _token(client)
        res = client.get(f"/api/v1/clients/{cid}/prompts/{pid}/answers?days=14", headers=_auth(token))
        assert res.status_code == 200, res.text
        answers = res.json()
        assert len(answers) == 2
        top = answers[0]
        assert top["status"] == "succeeded"
        assert top["raw_text"].startswith("M2 Test Site")
        assert top["mock"] is False
        assert top["judge_version"] == "rules-v2"
        assert top["model_label"] == "gpt-5-search-api"
        assert top["citations"][0]["url"] == "https://m2-brand.example/page"
        assert top["citations"][0]["is_brand_owned"] is True
        assert top["mentions"][0]["entity_kind"] == "brand"
        assert top["mentions"][0]["sentiment"] == "positive"

    def test_series_counts_runs_and_mentions(
        self, client: TestClient, answered_prompt: tuple[str, str]
    ) -> None:
        cid, pid = answered_prompt
        token = _token(client)
        res = client.get(f"/api/v1/clients/{cid}/prompts/{pid}/series?days=14", headers=_auth(token))
        assert res.status_code == 200, res.text
        series = res.json()
        assert len(series) == 2  # today + yesterday
        assert all(point["runs"] == 1 and point["mentioned"] == 1 for point in series)

    def test_prompt_list_carries_series_and_engine_status(
        self, client: TestClient, answered_prompt: tuple[str, str]
    ) -> None:
        cid, _pid = answered_prompt
        token = _token(client)
        res = client.get(f"/api/v1/clients/{cid}/prompts", headers=_auth(token))
        assert res.status_code == 200, res.text
        item = next(p for p in res.json() if p["text"] == "M2 answered prompt")
        assert len(item["series"]) == 2
        assert item["last_run_at"] is not None
        statuses = {s["engine"]: s["status"] for s in item["engine_status"]}
        assert statuses.get("chatgpt") == "succeeded"


# ──── Research agent (FR-5..FR-7) ────


class TestResearchAgent:
    @pytest.fixture(autouse=True)
    def _template_generator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Tests must not depend on a provider key being present.
        monkeypatch.setattr(settings, "openai_api_key", "")

    def test_generate_persists_pending_candidates(self, client: TestClient, m2_client: str) -> None:
        token = _token(client)
        res = client.post(
            f"/api/v1/clients/{m2_client}/research/generate",
            headers=_auth(token),
            json={"limit": 20},
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["generator"] == "template"
        assert body["created"] >= 6, body
        for candidate in body["candidates"]:
            assert candidate["funnel_stage"] in ("awareness", "consideration", "decision")
            assert 0 <= candidate["lead_intent_score"] <= 100
            assert candidate["rationale"]
            assert candidate["status"] == "pending"

        queue = client.get(f"/api/v1/clients/{m2_client}/research/candidates", headers=_auth(token)).json()
        assert len(queue) == body["created"]

        # A second run de-duplicates instead of duplicating.
        again = client.post(
            f"/api/v1/clients/{m2_client}/research/generate",
            headers=_auth(token),
            json={"limit": 20},
        ).json()
        assert again["created"] == 0

        # Cost tracking: every run is logged to agent_runs.
        conn = _psycopg()
        cur = conn.cursor()
        cur.execute(
            "SELECT model, status FROM agent_runs WHERE client_id = %s AND agent = 'research'",
            (m2_client,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        assert rows and all(status == "succeeded" for _model, status in rows)

    def test_accept_edits_and_reject_keep_history(self, client: TestClient, m2_client: str) -> None:
        token = _token(client)
        created = client.post(
            f"/api/v1/clients/{m2_client}/research/generate",
            headers=_auth(token),
            json={"limit": 5},
        ).json()["candidates"]
        assert len(created) >= 2

        # Accept with an operator edit.
        accept = client.post(
            f"/api/v1/clients/{m2_client}/research/candidates/{created[0]['id']}/accept",
            headers=_auth(token),
            json={"text": "M2 edited accepted prompt"},
        )
        assert accept.status_code == 201, accept.text
        prompt_id = accept.json()["prompt_id"]
        assert prompt_id

        prompts = client.get(f"/api/v1/clients/{m2_client}/prompts", headers=_auth(token)).json()
        accepted = next(p for p in prompts if p["id"] == prompt_id)
        assert accepted["text"] == "M2 edited accepted prompt"
        assert accepted["source"] == "research:template"
        assert accepted["is_active"] is True

        # The candidate keeps its original text (history) and points at the prompt.
        history = client.get(
            f"/api/v1/clients/{m2_client}/research/candidates?status=accepted", headers=_auth(token)
        ).json()
        assert history[0]["text"] != "M2 edited accepted prompt"
        assert history[0]["accepted_prompt_id"] == prompt_id

        # Reject another candidate: kept as history, not tracked.
        reject = client.post(
            f"/api/v1/clients/{m2_client}/research/candidates/{created[1]['id']}/reject",
            headers=_auth(token),
        )
        assert reject.status_code == 200, reject.text
        assert reject.json()["candidate"]["status"] == "rejected"

        # Acting twice on a resolved candidate is a conflict.
        again = client.post(
            f"/api/v1/clients/{m2_client}/research/candidates/{created[1]['id']}/reject",
            headers=_auth(token),
        )
        assert again.status_code == 409

    def test_accept_enforces_prompt_cap(self, client: TestClient, m2_client: str) -> None:
        token = _token(client)
        _add_prompt(client, token, m2_client, "M2 existing prompt")
        created = client.post(
            f"/api/v1/clients/{m2_client}/research/generate",
            headers=_auth(token),
            json={"limit": 3},
        ).json()["candidates"]

        conn = _psycopg()
        cur = conn.cursor()
        cur.execute(
            "UPDATE clients SET settings = jsonb_set(coalesce(settings, '{}'::jsonb), "
            "'{billing_limits}', '{\"max_prompts\": 1}'::jsonb) WHERE id = %s",
            (m2_client,),
        )
        cur.close()
        conn.close()

        res = client.post(
            f"/api/v1/clients/{m2_client}/research/candidates/{created[0]['id']}/accept",
            headers=_auth(token),
            json={},
        )
        assert res.status_code == 400
        assert "active prompts limit" in res.json()["detail"]


# ──── Gaps: evidence + status transitions ────


@pytest.fixture()
def gap_data(client: TestClient, m2_client: str) -> Generator[tuple[str, str, str], None, None]:
    """(client_id, gap_id, foreign_gap_id) with an answer citing a competitor."""
    token = _token(client)
    pid = _add_prompt(client, token, m2_client, "M2 gap prompt", engines=["chatgpt"])

    conn = _psycopg()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO domains (domain, domain_type) VALUES ('m2-rival.example', 'competitor') "
        "ON CONFLICT (domain) DO NOTHING"
    )
    cur.execute(
        "INSERT INTO competitors (client_id, name, domain) VALUES (%s, 'M2 Rival', 'm2-rival.example')",
        (m2_client,),
    )
    cur.execute("SELECT id FROM competitors WHERE client_id = %s AND name = 'M2 Rival'", (m2_client,))
    comp_id = cur.fetchone()[0]

    cur.execute(
        "INSERT INTO answers (client_id, prompt_id, engine, mode, run_index, status, run_day, collected_at, raw_text) "
        "VALUES (%s, %s, 'chatgpt', 'api', 1, 'succeeded', %s, now(), 'M2 Rival is the top pick here.') "
        "RETURNING id",
        (m2_client, pid, TODAY),
    )
    aid = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO brand_mentions (answer_id, client_id, entity_kind, competitor_id, excerpt) "
        "VALUES (%s, %s, 'competitor', %s, 'M2 Rival is the top pick')",
        (aid, m2_client, comp_id),
    )
    cur.execute(
        "INSERT INTO answer_citations (answer_id, client_id, url, domain_id, position, is_brand_owned, competitor_id) "
        "VALUES (%s, %s, 'https://m2-rival.example/best', "
        "(SELECT id FROM domains WHERE domain = 'm2-rival.example'), 1, false, %s) RETURNING id",
        (aid, m2_client, comp_id),
    )
    cur.fetchone()

    cur.execute(
        "INSERT INTO gaps (client_id, prompt_id, gap_type, details, status) "
        "VALUES (%s, %s, 'competitor_cited', '{}', 'open') RETURNING id",
        (m2_client, pid),
    )
    gap_id = cur.fetchone()[0]

    # A gap belonging to another tenant (org B) must never be readable here.
    cur.execute(
        "INSERT INTO gaps (client_id, gap_type, status) VALUES (%s, 'competitor_cited', 'open') RETURNING id",
        (str(CLIENT_B_ID),),
    )
    foreign_gap = cur.fetchone()[0]
    cur.close()
    conn.close()

    yield m2_client, str(gap_id), str(foreign_gap)

    conn = _psycopg()
    cur = conn.cursor()
    cur.execute("DELETE FROM gaps WHERE client_id = %s", (str(CLIENT_B_ID),))
    cur.close()
    conn.close()


class TestGaps:
    def test_gap_detail_returns_evidence_answers(
        self, client: TestClient, gap_data: tuple[str, str, str]
    ) -> None:
        cid, gap_id, _foreign = gap_data
        token = _token(client)
        res = client.get(f"/api/v1/clients/{cid}/gaps/{gap_id}", headers=_auth(token))
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["gap_type"] == "competitor_cited"
        assert body["why"]
        assert len(body["evidence"]) == 1
        ev = body["evidence"][0]
        assert ev["brand_mentioned"] is False
        assert ev["competitor_mentioned"] is True
        assert ev["excerpt"].startswith("M2 Rival")
        assert ev["citations"][0]["url"] == "https://m2-rival.example/best"

    def test_gap_status_transitions(self, client: TestClient, gap_data: tuple[str, str, str]) -> None:
        cid, gap_id, _foreign = gap_data
        token = _token(client)

        res = client.patch(
            f"/api/v1/clients/{cid}/gaps/{gap_id}", headers=_auth(token), json={"status": "in_progress"}
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "in_progress"
        assert res.json()["detected_at"]

        won = client.patch(f"/api/v1/clients/{cid}/gaps/{gap_id}", headers=_auth(token), json={"status": "won"})
        assert won.status_code == 200
        assert won.json()["status"] == "won"

        detail = client.get(f"/api/v1/clients/{cid}/gaps/{gap_id}", headers=_auth(token)).json()
        assert detail["status"] == "won"

        bad = client.patch(
            f"/api/v1/clients/{cid}/gaps/{gap_id}", headers=_auth(token), json={"status": "nope"}
        )
        assert bad.status_code == 422

    def test_gap_scoping_refuses_other_clients(
        self, client: TestClient, gap_data: tuple[str, str, str]
    ) -> None:
        cid, _gap_id, foreign_gap = gap_data
        token = _token(client)
        # Another tenant's gap id under our client: 404 (never leaks).
        res = client.get(f"/api/v1/clients/{cid}/gaps/{foreign_gap}", headers=_auth(token))
        assert res.status_code == 404
        # And the other tenant's client id is refused outright.
        res2 = client.get(f"/api/v1/clients/{CLIENT_B_ID}/gaps", headers=_auth(token))
        assert res2.status_code == 403


# ──── Tracking endpoints (FR-12) ────


class TestTracking:
    def test_citation_domains_ranking_and_share(
        self, client: TestClient, answered_prompt: tuple[str, str]
    ) -> None:
        cid, _pid = answered_prompt
        token = _token(client)
        conn = _psycopg()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO domains (domain, domain_type) VALUES ('reddit.com', 'forum') "
            "ON CONFLICT (domain) DO NOTHING"
        )
        for domain, url, position in (
            ("reddit.com", "https://reddit.com/r/foo", 2),
            ("g2.com", "https://g2.com/m2", 3),
        ):
            cur.execute(
                "INSERT INTO answer_citations (answer_id, client_id, url, domain_id, position, is_brand_owned) "
                "SELECT a.id, %s, %s, (SELECT id FROM domains WHERE domain = %s), %s, false "
                "FROM answers a WHERE a.client_id = %s AND a.run_day = %s LIMIT 1",
                (cid, url, domain, position, cid, TODAY),
            )
        cur.close()
        conn.close()

        res = client.get(f"/api/v1/clients/{cid}/citations/domains?days=7", headers=_auth(token))
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["total_citations"] == 4  # 2 brand + reddit + g2
        assert body["brand_citations"] == 2
        assert body["brand_share"] == pytest.approx(0.5)
        by_domain = {d["domain"]: d for d in body["domains"]}
        assert by_domain["m2-brand.example"]["is_brand"] is True
        assert by_domain["m2-brand.example"]["domain_type"] == "owned"
        assert by_domain["reddit.com"]["domain_type"] == "forum"
        assert by_domain["g2.com"]["domain_type"] == "review_site"

    def test_competitor_matrix_visibility(
        self, client: TestClient, answered_prompt: tuple[str, str]
    ) -> None:
        cid, _pid = answered_prompt
        token = _token(client)
        res = client.get(f"/api/v1/clients/{cid}/competitors/matrix?days=7", headers=_auth(token))
        assert res.status_code == 200, res.text
        body = res.json()
        row = next(r for r in body["rows"] if r["prompt_text"] == "M2 answered prompt")
        assert row["runs"] == 2
        assert row["brand_runs"] == 2
        assert row["brand_visible"] is True
        assert row["competitors"] == []

    def test_competitor_matrix_shows_competitor_presence(
        self, client: TestClient, gap_data: tuple[str, str, str]
    ) -> None:
        cid, _gap_id, _foreign = gap_data
        token = _token(client)
        res = client.get(f"/api/v1/clients/{cid}/competitors/matrix?days=7", headers=_auth(token))
        assert res.status_code == 200, res.text
        row = next(r for r in res.json()["rows"] if r["prompt_text"] == "M2 gap prompt")
        assert row["runs"] == 1
        assert row["brand_runs"] == 0
        assert row["brand_visible"] is False
        assert row["competitors"][0]["name"] == "M2 Rival"
        assert row["competitors"][0]["runs_with_mention"] == 1
