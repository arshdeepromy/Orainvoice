"""Property/example tests for the esignatures module gate (task 7.4).

# Feature: esignature-integration, Property: module-disabled endpoints return 403 via the module gate

**Validates: Requirements 2.1, 2.2, 2.3, 2.4**

The runtime gate for ``/api/v2/esign`` is the **module only**, enforced at two
layers for defence-in-depth (design §"Module registration and gating"):

1. ``ModuleMiddleware`` (``app/middleware/modules.py``) returns HTTP 403 for any
   request whose path resolves through the ``MODULE_ENDPOINT_MAP`` entry
   ``"/api/v2/esign": "esignatures"`` while the module is disabled for the org.
2. The router-level dependency
   :func:`app.modules.esignatures.dependencies.require_esign_module` raises HTTP
   403 (``ModuleMiddleware`` fails *open* on internal errors, so the router
   carries its own gate).

These tests assert both layers reject under-``/api/v2/esign`` requests with 403
when the ``esignatures`` module is disabled, and let them through (no 403) when
it is enabled. They deliberately assert **nothing** about ``feature_flags`` /
"either source" behaviour — ``ModuleService.is_enabled`` (backed by
``org_modules``) is the single source of truth.

Both layers are exercised in isolation with ``ModuleService.is_enabled`` /
``ModuleMiddleware._is_module_enabled_cached`` stubbed, rather than spinning up
the full FastAPI + Postgres + Redis stack (the same convention used by
``tests/test_staff_router.py``).
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

from app.middleware.modules import (
    MODULE_ENDPOINT_MAP,
    ModuleMiddleware,
    _resolve_module,
)
from app.modules.esignatures.dependencies import (
    ESIGN_MODULE_SLUG,
    require_esign_module,
)
from app.modules.esignatures.errors import CODE_MODULE_DISABLED

PBT_SETTINGS = settings(max_examples=150, deadline=None)

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


async def _run_middleware(
    path: str, org_id: uuid.UUID | None, enabled: bool
) -> tuple[int | None, bool]:
    """Drive ``ModuleMiddleware`` for one request; return (status, downstream_called).

    ``_is_module_enabled_cached`` is stubbed so no Redis/DB is touched. The
    downstream ASGI app records whether it was reached and replies 200.
    """
    state: dict = {}
    if org_id is not None:
        state["org_id"] = org_id

    downstream = {"called": False}

    async def dummy_app(scope, receive, send):  # noqa: ANN001
        downstream["called"] = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "server": ("testserver", 80),
        "headers": [],
        "state": state,
    }

    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):  # noqa: ANN001
        sent.append(message)

    mw = ModuleMiddleware(dummy_app)
    with patch.object(
        ModuleMiddleware,
        "_is_module_enabled_cached",
        new=AsyncMock(return_value=enabled),
    ):
        await mw(scope, receive, send)

    status = next(
        (m["status"] for m in sent if m["type"] == "http.response.start"), None
    )
    return status, downstream["called"]


# A spread of representative esign endpoint paths (all should be gated).
ESIGN_PATHS = [
    "/api/v2/esign",
    "/api/v2/esign/envelopes",
    "/api/v2/esign/envelopes/123e4567-e89b-12d3-a456-426614174000",
    "/api/v2/esign/envelopes/abc/void",
    "/api/v2/esign/envelopes/abc/signed-document",
]


# ---------------------------------------------------------------------------
# Layer 1 — MODULE_ENDPOINT_MAP / _resolve_module mapping (R2.1)
# ---------------------------------------------------------------------------


class TestEndpointMapMapping:
    """The ``/api/v2/esign`` prefix maps to the ``esignatures`` slug (R2.1)."""

    def test_endpoint_map_has_esign_entry(self):
        assert MODULE_ENDPOINT_MAP["/api/v2/esign"] == "esignatures"

    @pytest.mark.parametrize("path", ESIGN_PATHS)
    def test_esign_paths_resolve_to_esignatures(self, path):
        assert _resolve_module(path) == "esignatures"

    def test_webhook_path_resolves_to_esignatures(self):
        # The webhook path is under the prefix, so it resolves to the slug; the
        # middleware skips it only because such requests carry no org_id (see
        # TestMiddlewareGate.test_webhook_no_org_passes_through).
        assert _resolve_module("/api/v2/esign/webhook/route-abc") == "esignatures"

    def test_near_miss_paths_do_not_resolve(self):
        # Prefix matching is segment-aware: a path that merely starts with the
        # literal characters but is a different segment must NOT be gated as
        # esign.
        assert _resolve_module("/api/v2/esignatures") is None
        assert _resolve_module("/api/v2/esignx") is None
        assert _resolve_module("/api/v2/invoices") != "esignatures"

    @PBT_SETTINGS
    @given(suffix=st.text(alphabet=st.characters(blacklist_characters="?#"), min_size=0, max_size=40))
    def test_any_subpath_resolves_to_esignatures(self, suffix):
        # Any path that is exactly the prefix, or a child segment under it,
        # resolves to the esignatures slug.
        path = "/api/v2/esign" if suffix == "" else f"/api/v2/esign/{suffix}"
        assert _resolve_module(path) == "esignatures"


# ---------------------------------------------------------------------------
# Layer 1 — ModuleMiddleware 403 behaviour (R2.2)
# ---------------------------------------------------------------------------


class TestMiddlewareGate:
    """``ModuleMiddleware`` returns 403 for esign paths iff the module is off."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", ESIGN_PATHS)
    async def test_disabled_returns_403_and_blocks_downstream(self, path):
        status, downstream_called = await _run_middleware(
            path, org_id=uuid.uuid4(), enabled=False
        )
        assert status == 403
        assert downstream_called is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", ESIGN_PATHS)
    async def test_enabled_passes_through(self, path):
        status, downstream_called = await _run_middleware(
            path, org_id=uuid.uuid4(), enabled=True
        )
        assert status == 200
        assert downstream_called is True

    @pytest.mark.asyncio
    async def test_webhook_no_org_passes_through_even_when_disabled(self):
        # Documenso webhooks carry no org session; the middleware skips requests
        # with no org_id, so the public webhook is naturally ungated.
        status, downstream_called = await _run_middleware(
            "/api/v2/esign/webhook/route-abc", org_id=None, enabled=False
        )
        assert status == 200
        assert downstream_called is True

    @PBT_SETTINGS
    @given(
        suffix=st.text(
            alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")),
            min_size=0,
            max_size=30,
        ),
        enabled=st.booleans(),
    )
    def test_property_gate_matches_enablement(self, suffix, enabled):
        # For any esign sub-path and any org, the middleware returns 403 exactly
        # when the module is disabled, and passes through (200) when enabled.
        path = "/api/v2/esign" if suffix == "" else f"/api/v2/esign/{suffix}"
        status, downstream_called = asyncio.run(
            _run_middleware(path, org_id=uuid.uuid4(), enabled=enabled)
        )
        if enabled:
            assert status == 200
            assert downstream_called is True
        else:
            assert status == 403
            assert downstream_called is False


