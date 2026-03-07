"""Property-based test: module dependency invariant.

**Validates: Requirements 6.4** — Property 10

For any org, if module M is enabled and has dependencies [D1, D2], then
D1 and D2 are also enabled after calling enable_module().

Uses Hypothesis to generate random module selections and verifies the
dependency invariant holds across all inputs.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings as h_settings, HealthCheck, assume
from hypothesis import strategies as st

from app.core.modules import (
    DEPENDENCY_GRAPH,
    CORE_MODULES,
    ModuleService,
    get_all_dependencies,
)


PBT_SETTINGS = h_settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# All module slugs that have dependencies
MODULES_WITH_DEPS = [slug for slug, deps in DEPENDENCY_GRAPH.items() if deps]

# All known module slugs from the dependency graph (both keys and values)
ALL_MODULE_SLUGS = list(
    set(DEPENDENCY_GRAPH.keys())
    | {dep for deps in DEPENDENCY_GRAPH.values() for dep in deps}
    | CORE_MODULES
)

module_slug_strategy = st.sampled_from(MODULES_WITH_DEPS)


class TestModuleDependencyInvariant:
    """For any org, if module M is enabled and has dependencies, then all
    dependencies are also enabled.

    **Validates: Requirements 6.4**
    """

    @given(module_slug=module_slug_strategy)
    @PBT_SETTINGS
    def test_enable_module_enables_all_dependencies(self, module_slug: str) -> None:
        """After enable_module(M), every transitive dependency of M is enabled."""
        import asyncio

        org_id = str(uuid.uuid4())
        enabled_modules: dict[str, bool] = {}

        # Mock DB session
        mock_db = AsyncMock()

        # Track what gets enabled via _set_enabled
        async def fake_set_enabled(oid, slug, enabled, enabled_by):
            enabled_modules[slug] = enabled

        # is_enabled checks our in-memory state
        async def fake_is_enabled(oid, slug):
            if slug in CORE_MODULES:
                return True
            return enabled_modules.get(slug, False)

        # No-op cache invalidation
        async def fake_invalidate(oid):
            pass

        svc = ModuleService(mock_db)
        svc._set_enabled = fake_set_enabled
        svc.is_enabled = fake_is_enabled
        svc._invalidate_cache = fake_invalidate

        # Enable the module
        additionally_enabled = asyncio.get_event_loop().run_until_complete(
            svc.enable_module(org_id, module_slug)
        )

        # Verify: all transitive dependencies must be enabled
        all_deps = get_all_dependencies(module_slug)
        for dep in all_deps:
            if dep not in CORE_MODULES:
                assert enabled_modules.get(dep, False), (
                    f"Dependency '{dep}' of module '{module_slug}' was not enabled. "
                    f"Enabled modules: {enabled_modules}"
                )

        # The module itself must be enabled
        assert enabled_modules.get(module_slug, False), (
            f"Module '{module_slug}' itself was not enabled"
        )

    @given(
        modules=st.lists(
            st.sampled_from(ALL_MODULE_SLUGS),
            min_size=1,
            max_size=5,
            unique=True,
        )
    )
    @PBT_SETTINGS
    def test_enabling_multiple_modules_maintains_invariant(
        self, modules: list[str]
    ) -> None:
        """Enabling multiple modules in sequence maintains the dependency
        invariant: every enabled module's deps are also enabled."""
        import asyncio

        org_id = str(uuid.uuid4())
        enabled_modules: dict[str, bool] = {}

        mock_db = AsyncMock()

        async def fake_set_enabled(oid, slug, enabled, enabled_by):
            enabled_modules[slug] = enabled

        async def fake_is_enabled(oid, slug):
            if slug in CORE_MODULES:
                return True
            return enabled_modules.get(slug, False)

        async def fake_invalidate(oid):
            pass

        svc = ModuleService(mock_db)
        svc._set_enabled = fake_set_enabled
        svc.is_enabled = fake_is_enabled
        svc._invalidate_cache = fake_invalidate

        # Enable all modules in sequence
        for mod in modules:
            asyncio.get_event_loop().run_until_complete(
                svc.enable_module(org_id, mod)
            )

        # Verify invariant: for every enabled module, all its deps are enabled
        for mod, is_on in enabled_modules.items():
            if is_on:
                deps = DEPENDENCY_GRAPH.get(mod, [])
                for dep in deps:
                    if dep not in CORE_MODULES:
                        assert enabled_modules.get(dep, False), (
                            f"Module '{mod}' is enabled but dependency '{dep}' is not. "
                            f"State: {enabled_modules}"
                        )
