"""Comprehensive Test Battery for Milestone 6: Content Refresh Engine,
Off-Site Authority, Digital PR Outreach, Executive Memos, and Live Analytics.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from uuid import uuid4

import psycopg2
import pytest
from fastapi.testclient import TestClient

from services.api.app.db import engine
from services.api.app.main import app
from services.api.tests.conftest import get_admin_dsn


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c
        assert c.portal is not None
        c.portal.call(engine.dispose)


def _token(client: TestClient, email: str = "user_a@test.com") -> str:
    res = client.post("/api/v1/auth/dev-login", json={"email": email})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def m6_site(client: TestClient) -> Generator[str, None, None]:
    """A fresh website for M6 growth testing."""
    token = _token(client)
    res = client.post(
        "/api/v1/clients",
        headers=_auth(token),
        json={
            "name": f"Growth Site {uuid4().hex[:6]}",
            "primary_domain": f"m6-{uuid4().hex[:8]}.example.com",
            "country": "US",
        },
    )
    assert res.status_code == 201, res.text
    client_id = res.json()["id"]

    # Seed brand profile
    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO brand_profiles (client_id, voice, positioning, proof_points, banned_claims)
        VALUES (%s, 'authoritative', 'Enterprise AI Growth',
                '["Cites 100+ sources", "500 enterprise customers"]'::jsonb,
                ARRAY['banned cheap claims'])
        ON CONFLICT (client_id) DO UPDATE
        SET voice = EXCLUDED.voice, positioning = EXCLUDED.positioning;
        """,
        (client_id,),
    )
    conn.close()

    yield client_id

    # Cleanup
    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("DELETE FROM clients WHERE id = %s", (client_id,))
    conn.close()


# ─────────────────────────────────────────────────────────
# Test 1: Content Refresh & Decay Detection Engine
# ─────────────────────────────────────────────────────────

