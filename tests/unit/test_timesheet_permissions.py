"""Unit tests for timesheet permission integration.

Validates: Requirements 7.1, 7.2, 7.3, 7.5, 7.6

Tests that:
- timesheet.approve and payrun.lock appear in available permissions (CUSTOM_PERMISSIONS)
- has_permission resolves correctly for org_admin wildcard and explicit grant
- staff_member role is NOT blocked at the path layer for /api/v2/timesheets
"""
from __future__ import annotations

import pytest

from app.modules.auth.permission_registry import CUSTOM_PERMISSIONS
from app.modules.auth.rbac import (
    STAFF_MEMBER_ALLOWED_PREFIXES,
    check_role_path_access,
    has_permission,
)


class TestCustomPermissionsRegistered:
    """Verify timesheet.approve and payrun.lock are in CUSTOM_PERMISSIONS."""

    def test_timesheet_approve_in_custom_permissions(self):
        """timesheet.approve must be listed in CUSTOM_PERMISSIONS for timesheets module."""
        assert "timesheets" in CUSTOM_PERMISSIONS
        keys = [p.key for p in CUSTOM_PERMISSIONS["timesheets"]]
        assert "timesheet.approve" in keys

    def test_payrun_lock_in_custom_permissions(self):
        """payrun.lock must be listed in CUSTOM_PERMISSIONS for timesheets module."""
        assert "timesheets" in CUSTOM_PERMISSIONS
        keys = [p.key for p in CUSTOM_PERMISSIONS["timesheets"]]
        assert "payrun.lock" in keys


class TestHasPermissionResolution:
    """Verify has_permission resolves correctly for timesheet permissions."""

    def test_org_admin_has_timesheet_approve_via_wildcard(self):
        """org_admin should have timesheet.approve via timesheet.* wildcard."""
        assert has_permission("org_admin", "timesheet.approve") is True

    def test_org_admin_has_payrun_lock_via_wildcard(self):
        """org_admin should have payrun.lock via payrun.* wildcard."""
        assert has_permission("org_admin", "payrun.lock") is True

    def test_staff_member_does_not_have_timesheet_approve_by_default(self):
        """staff_member should NOT have timesheet.approve without explicit grant."""
        assert has_permission("staff_member", "timesheet.approve") is False

    def test_staff_member_with_custom_grant_has_timesheet_approve(self):
        """staff_member with custom_role_permissions including timesheet.approve should have it."""
        assert has_permission(
            "staff_member",
            "timesheet.approve",
            custom_role_permissions=["timesheet.approve"],
        ) is True

    def test_staff_member_with_custom_grant_has_payrun_lock(self):
        """staff_member with custom_role_permissions including payrun.lock should have it."""
        assert has_permission(
            "staff_member",
            "payrun.lock",
            custom_role_permissions=["payrun.lock"],
        ) is True

    def test_global_admin_has_all_permissions(self):
        """global_admin has wildcard * so should have any permission."""
        assert has_permission("global_admin", "timesheet.approve") is True
        assert has_permission("global_admin", "payrun.lock") is True

    def test_override_denies_permission(self):
        """Overrides should take precedence over role permissions."""
        overrides = [{"permission_key": "timesheet.approve", "is_granted": False}]
        assert has_permission("org_admin", "timesheet.approve", overrides=overrides) is False

    def test_override_grants_permission(self):
        """Overrides can explicitly grant a permission."""
        overrides = [{"permission_key": "timesheet.approve", "is_granted": True}]
        assert has_permission("staff_member", "timesheet.approve", overrides=overrides) is True


class TestStaffMemberPathAccess:
    """Verify staff_member is not blocked at path layer for timesheet endpoints."""

    def test_staff_member_can_reach_timesheets(self):
        """staff_member should NOT be blocked for /api/v2/timesheets."""
        result = check_role_path_access("staff_member", "/api/v2/timesheets", method="GET")
        assert result is None, f"Unexpected denial: {result}"

    def test_staff_member_can_reach_timesheets_subpath(self):
        """staff_member should NOT be blocked for /api/v2/timesheets/{id}."""
        result = check_role_path_access("staff_member", "/api/v2/timesheets/some-uuid", method="GET")
        assert result is None, f"Unexpected denial: {result}"

    def test_staff_member_can_reach_clocked_in(self):
        """staff_member should NOT be blocked for /api/v2/clocked-in."""
        result = check_role_path_access("staff_member", "/api/v2/clocked-in", method="GET")
        assert result is None, f"Unexpected denial: {result}"

    def test_staff_member_can_reach_timesheet_settings(self):
        """staff_member should NOT be blocked for /api/v2/timesheet-settings."""
        result = check_role_path_access("staff_member", "/api/v2/timesheet-settings", method="GET")
        assert result is None, f"Unexpected denial: {result}"

    def test_staff_member_can_post_to_timesheets(self):
        """staff_member should NOT be blocked for POST on /api/v2/timesheets (permission handles auth)."""
        result = check_role_path_access("staff_member", "/api/v2/timesheets/some-id/approve", method="POST")
        assert result is None, f"Unexpected denial: {result}"

    def test_timesheets_in_allowed_prefixes(self):
        """The three timesheet prefixes must be in STAFF_MEMBER_ALLOWED_PREFIXES."""
        assert any("/api/v2/timesheets" in p for p in STAFF_MEMBER_ALLOWED_PREFIXES)
        assert any("/api/v2/clocked-in" in p for p in STAFF_MEMBER_ALLOWED_PREFIXES)
        assert any("/api/v2/timesheet-settings" in p for p in STAFF_MEMBER_ALLOWED_PREFIXES)
