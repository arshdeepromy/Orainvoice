"""Tests for Carjam overage billing — task 16.6.

Covers:
- _report_carjam_overage_async: reports overage to Stripe for orgs exceeding plan limits
- report_carjam_overage_task: Celery task wrapper
- Edge cases: no overage, no subscription, Stripe errors

Requirements: 16.3
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_org(
    *,
    carjam_lookups: int = 0,
    stripe_subscription_id: str | None = "sub_test123",
    status: str = "active",
    plan_id: uuid.UUID | None = None,
    org_id: uuid.UUID | None = None,
) -> MagicMock:
    org = MagicMock()
    org.id = org_id or uuid.uuid4()
    org.carjam_lookups_this_month = carjam_lookups
    org.stripe_subscription_id = stripe_subscription_id
    org.status = status
    org.plan_id = plan_id or uuid.uuid4()
    return org


def _make_plan(*, carjam_lookups_included: int = 100) -> MagicMock:
    plan = MagicMock()
    plan.carjam_lookups_included = carjam_lookups_included
    return plan


def _build_session_factory_mock(session_mock):
    """Build a mock for async_session_factory that supports nested async with."""
    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=session_mock)
    session_ctx.__aexit__ = AsyncMock(return_value=False)

    # session.begin() returns an async context manager (not a coroutine)
    begin_ctx = MagicMock()
    begin_ctx.__aenter__ = AsyncMock(return_value=None)
    begin_ctx.__aexit__ = AsyncMock(return_value=False)
    session_mock.begin = MagicMock(return_value=begin_ctx)

    factory = MagicMock(return_value=session_ctx)
    return factory


# ---------------------------------------------------------------------------
# _report_carjam_overage_async tests
# ---------------------------------------------------------------------------


class TestReportCarjamOverageAsync:
    """Test the async overage reporting logic."""

    @pytest.mark.asyncio
    async def test_reports_overage_when_exceeded(self):
        """Org with usage > included should report overage to Stripe."""
        org = _make_org(carjam_lookups=150)
        plan = _make_plan(carjam_lookups_included=100)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(org, plan)]
        mock_session.execute = AsyncMock(return_value=mock_result)

        factory = _build_session_factory_mock(mock_session)

        with (
            patch("app.core.database.async_session_factory", factory),
            patch(
                "app.integrations.stripe_billing.report_metered_usage",
                new_callable=AsyncMock,
                return_value={"reported": True, "usage_record_id": "ur_123", "quantity": 50},
            ) as mock_report,
        ):
            from app.tasks.subscriptions import _report_carjam_overage_async

            result = await _report_carjam_overage_async()

        assert result["reported"] == 1
        assert result["skipped"] == 0
        assert result["errors"] == []
        mock_report.assert_called_once_with(
            subscription_id="sub_test123",
            quantity=50,
            action="set",
        )

    @pytest.mark.asyncio
    async def test_skips_when_no_overage(self):
        """Org with usage <= included should be skipped."""
        org = _make_org(carjam_lookups=50)
        plan = _make_plan(carjam_lookups_included=100)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(org, plan)]
        mock_session.execute = AsyncMock(return_value=mock_result)

        factory = _build_session_factory_mock(mock_session)

        with (
            patch("app.core.database.async_session_factory", factory),
            patch(
                "app.integrations.stripe_billing.report_metered_usage",
                new_callable=AsyncMock,
            ) as mock_report,
        ):
            from app.tasks.subscriptions import _report_carjam_overage_async

            result = await _report_carjam_overage_async()

        assert result["reported"] == 0
        assert result["skipped"] == 1
        mock_report.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_at_exact_limit(self):
        """Org with usage == included should not be charged."""
        org = _make_org(carjam_lookups=100)
        plan = _make_plan(carjam_lookups_included=100)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(org, plan)]
        mock_session.execute = AsyncMock(return_value=mock_result)

        factory = _build_session_factory_mock(mock_session)

        with (
            patch("app.core.database.async_session_factory", factory),
            patch(
                "app.integrations.stripe_billing.report_metered_usage",
                new_callable=AsyncMock,
            ) as mock_report,
        ):
            from app.tasks.subscriptions import _report_carjam_overage_async

            result = await _report_carjam_overage_async()

        assert result["reported"] == 0
        assert result["skipped"] == 1
        mock_report.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_stripe_error(self):
        """Stripe API error should be caught and recorded."""
        org = _make_org(carjam_lookups=200)
        plan = _make_plan(carjam_lookups_included=100)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(org, plan)]
        mock_session.execute = AsyncMock(return_value=mock_result)

        factory = _build_session_factory_mock(mock_session)

        with (
            patch("app.core.database.async_session_factory", factory),
            patch(
                "app.integrations.stripe_billing.report_metered_usage",
                new_callable=AsyncMock,
                side_effect=Exception("Stripe API error"),
            ),
        ):
            from app.tasks.subscriptions import _report_carjam_overage_async

            result = await _report_carjam_overage_async()

        assert result["reported"] == 0
        assert len(result["errors"]) == 1
        assert str(org.id) in result["errors"]

    @pytest.mark.asyncio
    async def test_handles_no_metered_item(self):
        """When Stripe has no metered item, report returns not reported."""
        org = _make_org(carjam_lookups=150)
        plan = _make_plan(carjam_lookups_included=100)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(org, plan)]
        mock_session.execute = AsyncMock(return_value=mock_result)

        factory = _build_session_factory_mock(mock_session)

        with (
            patch("app.core.database.async_session_factory", factory),
            patch(
                "app.integrations.stripe_billing.report_metered_usage",
                new_callable=AsyncMock,
                return_value={"reported": False, "reason": "no_metered_item"},
            ),
        ):
            from app.tasks.subscriptions import _report_carjam_overage_async

            result = await _report_carjam_overage_async()

        assert result["reported"] == 0
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_multiple_orgs_mixed(self):
        """Multiple orgs: some with overage, some without."""
        org_over = _make_org(carjam_lookups=200, stripe_subscription_id="sub_over")
        plan_over = _make_plan(carjam_lookups_included=100)

        org_under = _make_org(carjam_lookups=30, stripe_subscription_id="sub_under")
        plan_under = _make_plan(carjam_lookups_included=100)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(org_over, plan_over), (org_under, plan_under)]
        mock_session.execute = AsyncMock(return_value=mock_result)

        factory = _build_session_factory_mock(mock_session)

        with (
            patch("app.core.database.async_session_factory", factory),
            patch(
                "app.integrations.stripe_billing.report_metered_usage",
                new_callable=AsyncMock,
                return_value={"reported": True, "usage_record_id": "ur_1", "quantity": 100},
            ) as mock_report,
        ):
            from app.tasks.subscriptions import _report_carjam_overage_async

            result = await _report_carjam_overage_async()

        assert result["reported"] == 1
        assert result["skipped"] == 1
        assert result["errors"] == []
        mock_report.assert_called_once_with(
            subscription_id="sub_over",
            quantity=100,
            action="set",
        )

    @pytest.mark.asyncio
    async def test_no_orgs(self):
        """No active orgs should produce zero results."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        factory = _build_session_factory_mock(mock_session)

        with patch("app.core.database.async_session_factory", factory):
            from app.tasks.subscriptions import _report_carjam_overage_async

            result = await _report_carjam_overage_async()

        assert result["reported"] == 0
        assert result["skipped"] == 0
        assert result["errors"] == []


# ---------------------------------------------------------------------------
# Celery task wrapper test
# ---------------------------------------------------------------------------


class TestReportCarjamOverageTask:
    """Test the synchronous Celery task wrapper."""

    def test_task_calls_async_and_returns_result(self):
        expected = {"reported": 2, "skipped": 3, "errors": []}

        with patch(
            "app.tasks.subscriptions._run_async",
            return_value=expected,
        ):
            from app.tasks.subscriptions import report_carjam_overage_task

            result = report_carjam_overage_task()

        assert result == expected


# ---------------------------------------------------------------------------
# Beat schedule registration test
# ---------------------------------------------------------------------------


class TestBeatScheduleRegistration:
    """Verify the Carjam overage task is importable."""

    def test_carjam_overage_task_importable(self):
        from app.tasks.subscriptions import report_carjam_overage_task
        assert callable(report_carjam_overage_task)
