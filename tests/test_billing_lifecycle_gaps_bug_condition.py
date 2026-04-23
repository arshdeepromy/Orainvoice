"""Bug condition exploration test — billing lifecycle gaps.

This test encodes the EXPECTED behavior for the billing lifecycle.
On UNFIXED code, these tests FAIL — proving the bug exists.
After the fix, these tests PASS — confirming the bug is resolved.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7**

Bug conditions tested:
  Part A: Three lifecycle tasks missing from _DAILY_TASKS and WRITE_TASKS
  Part B: No grace period entry email sent on transition
  Part C: No fallback dunning email sent on payment failure
  Part D: No data deletion confirmation email sent after 90-day suspension
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks.scheduled import _DAILY_TASKS, WRITE_TASKS


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


def _billing_execute_side_effects(mock_org, mock_plan):
    """Build the sequence of execute() return values for process_recurring_billing_task.

    The function makes these queries in order:
    1. select(Organisation) — due orgs
    2. select(SubscriptionPlan) — plan for org
    3. select(OrganisationCoupon, Coupon) — active coupon
    4. select(OrgStorageAddon) — storage addon
    5. select(OrgPaymentMethod) — default payment method
    """
    org_result = MagicMock()
    org_result.scalars.return_value.all.return_value = [mock_org]

    plan_result = MagicMock()
    plan_result.scalar_one_or_none.return_value = mock_plan

    coupon_result = MagicMock()
    coupon_result.one_or_none.return_value = None

    storage_addon_result = MagicMock()
    storage_addon_result.scalar_one_or_none.return_value = None

    pm_result = MagicMock()
    pm_result.scalar_one_or_none.return_value = MagicMock(
        stripe_payment_method_id="pm_test", is_default=True,
    )

    return [org_result, plan_result, coupon_result, storage_addon_result, pm_result]


# ---------------------------------------------------------------------------
# Part A — Task Registration (deterministic)
# Validates: Requirements 1.1, 1.2, 1.3, 1.4
# ---------------------------------------------------------------------------


class TestTaskRegistration:
    """Assert lifecycle tasks are registered in _DAILY_TASKS and WRITE_TASKS."""

    def _get_task_names(self) -> list[str]:
        return [name for (_, _, name) in _DAILY_TASKS]

    def test_check_trial_expiry_in_daily_tasks(self):
        """1.1: check_trial_expiry must be scheduled in _DAILY_TASKS."""
        task_names = self._get_task_names()
        assert "check_trial_expiry" in task_names, (
            "check_trial_expiry is not registered in _DAILY_TASKS — "
            "trial orgs never receive reminders and trials never auto-convert"
        )

    def test_check_grace_period_in_daily_tasks(self):
        """1.2: check_grace_period must be scheduled in _DAILY_TASKS."""
        task_names = self._get_task_names()
        assert "check_grace_period" in task_names, (
            "check_grace_period is not registered in _DAILY_TASKS — "
            "orgs in grace_period are never transitioned to suspended"
        )

    def test_check_suspension_retention_in_daily_tasks(self):
        """1.3: check_suspension_retention must be scheduled in _DAILY_TASKS."""
        task_names = self._get_task_names()
        assert "check_suspension_retention" in task_names, (
            "check_suspension_retention is not registered in _DAILY_TASKS — "
            "suspended orgs never receive warnings and are never auto-deleted"
        )

    def test_check_trial_expiry_in_write_tasks(self):
        """1.4: check_trial_expiry must be in WRITE_TASKS for HA safety."""
        assert "check_trial_expiry" in WRITE_TASKS, (
            "check_trial_expiry is not in WRITE_TASKS — "
            "would execute on standby nodes causing replication conflicts"
        )

    def test_check_grace_period_in_write_tasks(self):
        """1.4: check_grace_period must be in WRITE_TASKS for HA safety."""
        assert "check_grace_period" in WRITE_TASKS, (
            "check_grace_period is not in WRITE_TASKS — "
            "would execute on standby nodes causing replication conflicts"
        )

    def test_check_suspension_retention_in_write_tasks(self):
        """1.4: check_suspension_retention must be in WRITE_TASKS for HA safety."""
        assert "check_suspension_retention" in WRITE_TASKS, (
            "check_suspension_retention is not in WRITE_TASKS — "
            "would execute on standby nodes causing replication conflicts"
        )


# ---------------------------------------------------------------------------
# Part B — Grace Period Entry Email (mock-based)
# Validates: Requirement 1.5
# ---------------------------------------------------------------------------


class TestGracePeriodEntryEmail:
    """Assert grace period entry email is sent when org transitions."""

    @pytest.mark.asyncio
    async def test_grace_period_email_sent_on_transition(self):
        """1.5: When org enters grace_period after MAX_BILLING_RETRIES,
        send_suspension_email_task must be called with email_type='grace_period'.
        """
        from app.integrations.stripe_billing import PaymentFailedError

        org_id = uuid.uuid4()

        mock_org = MagicMock()
        mock_org.id = org_id
        mock_org.status = "active"
        mock_org.next_billing_date = datetime.now(timezone.utc) - timedelta(hours=1)
        mock_org.plan_id = uuid.uuid4()
        mock_org.billing_interval = "monthly"
        mock_org.settings = {"billing_retry_count": 2}
        mock_org.stripe_customer_id = "cus_test123"
        mock_org.name = "Test Org"
        mock_org.sms_sent_this_month = 0
        mock_org.carjam_lookups_this_month = 0

        mock_plan = MagicMock()
        mock_plan.id = mock_org.plan_id
        mock_plan.name = "Pro"
        mock_plan.monthly_price_nzd = 49.0
        mock_plan.interval_config = []
        mock_plan.carjam_lookups_included = 50

        side_effects = _billing_execute_side_effects(mock_org, mock_plan)
        mock_session = _make_mock_session(execute_side_effect=side_effects)
        mock_session_factory = _make_mock_session_factory(mock_session)

        mock_suspension_email = AsyncMock()
        with patch(
            "app.core.database.async_session_factory", mock_session_factory
        ), patch(
            "app.integrations.stripe_billing.charge_org_payment_method",
            AsyncMock(side_effect=PaymentFailedError("Card declined")),
        ), patch(
            "app.core.audit.write_audit_log", AsyncMock()
        ), patch(
            "app.tasks.subscriptions.send_suspension_email_task", mock_suspension_email
        ), patch(
            "app.tasks.subscriptions.send_dunning_email_task", AsyncMock()
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
        ):
            from app.tasks.subscriptions import process_recurring_billing_task

            await process_recurring_billing_task()

            # Assert grace period email was sent
            mock_suspension_email.assert_any_call(
                org_id=str(org_id), email_type="grace_period"
            )


# ---------------------------------------------------------------------------
# Part C — Fallback Dunning Email (mock-based)
# Validates: Requirement 1.6
# ---------------------------------------------------------------------------


class TestFallbackDunningEmail:
    """Assert dunning email is sent on every payment failure."""

    @pytest.mark.asyncio
    async def test_dunning_email_sent_on_payment_failure(self):
        """1.6: When payment fails, send_dunning_email_task must be called
        with the current retry count.
        """
        from app.integrations.stripe_billing import PaymentFailedError

        org_id = uuid.uuid4()

        mock_org = MagicMock()
        mock_org.id = org_id
        mock_org.status = "active"
        mock_org.next_billing_date = datetime.now(timezone.utc) - timedelta(hours=1)
        mock_org.plan_id = uuid.uuid4()
        mock_org.billing_interval = "monthly"
        mock_org.settings = {"billing_retry_count": 0}
        mock_org.stripe_customer_id = "cus_test456"
        mock_org.name = "Test Org 2"
        mock_org.sms_sent_this_month = 0
        mock_org.carjam_lookups_this_month = 0

        mock_plan = MagicMock()
        mock_plan.id = mock_org.plan_id
        mock_plan.name = "Starter"
        mock_plan.monthly_price_nzd = 29.0
        mock_plan.interval_config = []
        mock_plan.carjam_lookups_included = 10

        side_effects = _billing_execute_side_effects(mock_org, mock_plan)
        mock_session = _make_mock_session(execute_side_effect=side_effects)
        mock_session_factory = _make_mock_session_factory(mock_session)

        mock_dunning_email = AsyncMock()
        with patch(
            "app.core.database.async_session_factory", mock_session_factory
        ), patch(
            "app.integrations.stripe_billing.charge_org_payment_method",
            AsyncMock(side_effect=PaymentFailedError("Insufficient funds")),
        ), patch(
            "app.core.audit.write_audit_log", AsyncMock()
        ), patch(
            "app.tasks.subscriptions.send_dunning_email_task", mock_dunning_email
        ), patch(
            "app.tasks.subscriptions.send_suspension_email_task", AsyncMock()
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

            await process_recurring_billing_task()

            # Assert dunning email was called with retry count 1
            mock_dunning_email.assert_called_once_with(
                org_id=str(org_id), attempt_count=1
            )


# ---------------------------------------------------------------------------
# Part D — Deletion Confirmation Email (mock-based)
# Validates: Requirement 1.7
# ---------------------------------------------------------------------------


class TestDeletionConfirmationEmail:
    """Assert data deletion email is sent when org is deleted after 90 days."""

    @pytest.mark.asyncio
    async def test_deletion_email_sent_on_90_day_deletion(self):
        """1.7: When check_suspension_retention_task deletes an org after 90 days,
        send_suspension_email_task must be called with email_type='data_deleted'.
        """
        org_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        suspended_at = (now - timedelta(days=91)).isoformat()

        mock_org = MagicMock()
        mock_org.id = org_id
        mock_org.status = "suspended"
        mock_org.settings = {
            "suspended_at": suspended_at,
            "retention_warnings_sent": ["30_day", "7_day"],
        }
        mock_org.name = "Deleted Org"

        org_result = MagicMock()
        org_result.scalars.return_value.all.return_value = [mock_org]

        mock_session = _make_mock_session(execute_return_value=org_result)
        mock_session_factory = _make_mock_session_factory(mock_session)

        mock_suspension_email = AsyncMock()
        with patch(
            "app.core.database.async_session_factory", mock_session_factory
        ), patch(
            "app.core.audit.write_audit_log", AsyncMock()
        ), patch(
            "app.tasks.subscriptions.send_suspension_email_task", mock_suspension_email
        ):
            from app.tasks.subscriptions import check_suspension_retention_task

            await check_suspension_retention_task()

            # Assert deletion confirmation email was sent
            mock_suspension_email.assert_any_call(
                org_id=str(org_id), email_type="data_deleted"
            )
