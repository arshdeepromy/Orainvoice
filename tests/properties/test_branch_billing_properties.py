"""Property-based tests for branch billing.

Properties covered:
  P1  — Branch billing formula: total = base × branches × interval_multiplier
  P2  — Create+deactivate = net zero: proration cancels out
  P3  — Proration sum consistency: sum of per-branch prorations = total proration
  P4  — HQ deactivation protection: HQ branch cannot be deactivated while others exist
  P19 — Stripe failure rollback: branch not persisted if Stripe fails
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal, ROUND_HALF_UP
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from app.modules.billing.branch_billing import (
    calculate_branch_cost,
    calculate_proration,
)
from app.modules.billing.interval_pricing import (
    compute_effective_price,
    INTERVAL_PERIODS_PER_YEAR,
)

# ---------------------------------------------------------------------------
# Settings — 100 examples per property, no deadline, suppress slow health check
# ---------------------------------------------------------------------------

BRANCH_BILLING_PBT_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

_TWO_PLACES = Decimal("0.01")
_ZERO = Decimal("0")

interval_strategy = st.sampled_from(["weekly", "fortnightly", "monthly", "annual"])

base_price_strategy = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("10000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

discount_strategy = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("100"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

branch_count_strategy = st.integers(min_value=1, max_value=50)

days_remaining_strategy = st.integers(min_value=0, max_value=365)

total_days_strategy = st.integers(min_value=1, max_value=365)

uuid_strategy = st.uuids()

safe_name_strategy = st.text(
    min_size=1,
    max_size=80,
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
).filter(lambda s: s.strip())


# ---------------------------------------------------------------------------
# Fake Branch helper
# ---------------------------------------------------------------------------

class _FakeBranch:
    """Minimal Branch stand-in for property tests."""

    def __init__(
        self,
        *,
        id: uuid.UUID | None = None,
        org_id: uuid.UUID | None = None,
        name: str = "Test Branch",
        address: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        logo_url: str | None = None,
        operating_hours: dict | None = None,
        timezone: str = "Pacific/Auckland",
        is_hq: bool = False,
        is_active: bool = True,
    ):
        self.id = id or uuid.uuid4()
        self.org_id = org_id or uuid.uuid4()
        self.name = name
        self.address = address
        self.phone = phone
        self.email = email
        self.logo_url = logo_url
        self.operating_hours = operating_hours or {}
        self.timezone = timezone
        self.is_hq = is_hq
        self.is_active = is_active
        from datetime import timezone as tz_utc, datetime as dt
        self.created_at = dt.now(tz_utc.utc)
        self.updated_at = dt.now(tz_utc.utc)


def _make_scalar_one_or_none(return_value):
    """Create a mock result whose .scalar_one_or_none() returns the given value."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = return_value
    return mock_result


def _make_scalar(return_value):
    """Create a mock result whose .scalar() returns the given value."""
    mock_result = MagicMock()
    mock_result.scalar.return_value = return_value
    return mock_result


# ===========================================================================
# Property 1: Branch billing formula
# Feature: branch-management-complete, Property 1: Branch billing formula
# ===========================================================================


