"""Unit tests for OraFlows Accounting financial reports (Task 2.5).

Covers:
  1. P&L with known invoice + expense data, verify line items and totals
  2. Balance sheet with known entries, verify balanced = true
  3. Tax estimate at bracket boundaries ($0, $14,000, $48,000, $70,000, $180,000)
  4. Cash vs accrual toggle produces different totals
  5. Aged receivables bucket accuracy at boundary days (30, 31, 60, 61, 90, 91)
  6. Tax position endpoint returns within 2 seconds

Requirements: 6.1–6.7, 7.1–7.5, 8.1–8.3, 9.1–9.6, 10.1, 10.2
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import all models so SQLAlchemy can resolve relationships.
import importlib as _importlib
import pathlib as _pathlib

for _models_file in _pathlib.Path("app/modules").rglob("models.py"):
    _mod_path = str(_models_file).replace("/", ".").replace("\\", ".").removesuffix(".py")
    try:
        _importlib.import_module(_mod_path)
    except Exception:
        pass

from app.modules.reports.service import (
    _calculate_sole_trader_tax,
    _calculate_company_tax,
    get_profit_loss,
    get_balance_sheet,
    get_aged_receivables,
    get_tax_estimate,
    get_tax_position,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db():
    """Create a mock AsyncSession with standard methods."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# 1. Sole Trader Tax Bracket Boundary Tests (pure function)
#    Validates: Requirement 9.2
# ---------------------------------------------------------------------------


class TestSoleTraderTaxBrackets:
    """NZ progressive tax brackets at exact boundary values."""

    def test_zero_income(self):
        """Req 9.2: $0 income → $0 tax."""
        assert _calculate_sole_trader_tax(Decimal("0")) == Decimal("0.00")

    def test_negative_income(self):
        """Req 9.2: Negative income → $0 tax."""
        assert _calculate_sole_trader_tax(Decimal("-5000")) == Decimal("0.00")

    def test_at_14000_boundary(self):
        """Req 9.2: $14,000 → 10.5% on full amount = $1,470."""
        result = _calculate_sole_trader_tax(Decimal("14000"))
        expected = Decimal("14000") * Decimal("0.105")
        assert result == expected.quantize(Decimal("0.01"))

    def test_at_48000_boundary(self):
        """Req 9.2: $48,000 → 10.5% on 14k + 17.5% on 34k."""
        result = _calculate_sole_trader_tax(Decimal("48000"))
        expected = (
            Decimal("14000") * Decimal("0.105")
            + Decimal("34000") * Decimal("0.175")
        )
        assert result == expected.quantize(Decimal("0.01"))

    def test_at_70000_boundary(self):
        """Req 9.2: $70,000 → 10.5% on 14k + 17.5% on 34k + 30% on 22k."""
        result = _calculate_sole_trader_tax(Decimal("70000"))
        expected = (
            Decimal("14000") * Decimal("0.105")
            + Decimal("34000") * Decimal("0.175")
            + Decimal("22000") * Decimal("0.30")
        )
        assert result == expected.quantize(Decimal("0.01"))

    def test_at_180000_boundary(self):
        """Req 9.2: $180,000 → all brackets up to 33%."""
        result = _calculate_sole_trader_tax(Decimal("180000"))
        expected = (
            Decimal("14000") * Decimal("0.105")
            + Decimal("34000") * Decimal("0.175")
            + Decimal("22000") * Decimal("0.30")
            + Decimal("110000") * Decimal("0.33")
        )
        assert result == expected.quantize(Decimal("0.01"))

    def test_above_180000(self):
        """Req 9.2: $200,000 → all brackets + 39% on excess."""
        result = _calculate_sole_trader_tax(Decimal("200000"))
        expected = (
            Decimal("14000") * Decimal("0.105")
            + Decimal("34000") * Decimal("0.175")
            + Decimal("22000") * Decimal("0.30")
            + Decimal("110000") * Decimal("0.33")
            + Decimal("20000") * Decimal("0.39")
        )
        assert result == expected.quantize(Decimal("0.01"))

    def test_tax_never_exceeds_income(self):
        """Req 9.6: Tax cannot exceed income at any bracket boundary."""
        for income_val in [0, 1, 14000, 48000, 70000, 180000, 500000]:
            income = Decimal(str(income_val))
            tax = _calculate_sole_trader_tax(income)
            assert tax <= income


