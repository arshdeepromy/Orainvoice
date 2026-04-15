"""Time Tracking router — timer start/stop, add as labour, employee hours report.

Requirements: 65.1, 65.2, 65.3
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.time_tracking.schemas import (
    AddTimeAsLabourRequest,
    AddTimeAsLabourResponse,
    EmployeeHoursEntry,
    EmployeeHoursReportResponse,
    TimeEntryResponse,
    TimerStartRequest,
    TimerStartResponse,
    TimerStopRequest,
    TimerStopResponse,
)
from app.modules.time_tracking.service import (
    add_time_as_labour_line_item,
    get_employee_hours_report,
    get_time_entries,
    start_timer,
    stop_timer,
)

router = APIRouter()


def _extract_org_context(
    request: Request,
) -> tuple[uuid.UUID | None, uuid.UUID | None, str | None]:
    """Extract org_id, user_id, and ip_address from request."""
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    ip_address = getattr(request.state, "client_ip", None)
    try:
        org_uuid = uuid.UUID(org_id) if org_id else None
        user_uuid = uuid.UUID(user_id) if user_id else None
    except (ValueError, TypeError):
        return None, None, ip_address
    return org_uuid, user_uuid, ip_address


# ---------------------------------------------------------------------------
# Timer start / stop — mounted under /api/v1/job-cards/{id}/timer
# These are registered on the job_cards router prefix via main.py
# ---------------------------------------------------------------------------


@router.post(
    "/{job_card_id}/timer/start",
    response_model=TimerStartResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error or active timer exists"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Job card not found"},
    },
    summary="Start time tracking on a job card",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def start_timer_endpoint(
    job_card_id: uuid.UUID,
    request: Request,
    payload: TimerStartRequest | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Start a timer for the current user on a job card.

    Only one active timer per user per job card is allowed.

    Requirements: 65.1
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    notes = payload.notes if payload else None

    try:
        result = await start_timer(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            job_card_id=job_card_id,
            notes=notes,
            ip_address=ip_address,
        )
    except ValueError as exc:
        error_msg = str(exc)
        status_code = 404 if "not found" in error_msg.lower() else 400
        return JSONResponse(status_code=status_code, content={"detail": error_msg})

    return TimerStartResponse(
        time_entry=TimeEntryResponse(**result),
        message="Timer started",
    )


@router.post(
    "/{job_card_id}/timer/stop",
    response_model=TimerStopResponse,
    responses={
        400: {"description": "No active timer found"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Stop time tracking on a job card",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def stop_timer_endpoint(
    job_card_id: uuid.UUID,
    request: Request,
    payload: TimerStopRequest | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Stop the active timer for the current user on a job card.

    Calculates total duration and stores it on the time entry.

    Requirements: 65.1
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    notes = payload.notes if payload else None

    try:
        result = await stop_timer(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            job_card_id=job_card_id,
            notes=notes,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return TimerStopResponse(
        time_entry=TimeEntryResponse(**result),
        message="Timer stopped",
    )


# ---------------------------------------------------------------------------
# Time entries list for a job card
# ---------------------------------------------------------------------------


@router.get(
    "/{job_card_id}/time-entries",
    response_model=list[TimeEntryResponse],
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="List time entries for a job card",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_time_entries_endpoint(
    job_card_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """List all time entries for a job card.

    Requirements: 65.1
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    entries = await get_time_entries(db, org_id=org_uuid, job_card_id=job_card_id)
    return [TimeEntryResponse(**e) for e in entries]


# ---------------------------------------------------------------------------
# Add time entry as labour line item
# ---------------------------------------------------------------------------


@router.post(
    "/{job_card_id}/time-entries/add-as-labour",
    response_model=AddTimeAsLabourResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Add a time entry as a Labour line item on the job card",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def add_time_as_labour_endpoint(
    job_card_id: uuid.UUID,
    payload: AddTimeAsLabourRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Convert a completed time entry into a Labour line item.

    Requirements: 65.2
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await add_time_as_labour_line_item(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            job_card_id=job_card_id,
            time_entry_id=payload.time_entry_id,
            labour_rate_id=payload.labour_rate_id,
            hourly_rate_override=payload.hourly_rate_override,
            description=payload.description,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return AddTimeAsLabourResponse(message="Time added as labour line item", **result)


# ---------------------------------------------------------------------------
# Employee hours report — Org_Admin only
# ---------------------------------------------------------------------------


@router.get(
    "/reports/employee-hours",
    response_model=EmployeeHoursReportResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
    },
    summary="Employee hours report",
    dependencies=[require_role("org_admin")],
)
async def employee_hours_report_endpoint(
    request: Request,
    start_date: datetime = Query(..., description="Start of date range (ISO 8601)"),
    end_date: datetime = Query(..., description="End of date range (ISO 8601)"),
    db: AsyncSession = Depends(get_db_session),
):
    """Total hours worked per employee in a date range.

    Org_Admin only.

    Requirements: 65.3
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await get_employee_hours_report(
        db,
        org_id=org_uuid,
        start_date=start_date,
        end_date=end_date,
    )

    return EmployeeHoursReportResponse(
        entries=[EmployeeHoursEntry(**e) for e in result["entries"]],
        start_date=result["start_date"],
        end_date=result["end_date"],
        total_hours=result["total_hours"],
    )
