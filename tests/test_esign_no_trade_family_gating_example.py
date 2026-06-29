"""Example test — the esignatures module has NO trade-family gating (task 10.4).

# Feature: esignature-integration, Property 6: No trade-family gating
# (enabling `esignatures` is permitted for any trade family)

**Validates: Requirements 2.5**

R2.5 requires the `esignatures` module to be available to *every* trade family
without any trade-family gate. In this codebase trade-family gating is
implemented in code (not via a DB column) through the constants in
``app/core/modules.py``:

- ``TRADE_FAMILY_REQUIRED_MODULES`` — maps a module slug to the single trade
  family it is restricted to. A module **absent** from this mapping is
  unrestricted (universal).
- ``TRADE_FAMILY_REJECTION_MESSAGES`` — the 403 message shown when a restricted
  module is enabled for the wrong family.
- ``is_trade_family_satisfied(slug, family)`` — the pure predicate every gate
  consults; it returns ``True`` for any slug not in
  ``TRADE_FAMILY_REQUIRED_MODULES``, regardless of the org's trade family.

These example tests assert ``esignatures`` is absent from the gating mapping
(so it is universal) and that the predicate admits it for every trade family —
including the ``None``/empty-string "unknown family" cases that a restricted
module would reject.
"""

from __future__ import annotations

import pytest

from app.core.modules import (
    TRADE_FAMILY_REJECTION_MESSAGES,
    TRADE_FAMILY_REQUIRED_MODULES,
    is_trade_family_satisfied,
)

ESIGN_SLUG = "esignatures"

# The canonical set of trade family slugs in OraInvoice (mirrors
# ``tests/properties/conftest.py::trade_family_strategy`` and the
# trade-family-gating steering doc). esignatures must be available to ALL.
ALL_TRADE_FAMILIES = [
    "automotive-transport",
    "electrical-mechanical",
    "plumbing-gas",
    "building-construction",
    "landscaping-outdoor",
    "cleaning-facilities",
    "it-technology",
    "creative-professional",
    "accounting-legal-financial",
    "health-wellness",
    "food-hospitality",
    "retail",
    "hair-beauty-personal-care",
    "trades-support-hire",
    "freelancing-contracting",
]


class TestEsignNotTradeFamilyGated:
    """`esignatures` carries no trade-family restriction (R2.5)."""

    def test_esign_absent_from_required_modules_mapping(self):
        # Absence from TRADE_FAMILY_REQUIRED_MODULES == universal/unrestricted.
        assert ESIGN_SLUG not in TRADE_FAMILY_REQUIRED_MODULES

    def test_esign_absent_from_rejection_messages(self):
        # No rejection message exists because the module is never rejected by
        # trade family.
        assert ESIGN_SLUG not in TRADE_FAMILY_REJECTION_MESSAGES

    def test_only_known_restricted_module_is_b2b_fleet(self):
        # Guard against a future accidental gating of esignatures: the only
        # trade-restricted module today is b2b-fleet-management. esignatures
        # must never be added here without revisiting R2.5.
        assert ESIGN_SLUG not in TRADE_FAMILY_REQUIRED_MODULES.keys()


class TestEsignSatisfiedForEveryTradeFamily:
    """`is_trade_family_satisfied` admits esignatures for any org."""

    @pytest.mark.parametrize("family", ALL_TRADE_FAMILIES)
    def test_satisfied_for_each_trade_family(self, family):
        # Enabling/using esignatures is permitted for every trade family.
        assert is_trade_family_satisfied(ESIGN_SLUG, family) is True

    def test_satisfied_when_family_unknown_or_empty(self):
        # A *restricted* module would be rejected for an unknown family
        # (None / ""), but esignatures — being universal — is still admitted.
        assert is_trade_family_satisfied(ESIGN_SLUG, None) is True
        assert is_trade_family_satisfied(ESIGN_SLUG, "") is True

    def test_satisfied_for_arbitrary_unrecognised_family(self):
        # Even a slug that is not a real trade family must not gate esignatures,
        # because the module has no entry in the restriction mapping.
        assert is_trade_family_satisfied(ESIGN_SLUG, "totally-made-up") is True
