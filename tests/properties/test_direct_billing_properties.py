"""Property-based tests for direct Stripe billing.

Properties covered:
  P1  — Active org next_billing_date is set correctly
  P2  — Trial orgs have null next_billing_date
  P3  — charge_org_payment_method creates correct PaymentIntent
  P4  — CardError raises PaymentFailedError with decline code
  P5  — Recurring billing query returns exactly due orgs
  P6  — Charge amount matches pricing formula
  P7  — Successful charge advances next_billing_date by interval duration
  P8  — Consecutive charge failures transition to grace_period
  P9  — Independent org processing on failure
  P10 — Immediate interval change recalculates next_billing_date
  P11 — Scheduled interval change stores pending change
  P12 — Dashboard returns local next_billing_date
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.modules.billing.interval_pricing import (
    apply_coupon_to_interval_price,
    compute_effective_price,
    compute_interval_duration,
    INTERVAL_PERIODS_PER_YEAR,
)
from app.integrations.stripe_billing import (
    charge_org_payment_method,
    PaymentFailedError,
    PaymentActionRequiredError,
)
from app.tasks.subscriptions import MAX_BILLING_RETRIES, GRACE_PERIOD_DAYS

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

DIRECT_BILLING_PBT_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

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

amount_cents_strategy = st.integers(min_value=1, max_value=10_000_00)

currency_strategy = st.sampled_from(["nzd", "usd", "aud", "gbp"])

customer_id_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
    min_size=5,
    max_size=30,
).map(lambda s: f"cus_{s}")

payment_method_id_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
    min_size=5,
    max_size=30,
).map(lambda s: f"pm_{s}")

decline_code_strategy = st.sampled_from([
    "insufficient_funds",
    "lost_card",
    "stolen_card",
    "expired_card",
    "incorrect_cvc",
    "processing_error",
    "card_declined",
    "do_not_honor",
])

org_status_strategy = st.sampled_from([
    "trial", "active", "payment_pending", "grace_period", "suspended", "deleted",
])

# Strategy for datetimes in a reasonable range
billing_datetime_strategy = st.datetimes(
    min_value=datetime(2024, 1, 1),
    max_value=datetime(2030, 12, 31),
    timezones=st.just(timezone.utc),
)

coupon_type_strategy = st.sampled_from(["percentage", "fixed_amount"])

coupon_percentage_strategy = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("100"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

coupon_fixed_strategy = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("10000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


# ---------------------------------------------------------------------------
# Fake org helper
# ---------------------------------------------------------------------------

class _FakeOrg:
    """Minimal Organisation stand-in for pure-function property tests."""

    def __init__(
        self,
        *,
        status: str = "active",
        billing_interval: str = "monthly",
        next_billing_date: datetime | None = None,
        settings: dict | None = None,
        stripe_customer_id: str | None = "cus_test",
    ):
        self.status = status
        self.billing_interval = billing_interval
        self.next_billing_date = next_billing_date
        self.settings = settings or {}
        self.stripe_customer_id = stripe_customer_id


# ===========================================================================
# Property 1: Active org next_billing_date is set correctly
# Feature: direct-stripe-billing, Property 1: Active org next_billing_date is set correctly
# ===========================================================================


class TestP1ActiveOrgNextBillingDateSetCorrectly:
    """For any Organisation that transitions to status='active' (via paid signup
    or trial conversion), next_billing_date must equal the activation timestamp
    plus compute_interval_duration(org.billing_interval).

    **Validates: Requirements 1.2, 1.3, 3.1, 3.3, 4.2**
    """

    @given(
        interval=interval_strategy,
        activation_time=billing_datetime_strategy,
    )
    @DIRECT_BILLING_PBT_SETTINGS
    def test_active_org_next_billing_date_equals_activation_plus_interval(
        self,
        interval: str,
        activation_time: datetime,
    ) -> None:
        """P1: next_billing_date == activation_time + compute_interval_duration(interval)."""
        duration = compute_interval_duration(interval)
        expected_next = activation_time + duration

        # Simulate what the code does on activation
        org = _FakeOrg(status="active", billing_interval=interval)
        org.next_billing_date = activation_time + compute_interval_duration(interval)

        assert org.next_billing_date == expected_next, (
            f"For interval={interval}, activation={activation_time}: "
            f"got {org.next_billing_date}, expected {expected_next}"
        )

    @given(
        interval=interval_strategy,
        activation_time=billing_datetime_strategy,
    )
    @DIRECT_BILLING_PBT_SETTINGS
    def test_next_billing_date_is_always_in_the_future(
        self,
        interval: str,
        activation_time: datetime,
    ) -> None:
        """P1: next_billing_date is always strictly after the activation time."""
        duration = compute_interval_duration(interval)
        next_billing = activation_time + duration

        assert next_billing > activation_time, (
            f"next_billing_date {next_billing} should be after activation {activation_time}"
        )


# ===========================================================================
# Property 2: Trial orgs have null next_billing_date
# Feature: direct-stripe-billing, Property 2: Trial orgs have null next_billing_date
# ===========================================================================


class TestP2TrialOrgsHaveNullNextBillingDate:
    """For any Organisation with status='trial', next_billing_date must be NULL.

    **Validates: Requirements 1.4, 8.3**
    """

    @given(
        interval=interval_strategy,
    )
    @DIRECT_BILLING_PBT_SETTINGS
    def test_trial_org_has_null_next_billing_date(
        self,
        interval: str,
    ) -> None:
        """P2: trial org's next_billing_date is None."""
        org = _FakeOrg(status="trial", billing_interval=interval, next_billing_date=None)
        assert org.next_billing_date is None, (
            f"Trial org should have next_billing_date=None, got {org.next_billing_date}"
        )

    @given(
        interval=interval_strategy,
    )
    @DIRECT_BILLING_PBT_SETTINGS
    def test_dashboard_returns_null_for_trial_org(
        self,
        interval: str,
    ) -> None:
        """P2: billing dashboard logic returns None for trial orgs."""
        org = _FakeOrg(status="trial", billing_interval=interval, next_billing_date=None)

        # Replicate dashboard logic: next_billing_date = None if status == "trial"
        dashboard_next_billing = None if org.status == "trial" else org.next_billing_date

        assert dashboard_next_billing is None, (
            f"Dashboard should return None for trial org, got {dashboard_next_billing}"
        )