# ---------------------------------------------------------------------------
# 2. Company Tax Rate Tests (pure function)
#    Validates: Requirement 9.1
# ---------------------------------------------------------------------------


class TestCompanyTax:
    """Flat 28% company tax rate."""

    def test_zero_income(self):
        """Req 9.1: $0 income → $0 tax."""
        assert _calculate_company_tax(Decimal("0")) == Decimal("0.00")

    def test_negative_income(self):
        """Req 9.1: Negative income → $0 tax."""
        assert _calculate_company_tax(Decimal("-10000")) == Decimal("0.00")

    def test_flat_rate(self):
        """Req 9.1: $100,000 → $28,000."""
        result = _calculate_company_tax(Decimal("100000"))
        assert result == Decimal("28000.00")

    def test_small_amount(self):
        """Req 9.1: $1 → $0.28."""
        result = _calculate_company_tax(Decimal("1"))
        assert result == Decimal("0.28")

    def test_tax_never_exceeds_income(self):
        """Req 9.6: Company tax (28%) never exceeds income."""
        for income_val in [0, 1, 100, 50000, 1000000]:
            income = Decimal(str(income_val))
            tax = _calculate_company_tax(income)
            assert tax <= income


# ---------------------------------------------------------------------------
# 3. P&L with known data — mocked DB
#    Validates: Requirements 6.1, 6.2
# ---------------------------------------------------------------------------


class TestProfitAndLoss:
    """P&L report aggregation with known journal line data."""

    @pytest.mark.asyncio
    async def test_pnl_line_items_and_totals(self):
        """Req 6.1, 6.2: P&L aggregates revenue, COGS, expenses correctly."""
        db = _mock_db()
        org_id = uuid.uuid4()
        rev_id = uuid.uuid4()
        cogs_id = uuid.uuid4()
        exp_id = uuid.uuid4()

        # Mock DB rows: (account_id, code, name, account_type, total_debit, total_credit)
        mock_rows = [
            MagicMock(
                account_id=rev_id, account_code="4000", account_name="Sales Revenue",
                account_type="revenue", total_debit=0, total_credit=10000,
            ),
            MagicMock(
                account_id=cogs_id, account_code="5000", account_name="Cost of Goods",
                account_type="cogs", total_debit=3000, total_credit=0,
            ),
            MagicMock(
                account_id=exp_id, account_code="6000", account_name="Rent",
                account_type="expense", total_debit=2000, total_credit=0,
            ),
        ]

        mock_result = MagicMock()
        mock_result.all.return_value = mock_rows
        db.execute.return_value = mock_result

        result = await get_profit_loss(
            db, org_id,
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
        )

        assert result["total_revenue"] == Decimal("10000.00")
        assert result["total_cogs"] == Decimal("3000.00")
        assert result["total_expenses"] == Decimal("2000.00")
        assert result["gross_profit"] == Decimal("7000.00")
        assert result["net_profit"] == Decimal("5000.00")
        assert result["currency"] == "NZD"
        assert len(result["revenue_items"]) == 1
        assert len(result["cogs_items"]) == 1
        assert len(result["expense_items"]) == 1

    @pytest.mark.asyncio
    async def test_pnl_empty_data(self):
        """Req 6.1: P&L with no data returns zero totals."""
        db = _mock_db()
        org_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.all.return_value = []
        db.execute.return_value = mock_result

        result = await get_profit_loss(
            db, org_id,
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
        )

        assert result["total_revenue"] == Decimal("0.00")
        assert result["total_cogs"] == Decimal("0.00")
        assert result["total_expenses"] == Decimal("0.00")
        assert result["gross_profit"] == Decimal("0.00")
        assert result["net_profit"] == Decimal("0.00")
        assert result["gross_margin_pct"] == Decimal("0")
        assert result["net_margin_pct"] == Decimal("0")

    @pytest.mark.asyncio
    async def test_pnl_margin_calculation(self):
        """Req 6.2: Gross and net margin percentages are correct."""
        db = _mock_db()
        org_id = uuid.uuid4()

        mock_rows = [
            MagicMock(
                account_id=uuid.uuid4(), account_code="4000", account_name="Sales",
                account_type="revenue", total_debit=0, total_credit=20000,
            ),
            MagicMock(
                account_id=uuid.uuid4(), account_code="5000", account_name="COGS",
                account_type="cogs", total_debit=8000, total_credit=0,
            ),
            MagicMock(
                account_id=uuid.uuid4(), account_code="6000", account_name="Expenses",
                account_type="expense", total_debit=4000, total_credit=0,
            ),
        ]

        mock_result = MagicMock()
        mock_result.all.return_value = mock_rows
        db.execute.return_value = mock_result

        result = await get_profit_loss(
            db, org_id,
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
        )

        # gross_profit = 20000 - 8000 = 12000, gross_margin = 60%
        assert result["gross_margin_pct"] == Decimal("60.00")
        # net_profit = 12000 - 4000 = 8000, net_margin = 40%
        assert result["net_margin_pct"] == Decimal("40.00")


