"""Time-clock + scheduling-ops API router (Phase 3 task B7).

Endpoints (design §5):

| Path                                                              | Method               | Purpose                                  |
|-------------------------------------------------------------------|----------------------|------------------------------------------|
| /api/v2/staff/me/clock-action                                     | POST                 | Self-service in/out (R4)                 |
| /api/v2/staff/me/running-late                                     | POST                 | Running-late upward message (R14b / G3)  |
| /api/v2/staff/{staff_id}/clock                                    | GET                  | List entries for a week (Hours tab — R8) |
| /api/v2/staff/{staff_id}/clock/break-start                        | POST                 | Begin break (R7)                         |
| /api/v2/staff/{staff_id}/clock/break-end                          | POST                 | End break (R7)                           |
| /api/v2/staff/{staff_id}/clock/manual                             | POST                 | Admin manual entry insert (R5)           |
| /api/v2/staff/{staff_id}/clock/manual/{entry_id}                  | PATCH, DELETE        | Admin manual entry edit/delete (R5)      |
| /api/v2/staff/{staff_id}/clock-entries/{entry_id}/flag            | POST                 | Flag entry for follow-up (R8 / G10)      |
| /api/v2/staff/{staff_id}/timesheets                               | GET                  | List week summaries (R9)                 |
| /api/v2/staff/{staff_id}/timesheets/{week_start}/approve          | POST                 | Approve week (R9)                        |
| /api/v2/staff/{staff_id}/timesheets/{week_start}/reopen           | POST                 | Reopen approved week (R9)                |
| /api/v2/overtime-requests                                         | GET, POST            | List + submit (R10)                      |
| /api/v2/overtime-requests/{request_id}/approve                    | POST                 | Approve (R10)                            |
| /api/v2/overtime-requests/{request_id}/reject                     | POST                 | Reject (R10)                             |
| /api/v2/shift-swaps                                               | GET, POST            | List + submit (R12)                      |
| /api/v2/shift-swaps/{swap_id}/accept                              | POST                 | Target accepts (R12 / G8)                |
| /api/v2/shift-swaps/{swap_id}/reject                              | POST                 | Target rejects (R12)                     |
| /api/v2/shift-swaps/{swap_id}/manager-approve                     | POST                 | Manager approves awaiting_manager (G8)   |
| /api/v2/shift-swaps/{swap_id}/manager-reject                      | POST                 | Manager rejects awaiting_manager (G8)    |
| /api/v2/shift-swaps/{swap_id}/cancel                              | POST                 | Requester cancels own swap               |
| /api/v2/shift-cover                                               | GET, POST            | List + open broadcast (R13)              |
| /api/v2/shift-cover/{cover_id}/accept                             | POST                 | Claim (R13 / G6)                         |

All list endpoints return ``{ items, total }`` per project-overview.md.
Module-gated by ``staff_management`` (404 ``not_enabled`` when disabled
for the org) — mirrors the helper in
:mod:`app.modules.staff.router`.

The flag-for-review endpoint enforces RBAC: only ``org_admin`` /
``branch_admin`` / ``location_manager`` can write the flag (R8 / G10).

The kiosk endpoints (``/api/v1/kiosk/clock/lookup`` +
``/api/v1/kiosk/clock/action``) live in :mod:`app.modules.kiosk.router`
per task B9 and are NOT registered here.

**Validates: Requirements R3, R4, R5, R7, R8, R9, R10, R12, R13, R14b — Staff Management Phase 3 task B7**
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.database import get_db_session
from app.modules.auth.models import User
from app.modules.auth.rbac import (
    BRANCH_ADMIN,
    LOCATION_MANAGER,
    ORG_ADMIN,
)
from app.modules.staff.models import StaffLocationAssignment, StaffMember
from app.modules.time_clock import (
    approvals as approvals_service,
    breaks as breaks_service,
    cover as cover_service,
    overtime as overtime_service,
    service as clock_service,
    swaps as swaps_service,
)
from app.modules.time_clock.models import (
    BreakRecord,
    OvertimeRequest,
    ShiftCoverRequest,
    ShiftSwapRequest,
    TimeClockEntry,
    TimesheetApproval,
)
from app.modules.time_clock.schemas import (
    AdminClockOutRequest,
    BreakRecordCreate,
    BreakRecordResponse,
    ClockedInStaffEntry,
    ClockedInStaffListResponse,
    FlagForReviewRequest,
    OvertimeRequestCreate,
    OvertimeRequestDecisionRequest,
    OvertimeRequestListResponse,
    OvertimeRequestResponse,
    RunningLateRequest,
    RunningLateResponse,
    SelfServiceClockActionRequest,
    SelfServiceClockActionResponse,
    ShiftCoverCreate,
    ShiftCoverListResponse,
    ShiftCoverResponse,
    ShiftCoverAssignRequest,
    EligibleStaffItem,
    EligibleStaffListResponse,
    ShiftSwapCreate,
    ShiftSwapListResponse,
    ShiftSwapResponse,
    TimeClockEntryCreate,
    TimeClockEntryListResponse,
    TimeClockEntryResponse,
    TimeClockEntryUpdate,
    TimesheetApprovalListResponse,
    TimesheetApprovalRequest,
    TimesheetApprovalResponse,
)


logger = logging.getLogger(__name__)


router = APIRouter()


# ---------------------------------------------------------------------------
# Auth + module gating helpers (mirrors app/modules/leave/router.py)
# ---------------------------------------------------------------------------


def _get_org_id(request: Request) -> UUID:
    """Resolve the requesting org UUID from middleware state.

    AuthMiddleware populates ``request.state.org_id`` as a string. We
    raise HTTP 401 when missing — matches the staff/leave router
    convention.
    """
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=401, detail="Organisation context required",
        )
    return UUID(str(org_id))


def _get_user_id(request: Request) -> UUID:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="User context required")
    return UUID(str(user_id))


def _get_user_role(request: Request) -> str:
    return str(getattr(request.state, "role", "") or "")


def _get_client_ip(request: Request) -> str | None:
    return getattr(request.state, "client_ip", None)


async def _require_staff_management_module(
    request: Request, db: AsyncSession,
) -> None:
    """Raise 404 ``not_enabled`` when ``staff_management`` is disabled
    for the requesting org. Mirrors the helper in
    :mod:`app.modules.staff.router` + :mod:`app.modules.leave.router`.
    """
    from app.core.modules import ModuleService

    org_id = _get_org_id(request)
    service = ModuleService(db)
    if not await service.is_enabled(str(org_id), "staff_management"):
        raise HTTPException(
            status_code=404,
            detail={"detail": "not_enabled", "module": "staff_management"},
        )


def _require_review_role(request: Request) -> None:
    """Gate flag-for-review (R8 / G10) — only ``org_admin``,
    ``branch_admin``, and ``location_manager`` may flag entries for
    follow-up. Lower roles get 403.
    """
    role = _get_user_role(request)
    if role not in (ORG_ADMIN, BRANCH_ADMIN, LOCATION_MANAGER):
        raise HTTPException(
            status_code=403,
            detail="org_admin, branch_admin, or location_manager required",
        )


async def _require_force_close_scope(
    request: Request,
    db: AsyncSession,
    *,
    staff_id: UUID,
) -> None:
    """Restrict which staff members an Org_User may force-close
    (R6.4 / R6.5).

    An org-level admin (``org_admin``) MAY force-close any Open_Entry
    in the organisation. A branch-scoped user (``branch_admin`` /
    ``location_manager``) MAY force-close only entries for staff
    whose ``staff_location_assignments`` intersect the requester's
    ``request.state.branch_ids``.

    Mirrors the authoritative branch-scope data gate in
    :mod:`app.modules.staff.router` (the staff-stats endpoint). Raises
    403 ``forbidden_scope`` for an out-of-scope target — the caller
    MUST invoke this BEFORE mutating the entry so a rejected request
    leaves the row unchanged.

    Assumes :func:`_require_review_role` has already run, so ``role``
    is one of ``org_admin`` / ``branch_admin`` / ``location_manager``.
    """
    role = _get_user_role(request)

    # Org-level admins have full-org scope — close any entry (R6.4).
    if role == ORG_ADMIN:
        return

    # Branch-scoped users (branch_admin / location_manager): the target
    # staff member must be assigned to a location within the requester's
    # branch scope (R6.4). An out-of-scope target is rejected (R6.5).
    branch_ids_raw = getattr(request.state, "branch_ids", None) or []
    branch_uuids: list[UUID] = []
    for raw in branch_ids_raw:
        try:
            branch_uuids.append(UUID(str(raw)))
        except (ValueError, TypeError):
            continue

    in_scope = False
    if branch_uuids:
        scoped = (
            await db.execute(
                select(StaffLocationAssignment.id)
                .where(
                    StaffLocationAssignment.staff_id == staff_id,
                    StaffLocationAssignment.location_id.in_(branch_uuids),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        in_scope = scoped is not None

    if not in_scope:
        raise HTTPException(
            status_code=403,
            detail={"detail": "forbidden_scope"},
        )


async def _resolve_self_staff(
    db: AsyncSession, *, org_id: UUID, user_id: UUID,
) -> StaffMember:
    """Return the staff record linked to ``user_id`` in ``org_id``.

    Used by ``/staff/me/...`` endpoints (R4 + R14b). Raises HTTP 422
    ``no_staff_for_user`` when the caller has no linked staff record
    — typical for org_admin accounts that are not also clock-in users.
    """
    stmt = (
        select(StaffMember)
        .where(
            and_(
                StaffMember.org_id == org_id,
                StaffMember.user_id == user_id,
                StaffMember.is_active.is_(True),
            ),
        )
        .limit(1)
    )
    staff = (await db.execute(stmt)).scalar_one_or_none()
    if staff is None:
        raise HTTPException(
            status_code=422,
            detail={"detail": "no_staff_for_user"},
        )
    return staff


def _detect_self_service_source(request: Request) -> str:
    """Pick ``self_service_mobile`` vs ``self_service_web`` based on
    the ``User-Agent`` header (R4.5).

    The mobile app builds via Capacitor and sends a User-Agent
    containing ``Mobile`` / ``Android`` / ``iPhone`` / ``Capacitor``;
    everything else is treated as web.
    """
    ua = (request.headers.get("user-agent") or "").lower()
    mobile_signals = ("mobile", "android", "iphone", "ipad", "capacitor")
    if any(sig in ua for sig in mobile_signals):
        return "self_service_mobile"
    return "self_service_web"


# ---------------------------------------------------------------------------
# Photo URL RBAC redaction (R8 / G10)
# ---------------------------------------------------------------------------


def _can_view_photos(role: str) -> bool:
    """Photos are gated to org_admin / branch_admin / location_manager
    (R8.3 / G10). Lower roles get ``None`` for the photo URLs in the
    serialised response.
    """
    return role in (ORG_ADMIN, BRANCH_ADMIN, LOCATION_MANAGER)


# ---------------------------------------------------------------------------
# Service-error → HTTP translation
# ---------------------------------------------------------------------------


def _raise_clock_service_error(exc: clock_service.TimeClockServiceError) -> None:
    """Map service-layer exceptions to documented HTTP envelopes (R3,
    R4, R5, R9). Frontend dispatchers match on ``detail.detail``.
    """
    if isinstance(exc, clock_service.EmployeeNotFoundError):
        raise HTTPException(
            status_code=422,
            detail={
                "detail": "employee_not_found",
                "message": (
                    "Employee code not recognised. Please see your manager."
                ),
            },
        )
    if isinstance(exc, clock_service.KioskLookupRateLimitedError):
        raise HTTPException(
            status_code=429,
            detail={"detail": "kiosk_lookup_rate_limited"},
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )
    if isinstance(exc, clock_service.PhotoRequiredError):
        raise HTTPException(
            status_code=422, detail={"detail": "photo_required"},
        )
    if isinstance(exc, clock_service.SelfServiceDisabledError):
        raise HTTPException(
            status_code=403,
            detail={
                "detail": "self_service_disabled",
                "message": (
                    "Self-service clock-in not enabled — please use the kiosk."
                ),
            },
        )
    if isinstance(exc, clock_service.GeofenceFailedError):
        raise HTTPException(
            status_code=422, detail={"detail": "geofence_failed"},
        )
    if isinstance(exc, clock_service.LockedWeekError):
        raise HTTPException(
            status_code=409, detail={"detail": "timesheet_locked"},
        )
    if isinstance(exc, clock_service.InvalidActionError):
        raise HTTPException(
            status_code=409, detail={"detail": str(exc) or "invalid_action"},
        )
    if isinstance(exc, clock_service.StaffNotFoundError):
        raise HTTPException(status_code=404, detail="Staff member not found")
    if isinstance(exc, clock_service.TimeClockEntryNotFoundError):
        raise HTTPException(
            status_code=404, detail="Time-clock entry not found",
        )
    if isinstance(exc, clock_service.NoUpcomingShiftError):
        raise HTTPException(
            status_code=422, detail={"detail": "no_upcoming_shift"},
        )
    if isinstance(exc, clock_service.TooManyLateReportsError):
        raise HTTPException(
            status_code=429, detail={"detail": "too_many_late_reports"},
        )
    # Unknown — surface as 500 so it shows up in logs.
    raise HTTPException(
        status_code=500,
        detail={"detail": "time_clock_service_error", "message": str(exc)},
    )


def _raise_break_service_error(exc: Exception) -> None:
    """Map break-service exceptions (R7)."""
    if isinstance(exc, breaks_service.BreakNotFoundError):
        raise HTTPException(status_code=404, detail="Break record not found")
    if isinstance(exc, breaks_service.BreakAlreadyEndedError):
        raise HTTPException(
            status_code=409, detail={"detail": "break_already_ended"},
        )
    if isinstance(exc, breaks_service.InvalidBreakTypeError):
        raise HTTPException(
            status_code=422, detail={"detail": "invalid_break_type"},
        )
    if isinstance(exc, clock_service.TimeClockServiceError):
        _raise_clock_service_error(exc)
    raise HTTPException(
        status_code=500, detail={"detail": "break_service_error"},
    )


def _raise_approval_service_error(exc: Exception) -> None:
    """Map approval-service exceptions (R9, R11)."""
    if isinstance(exc, approvals_service.TimesheetApprovalNotFoundError):
        raise HTTPException(
            status_code=404, detail="Timesheet approval not found",
        )
    if isinstance(exc, approvals_service.ToilChoiceRequiredError):
        raise HTTPException(
            status_code=422, detail={"detail": "toil_choice_required"},
        )
    if isinstance(exc, approvals_service.InvalidToilChoiceError):
        raise HTTPException(
            status_code=422, detail={"detail": "invalid_toil_choice"},
        )
    if isinstance(exc, clock_service.TimeClockServiceError):
        _raise_clock_service_error(exc)
    raise HTTPException(
        status_code=500, detail={"detail": "approval_service_error"},
    )


def _raise_swap_service_error(exc: swaps_service.ShiftSwapServiceError) -> None:
    """Map shift-swap service exceptions (R12 / G8)."""
    if isinstance(exc, swaps_service.ShiftSwapNotFoundError):
        raise HTTPException(status_code=404, detail="Shift swap not found")
    if isinstance(exc, swaps_service.ShiftSwapNotAuthorisedError):
        raise HTTPException(
            status_code=403, detail={"detail": str(exc) or "not_authorised"},
        )
    if isinstance(exc, swaps_service.ShiftSwapConflictError):
        raise HTTPException(status_code=409, detail={"detail": exc.code})
    if isinstance(exc, swaps_service.ShiftSwapInvalidStateError):
        raise HTTPException(
            status_code=409, detail={"detail": str(exc) or "invalid_state"},
        )
    raise HTTPException(
        status_code=500, detail={"detail": "shift_swap_service_error"},
    )


def _raise_cover_service_error(
    exc: cover_service.ShiftCoverServiceError,
) -> None:
    """Map shift-cover service exceptions (R13 / G6)."""
    if isinstance(exc, cover_service.ShiftCoverNotFoundError):
        raise HTTPException(status_code=404, detail="Shift cover not found")
    if isinstance(exc, cover_service.ShiftCoverNotAuthorisedError):
        raise HTTPException(
            status_code=403, detail={"detail": str(exc) or "not_authorised"},
        )
    if isinstance(exc, cover_service.ShiftCoverConflictError):
        raise HTTPException(
            status_code=409, detail={"detail": "scheduling_conflict_at_claim"},
        )
    if isinstance(exc, cover_service.ShiftCoverInvalidStateError):
        raise HTTPException(
            status_code=409, detail={"detail": "invalid_state"},
        )
    raise HTTPException(
        status_code=500, detail={"detail": "shift_cover_service_error"},
    )


def _raise_overtime_service_error(
    exc: overtime_service.OvertimeRequestServiceError,
) -> None:
    """Map overtime-request service exceptions (R10)."""
    if isinstance(exc, overtime_service.OvertimeRequestNotFoundError):
        raise HTTPException(
            status_code=404, detail="Overtime request not found",
        )
    if isinstance(exc, overtime_service.OvertimeRequestNotAuthorisedError):
        raise HTTPException(
            status_code=403, detail={"detail": str(exc) or "not_authorised"},
        )
    if isinstance(exc, overtime_service.OvertimeRequestInvalidStateError):
        raise HTTPException(
            status_code=409, detail={"detail": str(exc) or "invalid_state"},
        )
    if isinstance(exc, overtime_service.OvertimeRequestValidationError):
        raise HTTPException(
            status_code=422, detail={"detail": str(exc) or "invalid_payload"},
        )
    raise HTTPException(
        status_code=500, detail={"detail": "overtime_request_service_error"},
    )


# ---------------------------------------------------------------------------
# Serializers (resolve JOIN fields the schema expects)
# ---------------------------------------------------------------------------


async def _bulk_resolve_staff_names(
    db: AsyncSession, staff_ids: set[UUID],
) -> dict[UUID, str]:
    """Bulk-resolve ``staff_members.id → display name`` for response
    enrichment. Used by list endpoints to avoid N+1 lookups.
    """
    if not staff_ids:
        return {}
    rows = await db.execute(
        select(StaffMember.id, StaffMember.first_name, StaffMember.last_name)
        .where(StaffMember.id.in_(staff_ids))
    )
    out: dict[UUID, str] = {}
    for row in rows:
        first = (row.first_name or "").strip()
        last = (row.last_name or "").strip()
        out[row.id] = (f"{first} {last}".strip()) or "Staff"
    return out


async def _bulk_resolve_user_names(
    db: AsyncSession, user_ids: set[UUID],
) -> dict[UUID, str]:
    """Bulk-resolve ``users.id → email`` for response enrichment."""
    if not user_ids:
        return {}
    rows = await db.execute(
        select(User.id, User.email).where(User.id.in_(user_ids))
    )
    return {row.id: (row.email or "") for row in rows}


def _serialise_clock_entry(
    entry: TimeClockEntry,
    *,
    can_view_photos: bool,
    staff_name: str | None = None,
) -> TimeClockEntryResponse:
    """Serialise a :class:`TimeClockEntry` to the schema, applying the
    G10 photo-redaction RBAC.
    """
    data = TimeClockEntryResponse.model_validate(entry).model_dump()
    if not can_view_photos:
        data["clock_in_photo_url"] = None
        data["clock_out_photo_url"] = None
    if staff_name is not None:
        data["staff_name"] = staff_name
    return TimeClockEntryResponse(**data)


def _parse_week_start(week_start: str) -> date:
    """Parse a ``YYYY-MM-DD`` string from the path and 422 on bad input."""
    try:
        return date.fromisoformat(week_start)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail={"detail": "invalid_week_start", "message": "Expected YYYY-MM-DD"},
        )


# ===========================================================================
# /staff/me/* — self-service endpoints (R4, R14b)
#
# Declared BEFORE /staff/{staff_id}/* so FastAPI's score-based router
# matches the static path first.
# ===========================================================================


@router.post(
    "/staff/me/clock-action",
    response_model=SelfServiceClockActionResponse,
    summary="Self-service clock in / clock out",
)
async def self_service_clock_action(
    payload: SelfServiceClockActionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> SelfServiceClockActionResponse:
    """Self-service in/out for staff with
    ``self_service_clock_enabled=true`` (R4).

    Refusal cases:
      - 403 ``self_service_disabled`` — staff has the flag set false.
      - 422 ``photo_required`` — org policy requires a photo and the
        client did not supply one.
      - 422 ``geofence_failed`` — geofence enforced and the
        ``(lat, lng)`` is outside every configured branch's radius.
      - 422 ``no_staff_for_user`` — caller has no linked staff record.
      - 409 ``already_clocked_in`` / ``not_clocked_in`` — action
        sequence violation.
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    staff = await _resolve_self_staff(db, org_id=org_id, user_id=user_id)
    source = _detect_self_service_source(request)

    try:
        entry = await clock_service.self_service_clock_action(
            db,
            org_id=org_id,
            staff_id=staff.id,
            action=payload.action,
            photo_file_key=payload.photo_file_key,
            lat=payload.lat,
            lng=payload.lng,
            source=source,
            user_id=user_id,
            ip_address=ip_address,
        )
    except clock_service.TimeClockServiceError as exc:
        _raise_clock_service_error(exc)

    return SelfServiceClockActionResponse(
        time_clock_entry_id=entry.id,
        action=payload.action,
        source=entry.source,
        clock_in_at=entry.clock_in_at,
        clock_out_at=entry.clock_out_at,
        worked_minutes=entry.worked_minutes,
    )


