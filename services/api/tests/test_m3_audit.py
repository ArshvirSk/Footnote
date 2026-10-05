"""Milestone 3 API tests: audit re-runs (fix verification), finding triage,
dev brief export and the competitor intelligence matrix.

The crawler itself is unit-tested in ``test_site_audit.py`` with an httpx mock
transport; here ``run_site_audit`` is monkeypatched so the route-level diff and
persistence behaviour is deterministic. Every row these tests create is deleted
afterwards (client cascade + own domains).
"""

from __future__ import annotations

import json
from collections.abc import Generator, Iterator
from datetime import UTC, datetime
from typing import Any

import psycopg2
import pytest
from fastapi.testclient import TestClient
from services.api.app.audit import AuditResult, Finding
from services.api.app.db import engine
from services.api.app.main import app
from services.api.tests.conftest import CLIENT_B_ID, get_admin_dsn

TODAY = datetime.now(UTC).date()
BASE = "https://m3-audit.example"


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


def _psycopg() -> Any:
    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = True
    return conn


@pytest.fixture()
def m3_site(client: TestClient) -> Generator[str, None, None]:
    """A fresh website (org A) for audit and competitor-intel tests."""
    token = _token(client)
    res = client.post(
        "/api/v1/clients",
        headers=_auth(token),
        json={"name": "M3 Test Site", "primary_domain": "m3-test.example"},
    )
    assert res.status_code == 201, res.text
    client_id: str = res.json()["id"]
    yield client_id
    conn = _psycopg()
    cur = conn.cursor()
    cur.execute("DELETE FROM clients WHERE id = %s", (client_id,))
    cur.execute("DELETE FROM domains WHERE domain = 'm3-rival.example'")
    cur.close()
    conn.close()


def _add_prompt(client: TestClient, token: str, client_id: str, text: str) -> str:
    res = client.post(
        f"/api/v1/clients/{client_id}/prompts",
        headers=_auth(token),
        json={"text": text, "engines": ["chatgpt"]},
    )
    assert res.status_code == 201, res.text
    return str(res.json()["id"])


def _seed_audit(
    client_id: str,
    findings: list[tuple[str, str, str]],
    summary_extra: dict[str, Any] | None = None,
) -> str:
    """Insert an audit + findings; returns the audit id.

    ``findings`` entries are ``(rule, status, fix_owner)``.
    """
    summary: dict[str, Any] = {
        "base_url": BASE,
        "host": "m3-audit.example",
        "pages_crawled": 1,
        "page_urls": [BASE],
        "sitemap_urls": 0,
        "robots_rules": [],
        "speed": {"status": "not_configured"},
        "homepage_ms": 120,
    }
    summary.update(summary_extra or {})
    conn = _psycopg()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO audits (id, client_id, started_at, finished_at, score, summary) "
        "VALUES (gen_random_uuid(), %s, now(), now(), 60, %s) RETURNING id",
        (client_id, json.dumps(summary)),
    )
    audit_id = str(cur.fetchone()[0])
    for rule, status, owner in findings:
        cur.execute(
            "INSERT INTO audit_findings (id, audit_id, client_id, category, severity, url, rule, detail, "
            "fix_owner, status, suggested_fix) "
            "VALUES (gen_random_uuid(), %s, %s, 'meta', 'medium', %s, %s, %s, %s, %s, 'Apply the fix')",
            (audit_id, client_id, BASE, rule, f"{rule} detail", owner, status),
        )
    cur.close()
    conn.close()
    return audit_id


class _FakeAudit:
    """Stand-in for ``run_site_audit`` returning a fixed finding set."""

    def __init__(self, findings: list[Finding]) -> None:
        self.findings = findings
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, *args: Any, **kwargs: Any) -> AuditResult:
        self.calls.append({"args": args, "kwargs": kwargs})
        return AuditResult(
            score=72.0,
            findings=self.findings,
            pages=[],
            summary={
                "base_url": BASE,
                "host": "m3-audit.example",
                "pages_crawled": 1,
                "page_urls": [],
                "sitemap_urls": 0,
                "robots_rules": [],
                "speed": {"status": "not_configured"},
                "homepage_ms": 100,
            },
        )


def _finding(rule: str, severity: str = "medium", detail: str | None = None) -> Finding:
    return Finding("meta", severity, rule, detail or f"{rule} still present", BASE)


@pytest.fixture()
def fake_audit(monkeypatch: pytest.MonkeyPatch) -> Generator[_FakeAudit, None, None]:
    fake = _FakeAudit([])
    monkeypatch.setattr("services.api.app.routes.audits.run_site_audit", fake)
    yield fake


