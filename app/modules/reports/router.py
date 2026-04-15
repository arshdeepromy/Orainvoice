"""Reports router — org-level reporting endpoints.

All reports are filterable by date range (day/week/month/quarter/year/custom)
and exportable as PDF or CSV.

Requirements: 45.1, 45.2, 45.3, 45.4, 45.5, 45.6, 45.7, 66.4
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.reports.schemas import (
    AgedReceivablesResponse,
    BalanceSheetResponse,
    CarjamUsageResponse,
    CustomerStatementResponse,
    DatePreset,
    ExportFormat,
    FleetReportResponse,
    GSTReturnResponse,
    InvoiceStatusReportResponse,
    OutstandingInvoicesResponse,
    ProfitLossResponse,
    RevenueSummaryResponse,
    SmsUsageResponse,
    StorageUsageResponse,
    TaxEstimateResponse,
    TaxPositionResponse,
    TopServicesResponse,
)
from app.modules.reports.service import (
    get_aged_receivables,
    get_balance_sheet,
    get_carjam_usage,
    get_customer_statement,
    get_fleet_report,
    get_gst_return,
    get_invoice_status_report,
    get_outstanding_invoices,
    get_profit_loss,
    get_revenue_summary,
    get_sms_usage,
    get_storage_usage,
    get_tax_estimate,
    get_tax_position,
    get_top_services,
    resolve_date_range,
)

router = APIRouter()


def _resolve_branch_id(request: Request, branch_id_param: str | None) -> uuid.UUID | None:
    """Resolve branch UUID from query param or X-Branch-Id header (via middleware).

    Query param takes precedence. Falls back to request.state.branch_id
    set by BranchContextMiddleware from the X-Branch-Id header.
    """
    if branch_id_param:
        return uuid.UUID(branch_id_param)
    middleware_branch = getattr(request, "state", None) and getattr(request.state, "branch_id", None)
    if middleware_branch is not None:
        return middleware_branch if isinstance(middleware_branch, uuid.UUID) else uuid.UUID(str(middleware_branch))
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_org_id(request: Request) -> uuid.UUID | None:
    """Extract org_id from request state."""
    org_id = getattr(request.state, "org_id", None)
    try:
        return uuid.UUID(org_id) if org_id else None
    except (ValueError, TypeError):
        return None


def _parse_date(value: str | None) -> "date | None":
    """Parse an ISO date string, returning None on failure."""
    if not value:
        return None
    from datetime import date as _date

    try:
        return _date.fromisoformat(value)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# GET /reports/revenue — Revenue Summary
# ---------------------------------------------------------------------------

@router.get(
    "/revenue",
    response_model=RevenueSummaryResponse,
    summary="Revenue summary report",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def revenue_report(
    request: Request,
    preset: DatePreset | None = Query(None, description="Date preset"),
    start_date: str | None = Query(None, description="Custom start (YYYY-MM-DD)"),
    end_date: str | None = Query(None, description="Custom end (YYYY-MM-DD)"),
    export: ExportFormat | None = Query(None, description="Export format"),
    branch_id: str | None = Query(None, description="Optional branch UUID to scope report"),
    db: AsyncSession = Depends(get_db_session),
):
    """Revenue summary for the organisation.

    Requirements: 45.1, 45.2, 45.3, 20.1
    """
    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    branch_uuid = None
    if branch_id:
        try:
            branch_uuid = uuid.UUID(branch_id)
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid branch_id format"})
    else:
        branch_uuid = _resolve_branch_id(request, None)

    period_start, period_end = resolve_date_range(
        preset.value if preset else None,
        _parse_date(start_date),
        _parse_date(end_date),
    )
    data = await get_revenue_summary(db, org_id, period_start, period_end, branch_id=branch_uuid)
    return RevenueSummaryResponse(**data)


# ---------------------------------------------------------------------------
# GET /reports/invoices/status — Invoice Status Report
# ---------------------------------------------------------------------------

@router.get(
    "/invoices/status",
    response_model=InvoiceStatusReportResponse,
    summary="Invoice status breakdown",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def invoice_status_report(
    request: Request,
    preset: DatePreset | None = Query(None),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    export: ExportFormat | None = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    """Invoice status breakdown report.

    Requirements: 45.1, 45.2
    """
    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    period_start, period_end = resolve_date_range(
        preset.value if preset else None,
        _parse_date(start_date),
        _parse_date(end_date),
    )
    data = await get_invoice_status_report(db, org_id, period_start, period_end)
    return InvoiceStatusReportResponse(**data)


# ---------------------------------------------------------------------------
# GET /reports/outstanding — Outstanding Invoices
# ---------------------------------------------------------------------------

@router.get(
    "/outstanding",
    response_model=OutstandingInvoicesResponse,
    summary="Outstanding invoices with reminder support",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def outstanding_invoices_report(
    request: Request,
    branch_id: str | None = Query(None, description="Optional branch UUID to scope report"),
    db: AsyncSession = Depends(get_db_session),
):
    """Outstanding invoices report with one-click reminder button.

    Requirements: 45.1, 45.5, 20.3
    """
    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    branch_uuid = None
    if branch_id:
        try:
            branch_uuid = uuid.UUID(branch_id)
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid branch_id format"})
    else:
        branch_uuid = _resolve_branch_id(request, None)

    data = await get_outstanding_invoices(db, org_id, branch_id=branch_uuid)
    return OutstandingInvoicesResponse(**data)


# ---------------------------------------------------------------------------
# GET /reports/top-services — Top Services by Revenue
# ---------------------------------------------------------------------------

@router.get(
    "/top-services",
    response_model=TopServicesResponse,
    summary="Top services by revenue",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def top_services_report(
    request: Request,
    preset: DatePreset | None = Query(None),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    export: ExportFormat | None = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    """Top services by revenue.

    Requirements: 45.1, 45.2
    """
    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    period_start, period_end = resolve_date_range(
        preset.value if preset else None,
        _parse_date(start_date),
        _parse_date(end_date),
    )
    data = await get_top_services(db, org_id, period_start, period_end, limit=limit)
    return TopServicesResponse(**data)


# ---------------------------------------------------------------------------
# GET /reports/gst-return — GST Return Summary
# ---------------------------------------------------------------------------

@router.get(
    "/gst-return",
    response_model=GSTReturnResponse,
    summary="GST return summary for IRD filing",
    dependencies=[require_role("org_admin")],
)
async def gst_return_report(
    request: Request,
    preset: DatePreset | None = Query(None),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    export: ExportFormat | None = Query(None),
    branch_id: str | None = Query(None, description="Optional branch UUID to scope report"),
    db: AsyncSession = Depends(get_db_session),
):
    """GST return summary formatted for IRD filing.

    Requirements: 45.6, 20.2
    """
    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    branch_uuid = None
    if branch_id:
        try:
            branch_uuid = uuid.UUID(branch_id)
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid branch_id format"})

    period_start, period_end = resolve_date_range(
        preset.value if preset else None,
        _parse_date(start_date),
        _parse_date(end_date),
    )
    data = await get_gst_return(db, org_id, period_start, period_end, branch_id=branch_uuid)
    return GSTReturnResponse(**data)


# ---------------------------------------------------------------------------
# GET /reports/customer-statement/{id} — Customer Statement
# ---------------------------------------------------------------------------

@router.get(
    "/customer-statement/{customer_id}",
    response_model=CustomerStatementResponse,
    summary="Printable customer statement",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def customer_statement_report(
    customer_id: uuid.UUID,
    request: Request,
    preset: DatePreset | None = Query(None),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    export: ExportFormat | None = Query(None),
    branch_id: str | None = Query(None, description="Optional branch UUID to scope report"),
    db: AsyncSession = Depends(get_db_session),
):
    """Printable/emailable customer statement.

    Requirements: 45.7, 20.4
    """
    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    branch_uuid = None
    if branch_id:
        try:
            branch_uuid = uuid.UUID(branch_id)
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid branch_id format"})

    period_start, period_end = resolve_date_range(
        preset.value if preset else None,
        _parse_date(start_date),
        _parse_date(end_date),
    )
    data = await get_customer_statement(db, org_id, customer_id, period_start, period_end, branch_id=branch_uuid)
    if data is None:
        return JSONResponse(status_code=404, content={"detail": "Customer not found"})
    return CustomerStatementResponse(**data)


# ---------------------------------------------------------------------------
# GET /reports/carjam-usage — Carjam Usage Report
# ---------------------------------------------------------------------------

@router.get(
    "/carjam-usage",
    response_model=CarjamUsageResponse,
    summary="Carjam API usage report",
    dependencies=[require_role("org_admin")],
)
async def carjam_usage_report(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
):
    """Carjam API usage for the organisation.

    Requirements: 45.1
    """
    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    date_from = date.fromisoformat(from_date) if from_date else None
    date_to = date.fromisoformat(to_date) if to_date else None

    data = await get_carjam_usage(db, org_id, date_from=date_from, date_to=date_to)
    return CarjamUsageResponse(**data)


# ---------------------------------------------------------------------------
# GET /reports/sms-usage — SMS Usage Report
# ---------------------------------------------------------------------------

@router.get(
    "/sms-usage",
    response_model=SmsUsageResponse,
    summary="SMS usage report",
    dependencies=[require_role("org_admin")],
)
async def sms_usage_report(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
):
    """SMS usage for the organisation.

    Returns total sent, included quota, package credits, overage count,
    overage charge, per-SMS cost, and reset timestamp.

    Requirements: 7.1
    """
    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    data = await get_sms_usage(
        db, org_id,
        date_from=_parse_date(start_date),
        date_to=_parse_date(end_date),
    )
    return SmsUsageResponse(**data)


# ---------------------------------------------------------------------------
# GET /reports/storage — Storage Usage Report
# ---------------------------------------------------------------------------

@router.get(
    "/storage",
    response_model=StorageUsageResponse,
    summary="Storage usage report",
    dependencies=[require_role("org_admin")],
)
async def storage_usage_report(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Storage usage for the organisation.

    Requirements: 45.1
    """
    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    data = await get_storage_usage(db, org_id)
    return StorageUsageResponse(**data)


