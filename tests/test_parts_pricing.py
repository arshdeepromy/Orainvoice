"""Unit tests for _compute_pricing() edge cases.

Tests cover:
  - Known-value cost-per-unit calculation
  - Zero/None input handling (returns None)
  - Margin and margin_pct calculation
  - sell_price_per_unit=0 edge case

Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.catalogue.service import _compute_pricing


# ---------------------------------------------------------------------------
# Cost-per-unit known values
# ---------------------------------------------------------------------------


class TestCostPerUnitKnownValues:
    """Verify cost_per_unit with deterministic inputs."""

    def test_known_value_100_10_2(self) -> None:
        """purchase_price=100, qty_per_pack=10, total_packs=2 → cost_per_unit=5.00"""
        cost, _margin, _margin_pct = _compute_pricing(
            Decimal("100"), 10, 2, None,
        )
        assert cost == Decimal("100") / Decimal("20")
        assert cost == Decimal("5")


# ---------------------------------------------------------------------------
# None / zero input handling
# ---------------------------------------------------------------------------


class TestNoneAndZeroInputs:
    """When inputs are missing or zero, derived fields must be None."""

    def test_zero_qty_per_pack_returns_none(self) -> None:
        cost, margin, margin_pct = _compute_pricing(
            Decimal("100"), 0, 2, Decimal("10"),
        )
        assert cost is None
        assert margin is None
        assert margin_pct is None

    def test_zero_total_packs_returns_none(self) -> None:
        cost, margin, margin_pct = _compute_pricing(
            Decimal("100"), 10, 0, Decimal("10"),
        )
        assert cost is None
        assert margin is None
        assert margin_pct is None

    def test_none_purchase_price_returns_none(self) -> None:
        cost, margin, margin_pct = _compute_pricing(
            None, 10, 2, Decimal("10"),
        )
        assert cost is None
        assert margin is None
        assert margin_pct is None


# ---------------------------------------------------------------------------
# Margin calculation
# ---------------------------------------------------------------------------


class TestMarginCalculation:
    """Verify margin and margin_pct with known values."""

    def test_margin_sell_10_cost_5(self) -> None:
        """sell=10, cost=5 → margin=5, margin_pct=50"""
        cost, margin, margin_pct = _compute_pricing(
            Decimal("100"), 10, 2, Decimal("10"),
        )
        # cost_per_unit = 100 / (10*2) = 5
        assert cost == Decimal("5")
        assert margin == Decimal("5")
        expected_pct = (Decimal("5") / Decimal("10")) * Decimal("100")
        assert margin_pct == expected_pct

    def test_sell_price_zero_margin_pct_zero(self) -> None:
        """sell_price_per_unit=0 → margin_pct=0.00"""
        cost, margin, margin_pct = _compute_pricing(
            Decimal("100"), 10, 2, Decimal("0"),
        )
        assert cost == Decimal("5")
        assert margin == Decimal("0") - Decimal("5")
        assert margin_pct == Decimal("0.00")


# ---------------------------------------------------------------------------
# API schema validation tests — Requirements: 7.1, 7.2, 7.3, 7.5, 7.6
# ---------------------------------------------------------------------------

from pydantic import ValidationError

from app.modules.catalogue.schemas import PartCreateRequest, PartResponse
from app.modules.catalogue.router import ALLOWED_PACKAGING_TYPES


class TestPartCreateRequestSchema:
    """Verify PartCreateRequest accepts and validates pricing fields."""

    def test_create_request_with_all_pricing_fields(self) -> None:
        """PartCreateRequest with all pricing fields → fields are set correctly.

        Requirements: 7.1
        """
        req = PartCreateRequest(
            name="Brake Pad",
            default_price="29.95",
            purchase_price="200.00",
            packaging_type="box",
            qty_per_pack=10,
            total_packs=2,
            sell_price_per_unit="15.00",
            gst_mode="inclusive",
        )
        assert req.name == "Brake Pad"
        assert req.purchase_price == "200.00"
        assert req.packaging_type == "box"
        assert req.qty_per_pack == 10
        assert req.total_packs == 2
        assert req.sell_price_per_unit == "15.00"
        assert req.gst_mode == "inclusive"

    def test_create_request_qty_per_pack_zero_raises(self) -> None:
        """qty_per_pack=0 violates ge=1 constraint → ValidationError.

        Requirements: 7.5
        """
        with pytest.raises(ValidationError) as exc_info:
            PartCreateRequest(
                name="Spark Plug",
                default_price="5.00",
                qty_per_pack=0,
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("qty_per_pack",) for e in errors)

    def test_create_request_total_packs_zero_raises(self) -> None:
        """total_packs=0 violates ge=1 constraint → ValidationError.

        Requirements: 7.5
        """
        with pytest.raises(ValidationError) as exc_info:
            PartCreateRequest(
                name="Oil Filter",
                default_price="12.00",
                total_packs=0,
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("total_packs",) for e in errors)


class TestAllowedPackagingTypes:
    """Verify the ALLOWED_PACKAGING_TYPES constant.

    Requirements: 7.6
    """

    def test_allowed_set_contains_expected_values(self) -> None:
        expected = {"box", "carton", "pack", "bag", "pallet", "single"}
        assert ALLOWED_PACKAGING_TYPES == expected

    def test_invalid_type_not_in_allowed(self) -> None:
        assert "crate" not in ALLOWED_PACKAGING_TYPES
        assert "" not in ALLOWED_PACKAGING_TYPES


class TestPartResponseSchema:
    """Verify PartResponse can be constructed with all 9 pricing fields.

    Requirements: 7.3
    """

    def test_response_with_all_pricing_fields(self) -> None:
        resp = PartResponse(
            id="00000000-0000-0000-0000-000000000001",
            name="Brake Pad",
            default_price="29.95",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            purchase_price="200.00",
            packaging_type="box",
            qty_per_pack=10,
            total_packs=2,
            cost_per_unit="10.00",
            sell_price_per_unit="15.00",
            margin="5.00",
            margin_pct="33.33",
            gst_mode="inclusive",
        )
        assert resp.purchase_price == "200.00"
        assert resp.packaging_type == "box"
        assert resp.qty_per_pack == 10
        assert resp.total_packs == 2
        assert resp.cost_per_unit == "10.00"
        assert resp.sell_price_per_unit == "15.00"
        assert resp.margin == "5.00"
        assert resp.margin_pct == "33.33"
        assert resp.gst_mode == "inclusive"

    def test_response_with_none_pricing_fields(self) -> None:
        """All pricing fields default to None when not provided."""
        resp = PartResponse(
            id="00000000-0000-0000-0000-000000000002",
            name="Generic Part",
            default_price="10.00",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
        assert resp.purchase_price is None
        assert resp.packaging_type is None
        assert resp.qty_per_pack is None
        assert resp.total_packs is None
        assert resp.cost_per_unit is None
        assert resp.sell_price_per_unit is None
        assert resp.margin is None
        assert resp.margin_pct is None
        assert resp.gst_mode is None


# ---------------------------------------------------------------------------
# GST legacy boolean mapping — Requirements: 4.3, 4.4, 4.5, 4.6
# ---------------------------------------------------------------------------

from app.modules.catalogue.service import _map_gst_legacy


class TestGstLegacyMapping:
    """Verify _map_gst_legacy maps boolean pairs to the correct gst_mode string."""

    def test_exempt_when_gst_exempt_true(self) -> None:
        """is_gst_exempt=True, gst_inclusive=False → 'exempt'.

        Requirements: 4.4
        """
        assert _map_gst_legacy(True, False) == "exempt"

    def test_inclusive_when_not_exempt_and_inclusive(self) -> None:
        """is_gst_exempt=False, gst_inclusive=True → 'inclusive'.

        Requirements: 4.5
        """
        assert _map_gst_legacy(False, True) == "inclusive"

    def test_exclusive_when_both_false(self) -> None:
        """is_gst_exempt=False, gst_inclusive=False → 'exclusive'.

        Requirements: 4.6
        """
        assert _map_gst_legacy(False, False) == "exclusive"