class TestAuditRerun:
    def test_rerun_marks_fixed_and_reports_diff(
        self, client: TestClient, m3_site: str, fake_audit: _FakeAudit
    ) -> None:
        token = _token(client)
        audit_id = _seed_audit(
            m3_site,
            [
                ("missing_title", "open", "team"),          # gone next run -> fixed
                ("missing_description", "in_progress", "team"),  # still present -> carried
                ("missing_llms_txt", "ignored", "client_dev"),   # still present -> stay ignored
                ("thin_content", "fixed", "team"),          # present again -> regression
            ],
        )
        fake_audit.findings = [
            _finding("missing_description"),
            _finding("missing_llms_txt", "medium"),
            _finding("thin_content"),
            _finding("slow_lcp", "high"),
        ]

        res = client.post(f"/api/v1/clients/{m3_site}/audits/{audit_id}/rerun", headers=_auth(token))
        assert res.status_code == 200, res.text
        body = res.json()

        assert [f["rule"] for f in body["fixed"]] == ["missing_title"]
        assert [f["rule"] for f in body["still_present"]] == ["missing_description"]
        assert [f["rule"] for f in body["regressed"]] == ["thin_content"]
        assert [f["rule"] for f in body["new"]] == ["slow_lcp"]
        assert body["rerun_of"] == audit_id
        new_audit_id = body["audit"]["id"]
        assert new_audit_id != audit_id

        # Persisted state: vanished finding is verified against the new audit.
        conn = _psycopg()
        cur = conn.cursor()
        cur.execute(
            "SELECT status, verified_at, resolved_in_audit_id FROM audit_findings "
            "WHERE audit_id = %s AND rule = 'missing_title'",
            (audit_id,),
        )
        status, verified_at, resolved = cur.fetchone()
        assert status == "fixed"
        assert verified_at is not None
        assert str(resolved) == new_audit_id

        cur.execute("SELECT rerun_of FROM audits WHERE id = %s", (new_audit_id,))
        assert str(cur.fetchone()[0]) == audit_id

        # Triage state carries onto the new snapshot.
        cur.execute(
            "SELECT rule, status FROM audit_findings WHERE audit_id = %s ORDER BY rule",
            (new_audit_id,),
        )
        statuses = dict(cur.fetchall())
        assert statuses["missing_description"] == "in_progress"
        assert statuses["missing_llms_txt"] == "ignored"
        assert statuses["thin_content"] == "open"
        assert statuses["slow_lcp"] == "open"
        cur.close()
        conn.close()

    def test_rerun_unknown_audit_is_404(
        self, client: TestClient, m3_site: str, fake_audit: _FakeAudit
    ) -> None:
        token = _token(client)
        res = client.post(
            f"/api/v1/clients/{m3_site}/audits/00000000-0000-0000-0000-0000000000ff/rerun",
            headers=_auth(token),
        )
        assert res.status_code == 404


class TestFindingTriage:
    def test_status_transitions_validate(self, client: TestClient, m3_site: str) -> None:
        token = _token(client)
        audit_id = _seed_audit(m3_site, [("missing_title", "open", "team")])
        conn = _psycopg()
        cur = conn.cursor()
        cur.execute("SELECT id FROM audit_findings WHERE audit_id = %s", (audit_id,))
        finding_id = str(cur.fetchone()[0])
        cur.close()
        conn.close()

        url = f"/api/v1/clients/{m3_site}/audits/{audit_id}/findings/{finding_id}"
        res = client.patch(url, headers=_auth(token), json={"status": "in_progress"})
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "in_progress"

        ignored = client.patch(url, headers=_auth(token), json={"status": "ignored"})
        assert ignored.status_code == 200
        assert ignored.json()["status"] == "ignored"

        bad = client.patch(url, headers=_auth(token), json={"status": "nope"})
        assert bad.status_code == 422

        other = client.patch(
            f"/api/v1/clients/{m3_site}/audits/{audit_id}/findings/00000000-0000-0000-0000-0000000000ff",
            headers=_auth(token),
            json={"status": "open"},
        )
        assert other.status_code == 404

    def test_other_tenant_is_forbidden(self, client: TestClient, m3_site: str) -> None:
        token = _token(client)
        audit_id = _seed_audit(m3_site, [("missing_title", "open", "team")])
        res = client.post(
            f"/api/v1/clients/{CLIENT_B_ID}/audits/{audit_id}/rerun", headers=_auth(token)
        )
        assert res.status_code == 403