@router.post(
    "/staff/me/running-late",
    response_model=RunningLateResponse,
    summary="Report running late for an upcoming shift",
)
async def running_late(
    payload: RunningLateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> RunningLateResponse:
    """Staff-initiated "I'm running late" upward message (R14b / G3).

    Looks up the in-window scheduled shift, sends manager SMS, snoozes
    the automated ``check_late_arrivals`` Redis dedupe key, and writes
    audit ``staff.reported_late``. Per-shift rate-limited to 3 reports
    over a rolling 4h window.

    Refusal cases:
      - 422 ``no_upcoming_shift`` — no shift in
        ``[now-60m, now+120m]``.
      - 429 ``too_many_late_reports`` — rate limit tripped.
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    from app.core.redis import redis_pool

    staff = await _resolve_self_staff(db, org_id=org_id, user_id=user_id)

    try:
        result = await clock_service.report_running_late(
            db,
            org_id=org_id,
            staff=staff,
            minutes_late=payload.minutes_late,
            reason=payload.reason,
            redis=redis_pool,
            user_id=user_id,
            ip_address=ip_address,
        )
    except clock_service.TimeClockServiceError as exc:
        _raise_clock_service_error(exc)

    return RunningLateResponse(
        ok=bool(result.get("ok")),
        snoozed_until=result["snoozed_until"],
    )


# ===========================================================================
# /staff/{staff_id}/clock — Hours tab list + manual entry CRUD (R5, R8)
# ===========================================================================


@router.get(
    "/staff/{staff_id}/clock",
    response_model=TimeClockEntryListResponse,
    summary="List time-clock entries for a staff/week (Hours tab)",
)
async def list_clock_entries(
    staff_id: UUID,
    request: Request,
    week: str | None = Query(
        None,
        description=(
            "Monday of the week to load (YYYY-MM-DD). "
            "When omitted, defaults to the current week (UTC)."
        ),
    ),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
) -> TimeClockEntryListResponse:
    """Return the paginated list of ``time_clock_entries`` for the
    staff in the given ISO week (R8.2). Photo URLs are RBAC-redacted
    per :func:`_can_view_photos`.
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    role = _get_user_role(request)
    can_view_photos = _can_view_photos(role)

    if week is not None:
        try:
            week_start = date.fromisoformat(week)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=422,
                detail={"detail": "invalid_week", "message": "Expected YYYY-MM-DD"},
            )
    else:
        today = datetime.now(timezone.utc).date()
        week_start = today - timedelta(days=today.weekday())

    week_end = week_start + timedelta(days=7)
    start_dt = datetime.combine(week_start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(week_end, time.min, tzinfo=timezone.utc)

    base_where = and_(
        TimeClockEntry.org_id == org_id,
        TimeClockEntry.staff_id == staff_id,
        TimeClockEntry.clock_in_at >= start_dt,
        TimeClockEntry.clock_in_at < end_dt,
    )
    total = (
        await db.execute(
            select(TimeClockEntry.id).where(base_where)
        )
    ).all()
    rows = (
        await db.execute(
            select(TimeClockEntry)
            .where(base_where)
            .order_by(TimeClockEntry.clock_in_at.asc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()

    staff_names = await _bulk_resolve_staff_names(db, {staff_id})
    items = [
        _serialise_clock_entry(
            row,
            can_view_photos=can_view_photos,
            staff_name=staff_names.get(staff_id),
        )
        for row in rows
    ]
    return TimeClockEntryListResponse(items=items, total=len(total))


@router.post(
    "/staff/{staff_id}/clock/break-start",
    response_model=BreakRecordResponse,
    status_code=201,
    summary="Begin a break for an open clock entry",
)
async def break_start(
    staff_id: UUID,
    payload: BreakRecordCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> BreakRecordResponse:
    """Insert a ``break_records`` row for the staff's open clock
    entry (R7). The ``staff_id`` path arg is informational — the
    parent entry's ``staff_id`` is the source of truth; we cross-check
    so a caller can't post a break against another staff's entry by
    URL manipulation.
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    parent = await db.get(TimeClockEntry, payload.time_clock_entry_id)
    if parent is None or parent.org_id != org_id or parent.staff_id != staff_id:
        raise HTTPException(
            status_code=404, detail="Time-clock entry not found",
        )

    try:
        record = await breaks_service.start_break(
            db,
            org_id=org_id,
            time_clock_entry_id=payload.time_clock_entry_id,
            break_type=payload.break_type,
            start_at=payload.start_at,
            user_id=user_id,
            ip_address=ip_address,
        )
    except clock_service.TimeClockServiceError as exc:
        _raise_break_service_error(exc)

    return BreakRecordResponse.model_validate(record)


@router.post(
    "/staff/{staff_id}/clock/break-end",
    response_model=BreakRecordResponse,
    summary="End the named break record",
)
async def break_end(
    staff_id: UUID,
    request: Request,
    break_record_id: UUID = Query(..., description="break_records.id"),
    end_at: datetime | None = Query(
        None,
        description="Optional explicit end timestamp (defaults to now()).",
    ),
    db: AsyncSession = Depends(get_db_session),
) -> BreakRecordResponse:
    """Close an open break record (R7). The ``staff_id`` path arg is
    cross-checked against the parent ``time_clock_entries.staff_id``
    so a caller can't close another staff's break by URL manipulation.
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    record = await db.get(BreakRecord, break_record_id)
    if record is None or record.org_id != org_id:
        raise HTTPException(status_code=404, detail="Break record not found")
    parent = await db.get(TimeClockEntry, record.time_clock_entry_id)
    if parent is None or parent.staff_id != staff_id:
        raise HTTPException(status_code=404, detail="Break record not found")

    try:
        record = await breaks_service.end_break(
            db,
            org_id=org_id,
            break_record_id=break_record_id,
            end_at=end_at,
            user_id=user_id,
            ip_address=ip_address,
        )
    except clock_service.TimeClockServiceError as exc:
        _raise_break_service_error(exc)

    return BreakRecordResponse.model_validate(record)


@router.post(
    "/staff/{staff_id}/clock/manual",
    response_model=TimeClockEntryResponse,
    status_code=201,
    summary="Admin-manual clock entry insert (R5)",
)
async def manual_entry_create(
    staff_id: UUID,
    payload: TimeClockEntryCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> TimeClockEntryResponse:
    """Insert an ``admin_manual`` time-clock entry. Refused with 409
    ``timesheet_locked`` when the ``clock_in_at`` falls inside an
    approved week (R9.3).
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    role = _get_user_role(request)
    ip_address = _get_client_ip(request)

    # Path staff_id is authoritative — payload.staff_id is informational
    # (the schema includes it for symmetry but we ignore mismatches).
    try:
        entry = await clock_service.admin_manual_entry(
            db,
            org_id=org_id,
            staff_id=staff_id,
            clock_in_at=payload.clock_in_at,
            clock_out_at=payload.clock_out_at,
            break_minutes=payload.break_minutes,
            notes=payload.notes,
            scheduled_entry_id=payload.scheduled_entry_id,
            created_by=user_id,
            ip_address=ip_address,
        )
    except clock_service.TimeClockServiceError as exc:
        _raise_clock_service_error(exc)

    return _serialise_clock_entry(entry, can_view_photos=_can_view_photos(role))


@router.patch(
    "/staff/{staff_id}/clock/manual/{entry_id}",
    response_model=TimeClockEntryResponse,
    summary="Admin-manual clock entry edit (R5)",
)
async def manual_entry_update(
    staff_id: UUID,
    entry_id: UUID,
    payload: TimeClockEntryUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> TimeClockEntryResponse:
    """Edit an existing ``time_clock_entries`` row. Refused with 409
    ``timesheet_locked`` when the entry's week is approved (R9.3).
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    role = _get_user_role(request)
    ip_address = _get_client_ip(request)

    # Verify the entry belongs to the named staff to keep URL-based
    # tampering off the table.
    existing = await db.get(TimeClockEntry, entry_id)
    if (
        existing is None
        or existing.org_id != org_id
        or existing.staff_id != staff_id
    ):
        raise HTTPException(
            status_code=404, detail="Time-clock entry not found",
        )

    updates = payload.model_dump(exclude_unset=True)

    try:
        entry = await clock_service.update_manual_entry(
            db,
            org_id=org_id,
            entry_id=entry_id,
            updates=updates,
            user_id=user_id,
            ip_address=ip_address,
        )
    except clock_service.TimeClockServiceError as exc:
        _raise_clock_service_error(exc)

    # G16 — when the edit lands inside an approval window, recompute
    # totals + flip status to ``edited_after_approval``. The approvals
    # service is idempotent for non-approved windows.
    week_start = entry.clock_in_at.date()
    week_start = week_start - timedelta(days=week_start.weekday())
    try:
        await approvals_service.recompute_after_edit(
            db,
            org_id=org_id,
            staff_id=staff_id,
            week_start=week_start,
            user_id=user_id,
            ip_address=ip_address,
        )
    except Exception:  # noqa: BLE001 - recompute is best-effort.
        logger.exception(
            "manual_entry_update: recompute_after_edit failed staff=%s "
            "entry=%s",
            staff_id, entry_id,
        )

    return _serialise_clock_entry(entry, can_view_photos=_can_view_photos(role))


@router.delete(
    "/staff/{staff_id}/clock/manual/{entry_id}",
    status_code=204,
    summary="Admin-manual clock entry delete (R5)",
)
async def manual_entry_delete(
    staff_id: UUID,
    entry_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """Hard-delete an entry. Refused with 409 ``timesheet_locked``
    when the entry's week is approved (R9.3).
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    existing = await db.get(TimeClockEntry, entry_id)
    if (
        existing is None
        or existing.org_id != org_id
        or existing.staff_id != staff_id
    ):
        raise HTTPException(
            status_code=404, detail="Time-clock entry not found",
        )

    week_start = existing.clock_in_at.date()
    week_start = week_start - timedelta(days=week_start.weekday())

    try:
        await clock_service.delete_manual_entry(
            db,
            org_id=org_id,
            entry_id=entry_id,
            user_id=user_id,
            ip_address=ip_address,
        )
    except clock_service.TimeClockServiceError as exc:
        _raise_clock_service_error(exc)

    # G16 — recompute totals if this delete lands inside an approval
    # window. The approvals service is idempotent for non-approved
    # windows.
    try:
        await approvals_service.recompute_after_edit(
            db,
            org_id=org_id,
            staff_id=staff_id,
            week_start=week_start,
            user_id=user_id,
            ip_address=ip_address,
        )
    except Exception:  # noqa: BLE001 - recompute is best-effort.
        logger.exception(
            "manual_entry_delete: recompute_after_edit failed staff=%s "
            "entry=%s",
            staff_id, entry_id,
        )

    return Response(status_code=204)


# ===========================================================================
# /staff/clocked-in — admin "who is currently on the clock" dashboard
# ===========================================================================


@router.get(
    "/time-clock/clocked-in",
    response_model=ClockedInStaffListResponse,
    summary="List currently-clocked-in staff (admin dashboard)",
)
async def clocked_in_list(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> ClockedInStaffListResponse:
    """Return every staff with an open ``time_clock_entries`` row.

    Mounted at ``/api/v2/time-clock/clocked-in`` (NOT ``/api/v2/staff/...``)
    to avoid the route-ordering collision with ``staff_router.GET /{staff_id}``
    — that handler is registered earlier in ``app/main.py`` and would
    interpret the literal ``clocked-in`` as a ``staff_id`` UUID, returning
    422 ``Unprocessable Content`` for any non-UUID literal segment.

    Surfaces only the fields the realtime "who's on the clock" admin
    dashboard needs (staff identity + clock_in_at + open-row id) so
    the frontend can render a live elapsed timer client-side without
    per-second polling. Photos and notes are intentionally NOT
    surfaced — those live on the timesheet view.

    RBAC: ``org_admin`` / ``branch_admin`` / ``location_manager`` —
    same gating as the flag-for-review endpoint (G10).
    """
    await _require_staff_management_module(request, db)
    _require_review_role(request)
    org_id = _get_org_id(request)

    items = await clock_service.list_currently_clocked_in(
        db, org_id=org_id,
    )
    return ClockedInStaffListResponse(
        items=[ClockedInStaffEntry(**row) for row in items],
        total=len(items),
    )


@router.post(
    "/time-clock/admin-clock-out/{entry_id}",
    response_model=TimeClockEntryResponse,
    summary="Admin-forced clock-out for a still-open entry",
)
async def admin_clock_out(
    entry_id: UUID,
    payload: AdminClockOutRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> TimeClockEntryResponse:
    """Admin closes an open ``time_clock_entries`` row with a required
    ``reason_note``. Use case: an employee forgot to tap out at end-
    of-shift, the admin closes the row so timesheet totals are
    correct.

    Mounted at ``/api/v2/time-clock/admin-clock-out/{entry_id}`` (NOT
    ``/api/v2/staff/{staff_id}/...``) to avoid the same route-ordering
    collision as the list endpoint above. The ``staff_id`` is derived
    server-side from the ``entry_id`` so the URL is shorter AND the
    "wrong staff_id in the URL" attack vector is impossible.

    The ``reason_note`` is REQUIRED for record-keeping (3–500 chars
    enforced by the schema). The audit row carries both the before
    (open) and after (closed) snapshots PLUS the reason inside
    ``after_value.reason_note`` so post-hoc review can answer "who
    closed this open shift and why".

    Refused with 404 ``time_clock_entry_not_found`` when the entry id
    is unknown OR belongs to a different org. Refused with 409
    ``already_clocked_out`` when the row is already closed (the
    common "two admins racing to close the same shift" case). Refused
    with 409 ``timesheet_locked`` when the new clock_out_at falls
    inside an approved week.

    RBAC: ``org_admin`` / ``branch_admin`` / ``location_manager`` —
    same gating as the flag-for-review endpoint (G10). Force-close is
    additionally **scope-restricted** (R6.4 / R6.5): an ``org_admin``
    may close any open entry in the org, WHILE a branch-scoped user
    (``branch_admin`` / ``location_manager``) may close only entries
    for staff in their assigned branches — an out-of-scope target is
    refused with 403 ``forbidden_scope`` and the entry is left
    unchanged.
    """
    await _require_staff_management_module(request, db)
    _require_review_role(request)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    role = _get_user_role(request)
    ip_address = _get_client_ip(request)

    # Verify entry exists + belongs to this org BEFORE handing to the
    # service so a stale URL surfaces as 404 not_found rather than
    # leaking org_id-bound information through service-layer errors.
    entry_check = await db.get(TimeClockEntry, entry_id)
    if entry_check is None or entry_check.org_id != org_id:
        raise HTTPException(
            status_code=404,
            detail={"detail": "time_clock_entry_not_found"},
        )

    # Authorisation scope (R6.4 / R6.5): an org-level admin may close any
    # entry in the org; a branch-scoped user (branch_admin /
    # location_manager) may close only entries for staff in their assigned
    # branches. Checked BEFORE the service mutates the row so an
    # out-of-scope request (403 forbidden_scope) leaves the entry unchanged.
    await _require_force_close_scope(
        request, db, staff_id=entry_check.staff_id,
    )

    try:
        entry = await clock_service.admin_force_clock_out(
            db,
            org_id=org_id,
            entry_id=entry_id,
            reason_note=payload.reason_note,
            clock_out_at=payload.clock_out_at,
            user_id=user_id,
            ip_address=ip_address,
        )
    except clock_service.TimeClockServiceError as exc:
        _raise_clock_service_error(exc)

    return _serialise_clock_entry(entry, can_view_photos=_can_view_photos(role))


# ===========================================================================
# /staff/{staff_id}/clock-entries/{entry_id}/flag — flag for review (R8 / G10)
# ===========================================================================


@router.post(
    "/staff/{staff_id}/clock-entries/{entry_id}/flag",
    response_model=TimeClockEntryResponse,
    summary="Flag a clock entry for follow-up review (R8 / G10)",
)
async def flag_entry_for_review(
    staff_id: UUID,
    entry_id: UUID,
    payload: FlagForReviewRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> TimeClockEntryResponse:
    """Set ``flags.flagged_for_review=true`` on a ``time_clock_entries``
    row + write audit ``time_clock.flagged_for_review`` (G10).

    RBAC-gated: only ``org_admin`` / ``branch_admin`` /
    ``location_manager`` can flag (lower roles get 403).

    Path uses ``clock-entries/{entry_id}`` (NOT ``clock/...``) so it
    doesn't collide with the named ``clock/break-start`` /
    ``clock/break-end`` / ``clock/manual`` action routes — see
    design §5 for the rationale.
    """
    await _require_staff_management_module(request, db)
    _require_review_role(request)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    role = _get_user_role(request)
    ip_address = _get_client_ip(request)

    entry = await db.get(TimeClockEntry, entry_id)
    if (
        entry is None
        or entry.org_id != org_id
        or entry.staff_id != staff_id
    ):
        raise HTTPException(
            status_code=404, detail="Time-clock entry not found",
        )

    before = dict(entry.flags or {})
    new_flags = dict(before)
    new_flags["flagged_for_review"] = True
    if payload.reason is not None:
        new_flags["review_reason"] = payload.reason
    new_flags["flagged_by"] = str(user_id)
    new_flags["flagged_at"] = datetime.now(timezone.utc).isoformat()
    entry.flags = new_flags

    await db.flush()
    await db.refresh(entry)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="time_clock.flagged_for_review",
        entity_type="time_clock_entry",
        entity_id=entry.id,
        before_value={"flags": before},
        after_value={"flags": new_flags, "reason": payload.reason},
        ip_address=ip_address,
    )

    return _serialise_clock_entry(entry, can_view_photos=_can_view_photos(role))


# ===========================================================================
# /staff/{staff_id}/timesheets — week summaries + approve / reopen (R9, R11)
# ===========================================================================


@router.get(
    "/staff/{staff_id}/timesheets",
    response_model=TimesheetApprovalListResponse,
    summary="List timesheet approvals for a staff (paginated)",
)
async def list_timesheets(
    staff_id: UUID,
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    status: str | None = Query(
        None,
        pattern="^(pending|approved|rejected|edited_after_approval)$",
    ),
    db: AsyncSession = Depends(get_db_session),
) -> TimesheetApprovalListResponse:
    """Paginated list of ``timesheet_approvals`` for the staff,
    ordered by ``week_start DESC`` (most recent first).
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)

    where = [
        TimesheetApproval.org_id == org_id,
        TimesheetApproval.staff_id == staff_id,
    ]
    if status is not None:
        where.append(TimesheetApproval.status == status)

    total_rows = (
        await db.execute(
            select(TimesheetApproval.id).where(and_(*where))
        )
    ).all()
    rows = (
        await db.execute(
            select(TimesheetApproval)
            .where(and_(*where))
            .order_by(TimesheetApproval.week_start.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()

    staff_names = await _bulk_resolve_staff_names(db, {staff_id})
    approver_ids = {row.approved_by for row in rows if row.approved_by}
    approver_emails = await _bulk_resolve_user_names(db, approver_ids)

    items: list[TimesheetApprovalResponse] = []
    for row in rows:
        data = TimesheetApprovalResponse.model_validate(row).model_dump()
        data["staff_name"] = staff_names.get(staff_id)
        if row.approved_by:
            data["approved_by_email"] = approver_emails.get(row.approved_by)
        items.append(TimesheetApprovalResponse(**data))

    return TimesheetApprovalListResponse(items=items, total=len(total_rows))


@router.post(
    "/staff/{staff_id}/timesheets/{week_start}/approve",
    response_model=TimesheetApprovalResponse,
    summary="Approve a week's timesheet (R9, R11)",
)
async def approve_timesheet(
    staff_id: UUID,
    week_start: str,
    payload: TimesheetApprovalRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> TimesheetApprovalResponse:
    """Compute totals, upsert ``timesheet_approvals`` with
    ``status='approved'``, lock ``time_clock_entries`` edits in the
    week, and (when applicable) accrue TOIL.

    G10 — when the week contains entries with
    ``flags.flagged_for_review=true`` AND
    ``payload.acknowledge_flagged`` is not ``true``, refuses with 422
    ``flagged_acknowledgement_required`` so the admin UI's modal
    forces an explicit tick.
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    week_start_date = _parse_week_start(week_start)
    week_end_date = week_start_date + timedelta(days=7)

    # G10 — flagged-acknowledgement gate.
    if not payload.acknowledge_flagged:
        flagged_stmt = (
            select(TimeClockEntry.id)
            .where(
                and_(
                    TimeClockEntry.org_id == org_id,
                    TimeClockEntry.staff_id == staff_id,
                    TimeClockEntry.clock_in_at >= datetime.combine(
                        week_start_date, time.min, tzinfo=timezone.utc,
                    ),
                    TimeClockEntry.clock_in_at < datetime.combine(
                        week_end_date, time.min, tzinfo=timezone.utc,
                    ),
                    TimeClockEntry.flags["flagged_for_review"].astext == "true",
                ),
            )
            .limit(1)
        )
        if (await db.execute(flagged_stmt)).scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=422,
                detail={"detail": "flagged_acknowledgement_required"},
            )

    try:
        approval = await approvals_service.approve_week(
            db,
            org_id=org_id,
            staff_id=staff_id,
            week_start=week_start_date,
            approved_by=user_id,
            toil_choice=payload.toil_choice,
            extra_notes=payload.notes,
            ip_address=ip_address,
        )
    except (
        clock_service.TimeClockServiceError,
        approvals_service.TimesheetApprovalNotFoundError,
        approvals_service.ToilChoiceRequiredError,
        approvals_service.InvalidToilChoiceError,
    ) as exc:
        _raise_approval_service_error(exc)

    staff_names = await _bulk_resolve_staff_names(db, {staff_id})
    approver_emails = (
        await _bulk_resolve_user_names(db, {approval.approved_by})
        if approval.approved_by
        else {}
    )
    data = TimesheetApprovalResponse.model_validate(approval).model_dump()
    data["staff_name"] = staff_names.get(staff_id)
    if approval.approved_by:
        data["approved_by_email"] = approver_emails.get(approval.approved_by)
    return TimesheetApprovalResponse(**data)


@router.post(
    "/staff/{staff_id}/timesheets/{week_start}/reopen",
    response_model=TimesheetApprovalResponse,
    summary="Reopen an approved week (R9.4)",
)
async def reopen_timesheet(
    staff_id: UUID,
    week_start: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> TimesheetApprovalResponse:
    """Flip the week's ``timesheet_approvals.status`` to
    ``edited_after_approval`` so subsequent manual edits are
    permitted (R9.4).
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    week_start_date = _parse_week_start(week_start)

    try:
        approval = await approvals_service.reopen_week(
            db,
            org_id=org_id,
            staff_id=staff_id,
            week_start=week_start_date,
            user_id=user_id,
            ip_address=ip_address,
        )
    except (
        approvals_service.TimesheetApprovalNotFoundError,
        clock_service.TimeClockServiceError,
    ) as exc:
        _raise_approval_service_error(exc)

    staff_names = await _bulk_resolve_staff_names(db, {staff_id})
    approver_emails = (
        await _bulk_resolve_user_names(db, {approval.approved_by})
        if approval.approved_by
        else {}
    )
    data = TimesheetApprovalResponse.model_validate(approval).model_dump()
    data["staff_name"] = staff_names.get(staff_id)
    if approval.approved_by:
        data["approved_by_email"] = approver_emails.get(approval.approved_by)
    return TimesheetApprovalResponse(**data)


# ===========================================================================
# /overtime-requests — submit + decide (R10)
# ===========================================================================


@router.get(
    "/overtime-requests",
    response_model=OvertimeRequestListResponse,
    summary="List overtime requests (paginated, filterable)",
)
async def list_overtime_requests(
    request: Request,
    status: str | None = Query(
        None, pattern="^(pending|approved|rejected)$",
    ),
    staff_id: UUID | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
) -> OvertimeRequestListResponse:
    """List the org's overtime-request rows. ``status`` and
    ``staff_id`` are optional filters. Ordered most-recent-first.
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)

    where = [OvertimeRequest.org_id == org_id]
    if status is not None:
        where.append(OvertimeRequest.status == status)
    if staff_id is not None:
        where.append(OvertimeRequest.staff_id == staff_id)

    total_rows = (
        await db.execute(
            select(OvertimeRequest.id).where(and_(*where))
        )
    ).all()
    rows = (
        await db.execute(
            select(OvertimeRequest)
            .where(and_(*where))
            .order_by(OvertimeRequest.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()

    staff_ids = {row.staff_id for row in rows}
    staff_names = await _bulk_resolve_staff_names(db, staff_ids)
    user_ids = {row.requested_by for row in rows} | {
        row.decided_by for row in rows if row.decided_by
    }
    user_emails = await _bulk_resolve_user_names(db, user_ids)

    items: list[OvertimeRequestResponse] = []
    for row in rows:
        data = OvertimeRequestResponse.model_validate(row).model_dump()
        data["staff_name"] = staff_names.get(row.staff_id)
        data["requested_by_name"] = user_emails.get(row.requested_by)
        if row.decided_by:
            data["decided_by_name"] = user_emails.get(row.decided_by)
        items.append(OvertimeRequestResponse(**data))

    return OvertimeRequestListResponse(items=items, total=len(total_rows))


@router.post(
    "/overtime-requests",
    response_model=OvertimeRequestResponse,
    status_code=201,
    summary="Submit an overtime pre-approval request (R10)",
)
async def submit_overtime_request(
    payload: OvertimeRequestCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> OvertimeRequestResponse:
    """Insert an ``overtime_requests`` row in ``status='pending'``.

    When the caller is a staff submitting for themselves they may
    omit ``staff_id`` — the service resolves it from the caller's
    linked ``staff_members`` record. When admin submits on behalf of
    another staff, ``staff_id`` must be supplied.
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    staff_id = payload.staff_id
    if staff_id is None:
        # Resolve from caller's linked staff record.
        staff = await _resolve_self_staff(
            db, org_id=org_id, user_id=user_id,
        )
        staff_id = staff.id

    try:
        ot_request = await overtime_service.submit_overtime_request(
            db,
            org_id=org_id,
            staff_id=staff_id,
            proposed_extra_minutes=payload.proposed_extra_minutes,
            requested_by=user_id,
            schedule_entry_id=payload.schedule_entry_id,
            reason=payload.reason,
            ip_address=ip_address,
        )
    except overtime_service.OvertimeRequestServiceError as exc:
        _raise_overtime_service_error(exc)

    return OvertimeRequestResponse.model_validate(ot_request)


@router.post(
    "/overtime-requests/{request_id}/approve",
    response_model=OvertimeRequestResponse,
    summary="Approve a pending overtime request (R10)",
)
async def approve_overtime_request(
    request_id: UUID,
    payload: OvertimeRequestDecisionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> OvertimeRequestResponse:
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    try:
        ot_request = await overtime_service.approve_overtime_request(
            db,
            org_id=org_id,
            request_id=request_id,
            decided_by=user_id,
            decision_notes=payload.decision_notes,
            ip_address=ip_address,
        )
    except overtime_service.OvertimeRequestServiceError as exc:
        _raise_overtime_service_error(exc)

    return OvertimeRequestResponse.model_validate(ot_request)


@router.post(
    "/overtime-requests/{request_id}/reject",
    response_model=OvertimeRequestResponse,
    summary="Reject a pending overtime request (R10)",
)
async def reject_overtime_request(
    request_id: UUID,
    payload: OvertimeRequestDecisionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> OvertimeRequestResponse:
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    try:
        ot_request = await overtime_service.reject_overtime_request(
            db,
            org_id=org_id,
            request_id=request_id,
            decided_by=user_id,
            decision_notes=payload.decision_notes,
            ip_address=ip_address,
        )
    except overtime_service.OvertimeRequestServiceError as exc:
        _raise_overtime_service_error(exc)

    return OvertimeRequestResponse.model_validate(ot_request)


# ===========================================================================
# /shift-swaps — list / submit / target-decide / manager-decide / cancel (R12)
# ===========================================================================


def _serialise_swap(
    row: ShiftSwapRequest,
    *,
    staff_names: dict[UUID, str],
    user_emails: dict[UUID, str],
) -> ShiftSwapResponse:
    data = ShiftSwapResponse.model_validate(row).model_dump()
    data["requester_name"] = staff_names.get(row.requester_staff_id)
    if row.target_staff_id:
        data["target_name"] = staff_names.get(row.target_staff_id)
    if row.decided_by:
        data["decided_by_name"] = user_emails.get(row.decided_by)
    return ShiftSwapResponse(**data)


@router.get(
    "/shift-swaps",
    response_model=ShiftSwapListResponse,
    summary="List shift-swap requests (paginated, filterable)",
)
async def list_shift_swaps(
    request: Request,
    status: str | None = Query(
        None,
        pattern="^(pending|awaiting_manager|accepted|rejected|cancelled)$",
    ),
    requester_staff_id: UUID | None = Query(None),
    target_staff_id: UUID | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
) -> ShiftSwapListResponse:
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)

    where = [ShiftSwapRequest.org_id == org_id]
    if status is not None:
        where.append(ShiftSwapRequest.status == status)
    if requester_staff_id is not None:
        where.append(ShiftSwapRequest.requester_staff_id == requester_staff_id)
    if target_staff_id is not None:
        where.append(ShiftSwapRequest.target_staff_id == target_staff_id)

    total_rows = (
        await db.execute(
            select(ShiftSwapRequest.id).where(and_(*where))
        )
    ).all()
    rows = (
        await db.execute(
            select(ShiftSwapRequest)
            .where(and_(*where))
            .order_by(ShiftSwapRequest.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()

    staff_ids: set[UUID] = set()
    user_ids: set[UUID] = set()
    for row in rows:
        staff_ids.add(row.requester_staff_id)
        if row.target_staff_id:
            staff_ids.add(row.target_staff_id)
        if row.decided_by:
            user_ids.add(row.decided_by)
    staff_names = await _bulk_resolve_staff_names(db, staff_ids)
    user_emails = await _bulk_resolve_user_names(db, user_ids)

    items = [
        _serialise_swap(row, staff_names=staff_names, user_emails=user_emails)
        for row in rows
    ]
    return ShiftSwapListResponse(items=items, total=len(total_rows))


@router.post(
    "/shift-swaps",
    response_model=ShiftSwapResponse,
    status_code=201,
    summary="Submit a shift-swap request (R12)",
)
async def submit_shift_swap(
    payload: ShiftSwapCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> ShiftSwapResponse:
    """Insert a new ``shift_swap_requests`` row in ``status='pending'``.

    The requester is the caller's linked staff record (resolved from
    ``request.state.user_id``) — admin submitting on behalf of a
    staff is not yet supported via this endpoint.
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    staff = await _resolve_self_staff(db, org_id=org_id, user_id=user_id)

    try:
        swap = await swaps_service.create_swap_request(
            db,
            org_id=org_id,
            requester_staff_id=staff.id,
            schedule_entry_id=payload.schedule_entry_id,
            target_staff_id=payload.target_staff_id,
            reason=payload.reason,
            user_id=user_id,
            ip_address=ip_address,
        )
    except swaps_service.ShiftSwapServiceError as exc:
        _raise_swap_service_error(exc)

    staff_ids = {swap.requester_staff_id}
    if swap.target_staff_id:
        staff_ids.add(swap.target_staff_id)
    staff_names = await _bulk_resolve_staff_names(db, staff_ids)
    return _serialise_swap(
        swap, staff_names=staff_names, user_emails={},
    )


@router.post(
    "/shift-swaps/{swap_id}/accept",
    response_model=ShiftSwapResponse,
    summary="Target accepts a pending shift-swap (R12 / G8)",
)
async def shift_swap_accept(
    swap_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> ShiftSwapResponse:
    """Caller (must be the swap's ``target_staff_id``) accepts.

    When ``shift_swap_requires_manager_approval=false`` (default),
    auto-approves: re-checks eligibility and flips
    ``schedule_entries.staff_id``. When the toggle is ``true``,
    transitions to ``awaiting_manager`` (no schedule change yet).
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    staff = await _resolve_self_staff(db, org_id=org_id, user_id=user_id)

    try:
        swap = await swaps_service.target_accepts_swap(
            db,
            org_id=org_id,
            swap_id=swap_id,
            acting_staff_id=staff.id,
            user_id=user_id,
            ip_address=ip_address,
        )
    except swaps_service.ShiftSwapServiceError as exc:
        _raise_swap_service_error(exc)

    staff_ids = {swap.requester_staff_id}
    if swap.target_staff_id:
        staff_ids.add(swap.target_staff_id)
    staff_names = await _bulk_resolve_staff_names(db, staff_ids)
    user_emails = (
        await _bulk_resolve_user_names(db, {swap.decided_by})
        if swap.decided_by
        else {}
    )
    return _serialise_swap(
        swap, staff_names=staff_names, user_emails=user_emails,
    )


@router.post(
    "/shift-swaps/{swap_id}/reject",
    response_model=ShiftSwapResponse,
    summary="Target rejects a pending shift-swap (R12)",
)
async def shift_swap_reject(
    swap_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> ShiftSwapResponse:
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    staff = await _resolve_self_staff(db, org_id=org_id, user_id=user_id)

    try:
        swap = await swaps_service.target_rejects_swap(
            db,
            org_id=org_id,
            swap_id=swap_id,
            acting_staff_id=staff.id,
            user_id=user_id,
            ip_address=ip_address,
        )
    except swaps_service.ShiftSwapServiceError as exc:
        _raise_swap_service_error(exc)

    staff_ids = {swap.requester_staff_id}
    if swap.target_staff_id:
        staff_ids.add(swap.target_staff_id)
    staff_names = await _bulk_resolve_staff_names(db, staff_ids)
    return _serialise_swap(
        swap, staff_names=staff_names, user_emails={},
    )


@router.post(
    "/shift-swaps/{swap_id}/manager-approve",
    response_model=ShiftSwapResponse,
    summary="Manager approves a swap from awaiting_manager (G8)",
)
async def shift_swap_manager_approve(
    swap_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> ShiftSwapResponse:
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    try:
        swap = await swaps_service.manager_approves_swap(
            db,
            org_id=org_id,
            swap_id=swap_id,
            manager_user_id=user_id,
            ip_address=ip_address,
        )
    except swaps_service.ShiftSwapServiceError as exc:
        _raise_swap_service_error(exc)

    staff_ids = {swap.requester_staff_id}
    if swap.target_staff_id:
        staff_ids.add(swap.target_staff_id)
    staff_names = await _bulk_resolve_staff_names(db, staff_ids)
    user_emails = (
        await _bulk_resolve_user_names(db, {swap.decided_by})
        if swap.decided_by
        else {}
    )
    return _serialise_swap(
        swap, staff_names=staff_names, user_emails=user_emails,
    )


@router.post(
    "/shift-swaps/{swap_id}/manager-reject",
    response_model=ShiftSwapResponse,
    summary="Manager rejects a swap from awaiting_manager (G8)",
)
async def shift_swap_manager_reject(
    swap_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> ShiftSwapResponse:
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    try:
        swap = await swaps_service.manager_rejects_swap(
            db,
            org_id=org_id,
            swap_id=swap_id,
            manager_user_id=user_id,
            ip_address=ip_address,
        )
    except swaps_service.ShiftSwapServiceError as exc:
        _raise_swap_service_error(exc)

    staff_ids = {swap.requester_staff_id}
    if swap.target_staff_id:
        staff_ids.add(swap.target_staff_id)
    staff_names = await _bulk_resolve_staff_names(db, staff_ids)
    user_emails = (
        await _bulk_resolve_user_names(db, {swap.decided_by})
        if swap.decided_by
        else {}
    )
    return _serialise_swap(
        swap, staff_names=staff_names, user_emails=user_emails,
    )


@router.post(
    "/shift-swaps/{swap_id}/cancel",
    response_model=ShiftSwapResponse,
    summary="Requester cancels their own pending / awaiting_manager swap",
)
async def shift_swap_cancel(
    swap_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> ShiftSwapResponse:
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    staff = await _resolve_self_staff(db, org_id=org_id, user_id=user_id)

    try:
        swap = await swaps_service.cancel_swap(
            db,
            org_id=org_id,
            swap_id=swap_id,
            acting_staff_id=staff.id,
            user_id=user_id,
            ip_address=ip_address,
        )
    except swaps_service.ShiftSwapServiceError as exc:
        _raise_swap_service_error(exc)

    staff_ids = {swap.requester_staff_id}
    if swap.target_staff_id:
        staff_ids.add(swap.target_staff_id)
    staff_names = await _bulk_resolve_staff_names(db, staff_ids)
    return _serialise_swap(
        swap, staff_names=staff_names, user_emails={},
    )


# ===========================================================================
# /shift-cover — open broadcast + claim (R13 / G6)
# ===========================================================================


def _serialise_cover(
    row: ShiftCoverRequest,
    *,
    staff_names: dict[UUID, str],
    entries: dict[UUID, "ScheduleEntry"] | None = None,
) -> ShiftCoverResponse:
    data = ShiftCoverResponse.model_validate(row).model_dump()
    data["requester_name"] = staff_names.get(row.requester_staff_id)
    if row.accepted_by:
        data["accepted_by_name"] = staff_names.get(row.accepted_by)
    entry = (entries or {}).get(row.schedule_entry_id)
    if entry is not None:
        data["shift_start"] = entry.start_time
        data["shift_end"] = entry.end_time
        data["shift_title"] = entry.title
    return ShiftCoverResponse(**data)


async def _load_cover_entries(
    db: AsyncSession, rows: list[ShiftCoverRequest]
) -> dict[UUID, "ScheduleEntry"]:
    """Load the schedule_entries linked to a set of cover rows, keyed by id,
    so each cover can surface the shift date/time it covers."""
    from app.modules.scheduling_v2.models import ScheduleEntry

    entry_ids = {r.schedule_entry_id for r in rows if r.schedule_entry_id}
    if not entry_ids:
        return {}
    erows = (
        await db.execute(
            select(ScheduleEntry).where(ScheduleEntry.id.in_(entry_ids))
        )
    ).scalars().all()
    return {e.id: e for e in erows}


@router.get(
    "/shift-cover",
    response_model=ShiftCoverListResponse,
    summary="List shift-cover requests (paginated, filterable)",
)
async def list_shift_cover(
    request: Request,
    status: str | None = Query(
        None, pattern="^(open|accepted|cancelled|expired)$",
    ),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
) -> ShiftCoverListResponse:
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)

    where = [ShiftCoverRequest.org_id == org_id]
    if status is not None:
        where.append(ShiftCoverRequest.status == status)

    total_rows = (
        await db.execute(
            select(ShiftCoverRequest.id).where(and_(*where))
        )
    ).all()
    rows = (
        await db.execute(
            select(ShiftCoverRequest)
            .where(and_(*where))
            .order_by(ShiftCoverRequest.broadcast_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()

    staff_ids: set[UUID] = set()
    for row in rows:
        staff_ids.add(row.requester_staff_id)
        if row.accepted_by:
            staff_ids.add(row.accepted_by)
    staff_names = await _bulk_resolve_staff_names(db, staff_ids)
    entries_map = await _load_cover_entries(db, rows)

    items = [
        _serialise_cover(row, staff_names=staff_names, entries=entries_map)
        for row in rows
    ]
    return ShiftCoverListResponse(items=items, total=len(total_rows))


@router.post(
    "/shift-cover",
    response_model=ShiftCoverResponse,
    status_code=201,
    summary="Open a shift for cover (R13)",
)
async def submit_shift_cover(
    payload: ShiftCoverCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> ShiftCoverResponse:
    """Insert a ``shift_cover_requests`` row in ``status='open'``,
    compute the eligible-staff list per design §R13.2, and broadcast
    the "Cover needed" SMS.

    The requester is the caller's linked staff record (resolved from
    ``request.state.user_id``).
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    staff = await _resolve_self_staff(db, org_id=org_id, user_id=user_id)

    try:
        cover = await cover_service.create_cover_request(
            db,
            org_id=org_id,
            schedule_entry_id=payload.schedule_entry_id,
            requester_staff_id=staff.id,
            expires_at=payload.expires_at,
            user_id=user_id,
            ip_address=ip_address,
        )
    except cover_service.ShiftCoverServiceError as exc:
        _raise_cover_service_error(exc)

    staff_names = await _bulk_resolve_staff_names(
        db, {cover.requester_staff_id},
    )
    entries_map = await _load_cover_entries(db, [cover])
    return _serialise_cover(cover, staff_names=staff_names, entries=entries_map)


@router.post(
    "/shift-cover/{cover_id}/cancel",
    response_model=ShiftCoverResponse,
    summary="Cancel an open cover — the shift no longer needs coverage",
)
async def shift_cover_cancel(
    cover_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> ShiftCoverResponse:
    """Admin/manager closes an open cover request because the shift no longer
    needs to be covered. Sets ``status='cancelled'`` (no SMS). The underlying
    schedule entry is left untouched.
    """
    await _require_staff_management_module(request, db)
    if _get_user_role(request) not in (ORG_ADMIN, BRANCH_ADMIN, LOCATION_MANAGER):
        raise HTTPException(status_code=403, detail="forbidden")
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    try:
        cover = await cover_service.cancel_cover_request(
            db,
            org_id=org_id,
            cover_id=cover_id,
            acting_staff_id=None,  # admin/manager path
            user_id=user_id,
            ip_address=ip_address,
        )
    except cover_service.ShiftCoverServiceError as exc:
        _raise_cover_service_error(exc)

    staff_names = await _bulk_resolve_staff_names(db, {cover.requester_staff_id})
    entries_map = await _load_cover_entries(db, [cover])
    return _serialise_cover(cover, staff_names=staff_names, entries=entries_map)


@router.post(
    "/shift-cover/{cover_id}/accept",
    response_model=ShiftCoverResponse,
    summary="Claim an open cover request (R13 / G6)",
)
async def shift_cover_accept(
    cover_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> ShiftCoverResponse:
    """Eligible staff claims an open cover. Re-checks eligibility at
    the flip moment (409 ``scheduling_conflict_at_claim`` if a new
    conflicting shift was scheduled since broadcast — R13.4 / G6).
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    staff = await _resolve_self_staff(db, org_id=org_id, user_id=user_id)

    try:
        cover = await cover_service.accept_cover_request(
            db,
            org_id=org_id,
            cover_id=cover_id,
            accepting_staff_id=staff.id,
            user_id=user_id,
            ip_address=ip_address,
        )
    except cover_service.ShiftCoverServiceError as exc:
        _raise_cover_service_error(exc)

    staff_ids = {cover.requester_staff_id}
    if cover.accepted_by:
        staff_ids.add(cover.accepted_by)
    staff_names = await _bulk_resolve_staff_names(db, staff_ids)
    return _serialise_cover(cover, staff_names=staff_names)


@router.get(
    "/shift-cover/{cover_id}/eligible",
    response_model=EligibleStaffListResponse,
    summary="List staff who can be assigned an open cover (no conflicting shift)",
)
async def shift_cover_eligible(
    cover_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> EligibleStaffListResponse:
    """Return active staff with no scheduling conflict in the cover's
    window (admin/manager only) — used to populate the "Assign to staff"
    picker on the Open Shifts page.
    """
    await _require_staff_management_module(request, db)
    if _get_user_role(request) not in (ORG_ADMIN, BRANCH_ADMIN, LOCATION_MANAGER):
        raise HTTPException(status_code=403, detail="forbidden")
    org_id = _get_org_id(request)

    from app.modules.scheduling_v2.models import ScheduleEntry

    cover = await db.get(ShiftCoverRequest, cover_id)
    if cover is None or cover.org_id != org_id:
        raise HTTPException(status_code=404, detail="shift_cover_not_found")
    entry = await db.get(ScheduleEntry, cover.schedule_entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="schedule_entry_not_found")

    eligible = await cover_service.list_eligible_staff(
        db, org_id=org_id, schedule_entry=entry,
        requester_staff_id=cover.requester_staff_id,
    )
    items = [
        EligibleStaffItem(
            id=s.id,
            name=(
                s.name
                or f"{s.first_name or ''} {s.last_name or ''}".strip()
                or "Staff"
            ),
            position=s.position,
        )
        for s in eligible
    ]
    items.sort(key=lambda i: i.name.lower())
    return EligibleStaffListResponse(items=items, total=len(items))


@router.post(
    "/shift-cover/{cover_id}/assign",
    response_model=ShiftCoverResponse,
    summary="Assign an open cover request to a staff member (admin/manager)",
)
async def shift_cover_assign(
    cover_id: UUID,
    payload: ShiftCoverAssignRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> ShiftCoverResponse:
    """Admin/manager assigns an open cover to a chosen staff member.

    Reuses :func:`accept_cover_request` so the same base-eligibility and
    window-conflict re-checks apply (409 ``scheduling_conflict_at_claim``
    when the chosen staff has a conflicting shift). On success the shift's
    ``staff_id`` flips to the assignee and the cover is marked accepted.
    """
    await _require_staff_management_module(request, db)
    if _get_user_role(request) not in (ORG_ADMIN, BRANCH_ADMIN, LOCATION_MANAGER):
        raise HTTPException(status_code=403, detail="forbidden")
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = _get_client_ip(request)

    try:
        cover = await cover_service.accept_cover_request(
            db,
            org_id=org_id,
            cover_id=cover_id,
            accepting_staff_id=payload.staff_id,
            user_id=user_id,
            ip_address=ip_address,
        )
    except cover_service.ShiftCoverServiceError as exc:
        _raise_cover_service_error(exc)

    staff_ids = {cover.requester_staff_id}
    if cover.accepted_by:
        staff_ids.add(cover.accepted_by)
    staff_names = await _bulk_resolve_staff_names(db, staff_ids)
    return _serialise_cover(cover, staff_names=staff_names)
