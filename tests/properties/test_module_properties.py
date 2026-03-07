"""Comprehensive property-based tests for module system properties.

Properties covered:
  P1  — Module Isolation: disabled module returns 403
  P10 — Module Dependency Integrity: enabled module's deps are also enabled

**Validates: Requirements 1, 10**
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.properties.conftest import PBT_SETTINGS

from app.middleware.modules import MODULE_ENDPOINT_MAP, _resolve_module
from app.core.modules import (
    CORE_MODULES,
    DEPENDENCY_GRAPH,
    ModuleService,
    get_all_dependencies,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

NON_CORE_ENDPOINTS = {
    prefix: slug
    for prefix, slug in MODULE_ENDPOINT_MAP.items()
    if slug not in CORE_MODULES
}

endpoint_strategy = st.sampled_from(list(NON_CORE_ENDPOINTS.keys()))
path_suffix_strategy = st.sampled_from(["", "/", "/list", "/123", "/sub/456"])

MODULES_WITH_DEPS = [slug for slug, deps in DEPENDENCY_GRAPH.items() if deps]
ALL_MODULE_SLUGS = list(
    set(DEPENDENCY_GRAPH.keys())
    | {dep for deps in DEPENDENCY_GRAPH.values() for dep in deps}
    | CORE_MODULES
)

module_with_deps_strategy = st.sampled_from(MODULES_WITH_DEPS)
any_module_strategy = st.sampled_from(ALL_MODULE_SLUGS)


# ===========================================================================
# Property 1: Module Isolation — disabled module returns 403
# ===========================================================================


class TestP1ModuleIsolation:
    """Disabled module endpoints return HTTP 403.

    **Validates: Requirements 1**
    """

    @given(endpoint_prefix=endpoint_strategy, path_suffix=path_suffix_strategy)
    @PBT_SETTINGS
    def test_disabled_module_returns_403(
        self, endpoint_prefix: str, path_suffix: str,
    ) -> None:
        """P1: any request to a disabled module's endpoint returns 403."""
        from starlette.testclient import TestClient
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        from app.middleware.modules import ModuleMiddleware

        full_path = endpoint_prefix + path_suffix
        module_slug = _resolve_module(full_path)
        assert module_slug is not None
        assert module_slug not in CORE_MODULES

        org_id = str(uuid.uuid4())

        async def dummy_endpoint(request):
            return JSONResponse({"ok": True})

        app = Starlette(
            routes=[Route(full_path, dummy_endpoint, methods=["GET", "POST"])],
        )
        app.add_middleware(ModuleMiddleware)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_begin = AsyncMock()
        mock_begin.__aenter__ = AsyncMock(return_value=mock_begin)
        mock_begin.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin = MagicMock(return_value=mock_begin)

        async def fake_is_enabled(self_svc, oid, slug):
            return False

        with (
            patch("app.middleware.modules.async_session_factory", return_value=mock_session),
            patch("app.middleware.modules.ModuleService.is_enabled", fake_is_enabled),
        ):
            original_dispatch = ModuleMiddleware.dispatch

            async def patched_dispatch(self, request, call_next):
                request.state.org_id = org_id
                return await original_dispatch(self, request, call_next)

            with patch.object(ModuleMiddleware, "dispatch", patched_dispatch):
                client = TestClient(app)
                response = client.get(full_path)

        assert response.status_code == 403
        assert response.json()["module"] == module_slug

    @given(endpoint_prefix=endpoint_strategy)
    @PBT_SETTINGS
    def test_resolve_module_maps_correctly(self, endpoint_prefix: str) -> None:
        """P1: _resolve_module maps every prefix to its slug."""
        expected = NON_CORE_ENDPOINTS[endpoint_prefix]
        assert _resolve_module(endpoint_prefix) == expected
        assert _resolve_module(endpoint_prefix + "/sub") == expected


# ===========================================================================
# Property 10: Module Dependency Integrity
# ===========================================================================


class TestP10ModuleDependencyIntegrity:
    """If module M is enabled and has deps, all deps are also enabled.

    **Validates: Requirements 10**
    """

    @given(module_slug=module_with_deps_strategy)
    @PBT_SETTINGS
    def test_enable_module_enables_all_dependencies(self, module_slug: str) -> None:
        """P10: after enable_module(M), all transitive deps are enabled."""
        import asyncio

        org_id = str(uuid.uuid4())
        enabled_modules: dict[str, bool] = {}

        async def fake_set_enabled(oid, slug, enabled, enabled_by):
            enabled_modules[slug] = enabled

        async def fake_is_enabled(oid, slug):
            if slug in CORE_MODULES:
                return True
            return enabled_modules.get(slug, False)

        async def fake_invalidate(oid):
            pass

        mock_db = AsyncMock()
        svc = ModuleService(mock_db)
        svc._set_enabled = fake_set_enabled
        svc.is_enabled = fake_is_enabled
        svc._invalidate_cache = fake_invalidate

        asyncio.run(svc.enable_module(org_id, module_slug))

        all_deps = get_all_dependencies(module_slug)
        for dep in all_deps:
            if dep not in CORE_MODULES:
                assert enabled_modules.get(dep, False), (
                    f"Dependency '{dep}' of '{module_slug}' not enabled"
                )
        assert enabled_modules.get(module_slug, False)

    @given(
        modules=st.lists(any_module_strategy, min_size=1, max_size=5, unique=True),
    )
    @PBT_SETTINGS
    def test_enabling_multiple_maintains_invariant(self, modules: list[str]) -> None:
        """P10: enabling multiple modules maintains dependency invariant."""
        import asyncio

        org_id = str(uuid.uuid4())
        enabled_modules: dict[str, bool] = {}

        async def fake_set_enabled(oid, slug, enabled, enabled_by):
            enabled_modules[slug] = enabled

        async def fake_is_enabled(oid, slug):
            if slug in CORE_MODULES:
                return True
            return enabled_modules.get(slug, False)

        async def fake_invalidate(oid):
            pass

        mock_db = AsyncMock()
        svc = ModuleService(mock_db)
        svc._set_enabled = fake_set_enabled
        svc.is_enabled = fake_is_enabled
        svc._invalidate_cache = fake_invalidate

        async def _run_all():
            for mod in modules:
                await svc.enable_module(org_id, mod)

        asyncio.run(_run_all())

        for mod, is_on in enabled_modules.items():
            if is_on:
                deps = DEPENDENCY_GRAPH.get(mod, [])
                for dep in deps:
                    if dep not in CORE_MODULES:
                        assert enabled_modules.get(dep, False)