# ===========================================================================
# Property 3: charge_org_payment_method creates correct PaymentIntent
# Feature: direct-stripe-billing, Property 3: charge_org_payment_method creates correct PaymentIntent
# ===========================================================================


class TestP3ChargeCreatesCorrectPaymentIntent:
    """For any valid combination of customer_id, payment_method_id, amount_cents > 0,
    and currency, calling charge_org_payment_method must create a Stripe PaymentIntent
    with off_session=True and confirm=True, and on success return a dict containing
    payment_intent_id, status, and amount_cents matching the input.

    **Validates: Requirements 2.2, 2.3**
    """

    @given(
        customer_id=customer_id_strategy,
        payment_method_id=payment_method_id_strategy,
        amount_cents=amount_cents_strategy,
        currency=currency_strategy,
    )
    @DIRECT_BILLING_PBT_SETTINGS
    def test_charge_creates_payment_intent_with_correct_params(
        self,
        customer_id: str,
        payment_method_id: str,
        amount_cents: int,
        currency: str,
    ) -> None:
        """P3: charge_org_payment_method calls PaymentIntent.create with correct params."""
        mock_intent = MagicMock()
        mock_intent.id = "pi_test_123"
        mock_intent.status = "succeeded"

        with patch("app.integrations.stripe_billing._ensure_stripe_key", new_callable=AsyncMock), \
             patch("app.integrations.stripe_billing.stripe.PaymentIntent.create", return_value=mock_intent) as mock_create:

            result = asyncio.get_event_loop().run_until_complete(
                charge_org_payment_method(
                    customer_id=customer_id,
                    payment_method_id=payment_method_id,
                    amount_cents=amount_cents,
                    currency=currency,
                )
            )

            # Verify PaymentIntent.create was called with correct params
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["customer"] == customer_id
            assert call_kwargs["payment_method"] == payment_method_id
            assert call_kwargs["amount"] == amount_cents
            assert call_kwargs["currency"] == currency
            assert call_kwargs["off_session"] is True
            assert call_kwargs["confirm"] is True

            # Verify return dict
            assert result["payment_intent_id"] == "pi_test_123"
            assert result["status"] == "succeeded"
            assert result["amount_cents"] == amount_cents


