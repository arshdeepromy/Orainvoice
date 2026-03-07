"""Tests for Task 4.10 — IP allowlisting.

Tests cover:
  - IP allowlist parsing and matching (unit tests for core utility)
  - Self-lockout prevention (Requirement 6.2)
  - Blocked IP returns clear error (Requirement 6.3)
  - IP allowlist check integration with auth service
  - Allowlist update endpoint validation

Requirements: 6.1, 6.2, 6.3
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.ip_allowlist import (
    get_org_ip_allowlist,
    is_ip_in_allowlist,
    parse_ip_network,
    validate_allowlist_entries,
)


# ---------------------------------------------------------------------------
# Unit tests: core IP allowlist utilities
# ---------------------------------------------------------------------------


class TestParseIpNetwork:
    """Test parse_ip_network with various inputs."""

    def test_single_ipv4(self):
        net = parse_ip_network("192.168.1.1")
        assert net is not None
        assert str(net) == "192.168.1.1/32"

    def test_cidr_range(self):
        net = parse_ip_network("10.0.0.0/8")
        assert net is not None
        assert str(net) == "10.0.0.0/8"

    def test_ipv6(self):
        net = parse_ip_network("::1")
        assert net is not None

    def test_ipv6_cidr(self):
        net = parse_ip_network("2001:db8::/32")
        assert net is not None

    def test_invalid_entry(self):
        assert parse_ip_network("not-an-ip") is None

    def test_empty_string(self):
        assert parse_ip_network("") is None

    def test_whitespace_stripped(self):
        net = parse_ip_network("  10.0.0.0/24  ")
        assert net is not None
        assert str(net) == "10.0.0.0/24"


class TestIsIpInAllowlist:
    """Test is_ip_in_allowlist matching logic."""

    def test_exact_ip_match(self):
        assert is_ip_in_allowlist("192.168.1.1", ["192.168.1.1"]) is True

    def test_ip_in_cidr_range(self):
        assert is_ip_in_allowlist("10.0.0.5", ["10.0.0.0/24"]) is True

    def test_ip_not_in_range(self):
        assert is_ip_in_allowlist("172.16.0.1", ["10.0.0.0/8"]) is False

    def test_ip_in_one_of_multiple_ranges(self):
        allowlist = ["192.168.1.0/24", "10.0.0.0/8"]
        assert is_ip_in_allowlist("10.5.5.5", allowlist) is True

    def test_ip_not_in_any_range(self):
        allowlist = ["192.168.1.0/24", "10.0.0.0/8"]
        assert is_ip_in_allowlist("172.16.0.1", allowlist) is False

    def test_empty_allowlist(self):
        assert is_ip_in_allowlist("192.168.1.1", []) is False

    def test_invalid_ip_address(self):
        assert is_ip_in_allowlist("not-an-ip", ["10.0.0.0/8"]) is False

    def test_invalid_allowlist_entry_skipped(self):
        # Invalid entries are skipped, valid ones still match
        assert is_ip_in_allowlist("10.0.0.1", ["bad-entry", "10.0.0.0/8"]) is True

    def test_ipv6_match(self):
        assert is_ip_in_allowlist("::1", ["::1"]) is True

    def test_ipv6_cidr_match(self):
        assert is_ip_in_allowlist("2001:db8::1", ["2001:db8::/32"]) is True

    def test_broad_cidr(self):
        # /0 matches everything
        assert is_ip_in_allowlist("1.2.3.4", ["0.0.0.0/0"]) is True


class TestValidateAllowlistEntries:
    """Test validate_allowlist_entries for error detection."""

    def test_all_valid(self):
        entries = ["192.168.1.0/24", "10.0.0.1", "::1"]
        assert validate_allowlist_entries(entries) == []

    def test_invalid_entry(self):
        entries = ["192.168.1.0/24", "not-valid"]
        errors = validate_allowlist_entries(entries)
        assert len(errors) == 1
        assert "not-valid" in errors[0]

    def test_empty_list(self):
        assert validate_allowlist_entries([]) == []

    def test_multiple_invalid(self):
        entries = ["bad1", "bad2"]
        errors = validate_allowlist_entries(entries)
        assert len(errors) == 2


class TestGetOrgIpAllowlist:
    """Test get_org_ip_allowlist extraction from settings."""

    def test_no_settings(self):
        assert get_org_ip_allowlist(None) is None

    def test_empty_settings(self):
        assert get_org_ip_allowlist({}) is None

    def test_no_allowlist_key(self):
        assert get_org_ip_allowlist({"mfa_policy": "optional"}) is None

    def test_empty_allowlist(self):
        assert get_org_ip_allowlist({"ip_allowlist": []}) is None

    def test_valid_allowlist(self):
        result = get_org_ip_allowlist({"ip_allowlist": ["10.0.0.0/8"]})
        assert result == ["10.0.0.0/8"]

    def test_none_allowlist(self):
        assert get_org_ip_allowlist({"ip_allowlist": None}) is None

    def test_non_list_allowlist(self):
        # String instead of list — should return None
        assert get_org_ip_allowlist({"ip_allowlist": "10.0.0.0/8"}) is None


# ---------------------------------------------------------------------------
# Integration tests: check_ip_allowlist in auth service
# ---------------------------------------------------------------------------


class TestCheckIpAllowlist:
    """Test the check_ip_allowlist function from auth service."""

    @pytest.mark.asyncio
    async def test_no_allowlist_configured_allows_all(self):
        """When org has no IP allowlist, all IPs should be allowed."""
        from app.modules.auth.service import check_ip_allowlist

        mock_db = AsyncMock()
        # Simulate org with no ip_allowlist in settings
        mock_result = MagicMock()
        mock_result.first.return_value = ({"mfa_policy": "optional"},)
        mock_db.execute.return_value = mock_result

        org_id = uuid.uuid4()
        blocked = await check_ip_allowlist(
            mock_db, org_id=org_id, ip_address="1.2.3.4",
        )
        assert blocked is False

    @pytest.mark.asyncio
    async def test_ip_in_allowlist_allowed(self):
        """When IP is in the allowlist, login should be allowed."""
        from app.modules.auth.service import check_ip_allowlist

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = ({"ip_allowlist": ["10.0.0.0/8"]},)
        mock_db.execute.return_value = mock_result

        org_id = uuid.uuid4()
        blocked = await check_ip_allowlist(
            mock_db, org_id=org_id, ip_address="10.5.5.5",
        )
        assert blocked is False

    @pytest.mark.asyncio
    async def test_ip_not_in_allowlist_blocked(self):
        """When IP is NOT in the allowlist, login should be blocked (Req 6.1)."""
        from app.modules.auth.service import check_ip_allowlist

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = ({"ip_allowlist": ["10.0.0.0/8"]},)
        mock_db.execute.return_value = mock_result

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        blocked = await check_ip_allowlist(
            mock_db, org_id=org_id, ip_address="172.16.0.1",
            user_id=user_id, email="test@example.com",
        )
        assert blocked is True

        # Verify audit log was written (Req 6.3)
        # The second call to db.execute should be the audit log insert
        assert mock_db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_org_not_found_allows(self):
        """When org record is not found, allow the request."""
        from app.modules.auth.service import check_ip_allowlist

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_db.execute.return_value = mock_result

        org_id = uuid.uuid4()
        blocked = await check_ip_allowlist(
            mock_db, org_id=org_id, ip_address="1.2.3.4",
        )
        assert blocked is False

    @pytest.mark.asyncio
    async def test_empty_allowlist_allows_all(self):
        """When ip_allowlist is an empty list, allowlisting is disabled."""
        from app.modules.auth.service import check_ip_allowlist

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = ({"ip_allowlist": []},)
        mock_db.execute.return_value = mock_result

        org_id = uuid.uuid4()
        blocked = await check_ip_allowlist(
            mock_db, org_id=org_id, ip_address="1.2.3.4",
        )
        assert blocked is False


# ---------------------------------------------------------------------------
# Self-lockout prevention tests (Requirement 6.2)
# ---------------------------------------------------------------------------


class TestSelfLockoutPrevention:
    """Test that saving an IP allowlist validates the current session IP."""

    def test_current_ip_in_new_allowlist_passes(self):
        """If the admin's IP is in the new allowlist, it should be accepted."""
        current_ip = "192.168.1.100"
        new_allowlist = ["192.168.1.0/24"]
        assert is_ip_in_allowlist(current_ip, new_allowlist) is True

    def test_current_ip_not_in_new_allowlist_fails(self):
        """If the admin's IP is NOT in the new allowlist, it should be rejected."""
        current_ip = "172.16.0.1"
        new_allowlist = ["192.168.1.0/24"]
        assert is_ip_in_allowlist(current_ip, new_allowlist) is False

    def test_empty_allowlist_disables(self):
        """An empty allowlist disables the feature — no lockout risk."""
        current_ip = "192.168.1.100"
        new_allowlist = []
        # Empty allowlist means disabled, so the check shouldn't even run
        # The endpoint handles this by skipping the check for empty lists
        assert is_ip_in_allowlist(current_ip, new_allowlist) is False