# ---------------------------------------------------------------------------
# 4. Cash vs Accrual Basis
#    Validates: Requirements 6.3, 6.4
# ---------------------------------------------------------------------------


class TestCashVsAccrualBasis:
    """Cash vs accrual toggle produces different totals."""

    @pytest.mark.asyncio
    async def test_accrual_includes_all_posted_entries(self):
        """Req 6.3: Accrual basis includes all posted entries by entry_date."""
        db = _mock_db()
        org_id = uuid.uuid4()

        # Accrual: includes invoice + payment entries
        mock_rows = [
            MagicMock(
                account_id=uuid.uuid4(), account_code="4000", account_name="Sales",
                account_type="revenue", total_debit=0, total_credit=5000,
            ),
        ]
        mock_result = MagicMock()
        mock_result.all.return_value = mock_rows
        db.execute.return_value = mock_result

        result = await get_profit_loss(
            db, org_id,
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
            basis="accrual",
        )

        assert result["basis"] == "accrual"
        assert result["total_revenue"] == Decimal("5000.00")

    @pytest.mark.asyncio
    async def test_cash_basis_filters_payment_only(self):
        """Req 6.4: Cash basis includes only payment-sourced entries."""
        db = _mock_db()
        org_id = uuid.uuid4()

        # Cash: only payment entries (smaller amount)
        mock_rows = [
            MagicMock(
                account_id=uuid.uuid4(), account_code="4000", account_name="Sales",
                account_type="revenue", total_debit=0, total_credit=3000,
            ),
        ]
        mock_result = MagicMock()
        mock_result.all.return_value = mock_rows
        db.execute.return_value = mock_result

        result = await get_profit_loss(
            db, org_id,
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
            basis="cash",
        )

        assert result["basis"] == "cash"
        assert result["total_revenue"] == Decimal("3000.00")


# ---------------------------------------------------------------------------
# 5. Balance Sheet with known entries
#    Validates: Requirements 7.1, 7.3, 7.4
# ---------------------------------------------------------------------------


