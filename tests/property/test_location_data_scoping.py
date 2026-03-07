"""Property-based test: location data scoping for location_manager.

**Validates: Requirements 8.2, 8.6**

Property 17: For any Location_Manager user U assigned to location L, all
data returned by API queries is scoped to location L. No data from other
locations within the same organisation is accessible.

This test verifies the LocationScopedPermission logic directly: regardless
of what location IDs are generated, a location_manager can only access
resources whose location_id is in their assigned_location_ids.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from app.modules.auth.rbac import (
    LocationScopedPermission,
    PermissionDenied,
    LOCATION_MANAGER,
    has_permission,
    ROLE_PERMISSIONS,
)


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_uuid_strategy = st.uuids()
_location_list_strategy = st.lists(_uuid_strategy, min_size=1, max_size=5)


def _make_request(role: str, assigned_location_ids: list[uuid.UUID]) -> SimpleNamespace:
    """Build a fake request object with .state namespace for testing."""
    state = SimpleNamespace(
        user_id=str(uuid.uuid4()),
        org_id=str(uuid.uuid4()),
        role=role,
        assigned_location_ids=[str(lid) for lid in assigned_location_ids],
        franchise_group_id=None,
    )
    return SimpleNamespace(state=state)


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ===========================================================================
# Property 17: Location Data Scoping
# ===========================================================================


class TestLocationDataScoping:
    """For any location_manager user assigned to locations L, access to
    resources at location X is allowed iff X ∈ L.

    **Validates: Requirements 8.2, 8.6**
    """

    @given(
        assigned_locations=_location_list_strategy,
    )
    @PBT_SETTINGS
    def test_access_allowed_for_assigned_location(
        self,
        assigned_locations: list[uuid.UUID],
    ) -> None:
        """A location_manager can access any of their assigned locations."""
        scope = LocationScopedPermission()
        request = _make_request("location_manager", assigned_locations)

        for loc_id in assigned_locations:
            # Should not raise
            _run(scope.check(request, resource_location_id=str(loc_id)))

    @given(
        assigned_locations=_location_list_strategy,
        other_location=_uuid_strategy,
    )
    @PBT_SETTINGS
    def test_access_denied_for_unassigned_location(
        self,
        assigned_locations: list[uuid.UUID],
        other_location: uuid.UUID,
    ) -> None:
        """A location_manager cannot access a location not in their assignments."""
        assume(other_location not in assigned_locations)

        scope = LocationScopedPermission()
        request = _make_request("location_manager", assigned_locations)

        with pytest.raises(PermissionDenied, match="Access restricted to assigned locations"):
            _run(scope.check(request, resource_location_id=str(other_location)))

    @given(
        assigned_locations=_location_list_strategy,
        resource_location=_uuid_strategy,
        role=st.sampled_from(["org_admin", "salesperson", "global_admin", "staff_member"]),
    )
    @PBT_SETTINGS
    def test_non_location_manager_not_restricted(
        self,
        assigned_locations: list[uuid.UUID],
        resource_location: uuid.UUID,
        role: str,
    ) -> None:
        """Non-location_manager roles are not restricted by location scoping."""
        scope = LocationScopedPermission()
        request = _make_request(role, assigned_locations)

        # Should not raise for any role other than location_manager
        _run(scope.check(request, resource_location_id=str(resource_location)))

    @given(
        assigned_locations=_location_list_strategy,
    )
    @PBT_SETTINGS
    def test_none_location_skips_check(
        self,
        assigned_locations: list[uuid.UUID],
    ) -> None:
        """When resource_location_id is None, the check is skipped."""
        scope = LocationScopedPermission()
        request = _make_request("location_manager", assigned_locations)

        # Should not raise when location is None
        _run(scope.check(request, resource_location_id=None))