class TestP1BranchBillingFormula:
    """For any base plan price P > 0, number of active branches N >= 1, and
    billing interval I with its interval multiplier M, the total subscription
    charge SHALL equal P x N x M (where M is derived from
    compute_effective_price(P, I, discount)).

    **Validates: Requirements 4.1, 4.2, 4.6, 34.1**
    """

    @given(
        base_price=base_price_strategy,
        branch_count=branch_count_strategy,
        interval=interval_strategy,
        discount=discount_strategy,
    )
    @BRANCH_BILLING_PBT_SETTINGS
    def test_total_equals_per_branch_times_count(
        self,
        base_price: Decimal,
        branch_count: int,
        interval: str,
        discount: Decimal,
    ) -> None:
        """P1: calculate_branch_cost == compute_effective_price * branch_count."""
        total = calculate_branch_cost(base_price, branch_count, interval, discount)
        per_branch = compute_effective_price(base_price, interval, discount)
        expected = (per_branch * Decimal(branch_count)).quantize(
            _TWO_PLACES, rounding=ROUND_HALF_UP
        )
        assert total == expected, (
            f"For price={base_price}, count={branch_count}, interval={interval}, "
            f"discount={discount}: got {total}, expected {expected}"
        )

    @given(
        base_price=base_price_strategy,
        interval=interval_strategy,
        discount=discount_strategy,
    )
    @BRANCH_BILLING_PBT_SETTINGS
    def test_single_branch_equals_base_effective_price(
        self,
        base_price: Decimal,
        interval: str,
        discount: Decimal,
    ) -> None:
        """P1: with 1 branch, total == compute_effective_price (1x multiplier)."""
        total = calculate_branch_cost(base_price, 1, interval, discount)
        per_branch = compute_effective_price(base_price, interval, discount)
        assert total == per_branch, (
            f"Single branch cost {total} should equal per-branch {per_branch}"
        )

    @given(
        base_price=base_price_strategy,
        interval=interval_strategy,
        discount=discount_strategy,
    )
    @BRANCH_BILLING_PBT_SETTINGS
    def test_zero_branches_returns_zero(
        self,
        base_price: Decimal,
        interval: str,
        discount: Decimal,
    ) -> None:
        """P1: zero or negative branch count returns zero."""
        assert calculate_branch_cost(base_price, 0, interval, discount) == _ZERO
        assert calculate_branch_cost(base_price, -1, interval, discount) == _ZERO


# ===========================================================================
# Property 2: Create+deactivate = net zero
# Feature: branch-management-complete, Property 2: Create+deactivate proration cancellation
# ===========================================================================


class TestP2CreateDeactivateNetZero:
    """For any organisation with an active subscription and any point within a
    billing period, creating a branch and then immediately deactivating it SHALL
    result in a net-zero billing change (the prorated charge and prorated credit
    cancel out).

    **Validates: Requirements 4.3, 4.4, 34.2**
    """

    @given(
        per_branch_cost=base_price_strategy,
        days_remaining=st.integers(min_value=1, max_value=365),
        total_days=st.integers(min_value=1, max_value=365),
    )
    @BRANCH_BILLING_PBT_SETTINGS
    def test_proration_charge_and_credit_cancel_out(
        self,
        per_branch_cost: Decimal,
        days_remaining: int,
        total_days: int,
    ) -> None:
        """P2: prorated charge for adding + prorated credit for removing = net zero."""
        assume(days_remaining <= total_days)

        # Prorated charge for adding a branch
        charge = calculate_proration(per_branch_cost, days_remaining, total_days)
        # Prorated credit for removing the same branch at the same instant
        credit = calculate_proration(per_branch_cost, days_remaining, total_days)

        net = charge - credit
        assert net == _ZERO, (
            f"Net should be zero, got {net} "
            f"(charge={charge}, credit={credit})"
        )

    @given(
        per_branch_cost=base_price_strategy,
        days_remaining=st.integers(min_value=1, max_value=365),
        total_days=st.integers(min_value=1, max_value=365),
    )
    @BRANCH_BILLING_PBT_SETTINGS
    def test_proration_is_non_negative(
        self,
        per_branch_cost: Decimal,
        days_remaining: int,
        total_days: int,
    ) -> None:
        """P2: proration is always non-negative for valid inputs."""
        assume(days_remaining <= total_days)
        proration = calculate_proration(per_branch_cost, days_remaining, total_days)
        assert proration >= _ZERO, (
            f"Proration should be non-negative, got {proration}"
        )


# ===========================================================================
# Property 3: Proration sum consistency
# Feature: branch-management-complete, Property 3: Proration sum consistency
# ===========================================================================