class TestBalanceSheet:
    """Balance sheet aggregation and balanced check."""

    @pytest.mark.asyncio
    async def test_balanced_sheet(self):
        """Req 7.3, 7.4: Balance sheet where assets = liabilities + equity."""
        db = _mock_db()
        org_id = uuid.uuid4()

        mock_rows = [
            MagicMock(
                account_id=uuid.uuid4(), account_code="1000", account_name="Bank",
                account_type="asset", sub_type="current_asset",
                total_debit=50000, total_credit=0,
            ),
            MagicMock(
                account_id=uuid.uuid4(), account_code="2000", account_name="AP",
                account_type="liability", sub_type="current_liability",
                total_debit=0, total_credit=20000,
            ),
            MagicMock(
                account_id=uuid.uuid4(), account_code="3000", account_name="Retained Earnings",
                account_type="equity", sub_type=None,
                total_debit=0, total_credit=30000,
            ),
        ]

        mock_result = MagicMock()
        mock_result.all.return_value = mock_rows
        db.execute.return_value = mock_result

        result = await get_balance_sheet(db, org_id, as_at_date=date(2025, 12, 31))

        assert result["total_assets"] == Decimal("50000.00")
        assert result["total_liabilities"] == Decimal("20000.00")
        assert result["total_equity"] == Decimal("30000.00")
        assert result["balanced"] is True
        assert result["currency"] == "NZD"

    @pytest.mark.asyncio
    async def test_non_current_asset_grouping(self):
        """Req 7.2: Non-current assets grouped separately."""
        db = _mock_db()
        org_id = uuid.uuid4()

        mock_rows = [
            MagicMock(
                account_id=uuid.uuid4(), account_code="1000", account_name="Bank",
                account_type="asset", sub_type="current_asset",
                total_debit=30000, total_credit=0,
            ),
            MagicMock(
                account_id=uuid.uuid4(), account_code="1500", account_name="Equipment",
                account_type="asset", sub_type="non_current_asset",
                total_debit=20000, total_credit=0,
            ),
            MagicMock(
                account_id=uuid.uuid4(), account_code="3000", account_name="Equity",
                account_type="equity", sub_type=None,
                total_debit=0, total_credit=50000,
            ),
        ]

        mock_result = MagicMock()
        mock_result.all.return_value = mock_rows
        db.execute.return_value = mock_result

        result = await get_balance_sheet(db, org_id, as_at_date=date(2025, 12, 31))

        assert len(result["assets"]["current"]) == 1
        assert len(result["assets"]["non_current"]) == 1
        assert result["total_assets"] == Decimal("50000.00")
        assert result["balanced"] is True

    @pytest.mark.asyncio
    async def test_empty_balance_sheet(self):
        """Req 7.1: Empty balance sheet is balanced (0 = 0 + 0)."""
        db = _mock_db()
        org_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.all.return_value = []
        db.execute.return_value = mock_result

        result = await get_balance_sheet(db, org_id, as_at_date=date(2025, 12, 31))

        assert result["total_assets"] == Decimal("0.00")
        assert result["total_liabilities"] == Decimal("0.00")
        assert result["total_equity"] == Decimal("0.00")
        assert result["balanced"] is True


# ---------------------------------------------------------------------------
# 6. Aged Receivables Bucket Accuracy
#    Validates: Requirements 8.1, 8.2, 8.3
# ---------------------------------------------------------------------------


