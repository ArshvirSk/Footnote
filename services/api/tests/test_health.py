"""Tests for the API health endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient
from services.api.app.main import app

client = TestClient(app)


class TestHealth:
    """Health endpoint tests."""

    def test_health_returns_ok(self) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "environment" in data
        assert "version" in data

    def test_health_returns_version(self) -> None:
        response = client.get("/health")
        data = response.json()
        assert data["version"] == "0.1.0"
