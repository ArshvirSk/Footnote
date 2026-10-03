"""Pytest configuration and shared fixtures for the API test suite."""

from __future__ import annotations

import os
from typing import Generator
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


def get_test_dsn() -> str:
    """Get the test database connection string."""
    return os.environ.get(
        "DATABASE_URL_SYNC",
        "postgresql://postgres:postgres@localhost:5432/footnote",
    )


@pytest.fixture(scope="session")
def db_conn() -> Generator[psycopg2.extensions.connection, None, None]:
    """Session-scoped database connection for tests."""
    conn = psycopg2.connect(get_test_dsn())
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
def seed_test_tenants(db_conn: psycopg2.extensions.connection) -> None:
    """Create two isolated tenants for cross-tenant RLS testing."""
    cur = db_conn.cursor()

    # Use service role (bypass RLS) for setup
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

    db_conn.commit()
