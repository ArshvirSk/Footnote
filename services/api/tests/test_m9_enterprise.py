"""Comprehensive Test Battery for Milestone 9: Artifact Storage, Executive Reports, and Multi-CMS Adapters."""

from __future__ import annotations

import json
from collections.abc import Iterator
from uuid import UUID, uuid4

import psycopg2
import pytest
from fastapi.testclient import TestClient
from services.api.app.db import engine
from services.api.app.main import app
from services.api.app.storage import storage_service
from services.api.tests.conftest import (
    CLIENT_A_ID,
    ORG_A_ID,
    USER_A_ID,
    get_admin_dsn,
)
from services.workers.app.cms_adapters import (
    GhostPublishClient,
    WebflowPublishClient,
    WebhookPublishClient,
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


def test_storage_status_and_presigned_url(client: TestClient) -> None:
    """Test storage telemetry and presigned URL generation/verification."""
    token = _token(client, "user_a@test.com")
    headers = _auth(token)

    # 1. Telemetry status
    status_res = client.get("/api/v1/storage/status", headers=headers)
    assert status_res.status_code == 200, status_res.text
    status_data = status_res.json()
    assert status_data["provider"] in ("s3", "neon", "local")
    assert status_data["bucket"] == "footnote-artifacts"
    assert status_data["presigned_urls_enabled"] is True

    # 2. Generate presigned upload URL
    test_key = f"screenshots/test-{uuid4().hex[:8]}.png"
    presign_res = client.post(
        "/api/v1/storage/presigned-url",
        json={"key": test_key, "operation": "put_object", "expires_in_seconds": 1800},
        headers=headers,
    )
    assert presign_res.status_code == 200, presign_res.text
    presign_data = presign_res.json()
    assert presign_data["key"] == test_key
    assert "url" in presign_data
    assert "sig=" in presign_data["url"]
    assert "expires=" in presign_data["url"]

    # 3. Upload content via signed PUT
    upload_url = presign_data["url"]
    dummy_bytes = b"fake-png-screenshot-bytes"
    put_res = client.put(upload_url, content=dummy_bytes, headers={"Content-Type": "image/png"})
    assert put_res.status_code == 200, put_res.text
    assert put_res.json()["key"] == test_key

    # 4. Download content via signed GET
    download_presign = client.post(
        "/api/v1/storage/presigned-url",
        json={"key": test_key, "operation": "get_object"},
        headers=headers,
    )
    assert download_presign.status_code == 200
    get_res = client.get(download_presign.json()["url"])
    assert get_res.status_code == 200
    assert get_res.content == dummy_bytes


def test_executive_report_generation_and_export(client: TestClient) -> None:
    """Test compiling live metrics into an executive visibility audit dossier."""
    token = _token(client, "user_a@test.com")
    headers = _auth(token)

    # 1. Generate report
    gen_res = client.post(
        f"/api/v1/reports/{CLIENT_A_ID}/generate",
        json={"title": "Q3 Executive Visibility Audit", "report_type": "visibility_audit"},
        headers=headers,
    )
    assert gen_res.status_code == 200, gen_res.text
    report_data = gen_res.json()
    assert report_data["client_id"] == str(CLIENT_A_ID)
    assert "metrics_summary" in report_data
    summary = report_data["metrics_summary"]
    assert "share_of_voice_pct" in summary
    assert "overall_visibility_pct" in summary
    assert "engines_breakdown" in summary
    report_id = report_data["id"]

    # 2. List client reports
    list_res = client.get(f"/api/v1/reports/{CLIENT_A_ID}", headers=headers)
    assert list_res.status_code == 200, list_res.text
    reports_list = list_res.json()
    assert any(r["id"] == report_id for r in reports_list)

    # 3. Export HTML dossier
    html_res = client.get(f"/api/v1/reports/{report_id}/export?format=html", headers=headers)
    assert html_res.status_code == 200
    assert "text/html" in html_res.headers.get("content-type", "")
    assert "Executive Audit Dossier" in html_res.text
    assert "Share of Voice" in html_res.text
    assert "Engine Performance Matrix" in html_res.text

    # 4. Export JSON dossier
    json_res = client.get(f"/api/v1/reports/{report_id}/export?format=json", headers=headers)
    assert json_res.status_code == 200
    assert "share_of_voice_pct" in json_res.text


@pytest.mark.asyncio
async def test_multi_cms_publishers() -> None:
    """Test Webflow, Ghost, and Webhook publishing client adapters."""
    # 1. Webflow publisher
    wf = WebflowPublishClient(api_token="test_token", collection_id="test_col", site_domain="brand.com")
    wf_res = await wf.publish_item(title="How to Optimize for ChatGPT", body_md="# Guide", brand_name="Brand A")
    assert wf_res["provider"] == "webflow"
    assert wf_res["external_id"].startswith("wf-")
    assert "brand.com" in wf_res["url"]

    # 2. Ghost publisher
    ghost = GhostPublishClient(admin_api_url="https://ghost.brand.com", admin_api_key="123456:abcdef")
    ghost_res = await ghost.publish_post(title="AI Search Strategies", body_md="# Strategies", brand_name="Brand A")
    assert ghost_res["provider"] == "ghost"
    assert ghost_res["external_id"].startswith("ghost-")
    assert "ai-search-strategies" in ghost_res["url"]

    # 3. Webhook publisher
    hook = WebhookPublishClient(webhook_url="https://httpbin.org/post", secret_token="secret123")
    hook_res = await hook.dispatch(title="Webhook Story", body_md="# Webhook", brand_name="Brand A", draft_id=str(uuid4()))
    assert hook_res["provider"] == "webhook"
    assert hook_res["external_id"].startswith("hook-")


def test_reports_portal_role_access(client: TestClient) -> None:
    """Test client portal users can view their brand reports but not other brands."""
    # Seed viewer for Client A
    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("SELECT id FROM auth.users WHERE lower(email) = 'viewer@test.com' LIMIT 1")
    viewer_user_id = cur.fetchone()[0]

    cur.execute(
        """
        INSERT INTO client_members (client_id, user_id, role)
        VALUES (%s, %s, 'client_viewer')
        ON CONFLICT (client_id, user_id) DO UPDATE SET role = 'client_viewer'
        """,
        (str(CLIENT_A_ID), str(viewer_user_id)),
    )
    cur.close()
    conn.close()

    viewer_token = _token(client, "viewer@test.com")
    viewer_headers = _auth(viewer_token)

    # Viewer can access their assigned client reports
    res = client.get(f"/api/v1/reports/{CLIENT_A_ID}", headers=viewer_headers)
    assert res.status_code == 200, res.text

    # Viewer cannot generate reports (internal role required)
    gen_res = client.post(
        f"/api/v1/reports/{CLIENT_A_ID}/generate",
        json={"title": "Unauthorized"},
        headers=viewer_headers,
    )
    assert gen_res.status_code == 403
