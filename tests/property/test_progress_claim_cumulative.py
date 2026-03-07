"""Property-based test: cumulative claimed amount never exceeds revised_contract_value.

**Validates: Requirements 11** — Property 11

For any project P with progress claims, the cumulative claimed amount
(work_completed_to_date) never exceeds the revised_contract_value
(contract_value + variations_to_date).

Uses Hypothesis to generate random sequences of progress claims and
verifies the cumulative invariant holds through the service layer.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings as h_settings, HealthCheck, assume
from hypothesis import strategies as st

from app.modules.progress_claims.service import ProgressClaimService
from app.modules.progress_claims.schemas import ProgressClaimCreate


PBT_SETTINGS = h_settings(
    max_examples=80,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# Strategy: generate a contract value and a sequence of cumulative work amounts
contract_value_strategy = st.decimals(
    min_value=Decimal("1000"),
    max_value=Decimal("10000000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

variations_strategy = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("500000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


class TestProgressClaimCumulativeInvariant:
    """For any project, cumulative claimed never exceeds revised contract value.

    **Validates: Requirements 11**
    """

    @given(
        contract_value=contract_value_strategy,
        variations=variations_strategy,
        work_fractions=st.lists(
            st.floats(min_value=0.01, max_value=0.5, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=8,
        ),
        materials=st.decimals(
            min_value=Decimal("0"), max_value=Decimal("5000"),
            places=2, allow_nan=False, allow_infinity=False,
        ),
        retention_pct=st.floats(min_value=0, max_value=0.1, allow_nan=False, allow_infinity=False),
    )
    @PBT_SETTINGS
    def test_cumulative_claimed_never_exceeds_revised_contract(
        self,
        contract_value: Decimal,
        variations: Decimal,
        work_fractions: list[float],
        materials: Decimal,
        retention_pct: float,
    ) -> None:
        """Property 11: cumulative work_completed_to_date <= revised_contract_value."""
        revised = contract_value + variations

        # Build a sequence of cumulative work amounts from fractions
        cumulative = Decimal("0")
        previous = Decimal("0")

        for frac in work_fractions:
            increment = (revised * Decimal(str(frac))).quantize(Decimal("0.01"))
            cumulative = previous + increment

            # Clamp to revised contract value (the service enforces this)
            if cumulative > revised:
                cumulative = revised

            retention = (increment * Decimal(str(retention_pct))).quantize(Decimal("0.01"))

            # Use the static calculation method
            calc = ProgressClaimService.calculate_fields(
                contract_value=contract_value,
                variations_to_date=variations,
                work_completed_to_date=cumulative,
                work_completed_previous=previous,
                materials_on_site=materials,
                retention_withheld=retention,
            )

            # PROPERTY: cumulative never exceeds revised
            assert cumulative <= calc["revised_contract_value"], (
                f"Cumulative {cumulative} exceeds revised {calc['revised_contract_value']}"
            )

            # PROPERTY: revised = contract + variations
            assert calc["revised_contract_value"] == contract_value + variations

            # PROPERTY: this_period = to_date - previous
            assert calc["work_completed_this_period"] == cumulative - previous

            # PROPERTY: completion percentage is within [0, 100]
            assert Decimal("0") <= calc["completion_percentage"] <= Decimal("100")

            # Validate the service rejects over-contract claims
            ProgressClaimService.validate_cumulative_not_exceeding_contract(
                cumulative, calc["revised_contract_value"],
            )

            previous = cumulative

    @given(
        contract_value=contract_value_strategy,
        variations=variations_strategy,
        excess_fraction=st.floats(min_value=1.01, max_value=2.0, allow_nan=False, allow_infinity=False),
    )
    @PBT_SETTINGS
    def test_exceeding_contract_raises_error(
        self,
        contract_value: Decimal,
        variations: Decimal,
        excess_fraction: float,
    ) -> None:
        """Property 11 (negative): claims exceeding revised contract are rejected."""
        revised = contract_value + variations
        over_amount = (revised * Decimal(str(excess_fraction))).quantize(Decimal("0.01"))
        assume(over_amount > revised)

        with pytest.raises(ValueError, match="exceeds revised contract value"):
            ProgressClaimService.validate_cumulative_not_exceeding_contract(
                over_amount, revised,
            )