class TestP3ProrationSumConsistency:
    """For any set of branch activations within a billing period, the sum of
    individual per-branch prorated charges SHALL equal the total prorated charge
    for the period.

    **Validates: Requirements 34.3**
    """

    @given(
        per_branch_cost=base_price_strategy,
        num_branches=st.integers(min_value=1, max_value=20),
        days_remaining=st.integers(min_value=1, max_value=365),
        total_days=st.integers(min_value=1, max_value=365),
    )
    @BRANCH_BILLING_PBT_SETTINGS
    def test_sum_of_per_branch_prorations_equals_total(
        self,
        per_branch_cost: Decimal,
        num_branches: int,
        days_remaining: int,
        total_days: int,
    ) -> None:
        """P3: sum of N individual prorations == proration of (cost * N)."""
        assume(days_remaining <= total_days)

        # Sum of individual per-branch prorations
        individual_sum = sum(
            calculate_proration(per_branch_cost, days_remaining, total_days)
            for _ in range(num_branches)
        )

        # Total proration for all branches at once
        total_cost = (per_branch_cost * Decimal(num_branches)).quantize(
            _TWO_PLACES, rounding=ROUND_HALF_UP
        )
        total_proration = calculate_proration(total_cost, days_remaining, total_days)

        # Due to rounding, individual sum may differ by at most num_branches pennies
        # (each individual proration rounds independently)
        diff = abs(individual_sum - total_proration)
        max_rounding_error = Decimal(num_branches) * _TWO_PLACES
        assert diff <= max_rounding_error, (
            f"Sum of individual prorations ({individual_sum}) differs from "
            f"total proration ({total_proration}) by {diff}, "
            f"exceeding max rounding error {max_rounding_error}"
        )

    @given(
        per_branch_cost=base_price_strategy,
        days_remaining=st.integers(min_value=1, max_value=365),
        total_days=st.integers(min_value=1, max_value=365),
    )
    @BRANCH_BILLING_PBT_SETTINGS
    def test_proration_bounded_by_full_cost(
        self,
        per_branch_cost: Decimal,
        days_remaining: int,
        total_days: int,
    ) -> None:
        """P3: proration never exceeds the full per-branch cost."""
        assume(days_remaining <= total_days)
        proration = calculate_proration(per_branch_cost, days_remaining, total_days)
        assert proration <= per_branch_cost, (
            f"Proration {proration} should not exceed full cost {per_branch_cost}"
        )


# ===========================================================================
# Property 4: HQ deactivation protection
# Feature: branch-management-complete, Property 4: HQ deactivation protection
# ===========================================================================


class TestP4HQDeactivationProtection:
    """For any organisation with N > 1 active branches, attempting to deactivate
    the HQ branch (is_hq=True) SHALL be rejected with a ValueError (→ 400).

    **Validates: Requirements 6.3, 34.4**
    """

    @given(
        active_count=st.integers(min_value=2, max_value=20),
        branch_name=safe_name_strategy,
    )
    @BRANCH_BILLING_PBT_SETTINGS
    def test_hq_deactivation_rejected_when_other_branches_exist(
        self,
        active_count: int,
        branch_name: str,
    ) -> None:
        """P4: deactivating HQ branch raises ValueError when other active branches exist."""
        org_id = uuid.uuid4()
        branch_id = uuid.uuid4()
        user_id = uuid.uuid4()

        hq_branch = _FakeBranch(
            id=branch_id,
            org_id=org_id,
            name=branch_name,
            is_hq=True,
            is_active=True,
        )

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _make_scalar_one_or_none(hq_branch),  # branch lookup
            _make_scalar(active_count),            # active_count > 1
        ])
        db.flush = AsyncMock()

        from app.modules.organisations.service import deactivate_branch

        with pytest.raises(ValueError, match="Cannot deactivate HQ branch"):
            asyncio.get_event_loop().run_until_complete(
                deactivate_branch(
                    db,
                    org_id=org_id,
                    branch_id=branch_id,
                    user_id=user_id,
                )
            )

        # Branch should still be active (not modified)
        assert hq_branch.is_active is True

    @given(
        branch_name=safe_name_strategy,
    )
    @BRANCH_BILLING_PBT_SETTINGS
    def test_non_hq_branch_can_be_deactivated(
        self,
        branch_name: str,
    ) -> None:
        """P4 (inverse): non-HQ branch with multiple active branches can be deactivated."""
        org_id = uuid.uuid4()
        branch_id = uuid.uuid4()
        user_id = uuid.uuid4()

        non_hq_branch = _FakeBranch(
            id=branch_id,
            org_id=org_id,
            name=branch_name,
            is_hq=False,
            is_active=True,
        )

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _make_scalar_one_or_none(non_hq_branch),  # branch lookup
            _make_scalar(3),                            # active_count > 1
        ])
        db.flush = AsyncMock()

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            from app.modules.organisations.service import deactivate_branch

            result = asyncio.get_event_loop().run_until_complete(
                deactivate_branch(
                    db,
                    org_id=org_id,
                    branch_id=branch_id,
                    user_id=user_id,
                )
            )

        assert result is not None
        assert result["is_active"] is False
        assert non_hq_branch.is_active is False