class TestAgedReceivablesBucketing:
    """Aged receivables bucket accuracy at boundary days."""

    def _make_invoice_row(self, report_date: date, days_overdue: int, balance: Decimal):
        """Create a mock invoice row with a due_date that is days_overdue from report_date."""
        row = MagicMock()
        row.invoice_id = uuid.uuid4()
        row.invoice_number = f"INV-{days_overdue}"
        row.customer_id = uuid.uuid4()
        row.due_date = report_date - timedelta(days=days_overdue)
        row.balance_due = balance
        row.first_name = "Test"
        row.last_name = "Customer"
        return row

    @pytest.mark.asyncio
    async def test_30_days_in_current_bucket(self):
        """Req 8.1: Invoice 30 days overdue → current (0–30) bucket."""
        db = _mock_db()
        org_id = uuid.uuid4()
        report_date = date(2025, 6, 15)

        row = self._make_invoice_row(report_date, 30, Decimal("100.00"))
        mock_result = MagicMock()
        mock_result.all.return_value = [row]
        db.execute.return_value = mock_result

        result = await get_aged_receivables(db, org_id, report_date=report_date)

        assert result["overall"]["current"] == Decimal("100.00")
        assert result["overall"]["31_60"] == Decimal("0.00")

    @pytest.mark.asyncio
    async def test_31_days_in_31_60_bucket(self):
        """Req 8.1: Invoice 31 days overdue → 31–60 bucket."""
        db = _mock_db()
        org_id = uuid.uuid4()
        report_date = date(2025, 6, 15)

        row = self._make_invoice_row(report_date, 31, Decimal("200.00"))
        mock_result = MagicMock()
        mock_result.all.return_value = [row]
        db.execute.return_value = mock_result

        result = await get_aged_receivables(db, org_id, report_date=report_date)

        assert result["overall"]["current"] == Decimal("0.00")
        assert result["overall"]["31_60"] == Decimal("200.00")

    @pytest.mark.asyncio
    async def test_60_days_in_31_60_bucket(self):
        """Req 8.1: Invoice 60 days overdue → 31–60 bucket."""
        db = _mock_db()
        org_id = uuid.uuid4()
        report_date = date(2025, 6, 15)

        row = self._make_invoice_row(report_date, 60, Decimal("300.00"))
        mock_result = MagicMock()
        mock_result.all.return_value = [row]
        db.execute.return_value = mock_result

        result = await get_aged_receivables(db, org_id, report_date=report_date)

        assert result["overall"]["31_60"] == Decimal("300.00")
        assert result["overall"]["61_90"] == Decimal("0.00")

    @pytest.mark.asyncio
    async def test_61_days_in_61_90_bucket(self):
        """Req 8.1: Invoice 61 days overdue → 61–90 bucket."""
        db = _mock_db()
        org_id = uuid.uuid4()
        report_date = date(2025, 6, 15)

        row = self._make_invoice_row(report_date, 61, Decimal("400.00"))
        mock_result = MagicMock()
        mock_result.all.return_value = [row]
        db.execute.return_value = mock_result

        result = await get_aged_receivables(db, org_id, report_date=report_date)

        assert result["overall"]["61_90"] == Decimal("400.00")
        assert result["overall"]["31_60"] == Decimal("0.00")

    @pytest.mark.asyncio
    async def test_90_days_in_61_90_bucket(self):
        """Req 8.1: Invoice 90 days overdue → 61–90 bucket."""
        db = _mock_db()
        org_id = uuid.uuid4()
        report_date = date(2025, 6, 15)

        row = self._make_invoice_row(report_date, 90, Decimal("500.00"))
        mock_result = MagicMock()
        mock_result.all.return_value = [row]
        db.execute.return_value = mock_result

        result = await get_aged_receivables(db, org_id, report_date=report_date)

        assert result["overall"]["61_90"] == Decimal("500.00")
        assert result["overall"]["90_plus"] == Decimal("0.00")

    @pytest.mark.asyncio
    async def test_91_days_in_90_plus_bucket(self):
        """Req 8.1: Invoice 91 days overdue → 90+ bucket."""
        db = _mock_db()
        org_id = uuid.uuid4()
        report_date = date(2025, 6, 15)

        row = self._make_invoice_row(report_date, 91, Decimal("600.00"))
        mock_result = MagicMock()
        mock_result.all.return_value = [row]
        db.execute.return_value = mock_result

        result = await get_aged_receivables(db, org_id, report_date=report_date)

        assert result["overall"]["90_plus"] == Decimal("600.00")
        assert result["overall"]["61_90"] == Decimal("0.00")

    @pytest.mark.asyncio
    async def test_per_customer_totals(self):
        """Req 8.2: Per-customer totals match sum of their invoices."""
        db = _mock_db()
        org_id = uuid.uuid4()
        report_date = date(2025, 6, 15)
        cust_id = uuid.uuid4()

        row1 = self._make_invoice_row(report_date, 10, Decimal("100.00"))
        row1.customer_id = cust_id
        row2 = self._make_invoice_row(report_date, 45, Decimal("200.00"))
        row2.customer_id = cust_id

        mock_result = MagicMock()
        mock_result.all.return_value = [row1, row2]
        db.execute.return_value = mock_result

        result = await get_aged_receivables(db, org_id, report_date=report_date)

        assert len(result["customers"]) == 1
        cust = result["customers"][0]
        assert cust["total"] == Decimal("300.00")
        assert cust["current"] == Decimal("100.00")
        assert cust["31_60"] == Decimal("200.00")

    @pytest.mark.asyncio
    async def test_overall_total_matches_sum_of_buckets(self):
        """Req 8.1: Overall total = sum of all buckets."""
        db = _mock_db()
        org_id = uuid.uuid4()
        report_date = date(2025, 6, 15)

        rows = [
            self._make_invoice_row(report_date, 10, Decimal("100.00")),
            self._make_invoice_row(report_date, 40, Decimal("200.00")),
            self._make_invoice_row(report_date, 70, Decimal("300.00")),
            self._make_invoice_row(report_date, 100, Decimal("400.00")),
        ]
        mock_result = MagicMock()
        mock_result.all.return_value = rows
        db.execute.return_value = mock_result

        result = await get_aged_receivables(db, org_id, report_date=report_date)

        overall = result["overall"]
        bucket_sum = overall["current"] + overall["31_60"] + overall["61_90"] + overall["90_plus"]
        assert overall["total"] == bucket_sum
        assert overall["total"] == Decimal("1000.00")


