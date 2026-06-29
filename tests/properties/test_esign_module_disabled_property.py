"""Property 5 — Module-disabled endpoints are rejected (task 10.2).

# Feature: esignature-integration, Property 5: Module-disabled endpoints are rejected

**Validates: Requirements 2.2**

R2.2: *WHILE the ``esignatures`` module is disabled for an organisation, THE
Esign_Module SHALL return HTTP 403 for requests to endpoints under
``/api/v2/esign``.*

The runtime gate for ``/api/v2/esign`` is the **module only**, enforced at two
layers for defence-in-depth (design §"Module registration and gating"):

1. ``ModuleMiddleware`` (``app/middleware/modules.py``) maps the
   ``"/api/v2/esign": "esignatures"`` prefix and returns 403 when the module is
   disabled for the org.
2. The router-level dependency
   :func:`app.modules.esignatures.dependencies.require_esign_module` raises HTTP
   403 (``module_disabled``) — ``ModuleMiddleware`` fails *open* on internal
   errors, so the router carries its own gate.

Task 7.4 (``tests/test_esign_module_gate_property.py``) already exercises the
middleware ASGI path in depth. **This** Property-5 test focuses, and adds value,
on the *router dependency wired onto the real esign routes*: it asserts that

* every non-webhook ``/api/v2/esign`` route registered on the actual
  :mod:`app.modules.esignatures.router` router carries
  :func:`require_esign_module`, and that
* the dependency itself rejects with **403 / module_disabled** for *any* org and
  *any* esign sub-path when ``ModuleService.is_enabled`` reports the module
  disabled, and lets the request proceed (returns ``None``) when it is enabled.

It deliberately asserts **nothing** about ``feature_flags`` / "either source"
behaviour — ``ModuleService.is_enabled`` (backed by ``org_modules``) is the
single source of truth.

The gate is exercised in isolation with ``ModuleService.is_enabled`` stubbed
(no Redis/DB/network), mirroring the convention used by task 7.4 and the other
esign property tests.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from hypothesis import given, settings
from hypothesis import strategies as st

from app.middleware.modules import _resolve_module
from app.modules.esignatures.dependencies import (
    ESIGN_MODULE_SLUG,
    require_esign_module,
)
from app.modules.esignatures.errors import CODE_MODULE_DISABLED
from app.modules.esignatures.router import router as esign_router

PBT_SETTINGS = settings(max_examples=200, deadline=None)

# The canonical slug must be exactly "esignatures" everywhere (Task 7.3).
assert ESIGN_MODULE_SLUG == "esignatures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(org_id: uuid.UUID | None) -> MagicMock:
    """Minimal ``Request``-like object exposing only ``state.org_id``."""
    request = MagicMock()
    request.state = SimpleNamespace(org_id=org_id)
    return request


def _call_require_module(org_id: uuid.UUID, *, enabled: bool):
    """Drive ``require_esign_module`` with ``is_enabled`` stubbed to ``enabled``.

    Returns the dependency's return value (``None`` when it permits the request)
    and the recorded ``is_enabled`` call args, or raises the ``HTTPException``
    the dependency raises when the module is disabled.
    """
    request = _make_request(org_id)
    db = AsyncMock()
    with patch(
        "app.core.modules.ModuleService.is_enabled",
        new_callable=AsyncMock,
        return_value=enabled,
    ) as mock_is_enabled:
        result = asyncio.run(require_esign_module(request, db))
    return result, mock_is_enabled


# Representative esign endpoint sub-paths (all must resolve to the slug).
ESIGN_PATHS = [
    "/api/v2/esign",
    "/api/v2/esign/envelopes",
    "/api/v2/esign/envelopes/123e4567-e89b-12d3-a456-426614174000",
    "/api/v2/esign/envelopes/abc/void",
    "/api/v2/esign/envelopes/abc/signed-document",
]


# ---------------------------------------------------------------------------
# Added value — the router-level gate is wired onto the REAL esign routes.
# ---------------------------------------------------------------------------


def _router_has_module_gate() -> bool:
    """True iff ``require_esign_module`` is a router-level dependency."""
    for dep in esign_router.dependencies:
        call = getattr(dep, "dependency", None)
        if call is require_esign_module:
            return True
    return False


class TestRealRoutesCarryModuleGate:
    """Property 5 is enforced on the actual esign router, not just in theory."""

    def test_router_level_dependency_present(self):
        # The router declares ``dependencies=[Depends(require_esign_module)]`` so
        # EVERY mounted route inherits the module gate (R2.2).
        assert _router_has_module_gate()

    def test_every_esign_route_is_gated(self):
        # Each concrete route on the esign router inherits the router-level gate,
        # so no /api/v2/esign endpoint is silently ungated.
        routes = [r for r in esign_router.routes if hasattr(r, "path")]
        assert routes, "expected the esign router to register at least one route"
        for route in routes:
            route_dep_calls = {
                getattr(d, "dependency", None)
                for d in getattr(route, "dependencies", [])
            }
            # The gate is present either as a router-level dependency (inherited
            # by every route) or directly on the route.
            assert _router_has_module_gate() or require_esign_module in route_dep_calls

    @pytest.mark.parametrize("path", ESIGN_PATHS)
    def test_paths_resolve_to_esignatures_slug(self, path):
        # The middleware layer maps the same prefix to the canonical slug, so
        # the two defence-in-depth layers agree on what "esign" means.
        assert _resolve_module(path) == ESIGN_MODULE_SLUG


# ---------------------------------------------------------------------------
# Property 5 — disabled ⇒ 403 module_disabled; enabled ⇒ permitted.
# ---------------------------------------------------------------------------


class TestModuleDisabledRejected:
    """``require_esign_module`` rejects iff the module is disabled."""

    @PBT_SETTINGS
    @given(org_id=st.uuids())
    def test_disabled_rejects_with_403_module_disabled(self, org_id: uuid.UUID):
        """For any org, a disabled module yields 403 / ``module_disabled``.

        # Feature: esignature-integration, Property 5: Module-disabled endpoints are rejected

        **Validates: Requirements 2.2**
        """
        with pytest.raises(HTTPException) as excinfo:
            _call_require_module(org_id, enabled=False)

        assert excinfo.value.status_code == 403
        detail = excinfo.value.detail
        assert isinstance(detail, dict)
        assert detail["code"] == CODE_MODULE_DISABLED
        assert isinstance(detail["message"], str) and detail["message"]

    @PBT_SETTINGS
    @given(org_id=st.uuids())
    def test_disabled_gates_against_canonical_slug_and_org(self, org_id: uuid.UUID):
        """The gate consults ``is_enabled(org_id, "esignatures")`` (single source).

        # Feature: esignature-integration, Property 5: Module-disabled endpoints are rejected

        **Validates: Requirements 2.2**
        """
        request = _make_request(org_id)
        db = AsyncMock()
        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=False,
        ) as mock_is_enabled:
            with pytest.raises(HTTPException):
                asyncio.run(require_esign_module(request, db))
            mock_is_enabled.assert_awaited_once()
            args = mock_is_enabled.await_args.args
            assert args[0] == str(org_id)
            assert args[1] == ESIGN_MODULE_SLUG

    @PBT_SETTINGS
    @given(org_id=st.uuids())
    def test_enabled_permits_request(self, org_id: uuid.UUID):
        """For any org, an enabled module lets the request through (returns None).

        # Feature: esignature-integration, Property 5: Module-disabled endpoints are rejected

        **Validates: Requirements 2.2**
        """
        result, _ = _call_require_module(org_id, enabled=True)
        assert result is None

    @PBT_SETTINGS
    @given(org_id=st.uuids(), enabled=st.booleans())
    def test_rejected_exactly_when_disabled(self, org_id: uuid.UUID, enabled: bool):
        """Rejection happens exactly when the module is disabled, for any org.

        # Feature: esignature-integration, Property 5: Module-disabled endpoints are rejected

        **Validates: Requirements 2.2**
        """
        if enabled:
            result, _ = _call_require_module(org_id, enabled=True)
            assert result is None
        else:
            with pytest.raises(HTTPException) as excinfo:
                _call_require_module(org_id, enabled=False)
            assert excinfo.value.status_code == 403
            assert excinfo.value.detail["code"] == CODE_MODULE_DISABLED