# ---------------------------------------------------------------------------
# Layer 2 — router-level require_esign_module dependency (R2.2)
# ---------------------------------------------------------------------------


class TestRouterDependencyGate:
    """``require_esign_module`` raises 403 when disabled, passes when enabled."""

    @pytest.mark.asyncio
    async def test_disabled_raises_403_module_disabled(self):
        org_id = uuid.uuid4()
        request = _make_request(org_id)
        db = AsyncMock()

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=False,
        ) as mock_is_enabled:
            with pytest.raises(HTTPException) as excinfo:
                await require_esign_module(request, db)

        assert excinfo.value.status_code == 403
        # Humanized { message, code } body with the module_disabled code.
        detail = excinfo.value.detail
        assert isinstance(detail, dict)
        assert detail["code"] == CODE_MODULE_DISABLED
        assert isinstance(detail["message"], str) and detail["message"]

        # Gated against the canonical slug + the request's org_id.
        mock_is_enabled.assert_awaited_once()
        call_args = mock_is_enabled.await_args.args
        assert call_args[0] == str(org_id)
        assert call_args[1] == "esignatures"

    @pytest.mark.asyncio
    async def test_enabled_returns_none(self):
        request = _make_request(uuid.uuid4())
        db = AsyncMock()

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await require_esign_module(request, db)

        assert result is None

    @pytest.mark.asyncio
    async def test_no_org_context_raises_401(self):
        request = _make_request(None)
        db = AsyncMock()

        # org-id resolution short-circuits before any is_enabled call.
        with pytest.raises(HTTPException) as excinfo:
            await require_esign_module(request, db)

        assert excinfo.value.status_code == 401
