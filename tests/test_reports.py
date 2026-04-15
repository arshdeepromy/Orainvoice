"""Unit tests for Task 22.1 — org-level reports.

Tests cover:
  - resolve_date_range helper
  - get_revenue_summary
  - get_invoice_status_report
  - get_outstanding_invoices
  - get_top_services
  - get_gst_return (standard-rated vs zero-rated)
  - get_customer_statement
  - get_carjam_usage
  - get_storage_usage
  - get_fleet_report

Requirements: 45.1, 45.2, 45.3, 45.4, 45.5, 45.6, 45.7, 66.4
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure all ORM models are loaded for relationship resolution
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
import app.modules.inventory.models  # noqa: F401

from app.modules.reports.service import (
    get_carjam_usage,
    get_customer_statement,
    get_fleet_report,
    get_gst_return,
    get_invoice_status_report,
    get_outstanding_invoices,
    get_revenue_summary,
    get_storage_usage,
    get_top_services,
    resolve_date_range,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.execute = AsyncMock()
    return db


def _mock_scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.scalar.return_value = value
    return result


def _mock_row(**kwargs):
    """Create a mock row with named attributes."""
    row = MagicMock()
    for k, v in kwargs.items():
        setattr(row, k, v)
    return row


# ---------------------------------------------------------------------------
# resolve_date_range tests
# ---------------------------------------------------------------------------

class TestResolveDateRange:
    """Tests for the date range resolution helper."""

    def test_day_preset(self):
        start, end = resolve_date_range("day", None, None)
        assert start == end == date.today()

    def test_week_preset(self):
        start, end = resolve_date_range("week", None, None)
        today = date.today()
        assert start == today - __import__("datetime").timedelta(days=today.weekday())
        assert end == today

    def test_month_preset(self):
        start, end = resolve_date_range("month", None, None)
        today = date.today()
        assert start == today.replace(day=1)
        assert end == today

    def test_year_preset(self):
        start, end = resolve_date_range("year", None, None)
        today = date.today()
        assert start == today.replace(month=1, day=1)
        assert end == today

    def test_custom_range(self):
        s = date(2024, 1, 1)
        e = date(2024, 6, 30)
        start, end = resolve_date_range("custom", s, e)
        assert start == s
        assert end == e

    def test_none_defaults_to_month(self):
        start, end = resolve_date_range(None, None, None)
        today = date.today()
        assert start == today.replace(day=1)
        assert end == today

    def test_quarter_preset(self):
        start, end = resolve_date_range("quarter", None, None)
        today = date.today()
        q_month = ((today.month - 1) // 3) * 3 + 1
        assert start == today.replace(month=q_month, day=1)
        assert end == today


# ---------------------------------------------------------------------------
# Revenue Summary tests
# ---------------------------------------------------------------------------

class TestRevenueSummary:
    """Tests for get_revenue_summary."""

    @pytest.mark.asyncio
    async def test_revenue_summary_basic(self):
        db = _mock_db()
        org_id = uuid.uuid4()
        row = _mock_row(
            total_revenue_nzd=Decimal("1000.00"),
            total_gst_nzd=Decimal("150.00"),
            total_inclusive_nzd=Decimal("1150.00"),
            invoice_count=5,
        )
        inv_result = MagicMock()
        inv_result.one.return_value = row

        cn_result = MagicMock()
        cn_result.scalar.return_value = Decimal("0")

        pay_result = MagicMock()
        pay_result.scalar.return_value = Decimal("0")

        db.execute.side_effect = [inv_result, cn_result, pay_result]

        data = await get_revenue_summary(
            db, org_id, date(2024, 1, 1), date(2024, 1, 31)
        )
        assert data["total_revenue"] == Decimal("1000.00")
        assert data["total_gst"] == Decimal("150.00")
        assert data["total_inclusive"] == Decimal("1150.00")
        assert data["invoice_count"] == 5
        assert data["average_invoice"] == Decimal("230.00")
        assert data["currency"] == "NZD"

    @pytest.mark.asyncio
    async def test_revenue_summary_zero_invoices(self):
        db = _mock_db()
        org_id = uuid.uuid4()
        row = _mock_row(
            total_revenue_nzd=0,
            total_gst_nzd=0,
            total_inclusive_nzd=0,
            invoice_count=0,
        )
        inv_result = MagicMock()
        inv_result.one.return_value = row

        cn_result = MagicMock()
        cn_result.scalar.return_value = Decimal("0")

        pay_result = MagicMock()
        pay_result.scalar.return_value = Decimal("0")

        db.execute.side_effect = [inv_result, cn_result, pay_result]

        data = await get_revenue_summary(
            db, org_id, date(2024, 1, 1), date(2024, 1, 31)
        )
        assert data["invoice_count"] == 0
        assert data["average_invoice"] == Decimal("0")


# ---------------------------------------------------------------------------
# Invoice Status Report tests
# ---------------------------------------------------------------------------

class TestInvoiceStatusReport:
    """Tests for get_invoice_status_report."""

    @pytest.mark.asyncio
    async def test_status_breakdown(self):
        db = _mock_db()
        org_id = uuid.uuid4()
        rows = [
            _mock_row(status="issued", count=3, total=Decimal("300.00")),
            _mock_row(status="paid", count=10, total=Decimal("5000.00")),
            _mock_row(status="overdue", count=2, total=Decimal("400.00")),
        ]
        result_mock = MagicMock()
        result_mock.all.return_value = rows
        db.execute.return_value = result_mock

        data = await get_invoice_status_report(
            db, org_id, date(2024, 1, 1), date(2024, 12, 31)
        )
        assert len(data["breakdown"]) == 3
        assert data["breakdown"][0]["status"] == "issued"
        assert data["breakdown"][1]["count"] == 10


# ---------------------------------------------------------------------------
# Outstanding Invoices tests
# ---------------------------------------------------------------------------

class TestOutstandingInvoices:
    """Tests for get_outstanding_invoices."""

    @pytest.mark.asyncio
    async def test_outstanding_with_overdue(self):
        db = _mock_db()
        org_id = uuid.uuid4()
        cust_id = uuid.uuid4()
        inv_id = uuid.uuid4()
        past_due = date(2024, 1, 1)
        rows = [
            _mock_row(
                id=inv_id,
                invoice_number="INV-001",
                customer_id=cust_id,
                vehicle_rego="ABC123",
                issue_date=date(2023, 12, 1),
                due_date=past_due,
                total=Decimal("500.00"),
                balance_due=Decimal("500.00"),
                first_name="John",
                last_name="Doe",
            ),
        ]
        result_mock = MagicMock()
        result_mock.all.return_value = rows
        db.execute.return_value = result_mock

        data = await get_outstanding_invoices(db, org_id)
        assert data["count"] == 1
        assert data["total_outstanding"] == Decimal("500.00")
        assert data["invoices"][0]["customer_name"] == "John Doe"
        assert data["invoices"][0]["days_overdue"] > 0

    @pytest.mark.asyncio
    async def test_outstanding_empty(self):
        db = _mock_db()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        db.execute.return_value = result_mock

        data = await get_outstanding_invoices(db, uuid.uuid4())
        assert data["count"] == 0
        assert data["total_outstanding"] == Decimal("0")


# ---------------------------------------------------------------------------
# Top Services tests
# ---------------------------------------------------------------------------

class TestTopServices:
    """Tests for get_top_services."""

    @pytest.mark.asyncio
    async def test_top_services_ranking(self):
        db = _mock_db()
        org_id = uuid.uuid4()
        rows = [
            _mock_row(
                description="WOF Inspection",
                catalogue_item_id=uuid.uuid4(),
                count=50,
                total_revenue=Decimal("2750.00"),
            ),
            _mock_row(
                description="Oil Change",
                catalogue_item_id=uuid.uuid4(),
                count=30,
                total_revenue=Decimal("1500.00"),
            ),
        ]
        result_mock = MagicMock()
        result_mock.all.return_value = rows
        db.execute.return_value = result_mock

        data = await get_top_services(
            db, org_id, date(2024, 1, 1), date(2024, 12, 31)
        )
        assert len(data["services"]) == 2
        assert data["services"][0]["description"] == "WOF Inspection"
        assert data["services"][0]["total_revenue"] == Decimal("2750.00")


# ---------------------------------------------------------------------------
# GST Return tests
# ---------------------------------------------------------------------------

class TestGSTReturn:
    """Tests for get_gst_return — standard-rated vs zero-rated."""

    @pytest.mark.asyncio
    async def test_gst_return_mixed_items(self):
        db = _mock_db()
        org_id = uuid.uuid4()

        # Six sequential db.execute calls:
        # 1. standard-rated line items sum (NZD-converted)
        # 2. zero-rated line items sum (NZD-converted)
        # 3. invoice-level GST totals (NZD-converted)
        # 4. credit note refunds (NZD-converted)
        # 5. refund payments (NZD-converted)
        # 6. expense totals (purchases + input tax)
        std_result = MagicMock()
        std_result.scalar.return_value = Decimal("8000.00")

        zero_result = MagicMock()
        zero_result.scalar.return_value = Decimal("2000.00")

        gst_row = _mock_row(
            total_gst_nzd=Decimal("1200.00"),
            total_sales_nzd=Decimal("11200.00"),
        )
        gst_result = MagicMock()
        gst_result.one.return_value = gst_row

        cn_result = MagicMock()
        cn_result.scalar.return_value = Decimal("0")

        pay_refund_result = MagicMock()
        pay_refund_result.scalar.return_value = Decimal("0")

        expense_row = _mock_row(
            total_purchases=Decimal("3000.00"),
            total_input_tax=Decimal("391.30"),
        )
        expense_result = MagicMock()
        expense_result.one.return_value = expense_row

        db.execute.side_effect = [
            std_result, zero_result, gst_result,
            cn_result, pay_refund_result, expense_result,
        ]

        data = await get_gst_return(
            db, org_id, date(2024, 1, 1), date(2024, 3, 31)
        )
        assert data["currency"] == "NZD"
        assert data["total_sales"] == Decimal("11200.00")
        assert data["total_gst_collected"] == Decimal("1200.00")
        assert data["standard_rated_sales"] == Decimal("8000.00")
        assert data["zero_rated_sales"] == Decimal("2000.00")
        # Input tax from expenses
        assert data["total_purchases"] == Decimal("3000.00")
        assert data["total_input_tax"] == Decimal("391.30")
        # Net GST payable = output (1200) - input (391.30) = 808.70
        assert data["net_gst_payable"] == Decimal("808.70")
        assert data["net_gst"] == Decimal("808.70")  # legacy alias


# ---------------------------------------------------------------------------
# Customer Statement tests
# ---------------------------------------------------------------------------

class TestCustomerStatement:
    """Tests for get_customer_statement."""

    @pytest.mark.asyncio
    async def test_statement_not_found(self):
        db = _mock_db()
        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = None
        db.execute.return_value = cust_result

        data = await get_customer_statement(
            db, uuid.uuid4(), uuid.uuid4(), date(2024, 1, 1), date(2024, 12, 31)
        )
        assert data is None

    @pytest.mark.asyncio
    async def test_statement_with_invoices_and_payments(self):
        db = _mock_db()
        org_id = uuid.uuid4()
        cust_id = uuid.uuid4()
        inv_id = uuid.uuid4()

        # Mock customer
        customer = MagicMock()
        customer.first_name = "Jane"
        customer.last_name = "Smith"
        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = customer

        # Mock invoice
        invoice = MagicMock()
        invoice.id = inv_id
        invoice.invoice_number = "INV-001"
        invoice.issue_date = date(2024, 3, 1)
        invoice.total = Decimal("500.00")
        inv_result = MagicMock()
        inv_result.scalars.return_value.all.return_value = [invoice]

        # Mock payment
        payment = MagicMock()
        payment.amount = Decimal("200.00")
        payment.is_refund = False
        payment.method = "cash"
        payment.created_at = datetime(2024, 3, 5, tzinfo=timezone.utc)
        pay_result = MagicMock()
        pay_result.scalars.return_value.all.return_value = [payment]

        db.execute.side_effect = [cust_result, inv_result, pay_result]

        data = await get_customer_statement(
            db, org_id, cust_id, date(2024, 1, 1), date(2024, 12, 31)
        )
        assert data is not None
        assert data["customer_name"] == "Jane Smith"
        assert len(data["items"]) == 2
        assert data["closing_balance"] == Decimal("300.00")


# ---------------------------------------------------------------------------
# Carjam Usage tests
# ---------------------------------------------------------------------------

class TestCarjamUsage:
    """Tests for get_carjam_usage."""

    @pytest.mark.asyncio
    async def test_carjam_usage_with_overage(self):
        db = _mock_db()
        org_id = uuid.uuid4()
        row = _mock_row(
            carjam_lookups_this_month=150,
            carjam_lookups_included=100,
            carjam_lookups_reset_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
        )
        result_mock = MagicMock()
        result_mock.one_or_none.return_value = row
        db.execute.return_value = result_mock

        data = await get_carjam_usage(db, org_id)
        assert data["lookups_this_month"] == 150
        assert data["lookups_included"] == 100
        assert data["overage_lookups"] == 50

    @pytest.mark.asyncio
    async def test_carjam_usage_no_overage(self):
        db = _mock_db()
        row = _mock_row(
            carjam_lookups_this_month=50,
            carjam_lookups_included=100,
            carjam_lookups_reset_at=None,
        )
        result_mock = MagicMock()
        result_mock.one_or_none.return_value = row
        db.execute.return_value = result_mock

        data = await get_carjam_usage(db, uuid.uuid4())
        assert data["overage_lookups"] == 0

    @pytest.mark.asyncio
    async def test_carjam_usage_org_not_found(self):
        db = _mock_db()
        result_mock = MagicMock()
        result_mock.one_or_none.return_value = None
        db.execute.return_value = result_mock

        data = await get_carjam_usage(db, uuid.uuid4())
        assert data["lookups_this_month"] == 0


# ---------------------------------------------------------------------------
# Storage Usage tests
# ---------------------------------------------------------------------------

class TestStorageUsage:
    """Tests for get_storage_usage."""

    @pytest.mark.asyncio
    async def test_storage_usage_normal(self):
        db = _mock_db()
        org_id = uuid.uuid4()

        # Mock calculate_org_storage
        with patch(
            "app.modules.reports.service.calculate_org_storage",
            new_callable=AsyncMock,
            return_value=500_000_000,
        ):
            # Mock quota query
            quota_result = MagicMock()
            quota_result.scalar.return_value = 5  # 5 GB
            db.execute.return_value = quota_result

            data = await get_storage_usage(db, org_id)
            assert data["storage_used_bytes"] == 500_000_000
            assert data["storage_quota_bytes"] == 5 * 1_073_741_824
            assert data["alert_level"] == "none"
            assert data["usage_percentage"] < 80


# ---------------------------------------------------------------------------
# Fleet Report tests
# ---------------------------------------------------------------------------

class TestFleetReport:
    """Tests for get_fleet_report."""

    @pytest.mark.asyncio
    async def test_fleet_not_found(self):
        db = _mock_db()
        fleet_result = MagicMock()
        fleet_result.scalar_one_or_none.return_value = None
        db.execute.return_value = fleet_result

        data = await get_fleet_report(
            db, uuid.uuid4(), uuid.uuid4(), date(2024, 1, 1), date(2024, 12, 31)
        )
        assert data is None

    @pytest.mark.asyncio
    async def test_fleet_report_with_data(self):
        db = _mock_db()
        org_id = uuid.uuid4()
        fleet_id = uuid.uuid4()

        # Mock fleet account
        fleet = MagicMock()
        fleet.name = "ABC Transport"
        fleet_result = MagicMock()
        fleet_result.scalar_one_or_none.return_value = fleet

        # Mock customer IDs
        cust_ids = [(uuid.uuid4(),), (uuid.uuid4(),)]
        cust_result = MagicMock()
        cust_result.all.return_value = cust_ids

        # Mock spend
        spend_row = _mock_row(
            total_spend=Decimal("15000.00"),
            outstanding=Decimal("2000.00"),
        )
        spend_result = MagicMock()
        spend_result.one.return_value = spend_row

        # Mock vehicles serviced
        vehicle_result = MagicMock()
        vehicle_result.scalar.return_value = 8

        db.execute.side_effect = [fleet_result, cust_result, spend_result, vehicle_result]

        data = await get_fleet_report(
            db, org_id, fleet_id, date(2024, 1, 1), date(2024, 12, 31)
        )
        assert data is not None
        assert data["fleet_name"] == "ABC Transport"
        assert data["total_spend"] == Decimal("15000.00")
        assert data["vehicles_serviced"] == 8
        assert data["outstanding_balance"] == Decimal("2000.00")

    @pytest.mark.asyncio
    async def test_fleet_report_no_customers(self):
        db = _mock_db()
        org_id = uuid.uuid4()
        fleet_id = uuid.uuid4()

        fleet = MagicMock()
        fleet.name = "Empty Fleet"
        fleet_result = MagicMock()
        fleet_result.scalar_one_or_none.return_value = fleet

        cust_result = MagicMock()
        cust_result.all.return_value = []

        db.execute.side_effect = [fleet_result, cust_result]

        data = await get_fleet_report(
            db, org_id, fleet_id, date(2024, 1, 1), date(2024, 12, 31)
        )
        assert data["total_spend"] == Decimal("0")
        assert data["vehicles_serviced"] == 0
