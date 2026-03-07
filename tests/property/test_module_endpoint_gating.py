"""Property-based test: disabled module endpoints return 403.

**Validates: Requirements 6.2, 6.6** — Property 1

For any org with module M disabled, all of M's endpoints return HTTP 403.
Uses Hypothesis to generate random module/endpoint combinations and verifies
the middleware correctly blocks access.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from hypothesis import given, settings as h_settings, HealthCheck
from hypothesis import strategies as st

from app.middleware.modules import MODULE_ENDPOINT_MAP, _resolve_module
from app.core.modules import CORE_MODULES


PBT_SETTINGS = h_settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# Non-core module endpoint prefixes (core modules are always enabled)
NON_CORE_ENDPOINTS = {
    prefix: slug
    for prefix, slug in MODULE_ENDPOINT_MAP.items()
    if slug not in CORE_MODULES
}

endpoint_strategy = st.sampled_from(list(NON_CORE_ENDPOINTS.keys()))
path_suffix_strategy = st.one_of(
    st.just(""),
    st.just("/"),
    st.just("/list"),
    st.just("/123"),
    st.just("/some-resource/456"),
)


class TestDisabledModuleEndpointGating:
    """For any org with module M disabled, all M's endpoints return 403.

    **Validates: Requirements 6.2, 6.6**
    """

    @given(
        endpoint_prefix=endpoint_strategy,
        path_suffix=path_suffix_strategy,
    )
    @PBT_SETTINGS
    def test_disabled_module_endpoint_returns_403(
        self, endpoint_prefix: str, path_suffix: str
    ) -> None:
        """Any request to a disabled module's endpoint prefix returns 403."""
        from starlette.testclient import TestClient
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        from app.middleware.modules import ModuleMiddleware

        full_path = endpoint_prefix + path_suffix
        module_slug = _resolve_module(full_path)
        assert module_slug is not None, f"Path {full_path} should resolve to a module"
        assert module_slug not in CORE_MODULES

        org_id = str(uuid.uuid4())

        # Build a minimal Starlette app with the middleware
        async def dummy_endpoint(request):
            return JSONResponse({"ok": True})

        app = Starlette(
            routes=[Route(full_path, dummy_endpoint, methods=["GET", "PUT", "POST"])],
        )
        app.add_middleware(ModuleMiddleware)

        # Mock the async_session_factory and ModuleService.is_enabled
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_begin = AsyncMock()
        mock_begin.__aenter__ = AsyncMock(return_value=mock_begin)
        mock_begin.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin = MagicMock(return_value=mock_begin)

        # Module is disabled
        async def fake_is_enabled(self_svc, oid, slug):
            return False

        with (
            patch(
                "app.middleware.modules.async_session_factory",
                return_value=mock_session,
            ),
            patch(
                "app.middleware.modules.ModuleService.is_enabled",
                fake_is_enabled,
            ),
        ):
            client = TestClient(app)
            # Simulate authenticated request with org_id
            # We need to set request.state.org_id — use a middleware-like approach
            # by patching the middleware's dispatch to inject state
            original_dispatch = ModuleMiddleware.dispatch

            async def patched_dispatch(self, request, call_next):
                request.state.org_id = org_id
                return await original_dispatch(self, request, call_next)

            with patch.object(ModuleMiddleware, "dispatch", patched_dispatch):
                response = client.get(full_path)

        assert response.status_code == 403, (
            f"Expected 403 for disabled module '{module_slug}' at {full_path}, "
            f"got {response.status_code}"
        )
        body = response.json()
        assert body["module"] == module_slug

    @given(endpoint_prefix=endpoint_strategy)
    @PBT_SETTINGS
    def test_resolve_module_maps_correctly(self, endpoint_prefix: str) -> None:
        """_resolve_module correctly maps every endpoint prefix to its slug."""
        expected_slug = NON_CORE_ENDPOINTS[endpoint_prefix]
        assert _resolve_module(endpoint_prefix) == expected_slug
        # Also with a sub-path
        assert _resolve_module(endpoint_prefix + "/sub") == expected_slug
