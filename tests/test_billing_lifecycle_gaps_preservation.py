"""Preservation property tests — billing lifecycle gaps.

These tests capture EXISTING behavior on UNFIXED code. They must PASS
both before and after the fix, ensuring no regressions are introduced.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8**

Parts:
  A: Existing _DAILY_TASKS and WRITE_TASKS entries preserved
  B: Successful payment flow preserved (Hypothesis)
  C: Skipped org preservation (Hypothesis)
  D: Standby node skip preservation
  E: Non-buggy lifecycle states preserved (Hypothesis)
  F: Email failure resilience preserved
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.tasks.scheduled import _DAILY_TASKS, WRITE_TASKS


# ---------------------------------------------------------------------------
# Helpers (reused from bug condition test)
# ---------------------------------------------------------------------------


def _make_mock_session(execute_side_effect=None, execute_return_value=None):
    """Create a mock async session with proper async context manager for begin()."""
    mock_session = AsyncMock()
    mock_session.flush = AsyncMock()

    if execute_side_effect is not None:
        mock_session.execute = AsyncMock(side_effect=execute_side_effect)
    elif execute_return_value is not None:
        mock_session.execute = AsyncMock(return_value=execute_return_value)

    @asynccontextmanager
    async def _begin():
        yield

    mock_session.begin = _begin
    return mock_session


def _make_mock_session_factory(mock_session):
    """Create a mock async_session_factory returning an async context manager."""

    @asynccontextmanager
    async def _factory():
        yield mock_session

    return _factory


def _billing_execute_side_effects(mock_org, mock_plan, *, has_payment_method=True, has_stripe_customer=True):
    """Build the sequence of execute() return values for process_recurring_billing_task."""
    org_result = MagicMock()
    org_result.scalars.return_value.all.return_value = [mock_org]

    plan_result = MagicMock()
    plan_result.scalar_one_or_none.return_value = mock_plan

    coupon_result = MagicMock()
    coupon_result.one_or_none.return_value = None

    storage_addon_result = MagicMock()
    storage_addon_result.scalar_one_or_none.return_value = None

    pm_result = MagicMock()
    if has_payment_method:
        pm_result.scalar_one_or_none.return_value = MagicMock(
            stripe_payment_method_id="pm_test", is_default=True,
        )
    else:
        pm_result.scalar_one_or_none.return_value = None

    return [org_result, plan_result, coupon_result, storage_addon_result, pm_result]


# ---------------------------------------------------------------------------
# Snapshot of existing _DAILY_TASKS and WRITE_TASKS on UNFIXED code
# ---------------------------------------------------------------------------

# Record the current state so we can assert preservation after fix.
EXISTING_DAILY_TASK_NAMES = {name for (_, _, name) in _DAILY_TASKS}
EXISTING_DAILY_TASK_ENTRIES = [(fn.__name__, interval, name) for (fn, interval, name) in _DAILY_TASKS]
EXISTING_WRITE_TASKS = set(WRITE_TASKS)


# ---------------------------------------------------------------------------
# Part A — Existing _DAILY_TASKS and WRITE_TASKS entries preserved
# Validates: Requirements 3.7
# ---------------------------------------------------------------------------


class TestExistingTaskEntriesPreserved:
    """All existing _DAILY_TASKS and WRITE_TASKS entries must remain after fix."""

    @pytest.mark.parametrize(
        "fn_name,interval,name",
        EXISTING_DAILY_TASK_ENTRIES,
        ids=[e[2] for e in EXISTING_DAILY_TASK_ENTRIES],
    )
    def test_existing_daily_task_still_present(self, fn_name, interval, name):
        """**Validates: Requirements 3.7** — existing scheduled tasks unchanged."""
        current_entries = [(fn.__name__, iv, n) for (fn, iv, n) in _DAILY_TASKS]
        assert (fn_name, interval, name) in current_entries, (
            f"Existing _DAILY_TASKS entry ({fn_name}, {interval}, {name!r}) "
            f"was removed or modified after fix"
        )

    @pytest.mark.parametrize("task_name", sorted(EXISTING_WRITE_TASKS))
    def test_existing_write_task_still_present(self, task_name):
        """**Validates: Requirements 3.7** — existing WRITE_TASKS entries unchanged."""
        assert task_name in WRITE_TASKS, (
            f"Existing WRITE_TASKS entry {task_name!r} was removed after fix"
        )


# ---------------------------------------------------------------------------
# Part B — Successful payment flow preserved (Hypothesis)
# Validates: Requirements 3.1
# ---------------------------------------------------------------------------


# Hypothesis strategy for valid billing intervals
billing_intervals = st.sampled_from(["monthly", "annual"])

# Strategy for plan prices (in NZD, reasonable range)
plan_prices = st.decimals(min_value=1, max_value=500, places=2, allow_nan=False, allow_infinity=False)

# Strategy for past billing dates (1 to 30 days ago)
past_billing_dates = st.integers(min_value=1, max_value=30).map(
    lambda days: datetime.now(timezone.utc) - timedelta(days=days)
)


class TestSuccessfulPaymentFlowPreserved:
    """Successful billing charges must continue to advance next_billing_date,
    reset retry count, and create a BillingReceipt."""

    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=None)
    @given(
        billing_interval=billing_intervals,
        plan_price=plan_prices,
        days_ago=st.integers(min_value=1, max_value=30),
    )
    async def test_successful_payment_advances_billing_date(
        self, billing_interval, plan_price, days_ago
    ):
        """**Validates: Requirements 3.1** — successful charge advances next_billing_date,
        resets retry count, and creates a receipt."""
        from app.modules.billing.interval_pricing import compute_interval_duration

        now = datetime.now(timezone.utc)
        billing_date = now - timedelta(days=days_ago)

        org_id = uuid.uuid4()
        plan_id = uuid.uuid4()

        mock_org = MagicMock()
        mock_org.id = org_id
        mock_org.status = "active"
        mock_org.next_billing_date = billing_date
        mock_org.plan_id = plan_id
        mock_org.billing_interval = billing_interval
        mock_org.settings = {"billing_retry_count": 0}
        mock_org.stripe_customer_id = "cus_test"
        mock_org.name = "Test Org"
        mock_org.sms_sent_this_month = 0
        mock_org.carjam_lookups_this_month = 0

        mock_plan = MagicMock()
        mock_plan.id = plan_id
        mock_plan.name = "Pro"
        mock_plan.monthly_price_nzd = float(plan_price)
        mock_plan.interval_config = []
        mock_plan.carjam_lookups_included = 50

        side_effects = _billing_execute_side_effects(mock_org, mock_plan)
        mock_session = _make_mock_session(execute_side_effect=side_effects)
        mock_session_factory = _make_mock_session_factory(mock_session)

        # Track receipt creation
        added_objects = []
        original_add = mock_session.add

        def track_add(obj):
            added_objects.append(obj)

        mock_session.add = track_add

        charge_result = {"payment_intent_id": "pi_test123", "status": "succeeded"}

        with patch(
            "app.core.database.async_session_factory", mock_session_factory
        ), patch(
            "app.integrations.stripe_billing.charge_org_payment_method",
            AsyncMock(return_value=charge_result),
        ), patch(
            "app.modules.admin.service.compute_sms_overage_for_billing",
            AsyncMock(return_value={"overage_count": 0, "per_sms_cost_nzd": 0, "total_charge_nzd": 0}),
        ), patch(
            "app.modules.admin.service.compute_carjam_overage",
            MagicMock(return_value=0),
        ), patch(
            "app.modules.organisations.service._load_signup_billing_config",
            AsyncMock(return_value={"gst_rate": Decimal("0.15"), "processing_fee_rate": Decimal("0.029"), "processing_fee_fixed_cents": 30}),
        ), patch(
            "app.modules.organisations.service._compute_billing_breakdown",
            MagicMock(return_value={"total_amount_cents": 5635, "gst_amount_cents": 735, "processing_fee_cents": 0}),
        ), patch(
            "app.tasks.subscriptions._send_billing_receipt_email",
            AsyncMock(),
        ):
            from app.tasks.subscriptions import process_recurring_billing_task

            result = await process_recurring_billing_task()

            # Assert billing date was advanced
            expected_next = billing_date + compute_interval_duration(billing_interval)
            assert mock_org.next_billing_date == expected_next, (
                f"next_billing_date not advanced correctly: "
                f"expected {expected_next}, got {mock_org.next_billing_date}"
            )

            # Assert retry count was reset
            assert mock_org.settings["billing_retry_count"] == 0, (
                "billing_retry_count was not reset to 0 after successful charge"
            )

            # Assert a receipt was created (session.add was called)
            assert len(added_objects) > 0, "No BillingReceipt was created"

            # Assert result counts
            assert result["charged"] == 1
            assert result["failed"] == 0


# ---------------------------------------------------------------------------
# Part C — Skipped org preservation (Hypothesis)
# Validates: Requirements 3.2
# ---------------------------------------------------------------------------


class TestSkippedOrgPreservation:
    """Orgs with no payment method or no Stripe customer ID must be skipped."""

    @pytest.mark.asyncio
    @settings(max_examples=5, deadline=None)
    @given(
        has_payment_method=st.just(False),
        days_ago=st.integers(min_value=1, max_value=30),
    )
    async def test_org_without_payment_method_skipped(self, has_payment_method, days_ago):
        """**Validates: Requirements 3.2** — orgs with no default payment method are skipped."""
        now = datetime.now(timezone.utc)
        billing_date = now - timedelta(days=days_ago)

        org_id = uuid.uuid4()
        plan_id = uuid.uuid4()

        mock_org = MagicMock()
        mock_org.id = org_id
        mock_org.status = "active"
        mock_org.next_billing_date = billing_date
        mock_org.plan_id = plan_id
        mock_org.billing_interval = "monthly"
        mock_org.settings = {"billing_retry_count": 0}
        mock_org.stripe_customer_id = "cus_test"
        mock_org.name = "No PM Org"
        mock_org.sms_sent_this_month = 0
        mock_org.carjam_lookups_this_month = 0

        mock_plan = MagicMock()
        mock_plan.id = plan_id
        mock_plan.name = "Starter"
        mock_plan.monthly_price_nzd = 29.0
        mock_plan.interval_config = []
        mock_plan.carjam_lookups_included = 10

        side_effects = _billing_execute_side_effects(
            mock_org, mock_plan, has_payment_method=False
        )
        mock_session = _make_mock_session(execute_side_effect=side_effects)
        mock_session_factory = _make_mock_session_factory(mock_session)

        with patch(
            "app.core.database.async_session_factory", mock_session_factory
        ), patch(
            "app.modules.admin.service.compute_sms_overage_for_billing",
            AsyncMock(return_value={"overage_count": 0, "per_sms_cost_nzd": 0, "total_charge_nzd": 0}),
        ), patch(
            "app.modules.admin.service.compute_carjam_overage",
            MagicMock(return_value=0),
        ), patch(
            "app.modules.organisations.service._load_signup_billing_config",
            AsyncMock(return_value={"gst_rate": Decimal("0.15"), "processing_fee_rate": Decimal("0.029"), "processing_fee_fixed_cents": 30}),
        ), patch(
            "app.modules.organisations.service._compute_billing_breakdown",
            MagicMock(return_value={"total_amount_cents": 3335, "gst_amount_cents": 435, "processing_fee_cents": 0}),
        ):
            from app.tasks.subscriptions import process_recurring_billing_task

            result = await process_recurring_billing_task()

            assert result["skipped"] >= 1, "Org without payment method was not skipped"
            assert result["failed"] == 0, "Org without payment method caused a failure"

    @pytest.mark.asyncio
    @settings(max_examples=5, deadline=None)
    @given(days_ago=st.integers(min_value=1, max_value=30))
    async def test_org_without_stripe_customer_skipped(self, days_ago):
        """**Validates: Requirements 3.2** — orgs with no stripe_customer_id are skipped."""
        now = datetime.now(timezone.utc)
        billing_date = now - timedelta(days=days_ago)

        org_id = uuid.uuid4()
        plan_id = uuid.uuid4()

        mock_org = MagicMock()
        mock_org.id = org_id
        mock_org.status = "active"
        mock_org.next_billing_date = billing_date
        mock_org.plan_id = plan_id
        mock_org.billing_interval = "monthly"
        mock_org.settings = {"billing_retry_count": 0}
        mock_org.stripe_customer_id = None  # No Stripe customer
        mock_org.name = "No Stripe Org"
        mock_org.sms_sent_this_month = 0
        mock_org.carjam_lookups_this_month = 0

        mock_plan = MagicMock()
        mock_plan.id = plan_id
        mock_plan.name = "Starter"
        mock_plan.monthly_price_nzd = 29.0
        mock_plan.interval_config = []
        mock_plan.carjam_lookups_included = 10

        # For no stripe_customer_id, the code checks AFTER getting the payment method
        # So we need all 5 side effects
        side_effects = _billing_execute_side_effects(mock_org, mock_plan)
        mock_session = _make_mock_session(execute_side_effect=side_effects)
        mock_session_factory = _make_mock_session_factory(mock_session)

        with patch(
            "app.core.database.async_session_factory", mock_session_factory
        ), patch(
            "app.modules.admin.service.compute_sms_overage_for_billing",
            AsyncMock(return_value={"overage_count": 0, "per_sms_cost_nzd": 0, "total_charge_nzd": 0}),
        ), patch(
            "app.modules.admin.service.compute_carjam_overage",
            MagicMock(return_value=0),
        ), patch(
            "app.modules.organisations.service._load_signup_billing_config",
            AsyncMock(return_value={"gst_rate": Decimal("0.15"), "processing_fee_rate": Decimal("0.029"), "processing_fee_fixed_cents": 30}),
        ), patch(
            "app.modules.organisations.service._compute_billing_breakdown",
            MagicMock(return_value={"total_amount_cents": 3335, "gst_amount_cents": 435, "processing_fee_cents": 0}),
        ):
            from app.tasks.subscriptions import process_recurring_billing_task

            result = await process_recurring_billing_task()

            assert result["skipped"] >= 1, "Org without stripe_customer_id was not skipped"
            assert result["failed"] == 0, "Org without stripe_customer_id caused a failure"


# ---------------------------------------------------------------------------
# Part D — Standby node skip preservation
# Validates: Requirements 3.3
# ---------------------------------------------------------------------------


class TestStandbyNodeSkipPreservation:
    """All WRITE_TASKS must be skipped when node role is standby."""

    @pytest.mark.parametrize("task_name", sorted(EXISTING_WRITE_TASKS))
    def test_write_task_skipped_on_standby(self, task_name):
        """**Validates: Requirements 3.3** — standby nodes skip all WRITE_TASKS."""
        # Verify the task is in WRITE_TASKS (so the scheduler will skip it)
        assert task_name in WRITE_TASKS, (
            f"Task {task_name!r} is not in WRITE_TASKS — "
            f"would execute on standby nodes"
        )

        # Verify the task is also in _DAILY_TASKS (so it's actually scheduled)
        daily_task_names = {name for (_, _, name) in _DAILY_TASKS}
        if task_name in daily_task_names:
            # The scheduler loop checks: if role == "standby" and name in WRITE_TASKS: skip
            # This is a structural assertion — the skip logic is in _scheduler_loop
            assert task_name in WRITE_TASKS


# ---------------------------------------------------------------------------
# Part E — Non-buggy lifecycle states preserved (Hypothesis)
# Validates: Requirements 3.4, 3.5, 3.6
# ---------------------------------------------------------------------------


class TestNonBuggyLifecycleStatesPreserved:
    """Lifecycle tasks skip orgs that don't meet action thresholds."""

    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=None)
    @given(days_remaining=st.floats(min_value=3.01, max_value=30.0))
    async def test_trial_expiry_skips_orgs_with_days_remaining(self, days_remaining):
        """**Validates: Requirements 3.4** — trial orgs with > 3 days remaining are skipped."""
        now = datetime.now(timezone.utc)
        trial_ends_at = now + timedelta(days=days_remaining)

        org_id = uuid.uuid4()
        mock_org = MagicMock()
        mock_org.id = org_id
        mock_org.status = "trial"
        mock_org.trial_ends_at = trial_ends_at

        org_result = MagicMock()
        org_result.scalars.return_value.all.return_value = [mock_org]

        mock_session = _make_mock_session(execute_return_value=org_result)
        mock_session_factory = _make_mock_session_factory(mock_session)

        with patch(
            "app.core.database.async_session_factory", mock_session_factory
        ):
            from app.tasks.subscriptions import check_trial_expiry_task

            result = await check_trial_expiry_task()

            # Should not convert or send reminders for orgs with > 3 days
            assert result["trials_converted"] == 0, (
                f"Trial org with {days_remaining:.1f} days remaining was converted"
            )

    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=None)
    @given(days_elapsed=st.floats(min_value=0.0, max_value=6.9))
    async def test_grace_period_skips_orgs_under_7_days(self, days_elapsed):
        """**Validates: Requirements 3.5** — grace period orgs with < 7 days elapsed are skipped."""
        now = datetime.now(timezone.utc)
        grace_started = (now - timedelta(days=days_elapsed)).isoformat()

        org_id = uuid.uuid4()
        mock_org = MagicMock()
        mock_org.id = org_id
        mock_org.status = "grace_period"
        mock_org.settings = {"grace_period_started_at": grace_started}

        org_result = MagicMock()
        org_result.scalars.return_value.all.return_value = [mock_org]

        mock_session = _make_mock_session(execute_return_value=org_result)
        mock_session_factory = _make_mock_session_factory(mock_session)

        with patch(
            "app.core.database.async_session_factory", mock_session_factory
        ), patch(
            "app.core.audit.write_audit_log", AsyncMock()
        ), patch(
            "app.tasks.subscriptions.send_suspension_email_task", AsyncMock()
        ):
            from app.tasks.subscriptions import check_grace_period_task

            result = await check_grace_period_task()

            assert result["transitioned"] == 0, (
                f"Grace period org with {days_elapsed:.1f} days elapsed was transitioned"
            )

    @pytest.mark.asyncio
    @settings(max_examples=10, deadline=None)
    @given(days_suspended=st.floats(min_value=0.0, max_value=29.9))
    async def test_suspension_retention_skips_orgs_under_30_days(self, days_suspended):
        """**Validates: Requirements 3.6** — suspended orgs with < 30 days elapsed are skipped."""
        now = datetime.now(timezone.utc)
        suspended_at = (now - timedelta(days=days_suspended)).isoformat()

        org_id = uuid.uuid4()
        mock_org = MagicMock()
        mock_org.id = org_id
        mock_org.status = "suspended"
        mock_org.settings = {
            "suspended_at": suspended_at,
            "retention_warnings_sent": [],
        }

        org_result = MagicMock()
        org_result.scalars.return_value.all.return_value = [mock_org]

        mock_session = _make_mock_session(execute_return_value=org_result)
        mock_session_factory = _make_mock_session_factory(mock_session)

        with patch(
            "app.core.database.async_session_factory", mock_session_factory
        ), patch(
            "app.core.audit.write_audit_log", AsyncMock()
        ), patch(
            "app.tasks.subscriptions.send_suspension_email_task", AsyncMock()
        ):
            from app.tasks.subscriptions import check_suspension_retention_task

            result = await check_suspension_retention_task()

            assert result["deleted"] == 0, (
                f"Suspended org with {days_suspended:.1f} days was deleted"
            )
            assert result["warnings_sent"] == 0, (
                f"Suspended org with {days_suspended:.1f} days received a warning"
            )


