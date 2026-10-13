"""Comprehensive Test Battery for Milestone 7: Role-Gated Client Portal & Enterprise Admin Console."""

from __future__ import annotations

import json
from collections.abc import Generator, Iterator
from uuid import UUID, uuid4

import psycopg2
import pytest
from fastapi.testclient import TestClient
from services.api.app.audit_trail import record_audit_event
from services.api.app.db import engine
from services.api.app.main import app
from services.api.tests.conftest import (
    CLIENT_A_ID,
    CLIENT_VIEWER_ID,
    ORG_A_ID,
    USER_A_ID,
    get_admin_dsn,
)


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


@pytest.fixture(scope="module")
def seed_portal_users() -> None:
    """Ensure approver and viewer accounts exist for Client A."""
    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("SELECT id FROM auth.users WHERE lower(email) = 'approver@test.com' LIMIT 1")
    row = cur.fetchone()
    if row:
        approver_id = row[0]
    else:
        approver_id = str(uuid4())
        cur.execute(
            "INSERT INTO auth.users (id, email) VALUES (%s, 'approver@test.com')",
            (approver_id,),
        )

    cur.execute(
        """
        INSERT INTO client_members (client_id, user_id, role)
        VALUES (%s, %s, 'client_approver')
        ON CONFLICT (client_id, user_id) DO UPDATE SET role = 'client_approver'
        """,
        (str(CLIENT_A_ID), str(approver_id)),
    )

    # Ensure viewer has client_viewer role on Client A
    cur.execute(
        """
        INSERT INTO client_members (client_id, user_id, role)
        VALUES (%s, %s, 'client_viewer')
        ON CONFLICT (client_id, user_id) DO UPDATE SET role = 'client_viewer'
        """,
        (str(CLIENT_A_ID), str(CLIENT_VIEWER_ID)),
    )
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Admin User Management & RBAC Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_admin_user_management_and_rbac(client: TestClient, seed_portal_users: None) -> None:
    admin_token = _token(client, "user_a@test.com")
    viewer_token = _token(client, "viewer@test.com")

    # 1. Non-admin (viewer) gets 403 Forbidden
    res = client.get("/api/v1/admin/users", headers=_auth(viewer_token))
    assert res.status_code == 403, f"Viewer should not access admin endpoints: {res.text}"

    # 2. Admin can list users
    res = client.get("/api/v1/admin/users", headers=_auth(admin_token))
    assert res.status_code == 200, res.text
    users = res.json()
    assert isinstance(users, list)
    assert any(u["email"] == "user_a@test.com" for u in users)

    # 3. Admin can create a new internal user
    new_email = f"staff_{uuid4().hex[:6]}@example.com"
    create_res = client.post(
        "/api/v1/admin/users",
        headers=_auth(admin_token),
        json={"email": new_email, "role": "editor"},
    )
    assert create_res.status_code == 201, create_res.text
    created = create_res.json()
    assert created["email"] == new_email
    assert created["role"] == "editor"
    new_uid = created["user_id"]

    # 4. Admin can update user role
    update_res = client.patch(
        f"/api/v1/admin/users/{new_uid}",
        headers=_auth(admin_token),
        json={"role": "strategist"},
    )
    assert update_res.status_code == 200, update_res.text
    assert update_res.json()["role"] == "strategist"

    # 5. Admin can delete user
    del_res = client.delete(f"/api/v1/admin/users/{new_uid}", headers=_auth(admin_token))
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Audit Trail Log Recording & Query Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_admin_audit_log_recording_and_query(client: TestClient) -> None:
    admin_token = _token(client, "user_a@test.com")

    # Perform an action that logs an event
    test_client_res = client.post(
        "/api/v1/clients",
        headers=_auth(admin_token),
        json={
            "name": f"Audit Site {uuid4().hex[:6]}",
            "primary_domain": f"audit-{uuid4().hex[:6]}.example.com",
            "country": "US",
        },
    )
    assert test_client_res.status_code == 201
    cid = test_client_res.json()["id"]

    # Update billing limits to trigger billing_limits.updated event
    patch_res = client.patch(
        f"/api/v1/admin/clients/{cid}/billing-limits",
        headers=_auth(admin_token),
        json={"max_prompts": 250, "max_monthly_spend_usd": 150.0},
    )
    assert patch_res.status_code == 200

    # Query audit logs
    logs_res = client.get(
        "/api/v1/admin/audit-logs?action=billing_limits.updated",
        headers=_auth(admin_token),
    )
    assert logs_res.status_code == 200, logs_res.text
    data = logs_res.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 1
    found = any(i["action"] == "billing_limits.updated" for i in data["items"])
    assert found, f"Expected billing_limits.updated event in audit logs: {data['items']}"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Spend & Agent Runs Rollup Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_admin_spend_and_agent_runs_aggregation(client: TestClient) -> None:
    admin_token = _token(client, "user_a@test.com")

    # Insert a dummy agent run
    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = True
    cur = conn.cursor()
    run_id = uuid4()
    cur.execute(
        """
        INSERT INTO agent_runs
            (id, client_id, agent, model, tokens_in, tokens_out, cost_usd, status, started_at)
        VALUES
            (%s, %s, 'research', 'gpt-4o', 1200, 350, 0.0450, 'succeeded', now())
        """,
        (str(run_id), str(CLIENT_A_ID)),
    )
    conn.close()

    # Query spend analytics
    spend_res = client.get("/api/v1/admin/spend", headers=_auth(admin_token))
    assert spend_res.status_code == 200, spend_res.text
    spend = spend_res.json()
    assert spend["total_spend_usd"] >= 0.0450
    assert spend["total_tokens_in"] >= 1200
    assert any(ag["agent"] == "research" for ag in spend["by_agent"])
    assert any(m["model"] == "gpt-4o" for m in spend["by_model"])

    # Query agent runs list
    runs_res = client.get("/api/v1/admin/agent-runs?agent=research", headers=_auth(admin_token))
    assert runs_res.status_code == 200, runs_res.text
    runs = runs_res.json()
    assert any(r["id"] == str(run_id) for r in runs)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Client Billing Limits Update Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_admin_billing_limits_update(client: TestClient) -> None:
    admin_token = _token(client, "user_a@test.com")

    res = client.patch(
        f"/api/v1/admin/clients/{CLIENT_A_ID}/billing-limits",
        headers=_auth(admin_token),
        json={
            "max_prompts": 850,
            "max_monthly_spend_usd": 420.50,
            "max_runs_per_day": 45,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["client_id"] == str(CLIENT_A_ID)
    limits = body["billing_limits"]
    assert limits["max_prompts"] == 850
    assert limits["max_monthly_spend_usd"] == 420.50
    assert limits["max_runs_per_day"] == 45


# ─────────────────────────────────────────────────────────────────────────────
# 5. Role-Gated Client Portal Access & Approvals Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_portal_role_access_and_permissions(client: TestClient, seed_portal_users: None) -> None:
    approver_token = _token(client, "approver@test.com")
    viewer_token = _token(client, "viewer@test.com")

    # 1. Approver me context
    res = client.get("/api/v1/portal/me", headers=_auth(approver_token))
    assert res.status_code == 200, res.text
    me_app = res.json()
    assert me_app["role"] == "client_approver"
    assert me_app["active_client_id"] == str(CLIENT_A_ID)
    assert me_app["is_preview"] is False

    # 2. Seed a pending approval for Client A
    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = True
    cur = conn.cursor()
    ap_id = uuid4()
    cur.execute(
        """
        INSERT INTO approvals (id, client_id, subject_type, subject_id, status)
        VALUES (%s, %s, 'memo', %s, 'pending')
        """,
        (str(ap_id), str(CLIENT_A_ID), str(uuid4())),
    )
    conn.close()

    # 3. Viewer attempts to decide approval -> MUST BE FORBIDDEN (403)
    viewer_decide = client.post(
        f"/api/v1/portal/approvals/{ap_id}/decide",
        headers=_auth(viewer_token),
        json={"decision": "approved", "comment": "Trying to approve as viewer"},
    )
    assert viewer_decide.status_code == 403, (
        f"Viewer must not be allowed to decide approvals: {viewer_decide.text}"
    )
    assert "read-only" in viewer_decide.text.lower()

    # 4. Approver decides approval -> MUST SUCCEED (200)
    app_decide = client.post(
        f"/api/v1/portal/approvals/{ap_id}/decide",
        headers=_auth(approver_token),
        json={"decision": "approved", "comment": "Approved by client approver"},
    )
    assert app_decide.status_code == 200, app_decide.text
    assert app_decide.json()["status"] == "approved"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Portal Dashboard, Content Inventory & Settings Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_portal_dashboard_and_content_live_data(client: TestClient, seed_portal_users: None) -> None:
    approver_token = _token(client, "approver@test.com")

    # 1. Dashboard
    dash_res = client.get("/api/v1/portal/dashboard", headers=_auth(approver_token))
    assert dash_res.status_code == 200, dash_res.text
    dash = dash_res.json()
    assert dash["client_id"] == str(CLIENT_A_ID)
    assert "visibility_pct" in dash
    assert "citation_share_pct" in dash
    assert "content_shipped" in dash
    assert "pending_actions" in dash
    assert isinstance(dash["recent_mentions"], list)

    # 2. Content Inventory
    content_res = client.get("/api/v1/portal/content", headers=_auth(approver_token))
    assert content_res.status_code == 200, content_res.text
    assert isinstance(content_res.json(), list)

    # 3. Settings
    settings_res = client.get("/api/v1/portal/settings", headers=_auth(approver_token))
    assert settings_res.status_code == 200, settings_res.text
    settings = settings_res.json()
    assert settings["client_id"] == str(CLIENT_A_ID)
    assert "primary_domain" in settings
    assert "voice" in settings
    assert "proof_points_count" in settings
    assert "publish_targets" in settings
    assert "competitor_domains" in settings
