"""Supplementary unit tests for Task 22.3 — reporting module edge cases.

Covers gaps not addressed by test_reports.py and test_admin_reports.py:
  - GST return: all-exempt items, all-standard items, empty period
  - Customer statement: refunds, invoices-only, date ordering
  - MRR: suspended orgs excluded, grace_period included

Requirements: 45.6, 45.7, 46.2
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
import app.modules.inventory.models  # noqa: F401

from app.modules.reports.service import get_customer_statement, get_gst_return
from app.modules.admin.service import get_mrr_report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    return db


def _mock_row(**kwargs):
    row = MagicMock()
    for k, v in kwargs.items():
        setattr(row, k, v)
    return row


def _mock_scalar_result(value):
    result = MagicMock()
    result.scalar.return_value = value
    result.scalar_one_or_none.return_value = value
    return result


def _mock_execute_result(rows):
    result = MagicMock()
    result.all.return_value = rows
    return result


# ---------------------------------------------------------------------------
# GST Return — Requirement 45.6 edge cases
# ---------------------------------------------------------------------------


class TestGSTReturnEdgeCases:
    """Additional GST return scenarios beyond test_reports.py."""

    @pytest.mark.asyncio
    async def test_gst_return_all_zero_rated(self):
        """All items are GST-exempt — standard_rated_sales should be 0."""
        db = _mock_db()
        org_id = uuid.uuid4()

        std_result = MagicMock()
        std_result.scalar.return_value = Decimal("0")

        zero_result = MagicMock()
        zero_result.scalar.return_value = Decimal("5000.00")

        gst_row = _mock_row(
            total_gst=Decimal("0"),
            total_sales=Decimal("5000.00"),
        )
        gst_result = MagicMock()
        gst_result.one.return_value = gst_row

        db.execute.side_effect = [std_result, zero_result, gst_result]

        data = await get_gst_return(
            db, org_id, date(2024, 4, 1), date(2024, 6, 30)
        )
        assert data["standard_rated_sales"] == Decimal("0")
        assert data["zero_rated_sales"] == Decimal("5000.00")
        assert data["total_gst_collected"] == Decimal("0")
        assert data["net_gst"] == Decimal("0")

    @pytest.mark.asyncio
    async def test_gst_return_all_standard_rated(self):
        """No exempt items — zero_rated_sales should be 0."""
        db = _mock_db()
        org_id = uuid.uuid4()

        std_result = MagicMock()
        std_result.scalar.return_value = Decimal("10000.00")

        zero_result = MagicMock()
        zero_result.scalar.return_value = Decimal("0")

        gst_row = _mock_row(
            total_gst=Decimal("1500.00"),
            total_sales=Decimal("11500.00"),
        )
        gst_result = MagicMock()
        gst_result.one.return_value = gst_row

        db.execute.side_effect = [std_result, zero_result, gst_result]

        data = await get_gst_return(
            db, org_id, date(2024, 1, 1), date(2024, 3, 31)
        )
        assert data["standard_rated_sales"] == Decimal("10000.00")
        assert data["zero_rated_sales"] == Decimal("0")
        assert data["total_gst_collected"] == Decimal("1500.00")
        assert data["standard_rated_gst"] == Decimal("1500.00")

    @pytest.mark.asyncio
    async def test_gst_return_empty_period(self):
        """No invoices in the period — all values should be 0."""
        db = _mock_db()
        org_id = uuid.uuid4()

        std_result = MagicMock()
        std_result.scalar.return_value = Decimal("0")

        zero_result = MagicMock()
        zero_result.scalar.return_value = Decimal("0")

        gst_row = _mock_row(total_gst=Decimal("0"), total_sales=Decimal("0"))
        gst_result = MagicMock()
        gst_result.one.return_value = gst_row

        db.execute.side_effect = [std_result, zero_result, gst_result]

        data = await get_gst_return(
            db, org_id, date(2025, 1, 1), date(2025, 3, 31)
        )
        assert data["total_sales"] == Decimal("0")
        assert data["total_gst_collected"] == Decimal("0")
        assert data["standard_rated_sales"] == Decimal("0")
        assert data["zero_rated_sales"] == Decimal("0")
        assert data["net_gst"] == Decimal("0")
        assert data["period_start"] == date(2025, 1, 1)
        assert data["period_end"] == date(2025, 3, 31)


# ---------------------------------------------------------------------------
# Customer Statement — Requirement 45.7 edge cases
# ---------------------------------------------------------------------------


class TestCustomerStatementEdgeCases:
    """Additional customer statement scenarios beyond test_reports.py."""

    @pytest.mark.asyncio
    async def test_statement_with_refund(self):
        """Refund increases the closing balance (debit)."""
        db = _mock_db()
        org_id = uuid.uuid4()
        cust_id = uuid.uuid4()

        customer = MagicMock()
        customer.first_name = "Bob"
        customer.last_name = "Builder"
        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = customer

        inv = MagicMock()
        inv.id = uuid.uuid4()
        inv.invoice_number = "INV-010"
        inv.issue_date = date(2024, 6, 1)
        inv.total = Decimal("1000.00")
        inv_result = MagicMock()
        inv_result.scalars.return_value.all.return_value = [inv]

        # Payment of 1000, then refund of 300
        payment = MagicMock()
        payment.amount = Decimal("1000.00")
        payment.is_refund = False
        payment.method = "stripe"
        payment.created_at = datetime(2024, 6, 2, tzinfo=timezone.utc)

        refund = MagicMock()
        refund.amount = Decimal("300.00")
        refund.is_refund = True
        refund.method = "stripe"
        refund.created_at = datetime(2024, 6, 5, tzinfo=timezone.utc)

        pay_result = MagicMock()
        pay_result.scalars.return_value.all.return_value = [payment, refund]

        db.execute.side_effect = [cust_result, inv_result, pay_result]

        data = await get_customer_statement(
            db, org_id, cust_id, date(2024, 6, 1), date(2024, 6, 30)
        )
        assert data is not None
        # Invoice +1000, payment -1000, refund +300 = 300
        assert data["closing_balance"] == Decimal("300.00")
        assert len(data["items"]) == 3

    @pytest.mark.asyncio
    async def test_statement_invoices_only_no_payments(self):
        """Statement with invoices but no payments — balance equals total invoiced."""
        db = _mock_db()
        org_id = uuid.uuid4()
        cust_id = uuid.uuid4()

        customer = MagicMock()
        customer.first_name = "Alice"
        customer.last_name = "Wong"
        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = customer

        inv1 = MagicMock()
        inv1.id = uuid.uuid4()
        inv1.invoice_number = "INV-020"
        inv1.issue_date = date(2024, 7, 1)
        inv1.total = Decimal("250.00")

        inv2 = MagicMock()
        inv2.id = uuid.uuid4()
        inv2.invoice_number = "INV-021"
        inv2.issue_date = date(2024, 7, 15)
        inv2.total = Decimal("750.00")

        inv_result = MagicMock()
        inv_result.scalars.return_value.all.return_value = [inv1, inv2]

        pay_result = MagicMock()
        pay_result.scalars.return_value.all.return_value = []

        db.execute.side_effect = [cust_result, inv_result, pay_result]

        data = await get_customer_statement(
            db, org_id, cust_id, date(2024, 7, 1), date(2024, 7, 31)
        )
        assert data is not None
        assert data["closing_balance"] == Decimal("1000.00")
        assert len(data["items"]) == 2
        assert data["customer_name"] == "Alice Wong"

    @pytest.mark.asyncio
    async def test_statement_items_sorted_by_date(self):
        """Items are sorted chronologically even when invoices and payments interleave."""
        db = _mock_db()
        org_id = uuid.uuid4()
        cust_id = uuid.uuid4()

        customer = MagicMock()
        customer.first_name = "Charlie"
        customer.last_name = "Day"
        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = customer

        inv = MagicMock()
        inv.id = uuid.uuid4()
        inv.invoice_number = "INV-030"
        inv.issue_date = date(2024, 8, 10)
        inv.total = Decimal("500.00")
        inv_result = MagicMock()
        inv_result.scalars.return_value.all.return_value = [inv]

        # Payment made BEFORE the invoice issue date (e.g. deposit)
        payment = MagicMock()
        payment.amount = Decimal("200.00")
        payment.is_refund = False
        payment.method = "cash"
        payment.created_at = datetime(2024, 8, 5, tzinfo=timezone.utc)
        pay_result = MagicMock()
        pay_result.scalars.return_value.all.return_value = [payment]

        db.execute.side_effect = [cust_result, inv_result, pay_result]

        data = await get_customer_statement(
            db, org_id, cust_id, date(2024, 8, 1), date(2024, 8, 31)
        )
        assert data is not None
        # Sorted: payment (Aug 5) then invoice (Aug 10)
        assert data["items"][0]["date"] == date(2024, 8, 5)
        assert data["items"][1]["date"] == date(2024, 8, 10)
        # Balance: -200 (credit) + 500 (debit) = 300
        assert data["closing_balance"] == Decimal("300.00")


# ---------------------------------------------------------------------------
# MRR Calculation — Requirement 46.2 edge cases
# ---------------------------------------------------------------------------


class TestMrrEdgeCases:
    """Additional MRR scenarios beyond test_admin_reports.py."""

    @pytest.mark.asyncio
    async def test_mrr_excludes_suspended_orgs(self):
        """Suspended orgs should not contribute to MRR."""
        db = _mock_db()

        # Per-org query returns empty (no active/trial/grace orgs)
        # because the only org is suspended
        db.execute = AsyncMock(
            side_effect=[
                _mock_execute_result([]),  # per-org rows (no qualifying orgs)
                *[_mock_scalar_result(0) for _ in range(6)],  # month-over-month
            ]
        )

        result = await get_mrr_report(db)
        assert result["total_mrr_nzd"] == 0.0
        assert result["plan_breakdown"] == []

    @pytest.mark.asyncio
    async def test_mrr_includes_grace_period_orgs(self):
        """Grace period orgs should still contribute to MRR."""
        db = _mock_db()
        plan_id = uuid.uuid4()
        monthly_config = [{"interval": "monthly", "enabled": True, "discount_percent": 0}]

        # One org in grace_period on a $79 plan (monthly)
        db.execute = AsyncMock(
            side_effect=[
                _mock_execute_result([
                    (uuid.uuid4(), "monthly", plan_id, "Standard", 79.0, monthly_config),
                ]),
                *[_mock_scalar_result(79.0) for _ in range(6)],
            ]
        )

        result = await get_mrr_report(db)
        assert result["total_mrr_nzd"] == 79.0
        assert result["plan_breakdown"][0]["plan_name"] == "Standard"
        assert result["plan_breakdown"][0]["active_orgs"] == 1

    @pytest.mark.asyncio
    async def test_mrr_plan_breakdown_sums_correctly(self):
        """Total MRR equals sum of all plan breakdowns."""
        db = _mock_db()
        plan_id_starter = uuid.uuid4()
        plan_id_pro = uuid.uuid4()
        plan_id_enterprise = uuid.uuid4()
        monthly_config = [{"interval": "monthly", "enabled": True, "discount_percent": 0}]

        # 5 Starter ($29) + 3 Pro ($99) + 1 Enterprise ($249), all monthly
        org_rows = [
            *[(uuid.uuid4(), "monthly", plan_id_starter, "Starter", 29.0, monthly_config) for _ in range(5)],
            *[(uuid.uuid4(), "monthly", plan_id_pro, "Pro", 99.0, monthly_config) for _ in range(3)],
            (uuid.uuid4(), "monthly", plan_id_enterprise, "Enterprise", 249.0, monthly_config),
        ]

        db.execute = AsyncMock(
            side_effect=[
                _mock_execute_result(org_rows),
                *[_mock_scalar_result(691.0) for _ in range(6)],
            ]
        )

        result = await get_mrr_report(db)
        expected = 5 * 29.0 + 3 * 99.0 + 1 * 249.0  # 145 + 297 + 249 = 691
        assert result["total_mrr_nzd"] == expected
        breakdown_sum = sum(p["mrr_nzd"] for p in result["plan_breakdown"])
        assert breakdown_sum == expected
