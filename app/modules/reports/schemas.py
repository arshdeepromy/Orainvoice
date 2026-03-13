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
    total_gst_collected: Decimal = Field(description="Total GST collected")
    net_gst: Decimal = Field(description="Net GST payable")
    standard_rated_sales: Decimal = Field(description="Standard-rated sales (ex-GST)")
    standard_rated_gst: Decimal = Field(description="GST on standard-rated sales")
    zero_rated_sales: Decimal = Field(description="Zero-rated / GST-exempt sales")
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