class TestDevBrief:
    def test_brief_is_pr_ready_markdown(self, client: TestClient, m3_site: str) -> None:
        token = _token(client)
        audit_id = _seed_audit(
            m3_site,
            [
                ("missing_json_ld", "open", "team"),
                ("slow_lcp", "open", "client_dev"),
                ("missing_title", "fixed", "team"),
            ],
            summary_extra={
                "robots_rules": [
                    {"bot": "GPTBot", "group": "GPTBot", "allowed": False, "rule": "Disallow: /"},
                ],
                "speed": {"status": "ok", "performance_score": 35, "lcp_ms": 5200, "cls": 0.31, "tbt_ms": 800},
            },
        )
        res = client.get(f"/api/v1/clients/{m3_site}/audits/{audit_id}/brief", headers=_auth(token))
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["filename"].startswith("dev-brief-m3-test-site-")
        assert body["filename"].endswith(".md")
        markdown = body["markdown"]
        assert "# Site audit dev brief — M3 Test Site" in markdown
        assert "How to verify these fixes" in markdown
        assert "| GPTBot | GPTBot | ⛔ blocked | Disallow: / |" in markdown
        assert "Performance **35/100**" in markdown
        assert "`missing_json_ld`" in markdown
        assert "## Fix checklist — client dev" in markdown
        assert "`slow_lcp`" in markdown
        assert "Verified fixed in this snapshot" in markdown

    def test_brief_scoping_refuses_other_client(self, client: TestClient, m3_site: str) -> None:
        token = _token(client)
        audit_id = _seed_audit(m3_site, [("missing_title", "open", "team")])
        res = client.get(
            f"/api/v1/clients/{CLIENT_B_ID}/audits/{audit_id}/brief", headers=_auth(token)
        )
        assert res.status_code == 403


class TestCompetitorIntelligence:
    def test_page_map_sov_and_gap_prompts(self, client: TestClient, m3_site: str) -> None:
        token = _token(client)
        absent_prompt = _add_prompt(client, token, m3_site, "M3 intel prompt absent")
        present_prompt = _add_prompt(client, token, m3_site, "M3 intel prompt present")

        conn = _psycopg()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO domains (domain, domain_type) VALUES ('m3-rival.example', 'competitor') "
            "ON CONFLICT (domain) DO NOTHING"
        )
        cur.execute(
            "INSERT INTO competitors (client_id, name, domain) VALUES (%s, 'M3 Rival', 'm3-rival.example') "
            "RETURNING id",
            (m3_site,),
        )
        comp_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM domains WHERE domain = 'm3-rival.example'")
        domain_id = cur.fetchone()[0]

        # Prompt 1: competitor mentioned + cited, brand absent -> gap prompt.
        cur.execute(
            "INSERT INTO answers (client_id, prompt_id, engine, mode, run_index, status, run_day, collected_at, raw_text) "
            "VALUES (%s, %s, 'chatgpt', 'api', 1, 'succeeded', %s, now(), 'M3 Rival is the top pick.') RETURNING id",
            (m3_site, absent_prompt, TODAY),
        )
        answer_absent = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO brand_mentions (answer_id, client_id, entity_kind, competitor_id, excerpt) "
            "VALUES (%s, %s, 'competitor', %s, 'M3 Rival is the top pick')",
            (answer_absent, m3_site, comp_id),
        )
        cur.execute(
            "INSERT INTO answer_citations (answer_id, client_id, url, title, domain_id, position, is_brand_owned, competitor_id) "
            "VALUES (%s, %s, 'https://m3-rival.example/best', 'Best picks', %s, 1, false, %s)",
            (answer_absent, m3_site, domain_id, comp_id),
        )

        # Prompt 2: both brands appear -> competitor present but not a gap prompt.
        cur.execute(
            "INSERT INTO answers (client_id, prompt_id, engine, mode, run_index, status, run_day, collected_at, raw_text) "
            "VALUES (%s, %s, 'chatgpt', 'api', 1, 'succeeded', %s, now(), 'M3 Test Site and M3 Rival both appear.') "
            "RETURNING id",
            (m3_site, present_prompt, TODAY),
        )
        answer_present = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO brand_mentions (answer_id, client_id, entity_kind, linked, excerpt) "
            "VALUES (%s, %s, 'brand', false, 'M3 Test Site')",
            (answer_present, m3_site),
        )
        cur.execute(
            "INSERT INTO brand_mentions (answer_id, client_id, entity_kind, competitor_id, excerpt) "
            "VALUES (%s, %s, 'competitor', %s, 'M3 Rival')",
            (answer_present, m3_site, comp_id),
        )
        cur.close()
        conn.close()

        res = client.get(
            f"/api/v1/clients/{m3_site}/competitors/intelligence?days=7", headers=_auth(token)
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["total_brand_mentions"] == 1
        assert body["total_competitor_mentions"] == 2

        comp = next(c for c in body["competitors"] if c["name"] == "M3 Rival")
        assert comp["mentions"] == 2
        assert comp["prompts_present"] == 2
        assert comp["citations"] == 1
        assert comp["share_of_voice"] == pytest.approx(2 / 3)
        assert comp["top_pages"][0]["url"] == "https://m3-rival.example/best"
        assert comp["top_pages"][0]["citations"] == 1
        assert [p["prompt_text"] for p in comp["gap_prompts"]] == ["M3 intel prompt absent"]

    def test_other_tenant_is_forbidden(self, client: TestClient) -> None:
        token = _token(client)
        res = client.get(
            f"/api/v1/clients/{CLIENT_B_ID}/competitors/intelligence", headers=_auth(token)
        )
        assert res.status_code == 403