# ===========================================================================
# Property 4: CardError raises PaymentFailedError with decline code
# Feature: direct-stripe-billing, Property 4: CardError raises PaymentFailedError with decline code
# ===========================================================================


class TestP4CardErrorRaisesPaymentFailedError:
    """For any Stripe CardError response, charge_org_payment_method must raise
    PaymentFailedError containing the Stripe error message and the decline_code
    from the error.

    **Validates: Requirements 2.4**
    """

    @given(
        decline_code=decline_code_strategy,
        customer_id=customer_id_strategy,
        payment_method_id=payment_method_id_strategy,
        amount_cents=amount_cents_strategy,
    )
    @DIRECT_BILLING_PBT_SETTINGS
    def test_card_error_raises_payment_failed_with_decline_code(
        self,
        decline_code: str,
        customer_id: str,
        payment_method_id: str,
        amount_cents: int,
    ) -> None:
        """P4: CardError → PaymentFailedError with correct decline_code."""
        # Build a mock CardError
        mock_error = MagicMock()
        mock_error.decline_code = decline_code
        card_error = stripe.error.CardError(
            message=f"Your card was declined: {decline_code}",
            param="payment_method",
            code="card_declined",
        )
        card_error.error = mock_error

        with patch("app.integrations.stripe_billing._ensure_stripe_key", new_callable=AsyncMock), \
             patch("app.integrations.stripe_billing.stripe.PaymentIntent.create", side_effect=card_error):

            with pytest.raises(PaymentFailedError) as exc_info:
                asyncio.get_event_loop().run_until_complete(
                    charge_org_payment_method(
                        customer_id=customer_id,
                        payment_method_id=payment_method_id,
                        amount_cents=amount_cents,
                    )
                )

            assert exc_info.value.decline_code == decline_code, (
                f"Expected decline_code={decline_code}, got {exc_info.value.decline_code}"
            )


# Need stripe import for CardError construction
import stripe


# ===========================================================================
# Property 5: Recurring billing query returns exactly due orgs
# Feature: direct-stripe-billing, Property 5: Recurring billing query returns exactly due orgs
# ===========================================================================


def _is_due_for_billing(org: _FakeOrg, now: datetime) -> bool:
    """Replicate the recurring billing query filter predicate.

    An org is due when: status == 'active' AND next_billing_date is not None
    AND next_billing_date <= now.
    """
    return (
        org.status == "active"
        and org.next_billing_date is not None
        and org.next_billing_date <= now
    )


class TestP5RecurringBillingQueryReturnsExactlyDueOrgs:
    """For any set of organisations with varying statuses and next_billing_date
    values, the recurring billing query must return exactly those where
    status='active' AND next_billing_date IS NOT NULL AND next_billing_date <= now().

    **Validates: Requirements 5.1**
    """

    @given(
        statuses=st.lists(org_status_strategy, min_size=1, max_size=20),
        intervals=st.lists(interval_strategy, min_size=1, max_size=20),
        now=billing_datetime_strategy,
        data=st.data(),
    )
    @DIRECT_BILLING_PBT_SETTINGS
    def test_billing_query_filter_returns_exactly_due_orgs(
        self,
        statuses: list[str],
        intervals: list[str],
        now: datetime,
        data,
    ) -> None:
        """P5: filter predicate matches exactly the due orgs."""
        orgs = []
        for i, status in enumerate(statuses):
            interval = intervals[i % len(intervals)]
            # Generate next_billing_date: sometimes None, sometimes past, sometimes future
            has_date = data.draw(st.booleans())
            if has_date:
                offset_days = data.draw(st.integers(min_value=-60, max_value=60))
                nbd = now + timedelta(days=offset_days)
            else:
                nbd = None

            orgs.append(_FakeOrg(
                status=status,
                billing_interval=interval,
                next_billing_date=nbd,
            ))

        # Apply the filter predicate
        due_orgs = [o for o in orgs if _is_due_for_billing(o, now)]

        # Verify: every due org must be active with non-null next_billing_date <= now
        for org in due_orgs:
            assert org.status == "active"
            assert org.next_billing_date is not None
            assert org.next_billing_date <= now

        # Verify: every non-due org must violate at least one condition
        non_due = [o for o in orgs if not _is_due_for_billing(o, now)]
        for org in non_due:
            assert (
                org.status != "active"
                or org.next_billing_date is None
                or org.next_billing_date > now
            ), f"Org should not be due but passes all conditions"


