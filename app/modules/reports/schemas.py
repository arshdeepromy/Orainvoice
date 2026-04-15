"""Pydantic schemas for org-level reports.

Requirements: 45.1, 45.2, 45.3, 45.4, 45.5, 45.6, 45.7, 66.4
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared filter / export enums
# ---------------------------------------------------------------------------

class DatePreset(str, Enum):
    day = "day"
    week = "week"
    month = "month"
    quarter = "quarter"
    year = "year"
    custom = "custom"


class ExportFormat(str, Enum):
    pdf = "pdf"
    csv = "csv"


# ---------------------------------------------------------------------------
# Revenue Summary  (GET /reports/revenue)
# ---------------------------------------------------------------------------

class RevenueSummaryResponse(BaseModel):
    total_revenue: Decimal = Field(description="Total revenue (ex-GST) for the period")
    total_gst: Decimal = Field(description="Total GST collected")
    total_inclusive: Decimal = Field(description="Total revenue incl. GST")
    invoice_count: int = Field(description="Number of invoices in the period")
    average_invoice: Decimal = Field(description="Average invoice value")
    total_refunds: Decimal = Field(default=Decimal("0"), description="Total refunds (incl. GST) in period")
    refund_gst: Decimal = Field(default=Decimal("0"), description="GST component of refunds")
    net_revenue: Decimal = Field(default=Decimal("0"), description="Revenue after refunds (ex-GST)")
    net_gst: Decimal = Field(default=Decimal("0"), description="GST after refunds")
    period_start: date
    period_end: date


# ---------------------------------------------------------------------------
# Invoice Status Report  (GET /reports/invoices/status)
# ---------------------------------------------------------------------------

class InvoiceStatusBreakdown(BaseModel):
    status: str
    count: int
    total: Decimal


class InvoiceStatusReportResponse(BaseModel):
    breakdown: list[InvoiceStatusBreakdown]
    period_start: date
    period_end: date


# ---------------------------------------------------------------------------
# Outstanding Invoices  (GET /reports/outstanding)
# ---------------------------------------------------------------------------

class OutstandingInvoiceRow(BaseModel):
    invoice_id: uuid.UUID
    invoice_number: str | None
    customer_name: str
    customer_id: uuid.UUID
    vehicle_rego: str | None
    issue_date: date | None
    due_date: date | None
    total: Decimal
    balance_due: Decimal
    days_overdue: int


class OutstandingInvoicesResponse(BaseModel):
    invoices: list[OutstandingInvoiceRow]
    total_outstanding: Decimal
    count: int


# ---------------------------------------------------------------------------
# Top Services  (GET /reports/top-services)
# ---------------------------------------------------------------------------

class TopServiceRow(BaseModel):
    description: str
    catalogue_item_id: uuid.UUID | None
    count: int
    total_revenue: Decimal


class TopServicesResponse(BaseModel):
    services: list[TopServiceRow]
    period_start: date
    period_end: date


# ---------------------------------------------------------------------------
# GST Return Summary  (GET /reports/gst-return)
# ---------------------------------------------------------------------------

class GSTReturnResponse(BaseModel):
    total_sales: Decimal = Field(description="Total sales (incl. GST)")
    total_gst_collected: Decimal = Field(description="Total GST collected on sales")
    net_gst: Decimal = Field(description="Net GST payable after refunds")
    standard_rated_sales: Decimal = Field(description="Standard-rated sales (ex-GST)")
    standard_rated_gst: Decimal = Field(description="GST on standard-rated sales")
    zero_rated_sales: Decimal = Field(description="Zero-rated / GST-exempt sales")
    total_refunds: Decimal = Field(default=Decimal("0"), description="Total refund amount (incl. GST) in period")
    refund_gst: Decimal = Field(default=Decimal("0"), description="GST component of refunds in period")
    adjusted_total_sales: Decimal = Field(default=Decimal("0"), description="Net sales after refunds (incl. GST)")
    adjusted_gst_collected: Decimal = Field(default=Decimal("0"), description="Net GST after refunds")
    period_start: date
    period_end: date



# ---------------------------------------------------------------------------
# Customer Statement  (GET /reports/customer-statement/{id})
# ---------------------------------------------------------------------------

class StatementLineItem(BaseModel):
    date: date | None
    description: str
    reference: str | None
    debit: Decimal
    credit: Decimal
    balance: Decimal


class CustomerStatementResponse(BaseModel):
    customer_id: uuid.UUID
    customer_name: str
    items: list[StatementLineItem]
    opening_balance: Decimal
    closing_balance: Decimal
    period_start: date
    period_end: date


# ---------------------------------------------------------------------------
# Carjam Usage  (GET /reports/carjam-usage)
# ---------------------------------------------------------------------------

class CarjamDailyBreakdown(BaseModel):
    date: date
    lookups: int


class CarjamUsageResponse(BaseModel):
    total_lookups: int
    included_in_plan: int
    overage_lookups: int
    overage_charge: float
    daily_breakdown: list[CarjamDailyBreakdown]


# ---------------------------------------------------------------------------
# SMS Usage  (GET /reports/sms-usage)
# ---------------------------------------------------------------------------

class SmsUsageResponse(BaseModel):
    total_sent: int
    included_in_plan: int
    package_credits_remaining: int
    effective_quota: int
    overage_count: int
    overage_charge_nzd: float
    per_sms_cost_nzd: float
    reset_at: datetime | None


# ---------------------------------------------------------------------------
# Storage Usage  (GET /reports/storage)
# ---------------------------------------------------------------------------

class StorageBreakdownItem(BaseModel):
    category: str
    bytes: int


class StorageUsageResponse(BaseModel):
    used_bytes: int
    used_gb: float
    quota_gb: float
    usage_percent: float
    breakdown: list[StorageBreakdownItem] = []


# ---------------------------------------------------------------------------
# Fleet Account Report  (GET /reports/fleet/{id})
# ---------------------------------------------------------------------------

class FleetReportResponse(BaseModel):
    fleet_account_id: uuid.UUID
    fleet_name: str
    total_spend: Decimal
    vehicles_serviced: int
    outstanding_balance: Decimal
    period_start: date
    period_end: date


# ---------------------------------------------------------------------------
# Profit & Loss Report  (GET /reports/profit-loss)
# Requirements: 6.2
# ---------------------------------------------------------------------------

class ProfitLossLineItem(BaseModel):
    account_id: uuid.UUID
    account_code: str
    account_name: str
    amount: Decimal


class ProfitLossResponse(BaseModel):
    currency: str = "NZD"
    revenue_items: list[ProfitLossLineItem] = []
    total_revenue: Decimal
    cogs_items: list[ProfitLossLineItem] = []
    total_cogs: Decimal
    gross_profit: Decimal
    gross_margin_pct: Decimal
    expense_items: list[ProfitLossLineItem] = []
    total_expenses: Decimal
    net_profit: Decimal
    net_margin_pct: Decimal
    period_start: date
    period_end: date
    basis: str


# ---------------------------------------------------------------------------
# Balance Sheet Report  (GET /reports/balance-sheet)
# Requirements: 7.2
# ---------------------------------------------------------------------------

class BalanceSheetLineItem(BaseModel):
    account_id: uuid.UUID
    account_code: str
    account_name: str
    sub_type: str | None = None
    balance: Decimal


class BalanceSheetAssets(BaseModel):
    current: list[BalanceSheetLineItem] = []
    non_current: list[BalanceSheetLineItem] = []
    total: Decimal


class BalanceSheetLiabilities(BaseModel):
    current: list[BalanceSheetLineItem] = []
    non_current: list[BalanceSheetLineItem] = []
    total: Decimal


class BalanceSheetEquity(BaseModel):
    items: list[BalanceSheetLineItem] = []
    total: Decimal


class BalanceSheetResponse(BaseModel):
    currency: str = "NZD"
    as_at_date: date
    assets: BalanceSheetAssets
    liabilities: BalanceSheetLiabilities
    equity: BalanceSheetEquity
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal
    balanced: bool


# ---------------------------------------------------------------------------
# Aged Receivables Report  (GET /reports/aged-receivables)
# Requirements: 8.1
# ---------------------------------------------------------------------------

class AgedReceivablesInvoice(BaseModel):
    invoice_id: uuid.UUID
    invoice_number: str | None = None
    due_date: date | None = None
    balance_due: Decimal
    days_overdue: int
    bucket: str


class AgedReceivablesCustomer(BaseModel):
    customer_id: uuid.UUID
    customer_name: str
    current: Decimal
    days_31_60: Decimal = Field(alias="31_60")
    days_61_90: Decimal = Field(alias="61_90")
    days_90_plus: Decimal = Field(alias="90_plus")
    total: Decimal
    invoices: list[AgedReceivablesInvoice] = []

    model_config = {"populate_by_name": True}


class AgedReceivablesOverall(BaseModel):
    current: Decimal
    days_31_60: Decimal = Field(alias="31_60")
    days_61_90: Decimal = Field(alias="61_90")
    days_90_plus: Decimal = Field(alias="90_plus")
    total: Decimal

    model_config = {"populate_by_name": True}


class AgedReceivablesResponse(BaseModel):
    report_date: date
    customers: list[AgedReceivablesCustomer] = []
    overall: AgedReceivablesOverall


# ---------------------------------------------------------------------------
# Income Tax Estimate  (GET /reports/tax-estimate)
# Requirements: 9.5
# ---------------------------------------------------------------------------

class TaxEstimateResponse(BaseModel):
    currency: str = "NZD"
    business_type: str
    taxable_income: Decimal
    estimated_tax: Decimal
    effective_rate: Decimal
    provisional_tax_amount: Decimal
    next_provisional_due_date: date | None = None
    already_paid: Decimal
    balance_owing: Decimal
    tax_year_start: date
    tax_year_end: date


# ---------------------------------------------------------------------------
# Tax Position Dashboard  (GET /reports/tax-position)
# Requirements: 10.1
# ---------------------------------------------------------------------------

class TaxPositionResponse(BaseModel):
    currency: str = "NZD"
    gst_owing: Decimal
    next_gst_due: date | None = None
    income_tax_estimate: Decimal
    next_income_tax_due: date | None = None
    provisional_tax_amount: Decimal
    tax_year_start: date
    tax_year_end: date