# ---------------------------------------------------------------------------
# Endpoint integration tests (using TestClient)
# ---------------------------------------------------------------------------


class TestIPAllowlistEndpoint:
    """Test the PUT /api/v1/auth/ip-allowlist endpoint."""

    @pytest.fixture
    def client(self):
        """Create a test client with the auth router and mocked DB dependency."""
        from contextlib import asynccontextmanager

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.core.database import get_db_session
        from app.modules.auth.router import router

        app = FastAPI()
        app.include_router(router, prefix="/api/v1/auth")

        mock_db = AsyncMock()

        async def override_get_db_session():
            yield mock_db

        app.dependency_overrides[get_db_session] = override_get_db_session

        return TestClient(app), mock_db

    def test_invalid_entries_rejected(self, client):
        """Invalid IP/CIDR entries should be rejected with 400."""
        from app.modules.auth.models import User

        test_client, mock_db = client

        user = MagicMock(spec=User)
        user.id = uuid.uuid4()
        user.org_id = uuid.uuid4()
        user.role = "org_admin"

        with patch("app.modules.auth.router._get_current_user", return_value=user):
            resp = test_client.put(
                "/api/v1/auth/ip-allowlist",
                json={"ip_allowlist": ["not-valid-ip"]},
            )
            assert resp.status_code == 400
            assert "Invalid" in resp.json()["detail"]

    def test_self_lockout_prevented(self, client):
        """Saving an allowlist that excludes the admin's IP should fail (Req 6.2)."""
        from app.modules.auth.models import User

        test_client, mock_db = client

        user = MagicMock(spec=User)
        user.id = uuid.uuid4()
        user.org_id = uuid.uuid4()
        user.role = "org_admin"

        with patch("app.modules.auth.router._get_current_user", return_value=user):
            # TestClient uses testclient which sets client IP to "testclient"
            # which won't match any real CIDR range
            resp = test_client.put(
                "/api/v1/auth/ip-allowlist",
                json={"ip_allowlist": ["10.0.0.0/8"]},
            )
            assert resp.status_code == 400
            assert "not included" in resp.json()["detail"]
