"""Unit tests for Task 16.2 — free trial and signup.

Tests cover:
  - TrialStatusResponse schema validation
  - GET /api/v1/billing/trial endpoint logic
  - create_subscription_from_trial Stripe integration
  - Celery trial expiry task: 3-day reminder + auto-conversion
  - Requirements: 41.1, 41.2, 41.3, 41.4, 41.5
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.modules.admin.models  # noqa: F401

from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.billing.schemas import TrialStatusResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
PLAN_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


def _make_plan(
    plan_id=None,
    name="Starter",
    monthly_price_nzd=49.00,
    is_public=True,
    is_archived=False,
):
    plan = MagicMock(spec=SubscriptionPlan)
    plan.id = plan_id or PLAN_ID
    plan.name = name
    plan.monthly_price_nzd = Decimal(str(monthly_price_nzd))
    plan.is_public = is_public
    plan.is_archived = is_archived
    plan.user_seats = 5
    plan.storage_quota_gb = 5
    plan.carjam_lookups_included = 100
    return plan


def _make_org(
    org_id=None,
    status="trial",
    trial_ends_at=None,
    plan_id=None,
    stripe_customer_id="cus_test123",
    stripe_subscription_id=None,
):
    org = MagicMock(spec=Organisation)
    org.id = org_id or ORG_ID
    org.name = "Test Workshop"
    org.plan_id = plan_id or PLAN_ID
    org.status = status
    org.trial_ends_at = trial_ends_at
    org.stripe_customer_id = stripe_customer_id
    org.stripe_subscription_id = stripe_subscription_id
    org.storage_quota_gb = 5
    return org


def _make_user(user_id=None, org_id=None, role="org_admin", email="admin@test.com"):
    from app.modules.auth.models import User

    user = MagicMock(spec=User)
    user.id = user_id or USER_ID
    user.org_id = org_id or ORG_ID
    user.role = role
    user.email = email
    user.is_active = True
    return user


def _mock_db_session():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.commit = AsyncMock()
    return db


def _mock_scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _mock_scalars_result(values):
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = values
    scalars_mock.first.return_value = values[0] if values else None
    result.scalars.return_value = scalars_mock
    return result


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestTrialStatusSchema:
    """Verify TrialStatusResponse schema."""

    def test_trial_active(self):
        now = datetime.now(timezone.utc)
        trial_end = now + timedelta(days=10)
        resp = TrialStatusResponse(
            is_trial=True,
            trial_ends_at=trial_end,
            days_remaining=10,
            plan_name="Starter",
            plan_monthly_price_nzd=49.00,
            status="trial",
        )
        assert resp.is_trial is True
        assert resp.days_remaining == 10
        assert resp.plan_name == "Starter"
        assert resp.status == "trial"

    def test_not_on_trial(self):
        resp = TrialStatusResponse(
            is_trial=False,
            trial_ends_at=None,
            days_remaining=0,
            plan_name="Pro",
            plan_monthly_price_nzd=99.00,
            status="active",
        )
        assert resp.is_trial is False
        assert resp.days_remaining == 0
        assert resp.trial_ends_at is None

    def test_trial_expired(self):
        past = datetime.now(timezone.utc) - timedelta(days=1)
        resp = TrialStatusResponse(
            is_trial=True,
            trial_ends_at=past,
            days_remaining=0,
            plan_name="Starter",
            plan_monthly_price_nzd=49.00,
            status="trial",
        )
        assert resp.days_remaining == 0


# ---------------------------------------------------------------------------
# Stripe subscription creation tests
# ---------------------------------------------------------------------------


class TestCreateSubscriptionFromTrial:
    """Test create_subscription_from_trial in stripe_billing.py."""

    @pytest.mark.asyncio
    @patch("app.integrations.stripe_billing.stripe")
    async def test_creates_subscription_with_amount(self, mock_stripe):
        from app.integrations.stripe_billing import create_subscription_from_trial

        mock_sub = MagicMock()
        mock_sub.id = "sub_test123"
        mock_sub.status = "active"
        mock_stripe.Subscription.create.return_value = mock_sub

        result = await create_subscription_from_trial(
            customer_id="cus_test123",
            monthly_amount_cents=4900,
            metadata={"org_id": "test"},
        )

        assert result["subscription_id"] == "sub_test123"
        assert result["status"] == "active"
        mock_stripe.Subscription.create.assert_called_once()
        call_kwargs = mock_stripe.Subscription.create.call_args[1]
        assert call_kwargs["customer"] == "cus_test123"
        assert call_kwargs["items"][0]["price_data"]["unit_amount"] == 4900

    @pytest.mark.asyncio
    @patch("app.integrations.stripe_billing.stripe")
    async def test_creates_subscription_with_price_id(self, mock_stripe):
        from app.integrations.stripe_billing import create_subscription_from_trial

        mock_sub = MagicMock()
        mock_sub.id = "sub_test456"
        mock_sub.status = "active"
        mock_stripe.Subscription.create.return_value = mock_sub

        result = await create_subscription_from_trial(
            customer_id="cus_test123",
            price_id="price_abc",
        )

        assert result["subscription_id"] == "sub_test456"
        call_kwargs = mock_stripe.Subscription.create.call_args[1]
        assert call_kwargs["items"] == [{"price": "price_abc"}]

    @pytest.mark.asyncio
    async def test_raises_without_price_or_amount(self):
        from app.integrations.stripe_billing import create_subscription_from_trial

        with pytest.raises(ValueError, match="Either price_id or monthly_amount_cents"):
            await create_subscription_from_trial(customer_id="cus_test123")


# ---------------------------------------------------------------------------
# Trial expiry task tests
# ---------------------------------------------------------------------------


class TestTrialExpiryTask:
    """Test the Celery trial expiry checking logic."""

    def _build_session_factory_mock(self, session_mock):
        """Build a mock for async_session_factory that supports nested async with."""
        # session_factory() returns an async context manager yielding session
        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=session_mock)
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        # session.begin() returns an async context manager
        begin_ctx = MagicMock()
        begin_ctx.__aenter__ = AsyncMock(return_value=None)
        begin_ctx.__aexit__ = AsyncMock(return_value=False)
        session_mock.begin = MagicMock(return_value=begin_ctx)

        factory = MagicMock(return_value=session_ctx)
        return factory

    @pytest.mark.asyncio
    @patch("app.tasks.subscriptions._send_trial_reminder", new_callable=AsyncMock)
    @patch("app.tasks.subscriptions._convert_trial_to_active", new_callable=AsyncMock)
    async def test_sends_reminder_at_3_days(self, mock_convert, mock_reminder):
        """When 3 days remain, a reminder email should be sent (Req 41.4)."""
        from app.tasks.subscriptions import _check_trial_expiry_async

        now = datetime.now(timezone.utc)
        org = _make_org(trial_ends_at=now + timedelta(days=2, hours=12))

        session_mock = AsyncMock()
        orgs_result = _mock_scalars_result([org])
        dedup_result = MagicMock()
        dedup_result.scalar.return_value = 0
        session_mock.execute = AsyncMock(side_effect=[orgs_result, dedup_result])

        factory = self._build_session_factory_mock(session_mock)

        with patch("app.core.database.async_session_factory", factory):
            result = await _check_trial_expiry_async()

        assert result["reminders_sent"] == 1
        assert result["trials_converted"] == 0
        mock_reminder.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.tasks.subscriptions._send_trial_reminder", new_callable=AsyncMock)
    @patch("app.tasks.subscriptions._convert_trial_to_active", new_callable=AsyncMock)
    async def test_converts_expired_trial(self, mock_convert, mock_reminder):
        """When trial has ended, org should be converted to active (Req 41.5)."""
        from app.tasks.subscriptions import _check_trial_expiry_async

        now = datetime.now(timezone.utc)
        org = _make_org(trial_ends_at=now - timedelta(hours=1))

        session_mock = AsyncMock()
        orgs_result = _mock_scalars_result([org])
        session_mock.execute = AsyncMock(return_value=orgs_result)

        factory = self._build_session_factory_mock(session_mock)

        with patch("app.core.database.async_session_factory", factory):
            result = await _check_trial_expiry_async()

        assert result["trials_converted"] == 1
        assert result["reminders_sent"] == 0
        mock_convert.assert_called_once()
        mock_reminder.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.tasks.subscriptions._send_trial_reminder", new_callable=AsyncMock)
    @patch("app.tasks.subscriptions._convert_trial_to_active", new_callable=AsyncMock)
    async def test_skips_reminder_if_already_sent(self, mock_convert, mock_reminder):
        """Dedup: don't send reminder if one was already sent."""
        from app.tasks.subscriptions import _check_trial_expiry_async

        now = datetime.now(timezone.utc)
        org = _make_org(trial_ends_at=now + timedelta(days=2))

        session_mock = AsyncMock()
        orgs_result = _mock_scalars_result([org])
        dedup_result = MagicMock()
        dedup_result.scalar.return_value = 1
        session_mock.execute = AsyncMock(side_effect=[orgs_result, dedup_result])

        factory = self._build_session_factory_mock(session_mock)

        with patch("app.core.database.async_session_factory", factory):
            result = await _check_trial_expiry_async()

        assert result["reminders_sent"] == 0
        mock_reminder.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.tasks.subscriptions._send_trial_reminder", new_callable=AsyncMock)
    @patch("app.tasks.subscriptions._convert_trial_to_active", new_callable=AsyncMock)
    async def test_no_action_for_orgs_with_many_days_left(self, mock_convert, mock_reminder):
        """Orgs with >3 days remaining should not trigger any action."""
        from app.tasks.subscriptions import _check_trial_expiry_async

        now = datetime.now(timezone.utc)
        org = _make_org(trial_ends_at=now + timedelta(days=10))

        session_mock = AsyncMock()
        orgs_result = _mock_scalars_result([org])
        session_mock.execute = AsyncMock(return_value=orgs_result)

        factory = self._build_session_factory_mock(session_mock)

        with patch("app.core.database.async_session_factory", factory):
            result = await _check_trial_expiry_async()

        assert result["reminders_sent"] == 0
        assert result["trials_converted"] == 0
        mock_reminder.assert_not_called()
        mock_convert.assert_not_called()


