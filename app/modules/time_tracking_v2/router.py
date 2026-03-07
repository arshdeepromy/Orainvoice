"""Time tracking API router.

Endpoints:
- GET    /api/v2/time-entries                  — list time entries
- POST   /api/v2/time-entries                  — create time entry
- GET    /api/v2/time-entries/{id}             — get time entry
- PUT    /api/v2/time-entries/{id}             — update time entry
- POST   /api/v2/time-entries/timer/start      — start timer
- POST   /api/v2/time-entries/timer/stop       — stop timer
- GET    /api/v2/time-entries/timer/active      — get active timer
- GET    /api/v2/time-entries/timesheet         — weekly timesheet
- POST   /api/v2/time-entries/add-to-invoice   — add entries to invoice

**Validates: Requirement 13**
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.time_tracking_v2.schemas import (
    AddToInvoiceRequest,
    AddToInvoiceResponse,
    TimeEntryCreate,
    TimeEntryListResponse,
    TimeEntryResponse,
    TimeEntryUpdate,
    TimerStartRequest,
    TimerStopResponse,
    TimesheetDay,
    TimesheetResponse,
)
from app.modules.time_tracking_v2.service import (
    AlreadyInvoicedError,
    OverlapError,
    TimeTrackingService,
)

router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


def _get_user_id(request: Request) -> UUID:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return UUID(str(user_id))


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.get("", response_model=TimeEntryListResponse, summary="List time entries")
async def list_entries(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user_id: UUID | None = Query(None),
    job_id: UUID | None = Query(None),
    project_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TimeTrackingService(db)
    entries, total = await svc.list_entries(
        org_id, user_id=user_id, job_id=job_id, project_id=project_id,
        page=page, page_size=page_size,
    )
    return TimeEntryListResponse(
        entries=[TimeEntryResponse.model_validate(e) for e in entries],
        total=total, page=page, page_size=page_size,
    )


@router.post("", response_model=TimeEntryResponse, status_code=201, summary="Create time entry")
async def create_entry(
    payload: TimeEntryCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    svc = TimeTrackingService(db)
    try:
        entry = await svc.create_entry(
            org_id, user_id,
            start_time=payload.start_time,
            end_time=payload.end_time,
            duration_minutes=payload.duration_minutes,
            job_id=payload.job_id,
            project_id=payload.project_id,
            staff_id=payload.staff_id,
            description=payload.description,
            is_billable=payload.is_billable,
            hourly_rate=payload.hourly_rate,
        )
    except OverlapError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return TimeEntryResponse.model_validate(entry)


@router.get("/timer/active", response_model=TimeEntryResponse | None, summary="Get active timer")
async def get_active_timer(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    svc = TimeTrackingService(db)
    entry = await svc.get_active_timer(org_id, user_id)
    if entry is None:
        return None
    return TimeEntryResponse.model_validate(entry)


@router.get("/timesheet", response_model=TimesheetResponse, summary="Weekly timesheet")
async def get_timesheet(
    request: Request,
    week_start: date = Query(..., description="Monday of the week (YYYY-MM-DD)"),
    user_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    target_user = user_id or _get_user_id(request)
    svc = TimeTrackingService(db)
    data = await svc.get_timesheet(org_id, target_user, week_start)
    return TimesheetResponse(
        week_start=data["week_start"],
        week_end=data["week_end"],
        days=[
            TimesheetDay(
                date=d["date"],
                entries=[TimeEntryResponse.model_validate(e) for e in d["entries"]],
                total_minutes=d["total_minutes"],
                billable_minutes=d["billable_minutes"],
            )
            for d in data["days"]
        ],
        weekly_total_minutes=data["weekly_total_minutes"],
        weekly_billable_minutes=data["weekly_billable_minutes"],
    )


@router.get("/{entry_id}", response_model=TimeEntryResponse, summary="Get time entry")
async def get_entry(
    entry_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TimeTrackingService(db)
    entry = await svc.get_entry(org_id, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Time entry not found")
    return TimeEntryResponse.model_validate(entry)


@router.put("/{entry_id}", response_model=TimeEntryResponse, summary="Update time entry")
async def update_entry(
    entry_id: UUID,
    payload: TimeEntryUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TimeTrackingService(db)
    try:
        entry = await svc.update_entry(
            org_id, entry_id,
            **payload.model_dump(exclude_unset=True),
        )
    except OverlapError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if entry is None:
        raise HTTPException(status_code=404, detail="Time entry not found")
    return TimeEntryResponse.model_validate(entry)


# ---------------------------------------------------------------------------
# Timer
# ---------------------------------------------------------------------------

@router.post("/timer/start", response_model=TimeEntryResponse, status_code=201, summary="Start timer")
async def start_timer(
    payload: TimerStartRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    svc = TimeTrackingService(db)
    try:
        entry = await svc.start_timer(
            org_id, user_id,
            job_id=payload.job_id,
            project_id=payload.project_id,
            staff_id=payload.staff_id,
            description=payload.description,
            is_billable=payload.is_billable,
            hourly_rate=payload.hourly_rate,
        )
    except OverlapError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return TimeEntryResponse.model_validate(entry)


@router.post("/timer/stop", response_model=TimerStopResponse, summary="Stop timer")
async def stop_timer(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    svc = TimeTrackingService(db)
    try:
        entry = await svc.stop_timer(org_id, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return TimerStopResponse(
        entry=TimeEntryResponse.model_validate(entry),
        duration_minutes=entry.duration_minutes or 0,
    )


# ---------------------------------------------------------------------------
# Add to invoice
# ---------------------------------------------------------------------------

@router.post("/add-to-invoice", response_model=AddToInvoiceResponse, summary="Add time entries to invoice")
async def add_to_invoice(
    payload: AddToInvoiceRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TimeTrackingService(db)
    try:
        result = await svc.add_to_invoice(
            org_id, payload.time_entry_ids, payload.invoice_id,
        )
    except AlreadyInvoicedError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return AddToInvoiceResponse(
        invoice_id=result["invoice_id"],
        line_items_created=result["line_items_created"],
        total_hours=result["total_hours"],
        total_amount=result["total_amount"],
        entries_marked=result["entries_marked"],
    )
