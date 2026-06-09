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

    Placeholder: returns empty items with zero counts.
    Full aggregation queries will be wired in integration phase.
    """
    org_id = _get_org_id(request)

    # Placeholder response — real query will join staff names, compute summaries
    return TimesheetListResponse(
        items=[],
        total=0,
        period_summary=PeriodSummary(
            total_staff=0,
            approved_count=0,
            pending_count=0,
            locked_count=0,
            total_ordinary_hours=Decimal("0.00"),
            total_overtime_hours=Decimal("0.00"),
            total_public_holiday_hours=Decimal("0.00"),
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

    Placeholder: returns 200 with message.
    Full recomputation will call aggregation.compute_timesheet().
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

    return JSONResponse(
        content={"message": "Recomputation triggered", "timesheet_id": str(id)},
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


@timesheets_router.post("/materialise")
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

    Placeholder: returns empty list.
    Full implementation will query time_clock_entries WHERE clock_out_at IS NULL.
    """
    _get_org_id(request)

    return ClockedInResponse(items=[], total=0)


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
    )
