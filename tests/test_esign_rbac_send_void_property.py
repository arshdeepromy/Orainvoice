"""Property/example tests for esign send & void RBAC (task 10.3).

# Feature: esignature-integration, Property 22: Role-based access control for send and void

**Validates: Requirements 12.1, 12.2, 12.3**

The ``/api/v2/esign`` ``POST /envelopes`` (send) and ``POST /envelopes/{id}/void``
routes carry the shared dependency
:data:`app.modules.esignatures.dependencies.require_esign_sender`, defined as
``require_role(ORG_ADMIN, BRANCH_ADMIN, LOCATION_MANAGER)``. Per the design,
send/void are permitted **iff** the caller holds one of those three Org_Sender
roles; every other role (e.g. ``salesperson``, ``staff_member``, ``viewer``,
``global_admin``, ``franchise_admin``, ``kiosk``) is rejected with HTTP 403.

``require_role`` returns ``Depends(_check)``; ``_check`` reads ``user_id`` /
``org_id`` / ``role`` from ``request.state`` and raises ``HTTPException`` (401
when unauthenticated, 403 when the role is not permitted). These tests invoke
that inner dependency directly with a mock request — the same pure-logic
convention used by ``tests/test_org_security_settings_property.py`` and
``tests/test_backup_access_control_unit.py`` — rather than spinning up the full
FastAPI + Postgres stack.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.auth.rbac import (
    ALL_ROLES,
    BRANCH_ADMIN,
    LOCATION_MANAGER,
    ORG_ADMIN,
)
from app.modules.esignatures.dependencies import require_esign_sender

PBT_SETTINGS = settings(max_examples=200, deadline=None)

# The three Org_Sender roles permitted to send/void agreements (R12.1/12.2/12.3).
PERMITTED_ROLES = [ORG_ADMIN, BRANCH_ADMIN, LOCATION_MANAGER]

# Every other real role in the codebase must be denied. ``viewer`` is not a real
# role here but is included as an extra explicit denial per the task brief.
DENIED_ROLES = sorted((ALL_ROLES - set(PERMITTED_ROLES)) | {"viewer"})

# The dependency under test exposes its inner ``_check`` coroutine via
# ``.dependency`` (``require_role`` returns ``Depends(_check)``).
_check_fn = require_esign_sender.dependency


def _make_request(
    *, user_id: str | None, org_id: str | None, role: str | None
) -> MagicMock:
    """Build a minimal ``Request`` exposing the ``state`` attrs ``_check`` reads."""
    request = MagicMock()
    request.state = SimpleNamespace(user_id=user_id, org_id=org_id, role=role)
    return request


# ---------------------------------------------------------------------------
# Property 22 — permitted roles pass, all others get 403
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(
    role=st.sampled_from(PERMITTED_ROLES),
    user_id=st.uuids(),
    org_id=st.uuids(),
)
def test_permitted_roles_allowed(role: str, user_id, org_id) -> None:
    """**Validates: Requirements 12.1, 12.2, 12.3**

    org_admin / branch_admin / location_manager (with a valid org context)
    pass the send/void gate without raising.
    """
    request = _make_request(user_id=str(user_id), org_id=str(org_id), role=role)
    # Should not raise.
    asyncio.run(_check_fn(request))


@PBT_SETTINGS
@given(
    role=st.sampled_from(DENIED_ROLES),
    user_id=st.uuids(),
    org_id=st.uuids(),
)
def test_other_roles_rejected_with_403(role: str, user_id, org_id) -> None:
    """**Validates: Requirements 12.1, 12.2, 12.3**

    Any role outside the three Org_Sender roles is rejected with HTTP 403,
    even when fully authenticated with a valid org context.
    """
    request = _make_request(user_id=str(user_id), org_id=str(org_id), role=role)
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(_check_fn(request))
    assert excinfo.value.status_code == 403, (
        f"Expected 403 for role={role!r}, got {excinfo.value.status_code}"
    )


@PBT_SETTINGS
@given(
    role=st.sampled_from(PERMITTED_ROLES + DENIED_ROLES),
    user_id=st.uuids(),
    org_id=st.uuids(),
)
def test_gate_permits_iff_role_is_org_sender(role: str, user_id, org_id) -> None:
    """**Validates: Requirements 12.1, 12.2, 12.3**

    The biconditional: the gate permits the request exactly when the role is
    one of the three permitted Org_Sender roles; otherwise it raises 403.
    """
    request = _make_request(user_id=str(user_id), org_id=str(org_id), role=role)
    if role in PERMITTED_ROLES:
        asyncio.run(_check_fn(request))  # permitted → no raise
    else:
        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(_check_fn(request))
        assert excinfo.value.status_code == 403


# ---------------------------------------------------------------------------
# Example/edge tests — explicit named roles and unauthenticated cases
# ---------------------------------------------------------------------------


class TestExplicitRoles:
    """Concrete spot-checks for the roles named in the requirements."""

    @pytest.mark.parametrize("role", PERMITTED_ROLES)
    def test_permitted_role_allowed(self, role: str) -> None:
        request = _make_request(
            user_id=str(uuid.uuid4()), org_id=str(uuid.uuid4()), role=role
        )
        asyncio.run(_check_fn(request))  # no raise

    @pytest.mark.parametrize("role", ["salesperson", "staff_member", "viewer"])
    def test_named_denied_roles_get_403(self, role: str) -> None:
        request = _make_request(
            user_id=str(uuid.uuid4()), org_id=str(uuid.uuid4()), role=role
        )
        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(_check_fn(request))
        assert excinfo.value.status_code == 403

    def test_unauthenticated_request_raises_401(self) -> None:
        request = _make_request(user_id=None, org_id=None, role=None)
        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(_check_fn(request))
        assert excinfo.value.status_code == 401

    def test_permitted_role_without_org_context_raises_403(self) -> None:
        # Org-scoped roles must carry an org_id; missing org membership → 403.
        request = _make_request(
            user_id=str(uuid.uuid4()), org_id=None, role=ORG_ADMIN
        )
        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(_check_fn(request))
        assert excinfo.value.status_code == 403
