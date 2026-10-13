"""Comprehensive Test Battery for Milestone 10: Search Analytics, AI Referrals & Google AIO Adapter."""

from __future__ import annotations

import json
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from services.api.app.db import engine
from services.api.app.main import app
from services.api.app.search_analytics import classify_ai_referrer
from services.api.tests.conftest import (
    CLIENT_A_ID,
    ORG_A_ID,
    USER_A_ID,
)
from services.api.app.schemas import EngineType
from services.workers.app.adapters import GoogleAIOAdapter, InMemoryTokenBucket


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


def test_ai_referrer_classification() -> None:
    """Verify precision classification of generative AI referral sources."""
    # ChatGPT variants
    assert classify_ai_referrer("https://chatgpt.com") == "chatgpt"
    assert classify_ai_referrer("chat.openai.com") == "chatgpt"
    assert classify_ai_referrer("android.chatgpt.com") == "chatgpt"

    # Perplexity
    assert classify_ai_referrer("https://www.perplexity.ai/") == "perplexity"
    assert classify_ai_referrer("pplx.ai/search") == "perplexity"

    # Gemini
    assert classify_ai_referrer("gemini.google.com") == "gemini"
    assert classify_ai_referrer("bard.google.com") == "gemini"

    # Claude
    assert classify_ai_referrer("https://claude.ai/chat") == "claude"

    # Grok
    assert classify_ai_referrer("grok.com") == "grok"

    # Copilot
    assert classify_ai_referrer("copilot.microsoft.com") == "copilot"

    # Non-AI traffic
    assert classify_ai_referrer("google.com") is None
    assert classify_ai_referrer("bing.com") is None
    assert classify_ai_referrer("linkedin.com") is None
    assert classify_ai_referrer("direct") is None


def test_search_sync_and_performance_summary(client: TestClient) -> None:
    """Test on-demand search synchronization and summary KPI retrieval."""
    token = _token(client, "user_a@test.com")
    headers = _auth(token)

    # 1. Trigger search data synchronization
    sync_res = client.post(
        f"/api/v1/clients/{CLIENT_A_ID}/analytics/search/sync-now?days=14",
        headers=headers,
    )
    assert sync_res.status_code == 200, sync_res.text
    sync_data = sync_res.json()
    assert sync_data["status"] == "completed"
    assert sync_data["synced_days"] == 14

    # 2. Query Search summary
    summary_res = client.get(
        f"/api/v1/clients/{CLIENT_A_ID}/analytics/search/summary?days=14",
        headers=headers,
    )
    assert summary_res.status_code == 200, summary_res.text
    summary = summary_res.json()
    assert summary["client_id"] == str(CLIENT_A_ID)
    assert summary["total_clicks"] > 0
    assert summary["total_impressions"] > 0
    assert summary["total_aio_impressions"] > 0
    assert summary["total_ai_sessions"] > 0
    assert summary["ai_session_share_pct"] > 0.0
    assert summary["estimated_referral_value_usd"] > 0.0
    assert "undercount" in summary["attribution_disclaimer"].lower()


def test_search_timeseries_and_breakdowns(client: TestClient) -> None:
    """Test search timeseries trends, AI referrals engine split, and query matrices."""
    token = _token(client, "user_a@test.com")
    headers = _auth(token)

    # 1. Timeseries
    ts_res = client.get(
        f"/api/v1/clients/{CLIENT_A_ID}/analytics/search/timeseries?days=14",
        headers=headers,
    )
    assert ts_res.status_code == 200, ts_res.text
    ts = ts_res.json()
    assert len(ts) >= 1
    sample_pt = ts[-1]
    assert "clicks" in sample_pt
    assert "impressions" in sample_pt
    assert "ai_sessions" in sample_pt

    # 2. AI Referrals Breakdown
    ai_res = client.get(
        f"/api/v1/clients/{CLIENT_A_ID}/analytics/search/ai-referrals?days=14",
        headers=headers,
    )
    assert ai_res.status_code == 200, ai_res.text
    breakdown = ai_res.json()
    assert len(breakdown) >= 1
    assert any(b["engine"] == "chatgpt" for b in breakdown)
    assert any(b["engine"] == "perplexity" for b in breakdown)

    # 3. Top Search Queries
    queries_res = client.get(
        f"/api/v1/clients/{CLIENT_A_ID}/analytics/search/queries?days=14&limit=10",
        headers=headers,
    )
    assert queries_res.status_code == 200, queries_res.text
    queries = queries_res.json()
    assert len(queries) >= 1
    top_q = queries[0]
    assert "query" in top_q
    assert top_q["clicks"] > 0
    assert top_q["position"] > 0


def test_google_aio_adapter_contract() -> None:
    """Verify Google AI Overviews adapter request generation and grounding response parsing."""
    adapter = GoogleAIOAdapter(api_key="fake-gemini-key", bucket=InMemoryTokenBucket("google_aio", 30, 1.0))
    assert adapter.engine == EngineType.GOOGLE_AIO

    # Test request builder
    req = adapter._build_request(prompt="best CRM for law firms", geo="US")
    assert req.method == "POST"
    assert "gemini-2.5-flash:generateContent" in str(req.url)
    assert req.headers.get("x-goog-api-key") == "fake-gemini-key"

    # Test parser with Google grounding payload
    fake_response = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "Google AI Overview: The best CRM options include Clio, MyCase, and PracticePanther."}
                    ]
                },
                "groundingMetadata": {
                    "groundingChunks": [
                        {"web": {"uri": "https://www.clio.com", "title": "Clio Legal CRM"}},
                        {"web": {"uri": "https://www.mycase.com", "title": "MyCase Software"}},
                    ]
                },
            }
        ],
        "modelVersion": "gemini-2.5-flash",
    }

    raw_answer = adapter._parse_response(fake_response)
    assert "Google AI Overview" in raw_answer.text
    assert raw_answer.model_label == "google-aio-gemini-v2"
    assert len(raw_answer.citations) == 2
    assert raw_answer.citations[0]["url"] == "https://www.clio.com"
    assert raw_answer.citations[0]["position"] == 1
    assert raw_answer.citations[1]["url"] == "https://www.mycase.com"
    assert raw_answer.citations[1]["position"] == 2


def test_integrations_status_and_demo_connect(client: TestClient) -> None:
    """Test retrieving integrations status and connecting demo integrations."""
    token = _token(client, "user_a@test.com")
    headers = _auth(token)

    # 1. Connect demo integrations
    connect_res = client.post(
        f"/api/v1/clients/{CLIENT_A_ID}/integrations/connect-demo",
        headers=headers,
    )
    assert connect_res.status_code == 200, connect_res.text
    assert connect_res.json()["status"] == "connected"

    # 2. Check integrations status
    status_res = client.get(
        f"/api/v1/clients/{CLIENT_A_ID}/integrations/status",
        headers=headers,
    )
    assert status_res.status_code == 200, status_res.text
    statuses = status_res.json()
    assert len(statuses) >= 2
    providers = [s["provider"] for s in statuses]
    assert "gsc" in providers
    assert "ga4" in providers
    assert all(s["status"] == "active" for s in statuses)