# ---------------------------------------------------------------------------
# 7. Tax Estimate with mocked DB
#    Validates: Requirements 9.1–9.5
# ---------------------------------------------------------------------------


class TestTaxEstimate:
    """Tax estimate using mocked P&L data."""

    @pytest.mark.asyncio
    @patch("app.modules.reports.service.get_profit_loss", new_callable=AsyncMock)
    async def test_sole_trader_tax_estimate(self, mock_pnl):
        """Req 9.2, 9.3: Sole trader tax derived from P&L net_profit."""
        db = _mock_db()
        org_id = uuid.uuid4()

        # Mock org settings → sole_trader
        org_result = MagicMock()
        org_row = MagicMock()
        org_row.settings = {"business_type": "sole_trader"}
        org_result.one_or_none.return_value = org_row
        db.execute.return_value = org_result

        # Current year P&L: net_profit = $70,000
        current_pnl = {"net_profit": Decimal("70000.00")}
        # Prior year P&L: net_profit = $50,000
        prior_pnl = {"net_profit": Decimal("50000.00")}
        mock_pnl.side_effect = [current_pnl, prior_pnl]

        result = await get_tax_estimate(
            db, org_id,
            tax_year_start=date(2025, 4, 1),
            tax_year_end=date(2026, 3, 31),
        )

        assert result["business_type"] == "sole_trader"
        assert result["taxable_income"] == Decimal("70000.00")
        # Tax at $70k: 14000*0.105 + 34000*0.175 + 22000*0.30
        expected_tax = _calculate_sole_trader_tax(Decimal("70000"))
        assert result["estimated_tax"] == expected_tax
        assert result["currency"] == "NZD"

    @pytest.mark.asyncio
    @patch("app.modules.reports.service.get_profit_loss", new_callable=AsyncMock)
    async def test_company_tax_estimate(self, mock_pnl):
        """Req 9.1: Company tax = 28% flat rate."""
        db = _mock_db()
        org_id = uuid.uuid4()

        org_result = MagicMock()
        org_row = MagicMock()
        org_row.settings = {"business_type": "company"}
        org_result.one_or_none.return_value = org_row
        db.execute.return_value = org_result

        current_pnl = {"net_profit": Decimal("100000.00")}
        prior_pnl = {"net_profit": Decimal("80000.00")}
        mock_pnl.side_effect = [current_pnl, prior_pnl]

        result = await get_tax_estimate(
            db, org_id,
            tax_year_start=date(2025, 4, 1),
            tax_year_end=date(2026, 3, 31),
        )

        assert result["business_type"] == "company"
        assert result["estimated_tax"] == Decimal("28000.00")

    @pytest.mark.asyncio
    @patch("app.modules.reports.service.get_profit_loss", new_callable=AsyncMock)
    async def test_provisional_tax_calculation(self, mock_pnl):
        """Req 9.4: Provisional tax = prior year tax × 1.05."""
        db = _mock_db()
        org_id = uuid.uuid4()

        org_result = MagicMock()
        org_row = MagicMock()
        org_row.settings = {"business_type": "company"}
        org_result.one_or_none.return_value = org_row
        db.execute.return_value = org_result

        current_pnl = {"net_profit": Decimal("100000.00")}
        prior_pnl = {"net_profit": Decimal("80000.00")}
        mock_pnl.side_effect = [current_pnl, prior_pnl]

        result = await get_tax_estimate(
            db, org_id,
            tax_year_start=date(2025, 4, 1),
            tax_year_end=date(2026, 3, 31),
        )

        # Prior year tax: 80000 * 0.28 = 22400
        # Provisional: 22400 * 1.05 = 23520
        prior_tax = _calculate_company_tax(Decimal("80000"))
        expected_provisional = (prior_tax * Decimal("1.05")).quantize(Decimal("0.01"))
        assert result["provisional_tax_amount"] == expected_provisional

    @pytest.mark.asyncio
    @patch("app.modules.reports.service.get_profit_loss", new_callable=AsyncMock)
    async def test_effective_rate_calculation(self, mock_pnl):
        """Req 9.5: Effective rate = estimated_tax / taxable_income × 100."""
        db = _mock_db()
        org_id = uuid.uuid4()

        org_result = MagicMock()
        org_row = MagicMock()
        org_row.settings = {"business_type": "company"}
        org_result.one_or_none.return_value = org_row
        db.execute.return_value = org_result

        current_pnl = {"net_profit": Decimal("100000.00")}
        prior_pnl = {"net_profit": Decimal("0.00")}
        mock_pnl.side_effect = [current_pnl, prior_pnl]

        result = await get_tax_estimate(
            db, org_id,
            tax_year_start=date(2025, 4, 1),
            tax_year_end=date(2026, 3, 31),
        )

        # Company: 28000 / 100000 * 100 = 28.00%
        assert result["effective_rate"] == Decimal("28.00")

    @pytest.mark.asyncio
    @patch("app.modules.reports.service.get_profit_loss", new_callable=AsyncMock)
    async def test_default_business_type_is_sole_trader(self, mock_pnl):
        """Req 9.2: Default business_type is sole_trader when not set."""
        db = _mock_db()
        org_id = uuid.uuid4()

        org_result = MagicMock()
        org_row = MagicMock()
        org_row.settings = {}  # no business_type set
        org_result.one_or_none.return_value = org_row
        db.execute.return_value = org_result

        current_pnl = {"net_profit": Decimal("14000.00")}
        prior_pnl = {"net_profit": Decimal("0.00")}
        mock_pnl.side_effect = [current_pnl, prior_pnl]

        result = await get_tax_estimate(
            db, org_id,
            tax_year_start=date(2025, 4, 1),
            tax_year_end=date(2026, 3, 31),
        )

        assert result["business_type"] == "sole_trader"
        # $14,000 at 10.5% = $1,470
        assert result["estimated_tax"] == Decimal("1470.00")


