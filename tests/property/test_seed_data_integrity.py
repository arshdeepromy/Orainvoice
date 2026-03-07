"""Property-based tests for seed data referential integrity.

Validates that seed data migrations maintain internal consistency:
- All trade categories reference valid trade family slugs
- All module dependencies reference valid module slugs

**Validates: Requirements 3.1, 3.4, 6.1, 6.5**

Uses Hypothesis to sample from the seed data and verify referential integrity
holds for every entry.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Helper to import migration modules with non-standard filenames
# ---------------------------------------------------------------------------

def _import_migration(filename: str, module_name: str):
    """Import an alembic migration file by path."""
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


families_migration = _import_migration(
    "2025_01_15_0018-0018_seed_trade_families.py",
    "_mig_0018_trade_families",
)
categories_migration = _import_migration(
    "2025_01_15_0019-0019_seed_trade_categories.py",
    "_mig_0019_trade_categories",
)
modules_migration = _import_migration(
    "2025_01_15_0021-0021_seed_module_registry.py",
    "_mig_0021_module_registry",
)

# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# ---------------------------------------------------------------------------
# Derived data for strategies
# ---------------------------------------------------------------------------

VALID_FAMILY_SLUGS = frozenset(f["slug"] for f in families_migration.TRADE_FAMILIES)
ALL_TRADE_CATEGORIES = categories_migration.TRADE_CATEGORIES
VALID_MODULE_SLUGS = frozenset(m["slug"] for m in modules_migration.MODULE_REGISTRY)
ALL_MODULES = modules_migration.MODULE_REGISTRY


# ===========================================================================
# Property Test 2.6: Trade categories reference valid trade families
# ===========================================================================


class TestTradeCategoryFamilyReferences:
    """Every trade category must reference a valid trade family slug.

    **Validates: Requirements 3.1, 3.4**
    """

    @given(
        category=st.sampled_from(ALL_TRADE_CATEGORIES),
    )
    @PBT_SETTINGS
    def test_trade_category_references_valid_family(self, category: dict) -> None:
        """For any trade category in the seed data, its family_slug must
        exist in the set of seeded trade family slugs."""
        family_slug = category["family_slug"]
        assert family_slug in VALID_FAMILY_SLUGS, (
            f"Trade category '{category['slug']}' references family "
            f"'{family_slug}' which is not in the seeded trade families: "
            f"{sorted(VALID_FAMILY_SLUGS)}"
        )

    @given(
        category=st.sampled_from(ALL_TRADE_CATEGORIES),
    )
    @PBT_SETTINGS
    def test_trade_category_has_required_fields(self, category: dict) -> None:
        """Every trade category must have all required fields populated."""
        assert category["slug"], f"Category missing slug"
        assert category["display_name"], f"Category '{category['slug']}' missing display_name"
        assert category["family_slug"], f"Category '{category['slug']}' missing family_slug"
        assert isinstance(category["recommended_modules"], list), (
            f"Category '{category['slug']}' recommended_modules must be a list"
        )
        assert isinstance(category["terminology_overrides"], dict), (
            f"Category '{category['slug']}' terminology_overrides must be a dict"
        )

    @given(
        category=st.sampled_from(ALL_TRADE_CATEGORIES),
    )
    @PBT_SETTINGS
    def test_trade_category_recommended_modules_are_valid(self, category: dict) -> None:
        """Every recommended module in a trade category must be a valid
        module slug from the module registry."""
        for mod_slug in category["recommended_modules"]:
            assert mod_slug in VALID_MODULE_SLUGS, (
                f"Trade category '{category['slug']}' recommends module "
                f"'{mod_slug}' which is not in the module registry: "
                f"{sorted(VALID_MODULE_SLUGS)}"
            )


# ===========================================================================
# Property Test 2.7: Module dependencies reference valid module slugs
# ===========================================================================


class TestModuleDependencyReferences:
    """Every module dependency must reference a valid module slug.

    **Validates: Requirements 6.1, 6.5**
    """

    @given(
        module=st.sampled_from(ALL_MODULES),
    )
    @PBT_SETTINGS
    def test_module_dependencies_reference_valid_slugs(self, module: dict) -> None:
        """For any module in the registry, each dependency slug must exist
        in the set of registered module slugs."""
        for dep_slug in module["dependencies"]:
            assert dep_slug in VALID_MODULE_SLUGS, (
                f"Module '{module['slug']}' depends on '{dep_slug}' which "
                f"is not in the module registry: {sorted(VALID_MODULE_SLUGS)}"
            )

    @given(
        module=st.sampled_from(ALL_MODULES),
    )
    @PBT_SETTINGS
    def test_module_has_required_fields(self, module: dict) -> None:
        """Every module must have all required fields populated."""
        assert module["slug"], f"Module missing slug"
        assert module["display_name"], f"Module '{module['slug']}' missing display_name"
        assert module["description"], f"Module '{module['slug']}' missing description"
        assert module["category"], f"Module '{module['slug']}' missing category"
        assert isinstance(module["is_core"], bool), (
            f"Module '{module['slug']}' is_core must be a boolean"
        )
        assert isinstance(module["dependencies"], list), (
            f"Module '{module['slug']}' dependencies must be a list"
        )

    @given(
        module=st.sampled_from(ALL_MODULES),
    )
    @PBT_SETTINGS
    def test_module_does_not_depend_on_itself(self, module: dict) -> None:
        """No module should list itself as a dependency."""
        assert module["slug"] not in module["dependencies"], (
            f"Module '{module['slug']}' has a circular self-dependency"
        )
