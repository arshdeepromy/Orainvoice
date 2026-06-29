"""Property/example tests for field-placement send RBAC (task 14.2).

# Feature: esignature-field-placement, Property 16: Role-based access control for field-placement send, edit, and templates

**Validates: Requirements 9.2**

A field-placement send is a ``POST /api/v2/esign/envelopes`` request whose
:class:`EnvelopeCreate` payload carries a non-empty ``fields`` list (the
sender-defined Field_Set). The route applies the same RBAC gate as every other
mutating esign route —
:data:`app.modules.esignatures.dependencies.require_esign_sender`, defined as
``require_role(ORG_ADMIN, BRANCH_ADMIN, LOCATION_MANAGER)``. Per Requirement 9.2
of ``esignature-field-placement`` the field-placement send is permitted **iff**
the caller holds one of those three Org_Sender roles; every other role is
rejected with HTTP 403.

The RBAC gate is payload-agnostic — it inspects only ``request.state.role`` and
runs *before* the handler reads the body — so the presence of a ``fields`` set
does not change the gate's verdict. This test exercises ``require_esign_sender``
directly (via its inner ``_check`` coroutine) with a mock request, the same
pure-logic convention used by the existing
``tests/test_esign_rbac_send_void_property.py`` (Property 22 of the base spec),
and extends it to the field-placement send.

(The edit and template portions of Property 16 are covered in Task 21.7.)
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

# The three Org_Sender roles permitted to initiate a field-placement send (R9.2).
PERMITTED_ROLES = [ORG_ADMIN, BRANCH_ADMIN, LOCATION_MANAGER]

# Every other real role in the codebase must be denied. ``viewer`` is not a real
# role here but is included as an extra explicit denial per the requirement.
DENIED_ROLES = sorted((ALL_ROLES - set(PERMITTED_ROLES)) | {"viewer"})

# ``require_role`` returns ``Depends(_check)``; the inner coroutine reads
# ``user_id`` / ``org_id`` / ``role`` from ``request.state``.
_check_fn = require_esign_sender.dependency


def _make_request(
    *, user_id: str | None, org_id: str | None, role: str | None
) -> MagicMock:
    """Build a minimal ``Request`` exposing the ``state`` attrs ``_check`` reads."""
    request = MagicMock()
    request.state = SimpleNamespace(user_id=user_id, org_id=org_id, role=role)
    return request


# ---------------------------------------------------------------------------
# Property 16 (send portion) — the RBAC biconditional for a field-placement send
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(
    role=st.sampled_from(PERMITTED_ROLES + DENIED_ROLES),
    user_id=st.uuids(),
    org_id=st.uuids(),
)
def test_field_placement_send_permitted_iff_org_sender(
    role: str, user_id, org_id
) -> None:
    """**Validates: Requirements 9.2**

    The biconditional: a field-placement send (a send carrying a Field_Set)
    passes the ``require_esign_sender`` gate exactly when the caller holds one
    of the three Org_Sender roles (``org_admin`` / ``branch_admin`` /
    ``location_manager``); every other authenticated role is rejected with
    HTTP 403. The gate is payload-agnostic, so this holds for the field-set
    send identically to the plain send.
    """
    request = _make_request(user_id=str(user_id), org_id=str(org_id), role=role)
    if role in PERMITTED_ROLES:
        # Permitted Org_Sender role → gate allows the field-placement send.
        asyncio.run(_check_fn(request))  # must not raise
    else:
        # Any other role → HTTP 403.
        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(_check_fn(request))
        assert excinfo.value.status_code == 403, (
            f"Expected 403 for role={role!r}, got {excinfo.value.status_code}"
        )


# ---------------------------------------------------------------------------
# Example/edge tests — explicit named roles and unauthenticated cases
# ---------------------------------------------------------------------------


class TestExplicitRoles:
    """Concrete spot-checks for the roles named in Requirement 9.2."""

    @pytest.mark.parametrize("role", PERMITTED_ROLES)
    def test_org_sender_role_allowed(self, role: str) -> None:
        request = _make_request(
            user_id=str(uuid.uuid4()), org_id=str(uuid.uuid4()), role=role
        )
        asyncio.run(_check_fn(request))  # no raise

    @pytest.mark.parametrize(
        "role", ["salesperson", "staff_member", "viewer", "global_admin"]
    )
    def test_non_sender_roles_get_403(self, role: str) -> None:
        request = _make_request(
            user_id=str(uuid.uuid4()), org_id=str(uuid.uuid4()), role=role
        )
        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(_check_fn(request))
        assert excinfo.value.status_code == 403

    def test_unauthenticated_field_placement_send_raises_401(self) -> None:
        request = _make_request(user_id=None, org_id=None, role=None)
        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(_check_fn(request))
        assert excinfo.value.status_code == 401

    def test_org_sender_without_org_context_raises_403(self) -> None:
        # Org-scoped roles must carry an org_id; missing org membership → 403.
        request = _make_request(
            user_id=str(uuid.uuid4()), org_id=None, role=ORG_ADMIN
        )
        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(_check_fn(request))
        assert excinfo.value.status_code == 403
