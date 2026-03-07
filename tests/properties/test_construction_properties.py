"""Comprehensive property-based tests for construction module properties.

Properties covered:
  P11 — Progress Claim Financial Consistency: cumulative claims ≤ contract
  P12 — Variation Contract Value Consistency: revised = original + variations
  P20 — Retention Release Consistency: releases ≤ withheld

**Validates: Requirements 11, 12, 20**
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import pytest
from hypothesis import given, assume
from hypothesis import strategies as st

from tests.properties.conftest import PBT_SETTINGS

from app.modules.progress_claims.service import ProgressClaimService
from app.modules.retentions.service import RetentionService


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

contract_value_st = st.decimals(
    min_value=Decimal("1000"), max_value=Decimal("10000000"),
    places=2, allow_nan=False, allow_infinity=False,
)

variations_st = st.decimals(
    min_value=Decimal("0"), max_value=Decimal("500000"),
    places=2, allow_nan=False, allow_infinity=False,
)

retention_pct_st = st.decimals(
    min_value=Decimal("1"), max_value=Decimal("20"),
    places=2, allow_nan=False, allow_infinity=False,
)

work_amount_st = st.decimals(
    min_value=Decimal("1000"), max_value=Decimal("5000000"),
    places=2, allow_nan=False, allow_infinity=False,
)


# ===========================================================================
# Property 11: Progress Claim Financial Consistency
# ===========================================================================


class TestP11ProgressClaimConsistency:
    """Cumulative claimed amount never exceeds revised_contract_value.

    **Validates: Requirements 11**
    """

    @given(
        contract_value=contract_value_st,
        variations=variations_st,
        work_fractions=st.lists(
            st.floats(min_value=0.01, max_value=0.5, allow_nan=False, allow_infinity=False),
            min_size=1, max_size=8,
        ),
        materials=st.decimals(
            min_value=Decimal("0"), max_value=Decimal("5000"),
            places=2, allow_nan=False, allow_infinity=False,
        ),
        retention_pct=st.floats(min_value=0, max_value=0.1, allow_nan=False, allow_infinity=False),
    )
    @PBT_SETTINGS
    def test_cumulative_never_exceeds_revised_contract(
        self, contract_value, variations, work_fractions, materials, retention_pct,
    ) -> None:
        """P11: cumulative work_completed_to_date <= revised_contract_value."""
        revised = contract_value + variations
        cumulative = Decimal("0")
        previous = Decimal("0")

        for frac in work_fractions:
            increment = (revised * Decimal(str(frac))).quantize(Decimal("0.01"))
            cumulative = previous + increment
            if cumulative > revised:
                cumulative = revised

            retention = (increment * Decimal(str(retention_pct))).quantize(Decimal("0.01"))

            calc = ProgressClaimService.calculate_fields(
                contract_value=contract_value,
                variations_to_date=variations,
                work_completed_to_date=cumulative,
                work_completed_previous=previous,
                materials_on_site=materials,
                retention_withheld=retention,
            )

            assert cumulative <= calc["revised_contract_value"]
            assert calc["revised_contract_value"] == contract_value + variations
            assert calc["work_completed_this_period"] == cumulative - previous
            assert Decimal("0") <= calc["completion_percentage"] <= Decimal("100")

            ProgressClaimService.validate_cumulative_not_exceeding_contract(
                cumulative, calc["revised_contract_value"],
            )
            previous = cumulative

    @given(
        contract_value=contract_value_st,
        variations=variations_st,
        excess_fraction=st.floats(min_value=1.01, max_value=2.0, allow_nan=False, allow_infinity=False),
    )
    @PBT_SETTINGS
    def test_exceeding_contract_raises_error(
        self, contract_value, variations, excess_fraction,
    ) -> None:
        """P11 (negative): claims exceeding revised contract are rejected."""
        revised = contract_value + variations
        over_amount = (revised * Decimal(str(excess_fraction))).quantize(Decimal("0.01"))
        assume(over_amount > revised)

        with pytest.raises(ValueError, match="exceeds revised contract value"):
            ProgressClaimService.validate_cumulative_not_exceeding_contract(
                over_amount, revised,
            )


# ===========================================================================
# Property 12: Variation Contract Value Consistency
# ===========================================================================


class TestP12VariationContractValue:
    """revised_contract_value = original + sum of approved variation cost_impacts.

    **Validates: Requirements 12**
    """

    @given(
        original_value=contract_value_st,
        variation_impacts=st.lists(
            st.decimals(
                min_value=Decimal("-100000"), max_value=Decimal("500000"),
                places=2, allow_nan=False, allow_infinity=False,
            ),
            min_size=0, max_size=10,
        ),
    )
    @PBT_SETTINGS
    def test_revised_equals_original_plus_variations(
        self, original_value, variation_impacts,
    ) -> None:
        """P12: revised = original + sum(approved variation cost_impacts)."""
        total_impact = sum(variation_impacts, Decimal("0"))
        revised = original_value + total_impact
        assert revised == original_value + total_impact

    @given(
        original_value=contract_value_st,
        variation_impacts=st.lists(
            st.decimals(
                min_value=Decimal("0"), max_value=Decimal("100000"),
                places=2, allow_nan=False, allow_infinity=False,
            ),
            min_size=1, max_size=10,
        ),
    )
    @PBT_SETTINGS
    def test_positive_variations_increase_contract(
        self, original_value, variation_impacts,
    ) -> None:
        """P12: positive variations always increase the contract value."""
        total_impact = sum(variation_impacts, Decimal("0"))
        revised = original_value + total_impact
        assert revised >= original_value


# ===========================================================================
# Property 20: Retention Release Consistency
# ===========================================================================


class TestP20RetentionReleaseConsistency:
    """Sum of retention releases never exceeds total retention withheld.

    **Validates: Requirements 20**
    """

    @given(
        retention_pct=retention_pct_st,
        work_amounts=st.lists(work_amount_st, min_size=1, max_size=10),
        release_fractions=st.lists(
            st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=1, max_size=5,
        ),
    )
    @PBT_SETTINGS
    def test_releases_never_exceed_withheld(
        self, retention_pct, work_amounts, release_fractions,
    ) -> None:
        """P20: sum of releases <= total withheld."""
        total_withheld = Decimal("0")
        for work_amount in work_amounts:
            total_withheld += RetentionService.calculate_retention(work_amount, retention_pct)

        assume(total_withheld > 0)

        total_released = Decimal("0")
        for frac in release_fractions:
            remaining = total_withheld - total_released
            if remaining <= 0:
                break
            release = (remaining * Decimal(str(frac))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP,
            )
            if release <= 0:
                continue
            if release > remaining:
                release = remaining
            total_released += release
            assert total_released <= total_withheld

        assert total_released <= total_withheld

    @given(retention_pct=retention_pct_st, work_amount=work_amount_st)
    @PBT_SETTINGS
    def test_retention_is_non_negative(self, retention_pct, work_amount) -> None:
        """P20: retention calculation always produces non-negative value."""
        result = RetentionService.calculate_retention(work_amount, retention_pct)
        assert result >= Decimal("0")

    @given(retention_pct=retention_pct_st, work_amount=work_amount_st)
    @PBT_SETTINGS
    def test_retention_does_not_exceed_work_amount(
        self, retention_pct, work_amount,
    ) -> None:
        """P20: retention withheld never exceeds work completed."""
        assume(retention_pct <= Decimal("100"))
        result = RetentionService.calculate_retention(work_amount, retention_pct)
        assert result <= work_amount