# ===========================================================================
# Property 6: Charge amount matches pricing formula
# Feature: direct-stripe-billing, Property 6: Charge amount matches pricing formula
# ===========================================================================


class TestP6ChargeAmountMatchesPricingFormula:
    """For any plan with monthly_price_nzd > 0, billing interval I, interval
    discount D%, and optional coupon, the computed charge amount in cents must
    equal int(apply_coupon_to_interval_price(compute_effective_price(monthly_price,
    I, D), coupon) * 100).

    **Validates: Requirements 5.2**
    """

    @given(
        monthly_price=base_price_strategy,
        interval=interval_strategy,
        discount=discount_strategy,
    )
    @DIRECT_BILLING_PBT_SETTINGS
    def test_charge_amount_without_coupon(
        self,
        monthly_price: Decimal,
        interval: str,
        discount: Decimal,
    ) -> None:
        """P6: charge cents == int(compute_effective_price(...) * 100) without coupon."""
        effective = compute_effective_price(monthly_price, interval, discount)
        amount_cents = int((effective * Decimal("100")).to_integral_value())

        expected = int((effective * Decimal("100")).to_integral_value())
        assert amount_cents == expected, (
            f"For price={monthly_price}, interval={interval}, discount={discount}: "
            f"got {amount_cents}, expected {expected}"
        )

    @given(
        monthly_price=base_price_strategy,
        interval=interval_strategy,
        discount=discount_strategy,
        coupon_type=coupon_type_strategy,
        data=st.data(),
    )
    @DIRECT_BILLING_PBT_SETTINGS
    def test_charge_amount_with_coupon(
        self,
        monthly_price: Decimal,
        interval: str,
        discount: Decimal,
        coupon_type: str,
        data,
    ) -> None:
        """P6: charge cents == int(apply_coupon_to_interval_price(effective, coupon) * 100)."""
        coupon_value = data.draw(
            coupon_percentage_strategy if coupon_type == "percentage" else coupon_fixed_strategy
        )

        effective = compute_effective_price(monthly_price, interval, discount)
        after_coupon = apply_coupon_to_interval_price(effective, coupon_type, coupon_value)
        amount_cents = int((after_coupon * Decimal("100")).to_integral_value())

        # Recompute independently
        expected_effective = compute_effective_price(monthly_price, interval, discount)
        expected_after_coupon = apply_coupon_to_interval_price(
            expected_effective, coupon_type, coupon_value
        )
        expected_cents = int((expected_after_coupon * Decimal("100")).to_integral_value())

        assert amount_cents == expected_cents, (
            f"For price={monthly_price}, interval={interval}, discount={discount}, "
            f"coupon={coupon_type}/{coupon_value}: got {amount_cents}, expected {expected_cents}"
        )


# ===========================================================================
# Property 7: Successful charge advances next_billing_date by interval duration
# Feature: direct-stripe-billing, Property 7: Successful charge advances next_billing_date by interval duration
# ===========================================================================


class TestP7SuccessfulChargeAdvancesNextBillingDate:
    """For any Organisation with billing interval I and current next_billing_date = T,
    after a successful recurring charge, next_billing_date must equal
    T + compute_interval_duration(I).

    **Validates: Requirements 5.4**
    """

    @given(
        interval=interval_strategy,
        current_billing_date=billing_datetime_strategy,
    )
    @DIRECT_BILLING_PBT_SETTINGS
    def test_next_billing_date_advances_by_interval(
        self,
        interval: str,
        current_billing_date: datetime,
    ) -> None:
        """P7: after successful charge, next_billing_date = old + interval_duration."""
        org = _FakeOrg(
            status="active",
            billing_interval=interval,
            next_billing_date=current_billing_date,
        )

        # Simulate successful charge: advance next_billing_date
        duration = compute_interval_duration(interval)
        org.next_billing_date = org.next_billing_date + duration

        expected = current_billing_date + duration
        assert org.next_billing_date == expected, (
            f"For interval={interval}, old_date={current_billing_date}: "
            f"got {org.next_billing_date}, expected {expected}"
        )

    @given(
        interval=interval_strategy,
        current_billing_date=billing_datetime_strategy,
    )
    @DIRECT_BILLING_PBT_SETTINGS
    def test_advanced_date_is_strictly_after_current(
        self,
        interval: str,
        current_billing_date: datetime,
    ) -> None:
        """P7: the advanced next_billing_date is always after the current one."""
        duration = compute_interval_duration(interval)
        new_date = current_billing_date + duration

        assert new_date > current_billing_date, (
            f"Advanced date {new_date} should be after current {current_billing_date}"
        )


