"""Tests for Milestone 4: Content pipeline API and hard approval gate enforcement."""

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
def m4_site(client: TestClient) -> Generator[str, None, None]:
    """A fresh website for M4 content testing."""
    token = _token(client)
    res = client.post(
        "/api/v1/clients",
        headers=_auth(token),
        json={
            "name": f"Content Test {uuid4().hex[:6]}",
            "primary_domain": f"m4-{uuid4().hex[:8]}.example.com",
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
        VALUES (%s, 'authoritative and clear', 'Leading enterprise CRM',
                '["Trusted by 500 enterprises", "99.9%% uptime guarantee"]'::jsonb,
                ARRAY['cheapest CRM in the market'])
        ON CONFLICT (client_id) DO UPDATE
        SET voice = EXCLUDED.voice, positioning = EXCLUDED.positioning
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


def test_content_pipeline_lifecycle(client: TestClient, m4_site: str) -> None:
    token = _token(client)
    headers = _auth(token)
    cid = m4_site

    # 1. Create a brief manually
    res = client.post(
        f"/api/v1/clients/{cid}/content/briefs",
        headers=headers,
        json={
            "title": "Top 10 CRM Platforms for Modern Sales",
            "angle": "Why AI automation in CRM cuts pipeline friction by 40%",
            "outline": [
                {"heading": "Introduction", "points": ["State of modern CRM", "Role of AI"]},
                {"heading": "Key Capabilities", "points": ["Unified context", "Real-time sync"]},
            ],
            "sources": ["Industry benchmark report 2026", "Internal customer studies"],
            "grounding_rules": {"content_type": "article", "min_words": 1000},
        },
    )
    assert res.status_code == 201, res.text
    brief_data = res.json()
    brief_id = brief_data["id"]
    assert brief_id is not None

    # 2. List briefs
    list_res = client.get(f"/api/v1/clients/{cid}/content/briefs", headers=headers)
    assert list_res.status_code == 200
    briefs = list_res.json()
    assert any(b["id"] == brief_id for b in briefs)

    # 3. Get brief details
    get_brief = client.get(f"/api/v1/clients/{cid}/content/briefs/{brief_id}", headers=headers)
    assert get_brief.status_code == 200
    b_detail = get_brief.json()
    assert b_detail["title"] == "Top 10 CRM Platforms for Modern Sales"
    assert len(b_detail["outline"]) == 2

    # 4. Generate 3-pass draft from brief
    draft_res = client.post(
        f"/api/v1/clients/{cid}/content/drafts/generate",
        headers=headers,
        json={"brief_id": brief_id},
    )
    assert draft_res.status_code == 201, draft_res.text
    draft_data = draft_res.json()
    content_item_id = draft_data["content_item_id"]
    version_id = draft_data["version_id"]
    assert draft_data["version_no"] == 1
    assert "body_md" in draft_data
    assert len(draft_data["claims"]) > 0

    # 5. Get content item
    item_res = client.get(f"/api/v1/clients/{cid}/content/items/{content_item_id}", headers=headers)
    assert item_res.status_code == 200
    item = item_res.json()
    assert item["status"] == "in_review"
    assert item["current_version_id"] == version_id
    assert item["current_version"]["version_no"] == 1
    assert item["current_version"]["approval_status"] == "pending"

    # 6. HARD APPROVAL GATE ENFORCEMENT:
    # Trying to approve or publish the content item directly before approval gate is decided MUST FAIL!
    illegal_approve = client.patch(
        f"/api/v1/clients/{cid}/content/items/{content_item_id}",
        headers=headers,
        json={"status": "approved"},
    )
    assert illegal_approve.status_code == 400
    assert "Approval gate violation" in illegal_approve.json()["detail"]

    illegal_publish = client.patch(
        f"/api/v1/clients/{cid}/content/items/{content_item_id}",
        headers=headers,
        json={"status": "published"},
    )
    assert illegal_publish.status_code == 400
    assert "Approval gate violation" in illegal_publish.json()["detail"]

    # 7. List approvals and perform signoff
    approvals_res = client.get(f"/api/v1/clients/{cid}/content/approvals", headers=headers)
    assert approvals_res.status_code == 200
    approvals = approvals_res.json()
    version_approval = next(a for a in approvals if a["subject_id"] == version_id)
    assert version_approval["status"] == "pending"

    # Action approval: approve
    action_res = client.post(
        f"/api/v1/clients/{cid}/content/approvals/{version_approval['id']}/action",
        headers=headers,
        json={"action": "approve", "comment": "Verified all claims and brand voice."},
    )
    assert action_res.status_code == 200
    assert action_res.json()["new_status"] == "approved"

    # Now verify content item status advanced to approved
    item_after_appr = client.get(f"/api/v1/clients/{cid}/content/items/{content_item_id}", headers=headers)
    assert item_after_appr.status_code == 200
    assert item_after_appr.json()["status"] == "approved"

    # Now transitioning to published is legally permitted!
    pub_res = client.patch(
        f"/api/v1/clients/{cid}/content/items/{content_item_id}",
        headers=headers,
        json={"status": "published"},
    )
    assert pub_res.status_code == 200
    assert pub_res.json()["status"] == "published"

    # 8. Human revision: create version 2
    rev_res = client.post(
        f"/api/v1/clients/{cid}/content/items/{content_item_id}/versions",
        headers=headers,
        json={
            "title": "Top 10 CRM Platforms for Modern Sales (2026 Edition)",
            "body_md": "# Top 10 CRM Platforms for Modern Sales (2026 Edition)\n\nUpdated with latest enterprise data.",
            "claims": [{"claim": "Trusted by 500 enterprises", "source": "Internal", "status": "verified"}],
        },
    )
    assert rev_res.status_code == 201
    v2_data = rev_res.json()
    assert v2_data["version_no"] == 2
    assert v2_data["status"] == "in_review"

    # Verify item status was automatically reset to in_review
    item_v2 = client.get(f"/api/v1/clients/{cid}/content/items/{content_item_id}", headers=headers)
    assert item_v2.json()["status"] == "in_review"
    assert len(item_v2.json()["versions"]) == 2

    # 9. Unified Diff between version 1 and version 2
    diff_res = client.get(
        f"/api/v1/clients/{cid}/content/items/{content_item_id}/diff?v1=1&v2=2",
        headers=headers,
    )
    assert diff_res.status_code == 200
    diff_data = diff_res.json()
    assert "diff" in diff_data
    assert diff_data["v1"] == 1
    assert diff_data["v2"] == 2

    # 10. Kanban Pipeline aggregator
    kanban_res = client.get(f"/api/v1/clients/{cid}/content/pipeline", headers=headers)
    assert kanban_res.status_code == 200
    kanban = kanban_res.json()
    assert "columns" in kanban
    column_ids = [c["id"] for c in kanban["columns"]]
    assert "gap_detected" in column_ids
    assert "ops_review_draft" in column_ids
    assert "approved" in column_ids
