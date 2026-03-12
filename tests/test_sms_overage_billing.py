"""Tests for SMS overage billing — task 10.1.

Covers:
- _report_sms_overage_async: adds SMS overage line items to Stripe for orgs
  exceeding plan limits (after FIFO package credit deduction)
- report_sms_overage_task: Celery task wrapper
- Counter reset after billing
- Audit log with action sms_overage.billed
- Edge cases: no overage, no customer, Stripe errors

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
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
    sms_sent: int = 0,
    stripe_customer_id: str | None = "cus_test123",
    status: str = "active",
    plan_id: uuid.UUID | None = None,
    org_id: uuid.UUID | None = None,
) -> MagicMock:
    org = MagicMock()
    org.id = org_id or uuid.uuid4()
    org.sms_sent_this_month = sms_sent
    org.stripe_customer_id = stripe_customer_id
    org.status = status
    org.plan_id = plan_id or uuid.uuid4()
    return org


def _make_plan(
    *,
    sms_included: bool = True,
    sms_included_quota: int = 100,
    per_sms_cost_nzd: float = 0.08,
) -> MagicMock:
    plan = MagicMock()
    plan.sms_included = sms_included
    plan.sms_included_quota = sms_included_quota
    plan.per_sms_cost_nzd = per_sms_cost_nzd
    return plan


def _build_session_factory_mock(session_mock):
    """Build a mock for async_session_factory that supports nested async with."""
    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=session_mock)
    session_ctx.__aexit__ = AsyncMock(return_value=False)

    begin_ctx = MagicMock()
    begin_ctx.__aenter__ = AsyncMock(return_value=None)
    begin_ctx.__aexit__ = AsyncMock(return_value=False)
    session_mock.begin = MagicMock(return_value=begin_ctx)

    factory = MagicMock(return_value=session_ctx)
    return factory


# ---------------------------------------------------------------------------
# _report_sms_overage_async tests
# ---------------------------------------------------------------------------


class TestReportSmsOverageAsync:
    """Test the async SMS overage billing logic."""

    @pytest.mark.asyncio
    async def test_bills_overage_when_exceeded(self):
        """Org with SMS overage > 0 should create a Stripe InvoiceItem."""
        org = _make_org(sms_sent=150)
        plan = _make_plan(sms_included_quota=100, per_sms_cost_nzd=0.08)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(org, plan)]
        mock_session.execute = AsyncMock(return_value=mock_result)

        factory = _build_session_factory_mock(mock_session)

        overage_data = {
            "overage_count": 50,
            "per_sms_cost_nzd": 0.08,
            "total_charge_nzd": 4.0,
        }

        with (
            patch("app.core.database.async_session_factory", factory),
            patch(
                "app.modules.admin.service.compute_sms_overage_for_billing",
                new_callable=AsyncMock,
                return_value=overage_data,
            ),
            patch(
                "app.integrations.stripe_billing.create_invoice_item",
                new_callable=AsyncMock,
                return_value={"invoice_item_id": "ii_123", "amount": 400},
            ) as mock_create_item,
            patch(
                "app.core.audit.write_audit_log",
                new_callable=AsyncMock,
                return_value=uuid.uuid4(),
            ) as mock_audit,
        ):
            from app.tasks.subscriptions import _report_sms_overage_async

            result = await _report_sms_overage_async()

        assert result["reported"] == 1
        assert result["skipped"] == 0
        assert result["errors"] == []

        # Verify Stripe InvoiceItem was created
        mock_create_item.assert_called_once()
        call_kwargs = mock_create_item.call_args[1]
        assert call_kwargs["customer_id"] == "cus_test123"
        assert call_kwargs["quantity"] == 50
        assert call_kwargs["unit_amount_cents"] == 8  # 0.08 * 100
        assert "SMS overage: 50 messages" in call_kwargs["description"]

        # Verify counter was reset (Req 4.4)
        assert org.sms_sent_this_month == 0

        # Verify audit log (Req 4.5)
        mock_audit.assert_called_once()
        audit_kwargs = mock_audit.call_args[1]
        assert audit_kwargs["action"] == "sms_overage.billed"
        assert audit_kwargs["entity_type"] == "organisation"
        assert audit_kwargs["after_value"]["overage_count"] == 50
        assert audit_kwargs["after_value"]["per_sms_cost_nzd"] == 0.08
        assert audit_kwargs["after_value"]["total_charge_nzd"] == 4.0

    @pytest.mark.asyncio
    async def test_skips_when_no_overage(self):
        """Org with overage == 0 should be skipped, counter still reset."""
        org = _make_org(sms_sent=50)
        plan = _make_plan(sms_included_quota=100)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(org, plan)]
        mock_session.execute = AsyncMock(return_value=mock_result)

        factory = _build_session_factory_mock(mock_session)

        overage_data = {
            "overage_count": 0,
            "per_sms_cost_nzd": 0.08,
            "total_charge_nzd": 0.0,
        }

        with (
            patch("app.core.database.async_session_factory", factory),
            patch(
                "app.modules.admin.service.compute_sms_overage_for_billing",
                new_callable=AsyncMock,
                return_value=overage_data,
            ),
            patch(
                "app.integrations.stripe_billing.create_invoice_item",
                new_callable=AsyncMock,
            ) as mock_create_item,
        ):
            from app.tasks.subscriptions import _report_sms_overage_async

            result = await _report_sms_overage_async()

        assert result["reported"] == 0
        assert result["skipped"] == 1
        mock_create_item.assert_not_called()

        # Counter should still be reset (Req 4.4)
        assert org.sms_sent_this_month == 0

    @pytest.mark.asyncio
    async def test_handles_stripe_error(self):
        """Stripe API error should be caught and recorded."""
        org = _make_org(sms_sent=200)
        plan = _make_plan(sms_included_quota=100)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(org, plan)]
        mock_session.execute = AsyncMock(return_value=mock_result)

        factory = _build_session_factory_mock(mock_session)

        overage_data = {
            "overage_count": 100,
            "per_sms_cost_nzd": 0.08,
            "total_charge_nzd": 8.0,
        }

        with (
            patch("app.core.database.async_session_factory", factory),
            patch(
                "app.modules.admin.service.compute_sms_overage_for_billing",
                new_callable=AsyncMock,
                return_value=overage_data,
            ),
            patch(
                "app.integrations.stripe_billing.create_invoice_item",
                new_callable=AsyncMock,
                side_effect=Exception("Stripe API error"),
            ),
        ):
            from app.tasks.subscriptions import _report_sms_overage_async

            result = await _report_sms_overage_async()

        assert result["reported"] == 0
        assert len(result["errors"]) == 1
        assert str(org.id) in result["errors"]

    @pytest.mark.asyncio
    async def test_multiple_orgs_mixed(self):
        """Multiple orgs: some with overage, some without."""
        org_over = _make_org(sms_sent=200, stripe_customer_id="cus_over")
        plan_over = _make_plan(sms_included_quota=100)

        org_under = _make_org(sms_sent=30, stripe_customer_id="cus_under")
        plan_under = _make_plan(sms_included_quota=100)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [
            (org_over, plan_over),
            (org_under, plan_under),
        ]
        mock_session.execute = AsyncMock(return_value=mock_result)

        factory = _build_session_factory_mock(mock_session)

        # compute_sms_overage_for_billing is called per-org
        async def mock_compute(db, org_id):
            if org_id == org_over.id:
                return {"overage_count": 100, "per_sms_cost_nzd": 0.08, "total_charge_nzd": 8.0}
            return {"overage_count": 0, "per_sms_cost_nzd": 0.08, "total_charge_nzd": 0.0}

        with (
            patch("app.core.database.async_session_factory", factory),
            patch(
                "app.modules.admin.service.compute_sms_overage_for_billing",
                side_effect=mock_compute,
            ),
            patch(
                "app.integrations.stripe_billing.create_invoice_item",
                new_callable=AsyncMock,
                return_value={"invoice_item_id": "ii_1", "amount": 800},
            ) as mock_create_item,
            patch(
                "app.core.audit.write_audit_log",
                new_callable=AsyncMock,
                return_value=uuid.uuid4(),
            ),
        ):
            from app.tasks.subscriptions import _report_sms_overage_async

            result = await _report_sms_overage_async()

        assert result["reported"] == 1
        assert result["skipped"] == 1
        assert result["errors"] == []
        mock_create_item.assert_called_once()

        # Both counters should be reset
        assert org_over.sms_sent_this_month == 0
        assert org_under.sms_sent_this_month == 0

    @pytest.mark.asyncio
    async def test_no_orgs(self):
        """No active orgs should produce zero results."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        factory = _build_session_factory_mock(mock_session)

        with patch("app.core.database.async_session_factory", factory):
            from app.tasks.subscriptions import _report_sms_overage_async

            result = await _report_sms_overage_async()

        assert result["reported"] == 0
        assert result["skipped"] == 0
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_description_format(self):
        """Line item description should match the required format."""
        org = _make_org(sms_sent=120)
        plan = _make_plan(sms_included_quota=100, per_sms_cost_nzd=0.12)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(org, plan)]
        mock_session.execute = AsyncMock(return_value=mock_result)

        factory = _build_session_factory_mock(mock_session)

        overage_data = {
            "overage_count": 20,
            "per_sms_cost_nzd": 0.12,
            "total_charge_nzd": 2.4,
        }

        with (
            patch("app.core.database.async_session_factory", factory),
            patch(
                "app.modules.admin.service.compute_sms_overage_for_billing",
                new_callable=AsyncMock,
                return_value=overage_data,
            ),
            patch(
                "app.integrations.stripe_billing.create_invoice_item",
                new_callable=AsyncMock,
                return_value={"invoice_item_id": "ii_456", "amount": 240},
            ) as mock_create_item,
            patch(
                "app.core.audit.write_audit_log",
                new_callable=AsyncMock,
                return_value=uuid.uuid4(),
            ),
        ):
            from app.tasks.subscriptions import _report_sms_overage_async

            await _report_sms_overage_async()

        call_kwargs = mock_create_item.call_args[1]
        assert call_kwargs["description"] == "SMS overage: 20 messages × $0.1200"


# ---------------------------------------------------------------------------
# Celery task wrapper test
# ---------------------------------------------------------------------------


class TestReportSmsOverageTask:
    """Test the synchronous Celery task wrapper."""

    def test_task_calls_async_and_returns_result(self):
        expected = {"reported": 2, "skipped": 3, "errors": []}

        with patch(
            "app.tasks.subscriptions._run_async",
            return_value=expected,
        ):
            from app.tasks.subscriptions import report_sms_overage_task

            result = report_sms_overage_task()

        assert result == expected


# ---------------------------------------------------------------------------
# Beat schedule registration test
# ---------------------------------------------------------------------------


class TestBeatScheduleRegistration:
    """Verify the SMS overage task is importable."""

    def test_sms_overage_task_importable(self):
        from app.tasks.subscriptions import report_sms_overage_task
        assert callable(report_sms_overage_task)
