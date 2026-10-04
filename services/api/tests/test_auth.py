"""Tests for auth module — JWT decoding, role checking, and user context."""

from __future__ import annotations

from services.api.app.auth import OPS_ROLES, PORTAL_ROLES, MemberRole


class TestRoleEnums:
    """Test role classification helpers."""

    def test_ops_roles_are_internal(self) -> None:
        """All ops roles should be internal roles."""
        assert MemberRole.OWNER in OPS_ROLES
        assert MemberRole.ADMIN in OPS_ROLES
        assert MemberRole.STRATEGIST in OPS_ROLES
        assert MemberRole.EDITOR in OPS_ROLES

    def test_portal_roles_are_client_scoped(self) -> None:
        """Portal roles should only contain client-scoped roles."""
        assert MemberRole.CLIENT_APPROVER in PORTAL_ROLES
        assert MemberRole.CLIENT_VIEWER in PORTAL_ROLES
        assert MemberRole.OWNER not in PORTAL_ROLES

    def test_no_role_overlap(self) -> None:
        """Ops and portal roles should not overlap."""
        assert OPS_ROLES.isdisjoint(PORTAL_ROLES)

    def test_all_roles_covered(self) -> None:
        """Every member_role_t value should be in either ops or portal."""
        all_roles = set(MemberRole)
        covered = OPS_ROLES | PORTAL_ROLES
        assert all_roles == covered, f"Uncovered roles: {all_roles - covered}"


class TestMemberRoleValues:
    """Test that enum values match the database enum exactly."""

    def test_values_match_db(self) -> None:
        expected = {"owner", "admin", "strategist", "editor", "client_approver", "client_viewer"}
        actual = {r.value for r in MemberRole}
        assert actual == expected