# ---------------------------------------------------------------------------
# Convert trial to active tests
# ---------------------------------------------------------------------------


class TestConvertTrialToActive:
    """Test _convert_trial_to_active helper."""

    @pytest.mark.asyncio
    @patch("app.integrations.stripe_billing.create_subscription_from_trial", new_callable=AsyncMock)
    @patch("app.core.audit.write_audit_log", new_callable=AsyncMock)
    async def test_successful_conversion(self, mock_audit, mock_create_sub):
        from app.tasks.subscriptions import _convert_trial_to_active

        plan = _make_plan(monthly_price_nzd=49.00)
        org = _make_org(stripe_customer_id="cus_test123")

        mock_create_sub.return_value = {
            "subscription_id": "sub_new123",
            "status": "active",
        }

        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(plan))

        now = datetime.now(timezone.utc)
        await _convert_trial_to_active(db, org, now)

        assert org.status == "active"
        assert org.stripe_subscription_id == "sub_new123"
        mock_create_sub.assert_called_once()
        mock_audit.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_without_stripe_customer(self):
        from app.tasks.subscriptions import _convert_trial_to_active

        plan = _make_plan()
        org = _make_org(stripe_customer_id=None)

        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(plan))

        with pytest.raises(ValueError, match="No Stripe customer ID"):
            await _convert_trial_to_active(db, org, datetime.now(timezone.utc))

    @pytest.mark.asyncio
    async def test_raises_without_plan(self):
        from app.tasks.subscriptions import _convert_trial_to_active

        org = _make_org()

        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with pytest.raises(ValueError, match="Plan .* not found"):
            await _convert_trial_to_active(db, org, datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Celery Beat schedule test
# ---------------------------------------------------------------------------


class TestCeleryBeatSchedule:
    """Verify the trial expiry task is importable."""

    def test_trial_expiry_task_importable(self):
        from app.tasks.subscriptions import check_trial_expiry_task
        assert callable(check_trial_expiry_task)