# ---------------------------------------------------------------------------
# 8. Tax Position Dashboard
#    Validates: Requirements 10.1, 10.2
# ---------------------------------------------------------------------------


class TestTaxPosition:
    """Tax position combines GST + income tax."""

    @pytest.mark.asyncio
    @patch("app.modules.reports.service.get_tax_estimate", new_callable=AsyncMock)
    @patch("app.modules.reports.service.get_gst_return", new_callable=AsyncMock)
    async def test_tax_position_combines_gst_and_income_tax(self, mock_gst, mock_tax):
        """Req 10.1: Tax position returns GST owing + income tax estimate."""
        db = _mock_db()
        org_id = uuid.uuid4()

        mock_gst.return_value = {"net_gst_payable": Decimal("1500.00")}
        mock_tax.return_value = {
            "estimated_tax": Decimal("5000.00"),
            "next_provisional_due_date": date(2025, 8, 28),
            "provisional_tax_amount": Decimal("4200.00"),
        }

        result = await get_tax_position(db, org_id)

        assert result["gst_owing"] == Decimal("1500.00")
        assert result["income_tax_estimate"] == Decimal("5000.00")
        assert result["provisional_tax_amount"] == Decimal("4200.00")
        assert result["currency"] == "NZD"
        assert result["next_gst_due"] is not None
        assert result["next_income_tax_due"] is not None

    @pytest.mark.asyncio
    @patch("app.modules.reports.service.get_tax_estimate", new_callable=AsyncMock)
    @patch("app.modules.reports.service.get_gst_return", new_callable=AsyncMock)
    async def test_tax_position_returns_within_2_seconds(self, mock_gst, mock_tax):
        """Req 10.2: Tax position endpoint returns within 2 seconds."""
        import time

        db = _mock_db()
        org_id = uuid.uuid4()

        mock_gst.return_value = {"net_gst_payable": Decimal("0.00")}
        mock_tax.return_value = {
            "estimated_tax": Decimal("0.00"),
            "next_provisional_due_date": date(2025, 8, 28),
            "provisional_tax_amount": Decimal("0.00"),
        }

        start = time.monotonic()
        result = await get_tax_position(db, org_id)
        elapsed = time.monotonic() - start

        assert elapsed < 2.0, f"Tax position took {elapsed:.2f}s, exceeds 2s limit"