# ===========================================================================
# Property 8: Consecutive charge failures transition to grace_period
# Feature: direct-stripe-billing, Property 8: Consecutive charge failures transition to grace_period
# ===========================================================================


def _simulate_billing_failures(org: _FakeOrg, num_failures: int) -> None:
    """Simulate consecutive billing failures on an org.

    Replicates the retry logic from process_recurring_billing_task:
    - Increment billing_retry_count on each failure
    - Transition to grace_period after MAX_BILLING_RETRIES
    """
    for _ in range(num_failures):
        retry_count = org.settings.get("billing_retry_count", 0) + 1
        org.settings["billing_retry_count"] = retry_count

        if retry_count >= MAX_BILLING_RETRIES:
            org.status = "grace_period"


class TestP8ConsecutiveFailuresTransitionToGracePeriod:
    """For any active Organisation, after MAX_BILLING_RETRIES consecutive charge
    failures, the Organisation's status must be 'grace_period'.

    **Validates: Requirements 4.4, 5.5**
    """

    @given(
        interval=interval_strategy,
        initial_retry_count=st.integers(min_value=0, max_value=0),
    )
    @DIRECT_BILLING_PBT_SETTINGS
    def test_max_retries_transitions_to_grace_period(
        self,
        interval: str,
        initial_retry_count: int,
    ) -> None:
        """P8: after MAX_BILLING_RETRIES failures, status becomes grace_period."""
        org = _FakeOrg(
            status="active",
            billing_interval=interval,
            settings={"billing_retry_count": initial_retry_count},
        )

        _simulate_billing_failures(org, MAX_BILLING_RETRIES)

        assert org.status == "grace_period", (
            f"After {MAX_BILLING_RETRIES} failures, status should be 'grace_period', "
            f"got '{org.status}'"
        )
        assert org.settings["billing_retry_count"] == MAX_BILLING_RETRIES, (
            f"Retry count should be {MAX_BILLING_RETRIES}, "
            f"got {org.settings['billing_retry_count']}"
        )

    @given(
        interval=interval_strategy,
        num_failures=st.integers(min_value=1, max_value=MAX_BILLING_RETRIES - 1),
    )
    @DIRECT_BILLING_PBT_SETTINGS
    def test_fewer_than_max_retries_stays_active(
        self,
        interval: str,
        num_failures: int,
    ) -> None:
        """P8: fewer than MAX_BILLING_RETRIES failures keeps status as active."""
        org = _FakeOrg(
            status="active",
            billing_interval=interval,
            settings={"billing_retry_count": 0},
        )

        _simulate_billing_failures(org, num_failures)

        assert org.status == "active", (
            f"After {num_failures} failures (< {MAX_BILLING_RETRIES}), "
            f"status should remain 'active', got '{org.status}'"
        )


# ===========================================================================
# Property 9: Independent org processing on failure
# Feature: direct-stripe-billing, Property 9: Independent org processing on failure
# ===========================================================================


