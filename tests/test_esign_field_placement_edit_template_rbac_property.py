"""Property/example tests for field-placement edit + template RBAC (task 21.7).

# Feature: esignature-field-placement, Property 16: Role-based access control for field-placement send, edit, and templates

**Validates: Requirements 13.2, 17.7**

This covers the **edit + template** portion of Property 16. The send portion is
covered in :mod:`tests.test_esign_field_placement_rbac_property` (task 14.2).

Three mutating field-placement routes carry the same RBAC gate
(:data:`app.modules.esignatures.dependencies.require_esign_sender`, defined as
``require_role(ORG_ADMIN, BRANCH_ADMIN, LOCATION_MANAGER)``):

* ``PUT /api/v2/esign/envelopes/{id}/fields`` — replace a sent Envelope's
  Field_Set in place (a post-send edit, Requirement 13).
* ``POST /api/v2/esign/field-templates`` — create a reusable Field_Template
  (Requirement 17).
* ``DELETE /api/v2/esign/field-templates/{id}`` — delete a Field_Template
  (Requirement 17).

Per Requirement 13.2 (edit) and Requirement 17.7 (template create/apply/delete),
each of these is permitted **iff** the caller holds one of the three Org_Sender
roles (``org_admin`` / ``branch_admin`` / ``location_manager``); every other
role is rejected with HTTP 403.

The RBAC gate is route-agnostic — it inspects only ``request.state.role`` and
runs *before* the handler reads the body or path — so the verdict is identical
across the edit and template routes. The three routes are confirmed to carry
``dependencies=[require_esign_sender]`` in
``app/modules/esignatures/router.py``. This test exercises
``require_esign_sender`` directly (via its inner ``_check`` coroutine) with a
mock request, mirroring task 14.2's approach.
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

# The three Org_Sender roles permitted to edit a Field_Set (R13.2) or to
# create/apply/delete a Field_Template (R17.7).
PERMITTED_ROLES = [ORG_ADMIN, BRANCH_ADMIN, LOCATION_MANAGER]

# Every other real role in the codebase must be denied. ``viewer`` is not a real
# role here but is included as an extra explicit denial per the requirements.
DENIED_ROLES = sorted((ALL_ROLES - set(PERMITTED_ROLES)) | {"viewer"})

# The three mutating edit + template routes that carry ``require_esign_sender``.
# Labels are descriptive only — the gate is route-agnostic, so all three share
# one verdict for a given role. Listing them documents the coverage intent.
EDIT_TEMPLATE_ROUTES = [
    "PUT /envelopes/{id}/fields",   # post-send Field_Set edit (R13.2)
    "POST /field-templates",        # create a Field_Template (R17.7)
    "DELETE /field-templates/{id}",  # delete a Field_Template (R17.7)
]

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
# Property 16 (edit + template portion) — the RBAC biconditional for the
# PUT …/fields edit and the POST/DELETE …/field-templates routes.
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(
    role=st.sampled_from(PERMITTED_ROLES + DENIED_ROLES),
    route=st.sampled_from(EDIT_TEMPLATE_ROUTES),
    user_id=st.uuids(),
    org_id=st.uuids(),
)
def test_edit_and_template_mutations_permitted_iff_org_sender(
    role: str, route: str, user_id, org_id
) -> None:
    """**Validates: Requirements 13.2, 17.7**

    The biconditional: a post-send Field_Set edit (``PUT …/fields``, R13.2) and
    a Field_Template create/apply/delete (``POST``/``DELETE …/field-templates``,
    R17.7) each pass the ``require_esign_sender`` gate exactly when the caller
    holds one of the three Org_Sender roles (``org_admin`` / ``branch_admin`` /
    ``location_manager``); every other authenticated role is rejected with
    HTTP 403. The gate is route-agnostic, so this holds identically across all
    three mutating edit + template routes.
    """
    request = _make_request(user_id=str(user_id), org_id=str(org_id), role=role)
    if role in PERMITTED_ROLES:
        # Permitted Org_Sender role → gate allows the edit / template mutation.
        asyncio.run(_check_fn(request))  # must not raise
    else:
        # Any other role → HTTP 403, regardless of which mutating route.
        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(_check_fn(request))
        assert excinfo.value.status_code == 403, (
            f"Expected 403 for role={role!r} on {route}, "
            f"got {excinfo.value.status_code}"
        )


# ---------------------------------------------------------------------------
# Example/edge tests — explicit named roles and unauthenticated cases
# ---------------------------------------------------------------------------


class TestExplicitRoles:
    """Concrete spot-checks for the roles named in R13.2 / R17.7."""

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

    def test_unauthenticated_edit_or_template_raises_401(self) -> None:
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
