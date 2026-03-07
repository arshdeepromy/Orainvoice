"""Pydantic v2 schemas for the enhanced reporting module.

Covers request filters, report output shapes, and schedule management.

**Validates: Task 54 — Enhanced Reporting System**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request / filter schemas
# ---------------------------------------------------------------------------

class ReportFilters(BaseModel):
    """Common filters accepted by all report endpoints."""
    date_from: date | None = None
    date_to: date | None = None
    location_id: uuid.UUID | None = None
    currency: str | None = None


# ---------------------------------------------------------------------------
# Inventory report schemas
# ---------------------------------------------------------------------------

class StockValuationItem(BaseModel):
    product_id: uuid.UUID
    product_name: str
    sku: str | None = None
    quantity: Decimal
    cost_price: Decimal
    valuation: Decimal


class StockValuationReport(BaseModel):
    items: list[StockValuationItem] = []
    total_valuation: Decimal = Decimal("0")


class StockMovementSummaryItem(BaseModel):
    movement_type: str
    total_quantity: Decimal
    movement_count: int


class StockMovementSummaryReport(BaseModel):
    items: list[StockMovementSummaryItem] = []


class LowStockItem(BaseModel):
    product_id: uuid.UUID
    product_name: str
    sku: str | None = None
    current_quantity: Decimal
    low_stock_threshold: Decimal


class LowStockReport(BaseModel):
    items: list[LowStockItem] = []


class DeadStockItem(BaseModel):
    product_id: uuid.UUID
    product_name: str
    sku: str | None = None
    quantity: Decimal
    last_movement_date: date | None = None


class DeadStockReport(BaseModel):
    items: list[DeadStockItem] = []
    days_threshold: int = 90


# ---------------------------------------------------------------------------
# Job report schemas
# ---------------------------------------------------------------------------

class JobProfitabilityItem(BaseModel):
    job_id: uuid.UUID
    job_number: str
    revenue: Decimal = Decimal("0")
    labour_cost: Decimal = Decimal("0")
    material_cost: Decimal = Decimal("0")
    expense_cost: Decimal = Decimal("0")
    profit: Decimal = Decimal("0")
    margin_percent: Decimal = Decimal("0")


class JobProfitabilityReport(BaseModel):
    items: list[JobProfitabilityItem] = []
    total_revenue: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")
    total_profit: Decimal = Decimal("0")


class JobStatusSummaryItem(BaseModel):
    status: str
    count: int


class JobStatusSummaryReport(BaseModel):
    items: list[JobStatusSummaryItem] = []


class AvgCompletionTimeItem(BaseModel):
    trade_category: str
    avg_days: Decimal


class AvgCompletionTimeReport(BaseModel):
    items: list[AvgCompletionTimeItem] = []


class StaffUtilisationItem(BaseModel):
    staff_id: uuid.UUID
    staff_name: str
    total_hours: Decimal = Decimal("0")
    billable_hours: Decimal = Decimal("0")
    utilisation_percent: Decimal = Decimal("0")


class StaffUtilisationReport(BaseModel):
    items: list[StaffUtilisationItem] = []


# ---------------------------------------------------------------------------
# Project report schemas
# ---------------------------------------------------------------------------

class ProjectProfitabilityItem(BaseModel):
    project_id: uuid.UUID
    project_name: str
    contract_value: Decimal = Decimal("0")
    total_costs: Decimal = Decimal("0")
    profit: Decimal = Decimal("0")
    margin_percent: Decimal = Decimal("0")


class ProjectProfitabilityReport(BaseModel):
    items: list[ProjectProfitabilityItem] = []


class ProgressClaimSummaryItem(BaseModel):
    project_id: uuid.UUID
    project_name: str
    total_claimed: Decimal = Decimal("0")
    total_paid: Decimal = Decimal("0")
    retention_held: Decimal = Decimal("0")


class ProgressClaimSummaryReport(BaseModel):
    items: list[ProgressClaimSummaryItem] = []


class VariationRegisterItem(BaseModel):
    variation_id: uuid.UUID
    project_name: str
    description: str
    status: str
    cost_impact: Decimal = Decimal("0")


class VariationRegisterReport(BaseModel):
    items: list[VariationRegisterItem] = []
    total_impact: Decimal = Decimal("0")


class RetentionSummaryItem(BaseModel):
    project_id: uuid.UUID
    project_name: str
    retention_held: Decimal = Decimal("0")
    retention_released: Decimal = Decimal("0")
    retention_balance: Decimal = Decimal("0")


class RetentionSummaryReport(BaseModel):
    items: list[RetentionSummaryItem] = []


# ---------------------------------------------------------------------------
# POS report schemas
# ---------------------------------------------------------------------------

class DailySalesByMethodItem(BaseModel):
    payment_method: str
    total: Decimal = Decimal("0")
    count: int = 0


class DailySalesByCategoryItem(BaseModel):
    category: str
    total: Decimal = Decimal("0")
    count: int = 0


class DailySalesSummaryReport(BaseModel):
    by_payment_method: list[DailySalesByMethodItem] = []
    by_category: list[DailySalesByCategoryItem] = []
    grand_total: Decimal = Decimal("0")


class SessionReconciliationItem(BaseModel):
    session_id: uuid.UUID
    user_name: str | None = None
    opening_cash: Decimal = Decimal("0")
    expected_cash: Decimal = Decimal("0")
    actual_cash: Decimal | None = None
    variance: Decimal = Decimal("0")


class SessionReconciliationReport(BaseModel):
    items: list[SessionReconciliationItem] = []


class HourlySalesItem(BaseModel):
    hour: int
    total: Decimal = Decimal("0")
    count: int = 0


class HourlySalesHeatmapReport(BaseModel):
    items: list[HourlySalesItem] = []


# ---------------------------------------------------------------------------
# Hospitality report schemas
# ---------------------------------------------------------------------------

class TableTurnoverItem(BaseModel):
    table_number: str
    covers: int = 0
    turnover_count: int = 0


class TableTurnoverReport(BaseModel):
    items: list[TableTurnoverItem] = []
    avg_turnover: Decimal = Decimal("0")


class AvgOrderValueReport(BaseModel):
    avg_order_value: Decimal = Decimal("0")
    total_orders: int = 0
    total_revenue: Decimal = Decimal("0")


class KitchenPrepTimeItem(BaseModel):
    item_name: str
    avg_prep_minutes: Decimal = Decimal("0")
    order_count: int = 0


class KitchenPrepTimeReport(BaseModel):
    items: list[KitchenPrepTimeItem] = []


class TipSummaryByStaffItem(BaseModel):
    staff_id: uuid.UUID
    staff_name: str
    total_tips: Decimal = Decimal("0")
    tip_count: int = 0


class TipSummaryReport(BaseModel):
    items: list[TipSummaryByStaffItem] = []
    grand_total: Decimal = Decimal("0")


# ---------------------------------------------------------------------------
# Tax return report schemas
# ---------------------------------------------------------------------------

class GSTReturnReport(BaseModel):
    """NZ GST return."""
    total_sales_incl: Decimal = Decimal("0")
    total_sales_excl: Decimal = Decimal("0")
    gst_collected: Decimal = Decimal("0")
    zero_rated_sales: Decimal = Decimal("0")
    gst_on_purchases: Decimal = Decimal("0")
    net_gst: Decimal = Decimal("0")


class BASReport(BaseModel):
    """AU BAS report."""
    total_sales: Decimal = Decimal("0")
    gst_on_sales: Decimal = Decimal("0")
    gst_on_purchases: Decimal = Decimal("0")
    net_gst: Decimal = Decimal("0")
    total_wages: Decimal = Decimal("0")
    payg_withheld: Decimal = Decimal("0")


class VATReturnReport(BaseModel):
    """UK VAT return."""
    box1_vat_due_sales: Decimal = Decimal("0")
    box2_vat_due_acquisitions: Decimal = Decimal("0")
    box3_total_vat_due: Decimal = Decimal("0")
    box4_vat_reclaimed: Decimal = Decimal("0")
    box5_net_vat: Decimal = Decimal("0")
    box6_total_sales_excl: Decimal = Decimal("0")
    box7_total_purchases_excl: Decimal = Decimal("0")
    box8_total_supplies_ex_vat: Decimal = Decimal("0")
    box9_total_acquisitions_ex_vat: Decimal = Decimal("0")


# ---------------------------------------------------------------------------
# Schedule schemas
# ---------------------------------------------------------------------------

class ReportScheduleCreate(BaseModel):
    report_type: str
    frequency: str = "daily"  # daily, weekly, monthly
    filters: dict[str, Any] = {}
    recipients: list[str] = []
    is_active: bool = True


class ReportScheduleResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    report_type: str
    frequency: str
    filters: dict[str, Any]
    recipients: list[str]
    is_active: bool
    last_generated_at: datetime | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Generic report response wrapper
# ---------------------------------------------------------------------------

class ReportResponse(BaseModel):
    report_type: str
    generated_at: datetime
    filters: ReportFilters
    data: Any