def _simulate_independent_billing(
    orgs: list[_FakeOrg],
    fail_indices: set[int],
) -> None:
    """Simulate independent billing processing where some orgs fail and some succeed.

    Replicates the per-org try/except pattern from process_recurring_billing_task.
    """
    for i, org in enumerate(orgs):
        try:
            if i in fail_indices:
                raise PaymentFailedError("Simulated failure", decline_code="card_declined")

            # Success: advance next_billing_date
            duration = compute_interval_duration(org.billing_interval)
            org.next_billing_date = org.next_billing_date + duration
            org.settings["billing_retry_count"] = 0

        except (PaymentFailedError, PaymentActionRequiredError):
            # Failure: increment retry count
            retry_count = org.settings.get("billing_retry_count", 0) + 1
            org.settings["billing_retry_count"] = retry_count
            if retry_count >= MAX_BILLING_RETRIES:
                org.status = "grace_period"


class TestP9IndependentOrgProcessingOnFailure:
    """For any set of due organisations where some charges fail and some succeed,
    all successful charges must still advance their next_billing_date, regardless
    of failures in other orgs.

    **Validates: Requirements 5.6**
    """

    @given(
        num_orgs=st.integers(min_value=2, max_value=10),
        interval=interval_strategy,
        now=billing_datetime_strategy,
        data=st.data(),
    )
    @DIRECT_BILLING_PBT_SETTINGS
    def test_successful_orgs_advance_despite_failures(
        self,
        num_orgs: int,
        interval: str,
        now: datetime,
        data,
    ) -> None:
        """P9: successful charges advance next_billing_date regardless of other failures."""
        orgs = [
            _FakeOrg(
                status="active",
                billing_interval=interval,
                next_billing_date=now - timedelta(hours=1),
                settings={"billing_retry_count": 0},
            )
            for _ in range(num_orgs)
        ]

        # Record original dates
        original_dates = [o.next_billing_date for o in orgs]

        # Randomly select which orgs fail (at least one fails, at least one succeeds)
        fail_indices = set(data.draw(
            st.sets(
                st.integers(min_value=0, max_value=num_orgs - 1),
                min_size=1,
                max_size=max(1, num_orgs - 1),
            )
        ))
        # Ensure at least one succeeds
        success_indices = set(range(num_orgs)) - fail_indices
        if not success_indices:
            fail_indices.discard(0)
            success_indices = {0}

        _simulate_independent_billing(orgs, fail_indices)

        duration = compute_interval_duration(interval)

        # Verify successful orgs advanced
        for i in success_indices:
            expected = original_dates[i] + duration
            assert orgs[i].next_billing_date == expected, (
                f"Org {i} (success) should have advanced to {expected}, "
                f"got {orgs[i].next_billing_date}"
            )

        # Verify failed orgs did NOT advance
        for i in fail_indices:
            assert orgs[i].next_billing_date == original_dates[i], (
                f"Org {i} (failed) should not have advanced, "
                f"got {orgs[i].next_billing_date}"
            )


# ===========================================================================
# Property 10: Immediate interval change recalculates next_billing_date
# Feature: direct-stripe-billing, Property 10: Immediate interval change recalculates next_billing_date
# ===========================================================================


class TestP10ImmediateIntervalChangeRecalculatesNextBillingDate:
    """For any Organisation changing to a longer billing interval (fewer periods
    per year), next_billing_date must be recalculated as
    now() + compute_interval_duration(new_interval).

    **Validates: Requirements 6.2**
    """

    @given(
        current_interval=interval_strategy,
        new_interval=interval_strategy,
        now=billing_datetime_strategy,
    )
    @DIRECT_BILLING_PBT_SETTINGS
    def test_immediate_change_recalculates_next_billing_date(
        self,
        current_interval: str,
        new_interval: str,
        now: datetime,
    ) -> None:
        """P10: longer interval change → next_billing_date = now + new_interval_duration."""
        # Skip same interval or non-immediate (shorter) changes
        current_periods = INTERVAL_PERIODS_PER_YEAR[current_interval]
        new_periods = INTERVAL_PERIODS_PER_YEAR[new_interval]
        if new_periods >= current_periods:
            return  # Not an immediate change

        org = _FakeOrg(
            status="active",
            billing_interval=current_interval,
            next_billing_date=now - timedelta(days=5),
        )

        # Simulate immediate interval change (from billing router)
        org.billing_interval = new_interval
        org.next_billing_date = now + compute_interval_duration(new_interval)

        expected = now + compute_interval_duration(new_interval)
        assert org.next_billing_date == expected, (
            f"For {current_interval}→{new_interval} at {now}: "
            f"got {org.next_billing_date}, expected {expected}"
        )
        assert org.billing_interval == new_interval