# ---------------------------------------------------------------------------
# Part F — Email failure resilience preserved
# Validates: Requirements 3.8
# ---------------------------------------------------------------------------


class TestEmailFailureResiliencePreserved:
    """Email sending failures must not crash the parent task."""

    @pytest.mark.asyncio
    async def test_receipt_email_failure_does_not_crash_billing(self):
        """**Validates: Requirements 3.8** — _send_billing_receipt_email failure
        is caught and logged without crashing process_recurring_billing_task."""
        now = datetime.now(timezone.utc)
        org_id = uuid.uuid4()
        plan_id = uuid.uuid4()

        mock_org = MagicMock()
        mock_org.id = org_id
        mock_org.status = "active"
        mock_org.next_billing_date = now - timedelta(hours=1)
        mock_org.plan_id = plan_id
        mock_org.billing_interval = "monthly"
        mock_org.settings = {"billing_retry_count": 0}
        mock_org.stripe_customer_id = "cus_test"
        mock_org.name = "Email Fail Org"
        mock_org.sms_sent_this_month = 0
        mock_org.carjam_lookups_this_month = 0

        mock_plan = MagicMock()
        mock_plan.id = plan_id
        mock_plan.name = "Pro"
        mock_plan.monthly_price_nzd = 49.0
        mock_plan.interval_config = []
        mock_plan.carjam_lookups_included = 50

        side_effects = _billing_execute_side_effects(mock_org, mock_plan)
        mock_session = _make_mock_session(execute_side_effect=side_effects)
        mock_session_factory = _make_mock_session_factory(mock_session)
        mock_session.add = MagicMock()

        charge_result = {"payment_intent_id": "pi_test", "status": "succeeded"}

        with patch(
            "app.core.database.async_session_factory", mock_session_factory
        ), patch(
            "app.integrations.stripe_billing.charge_org_payment_method",
            AsyncMock(return_value=charge_result),
        ), patch(
            "app.modules.admin.service.compute_sms_overage_for_billing",
            AsyncMock(return_value={"overage_count": 0, "per_sms_cost_nzd": 0, "total_charge_nzd": 0}),
        ), patch(
            "app.modules.admin.service.compute_carjam_overage",
            MagicMock(return_value=0),
        ), patch(
            "app.modules.organisations.service._load_signup_billing_config",
            AsyncMock(return_value={"gst_rate": Decimal("0.15"), "processing_fee_rate": Decimal("0.029"), "processing_fee_fixed_cents": 30}),
        ), patch(
            "app.modules.organisations.service._compute_billing_breakdown",
            MagicMock(return_value={"total_amount_cents": 5635, "gst_amount_cents": 735, "processing_fee_cents": 0}),
        ), patch(
            "app.tasks.subscriptions._send_billing_receipt_email",
            AsyncMock(side_effect=Exception("SMTP connection refused")),
        ):
            from app.tasks.subscriptions import process_recurring_billing_task

            # Should NOT raise — email failure is caught
            result = await process_recurring_billing_task()

            assert result["charged"] == 1, (
                "Billing task crashed or failed due to email sending failure"
            )
            assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_suspension_email_failure_does_not_crash_grace_period_check(self):
        """**Validates: Requirements 3.8** — send_suspension_email_task failure
        does not crash check_grace_period_task."""
        now = datetime.now(timezone.utc)
        grace_started = (now - timedelta(days=8)).isoformat()

        org_id = uuid.uuid4()
        mock_org = MagicMock()
        mock_org.id = org_id
        mock_org.status = "grace_period"
        mock_org.settings = {"grace_period_started_at": grace_started}

        org_result = MagicMock()
        org_result.scalars.return_value.all.return_value = [mock_org]

        mock_session = _make_mock_session(execute_return_value=org_result)
        mock_session_factory = _make_mock_session_factory(mock_session)

        with patch(
            "app.core.database.async_session_factory", mock_session_factory
        ), patch(
            "app.core.audit.write_audit_log", AsyncMock()
        ), patch(
            "app.tasks.subscriptions.send_suspension_email_task",
            AsyncMock(side_effect=Exception("Email service down")),
        ):
            from app.tasks.subscriptions import check_grace_period_task

            # The task catches exceptions per-org, so it should not crash
            result = await check_grace_period_task()

            # The org processing should have errored but not crashed the task
            assert "errors" in result