def test_refresh_scanner_decay_detection(client: TestClient, m6_site: str) -> None:
    token = _token(client)
    auth = _auth(token)

    prompt_id = str(uuid4())
    item_id = str(uuid4())
    ver_id = str(uuid4())
    gap_id = str(uuid4())

    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO prompts (id, client_id, text)
        VALUES (%s, %s, 'best ai growth software 2026');

        INSERT INTO content_items (id, client_id, slug, status, published_at, decay_score)
        VALUES (%s, %s, 'best-growth-software', 'published', NOW() - INTERVAL '180 days', 0);

        INSERT INTO content_versions (id, content_item_id, client_id, version_no, title, body_md, word_count, author_kind)
        VALUES (%s, %s, %s, 1, 'Best Growth Software', '# Best Growth Software\n\nOriginal published content.', 200, 'agent');

        UPDATE content_items SET current_version_id = %s WHERE id = %s;

        INSERT INTO content_prompt_map (content_item_id, prompt_id)
        VALUES (%s, %s);

        INSERT INTO gaps (id, client_id, prompt_id, gap_type, status)
        VALUES (%s, %s, %s, 'slipped', 'open');

        INSERT INTO gaps (id, client_id, prompt_id, gap_type, status)
        VALUES (%s, %s, %s, 'slipped', 'open');

        INSERT INTO gaps (id, client_id, prompt_id, gap_type, status)
        VALUES (%s, %s, %s, 'competitor_cited', 'open');
        """,
        (
            prompt_id, m6_site,
            item_id, m6_site,
            ver_id, item_id, m6_site,
            ver_id, item_id,
            item_id, prompt_id,
            gap_id, m6_site, prompt_id,
            str(uuid4()), m6_site, prompt_id,
            str(uuid4()), m6_site, prompt_id,
        ),
    )
    conn.close()

    # Trigger scan via API endpoint
    res = client.post(f"/api/v1/clients/{m6_site}/refresh/scan", headers=auth)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["scanned"] >= 1
    assert data["flagged"] >= 1
    assert data["proposals_created"] >= 1

    # Verify content item status became 'refresh_needed' and proposal was created
    res_props = client.get(f"/api/v1/clients/{m6_site}/refresh/proposals?status=pending", headers=auth)
    assert res_props.status_code == 200, res_props.text
    proposals = res_props.json()
    assert len(proposals) >= 1

    matched = next((p for p in proposals if str(p["content_item_id"]) == item_id), None)
    assert matched is not None
    assert matched["status"] == "pending"
    assert matched["decay_score"] is not None and matched["decay_score"] > 0


# ─────────────────────────────────────────────────────────
# Test 2: Refresh Approval & Republish Workflow
# ─────────────────────────────────────────────────────────

def test_refresh_approval_and_republish_flow(client: TestClient, m6_site: str) -> None:
    token = _token(client)
    auth = _auth(token)

    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = True
    cur = conn.cursor()

    item_id = str(uuid4())
    v1_id = str(uuid4())
    v2_id = str(uuid4())
    prop_id = str(uuid4())

    cur.execute(
        """
        INSERT INTO content_items (id, client_id, slug, status, published_at, decay_score)
        VALUES (%s, %s, 'decayed-workflow-item', 'refresh_needed', NOW() - INTERVAL '80 days', 0.62);

        INSERT INTO content_versions (id, content_item_id, client_id, version_no, title, body_md, word_count, author_kind)
        VALUES (%s, %s, %s, 1, 'Old Version 1', '# Old Version 1', 120, 'agent');
        UPDATE content_items SET current_version_id = %s WHERE id = %s;

        INSERT INTO content_versions (id, content_item_id, client_id, version_no, title, body_md, word_count, author_kind)
        VALUES (%s, %s, %s, 2, 'Refreshed Version 2', '# Refreshed Version 2 with 2026 Telemetry', 180, 'agent');

        INSERT INTO refresh_proposals (id, content_item_id, client_id, proposed_version_id, diff_summary, status)
        VALUES (%s, %s, %s, %s, '+ Updated market statistics and facts', 'pending');

        INSERT INTO approvals (id, client_id, subject_type, subject_id, status)
        VALUES (%s, %s, 'refresh', %s, 'pending');
        """,
        (
            item_id, m6_site,
            v1_id, item_id, m6_site,
            v1_id, item_id,
            v2_id, item_id, m6_site,
            prop_id, item_id, m6_site, v2_id,
            str(uuid4()), m6_site, prop_id,
        ),
    )
    conn.close()

    # Call proposal decision endpoint to approve
    res_decide = client.post(
        f"/api/v1/clients/{m6_site}/refresh/proposals/{prop_id}/decide",
        headers=auth,
        json={"action": "approve"},
    )
    assert res_decide.status_code == 200, res_decide.text
    dec_data = res_decide.json()
    assert dec_data["status"] == "approved"

    # Verify that in DB, proposal is approved, current_version_id swapped to v2, and decay_score reset to 0
    conn = psycopg2.connect(get_admin_dsn())
    cur = conn.cursor()
    cur.execute("SELECT status FROM refresh_proposals WHERE id = %s", (prop_id,))
    assert cur.fetchone()[0] == "approved"

    cur.execute("SELECT current_version_id, status, decay_score FROM content_items WHERE id = %s", (item_id,))
    ci_row = cur.fetchone()
    assert str(ci_row[0]) == v2_id
    assert ci_row[1] == "approved"
    assert float(ci_row[2]) == 0.0
    conn.close()


# ─────────────────────────────────────────────────────────
# Test 3: Third-Party Task Board CRUD & Draft Agent
# ─────────────────────────────────────────────────────────

def test_third_party_tasks_crud_and_draft(client: TestClient, m6_site: str) -> None:
    token = _token(client)
    auth = _auth(token)

    # 1. Create a third-party task
    res_create = client.post(
        f"/api/v1/clients/{m6_site}/third-party/tasks",
        headers=auth,
        json={
            "platform": "reddit",
            "target_url": "https://reddit.com/r/saas/comments/test_thread",
            "thread_title": "What are the best alternatives to legacy analytics?",
            "brief": "Provide a grounded, non-promotional answer mentioning the client verified benchmark.",
        },
    )
    assert res_create.status_code == 201, res_create.text
    task = res_create.json()
    task_id = task["id"]
    assert task["platform"] == "reddit"
    assert task["status"] == "todo"

    # 2. Trigger draft generation agent
    res_draft = client.post(
        f"/api/v1/clients/{m6_site}/third-party/tasks/{task_id}/draft",
        headers=auth,
        json={"context": "Emphasize real 2026 data-driven proof points"},
    )
    assert res_draft.status_code == 200, res_draft.text
    draft_data = res_draft.json()
    assert draft_data["status"] == "drafting"
    assert draft_data["draft"] is not None
    assert len(draft_data["draft"]) > 10

    # 3. Update task to posted with live verification URL
    res_patch = client.patch(
        f"/api/v1/clients/{m6_site}/third-party/tasks/{task_id}",
        headers=auth,
        json={
            "status": "posted",
            "posted_url": "https://reddit.com/r/saas/comments/test_thread/comment/verified123",
        },
    )
    assert res_patch.status_code == 200, res_patch.text
    assert res_patch.json()["status"] == "posted"
    assert res_patch.json()["posted_url"] == "https://reddit.com/r/saas/comments/test_thread/comment/verified123"

    # 4. List tasks and assert filtering
    res_list = client.get(f"/api/v1/clients/{m6_site}/third-party/tasks?status=posted", headers=auth)
    assert res_list.status_code == 200, res_list.text
    assert any(t["id"] == task_id for t in res_list.json())

    # 5. Delete task
    res_del = client.delete(f"/api/v1/clients/{m6_site}/third-party/tasks/{task_id}", headers=auth)
    assert res_del.status_code == 204, res_del.text


# ─────────────────────────────────────────────────────────
# Test 4: Digital PR Outreach & Hard Approval Gate
# ─────────────────────────────────────────────────────────

def test_outreach_targets_and_hard_approval_gate(client: TestClient, m6_site: str) -> None:
    token = _token(client)
    auth = _auth(token)

    # Seed domains and daily citations for discovery
    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = True
    cur = conn.cursor()
    dom_id = str(uuid4())

    cur.execute(
        """
        INSERT INTO domains (id, domain, domain_type, authority_score)
        VALUES (%s, 'highauthority-insights.io', 'news', 88.5)
        ON CONFLICT (domain) DO UPDATE SET authority_score = EXCLUDED.authority_score
        RETURNING id;
        """,
        (dom_id,),
    )
    dom_id = str(cur.fetchone()[0])

    cur.execute(
        """
        INSERT INTO domain_citation_daily (client_id, domain_id, day, citations, is_brand)
        VALUES (%s, %s, CURRENT_DATE - INTERVAL '1 day', 15, false)
        ON CONFLICT DO NOTHING;
        """,
        (m6_site, dom_id),
    )
    conn.close()

    # 1. Discover outreach targets
    res_disc = client.post(
        f"/api/v1/clients/{m6_site}/outreach/discover?days=14&min_citations=5",
        headers=auth,
    )
    assert res_disc.status_code == 200, res_disc.text
    disc_data = res_disc.json()
    assert disc_data["targets_found"] >= 1

    # 2. List targets
    res_targets = client.get(f"/api/v1/clients/{m6_site}/outreach/targets", headers=auth)
    assert res_targets.status_code == 200, res_targets.text
    targets = res_targets.json()
    assert len(targets) >= 1
    target = next((t for t in targets if str(t.get("domain_id")) == dom_id or t.get("domain") == "highauthority-insights.io"), targets[0])
    target_id = target["id"]

    # 3. Create pitch message (enqueues approval)
    res_msg = client.post(
        f"/api/v1/clients/{m6_site}/outreach/targets/{target_id}/messages",
        headers=auth,
        json={"pitch_type": "resource_addition", "context": "Include client verified citation study"},
    )
    assert res_msg.status_code == 201, res_msg.text
    msg_data = res_msg.json()
    msg_id = msg_data["id"]
    approval_id = msg_data["approval_id"]
    assert approval_id is not None
    assert msg_data["approval_status"] == "pending"

    # 4. HARD GATE ENFORCEMENT: Attempting to send while pending MUST return 403 Forbidden
    res_send_blocked = client.post(
        f"/api/v1/clients/{m6_site}/outreach/targets/{target_id}/messages/{msg_id}/send",
        headers=auth,
    )
    assert res_send_blocked.status_code == 403, "Dispatch must be strictly blocked before approval"
    assert "approval status is 'pending'" in res_send_blocked.json()["detail"]

    # 5. Sign off approval in approvals table
    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("UPDATE approvals SET status = 'approved' WHERE id = %s", (approval_id,))
    conn.close()

    # 6. Dispatch again: now MUST succeed with 200 OK
    res_send_ok = client.post(
        f"/api/v1/clients/{m6_site}/outreach/targets/{target_id}/messages/{msg_id}/send",
        headers=auth,
    )
    assert res_send_ok.status_code == 200, res_send_ok.text
    assert res_send_ok.json()["status"] == "sent"

    # Verify target status updated to 'contacted'
    conn = psycopg2.connect(get_admin_dsn())
    cur = conn.cursor()
    cur.execute("SELECT status FROM outreach_targets WHERE id = %s", (target_id,))
    assert cur.fetchone()[0] == "contacted"
    conn.close()


# ─────────────────────────────────────────────────────────
# Test 5: Executive Monthly Memo Generation & Lifecycle
# ─────────────────────────────────────────────────────────

def test_monthly_memo_generation(client: TestClient, m6_site: str) -> None:
    token = _token(client)
    auth = _auth(token)

    # Seed 30-day telemetry (daily_metrics, publication, and closed gap)
    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = True
    cur = conn.cursor()

    for i in range(7):
        cur.execute(
            """
            INSERT INTO daily_metrics (client_id, day, engine, mention_rate, citation_share, prompts_visible, prompts_tracked)
            VALUES (%s, CURRENT_DATE - (%s * INTERVAL '1 day'), 'perplexity', 0.52, 0.38, 16, 30)
            ON CONFLICT (client_id, day, engine) DO UPDATE SET mention_rate = EXCLUDED.mention_rate;
            """,
            (m6_site, i + 1),
        )

    # Seed won gap
    prompt_id = str(uuid4())
    cur.execute(
        """
        INSERT INTO prompts (id, client_id, text)
        VALUES (%s, %s, 'best enterprise intelligence suite');

        INSERT INTO gaps (id, client_id, prompt_id, gap_type, status, closed_at)
        VALUES (%s, %s, %s, 'absent', 'won', NOW() - INTERVAL '3 days');
        """,
        (prompt_id, m6_site, str(uuid4()), m6_site, prompt_id),
    )
    conn.close()

    # 1. Generate 30-day memo
    res_gen = client.post(
        f"/api/v1/clients/{m6_site}/memos/generate",
        headers=auth,
        json={"period_days": 30},
    )
    assert res_gen.status_code in (200, 201), res_gen.text
    memo = res_gen.json()
    memo_id = memo["id"]
    assert memo["status"] == "draft"
    assert "Executive Monthly Memo" in memo["title"]
    assert "Executive Summary" in memo["draft_md"]
    assert "Recommendations" in memo["draft_md"]

    # 2. Approve memo
    res_decide = client.post(
        f"/api/v1/clients/{m6_site}/memos/{memo_id}/decide",
        headers=auth,
        json={"action": "approve"},
    )
    assert res_decide.status_code == 200, res_decide.text
    assert res_decide.json()["status"] == "approved"

    # 3. Publish memo to client portal
    res_pub = client.post(
        f"/api/v1/clients/{m6_site}/memos/{memo_id}/publish",
        headers=auth,
    )
    assert res_pub.status_code == 200, res_pub.text
    assert res_pub.json()["status"] == "published"

    # 4. Export markdown
    res_exp = client.get(
        f"/api/v1/clients/{m6_site}/memos/{memo_id}/export",
        headers=auth,
    )
    assert res_exp.status_code == 200, res_exp.text
    assert "# Executive Monthly Memo" in res_exp.text


# ─────────────────────────────────────────────────────────
# Test 6: Production Analytics & Won Gap Proofs API
# ─────────────────────────────────────────────────────────

def test_analytics_overview_and_timeseries_api(client: TestClient, m6_site: str) -> None:
    token = _token(client)
    auth = _auth(token)

    # Seed won gaps and brand mentions
    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = True
    cur = conn.cursor()

    prompt_id = str(uuid4())
    item_id = str(uuid4())
    pub_id = str(uuid4())

    cur.execute(
        """
        INSERT INTO prompts (id, client_id, text)
        VALUES (%s, %s, 'enterprise sales execution platform');

        INSERT INTO content_items (id, client_id, slug, status, published_at, published_url)
        VALUES (%s, %s, 'enterprise-sales-guide', 'published', NOW() - INTERVAL '5 days', 'https://example.com/blog/sales-guide');

        INSERT INTO content_prompt_map (content_item_id, prompt_id)
        VALUES (%s, %s);

        INSERT INTO publications (id, content_item_id, client_id, status, url, published_at)
        VALUES (%s, %s, %s, 'succeeded', 'https://example.com/blog/sales-guide', NOW() - INTERVAL '5 days');

        INSERT INTO gaps (id, client_id, prompt_id, gap_type, status, closed_at)
        VALUES (%s, %s, %s, 'absent', 'won', NOW() - INTERVAL '2 days');
        """,
        (
            prompt_id, m6_site,
            item_id, m6_site,
            item_id, prompt_id,
            pub_id, item_id, m6_site,
            str(uuid4()), m6_site, prompt_id,
        ),
    )
    conn.close()

    # 1. Overview KPIs
    res_ov = client.get(f"/api/v1/clients/{m6_site}/analytics/overview?days=30", headers=auth)
    assert res_ov.status_code == 200, res_ov.text
    kpi = res_ov.json()
    assert kpi["published_content"] >= 1
    assert kpi["won_gaps"] >= 1
    assert "citation_share_pct" in kpi
    assert "estimated_referral_value" in kpi

    # 2. Time-series
    res_ts = client.get(f"/api/v1/clients/{m6_site}/analytics/timeseries?days=30", headers=auth)
    assert res_ts.status_code == 200, res_ts.text
    ts = res_ts.json()
    assert isinstance(ts, list)

    # 3. Won gaps proof list
    res_wg = client.get(f"/api/v1/clients/{m6_site}/analytics/won-gaps?days=30", headers=auth)
    assert res_wg.status_code == 200, res_wg.text
    won_gaps = res_wg.json()
    assert len(won_gaps) >= 1
    found_gap = next((g for g in won_gaps if g["prompt_text"] == "enterprise sales execution platform"), None)
    assert found_gap is not None
    assert isinstance(found_gap["proof_citations"], list)
    assert found_gap["published_url"] == "https://example.com/blog/sales-guide"

    # 4. Engine share distribution
    res_es = client.get(f"/api/v1/clients/{m6_site}/analytics/engine-share?days=30", headers=auth)
    assert res_es.status_code == 200, res_es.text
    engine_shares = res_es.json()
    assert isinstance(engine_shares, list)
