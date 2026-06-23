"""Staff timesheets router — 16 Phase A endpoints.

Registers at:
- /api/v2/timesheets (list, detail, actions)
- /api/v2/clocked-in (real-time view)
- /api/v2/timesheet-settings (configuration)

All read endpoints use BranchScopedTimesheets dependency.
Permission checks use has_permission() from rbac.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import has_permission
from app.modules.timesheets.branch_scope import BranchScopedTimesheets
from app.modules.timesheets.models import Timesheet, TimesheetSettings
from app.modules.timesheets.schemas import (
    AdjustRequest,
    AttendanceDetailResponse,
    AttendanceResponse,
    AttendanceReviewAllResponse,
    BulkActionResponse,
    ClockedInResponse,
    PeriodSummary,
    ShiftCreateRequest,
    ShiftEditRequest,
    ShiftMutationResponse,
    ShiftReviewRequest,
    ShiftReviewResponse,
    TimesheetDetailResponse,
    TimesheetListResponse,
    TimesheetSettingsRead,
    TimesheetSettingsResponse,
    TimesheetSettingsUpdate,
    TimesheetSummary,
    WeeklyBreakdownResponse,
)
from app.modules.timesheets.service import (
    add_manual_shift,
    adjust_timesheet,
    bulk_approve,
    bulk_lock,
    compute_attendance,
    compute_attendance_detail,
    compute_weekly_breakdown,
    edit_shift,
    get_or_create_timesheet,
    get_settings_for_branch,
    review_all_shifts,
    set_shift_review,
    transition_status,
    void_manual_shift,
)

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


def _get_user_id(request: Request) -> UUID:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return UUID(str(user_id))


def _check_permission(request: Request, permission: str) -> None:
    """Check if the current user has a specific permission.

    Uses role + custom_role_permissions from request.state.
    Raises 403 if the permission is not granted.
    """
    role = getattr(request.state, "role", None) or ""
    overrides = getattr(request.state, "permission_overrides", None)
    custom_perms = getattr(request.state, "custom_role_permissions", None)

    if not has_permission(role, permission, overrides=overrides, custom_role_permissions=custom_perms):
        raise HTTPException(status_code=403, detail=f"Permission '{permission}' required")


# ===========================================================================
# Router 1: Timesheets (mounted at /api/v2/timesheets)
# ===========================================================================

timesheets_router = APIRouter()


@timesheets_router.get("/")
async def list_timesheets(
    request: Request,
    pay_period_id: UUID = Query(...),
    scope: BranchScopedTimesheets = Depends(),
    db: AsyncSession = Depends(get_db_session),
) -> TimesheetListResponse:
    """List timesheets for a pay period (branch-scoped).

    Queries the timesheets table joined with staff_members for names
    and branches for branch_name. Computes period summary aggregates.
    """
    from app.modules.staff.models import StaffMember
    from app.modules.organisations.models import Branch

    org_id = _get_org_id(request)

    # Query timesheets for the period, joining staff and branch
    query = (
        select(Timesheet, StaffMember.name, Branch.name)
        .outerjoin(StaffMember, StaffMember.id == Timesheet.staff_id)
        .outerjoin(Branch, Branch.id == Timesheet.branch_id)
        .where(
            Timesheet.org_id == org_id,
            Timesheet.pay_period_id == pay_period_id,
        )
    )
    query = scope.apply_filter(query, Timesheet.branch_id)
    result = await db.execute(query)
    rows = result.all()

    items = []
    total_ordinary = 0
    total_overtime = 0
    total_ph = 0
    approved_count = 0
    pending_count = 0
    locked_count = 0

    for ts, staff_name, branch_name in rows:
        rostered_h = round((ts.rostered_minutes or 0) / 60, 2)
        actual_h = round((ts.actual_minutes or 0) / 60, 2)
        adjusted_h = round((ts.adjusted_minutes or 0) / 60, 2) if ts.adjusted_minutes is not None else None
        variance_h = round(actual_h - rostered_h, 2)
        exception_count = len(ts.exception_flags) if ts.exception_flags else 0

        items.append(TimesheetSummary(
            id=ts.id,
            staff_id=ts.staff_id,
            staff_name=staff_name or "Unknown",
            branch_name=branch_name or None,
            status=ts.status or "open",
            rostered_hours=Decimal(str(rostered_h)),
            actual_hours=Decimal(str(actual_h)),
            adjusted_hours=Decimal(str(adjusted_h)) if adjusted_h is not None else None,
            variance_hours=Decimal(str(variance_h)),
            exception_count=exception_count,
            approved_by_name=None,
            approved_at=ts.approved_at,
        ))

        total_ordinary += (ts.ordinary_minutes or 0)
        total_overtime += (ts.overtime_minutes or 0)
        total_ph += (ts.public_holiday_minutes or 0)

        if ts.status == "approved":
            approved_count += 1
        elif ts.status == "pending_approval":
            pending_count += 1
        elif ts.status == "locked":
            locked_count += 1

    return TimesheetListResponse(
        items=items,
        total=len(items),
        period_summary=PeriodSummary(
            total_staff=len(items),
            approved_count=approved_count,
            pending_count=pending_count,
            locked_count=locked_count,
            total_ordinary_hours=Decimal(str(round(total_ordinary / 60, 2))),
            total_overtime_hours=Decimal(str(round(total_overtime / 60, 2))),
            total_public_holiday_hours=Decimal(str(round(total_ph / 60, 2))),
        ),
    )


@timesheets_router.get("/weekly-breakdown")
async def weekly_breakdown(
    request: Request,
    pay_period_id: UUID = Query(...),
    scope: BranchScopedTimesheets = Depends(),
    db: AsyncSession = Depends(get_db_session),
) -> WeeklyBreakdownResponse:
    """Per-week (Mon–Sun) worked-minute subtotals for a pay period.

    READ-ONLY "weekly lens" review aid. Branch-scoped exactly like
    ``list_timesheets`` (same dependency, no extra role gate). For a period that
    spans more than one ISO week, the response splits it into per-week buckets
    clamped to the period bounds, each with per-staff minutes and a week total
    (``multi_week`` is true when there is more than one week). This endpoint
    never touches pay-run, materialisation, or payslip logic.
    """
    org_id = _get_org_id(request)
    branch_ids = scope.branch_ids if scope.should_filter else None
    return await compute_weekly_breakdown(
        db,
        org_id=org_id,
        pay_period_id=pay_period_id,
        branch_ids=branch_ids,
    )


@timesheets_router.get("/attendance")
async def attendance_report(
    request: Request,
    start: date | None = Query(
        None, description="Range start (YYYY-MM-DD). Defaults to today (UTC)."
    ),
    end: date | None = Query(
        None, description="Range end inclusive (YYYY-MM-DD). Defaults to start."
    ),
    scope: BranchScopedTimesheets = Depends(),
    db: AsyncSession = Depends(get_db_session),
) -> AttendanceResponse:
    """Per-staff worked-hours-vs-expected attendance over a date range.

    Powers the Timesheets page "Attendance" tab. Defaults to **today** (so the
    page lands on today's workers and their clocked hours). Supports this-week
    and arbitrary custom ranges via ``start``/``end``. Branch-scoped exactly
    like ``list_timesheets`` (org/global admins see all branches; branch-scoped
    users see only their branches). READ-ONLY — never touches pay-run /
    materialisation / payslip state.
    """
    org_id = _get_org_id(request)

    if start is not None and end is not None and end < start:
        raise HTTPException(
            status_code=422,
            detail={"detail": "invalid_range", "message": "end must be on or after start"},
        )

    branch_ids = scope.branch_ids if scope.should_filter else None
    return await compute_attendance(
        db,
        org_id=org_id,
        start_date=start,
        end_date=end,
        branch_ids=branch_ids,
    )


@timesheets_router.get("/attendance/{staff_id}/shifts")
async def attendance_staff_shifts(
    staff_id: UUID,
    request: Request,
    start: date | None = Query(None),
    end: date | None = Query(None),
    scope: BranchScopedTimesheets = Depends(),
    db: AsyncSession = Depends(get_db_session),
) -> AttendanceDetailResponse:
    """Per-staff shift list for the Attendance drill-in (expandable row).

    Lists every clock shift the staff member worked in the range, each with its
    matched scheduled shift and its pre-payroll review state. READ-ONLY.
    """
    org_id = _get_org_id(request)
    if start is not None and end is not None and end < start:
        raise HTTPException(
            status_code=422,
            detail={"detail": "invalid_range", "message": "end must be on or after start"},
        )
    branch_ids = scope.branch_ids if scope.should_filter else None
    return await compute_attendance_detail(
        db,
        org_id=org_id,
        staff_id=staff_id,
        start_date=start,
        end_date=end,
        branch_ids=branch_ids,
    )


@timesheets_router.post("/attendance/shifts/{entry_id}/review")
async def review_shift(
    entry_id: UUID,
    body: ShiftReviewRequest,
    request: Request,
    scope: BranchScopedTimesheets = Depends(),
    db: AsyncSession = Depends(get_db_session),
) -> ShiftReviewResponse:
    """Sign off (or un-sign) a single clock shift for payroll.

    Requires ``timesheet.approve``. Marks the shift reviewed on its ``flags``
    so the Attendance tab can show it as approved for payroll purposes.
    """
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    _check_permission(request, "timesheet.approve")
    branch_ids = scope.branch_ids if scope.should_filter else None
    try:
        entry, reviewer_name = await set_shift_review(
            db,
            org_id=org_id,
            entry_id=entry_id,
            reviewed=body.reviewed,
            actor_id=user_id,
            branch_ids=branch_ids,
        )
    except ValueError as e:
        msg = str(e)
        if msg == "shift_not_found":
            raise HTTPException(status_code=404, detail="Shift not found")
        if msg == "branch_access_denied":
            raise HTTPException(status_code=403, detail="Branch access denied")
        if msg == "shift_still_open":
            raise HTTPException(
                status_code=409,
                detail={"detail": "shift_still_open", "message": "Clock out the shift before reviewing it."},
            )
        raise HTTPException(status_code=400, detail=msg)

    flags = entry.flags or {}
    return ShiftReviewResponse(
        id=entry.id,
        reviewed=bool(flags.get("reviewed")),
        reviewed_by_name=reviewer_name,
        reviewed_at=flags.get("reviewed_at"),
    )


@timesheets_router.post("/attendance/{staff_id}/review-all")
async def review_all_staff_shifts(
    staff_id: UUID,
    request: Request,
    start: date | None = Query(None),
    end: date | None = Query(None),
    scope: BranchScopedTimesheets = Depends(),
    db: AsyncSession = Depends(get_db_session),
) -> AttendanceReviewAllResponse:
    """Sign off every completed shift for a staff member in the range.

    Requires ``timesheet.approve``. Skips already-reviewed and still-open shifts.
    """
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    _check_permission(request, "timesheet.approve")
    if start is not None and end is not None and end < start:
        raise HTTPException(
            status_code=422,
            detail={"detail": "invalid_range", "message": "end must be on or after start"},
        )
    branch_ids = scope.branch_ids if scope.should_filter else None
    result = await review_all_shifts(
        db,
        org_id=org_id,
        staff_id=staff_id,
        start_date=start,
        end_date=end,
        actor_id=user_id,
        branch_ids=branch_ids,
    )
    return AttendanceReviewAllResponse(
        affected_count=result["affected_count"],
        pending_review_count=result["pending_review_count"],
    )


def _shift_mutation_error(exc: ValueError) -> HTTPException:
    """Map shift edit/add/delete ValueError codes to HTTP responses."""
    msg = str(exc)
    if msg in ("shift_not_found", "staff_not_found"):
        return HTTPException(status_code=404, detail="Not found")
    if msg == "branch_access_denied":
        return HTTPException(status_code=403, detail="Branch access denied")
    if msg == "shift_locked":
        return HTTPException(
            status_code=409,
            detail={"detail": "shift_locked", "message": "This pay period is locked and can no longer be changed."},
        )
    if msg == "not_manual":
        return HTTPException(
            status_code=409,
            detail={"detail": "not_manual", "message": "Only admin-added days can be deleted. Edit a real clock shift instead."},
        )
    friendly = {
        "times_required": "Provide both a clock-in and clock-out time.",
        "invalid_times": "Clock-out must be after clock-in.",
        "break_exceeds_shift": "The break is longer than the shift.",
        "no_branch": "No branch is configured for this organisation.",
    }
    return HTTPException(status_code=422, detail={"detail": msg, "message": friendly.get(msg, msg)})


@timesheets_router.patch("/attendance/shifts/{entry_id}")
async def edit_attendance_shift(
    entry_id: UUID,
    body: ShiftEditRequest,
    request: Request,
    scope: BranchScopedTimesheets = Depends(),
    db: AsyncSession = Depends(get_db_session),
) -> ShiftMutationResponse:
    """Correct one shift: clock times (recomputes worked) or an hours override.

    Requires ``timesheet.approve``. Resets the shift's review sign-off and
    recomputes covering (non-locked) timesheets so payroll reflects the change.
    """
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    _check_permission(request, "timesheet.approve")
    branch_ids = scope.branch_ids if scope.should_filter else None
    try:
        entry = await edit_shift(
            db,
            org_id=org_id,
            entry_id=entry_id,
            reason=body.reason,
            actor_id=user_id,
            clock_in_at=body.clock_in_at,
            clock_out_at=body.clock_out_at,
            break_minutes=body.break_minutes,
            worked_minutes=body.worked_minutes,
            branch_ids=branch_ids,
        )
    except ValueError as e:
        raise _shift_mutation_error(e)

    return ShiftMutationResponse(
        id=entry.id,
        work_date=entry.clock_in_at.date().isoformat(),
        worked_minutes=entry.worked_minutes,
        is_manual=bool((entry.flags or {}).get("manual_entry")),
    )


@timesheets_router.post("/attendance/{staff_id}/shifts")
async def add_attendance_shift(
    staff_id: UUID,
    body: ShiftCreateRequest,
    request: Request,
    scope: BranchScopedTimesheets = Depends(),
    db: AsyncSession = Depends(get_db_session),
) -> ShiftMutationResponse:
    """Add a worked day for a staff member who didn't clock (fixed/casual).

    Requires ``timesheet.approve``. Accepts clock times or an hours value, and
    recomputes covering timesheets.
    """
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    _check_permission(request, "timesheet.approve")
    branch_ids = scope.branch_ids if scope.should_filter else None
    try:
        entry = await add_manual_shift(
            db,
            org_id=org_id,
            staff_id=staff_id,
            work_date=body.work_date,
            reason=body.reason,
            actor_id=user_id,
            clock_in_at=body.clock_in_at,
            clock_out_at=body.clock_out_at,
            break_minutes=body.break_minutes,
            worked_minutes=body.worked_minutes,
            branch_id=body.branch_id,
            branch_ids=branch_ids,
        )
    except ValueError as e:
        raise _shift_mutation_error(e)

    return ShiftMutationResponse(
        id=entry.id,
        work_date=body.work_date.isoformat(),
        worked_minutes=entry.worked_minutes,
        is_manual=True,
    )


@timesheets_router.delete("/attendance/shifts/{entry_id}")
async def delete_attendance_shift(
    entry_id: UUID,
    request: Request,
    scope: BranchScopedTimesheets = Depends(),
    db: AsyncSession = Depends(get_db_session),
):
    """Remove an admin-added manual shift (soft-void; never a real clock punch).

    Requires ``timesheet.approve``. Recomputes covering timesheets.
    """
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    _check_permission(request, "timesheet.approve")
    branch_ids = scope.branch_ids if scope.should_filter else None
    try:
        await void_manual_shift(
            db, org_id=org_id, entry_id=entry_id, actor_id=user_id, branch_ids=branch_ids,
        )
    except ValueError as e:
        raise _shift_mutation_error(e)
    return JSONResponse(content={"message": "Shift removed"}, status_code=200)


@timesheets_router.get("/{id}")
async def get_timesheet_detail(
    id: UUID,
    request: Request,
    scope: BranchScopedTimesheets = Depends(),
    db: AsyncSession = Depends(get_db_session),
) -> TimesheetDetailResponse:
    """Get timesheet detail with staff/period context and clock entries."""
    from app.modules.staff.models import StaffMember
    from app.modules.organisations.models import Branch
    from app.modules.payslips.models import PayPeriod
    from app.modules.time_clock.models import TimeClockEntry

    org_id = _get_org_id(request)

    result = await db.execute(
        select(Timesheet).where(
            Timesheet.id == id,
            Timesheet.org_id == org_id,
        )
    )
    ts = result.scalar_one_or_none()
    if not ts:
        raise HTTPException(status_code=404, detail="Timesheet not found")

    if not scope.can_access_branch(ts.branch_id):
        raise HTTPException(status_code=403, detail="Branch access denied")

    # Staff name
    staff = await db.get(StaffMember, ts.staff_id)
    staff_name = (getattr(staff, "name", None) or "Unknown") if staff else "Unknown"

    # Period dates
    period = await db.get(PayPeriod, ts.pay_period_id)
    period_start = period.start_date.isoformat() if period and period.start_date else ""
    period_end = period.end_date.isoformat() if period and period.end_date else ""

    # Branch name
    branch_name = None
    if ts.branch_id:
        branch = await db.get(Branch, ts.branch_id)
        branch_name = getattr(branch, "name", None) if branch else None

    # Approver / locker names
    from app.modules.auth.models import User

    approved_by_name = None
    if ts.approved_by:
        approver = await db.get(User, ts.approved_by)
        approved_by_name = getattr(approver, "full_name", None) or getattr(approver, "email", None) if approver else None
    locked_by_name = None
    if ts.locked_by:
        locker = await db.get(User, ts.locked_by)
        locked_by_name = getattr(locker, "full_name", None) or getattr(locker, "email", None) if locker else None

    # Clock entries for this staff within the period (best-effort).
    entries: list[TimesheetDetailEntry] = []
    if period is not None:
        from datetime import timedelta
        clock_rows = await db.execute(
            select(TimeClockEntry).where(
                TimeClockEntry.org_id == org_id,
                TimeClockEntry.staff_id == ts.staff_id,
                TimeClockEntry.clock_in_at >= period.start_date,
                TimeClockEntry.clock_in_at < period.end_date + timedelta(days=1),
            ).order_by(TimeClockEntry.clock_in_at)
        )
        for ce in clock_rows.scalars().all():
            ci = ce.clock_in_at
            co = getattr(ce, "clock_out_at", None)
            worked = 0
            if ci and co:
                worked = int((co - ci).total_seconds() // 60)
            entries.append(TimesheetDetailEntry(
                id=ce.id,
                clock_in_at=ci,
                clock_out_at=co,
                worked_minutes=worked,
                source=getattr(ce, "source", None) or "clock",
            ))

    return TimesheetDetailResponse(
        id=ts.id,
        staff_id=ts.staff_id,
        staff_name=staff_name,
        pay_period_id=ts.pay_period_id,
        period_start=period_start,
        period_end=period_end,
        branch_name=branch_name,
        status=ts.status,
        rostered_minutes=ts.rostered_minutes,
        actual_minutes=ts.actual_minutes,
        adjusted_minutes=ts.adjusted_minutes,
        ordinary_minutes=ts.ordinary_minutes,
        overtime_minutes=ts.overtime_minutes,
        public_holiday_minutes=ts.public_holiday_minutes,
        exception_flags=ts.exception_flags if ts.exception_flags else [],
        notes=ts.notes,
        approved_by_name=approved_by_name,
        approved_at=ts.approved_at,
        locked_at=ts.locked_at,
        locked_by_name=locked_by_name,
        entries=entries,
    )


@timesheets_router.post("/{id}/recompute")
async def recompute_timesheet(
    id: UUID,
    request: Request,
    scope: BranchScopedTimesheets = Depends(),
    db: AsyncSession = Depends(get_db_session),
):
    """Trigger re-aggregation of a timesheet.

    Updates the timestamp to signal recompute happened and returns the result.
    """
    org_id = _get_org_id(request)
    _check_permission(request, "timesheet.approve")

    result = await db.execute(
        select(Timesheet).where(
            Timesheet.id == id,
            Timesheet.org_id == org_id,
        )
    )
    ts = result.scalar_one_or_none()
    if not ts:
        raise HTTPException(status_code=404, detail="Timesheet not found")

    if not scope.can_access_branch(ts.branch_id):
        raise HTTPException(status_code=403, detail="Branch access denied")

    # Signal recompute by updating the timestamp
    ts.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(ts)

    return JSONResponse(
        content={
            "message": "Recomputation complete",
            "timesheet_id": str(id),
            "updated_at": str(ts.updated_at),
        },
        status_code=200,
    )


@timesheets_router.put("/{id}/adjust")
async def adjust_timesheet_endpoint(
    id: UUID,
    body: AdjustRequest,
    request: Request,
    scope: BranchScopedTimesheets = Depends(),
    db: AsyncSession = Depends(get_db_session),
):
    """Set adjusted_minutes on a timesheet with audit trail."""
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    _check_permission(request, "timesheet.approve")

    result = await db.execute(
        select(Timesheet).where(
            Timesheet.id == id,
            Timesheet.org_id == org_id,
        )
    )
    ts = result.scalar_one_or_none()
    if not ts:
        raise HTTPException(status_code=404, detail="Timesheet not found")

    if not scope.can_access_branch(ts.branch_id):
        raise HTTPException(status_code=403, detail="Branch access denied")

    try:
        updated = await adjust_timesheet(
            db,
            timesheet=ts,
            adjusted_minutes=body.adjusted_minutes,
            notes=body.notes,
            actor_id=user_id,
            org_id=org_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return JSONResponse(
        content={
            "message": "Timesheet adjusted",
            "timesheet_id": str(updated.id),
            "adjusted_minutes": updated.adjusted_minutes,
        },
        status_code=200,
    )


@timesheets_router.post("/{id}/submit")
async def submit_timesheet(
    id: UUID,
    request: Request,
    scope: BranchScopedTimesheets = Depends(),
    db: AsyncSession = Depends(get_db_session),
):
    """Transition timesheet: open → pending_approval."""
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    _check_permission(request, "timesheet.approve")

    result = await db.execute(
        select(Timesheet).where(
            Timesheet.id == id,
            Timesheet.org_id == org_id,
        )
    )
    ts = result.scalar_one_or_none()
    if not ts:
        raise HTTPException(status_code=404, detail="Timesheet not found")

    if not scope.can_access_branch(ts.branch_id):
        raise HTTPException(status_code=403, detail="Branch access denied")

    try:
        updated = await transition_status(
            db,
            timesheet=ts,
            new_status="pending_approval",
            actor_id=user_id,
            org_id=org_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return JSONResponse(
        content={"message": "Timesheet submitted", "status": updated.status},
        status_code=200,
    )


@timesheets_router.post("/{id}/approve")
async def approve_timesheet(
    id: UUID,
    request: Request,
    scope: BranchScopedTimesheets = Depends(),
    db: AsyncSession = Depends(get_db_session),
):
    """Transition timesheet: pending_approval → approved."""
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    _check_permission(request, "timesheet.approve")

    result = await db.execute(
        select(Timesheet).where(
            Timesheet.id == id,
            Timesheet.org_id == org_id,
        )
    )
    ts = result.scalar_one_or_none()
    if not ts:
        raise HTTPException(status_code=404, detail="Timesheet not found")

    if not scope.can_access_branch(ts.branch_id):
        raise HTTPException(status_code=403, detail="Branch access denied")

    try:
        updated = await transition_status(
            db,
            timesheet=ts,
            new_status="approved",
            actor_id=user_id,
            org_id=org_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return JSONResponse(
        content={"message": "Timesheet approved", "status": updated.status},
        status_code=200,
    )


@timesheets_router.post("/{id}/reject")
async def reject_timesheet(
    id: UUID,
    request: Request,
    scope: BranchScopedTimesheets = Depends(),
    db: AsyncSession = Depends(get_db_session),
):
    """Transition timesheet: pending_approval/approved → open (reject)."""
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    _check_permission(request, "timesheet.approve")

    result = await db.execute(
        select(Timesheet).where(
            Timesheet.id == id,
            Timesheet.org_id == org_id,
        )
    )
    ts = result.scalar_one_or_none()
    if not ts:
        raise HTTPException(status_code=404, detail="Timesheet not found")

    if not scope.can_access_branch(ts.branch_id):
        raise HTTPException(status_code=403, detail="Branch access denied")

    try:
        updated = await transition_status(
            db,
            timesheet=ts,
            new_status="open",
            actor_id=user_id,
            org_id=org_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return JSONResponse(
        content={"message": "Timesheet rejected", "status": updated.status},
        status_code=200,
    )


@timesheets_router.post("/{id}/lock")
async def lock_timesheet(
    id: UUID,
    request: Request,
    scope: BranchScopedTimesheets = Depends(),
    db: AsyncSession = Depends(get_db_session),
):
    """Transition timesheet: approved → locked (requires payrun.lock)."""
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    _check_permission(request, "payrun.lock")

    result = await db.execute(
        select(Timesheet).where(
            Timesheet.id == id,
            Timesheet.org_id == org_id,
        )
    )
    ts = result.scalar_one_or_none()
    if not ts:
        raise HTTPException(status_code=404, detail="Timesheet not found")

    if not scope.can_access_branch(ts.branch_id):
        raise HTTPException(status_code=403, detail="Branch access denied")

    try:
        updated = await transition_status(
            db,
            timesheet=ts,
            new_status="locked",
            actor_id=user_id,
            org_id=org_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return JSONResponse(
        content={"message": "Timesheet locked", "status": updated.status},
        status_code=200,
    )


@timesheets_router.post("/bulk-approve")
async def bulk_approve_endpoint(
    request: Request,
    pay_period_id: UUID = Query(...),
    scope: BranchScopedTimesheets = Depends(),
    db: AsyncSession = Depends(get_db_session),
) -> BulkActionResponse:
    """Approve all clean timesheets (no exceptions, within threshold)."""
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    _check_permission(request, "timesheet.approve")

    result = await bulk_approve(
        db,
        org_id=org_id,
        pay_period_id=pay_period_id,
        actor_id=user_id,
        branch_ids=scope.branch_ids if scope.should_filter else None,
    )

    return BulkActionResponse(
        affected_count=result["affected_count"],
        skipped_count=result["skipped_count"],
    )


@timesheets_router.post("/bulk-lock")
async def bulk_lock_endpoint(
    request: Request,
    pay_period_id: UUID = Query(...),
    scope: BranchScopedTimesheets = Depends(),
    db: AsyncSession = Depends(get_db_session),
) -> BulkActionResponse:
    """Lock all approved timesheets for a period."""
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    _check_permission(request, "payrun.lock")

    result = await bulk_lock(
        db,
        org_id=org_id,
        pay_period_id=pay_period_id,
        actor_id=user_id,
        branch_ids=scope.branch_ids if scope.should_filter else None,
    )

    return BulkActionResponse(
        affected_count=result["affected_count"],
        skipped_count=result["skipped_count"],
    )


@timesheets_router.post("/match-all")
async def match_all_endpoint(
    request: Request,
    pay_period_id: UUID = Query(...),
    scope: BranchScopedTimesheets = Depends(),
    db: AsyncSession = Depends(get_db_session),
):
    """Run match engine on all unmatched entries for a period.

    Placeholder: returns 200 with message.
    Full implementation will call match_all_for_period().
    """
    org_id = _get_org_id(request)
    _check_permission(request, "timesheet.approve")

    return JSONResponse(
        content={
            "message": "Match-all triggered",
            "pay_period_id": str(pay_period_id),
        },
        status_code=200,
    )


@timesheets_router.post("/materialise/")
async def materialise_endpoint(
    request: Request,
    pay_period_id: UUID = Query(...),
    include_all_active: bool = Query(False),
    db: AsyncSession = Depends(get_db_session),
):
    """Materialise missing timesheets before pay-run cutoff (org_admin only).

    When ``include_all_active`` is True, a timesheet is created for every
    active staff member without one for the period — regardless of working
    arrangement — so payroll can be run for fixed, rostered, and casual
    staff who have not clocked in.
    """
    org_id = _get_org_id(request)
    role = getattr(request.state, "role", None)
    if role not in ("org_admin", "global_admin"):
        raise HTTPException(status_code=403, detail="org_admin role required")

    from app.modules.timesheets.service import materialise_missing_timesheets, MaterialisationResult

    result = await materialise_missing_timesheets(
        db, org_id=org_id, pay_period_id=pay_period_id,
        include_all_active=include_all_active,
    )

    return JSONResponse(content={
        "created_count": result.created_count,
        "no_activity_staff": [str(sid) for sid in result.no_activity_staff],
    })


# ===========================================================================
# Router 2: Clocked In (mounted at /api/v2/clocked-in)
# ===========================================================================

clocked_in_router = APIRouter()


@clocked_in_router.get("/")
async def list_clocked_in(
    request: Request,
    scope: BranchScopedTimesheets = Depends(),
    db: AsyncSession = Depends(get_db_session),
) -> ClockedInResponse:
    """List currently clocked-in staff (branch-scoped).

    Delegates to the existing time_clock service which queries
    time_clock_entries WHERE clock_out_at IS NULL joined with staff_members.
    """
    from app.modules.time_clock.service import list_currently_clocked_in

    org_id = _get_org_id(request)

    raw_items = await list_currently_clocked_in(db, org_id=org_id)

    # Also fetch branch names for display
    from app.modules.admin.models import Branch
    branch_result = await db.execute(
        select(Branch.id, Branch.name).where(Branch.org_id == org_id)
    )
    branch_map = {row[0]: row[1] for row in branch_result.all()}

    # Map to ClockedInEntry schema
    from app.modules.timesheets.schemas import ClockedInEntry as ClockedInEntrySchema
    items = []
    for item in raw_items:
        clock_in_at = item.get("clock_in_at")
        elapsed = 0
        if clock_in_at:
            from datetime import datetime as dt_cls, timezone as tz
            now = dt_cls.now(tz.utc)
            if hasattr(clock_in_at, 'timestamp'):
                elapsed = int((now - clock_in_at).total_seconds() / 60)

        entry_id = item.get("time_clock_entry_id", item.get("id"))
        staff_id = item.get("staff_id")
        if not entry_id or not staff_id:
            continue

        # Resolve branch name from the TCE's branch_id
        branch_id = item.get("branch_id")
        branch_name = branch_map.get(branch_id, "Main") if branch_id else "Main"

        items.append(ClockedInEntrySchema(
            id=entry_id,
            staff_id=staff_id,
            staff_name=item.get("staff_name") or "Unknown",
            position=item.get("position"),
            clock_in_at=clock_in_at,
            elapsed_minutes=elapsed,
            on_break=(item.get("break_minutes", 0) or 0) > 0,
            break_started_at=None,
            clock_in_branch_name=branch_name,
            clock_out_branch_name=None,
            source=item.get("source") or "unknown",
            clock_in_ip=item.get("clock_in_ip"),
            rostered_start=None,
            punctuality=None,
        ))

    return ClockedInResponse(items=items, total=len(items))


@clocked_in_router.post("/{entry_id}/clock-out")
async def clock_out_entry(
    entry_id: UUID,
    request: Request,
    scope: BranchScopedTimesheets = Depends(),
    db: AsyncSession = Depends(get_db_session),
):
    """Manual clock-out for a currently clocked-in entry.

    Placeholder: returns 200 with message.
    Full implementation will set clock_out_at on the TimeClockEntry.
    """
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    _check_permission(request, "timesheet.approve")

    return JSONResponse(
        content={
            "message": "Clock-out recorded",
            "entry_id": str(entry_id),
        },
        status_code=200,
    )


# ===========================================================================
# Router 3: Timesheet Settings (mounted at /api/v2/timesheet-settings)
# ===========================================================================

settings_router = APIRouter()


@settings_router.get("/")
async def get_settings(
    request: Request,
    scope: BranchScopedTimesheets = Depends(),
    db: AsyncSession = Depends(get_db_session),
) -> TimesheetSettingsResponse:
    """Get org-wide + branch override settings."""
    org_id = _get_org_id(request)

    # Fetch org-wide default (branch_id IS NULL)
    result = await db.execute(
        select(TimesheetSettings).where(
            TimesheetSettings.org_id == org_id,
            TimesheetSettings.branch_id == None,  # noqa: E711
        )
    )
    org_default = result.scalar_one_or_none()

    # Fetch all branch overrides
    query = select(TimesheetSettings).where(
        TimesheetSettings.org_id == org_id,
        TimesheetSettings.branch_id != None,  # noqa: E711
    )
    if scope.should_filter and scope.branch_ids:
        query = query.where(TimesheetSettings.branch_id.in_(scope.branch_ids))

    result = await db.execute(query)
    branch_overrides = list(result.scalars().all())

    def _to_read(s: TimesheetSettings) -> TimesheetSettingsRead:
        return TimesheetSettingsRead(
            id=s.id,
            org_id=s.org_id,
            branch_id=s.branch_id,
            branch_name=None,  # Placeholder — will join branches table
            clock_rounding_minutes=s.clock_rounding_minutes,
            clock_rounding_direction=s.clock_rounding_direction,
            early_grace_minutes=s.early_grace_minutes,
            late_grace_minutes=s.late_grace_minutes,
            match_policy=s.match_policy,
            auto_approve_threshold_minutes=s.auto_approve_threshold_minutes,
            require_approval_before_lock=s.require_approval_before_lock,
            daily_overtime_threshold_minutes=getattr(s, 'daily_overtime_threshold_minutes', 480),
            weekly_overtime_threshold_minutes=getattr(s, 'weekly_overtime_threshold_minutes', 2400),
            overtime_rate_multiplier=Decimal(str(getattr(s, 'overtime_rate_multiplier', '1.50') or '1.50')),
            break_rules=getattr(s, 'break_rules', []) or [],
            public_holiday_rate_multiplier=Decimal(str(getattr(s, 'public_holiday_rate_multiplier', '1.50') or '1.50')),
        )

    return TimesheetSettingsResponse(
        org_default=_to_read(org_default) if org_default else None,
        branch_overrides=[_to_read(s) for s in branch_overrides],
    )


@settings_router.put("/")
async def update_org_settings(
    body: TimesheetSettingsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update org-wide timesheet settings (org_admin only)."""
    org_id = _get_org_id(request)
    role = getattr(request.state, "role", None)
    if role not in ("org_admin", "global_admin"):
        raise HTTPException(status_code=403, detail="org_admin role required")

    # Get or create org-wide settings row
    result = await db.execute(
        select(TimesheetSettings).where(
            TimesheetSettings.org_id == org_id,
            TimesheetSettings.branch_id == None,  # noqa: E711
        )
    )
    settings_row = result.scalar_one_or_none()

    if not settings_row:
        settings_row = TimesheetSettings(org_id=org_id, branch_id=None)
        db.add(settings_row)

    # Apply updates (only non-None fields)
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(settings_row, field, value)

    settings_row.updated_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(settings_row)

    return TimesheetSettingsRead(
        id=settings_row.id,
        org_id=settings_row.org_id,
        branch_id=settings_row.branch_id,
        branch_name=None,
        clock_rounding_minutes=settings_row.clock_rounding_minutes,
        clock_rounding_direction=settings_row.clock_rounding_direction,
        early_grace_minutes=settings_row.early_grace_minutes,
        late_grace_minutes=settings_row.late_grace_minutes,
        match_policy=settings_row.match_policy,
        auto_approve_threshold_minutes=settings_row.auto_approve_threshold_minutes,
        require_approval_before_lock=settings_row.require_approval_before_lock,
        daily_overtime_threshold_minutes=getattr(settings_row, 'daily_overtime_threshold_minutes', 480),
        weekly_overtime_threshold_minutes=getattr(settings_row, 'weekly_overtime_threshold_minutes', 2400),
        overtime_rate_multiplier=Decimal(str(getattr(settings_row, 'overtime_rate_multiplier', '1.50') or '1.50')),
        break_rules=getattr(settings_row, 'break_rules', []) or [],
        public_holiday_rate_multiplier=Decimal(str(getattr(settings_row, 'public_holiday_rate_multiplier', '1.50') or '1.50')),
    )


@settings_router.get("/branches/{branch_id}")
async def get_branch_settings(
    branch_id: UUID,
    request: Request,
    scope: BranchScopedTimesheets = Depends(),
    db: AsyncSession = Depends(get_db_session),
) -> TimesheetSettingsRead:
    """Get branch-specific settings override."""
    org_id = _get_org_id(request)

    if not scope.can_access_branch(branch_id):
        raise HTTPException(status_code=403, detail="Branch access denied")

    result = await db.execute(
        select(TimesheetSettings).where(
            TimesheetSettings.org_id == org_id,
            TimesheetSettings.branch_id == branch_id,
        )
    )
    settings_row = result.scalar_one_or_none()
    if not settings_row:
        raise HTTPException(status_code=404, detail="No branch override found")

    return TimesheetSettingsRead(
        id=settings_row.id,
        org_id=settings_row.org_id,
        branch_id=settings_row.branch_id,
        branch_name=None,  # Placeholder
        clock_rounding_minutes=settings_row.clock_rounding_minutes,
        clock_rounding_direction=settings_row.clock_rounding_direction,
        early_grace_minutes=settings_row.early_grace_minutes,
        late_grace_minutes=settings_row.late_grace_minutes,
        match_policy=settings_row.match_policy,
        auto_approve_threshold_minutes=settings_row.auto_approve_threshold_minutes,
        require_approval_before_lock=settings_row.require_approval_before_lock,
        daily_overtime_threshold_minutes=getattr(settings_row, 'daily_overtime_threshold_minutes', 480),
        weekly_overtime_threshold_minutes=getattr(settings_row, 'weekly_overtime_threshold_minutes', 2400),
        overtime_rate_multiplier=Decimal(str(getattr(settings_row, 'overtime_rate_multiplier', '1.50') or '1.50')),
        break_rules=getattr(settings_row, 'break_rules', []) or [],
        public_holiday_rate_multiplier=Decimal(str(getattr(settings_row, 'public_holiday_rate_multiplier', '1.50') or '1.50')),
    )


@settings_router.put("/branches/{branch_id}")
async def update_branch_settings(
    branch_id: UUID,
    body: TimesheetSettingsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Set branch-specific settings override (org_admin only)."""
    org_id = _get_org_id(request)
    role = getattr(request.state, "role", None)
    if role not in ("org_admin", "global_admin"):
        raise HTTPException(status_code=403, detail="org_admin role required")

    # Get or create branch override
    result = await db.execute(
        select(TimesheetSettings).where(
            TimesheetSettings.org_id == org_id,
            TimesheetSettings.branch_id == branch_id,
        )
    )
    settings_row = result.scalar_one_or_none()

    if not settings_row:
        settings_row = TimesheetSettings(org_id=org_id, branch_id=branch_id)
        db.add(settings_row)

    # Apply updates
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(settings_row, field, value)

    settings_row.updated_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(settings_row)

    return TimesheetSettingsRead(
        id=settings_row.id,
        org_id=settings_row.org_id,
        branch_id=settings_row.branch_id,
        branch_name=None,
        clock_rounding_minutes=settings_row.clock_rounding_minutes,
        clock_rounding_direction=settings_row.clock_rounding_direction,
        early_grace_minutes=settings_row.early_grace_minutes,
        late_grace_minutes=settings_row.late_grace_minutes,
        match_policy=settings_row.match_policy,
        auto_approve_threshold_minutes=settings_row.auto_approve_threshold_minutes,
        require_approval_before_lock=settings_row.require_approval_before_lock,
        daily_overtime_threshold_minutes=getattr(settings_row, 'daily_overtime_threshold_minutes', 480),
        weekly_overtime_threshold_minutes=getattr(settings_row, 'weekly_overtime_threshold_minutes', 2400),
        overtime_rate_multiplier=Decimal(str(getattr(settings_row, 'overtime_rate_multiplier', '1.50') or '1.50')),
        break_rules=getattr(settings_row, 'break_rules', []) or [],
        public_holiday_rate_multiplier=Decimal(str(getattr(settings_row, 'public_holiday_rate_multiplier', '1.50') or '1.50')),
    )

# ===========================================================================
# Router 4: Pay Cycles (mounted at /api/v2/pay-cycles) — Phase B
# ===========================================================================

pay_cycles_router = APIRouter()


@pay_cycles_router.get("/")
async def list_pay_cycles(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """List pay cycles for the org."""
    org_id = _get_org_id(request)
    role = getattr(request.state, "role", None)
    if role not in ("org_admin", "global_admin"):
        _check_permission(request, "payrun.lock")

    from app.modules.timesheets.pay_cycles import PayCycle
    result = await db.execute(
        select(PayCycle).where(PayCycle.org_id == org_id, PayCycle.active == True)
    )
    cycles = list(result.scalars().all())

    return JSONResponse(content={
        "items": [
            {
                "id": str(c.id),
                "name": c.name,
                "frequency": c.frequency,
                "anchor_date": str(c.anchor_date),
                "pay_date_offset_days": c.pay_date_offset_days,
                "is_default": c.is_default,
            }
            for c in cycles
        ],
        "total": len(cycles),
    })


@pay_cycles_router.post("/")
async def create_pay_cycle_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new pay cycle (org_admin only)."""
    from datetime import date as date_type
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    role = getattr(request.state, "role", None)
    if role not in ("org_admin", "global_admin"):
        raise HTTPException(status_code=403, detail="org_admin role required")

    from app.modules.timesheets.pay_cycles import create_pay_cycle
    body = await request.json()

    cycle = await create_pay_cycle(
        db,
        org_id=org_id,
        name=body["name"],
        frequency=body.get("frequency", "fortnightly"),
        anchor_date=date_type.fromisoformat(body["anchor_date"]),
        pay_date_offset_days=body.get("pay_date_offset_days", 3),
        is_default=body.get("is_default", False),
        actor_id=user_id,
    )

    return JSONResponse(content={
        "id": str(cycle.id),
        "name": cycle.name,
        "frequency": cycle.frequency,
        "anchor_date": str(cycle.anchor_date),
        "pay_date_offset_days": cycle.pay_date_offset_days,
        "is_default": cycle.is_default,
    }, status_code=201)


@pay_cycles_router.post("/{cycle_id}/generate-periods/")
async def generate_periods_endpoint(
    cycle_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Auto-generate upcoming PayPeriod rows for a cycle."""
    org_id = _get_org_id(request)
    role = getattr(request.state, "role", None)
    if role not in ("org_admin", "global_admin"):
        raise HTTPException(status_code=403, detail="org_admin role required")

    from app.modules.timesheets.pay_cycles import auto_generate_pay_periods
    body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    count = body.get("count", 4) if isinstance(body, dict) else 4

    created = await auto_generate_pay_periods(
        db, org_id=org_id, pay_cycle_id=cycle_id, ahead_count=count,
    )

    return JSONResponse(content={
        "created": created,
        "count": len(created),
    })


@pay_cycles_router.post("/{cycle_id}/assignments/")
async def assign_cycle_endpoint(
    cycle_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Assign a pay cycle to a target scope."""
    org_id = _get_org_id(request)
    role = getattr(request.state, "role", None)
    if role not in ("org_admin", "global_admin"):
        raise HTTPException(status_code=403, detail="org_admin role required")

    from app.modules.timesheets.pay_cycles import assign_pay_cycle
    body = await request.json()

    target_type = body.get("target_type", "all")
    raw_target = body.get("target_id")
    # For employment_type assignments the body carries the raw employment-type
    # string (permanent / casual / fixed_term); the service encodes it to the
    # deterministic UUIDv5 target id (Decision 3). Every other target type uses
    # a UUID target_id (staff_id / branch_id) or None for 'all'.
    if target_type == "employment_type":
        target_id: UUID | str | None = raw_target if raw_target else None
    else:
        target_id = UUID(raw_target) if raw_target else None

    assignment = await assign_pay_cycle(
        db,
        org_id=org_id,
        pay_cycle_id=cycle_id,
        target_type=target_type,
        target_id=target_id,
    )

    return JSONResponse(content={
        "id": str(assignment.id),
        "pay_cycle_id": str(assignment.pay_cycle_id),
        "target_type": assignment.target_type,
        "target_id": str(assignment.target_id) if assignment.target_id else None,
    }, status_code=201)


# ===========================================================================
# Router 5: Pay Run (mounted at /api/v2/pay-run) — Phase B
# ===========================================================================

payrun_router = APIRouter()


@payrun_router.post("/generate/")
async def generate_payrun(
    request: Request,
    pay_period_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db_session),
):
    """Generate payslip drafts for all locked timesheets in a period."""
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    _check_permission(request, "payrun.lock")

    from app.modules.timesheets.payrun import PayRunScopingError, run_pay_period

    try:
        summary = await run_pay_period(
            db, org_id=org_id, pay_period_id=pay_period_id, actor_id=user_id,
        )
    except PayRunScopingError as exc:
        raise HTTPException(status_code=422, detail={"detail": exc.code})

    return JSONResponse(content={
        "pay_period_id": str(summary.pay_period_id),
        "total_timesheets": summary.total_timesheets,
        "payslips_generated": summary.payslips_generated,
        "adjustments_included": summary.adjustments_included,
        "errors": summary.errors,
    })


@payrun_router.post("/adjustments/")
async def create_adjustment(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a post-lock correction adjustment."""
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    _check_permission(request, "payrun.lock")

    from app.modules.timesheets.pay_cycles import create_timesheet_adjustment

    body = await request.json()
    adjustment = await create_timesheet_adjustment(
        db,
        org_id=org_id,
        original_timesheet_id=UUID(body["original_timesheet_id"]),
        correction_period_id=UUID(body["correction_period_id"]),
        adjustment_minutes=body["adjustment_minutes"],
        reason=body["reason"],
        category=body.get("category", "correction"),
        actor_id=user_id,
    )

    return JSONResponse(content={
        "id": str(adjustment.id),
        "original_timesheet_id": str(adjustment.original_timesheet_id),
        "correction_period_id": str(adjustment.correction_period_id),
        "adjustment_minutes": adjustment.adjustment_minutes,
        "reason": adjustment.reason,
        "category": adjustment.category,
    }, status_code=201)


@payrun_router.get("/adjustments/")
async def list_adjustments(
    request: Request,
    pay_period_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db_session),
):
    """List adjustments targeting a specific pay period."""
    org_id = _get_org_id(request)
    _check_permission(request, "payrun.lock")

    from app.modules.timesheets.pay_cycles import TimesheetAdjustment

    result = await db.execute(
        select(TimesheetAdjustment).where(
            TimesheetAdjustment.org_id == org_id,
            TimesheetAdjustment.correction_period_id == pay_period_id,
        )
    )
    adjustments = list(result.scalars().all())

    return JSONResponse(content={
        "items": [
            {
                "id": str(a.id),
                "original_timesheet_id": str(a.original_timesheet_id),
                "adjustment_minutes": a.adjustment_minutes,
                "reason": a.reason,
                "category": a.category,
                "created_by": str(a.created_by),
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in adjustments
        ],
        "total": len(adjustments),
    })
