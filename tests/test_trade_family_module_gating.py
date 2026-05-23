"""Unit tests for trade-family-restricted module gating (task 1.3 of
b2b-fleet-portal).

Covers the new pure helpers added in ``app/core/modules.py`` and
``app/modules/setup_guide/router.py``:

- ``is_trade_family_satisfied(slug, org_trade_family)``
- ``trade_gated_modules_for_org(org_trade_family)``

And the integration of those helpers into the module list, enable
endpoint, and setup-guide question generator.

**Validates: Requirements 1.2, 1.3, 1.4** (b2b-fleet-portal spec)

The full property tests for trade-family gating live in
``tests/fleet_portal/test_module_gating_property.py`` (task 3.9).
This file provides example-based smoke coverage for task 1.3.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.modules import (
    DEPENDENCY_GRAPH,
    TRADE_FAMILY_REJECTION_MESSAGES,
    TRADE_FAMILY_REQUIRED_MODULES,
    is_trade_family_satisfied,
)
from app.modules.setup_guide.router import (
    TRADE_GATED_MODULES,
    filter_eligible_modules,
    trade_gated_modules_for_org,
)


# ---------------------------------------------------------------------------
# Lightweight module stub mirroring ``ModuleRegistry``
# ---------------------------------------------------------------------------


@dataclass
class ModuleStub:
    slug: str
    is_core: bool = False
    setup_question: str | None = None
    display_name: str = ""
    setup_question_description: str | None = None
    category: str | None = "general"
    dependencies: list[str] = field(default_factory=list)
    status: str = "available"


# ---------------------------------------------------------------------------
# Constants — sanity check the registry
# ---------------------------------------------------------------------------


class TestConstants:
    """Sanity checks: the new constants are wired up correctly."""

    def test_b2b_fleet_management_required_family_is_automotive_transport(self):
        """Validates: Requirement 1.3 — the trade-family restriction is
        ``automotive-transport`` for ``b2b-fleet-management``."""
        assert (
            TRADE_FAMILY_REQUIRED_MODULES["b2b-fleet-management"]
            == "automotive-transport"
        )

    def test_b2b_fleet_management_dependency_is_vehicles(self):
        """Validates: Requirement 1.4 — enabling ``b2b-fleet-management``
        auto-enables ``vehicles`` via ``DEPENDENCY_GRAPH``."""
        assert DEPENDENCY_GRAPH["b2b-fleet-management"] == ["vehicles"]

    def test_b2b_fleet_management_rejection_message_matches_spec(self):
        """The 403 rejection message must be the exact wording in
        Requirement 1.3."""
        assert TRADE_FAMILY_REJECTION_MESSAGES["b2b-fleet-management"] == (
            "B2B Fleet Management is available only for automotive and "
            "transport organisations"
        )


# ---------------------------------------------------------------------------
# is_trade_family_satisfied
# ---------------------------------------------------------------------------


class TestIsTradeFamilySatisfied:
    """Pure-function predicate for trade-family gating."""

    def test_unrestricted_module_always_satisfied(self):
        # Any module not in TRADE_FAMILY_REQUIRED_MODULES — e.g. ``invoicing``,
        # ``customers``, ``inventory`` — is always satisfied regardless of
        # the org's trade family (or absence thereof).
        assert is_trade_family_satisfied("invoicing", None) is True
        assert is_trade_family_satisfied("inventory", "automotive-transport") is True
        assert is_trade_family_satisfied("inventory", "construction") is True

    def test_restricted_module_satisfied_when_family_matches(self):
        # Validates: Requirement 1.2 — for matching orgs the restricted
        # module SHALL be visible.
        assert (
            is_trade_family_satisfied(
                "b2b-fleet-management", "automotive-transport"
            )
            is True
        )

    def test_restricted_module_not_satisfied_when_family_differs(self):
        # Validates: Requirement 1.2 — for non-matching orgs the
        # restricted module SHALL be hidden.
        assert (
            is_trade_family_satisfied("b2b-fleet-management", "construction")
            is False
        )
        assert (
            is_trade_family_satisfied("b2b-fleet-management", "plumbing-gas")
            is False
        )

    def test_restricted_module_not_satisfied_when_family_unknown(self):
        # Defence-in-depth: an org with no resolvable trade family should
        # never see a restricted module.
        assert is_trade_family_satisfied("b2b-fleet-management", None) is False

    def test_restricted_module_not_satisfied_for_empty_string(self):
        assert is_trade_family_satisfied("b2b-fleet-management", "") is False


# ---------------------------------------------------------------------------
# trade_gated_modules_for_org
# ---------------------------------------------------------------------------


class TestTradeGatedModulesForOrg:
    """Per-org trade-gated set used by the setup guide."""

    def test_baseline_set_always_included(self):
        # ``vehicles`` is auto-enabled by trade family and so is always
        # excluded from the setup guide regardless of the org's family.
        for family in (None, "construction", "automotive-transport"):
            gated = trade_gated_modules_for_org(family)
            assert (
                "vehicles" in gated
            ), f"vehicles should always be gated (family={family})"

    def test_b2b_fleet_management_excluded_for_non_matching_family(self):
        # Validates: Requirement 1.2 — non-matching org → restricted module
        # is excluded from the guide.
        gated = trade_gated_modules_for_org("construction")
        assert "b2b-fleet-management" in gated

    def test_b2b_fleet_management_excluded_when_family_unknown(self):
        gated = trade_gated_modules_for_org(None)
        assert "b2b-fleet-management" in gated

    def test_b2b_fleet_management_included_for_matching_family(self):
        # Validates: Requirement 1.2 — for matching org the restricted
        # module is NOT in the gated set, so it is eligible to appear as
        # a setup-guide question.
        gated = trade_gated_modules_for_org("automotive-transport")
        assert "b2b-fleet-management" not in gated

    def test_baseline_TRADE_GATED_MODULES_remain(self):
        # The function must not drop any baseline gated slug.
        gated = trade_gated_modules_for_org("automotive-transport")
        assert TRADE_GATED_MODULES <= gated


# ---------------------------------------------------------------------------
# Setup guide filtering — smoke verification per task 1.3
# ---------------------------------------------------------------------------


def _registry_with_b2b_fleet() -> list[ModuleStub]:
    """Realistic registry slice that includes the new module."""
    return [
        # Core modules — never appear
        ModuleStub(slug="invoicing", is_core=True, setup_question=None),
        ModuleStub(slug="customers", is_core=True, setup_question=None),
        # Trade-auto-gated — never appears
        ModuleStub(slug="vehicles", setup_question="Do you manage vehicles?"),
        # Optional — should appear for any org with the right plan
        ModuleStub(slug="quotes", setup_question="Will you be sending quotes?"),
        # New trade-family-restricted module
        ModuleStub(
            slug="b2b-fleet-management",
            display_name="B2B Fleet Management",
            setup_question=(
                "Do your business customers need a self-service portal "
                "to manage their vehicle fleet?"
            ),
            setup_question_description=(
                "Let fleet operators log in to view vehicles, invite "
                "drivers, run NZTA pre-trip checklists, book services, "
                "request quotes, and manage WOF/COF reminders."
            ),
            category="fleet_management",
            dependencies=["vehicles"],
        ),
    ]


class TestSetupGuideFilteringWithTradeFamily:
    """End-to-end smoke verification of task 1.3.

    Mirrors the smoke check in tasks.md:
        GET /api/v2/setup-guide/questions for an automotive-transport org
        with the module not yet enabled — the b2b-fleet-management question
        SHALL appear with the correct text. For a non-automotive org, it
        SHALL be absent.
    """

    def test_question_appears_for_automotive_transport_org(self):
        """Validates: Requirements 1.2 and the smoke check in task 1.3."""
        registry = _registry_with_b2b_fleet()
        plan_modules = {"all"}

        gated = trade_gated_modules_for_org("automotive-transport")
        eligible = filter_eligible_modules(registry, plan_modules, gated)
        slugs = {m.slug for m in eligible}

        assert "b2b-fleet-management" in slugs

        b2b = next(m for m in eligible if m.slug == "b2b-fleet-management")
        assert b2b.setup_question == (
            "Do your business customers need a self-service portal "
            "to manage their vehicle fleet?"
        )

    def test_question_absent_for_non_automotive_org(self):
        """Validates: Requirement 1.2 and the smoke check in task 1.3."""
        registry = _registry_with_b2b_fleet()
        plan_modules = {"all"}

        for family in ("construction", "plumbing-gas", "electrical", None):
            gated = trade_gated_modules_for_org(family)
            eligible = filter_eligible_modules(registry, plan_modules, gated)
            slugs = {m.slug for m in eligible}
            assert (
                "b2b-fleet-management" not in slugs
            ), f"should be absent for trade_family={family!r}"

    def test_other_modules_unaffected_by_gating(self):
        """The new gating must not change which other modules are eligible."""
        registry = _registry_with_b2b_fleet()
        plan_modules = {"all"}

        gated_auto = trade_gated_modules_for_org("automotive-transport")
        gated_other = trade_gated_modules_for_org("construction")

        eligible_auto = {m.slug for m in filter_eligible_modules(registry, plan_modules, gated_auto)}
        eligible_other = {m.slug for m in filter_eligible_modules(registry, plan_modules, gated_other)}

        # The only difference between the two eligible sets must be the
        # restricted module itself.
        assert eligible_auto - eligible_other == {"b2b-fleet-management"}
        assert eligible_other - eligible_auto == set()

        # ``quotes`` is in both; ``vehicles`` and ``invoicing`` are in neither.
        assert "quotes" in eligible_auto
        assert "quotes" in eligible_other
        assert "vehicles" not in eligible_auto
        assert "invoicing" not in eligible_auto
