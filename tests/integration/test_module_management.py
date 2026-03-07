"""Integration tests for module selection and dependency system.

**Validates: Requirements 6.3, 6.4, 6.5**

Tests:
- Enabling a module with dependencies auto-enables dependencies (5.9)
- Disabling a module that others depend on returns warning with dependent list (5.10)
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.core.modules import (
    CORE_MODULES,
    DEPENDENCY_GRAPH,
    ModuleService,
    get_all_dependencies,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_module_service() -> tuple[ModuleService, dict[str, bool]]:
    """Create a ModuleService with in-memory state (no real DB/Redis)."""
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

    return svc, enabled_modules


# ===========================================================================
# 5.9: Enabling a module with dependencies auto-enables dependencies
# ===========================================================================


class TestEnableModuleWithDependencies:
    """Enabling a module auto-enables its required dependencies.

    **Validates: Requirements 6.4, 6.5**
    """

    @pytest.mark.asyncio
    async def test_enable_pos_auto_enables_inventory(self):
        """POS requires inventory. Enabling POS should auto-enable inventory."""
        svc, state = _make_module_service()
        org_id = str(uuid.uuid4())

        additionally = await svc.enable_module(org_id, "pos")

        assert state.get("inventory") is True, "inventory should be auto-enabled"
        assert state.get("pos") is True, "pos should be enabled"
        assert "inventory" in additionally

    @pytest.mark.asyncio
    async def test_enable_kitchen_display_auto_enables_tables_and_pos_and_inventory(self):
        """kitchen_display requires tables + pos. pos requires inventory.
        All three should be auto-enabled."""
        svc, state = _make_module_service()
        org_id = str(uuid.uuid4())

        additionally = await svc.enable_module(org_id, "kitchen_display")

        assert state.get("tables") is True
        assert state.get("pos") is True
        assert state.get("inventory") is True  # transitive via pos
        assert state.get("kitchen_display") is True
        assert "tables" in additionally
        assert "pos" in additionally
        assert "inventory" in additionally

    @pytest.mark.asyncio
    async def test_enable_retentions_auto_enables_progress_claims_and_projects(self):
        """retentions → progress_claims → projects."""
        svc, state = _make_module_service()
        org_id = str(uuid.uuid4())

        additionally = await svc.enable_module(org_id, "retentions")

        assert state.get("progress_claims") is True
        assert state.get("projects") is True
        assert state.get("retentions") is True

    @pytest.mark.asyncio
    async def test_enable_module_with_deps_already_enabled(self):
        """If dependencies are already enabled, they are not in the
        additionally_enabled list."""
        svc, state = _make_module_service()
        org_id = str(uuid.uuid4())

        # Pre-enable inventory
        state["inventory"] = True

        additionally = await svc.enable_module(org_id, "pos")

        assert state.get("pos") is True
        assert "inventory" not in additionally  # was already enabled

    @pytest.mark.asyncio
    async def test_enable_staff_auto_enables_scheduling(self):
        """staff requires scheduling."""
        svc, state = _make_module_service()
        org_id = str(uuid.uuid4())

        additionally = await svc.enable_module(org_id, "staff")

        assert state.get("scheduling") is True
        assert state.get("staff") is True
        assert "scheduling" in additionally

    @pytest.mark.asyncio
    async def test_enable_ecommerce_auto_enables_inventory(self):
        """ecommerce requires inventory."""
        svc, state = _make_module_service()
        org_id = str(uuid.uuid4())

        additionally = await svc.enable_module(org_id, "ecommerce")

        assert state.get("inventory") is True
        assert state.get("ecommerce") is True


# ===========================================================================
# 5.10: Disabling a module that others depend on returns warning
# ===========================================================================


class TestDisableModuleWithDependents:
    """Disabling a module that other enabled modules depend on returns a
    warning with the dependent list.

    **Validates: Requirements 6.3**
    """

    @pytest.mark.asyncio
    async def test_disable_inventory_warns_about_pos(self):
        """If POS is enabled and depends on inventory, disabling inventory
        should return POS as a dependent."""
        svc, state = _make_module_service()
        org_id = str(uuid.uuid4())

        # Enable POS (which auto-enables inventory)
        await svc.enable_module(org_id, "pos")

        dependents = await svc.disable_module(org_id, "inventory")

        assert "pos" in dependents, (
            f"Expected 'pos' in dependents, got {dependents}"
        )

    @pytest.mark.asyncio
    async def test_disable_tables_warns_about_kitchen_display(self):
        """kitchen_display depends on tables. Disabling tables should warn."""
        svc, state = _make_module_service()
        org_id = str(uuid.uuid4())

        await svc.enable_module(org_id, "kitchen_display")

        dependents = await svc.disable_module(org_id, "tables")

        assert "kitchen_display" in dependents

    @pytest.mark.asyncio
    async def test_disable_projects_warns_about_progress_claims(self):
        """progress_claims depends on projects."""
        svc, state = _make_module_service()
        org_id = str(uuid.uuid4())

        await svc.enable_module(org_id, "progress_claims")

        dependents = await svc.disable_module(org_id, "projects")

        assert "progress_claims" in dependents

    @pytest.mark.asyncio
    async def test_disable_module_with_no_dependents_returns_empty(self):
        """Disabling a module with no enabled dependents returns empty list."""
        svc, state = _make_module_service()
        org_id = str(uuid.uuid4())

        # Enable only quotes (no other module depends on quotes)
        state["quotes"] = True

        dependents = await svc.disable_module(org_id, "quotes")

        assert dependents == []

    @pytest.mark.asyncio
    async def test_disable_inventory_warns_about_multiple_dependents(self):
        """If both POS and ecommerce are enabled, disabling inventory
        should list both as dependents."""
        svc, state = _make_module_service()
        org_id = str(uuid.uuid4())

        await svc.enable_module(org_id, "pos")
        await svc.enable_module(org_id, "ecommerce")

        dependents = await svc.disable_module(org_id, "inventory")

        assert "pos" in dependents
        assert "ecommerce" in dependents

    @pytest.mark.asyncio
    async def test_disable_progress_claims_warns_retentions_and_variations(self):
        """Both retentions and variations depend on progress_claims."""
        svc, state = _make_module_service()
        org_id = str(uuid.uuid4())

        await svc.enable_module(org_id, "retentions")
        await svc.enable_module(org_id, "variations")

        dependents = await svc.disable_module(org_id, "progress_claims")

        assert "retentions" in dependents
        assert "variations" in dependents

    @pytest.mark.asyncio
    async def test_core_module_disable_returns_empty(self):
        """Core modules cannot be disabled — returns empty dependents."""
        svc, state = _make_module_service()
        org_id = str(uuid.uuid4())

        dependents = await svc.disable_module(org_id, "invoicing")

        assert dependents == []