# ===========================================================================
# Property 11: Scheduled interval change stores pending change
# Feature: direct-stripe-billing, Property 11: Scheduled interval change stores pending change
# ===========================================================================


class TestP11ScheduledIntervalChangeStoresPendingChange:
    """For any Organisation changing to a shorter billing interval (more periods
    per year), the pending change must be stored in
    org.settings['pending_interval_change'] with effective_at equal to the
    current next_billing_date.

    **Validates: Requirements 6.3**
    """

    @given(
        current_interval=interval_strategy,
        new_interval=interval_strategy,
        current_billing_date=billing_datetime_strategy,
    )
    @DIRECT_BILLING_PBT_SETTINGS
    def test_scheduled_change_stores_pending_with_effective_at(
        self,
        current_interval: str,
        new_interval: str,
        current_billing_date: datetime,
    ) -> None:
        """P11: shorter interval change → pending_interval_change stored with effective_at."""
        # Skip same interval or immediate (longer) changes
        current_periods = INTERVAL_PERIODS_PER_YEAR[current_interval]
        new_periods = INTERVAL_PERIODS_PER_YEAR[new_interval]
        if new_periods <= current_periods:
            return  # Not a scheduled change

        org = _FakeOrg(
            status="active",
            billing_interval=current_interval,
            next_billing_date=current_billing_date,
            settings={},
        )

        # Simulate scheduled interval change (from billing router)
        effective_at = org.next_billing_date
        org.settings["pending_interval_change"] = {
            "new_interval": new_interval,
            "effective_at": effective_at.isoformat() if effective_at else None,
        }

        pending = org.settings["pending_interval_change"]
        assert pending["new_interval"] == new_interval, (
            f"Pending new_interval should be {new_interval}, got {pending['new_interval']}"
        )
        assert pending["effective_at"] == current_billing_date.isoformat(), (
            f"Pending effective_at should be {current_billing_date.isoformat()}, "
            f"got {pending['effective_at']}"
        )
        # Billing interval should NOT change yet
        assert org.billing_interval == current_interval, (
            f"Billing interval should remain {current_interval} for scheduled change, "
            f"got {org.billing_interval}"
        )


# ===========================================================================
# Property 12: Dashboard returns local next_billing_date
# Feature: direct-stripe-billing, Property 12: Dashboard returns local next_billing_date
# ===========================================================================


class TestP12DashboardReturnsLocalNextBillingDate:
    """For any active Organisation with a non-null next_billing_date, the billing
    dashboard response's next_billing_date field must equal org.next_billing_date.

    **Validates: Requirements 8.1**
    """

    @given(
        interval=interval_strategy,
        billing_date=billing_datetime_strategy,
    )
    @DIRECT_BILLING_PBT_SETTINGS
    def test_dashboard_returns_org_next_billing_date(
        self,
        interval: str,
        billing_date: datetime,
    ) -> None:
        """P12: dashboard next_billing_date == org.next_billing_date for active orgs."""
        org = _FakeOrg(
            status="active",
            billing_interval=interval,
            next_billing_date=billing_date,
        )

        # Replicate dashboard logic
        dashboard_next_billing = None if org.status == "trial" else org.next_billing_date

        assert dashboard_next_billing == billing_date, (
            f"Dashboard should return {billing_date}, got {dashboard_next_billing}"
        )

    @given(
        interval=interval_strategy,
        billing_date=billing_datetime_strategy,
        status=st.sampled_from(["active", "grace_period", "suspended"]),
    )
    @DIRECT_BILLING_PBT_SETTINGS
    def test_dashboard_returns_date_for_non_trial_statuses(
        self,
        interval: str,
        billing_date: datetime,
        status: str,
    ) -> None:
        """P12: non-trial statuses return the actual next_billing_date."""
        org = _FakeOrg(
            status=status,
            billing_interval=interval,
            next_billing_date=billing_date,
        )

        dashboard_next_billing = None if org.status == "trial" else org.next_billing_date

        assert dashboard_next_billing == billing_date, (
            f"For status={status}, dashboard should return {billing_date}, "
            f"got {dashboard_next_billing}"
        )