# ---------------------------------------------------------------------------
# GET /reports/fleet/{id} — Fleet Account Report
# ---------------------------------------------------------------------------

@router.get(
    "/fleet/{fleet_id}",
    response_model=FleetReportResponse,
    summary="Fleet account report",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def fleet_report(
    fleet_id: uuid.UUID,
    request: Request,
    preset: DatePreset | None = Query(None),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    export: ExportFormat | None = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    """Fleet account report: total spend, vehicles serviced, outstanding balance.

    Requirements: 66.4
    """
    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    period_start, period_end = resolve_date_range(
        preset.value if preset else None,
        _parse_date(start_date),
        _parse_date(end_date),
    )
    data = await get_fleet_report(db, org_id, fleet_id, period_start, period_end)
    if data is None:
        return JSONResponse(status_code=404, content={"detail": "Fleet account not found"})
    return FleetReportResponse(**data)


# ---------------------------------------------------------------------------
# GET /reports/profit-loss — Profit & Loss Report
# ---------------------------------------------------------------------------

@router.get(
    "/profit-loss",
    response_model=ProfitLossResponse,
    summary="Profit & Loss report",
    dependencies=[require_role("org_admin")],
)
async def profit_loss_report(
    request: Request,
    period_start: date = Query(..., description="Period start date (YYYY-MM-DD)"),
    period_end: date = Query(..., description="Period end date (YYYY-MM-DD)"),
    basis: str = Query("accrual", description="Accounting basis: accrual or cash"),
    branch_id: uuid.UUID | None = Query(None, description="Optional branch UUID filter"),
    db: AsyncSession = Depends(get_db_session),
):
    """Profit & Loss report for a date range with optional basis and branch filter.

    Requirements: 6.1–6.7
    """
    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    resolved_branch = branch_id or _resolve_branch_id(request, None)
    data = await get_profit_loss(db, org_id, period_start, period_end, basis=basis, branch_id=resolved_branch)
    return ProfitLossResponse(**data)


# ---------------------------------------------------------------------------
# GET /reports/balance-sheet — Balance Sheet Report
# ---------------------------------------------------------------------------

@router.get(
    "/balance-sheet",
    response_model=BalanceSheetResponse,
    summary="Balance Sheet report",
    dependencies=[require_role("org_admin")],
)
async def balance_sheet_report(
    request: Request,
    as_at_date: date = Query(..., description="Balance sheet as-at date (YYYY-MM-DD)"),
    branch_id: uuid.UUID | None = Query(None, description="Optional branch UUID filter"),
    db: AsyncSession = Depends(get_db_session),
):
    """Balance Sheet as at a specific date with optional branch filter.

    Requirements: 7.1–7.5
    """
    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    resolved_branch = branch_id or _resolve_branch_id(request, None)
    data = await get_balance_sheet(db, org_id, as_at_date, branch_id=resolved_branch)
    return BalanceSheetResponse(**data)


# ---------------------------------------------------------------------------
# GET /reports/aged-receivables — Aged Receivables Report
# ---------------------------------------------------------------------------

@router.get(
    "/aged-receivables",
    response_model=AgedReceivablesResponse,
    summary="Aged receivables report",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def aged_receivables_report(
    request: Request,
    report_date: date | None = Query(None, description="Report date (defaults to today)"),
    db: AsyncSession = Depends(get_db_session),
):
    """Aged receivables grouped by customer into ageing buckets.

    Requirements: 8.1–8.3
    """
    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    data = await get_aged_receivables(db, org_id, report_date=report_date)
    return AgedReceivablesResponse(**data)


# ---------------------------------------------------------------------------
# GET /reports/tax-estimate — Income Tax Estimate
# ---------------------------------------------------------------------------

@router.get(
    "/tax-estimate",
    response_model=TaxEstimateResponse,
    summary="Income tax estimate",
    dependencies=[require_role("org_admin")],
)
async def tax_estimate_report(
    request: Request,
    tax_year_start: date = Query(..., description="Tax year start date (YYYY-MM-DD)"),
    tax_year_end: date = Query(..., description="Tax year end date (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db_session),
):
    """Income tax estimate for a tax year using NZ brackets.

    Requirements: 9.1–9.6
    """
    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    data = await get_tax_estimate(db, org_id, tax_year_start, tax_year_end)
    return TaxEstimateResponse(**data)


# ---------------------------------------------------------------------------
# GET /reports/tax-position — Tax Position Dashboard
# ---------------------------------------------------------------------------

@router.get(
    "/tax-position",
    response_model=TaxPositionResponse,
    summary="Combined tax position dashboard",
    dependencies=[require_role("org_admin")],
)
async def tax_position_report(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Combined GST + income tax position with next due dates.

    Requirements: 10.1, 10.2
    """
    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    data = await get_tax_position(db, org_id)
    return TaxPositionResponse(**data)
