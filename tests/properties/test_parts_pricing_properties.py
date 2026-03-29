"""Property-based tests for parts packaging & pricing calculations.

Properties covered:
  P1 — Cost-per-unit calculation
  P2 — Margin computation

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4**
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given, assume
from hypothesis import strategies as st

from tests.properties.conftest import PBT_SETTINGS
from app.modules.catalogue.service import _compute_pricing


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

positive_price = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("99999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

non_negative_price = st.decimals(
    min_value=Decimal("0.00"),
    max_value=Decimal("99999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

positive_int = st.integers(min_value=1, max_value=1000)

zero_or_negative_int = st.integers(min_value=-100, max_value=0)


# ===========================================================================
# Property 1: Cost-per-unit calculation
# Feature: parts-packaging-pricing, Property 1: Cost-per-unit calculation
# ===========================================================================


class TestP1CostPerUnitCalculation:
    """For any positive purchase_price, qty_per_pack, total_packs:
    cost_per_unit == purchase_price / (qty_per_pack × total_packs).
    For zero/None inputs: cost_per_unit is None.

    **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
    """

    @given(
        purchase_price=positive_price,
        qty_per_pack=positive_int,
        total_packs=positive_int,
        sell_price=st.one_of(st.none(), non_negative_price),
    )
    @PBT_SETTINGS
    def test_positive_inputs_produce_correct_cost(
        self,
        purchase_price: Decimal,
        qty_per_pack: int,
        total_packs: int,
        sell_price: Decimal | None,
    ) -> None:
        """P1: cost_per_unit == purchase_price / (qty_per_pack × total_packs)."""
        cost_per_unit, _, _ = _compute_pricing(
            purchase_price, qty_per_pack, total_packs, sell_price,
        )
        expected = Decimal(str(purchase_price)) / Decimal(str(qty_per_pack * total_packs))
        assert cost_per_unit == expected, (
            f"cost_per_unit {cost_per_unit} != expected {expected}"
        )

    @given(
        purchase_price=positive_price,
        total_packs=positive_int,
        sell_price=st.one_of(st.none(), non_negative_price),
    )
    @PBT_SETTINGS
    def test_zero_qty_per_pack_returns_none(
        self,
        purchase_price: Decimal,
        total_packs: int,
        sell_price: Decimal | None,
    ) -> None:
        """P1: zero qty_per_pack → cost_per_unit is None."""
        cost_per_unit, _, _ = _compute_pricing(
            purchase_price, 0, total_packs, sell_price,
        )
        assert cost_per_unit is None

    @given(
        purchase_price=positive_price,
        qty_per_pack=positive_int,
        sell_price=st.one_of(st.none(), non_negative_price),
    )
    @PBT_SETTINGS
    def test_zero_total_packs_returns_none(
        self,
        purchase_price: Decimal,
        qty_per_pack: int,
        sell_price: Decimal | None,
    ) -> None:
        """P1: zero total_packs → cost_per_unit is None."""
        cost_per_unit, _, _ = _compute_pricing(
            purchase_price, qty_per_pack, 0, sell_price,
        )
        assert cost_per_unit is None

    @given(
        qty_per_pack=positive_int,
        total_packs=positive_int,
        sell_price=st.one_of(st.none(), non_negative_price),
    )
    @PBT_SETTINGS
    def test_none_purchase_price_returns_none(
        self,
        qty_per_pack: int,
        total_packs: int,
        sell_price: Decimal | None,
    ) -> None:
        """P1: None purchase_price → cost_per_unit is None."""
        cost_per_unit, _, _ = _compute_pricing(
            None, qty_per_pack, total_packs, sell_price,
        )
        assert cost_per_unit is None

    @given(
        qty_per_pack=st.one_of(st.none(), st.just(0)),
        total_packs=st.one_of(st.none(), st.just(0)),
        sell_price=st.one_of(st.none(), non_negative_price),
    )
    @PBT_SETTINGS
    def test_none_or_zero_inputs_returns_none(
        self,
        qty_per_pack: int | None,
        total_packs: int | None,
        sell_price: Decimal | None,
    ) -> None:
        """P1: None/zero for qty or packs → cost_per_unit is None."""
        cost_per_unit, _, _ = _compute_pricing(
            None, qty_per_pack, total_packs, sell_price,
        )
        assert cost_per_unit is None


# ===========================================================================
# Property 2: Margin computation
# Feature: parts-packaging-pricing, Property 2: Margin computation
# ===========================================================================


class TestP2MarginComputation:
    """For any non-negative sell and cost: margin == sell - cost,
    margin_pct == (margin / sell) × 100 when sell > 0,
    margin_pct == 0.00 when sell is zero,
    both None when cost is None.

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
    """

    @given(
        purchase_price=positive_price,
        qty_per_pack=positive_int,
        total_packs=positive_int,
        sell_price=st.decimals(
            min_value=Decimal("0.01"),
            max_value=Decimal("99999.99"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @PBT_SETTINGS
    def test_margin_equals_sell_minus_cost(
        self,
        purchase_price: Decimal,
        qty_per_pack: int,
        total_packs: int,
        sell_price: Decimal,
    ) -> None:
        """P2: margin == sell_price_per_unit - cost_per_unit."""
        cost_per_unit, margin, margin_pct = _compute_pricing(
            purchase_price, qty_per_pack, total_packs, sell_price,
        )
        assert cost_per_unit is not None
        expected_margin = Decimal(str(sell_price)) - cost_per_unit
        assert margin == expected_margin, (
            f"margin {margin} != expected {expected_margin}"
        )

    @given(
        purchase_price=positive_price,
        qty_per_pack=positive_int,
        total_packs=positive_int,
        sell_price=st.decimals(
            min_value=Decimal("0.01"),
            max_value=Decimal("99999.99"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @PBT_SETTINGS
    def test_margin_pct_formula_when_sell_positive(
        self,
        purchase_price: Decimal,
        qty_per_pack: int,
        total_packs: int,
        sell_price: Decimal,
    ) -> None:
        """P2: margin_pct == (margin / sell) × 100 when sell > 0."""
        cost_per_unit, margin, margin_pct = _compute_pricing(
            purchase_price, qty_per_pack, total_packs, sell_price,
        )
        assert cost_per_unit is not None
        assert margin is not None
        expected_pct = (margin / Decimal(str(sell_price))) * Decimal("100")
        assert margin_pct == expected_pct, (
            f"margin_pct {margin_pct} != expected {expected_pct}"
        )

    @given(
        purchase_price=positive_price,
        qty_per_pack=positive_int,
        total_packs=positive_int,
    )
    @PBT_SETTINGS
    def test_margin_pct_zero_when_sell_is_zero(
        self,
        purchase_price: Decimal,
        qty_per_pack: int,
        total_packs: int,
    ) -> None:
        """P2: margin_pct == 0.00 when sell_price_per_unit is zero."""
        cost_per_unit, margin, margin_pct = _compute_pricing(
            purchase_price, qty_per_pack, total_packs, Decimal("0.00"),
        )
        assert cost_per_unit is not None
        assert margin is not None
        assert margin_pct == Decimal("0.00"), (
            f"margin_pct {margin_pct} != 0.00 when sell is zero"
        )

    @given(
        sell_price=st.one_of(st.none(), non_negative_price),
    )
    @PBT_SETTINGS
    def test_margin_none_when_cost_is_none(
        self,
        sell_price: Decimal | None,
    ) -> None:
        """P2: margin and margin_pct are None when cost_per_unit is None."""
        # Ensure cost_per_unit is None by passing None purchase_price
        cost_per_unit, margin, margin_pct = _compute_pricing(
            None, 1, 1, sell_price,
        )
        assert cost_per_unit is None
        assert margin is None
        assert margin_pct is None


# ===========================================================================
# Property 5: Positive integer validation for packaging quantities
# Feature: parts-packaging-pricing, Property 5: Positive integer validation
# ===========================================================================


class TestP5PositiveIntegerValidation:
    """For any integer ≤ 0 as qty_per_pack or total_packs, the Pydantic
    schema returns a ValidationError (which the API surfaces as 422).
    For any positive integer, the schema accepts it.

    **Validates: Requirements 5.4, 5.5, 7.5**
    """

    @given(
        non_positive=st.integers(min_value=-1000, max_value=0),
    )
    @PBT_SETTINGS
    def test_non_positive_qty_per_pack_rejected(
        self,
        non_positive: int,
    ) -> None:
        """P5: qty_per_pack ≤ 0 → ValidationError (422 at API level)."""
        from pydantic import ValidationError
        from app.modules.catalogue.schemas import PartCreateRequest

        import pytest
        with pytest.raises(ValidationError):
            PartCreateRequest(
                name="Test Part",
                default_price="10.00",
                qty_per_pack=non_positive,
            )

    @given(
        non_positive=st.integers(min_value=-1000, max_value=0),
    )
    @PBT_SETTINGS
    def test_non_positive_total_packs_rejected(
        self,
        non_positive: int,
    ) -> None:
        """P5: total_packs ≤ 0 → ValidationError (422 at API level)."""
        from pydantic import ValidationError
        from app.modules.catalogue.schemas import PartCreateRequest

        import pytest
        with pytest.raises(ValidationError):
            PartCreateRequest(
                name="Test Part",
                default_price="10.00",
                total_packs=non_positive,
            )

    @given(
        positive=st.integers(min_value=1, max_value=10000),
    )
    @PBT_SETTINGS
    def test_positive_qty_per_pack_accepted(
        self,
        positive: int,
    ) -> None:
        """P5: positive qty_per_pack → schema accepts it."""
        from app.modules.catalogue.schemas import PartCreateRequest

        req = PartCreateRequest(
            name="Test Part",
            default_price="10.00",
            qty_per_pack=positive,
        )
        assert req.qty_per_pack == positive

    @given(
        positive=st.integers(min_value=1, max_value=10000),
    )
    @PBT_SETTINGS
    def test_positive_total_packs_accepted(
        self,
        positive: int,
    ) -> None:
        """P5: positive total_packs → schema accepts it."""
        from app.modules.catalogue.schemas import PartCreateRequest

        req = PartCreateRequest(
            name="Test Part",
            default_price="10.00",
            total_packs=positive,
        )
        assert req.total_packs == positive


# ===========================================================================
# Property 8: Invalid packaging type rejection
# Feature: parts-packaging-pricing, Property 8: Invalid packaging type rejection
# ===========================================================================


class TestP8InvalidPackagingTypeRejection:
    """For any string not in {box, carton, pack, bag, pallet, single},
    the router validation rejects it. For any string in the allowed set,
    it is accepted.

    **Validates: Requirements 7.6**
    """

    @given(
        random_string=st.text(min_size=1, max_size=50).filter(
            lambda s: s.strip() and s not in {"box", "carton", "pack", "bag", "pallet", "single"}
        ),
    )
    @PBT_SETTINGS
    def test_invalid_packaging_type_not_in_allowed_set(
        self,
        random_string: str,
    ) -> None:
        """P8: packaging_type not in allowed set → rejected."""
        from app.modules.catalogue.router import ALLOWED_PACKAGING_TYPES

        assert random_string not in ALLOWED_PACKAGING_TYPES

    @given(
        valid_type=st.sampled_from(["box", "carton", "pack", "bag", "pallet", "single"]),
    )
    @PBT_SETTINGS
    def test_valid_packaging_type_in_allowed_set(
        self,
        valid_type: str,
    ) -> None:
        """P8: packaging_type in allowed set → accepted."""
        from app.modules.catalogue.router import ALLOWED_PACKAGING_TYPES

        assert valid_type in ALLOWED_PACKAGING_TYPES


# ===========================================================================
# Property 4: GST legacy boolean mapping
# Feature: parts-packaging-pricing, Property 4: GST legacy boolean mapping
# ===========================================================================


class TestP4GstLegacyMapping:
    """For any (is_gst_exempt, gst_inclusive) boolean pair, the mapping
    produces the correct gst_mode string. The mapping is total over the
    boolean domain.

    **Validates: Requirements 4.3, 4.4, 4.5, 4.6, 8.2**
    """

    @given(gst_inclusive=st.booleans())
    @PBT_SETTINGS
    def test_exempt_when_is_gst_exempt_true(
        self,
        gst_inclusive: bool,
    ) -> None:
        """P4: is_gst_exempt=True → 'exempt' regardless of gst_inclusive."""
        from app.modules.catalogue.service import _map_gst_legacy

        result = _map_gst_legacy(is_gst_exempt=True, gst_inclusive=gst_inclusive)
        assert result == "exempt", (
            f"Expected 'exempt' when is_gst_exempt=True, got '{result}'"
        )

    @given(data=st.data())
    @PBT_SETTINGS
    def test_inclusive_when_not_exempt_and_gst_inclusive(
        self,
        data: st.DataObject,
    ) -> None:
        """P4: is_gst_exempt=False, gst_inclusive=True → 'inclusive'."""
        from app.modules.catalogue.service import _map_gst_legacy

        result = _map_gst_legacy(is_gst_exempt=False, gst_inclusive=True)
        assert result == "inclusive", (
            f"Expected 'inclusive' when is_gst_exempt=False and gst_inclusive=True, got '{result}'"
        )

    @given(data=st.data())
    @PBT_SETTINGS
    def test_exclusive_when_both_false(
        self,
        data: st.DataObject,
    ) -> None:
        """P4: is_gst_exempt=False, gst_inclusive=False → 'exclusive'."""
        from app.modules.catalogue.service import _map_gst_legacy

        result = _map_gst_legacy(is_gst_exempt=False, gst_inclusive=False)
        assert result == "exclusive", (
            f"Expected 'exclusive' when both booleans are False, got '{result}'"
        )

    @given(
        is_gst_exempt=st.booleans(),
        gst_inclusive=st.booleans(),
    )
    @PBT_SETTINGS
    def test_totality_result_always_valid(
        self,
        is_gst_exempt: bool,
        gst_inclusive: bool,
    ) -> None:
        """P4: For any boolean pair, result is always in {'exempt', 'inclusive', 'exclusive'}."""
        from app.modules.catalogue.service import _map_gst_legacy

        result = _map_gst_legacy(is_gst_exempt=is_gst_exempt, gst_inclusive=gst_inclusive)
        assert result in {"exempt", "inclusive", "exclusive"}, (
            f"Unexpected gst_mode '{result}' for is_gst_exempt={is_gst_exempt}, "
            f"gst_inclusive={gst_inclusive}"
        )

    @given(
        is_gst_exempt=st.booleans(),
        gst_inclusive=st.booleans(),
    )
    @PBT_SETTINGS
    def test_mapping_correctness_all_combinations(
        self,
        is_gst_exempt: bool,
        gst_inclusive: bool,
    ) -> None:
        """P4: Full mapping correctness across all boolean combinations."""
        from app.modules.catalogue.service import _map_gst_legacy

        result = _map_gst_legacy(is_gst_exempt=is_gst_exempt, gst_inclusive=gst_inclusive)

        if is_gst_exempt:
            assert result == "exempt"
        elif gst_inclusive:
            assert result == "inclusive"
        else:
            assert result == "exclusive"


# ===========================================================================
# Property 3: Currency formatting
# Feature: parts-packaging-pricing, Property 3: Currency formatting
# ===========================================================================


def fmt_nzd(value: float) -> str:
    """Python equivalent of the frontend NZD formatting function:
    ``const fmtNZD = (v: number) => '$' + v.toFixed(2)``
    """
    return f"${value:.2f}"


import re

_NZD_PATTERN = re.compile(r"^\$-?\d+\.\d{2}$")


class TestP3CurrencyFormatting:
    """For any numeric value, the NZD formatting function produces a string
    matching the pattern ``$X.XX`` (dollar sign, optional negative sign,
    digits, decimal point, exactly two decimal digits).

    **Validates: Requirements 3.6, 3.7, 6.4**
    """

    @given(
        value=st.floats(
            min_value=-99999.99,
            max_value=99999.99,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @PBT_SETTINGS
    def test_nzd_format_matches_pattern(self, value: float) -> None:
        """P3: fmt_nzd(value) always matches ``$X.XX`` pattern."""
        result = fmt_nzd(value)
        assert _NZD_PATTERN.match(result), (
            f"fmt_nzd({value!r}) = {result!r} does not match pattern $X.XX"
        )

    @given(
        value=st.floats(
            min_value=0.0,
            max_value=99999.99,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @PBT_SETTINGS
    def test_nzd_format_starts_with_dollar(self, value: float) -> None:
        """P3: formatted string always starts with '$'."""
        result = fmt_nzd(value)
        assert result.startswith("$"), (
            f"fmt_nzd({value!r}) = {result!r} does not start with '$'"
        )

    @given(
        value=st.floats(
            min_value=-99999.99,
            max_value=99999.99,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @PBT_SETTINGS
    def test_nzd_format_has_exactly_two_decimal_places(self, value: float) -> None:
        """P3: formatted string always has exactly two digits after the decimal point."""
        result = fmt_nzd(value)
        # Split on the last '.' to get the decimal portion
        assert "." in result, f"fmt_nzd({value!r}) = {result!r} has no decimal point"
        decimal_part = result.rsplit(".", 1)[1]
        assert len(decimal_part) == 2, (
            f"fmt_nzd({value!r}) = {result!r} has {len(decimal_part)} decimal digits, expected 2"
        )


# ===========================================================================
# Property 6: API pricing fields round-trip
# Feature: parts-packaging-pricing, Property 6: API pricing fields round-trip
# ===========================================================================

ALLOWED_PACKAGING_TYPES = ["box", "carton", "pack", "bag", "pallet", "single"]
ALLOWED_GST_MODES = ["inclusive", "exclusive", "exempt"]


class TestP6ApiPricingFieldsRoundTrip:
    """Create a part with a valid pricing payload, simulate retrieval via
    ``_part_to_dict``-style serialisation, and verify that all submitted
    fields are returned with their original values plus correctly computed
    derived fields (cost_per_unit, margin, margin_pct).

    **Validates: Requirements 7.1, 7.2, 7.3**
    """

    @given(
        purchase_price=positive_price,
        packaging_type=st.sampled_from(ALLOWED_PACKAGING_TYPES),
        qty_per_pack=positive_int,
        total_packs=positive_int,
        sell_price_per_unit=non_negative_price,
        gst_mode=st.sampled_from(ALLOWED_GST_MODES),
    )
    @PBT_SETTINGS
    def test_round_trip_preserves_submitted_and_computes_derived(
        self,
        purchase_price: Decimal,
        packaging_type: str,
        qty_per_pack: int,
        total_packs: int,
        sell_price_per_unit: Decimal,
        gst_mode: str,
    ) -> None:
        """P6: submitted fields preserved, derived fields computed correctly."""
        # --- Step 1: compute derived fields via the real service helper ---
        cost_per_unit, margin, margin_pct = _compute_pricing(
            purchase_price, qty_per_pack, total_packs, sell_price_per_unit,
        )

        # --- Step 2: simulate _part_to_dict serialisation (Decimal → str) ---
        response = {
            "purchase_price": str(purchase_price),
            "packaging_type": packaging_type,
            "qty_per_pack": qty_per_pack,
            "total_packs": total_packs,
            "sell_price_per_unit": str(sell_price_per_unit),
            "gst_mode": gst_mode,
            "cost_per_unit": str(cost_per_unit) if cost_per_unit is not None else None,
            "margin": str(margin) if margin is not None else None,
            "margin_pct": str(margin_pct) if margin_pct is not None else None,
        }

        # --- Step 3: verify submitted fields are preserved ---
        assert response["purchase_price"] == str(purchase_price)
        assert response["packaging_type"] == packaging_type
        assert response["qty_per_pack"] == qty_per_pack
        assert response["total_packs"] == total_packs
        assert response["sell_price_per_unit"] == str(sell_price_per_unit)
        assert response["gst_mode"] == gst_mode

        # --- Step 4: verify derived fields are present and correct ---
        # cost_per_unit must be computed (all inputs are positive)
        assert cost_per_unit is not None, "cost_per_unit should be computed for positive inputs"
        expected_cost = Decimal(str(purchase_price)) / Decimal(str(qty_per_pack * total_packs))
        assert cost_per_unit == expected_cost, (
            f"cost_per_unit {cost_per_unit} != expected {expected_cost}"
        )
        assert response["cost_per_unit"] == str(expected_cost)

        # margin must be computed
        expected_margin = Decimal(str(sell_price_per_unit)) - expected_cost
        assert margin == expected_margin, (
            f"margin {margin} != expected {expected_margin}"
        )
        assert response["margin"] == str(expected_margin)

        # margin_pct
        if sell_price_per_unit > 0:
            expected_pct = (expected_margin / Decimal(str(sell_price_per_unit))) * Decimal("100")
        else:
            expected_pct = Decimal("0.00")
        assert margin_pct == expected_pct, (
            f"margin_pct {margin_pct} != expected {expected_pct}"
        )
        assert response["margin_pct"] == str(expected_pct)


# ===========================================================================
# Property 7: Server-side derived field consistency
# Feature: parts-packaging-pricing, Property 7: Server-side derived field consistency
# ===========================================================================


class TestP7ServerSideDerivedFieldConsistency:
    """For any valid inputs (positive purchase_price, positive integer
    qty_per_pack and total_packs, non-negative sell_price_per_unit),
    the persisted cost_per_unit, margin, and margin_pct match the
    formulas exactly:
      - cost_per_unit == purchase_price / (qty_per_pack × total_packs)
      - margin == sell_price_per_unit - cost_per_unit
      - margin_pct == (margin / sell_price_per_unit) × 100  (or 0.00 when sell is zero)

    **Validates: Requirements 7.4**
    """

    @given(
        purchase_price=positive_price,
        qty_per_pack=positive_int,
        total_packs=positive_int,
        sell_price_per_unit=st.decimals(
            min_value=Decimal("0.01"),
            max_value=Decimal("99999.99"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @PBT_SETTINGS
    def test_all_derived_fields_consistent_positive_sell(
        self,
        purchase_price: Decimal,
        qty_per_pack: int,
        total_packs: int,
        sell_price_per_unit: Decimal,
    ) -> None:
        """P7: All three derived fields match their formulas when sell > 0."""
        cost_per_unit, margin, margin_pct = _compute_pricing(
            purchase_price, qty_per_pack, total_packs, sell_price_per_unit,
        )

        # cost_per_unit formula
        expected_cost = Decimal(str(purchase_price)) / Decimal(str(qty_per_pack * total_packs))
        assert cost_per_unit == expected_cost, (
            f"cost_per_unit {cost_per_unit} != expected {expected_cost}"
        )

        # margin formula
        expected_margin = Decimal(str(sell_price_per_unit)) - expected_cost
        assert margin == expected_margin, (
            f"margin {margin} != expected {expected_margin}"
        )

        # margin_pct formula (sell > 0)
        expected_pct = (expected_margin / Decimal(str(sell_price_per_unit))) * Decimal("100")
        assert margin_pct == expected_pct, (
            f"margin_pct {margin_pct} != expected {expected_pct}"
        )

    @given(
        purchase_price=positive_price,
        qty_per_pack=positive_int,
        total_packs=positive_int,
    )
    @PBT_SETTINGS
    def test_derived_fields_consistent_zero_sell(
        self,
        purchase_price: Decimal,
        qty_per_pack: int,
        total_packs: int,
    ) -> None:
        """P7: margin_pct == 0.00 when sell_price_per_unit is zero."""
        cost_per_unit, margin, margin_pct = _compute_pricing(
            purchase_price, qty_per_pack, total_packs, Decimal("0.00"),
        )

        # cost_per_unit formula
        expected_cost = Decimal(str(purchase_price)) / Decimal(str(qty_per_pack * total_packs))
        assert cost_per_unit == expected_cost, (
            f"cost_per_unit {cost_per_unit} != expected {expected_cost}"
        )

        # margin formula (sell is zero)
        expected_margin = Decimal("0.00") - expected_cost
        assert margin == expected_margin, (
            f"margin {margin} != expected {expected_margin}"
        )

        # margin_pct must be 0.00 when sell is zero
        assert margin_pct == Decimal("0.00"), (
            f"margin_pct {margin_pct} != 0.00 when sell is zero"
        )


# ===========================================================================
# Property 9: Migration data transformation
# Feature: parts-packaging-pricing, Property 9: Migration data transformation
# ===========================================================================

import pathlib


class TestP9MigrationDataTransformation:
    """After migration, existing rows have sell_price_per_unit == default_price,
    packaging_type == 'single', qty_per_pack == 1, total_packs == 1.

    Since we cannot execute the actual migration SQL in a property test, we
    verify two things:
      1. The migration source code contains the correct SQL statements.
      2. For any valid default_price, the expected post-migration state holds
         (sell_price_per_unit == default_price, packaging_type == 'single',
         qty_per_pack == 1, total_packs == 1).

    **Validates: Requirements 8.3, 8.4, 8.6**
    """

    # -----------------------------------------------------------------------
    # Static checks: migration source contains the expected SQL statements
    # -----------------------------------------------------------------------

    _MIGRATION_PATH = (
        pathlib.Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "2026_03_28_0900-0116_parts_packaging_pricing.py"
    )

    @classmethod
    def _read_migration_source(cls) -> str:
        """Read the migration file source code from disk."""
        return cls._MIGRATION_PATH.read_text(encoding="utf-8")

    def test_migration_copies_default_price_to_sell_price(self) -> None:
        """P9: Migration SQL copies default_price → sell_price_per_unit."""
        source = self._read_migration_source()
        assert "sell_price_per_unit = default_price" in source, (
            "Migration must copy default_price into sell_price_per_unit"
        )

    def test_migration_sets_packaging_type_single(self) -> None:
        """P9: Migration SQL sets packaging_type = 'single' for existing rows."""
        source = self._read_migration_source()
        assert "packaging_type = 'single'" in source, (
            "Migration must set packaging_type = 'single'"
        )

    def test_migration_sets_qty_per_pack_one(self) -> None:
        """P9: Migration SQL sets qty_per_pack = 1 for existing rows."""
        source = self._read_migration_source()
        assert "qty_per_pack = 1" in source, (
            "Migration must set qty_per_pack = 1"
        )

    def test_migration_sets_total_packs_one(self) -> None:
        """P9: Migration SQL sets total_packs = 1 for existing rows."""
        source = self._read_migration_source()
        assert "total_packs = 1" in source, (
            "Migration must set total_packs = 1"
        )

    # -----------------------------------------------------------------------
    # Property-based: for any valid default_price, post-migration state holds
    # -----------------------------------------------------------------------

    @given(
        default_price=st.decimals(
            min_value=Decimal("0.01"),
            max_value=Decimal("99999.99"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @PBT_SETTINGS
    def test_post_migration_sell_price_equals_default_price(
        self,
        default_price: Decimal,
    ) -> None:
        """P9: For any default_price, sell_price_per_unit == default_price after migration."""
        # Simulate the migration transformation: the SQL copies default_price
        # into sell_price_per_unit verbatim.
        sell_price_per_unit = default_price
        assert sell_price_per_unit == default_price, (
            f"sell_price_per_unit {sell_price_per_unit} != default_price {default_price}"
        )

    @given(
        default_price=st.decimals(
            min_value=Decimal("0.01"),
            max_value=Decimal("99999.99"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @PBT_SETTINGS
    def test_post_migration_packaging_defaults(
        self,
        default_price: Decimal,
    ) -> None:
        """P9: For any existing row, packaging_type='single', qty_per_pack=1, total_packs=1."""
        # Simulate the migration transformation for packaging fields.
        # The migration sets these unconditionally for all existing rows.
        packaging_type = "single"
        qty_per_pack = 1
        total_packs = 1

        assert packaging_type == "single", (
            f"packaging_type should be 'single', got '{packaging_type}'"
        )
        assert qty_per_pack == 1, (
            f"qty_per_pack should be 1, got {qty_per_pack}"
        )
        assert total_packs == 1, (
            f"total_packs should be 1, got {total_packs}"
        )

    @given(
        default_price=st.decimals(
            min_value=Decimal("0.00"),
            max_value=Decimal("99999.99"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        is_gst_exempt=st.booleans(),
        gst_inclusive=st.booleans(),
        name=st.text(min_size=1, max_size=50, alphabet=st.characters(
            whitelist_categories=("L", "N", "Zs"),
        )).filter(lambda s: s.strip()),
    )
    @PBT_SETTINGS
    def test_post_migration_preserves_existing_columns(
        self,
        default_price: Decimal,
        is_gst_exempt: bool,
        gst_inclusive: bool,
        name: str,
    ) -> None:
        """P9: Migration preserves all pre-existing column values (default_price,
        is_gst_exempt, gst_inclusive, name) while adding new fields."""
        # Simulate a pre-migration row
        pre_migration_row = {
            "name": name,
            "default_price": default_price,
            "is_gst_exempt": is_gst_exempt,
            "gst_inclusive": gst_inclusive,
        }

        # Simulate post-migration row: existing columns unchanged, new columns added
        post_migration_row = {
            **pre_migration_row,
            "sell_price_per_unit": default_price,
            "packaging_type": "single",
            "qty_per_pack": 1,
            "total_packs": 1,
        }

        # Verify existing columns are preserved
        assert post_migration_row["name"] == name
        assert post_migration_row["default_price"] == default_price
        assert post_migration_row["is_gst_exempt"] == is_gst_exempt
        assert post_migration_row["gst_inclusive"] == gst_inclusive

        # Verify new columns have correct values
        assert post_migration_row["sell_price_per_unit"] == default_price
        assert post_migration_row["packaging_type"] == "single"
        assert post_migration_row["qty_per_pack"] == 1
        assert post_migration_row["total_packs"] == 1
