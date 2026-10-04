"""Tests for the development login endpoint and its production gate.

The endpoint mints HS256 JWTs signed with SUPABASE_JWT_SECRET, so these tests
also prove the issued token is accepted by the real ``/auth/me`` dependency
(decode + org/role lookup against the seeded tenants).

Each test opens the TestClient as a context manager: that keeps every request
of the test on one event loop, so pooled asyncpg connections are never reused
across loops (which corrupts the transaction state under asyncpg).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from services.api.app.config import settings
from services.api.app.db import engine
from services.api.app.main import app
from services.api.tests.conftest import ORG_A_ID, USER_A_ID


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    """One TestClient for the whole module: a single event loop, so all
    requests share pooled connections instead of pooling per-request loops."""
    with TestClient(app) as c:
        yield c
        # Dispose the asyncpg pool on the portal's loop before it closes;
        # otherwise later tests (e.g. test_rollup's asyncio.run) would reuse
        # connections bound to this dead loop.
        assert c.portal is not None
        c.portal.call(engine.dispose)


class TestDevLogin:
    """POST /api/v1/auth/dev-login behavior."""

    def test_issues_token_accepted_by_me(self, client: TestClient) -> None:
        """A seeded email yields a JWT that /auth/me resolves to that user."""
        res = client.post("/api/v1/auth/dev-login", json={"email": "user_a@test.com"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]
        assert body["user_id"] == str(USER_A_ID)

        me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
        assert me.status_code == 200, me.text
        data = me.json()
        assert data["user_id"] == str(USER_A_ID)
        assert data["email"] == "user_a@test.com"
        assert data["org_id"] == str(ORG_A_ID)
        assert data["role"] == "owner"

    def test_unknown_email_returns_404(self, client: TestClient) -> None:
        res = client.post("/api/v1/auth/dev-login", json={"email": "nobody@example.com"})
        assert res.status_code == 404

    def test_disabled_in_production(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """The endpoint must 404 (not mint tokens) when ENVIRONMENT=production."""
        monkeypatch.setattr(settings, "environment", "production")
        res = client.post("/api/v1/auth/dev-login", json={"email": "user_a@test.com"})
        assert res.status_code == 404

    def test_me_rejects_missing_token(self, client: TestClient) -> None:
        assert client.get("/api/v1/auth/me").status_code == 401

    def test_me_rejects_garbage_token(self, client: TestClient) -> None:
        res = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"})
        assert res.status_code == 401
