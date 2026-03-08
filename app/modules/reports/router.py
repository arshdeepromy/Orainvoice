"""Reports router — org-level reporting endpoints.

All reports are filterable by date range (day/week/month/quarter/year/custom)
and exportable as PDF or CSV.

Requirements: 45.1, 45.2, 45.3, 45.4, 45.5, 45.6, 45.7, 66.4
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.reports.schemas import (
    CarjamUsageResponse,
    CustomerStatementResponse,
    DatePreset,
    ExportFormat,
    FleetReportResponse,
    GSTReturnResponse,
    InvoiceStatusReportResponse,
    OutstandingInvoicesResponse,
    RevenueSummaryResponse,
    SmsUsageResponse,
    StorageUsageResponse,
    TopServicesResponse,
)
from app.modules.reports.service import (
    get_carjam_usage,
    get_customer_statement,
    get_fleet_report,
    get_gst_return,
    get_invoice_status_report,
    get_outstanding_invoices,
    get_revenue_summary,
    get_sms_usage,
    get_storage_usage,
    get_top_services,
    resolve_date_range,
)

router = APIRouter()


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
    db: AsyncSession = Depends(get_db_session),
):
    """Revenue summary for the organisation.

    Requirements: 45.1, 45.2, 45.3
    """
    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    period_start, period_end = resolve_date_range(
        preset.value if preset else None,
        _parse_date(start_date),
        _parse_date(end_date),
    )
    data = await get_revenue_summary(db, org_id, period_start, period_end)
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
    db: AsyncSession = Depends(get_db_session),
):
    """Outstanding invoices report with one-click reminder button.

    Requirements: 45.1, 45.5
    """
    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    data = await get_outstanding_invoices(db, org_id)
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
    db: AsyncSession = Depends(get_db_session),
):
    """GST return summary formatted for IRD filing.

    Requirements: 45.6
    """
    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    period_start, period_end = resolve_date_range(
        preset.value if preset else None,
        _parse_date(start_date),
        _parse_date(end_date),
    )
    data = await get_gst_return(db, org_id, period_start, period_end)
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
    db: AsyncSession = Depends(get_db_session),
):
    """Printable/emailable customer statement.

    Requirements: 45.7
    """
    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    period_start, period_end = resolve_date_range(
        preset.value if preset else None,
        _parse_date(start_date),
        _parse_date(end_date),
    )
    data = await get_customer_statement(db, org_id, customer_id, period_start, period_end)
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
):
    """Carjam API usage for the organisation.

    Requirements: 45.1
    """
    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    data = await get_carjam_usage(db, org_id)
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
):
    """SMS usage for the organisation.

    Returns total sent, included quota, package credits, overage count,
    overage charge, per-SMS cost, and reset timestamp.

    Requirements: 7.1
    """
    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    data = await get_sms_usage(db, org_id)
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
