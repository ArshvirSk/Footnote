"""Comprehensive Test Battery for Milestone 8: Production Hardening & System Automation."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg2
import pytest
from fastapi.testclient import TestClient
from services.api.app.db import engine
from services.api.app.main import app
from services.api.tests.conftest import (
    CLIENT_A_ID,
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
def setup_test_prompt() -> None:
    """Ensure a prompt exists for Client A for re-baselining tests."""
    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = True
    cur = conn.cursor()

    # Clean prior test model releases
    cur.execute("DELETE FROM model_release_events WHERE model_label LIKE '%test%'")

    cur.execute(
        """
        INSERT INTO prompts (id, client_id, text, engines, is_active, last_baselined_at)
        VALUES (gen_random_uuid(), %s, 'test prompt for m8 baseline verification', '{chatgpt,gemini,claude}', true, NULL)
        ON CONFLICT DO NOTHING
        """,
        (str(CLIENT_A_ID),),
    )
    cur.close()
    conn.close()


def test_model_release_detection_and_recording(client: TestClient, setup_test_prompt: None) -> None:
    """Test model detection logic detects version strings and stores records in model_release_events."""
    admin_token = _token(client, "user_a@test.com")
    auth_header = _auth(admin_token)

    unique_model = f"gpt-4o-test-{uuid4().hex[:6]}"
    custom_candidates = [
        {
            "engine": "chatgpt",
            "model_label": unique_model,
            "source_url": "https://openai.com/test-release",
        }
    ]

    # 1. Trigger model check
    check_res = client.post(
        "/api/v1/admin/model-releases/check",
        json={"custom_candidates": custom_candidates},
        headers=auth_header,
    )
    assert check_res.status_code == 200, check_res.text
    check_data = check_res.json()
    assert "newly_detected" in check_data
    detected_labels = [m["model_label"] for m in check_data["newly_detected"]]
    assert unique_model in detected_labels

    # 2. List model releases and verify inclusion
    list_res = client.get("/api/v1/admin/model-releases?engine=chatgpt", headers=auth_header)
    assert list_res.status_code == 200, list_res.text
    releases = list_res.json()
    assert any(r["model_label"] == unique_model for r in releases)


def test_prompt_rebaselining_trigger(client: TestClient, setup_test_prompt: None) -> None:
    """Test re-baselining endpoint updates last_baselined_at on target prompts and logs audit events."""
    admin_token = _token(client, "user_a@test.com")
    auth_header = _auth(admin_token)

    # Trigger re-baseline for chatgpt engine on Client A
    rebase_res = client.post(
        "/api/v1/admin/model-releases/rebaseline",
        json={"engine": "chatgpt", "client_id": str(CLIENT_A_ID)},
        headers=auth_header,
    )
    assert rebase_res.status_code == 200, rebase_res.text
    rebase_data = rebase_res.json()
    assert rebase_data["status"] == "success"
    assert rebase_data["updated_prompts"] >= 1

    # Verify audit log recorded
    audit_res = client.get("/api/v1/admin/audit-logs?action=prompts.rebaselined", headers=auth_header)
    assert audit_res.status_code == 200, audit_res.text
    audit_data = audit_res.json()
    assert audit_data["total"] >= 1


def test_model_release_rebaseline_by_event_id(client: TestClient) -> None:
    """Test re-baselining specifically for the engine associated with a detected release event."""
    admin_token = _token(client, "user_a@test.com")
    auth_header = _auth(admin_token)

    # 1. First record an event
    event_model = f"claude-3-7-test-{uuid4().hex[:6]}"
    check_res = client.post(
        "/api/v1/admin/model-releases/check",
        json={
            "custom_candidates": [
                {"engine": "claude", "model_label": event_model, "source_url": "https://anthropic.com/test"}
            ]
        },
        headers=auth_header,
    )
    assert check_res.status_code == 200
    newly = check_res.json()["newly_detected"]
    target_event = next(e for e in newly if e["model_label"] == event_model)
    event_id = target_event["id"]

    # 2. Re-baseline for this release event
    rebase_res = client.post(
        f"/api/v1/admin/model-releases/{event_id}/rebaseline",
        headers=auth_header,
    )
    assert rebase_res.status_code == 200, rebase_res.text
    assert rebase_res.json()["status"] == "success"
    assert rebase_res.json()["engine"] == "claude"


def test_model_drift_summary_endpoint(client: TestClient) -> None:
    """Test GET /api/v1/admin/model-releases/summary returns drift counts and latest release."""
    admin_token = _token(client, "user_a@test.com")
    auth_header = _auth(admin_token)

    res = client.get("/api/v1/admin/model-releases/summary", headers=auth_header)
    assert res.status_code == 200, res.text
    data = res.json()
    assert "total_active_prompts" in data
    assert "never_baselined_prompts" in data
    assert "baselined_prompts" in data
    assert "recent_releases_count" in data
    assert "has_unbaselined_drift" in data
    assert data["total_active_prompts"] >= 1


def test_admin_daemon_status_and_trigger(client: TestClient) -> None:
    """Test background daemon status retrieval and manual cycle dispatch."""
    admin_token = _token(client, "user_a@test.com")
    auth_header = _auth(admin_token)

    # 1. Check daemon telemetry
    status_res = client.get("/api/v1/admin/daemon/status", headers=auth_header)
    assert status_res.status_code == 200, status_res.text
    status_data = status_res.json()
    assert status_data["status"] == "active"
    assert status_data["uptime_seconds"] >= 0
    assert "daily_batch" in status_data["supported_tasks"]
    assert "decay_scan" in status_data["supported_tasks"]

    # 2. Trigger daemon cycle manually
    trigger_res = client.post(
        "/api/v1/admin/daemon/trigger",
        json={"tasks": ["daily_batch", "nightly_rollup", "model_release_check"]},
        headers=auth_header,
    )
    assert trigger_res.status_code == 200, trigger_res.text
    trigger_data = trigger_res.json()
    assert trigger_data["cycle_status"] == "completed"
    assert "daily_batch" in trigger_data["tasks"]
    assert trigger_data["tasks"]["daily_batch"]["status"] == "succeeded"


def test_data_retention_pruning(client: TestClient) -> None:
    """Test data retention table counts and expired records pruning."""
    admin_token = _token(client, "user_a@test.com")
    auth_header = _auth(admin_token)

    # 1. Fetch table counts
    tables_res = client.get("/api/v1/admin/maintenance/tables", headers=auth_header)
    assert tables_res.status_code == 200, tables_res.text
    table_counts = tables_res.json()
    assert "answers" in table_counts
    assert "prompts" in table_counts

    # 2. Seed an old failed answer 60 days ago
    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("SELECT id FROM prompts WHERE client_id = %s LIMIT 1", (str(CLIENT_A_ID),))
    prompt_id = cur.fetchone()[0]

    expired_time = datetime.now(UTC) - timedelta(days=60)
    cur.execute(
        """
        INSERT INTO answers (
            id, client_id, prompt_id, engine, mode, status, error, collected_at
        ) VALUES (
            gen_random_uuid(), %s, %s, 'chatgpt', 'api', 'failed', 'Timeout error', %s
        )
        """,
        (str(CLIENT_A_ID), str(prompt_id), expired_time),
    )
    cur.close()
    conn.close()

    # 3. Call prune endpoint
    prune_res = client.post(
        "/api/v1/admin/maintenance/prune",
        json={"failed_answers_days": 30, "historical_answers_days": 365},
        headers=auth_header,
    )
    assert prune_res.status_code == 200, prune_res.text
    prune_data = prune_res.json()
    assert prune_data["pruned_failed_answers"] >= 1
    assert prune_data["total_pruned"] >= 1
    assert "retention_cutoffs" in prune_data


def test_role_rbac_restrictions_on_maintenance(client: TestClient) -> None:
    """Verify that unauthorized client viewers cannot access admin maintenance endpoints."""
    # Viewer token for Client A
    viewer_token = _token(client, "viewer@test.com")
    viewer_auth = _auth(viewer_token)

    # Maintenance prune forbidden
    prune_res = client.post(
        "/api/v1/admin/maintenance/prune",
        json={"failed_answers_days": 30},
        headers=viewer_auth,
    )
    assert prune_res.status_code == 403

    # Model release check forbidden
    check_res = client.post(
        "/api/v1/admin/model-releases/check",
        json={"custom_candidates": []},
        headers=viewer_auth,
    )
    assert check_res.status_code == 403

    # Daemon trigger forbidden
    trigger_res = client.post(
        "/api/v1/admin/daemon/trigger",
        json={"tasks": ["daily_batch"]},
        headers=viewer_auth,
    )
    assert trigger_res.status_code == 403
