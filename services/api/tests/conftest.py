"""Pytest configuration and shared fixtures for the API test suite.

RLS tests must run as a **non-owner** role: table owners bypass row-level
security, so a connection as the migration user (e.g. Neon's `neondb_owner`)
would silently see every tenant's rows. The session fixtures therefore:

1. connect as the admin/migration user (from env or .env) to create a dedicated
   `footnote_test` role and seed tenants, then
2. hand every test a connection as that role, which RLS actually governs.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from uuid import UUID

import psycopg2
import pytest

# Fixed test UUIDs
ORG_A_ID = UUID("a0000000-0000-0000-0000-000000000001")
ORG_B_ID = UUID("b0000000-0000-0000-0000-000000000001")
USER_A_ID = UUID("a0000000-0000-0000-0000-00000000000a")
USER_B_ID = UUID("b0000000-0000-0000-0000-00000000000b")
CLIENT_A_ID = UUID("a0000000-0000-0000-0000-0000000000ca")
CLIENT_B_ID = UUID("b0000000-0000-0000-0000-0000000000cb")
CLIENT_VIEWER_ID = UUID("c0000000-0000-0000-0000-00000000000c")

# Non-owner role used by tests; subject to RLS like PostgREST-style access.
TEST_ROLE = "footnote_test"
TEST_ROLE_PASSWORD = "footnote_test"


def get_admin_dsn() -> str:
    """Admin/migration DSN (owner): env var first, then project .env, then localhost."""
    dsn = os.environ.get("DATABASE_URL_SYNC")
    if not dsn:
        env_path = Path(__file__).resolve().parents[3] / ".env"
        values: dict[str, str] = {}
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    values[key.strip()] = val.strip().strip('"').strip("'")
        # Prefer Neon's unpooled (direct) endpoint: session-level state (SET LOCAL)
        # must survive across statements.
        dsn = values.get("DATABASE_URL_UNPOOLED") or values.get("DATABASE_URL") or ""
    if dsn:
        return dsn.replace("postgresql+asyncpg://", "postgresql://")
    return "postgresql://postgres:postgres@localhost:5432/footnote"


def _role_dsn(admin_dsn: str) -> str:
    """Same database as admin_dsn but logged in as TEST_ROLE."""
    parsed = urlparse(admin_dsn)
    host = parsed.hostname or "localhost"
    netloc = f"{TEST_ROLE}:{TEST_ROLE_PASSWORD}@{host}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


@pytest.fixture(scope="session")
def admin_conn() -> Generator[psycopg2.extensions.connection, None, None]:
    """Owner connection: ensures the test role + grants exist (idempotent)."""
    conn = psycopg2.connect(get_admin_dsn())
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (TEST_ROLE,))
    if cur.fetchone() is None:
        cur.execute(
            f'CREATE ROLE {TEST_ROLE} LOGIN PASSWORD %s NOSUPERUSER NOCREATEROLE NOBYPASSRLS',
            (TEST_ROLE_PASSWORD,),
        )
    # Grants so RLS (not bare privileges) is what the tests exercise.
    cur.execute(f"GRANT USAGE ON SCHEMA public TO {TEST_ROLE}")
    cur.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {TEST_ROLE}")
    cur.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {TEST_ROLE}")
    conn.commit()

    yield conn
    conn.close()


@pytest.fixture(scope="session")
def db_conn(admin_conn: psycopg2.extensions.connection) -> Generator[psycopg2.extensions.connection, None, None]:
    """Session-scoped database connection for tests — as the non-owner test role."""
    conn = psycopg2.connect(_role_dsn(get_admin_dsn()))
    conn.autocommit = False
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def _reset_rls(db_conn: psycopg2.extensions.connection) -> Generator[None, None, None]:
    """Reset the RLS session variable before each test."""
    cur = db_conn.cursor()
    cur.execute("RESET request.jwt.claim.sub")
    db_conn.commit()
    yield
    db_conn.rollback()


@pytest.fixture(scope="session", autouse=True)
def seed_test_tenants(admin_conn: psycopg2.extensions.connection) -> None:
    """Create two isolated tenants for cross-tenant RLS testing (as owner)."""
    cur = admin_conn.cursor()

    # Auth users
    for uid, email in [
        (USER_A_ID, "user_a@test.com"),
        (USER_B_ID, "user_b@test.com"),
        (CLIENT_VIEWER_ID, "viewer@test.com"),
    ]:
        cur.execute(
            "INSERT INTO auth.users (id, email) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
            (str(uid), email),
        )

    # Orgs
    for oid, name, slug in [
        (ORG_A_ID, "Org A", "org-a"),
        (ORG_B_ID, "Org B", "org-b"),
    ]:
        cur.execute(
            "INSERT INTO organizations (id, name, slug) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING",
            (str(oid), name, slug),
        )

    # Org members
    cur.execute(
        "INSERT INTO org_members (org_id, user_id, role) VALUES (%s, %s, 'owner') ON CONFLICT DO NOTHING",
        (str(ORG_A_ID), str(USER_A_ID)),
    )
    cur.execute(
        "INSERT INTO org_members (org_id, user_id, role) VALUES (%s, %s, 'owner') ON CONFLICT DO NOTHING",
        (str(ORG_B_ID), str(USER_B_ID)),
    )

    # Clients
    cur.execute(
        "INSERT INTO clients (id, org_id, name, primary_domain) VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
        (str(CLIENT_A_ID), str(ORG_A_ID), "Client A", "client-a.com"),
    )
    cur.execute(
        "INSERT INTO clients (id, org_id, name, primary_domain) VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
        (str(CLIENT_B_ID), str(ORG_B_ID), "Client B", "client-b.com"),
    )

    # Client member (viewer for Client A only)
    cur.execute(
        "INSERT INTO client_members (client_id, user_id, role) VALUES (%s, %s, 'client_viewer') ON CONFLICT DO NOTHING",
        (str(CLIENT_A_ID), str(CLIENT_VIEWER_ID)),
    )

    # Seed data for each client
    for client_id in [CLIENT_A_ID, CLIENT_B_ID]:
        # Brand profile
        cur.execute(
            "INSERT INTO brand_profiles (client_id, voice) VALUES (%s, %s) ON CONFLICT (client_id) DO NOTHING",
            (str(client_id), f"Voice for {client_id}"),
        )
        # A prompt
        cur.execute(
            "INSERT INTO prompts (client_id, text) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (str(client_id), f"Test prompt for {client_id}"),
        )

    admin_conn.commit()
