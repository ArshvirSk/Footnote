"""RLS test suite — verifies that row-level security prevents cross-tenant access.

These tests use real Postgres connections and set the JWT claim to simulate
different users, then verify that RLS policies correctly isolate data.
"""

from __future__ import annotations

import psycopg2
import pytest

from services.api.tests.conftest import (
    CLIENT_A_ID,
    CLIENT_B_ID,
    CLIENT_VIEWER_ID,
    USER_A_ID,
    USER_B_ID,
)


def _set_user(cur: psycopg2.extensions.cursor, user_id: str) -> None:
    """Set the RLS session variable to simulate a specific user."""
    cur.execute("SET LOCAL request.jwt.claim.sub = %s", (user_id,))


class TestRLSClients:
    """Test RLS on the clients table."""

    def test_user_a_sees_only_client_a(
        self, db_conn: psycopg2.extensions.connection
    ) -> None:
        """User A (org A owner) should see Client A but not Client B."""
        cur = db_conn.cursor()
        cur.execute("BEGIN")
        _set_user(cur, str(USER_A_ID))
        cur.execute("SELECT id FROM clients")
        rows = cur.fetchall()
        client_ids = {str(r[0]) for r in rows}
        assert str(CLIENT_A_ID) in client_ids, "User A should see Client A"
        assert str(CLIENT_B_ID) not in client_ids, "User A should NOT see Client B"
        cur.execute("ROLLBACK")

    def test_user_b_sees_only_client_b(
        self, db_conn: psycopg2.extensions.connection
    ) -> None:
        """User B (org B owner) should see Client B but not Client A."""
        cur = db_conn.cursor()
        cur.execute("BEGIN")
        _set_user(cur, str(USER_B_ID))
        cur.execute("SELECT id FROM clients")
        rows = cur.fetchall()
        client_ids = {str(r[0]) for r in rows}
        assert str(CLIENT_B_ID) in client_ids, "User B should see Client B"
        assert str(CLIENT_A_ID) not in client_ids, "User B should NOT see Client A"
        cur.execute("ROLLBACK")

    def test_client_viewer_sees_only_assigned_client(
        self, db_conn: psycopg2.extensions.connection
    ) -> None:
        """Client viewer should see only Client A (their assigned client)."""
        cur = db_conn.cursor()
        cur.execute("BEGIN")
        _set_user(cur, str(CLIENT_VIEWER_ID))
        cur.execute("SELECT id FROM clients")
        rows = cur.fetchall()
        client_ids = {str(r[0]) for r in rows}
        assert str(CLIENT_A_ID) in client_ids, "Client viewer should see Client A"
        assert str(CLIENT_B_ID) not in client_ids, "Client viewer should NOT see Client B"
        cur.execute("ROLLBACK")


class TestRLSPrompts:
    """Test RLS on the prompts table (client-scoped)."""

    def test_user_a_sees_only_client_a_prompts(
        self, db_conn: psycopg2.extensions.connection
    ) -> None:
        """User A should see only prompts for Client A."""
        cur = db_conn.cursor()
        cur.execute("BEGIN")
        _set_user(cur, str(USER_A_ID))
        cur.execute("SELECT client_id FROM prompts")
        rows = cur.fetchall()
        seen_clients = {str(r[0]) for r in rows}
        # User A might see Client A's prompts; must NOT see Client B's
        assert str(CLIENT_B_ID) not in seen_clients, "User A should NOT see Client B prompts"
        cur.execute("ROLLBACK")

    def test_user_b_cannot_see_client_a_prompts(
        self, db_conn: psycopg2.extensions.connection
    ) -> None:
        """User B should not see Client A's prompts."""
        cur = db_conn.cursor()
        cur.execute("BEGIN")
        _set_user(cur, str(USER_B_ID))
        cur.execute("SELECT client_id FROM prompts")
        rows = cur.fetchall()
        seen_clients = {str(r[0]) for r in rows}
        assert str(CLIENT_A_ID) not in seen_clients, "User B should NOT see Client A prompts"
        cur.execute("ROLLBACK")


class TestRLSBrandProfile:
    """Test RLS on brand_profiles (client-scoped)."""

    def test_cross_tenant_read_blocked(
        self, db_conn: psycopg2.extensions.connection
    ) -> None:
        """User A should not see Client B's brand profile."""
        cur = db_conn.cursor()
        cur.execute("BEGIN")
        _set_user(cur, str(USER_A_ID))
        cur.execute("SELECT client_id FROM brand_profiles")
        rows = cur.fetchall()
        seen_clients = {str(r[0]) for r in rows}
        assert str(CLIENT_B_ID) not in seen_clients
        cur.execute("ROLLBACK")


class TestRLSWriteBlocked:
    """Test that RLS blocks cross-tenant writes."""

    def test_user_a_cannot_insert_prompt_for_client_b(
        self, db_conn: psycopg2.extensions.connection
    ) -> None:
        """User A should not be able to insert a prompt for Client B."""
        cur = db_conn.cursor()
        cur.execute("BEGIN")
        _set_user(cur, str(USER_A_ID))
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute(
                "INSERT INTO prompts (client_id, text) VALUES (%s, %s)",
                (str(CLIENT_B_ID), "Malicious prompt"),
            )
        cur.execute("ROLLBACK")

    def test_user_b_cannot_update_client_a_profile(
        self, db_conn: psycopg2.extensions.connection
    ) -> None:
        """User B should not be able to update Client A's brand profile."""
        cur = db_conn.cursor()
        cur.execute("BEGIN")
        _set_user(cur, str(USER_B_ID))
        cur.execute(
            "UPDATE brand_profiles SET voice = 'hacked' WHERE client_id = %s",
            (str(CLIENT_A_ID),),
        )
        # RLS should silently filter — 0 rows affected
        assert cur.rowcount == 0, "User B should not be able to update Client A's profile"
        cur.execute("ROLLBACK")
