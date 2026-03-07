"""Comprehensive property-based tests for RBAC properties.

Properties covered:
  P17 — Location Data Scoping: location_manager can only access assigned locations

**Validates: Requirements 17**
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from hypothesis import given, assume
from hypothesis import strategies as st

from tests.properties.conftest import PBT_SETTINGS

from app.modules.auth.rbac import (
    LocationScopedPermission,
    PermissionDenied,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_uuid_st = st.uuids()
_location_list_st = st.lists(_uuid_st, min_size=1, max_size=5)


def _make_request(role: str, assigned_location_ids: list[uuid.UUID]):
    state = SimpleNamespace(
        user_id=str(uuid.uuid4()),
        org_id=str(uuid.uuid4()),
        role=role,
        assigned_location_ids=[str(lid) for lid in assigned_location_ids],
        franchise_group_id=None,
    )
    return SimpleNamespace(state=state)


def _run(coro):
    return asyncio.run(coro)


# ===========================================================================
# Property 17: Location Data Scoping
# ===========================================================================


class TestP17LocationDataScoping:
    """Location_manager can only access data for assigned locations.

    **Validates: Requirements 17**
    """

    @given(assigned_locations=_location_list_st)
    @PBT_SETTINGS
    def test_access_allowed_for_assigned_location(
        self, assigned_locations,
    ) -> None:
        """P17: location_manager can access any assigned location."""
        scope = LocationScopedPermission()
        request = _make_request("location_manager", assigned_locations)
        for loc_id in assigned_locations:
            _run(scope.check(request, resource_location_id=str(loc_id)))

    @given(assigned_locations=_location_list_st, other_location=_uuid_st)
    @PBT_SETTINGS
    def test_access_denied_for_unassigned_location(
        self, assigned_locations, other_location,
    ) -> None:
        """P17: location_manager cannot access unassigned location."""
        assume(other_location not in assigned_locations)
        scope = LocationScopedPermission()
        request = _make_request("location_manager", assigned_locations)
        with pytest.raises(PermissionDenied, match="Access restricted to assigned locations"):
            _run(scope.check(request, resource_location_id=str(other_location)))

    @given(
        assigned_locations=_location_list_st,
        resource_location=_uuid_st,
        role=st.sampled_from(["org_admin", "salesperson", "global_admin", "staff_member"]),
    )
    @PBT_SETTINGS
    def test_non_location_manager_not_restricted(
        self, assigned_locations, resource_location, role,
    ) -> None:
        """P17: non-location_manager roles are not restricted."""
        scope = LocationScopedPermission()
        request = _make_request(role, assigned_locations)
        _run(scope.check(request, resource_location_id=str(resource_location)))

    @given(assigned_locations=_location_list_st)
    @PBT_SETTINGS
    def test_none_location_skips_check(self, assigned_locations) -> None:
        """P17: when resource_location_id is None, check is skipped."""
        scope = LocationScopedPermission()
        request = _make_request("location_manager", assigned_locations)
        _run(scope.check(request, resource_location_id=None))
