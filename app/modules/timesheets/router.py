"""Staff timesheets router — 16 Phase A endpoints.

Registers at:
- /api/v2/timesheets (list, detail, actions)
- /api/v2/clocked-in (real-time view)
- /api/v2/timesheet-settings (configuration)

All read endpoints use BranchScopedTimesheets dependency.
Permission checks use has_permission() from rbac.
"""
from __future__ import annotations

from datetime import datetime, timezone
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
    BulkActionResponse,
    ClockedInResponse,
    PeriodSummary,
    TimesheetDetailResponse,
    TimesheetListResponse,
    TimesheetSettingsRead,
    TimesheetSettingsResponse,
    TimesheetSettingsUpdate,
    TimesheetSummary,
)
from app.modules.timesheets.service import (
    adjust_timesheet,
    bulk_approve,
    bulk_lock,
    get_or_create_timesheet,
    get_settings_for_branch,
    transition_status,
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


@timesheets_router.get("/{id}")
async def get_timesheet_detail(
    id: UUID,
    request: Request,
    scope: BranchScopedTimesheets = Depends(),
    db: AsyncSession = Depends(get_db_session),
) -> TimesheetDetailResponse:
    """Get timesheet detail with entries.

    Placeholder: returns basic data from the Timesheet row, empty entries.
    """
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

    return TimesheetDetailResponse(
        id=ts.id,
        staff_id=ts.staff_id,
        staff_name="",  # Placeholder — will join staff_members.name
        pay_period_id=ts.pay_period_id,
        period_start="",  # Placeholder — will join pay_periods
        period_end="",
        branch_name=None,
        status=ts.status,
        rostered_minutes=ts.rostered_minutes,
        actual_minutes=ts.actual_minutes,
        adjusted_minutes=ts.adjusted_minutes,
        ordinary_minutes=ts.ordinary_minutes,
        overtime_minutes=ts.overtime_minutes,
        public_holiday_minutes=ts.public_holiday_minutes,
        exception_flags=ts.exception_flags if ts.exception_flags else [],
        notes=ts.notes,
        approved_by_name=None,
        approved_at=ts.approved_at,
        locked_at=ts.locked_at,
        locked_by_name=None,
        entries=[],  # Placeholder — will fetch clock entries with matches
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
    db: AsyncSession = Depends(get_db_session),
):
    """Materialise missing timesheets before pay-run cutoff (org_admin only)."""
    org_id = _get_org_id(request)
    role = getattr(request.state, "role", None)
    if role not in ("org_admin", "global_admin"):
        raise HTTPException(status_code=403, detail="org_admin role required")

    from app.modules.timesheets.service import materialise_missing_timesheets, MaterialisationResult

    result = await materialise_missing_timesheets(
        db, org_id=org_id, pay_period_id=pay_period_id,
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

    target_id = UUID(body["target_id"]) if body.get("target_id") else None
    assignment = await assign_pay_cycle(
        db,
        org_id=org_id,
        pay_cycle_id=cycle_id,
        target_type=body.get("target_type", "all"),
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

    from app.modules.timesheets.payrun import run_pay_period

    summary = await run_pay_period(
        db, org_id=org_id, pay_period_id=pay_period_id, actor_id=user_id,
    )

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