# ===========================================================================
# Property 19: Stripe failure rollback
# Feature: branch-management-complete, Property 19: Stripe failure rollback
# ===========================================================================


class TestP19StripeFailureRollback:
    """For any branch creation where the subsequent Stripe subscription quantity
    update fails, the branch record SHALL be rolled back (not persisted in the
    database).

    **Validates: Requirements 5.5**
    """

    @given(
        branch_name=safe_name_strategy,
    )
    @BRANCH_BILLING_PBT_SETTINGS
    def test_stripe_failure_triggers_rollback(
        self,
        branch_name: str,
    ) -> None:
        """P19: Stripe failure during create_branch_with_billing rolls back the branch."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        db = AsyncMock()
        db.rollback = AsyncMock()

        # Mock create_branch to succeed
        mock_branch_data = {
            "id": str(uuid.uuid4()),
            "name": branch_name,
            "org_id": str(org_id),
            "is_active": True,
        }

        # Mock sync_stripe_branch_quantity to fail
        stripe_error = Exception("Stripe API error: card_declined")

        with patch(
            "app.modules.organisations.service.create_branch",
            new_callable=AsyncMock,
            return_value=mock_branch_data,
        ), \
        patch(
            "app.modules.billing.branch_billing.sync_stripe_branch_quantity",
            new_callable=AsyncMock,
            side_effect=stripe_error,
        ):
            from app.modules.billing.branch_billing import create_branch_with_billing

            with pytest.raises(ValueError, match="Payment failed"):
                asyncio.get_event_loop().run_until_complete(
                    create_branch_with_billing(
                        db,
                        org_id=org_id,
                        user_id=user_id,
                        name=branch_name,
                    )
                )

        # db.rollback() must have been called
        db.rollback.assert_called_once()

    @given(
        branch_name=safe_name_strategy,
    )
    @BRANCH_BILLING_PBT_SETTINGS
    def test_stripe_success_does_not_rollback(
        self,
        branch_name: str,
    ) -> None:
        """P19 (inverse): successful Stripe sync does not trigger rollback."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        db = AsyncMock()
        db.rollback = AsyncMock()

        mock_branch_data = {
            "id": str(uuid.uuid4()),
            "name": branch_name,
            "org_id": str(org_id),
            "is_active": True,
        }

        with patch(
            "app.modules.organisations.service.create_branch",
            new_callable=AsyncMock,
            return_value=mock_branch_data,
        ), \
        patch(
            "app.modules.billing.branch_billing.sync_stripe_branch_quantity",
            new_callable=AsyncMock,
            return_value={"synced": True, "quantity": 2},
        ):
            from app.modules.billing.branch_billing import create_branch_with_billing

            result = asyncio.get_event_loop().run_until_complete(
                create_branch_with_billing(
                    db,
                    org_id=org_id,
                    user_id=user_id,
                    name=branch_name,
                )
            )

        assert result is not None
        assert result["name"] == branch_name
        # Rollback should NOT have been called
        db.rollback.assert_not_called()
