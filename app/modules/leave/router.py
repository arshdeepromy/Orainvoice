"""Leave module API router.

Endpoints (per design.md §5):

| Path                                                               | Method        | Purpose                          |
|--------------------------------------------------------------------|---------------|----------------------------------|
| /api/v2/leave/types                                                | GET, POST     | List + create leave types        |
| /api/v2/leave/types/{leave_type_id}                                | PATCH         | Update leave type (statutory rows can update non-statutory fields; delete blocked) |
| /api/v2/staff/{staff_id}/leave/balances                            | GET           | Balances for one staff           |
| /api/v2/staff/{staff_id}/leave/ledger                              | GET           | Ledger history for one staff     |
| /api/v2/staff/{staff_id}/leave/requests                            | GET, POST     | List own + submit                |
| /api/v2/staff/{staff_id}/leave/balances/{leave_type_id}/adjust     | POST          | Manual balance adjustment (admin)|
| /api/v2/leave/approvals                                            | GET           | Approval queue (role-scoped)     |
| /api/v2/leave/requests/{request_id}/approve                        | POST          | Approve                          |
| /api/v2/leave/requests/{request_id}/reject                         | POST          | Reject                           |
| /api/v2/leave/requests/{request_id}/cancel                         | POST          | Cancel                           |

All list endpoints return ``{ items, total }``. Pagination uses
``offset`` + ``limit`` (project convention — ``skip`` is silently
ignored upstream). Module-gated by ``staff_management`` (404
``not_enabled`` when disabled, matching the staff router pattern). All
write paths use ``await db.flush()`` (not ``commit``) and
``await db.refresh(obj)`` before returning ORM objects.

Confidential filtering (P2-N1, P2-N12, R4.6, R4.9): every endpoint
that returns ``leave_requests`` (approval queue + per-staff request
list) routes its query through
:func:`app.modules.leave.visibility._apply_confidential_filter` so the
DB never returns family-violence rows to a user without
``leave.fv_view``.

Approval-queue role scoping (B6 spec):
- ``org_admin`` — sees every request in the org.
- ``branch_admin`` — scoped via ``staff_location_assignments`` to the
  branches in their ``request.state.branch_ids`` JSONB array.
- ``manager`` — scoped via ``staff_members.reporting_to`` to direct
  reports.
- Any other role — empty queue.

**Validates: Requirements R1–R4, R7, R11.5 — Staff Management Phase 2 task B6**
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.database import get_db_session
from app.modules.leave import service as leave_service
from app.modules.leave.models import LeaveRequest, LeaveType
from app.modules.leave.schemas import (
    AdjustBalanceRequest,
    EligibilityNote,
    LeaveBalanceListResponse,
    LeaveBalanceResponse,
    LeaveLedgerListResponse,
    LeaveLedgerResponse,
    LeaveRequestCreate,
    LeaveRequestDecisionRequest,
    LeaveRequestListResponse,
    LeaveRequestResponse,
    LeaveTypeCreate,
    LeaveTypeListResponse,
    LeaveTypeResponse,
    LeaveTypeUpdate,
    MarkDayLeaveRequest,
    MarkDayLeaveResponse,
    UnmarkDayLeaveRequest,
    UnmarkDayLeaveResponse,
    StaffLeaveEligibilityItem,
    StaffLeaveEligibilityResponse,
    ReferenceGuideResponse,
    ReferenceGuideSection,
    StaffLeaveBalances,
    StaffLeaveBalancesListResponse,
)
from app.modules.auth.rbac import has_permission
from app.modules.leave.reference_guide import REFERENCE_GUIDE_SECTIONS
from app.modules.leave.service import (
    BereavementCapExceededError,
    BereavementValidationError,
    InsufficientLeaveError,
    InsufficientToilBalanceError,
    LeaveEligibilityError,
    LeavePermissionDenied,
    LeaveServiceError,
)
from app.modules.leave.visibility import _apply_confidential_filter
from app.modules.staff.models import StaffLocationAssignment, StaffMember

router = APIRouter()


# ---------------------------------------------------------------------------
# Auth + module gating helpers (mirrors app/modules/staff/router.py)
# ---------------------------------------------------------------------------


def _get_org_id(request: Request) -> UUID:
    """Resolve the requesting organisation UUID from middleware state.

    AuthMiddleware populates ``request.state.org_id`` as a string. We
    raise HTTP 401 when the header is missing — matches the existing
    staff router so the frontend's error toast logic works unchanged.
    """
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


def _get_user_id(request: Request) -> UUID:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="User context required")
    return UUID(str(user_id))


def _get_user_role(request: Request) -> str:
    return str(getattr(request.state, "role", "") or "")


# Roles permitted to mark another staff member on leave from the roster grid.
_MARK_LEAVE_ROLES = {
    "org_admin",
    "branch_admin",
    "location_manager",
    "global_admin",
}


async def _require_staff_management_module(
    request: Request, db: AsyncSession
) -> None:
    """Raise 404 ``not_enabled`` when ``staff_management`` is disabled
    for the requesting org. Identical to the helper in
    ``app/modules/staff/router.py`` — both gates need the same
    semantics so the frontend's degrade-gracefully logic works
    identically across the two surfaces.
    """
    from app.core.modules import ModuleService

    org_id = _get_org_id(request)
    service = ModuleService(db)
    if not await service.is_enabled(str(org_id), "staff_management"):
        raise HTTPException(
            status_code=404,
            detail={"detail": "not_enabled", "module": "staff_management"},
        )


def _require_org_admin(request: Request) -> None:
    """Gate org_admin-only endpoints (leave-type create / update +
    manual balance adjustment).
    """
    role = _get_user_role(request)
    if role not in ("org_admin", "global_admin"):
        raise HTTPException(status_code=403, detail="org_admin role required")


def _require_permission(request: Request, permission: str) -> None:
    """Gate an endpoint on a permission key (role + custom-role permissions).

    Mirrors ``app/modules/timesheets/router.py::_check_permission``. Raises 403
    when the permission is not granted. Used by the org-wide balances list
    (``leave.balance_view``) and the manual adjust (``leave.balance_adjust``).
    """
    role = _get_user_role(request)
    overrides = getattr(request.state, "permission_overrides", None)
    custom_perms = getattr(request.state, "custom_role_permissions", None)
    if not has_permission(
        role, permission, overrides=overrides, custom_role_permissions=custom_perms
    ):
        raise HTTPException(
            status_code=403, detail=f"Permission '{permission}' required"
        )


# ---------------------------------------------------------------------------
# Service-error → HTTP translation
# ---------------------------------------------------------------------------


def _raise_service_error(exc: LeaveServiceError) -> None:
    """Map a service-layer exception to the right HTTP envelope.

    Routers translate the typed exceptions raised by
    :mod:`app.modules.leave.service` into the JSON shapes documented in
    design §4.3. Frontend dispatcher matches on ``detail.detail``.
    """
    if isinstance(exc, InsufficientLeaveError):
        raise HTTPException(
            status_code=422,
            detail={
                "detail": "insufficient_balance",
                "available": str(exc.available),
            },
        )
    if isinstance(exc, InsufficientToilBalanceError):
        raise HTTPException(
            status_code=422,
            detail={
                "detail": "insufficient_toil_balance",
                "available": str(exc.available),
            },
        )
    if isinstance(exc, BereavementValidationError):
        raise HTTPException(
            status_code=422,
            detail={"detail": "relationship_required", "field": exc.field},
        )
    if isinstance(exc, BereavementCapExceededError):
        raise HTTPException(
            status_code=422,
            detail={
                "detail": "bereavement_cap_exceeded",
                "cap_hours": str(exc.cap_hours),
            },
        )
    if isinstance(exc, LeavePermissionDenied):
        raise HTTPException(status_code=403, detail={"detail": exc.reason})

    # Generic / not-found-style — the service raises with a slug-style
    # message ("leave_request_not_found", "leave_type_not_found", etc).
    msg = str(exc)
    not_found_slugs = (
        "leave_request_not_found",
        "leave_type_not_found",
        "leave_balance_not_found",
        "staff_not_found",
    )
    if any(slug in msg for slug in not_found_slugs):
        raise HTTPException(status_code=404, detail={"detail": msg})
    raise HTTPException(status_code=422, detail={"detail": msg})


# ---------------------------------------------------------------------------
# Approval-queue role scoping
# ---------------------------------------------------------------------------


def _scope_approval_queue(query, request: Request, org_id: UUID, user_id: UUID):
    """Apply role-based scoping to the org-wide approval queue.

    Per the spec:

    - ``org_admin`` (and ``global_admin`` in tenant context) — no extra
      scoping; sees every request in the org.
    - ``branch_admin`` — only requests from staff at the branches the
      admin manages. Staff-branch link is via
      ``staff_location_assignments`` (location_id ∈ user.branch_ids
      JSONB array on the JWT, mirrored on ``request.state.branch_ids``).
    - ``manager`` — only requests from direct reports
      (``staff_members.reporting_to == manager_staff_id``). The
      manager's staff record is found via ``staff_members.user_id ==
      current user``.
    - Any other role — return an empty result set (the queue is
      admin-facing; non-admin staff browse their own requests via
      ``GET /staff/{id}/leave/requests``).
    """
    role = _get_user_role(request)

    if role in ("org_admin", "global_admin"):
        return query

    if role == "branch_admin":
        branch_ids_raw = getattr(request.state, "branch_ids", None) or []
        branch_uuids: list[UUID] = []
        for raw in branch_ids_raw:
            try:
                branch_uuids.append(UUID(str(raw)))
            except (ValueError, TypeError):
                continue
        if not branch_uuids:
            # Branch admin without any branches → empty queue.
            return query.where(LeaveRequest.id.is_(None))
        scoped_staff_ids = (
            select(StaffLocationAssignment.staff_id)
            .where(StaffLocationAssignment.location_id.in_(branch_uuids))
            .distinct()
        )
        return query.where(LeaveRequest.staff_id.in_(scoped_staff_ids))

    if role == "manager":
        # Manager's own staff record (the one whose user_id == current
        # user). Direct reports are staff whose ``reporting_to`` points
        # at that record.
        manager_staff_id_subq = (
            select(StaffMember.id)
            .where(StaffMember.user_id == user_id, StaffMember.org_id == org_id)
            .limit(1)
            .scalar_subquery()
        )
        direct_reports = (
            select(StaffMember.id)
            .where(StaffMember.reporting_to == manager_staff_id_subq)
        )
        return query.where(LeaveRequest.staff_id.in_(direct_reports))

    # Any other role: deny by returning a contradiction.
    return query.where(LeaveRequest.id.is_(None))


# ===========================================================================
# Leave types
# ===========================================================================


@router.post(
    "/leave/mark-day",
    response_model=MarkDayLeaveResponse,
    summary="Mark a staff member on leave for a day and publish their shift to Open Shifts",
)
async def mark_day_leave_endpoint(
    payload: MarkDayLeaveRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Roster-grid "paint leave" action (admin / manager).

    Submits + auto-approves a single-day leave for the chosen leave type and,
    by default, publishes the staff member's displaced shift(s) to Open Shifts.
    Gated by the ``staff_management`` module and a management role.
    """
    await _require_staff_management_module(request, db)
    if _get_user_role(request) not in _MARK_LEAVE_ROLES:
        raise HTTPException(status_code=403, detail="forbidden")
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    try:
        result = await leave_service.mark_day_leave(
            db,
            org_id=org_id,
            staff_id=payload.staff_id,
            leave_type_id=payload.leave_type_id,
            on_date=payload.date,
            requested_by_user_id=user_id,
            request=request,
            publish_to_open_shifts=payload.publish_to_open_shifts,
        )
    except LeaveEligibilityError as exc:
        # Structured "why / when eligible" payload for the UI.
        raise HTTPException(status_code=422, detail=exc.payload)
    except (
        LeaveServiceError,
        InsufficientLeaveError,
        InsufficientToilBalanceError,
        BereavementCapExceededError,
        BereavementValidationError,
    ) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except LeavePermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return MarkDayLeaveResponse(**result)


@router.post(
    "/leave/unmark-day",
    response_model=UnmarkDayLeaveResponse,
    summary="Remove a staff member's leave on a day (inverse of mark-day)",
)
async def unmark_day_leave_endpoint(
    payload: UnmarkDayLeaveRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Roster-grid "remove leave" action (admin / manager).

    Cancels the approved leave request(s) covering the date (restoring the
    balance), clears the leave block, and closes any open cover the staff
    raised for that day. Gated by the ``staff_management`` module and a
    management role.
    """
    await _require_staff_management_module(request, db)
    if _get_user_role(request) not in _MARK_LEAVE_ROLES:
        raise HTTPException(status_code=403, detail="forbidden")
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    try:
        result = await leave_service.unmark_day_leave(
            db,
            org_id=org_id,
            staff_id=payload.staff_id,
            on_date=payload.date,
            requested_by_user_id=user_id,
            request=request,
        )
    except LeavePermissionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LeaveServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return UnmarkDayLeaveResponse(**result)


@router.get(
    "/leave/staff/{staff_id}/eligibility",
    response_model=StaffLeaveEligibilityResponse,
    summary="Per-staff eligibility + balance across every active leave type",
)
async def staff_leave_eligibility(
    staff_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return every active leave type with this staff member's eligibility
    status and current balance — powers the drill-in Leave view.

    Module-gated by ``staff_management`` and the ``leave.balance_view``
    permission. Org-scoped via RLS.
    """
    await _require_staff_management_module(request, db)
    _require_permission(request, "leave.balance_view")
    org_id = _get_org_id(request)
    try:
        result = await leave_service.compute_staff_leave_eligibility(
            db, org_id=org_id, staff_id=staff_id,
        )
    except LeaveServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return StaffLeaveEligibilityResponse(
        staff_id=result["staff_id"],
        employment_start_date=result["employment_start_date"],
        months_completed=result["months_completed"],
        days_employed=result["days_employed"],
        rule_set_version=result["rule_set_version"],
        items=[StaffLeaveEligibilityItem(**it) for it in result["items"]],
    )


@router.get(
    "/leave/types",
    response_model=LeaveTypeListResponse,
    summary="List leave types for the org",
)
async def list_leave_types(
    request: Request,
    include_inactive: bool = Query(False),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
):
    """List leave types for the requesting org.

    Returns active types by default; pass ``?include_inactive=true`` to
    include deactivated rows (Settings → People → Leave Types uses
    this so admins can re-activate previously disabled types).
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)

    stmt = select(LeaveType).where(LeaveType.org_id == org_id)
    if not include_inactive:
        stmt = stmt.where(LeaveType.active.is_(True))
    stmt = stmt.order_by(LeaveType.display_order, LeaveType.name)

    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    items = [LeaveTypeResponse.model_validate(row) for row in rows]

    # Apply pagination after materialising — leave_types is a small
    # table (≤ ~20 rows per org) so a count(*) round-trip would cost
    # more than just slicing in Python.
    total = len(items)
    sliced = items[offset : offset + limit]
    return LeaveTypeListResponse(items=sliced, total=total)


@router.post(
    "/leave/types",
    response_model=LeaveTypeResponse,
    status_code=201,
    summary="Create leave type (org_admin only)",
)
async def create_leave_type(
    payload: LeaveTypeCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a custom leave type. Statutory rows are seeded by the
    A1 migration backfill; this endpoint always inserts with
    ``is_statutory=false``.
    """
    await _require_staff_management_module(request, db)
    _require_org_admin(request)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = getattr(request.state, "client_ip", None)

    # Reject duplicate code within the org early — the DB unique
    # constraint would also catch this, but a 422 with a clear slug is
    # easier for the frontend to render than a 500 from the
    # constraint violation.
    existing = await db.execute(
        select(LeaveType.id).where(
            LeaveType.org_id == org_id, LeaveType.code == payload.code
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=422,
            detail={"detail": "leave_type_code_in_use", "code": payload.code},
        )

    leave_type = LeaveType(
        org_id=org_id,
        code=payload.code,
        name=payload.name,
        is_paid=payload.is_paid,
        accrual_method=payload.accrual_method,
        accrual_amount=payload.accrual_amount,
        accrual_unit=payload.accrual_unit,
        carry_over_max=payload.carry_over_max,
        is_statutory=False,
        requires_doctor_note=payload.requires_doctor_note,
        confidential_visibility=payload.confidential_visibility,
        active=payload.active,
        display_order=payload.display_order,
    )
    db.add(leave_type)
    await db.flush()
    await db.refresh(leave_type)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="leave_type.created",
        entity_type="leave_type",
        entity_id=leave_type.id,
        after_value={
            "code": leave_type.code,
            "name": leave_type.name,
            "accrual_method": leave_type.accrual_method,
            "accrual_amount": (
                str(leave_type.accrual_amount)
                if leave_type.accrual_amount is not None
                else None
            ),
            "accrual_unit": leave_type.accrual_unit,
        },
        ip_address=ip_address,
    )

    return LeaveTypeResponse.model_validate(leave_type)


@router.patch(
    "/leave/types/{leave_type_id}",
    response_model=LeaveTypeResponse,
    summary="Update leave type (org_admin only)",
)
async def update_leave_type(
    leave_type_id: UUID,
    payload: LeaveTypeUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update a leave type. Statutory types can update display fields
    (``display_order``, ``active``, ``carry_over_max`` etc) but
    deactivating a statutory type is blocked per R7 (the DB-level
    backfill seeds them and the workflow refuses to delete them).
    """
    await _require_staff_management_module(request, db)
    _require_org_admin(request)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    ip_address = getattr(request.state, "client_ip", None)

    leave_type = await db.get(LeaveType, leave_type_id)
    if leave_type is None or leave_type.org_id != org_id:
        raise HTTPException(
            status_code=404, detail={"detail": "leave_type_not_found"}
        )

    fields = payload.model_dump(exclude_unset=True)

    # R7 / design §6.3: statutory rows can be reordered or have their
    # display attributes tweaked but cannot be deactivated or have
    # their statutory accrual_method swapped. The frontend already
    # disables the toggle but the backend enforces the rule too.
    if leave_type.is_statutory and fields.get("active") is False:
        raise HTTPException(
            status_code=422,
            detail={"detail": "statutory_leave_type_cannot_be_deactivated"},
        )

    before_value: dict[str, Any] = {}
    after_value: dict[str, Any] = {}
    for key, new_value in fields.items():
        old_value = getattr(leave_type, key)
        if old_value != new_value:
            before_value[key] = (
                str(old_value) if isinstance(old_value, Decimal) else old_value
            )
            after_value[key] = (
                str(new_value) if isinstance(new_value, Decimal) else new_value
            )
            setattr(leave_type, key, new_value)

    await db.flush()
    await db.refresh(leave_type)

    if after_value:
        await write_audit_log(
            session=db,
            org_id=org_id,
            user_id=user_id,
            action="leave_type.updated",
            entity_type="leave_type",
            entity_id=leave_type.id,
            before_value=before_value or None,
            after_value=after_value,
            ip_address=ip_address,
        )

    return LeaveTypeResponse.model_validate(leave_type)


# ===========================================================================
# Org-wide Leave Balances list + reference guide
# ===========================================================================


@router.get(
    "/leave/balances",
    response_model=StaffLeaveBalancesListResponse,
    summary="Org-wide leave balances list",
)
async def list_org_leave_balances(
    request: Request,
    employment_type: str | None = Query(None),
    group_by: str | None = Query(None, pattern="^(employment_type)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
):
    """List every staff member with their vested leave balances (R1).

    Module-gated by ``staff_management`` (404 ``not_enabled``) AND the
    ``leave.balance_view`` permission (403). Org-scoped via RLS. The
    ``employment_type`` filter and ``group_by`` are display conveniences applied
    after eligibility (R2.4); only vested types are included per row (R1.6).
    """
    await _require_staff_management_module(request, db)
    _require_permission(request, "leave.balance_view")
    org_id = _get_org_id(request)

    items, total = await leave_service.list_org_balances(
        db,
        org_id=org_id,
        employment_type=employment_type,
        group_by=group_by,
        offset=offset,
        limit=limit,
    )
    return StaffLeaveBalancesListResponse(
        items=[
            StaffLeaveBalances(
                staff_id=row["staff_id"],
                staff_name=row["staff_name"],
                employment_type=row["employment_type"],
                holiday_pay_method=row["holiday_pay_method"],
                balances=[
                    LeaveBalanceResponse(**b) for b in row["balances"]
                ],
                eligibility_notes=[
                    EligibilityNote(**n) for n in row["eligibility_notes"]
                ],
            )
            for row in items
        ],
        total=total,
    )


@router.get(
    "/leave/reference-guide",
    response_model=ReferenceGuideResponse,
    summary="NZ Holidays Act 2003 reference guide",
)
async def get_leave_reference_guide(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the NZ Holidays Act 2003 reference content (R15).

    Module-gated; available to any org user even when content is partially
    populated (R15.6).
    """
    await _require_staff_management_module(request, db)
    return ReferenceGuideResponse(
        rule_set_version="holidays_act_2003",
        sections=[
            ReferenceGuideSection(**s) for s in REFERENCE_GUIDE_SECTIONS
        ],
    )


# ===========================================================================
# Per-staff balances + ledger + requests
# ===========================================================================


@router.get(
    "/staff/{staff_id}/leave/balances",
    response_model=LeaveBalanceListResponse,
    summary="List leave balances for one staff member",
)
async def list_staff_balances(
    staff_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return all per-type balances for a staff member.

    Service layer JOINs ``leave_types`` for ``leave_type_code`` /
    ``leave_type_name`` and computes ``available_hours`` so the
    frontend can render the balance cards without an extra round-trip.
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    items, total = await leave_service.list_balances(
        db, org_id=org_id, staff_id=staff_id
    )
    return LeaveBalanceListResponse(
        items=[LeaveBalanceResponse(**item) for item in items],
        total=total,
    )


@router.get(
    "/staff/{staff_id}/leave/ledger",
    response_model=LeaveLedgerListResponse,
    summary="List leave ledger entries for one staff member",
)
async def list_staff_ledger(
    staff_id: UUID,
    request: Request,
    leave_type_id: UUID | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
):
    """Return ledger entries for a staff member, optionally filtered
    by leave_type. Confidential rows are filtered out by the service
    layer's ``_apply_confidential_filter``.

    P2-N10: when the underlying leave type is per-event (e.g.
    bereavement), each item surfaces ``request_relationship_to_subject``
    via JOIN to ``leave_requests.relationship_to_subject``.
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    user_role = _get_user_role(request)

    items, total = await leave_service.list_ledger(
        db,
        org_id=org_id,
        staff_id=staff_id,
        leave_type_id=leave_type_id,
        request=request,
        user_id=user_id,
        user_role=user_role,
        offset=offset,
        limit=limit,
    )
    return LeaveLedgerListResponse(
        items=[LeaveLedgerResponse(**item) for item in items],
        total=total,
    )


@router.get(
    "/staff/{staff_id}/leave/requests",
    response_model=LeaveRequestListResponse,
    summary="List leave requests for one staff member",
)
async def list_staff_requests(
    staff_id: UUID,
    request: Request,
    status: str | None = Query(None, pattern="^(pending|approved|rejected|cancelled)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
):
    """Return leave requests for one staff member.

    The service routes the underlying query through
    ``_apply_confidential_filter``: a staff browsing their own list
    sees their own confidential requests (subject branch); other
    callers without ``leave.fv_view`` do not.
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    user_role = _get_user_role(request)

    items, total = await leave_service.list_requests(
        db,
        org_id=org_id,
        staff_id=staff_id,
        status=status,
        request=request,
        user_id=user_id,
        user_role=user_role,
        offset=offset,
        limit=limit,
    )
    return LeaveRequestListResponse(
        items=[LeaveRequestResponse(**item) for item in items],
        total=total,
    )


@router.post(
    "/staff/{staff_id}/leave/requests",
    response_model=LeaveRequestResponse,
    status_code=201,
    summary="Submit a leave request",
)
async def submit_staff_request(
    staff_id: UUID,
    payload: LeaveRequestCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Submit a new leave request for a staff member.

    Validation (bereavement gate, TOIL guard, balance check, partial
    day capture) lives in :func:`app.modules.leave.service.submit_request`.
    Service-layer exceptions are translated to HTTP via
    :func:`_raise_service_error`.
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)

    try:
        leave_request = await leave_service.submit_request(
            db,
            org_id=org_id,
            staff_id=staff_id,
            payload=payload,
            requested_by_user_id=user_id,
        )
    except LeaveServiceError as exc:
        _raise_service_error(exc)

    # The service returns the bare ORM row — wrap it in the response
    # schema. Joined fields (staff_name, leave_type_code, etc.) are
    # left as None on the immediate post-submit response since the
    # frontend already has the staff + leave_type names locally.
    return LeaveRequestResponse.model_validate(leave_request)


# ===========================================================================
# Decision endpoints
# ===========================================================================


@router.post(
    "/leave/requests/{request_id}/approve",
    response_model=LeaveRequestResponse,
    summary="Approve a pending leave request",
)
async def approve_leave_request(
    request_id: UUID,
    payload: LeaveRequestDecisionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Approve a pending leave request.

    Confidential-permission check (R4.6) runs in the service before
    any state mutation; non-permitted approvers receive HTTP 403 and
    no audit row is written.
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)

    try:
        leave_request = await leave_service.approve_request(
            db,
            org_id=org_id,
            request_id=request_id,
            decided_by_user_id=user_id,
            request=request,
            decision_notes=payload.decision_notes,
        )
    except LeaveServiceError as exc:
        _raise_service_error(exc)

    return LeaveRequestResponse.model_validate(leave_request)


@router.post(
    "/leave/requests/{request_id}/reject",
    response_model=LeaveRequestResponse,
    summary="Reject a pending leave request",
)
async def reject_leave_request(
    request_id: UUID,
    payload: LeaveRequestDecisionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Reject a pending leave request. ``decision_notes`` is optional;
    confidential leave types redact it from the audit row per design
    §4.3.1.
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)

    try:
        leave_request = await leave_service.reject_request(
            db,
            org_id=org_id,
            request_id=request_id,
            decided_by_user_id=user_id,
            request=request,
            decision_notes=payload.decision_notes,
        )
    except LeaveServiceError as exc:
        _raise_service_error(exc)

    return LeaveRequestResponse.model_validate(leave_request)


@router.post(
    "/leave/requests/{request_id}/cancel",
    response_model=LeaveRequestResponse,
    summary="Cancel a pending or approved leave request",
)
async def cancel_leave_request(
    request_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Cancel a pending or approved leave request.

    Subject-branch (staff cancelling their own request) and approver-
    branch (admin with ``leave.fv_view``) are both allowed by the
    service. For an approved request, a compensating ledger row
    restores the hours; for pending, just the pending counter is
    reversed.
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)

    try:
        leave_request = await leave_service.cancel_request(
            db,
            org_id=org_id,
            request_id=request_id,
            user_id=user_id,
            request=request,
        )
    except LeaveServiceError as exc:
        _raise_service_error(exc)

    return LeaveRequestResponse.model_validate(leave_request)


# ===========================================================================
# Manual balance adjustment (admin)
# ===========================================================================


@router.post(
    "/staff/{staff_id}/leave/balances/{leave_type_id}/adjust",
    summary="Manual balance adjustment (org_admin only)",
)
async def adjust_leave_balance(
    staff_id: UUID,
    leave_type_id: UUID,
    payload: AdjustBalanceRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Adjust a staff member's leave balance.

    The path parameters override any ``staff_id`` / ``leave_type_id``
    on the body so the audit trail always carries the URL-bound IDs.
    Returns the resulting ledger row id + new accrued total.
    """
    await _require_staff_management_module(request, db)
    _require_permission(request, "leave.balance_adjust")
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)

    try:
        ledger = await leave_service.adjust_balance(
            db,
            org_id=org_id,
            staff_id=staff_id,
            leave_type_id=leave_type_id,
            delta_hours=payload.delta_hours,
            reason=payload.reason,
            notes=payload.notes,
            created_by_user_id=user_id,
        )
    except LeaveServiceError as exc:
        _raise_service_error(exc)

    return {
        "ledger_id": str(ledger.id),
        "delta_hours": str(ledger.delta_hours),
        "occurred_at": ledger.occurred_at.isoformat(),
    }


# ===========================================================================
# Approval queue (role-scoped)
# ===========================================================================


@router.get(
    "/leave/approvals",
    response_model=LeaveRequestListResponse,
    summary="Approval queue (role-scoped)",
)
async def list_approval_queue(
    request: Request,
    status: str | None = Query(
        "pending", pattern="^(pending|approved|rejected|cancelled|all)$"
    ),
    start_lte: date | None = Query(
        None,
        description="Filter requests starting on or before this date (used with end_gte)",
    ),
    end_gte: date | None = Query(
        None,
        description="Filter requests ending on or after this date (used with start_lte)",
    ),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
):
    """Approval queue for admins / managers.

    Scoping (per spec):
      - ``org_admin`` — every request in the org.
      - ``branch_admin`` — only requests from staff at branches in
        ``request.state.branch_ids``.
      - ``manager`` — only requests from direct reports (resolved via
        ``staff_members.reporting_to``).

    Confidential filter from B3a is applied AFTER role scoping so
    family-violence requests submitted by other staff are hidden from
    non-permitted admins. Per-N12, the filter keys subject access to
    ``staff_id`` (not ``requested_by``), so a staff member whose FV
    request was proxy-submitted by a manager still sees it in their
    own approval queue (irrelevant for this endpoint — they wouldn't
    be in the approval queue at all — but exercised by the per-staff
    request list).

    Default ``status='pending'`` — admins land on the queue and see
    the actionable items first; pass ``?status=all`` to see every
    state.
    """
    await _require_staff_management_module(request, db)
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    user_role = _get_user_role(request)

    # Build the joined SELECT inline so the count + list queries share
    # the same WHERE clauses (status filter, role scoping, confidential
    # filter). The shape mirrors ``service.list_requests`` but adds the
    # role-scoping wrapper that's specific to the approval queue.
    from app.modules.auth.models import User
    from app.modules.leave.models import LeaveType as LT

    requested_by_user = User.__table__.alias("requested_by_user")

    base_query = select(LeaveRequest).where(LeaveRequest.org_id == org_id)
    if status and status != "all":
        base_query = base_query.where(LeaveRequest.status == status)
    # Date-range filter (Roster Grid Editor — task A7). When both
    # ``start_lte`` and ``end_gte`` are supplied, restrict to requests
    # whose date range overlaps the visible window. Applied BEFORE the
    # role-scoping wrapper so admin scoping still bites.
    if start_lte is not None and end_gte is not None:
        base_query = base_query.where(
            LeaveRequest.start_date <= start_lte,
            LeaveRequest.end_date >= end_gte,
        )
    base_query = _scope_approval_queue(base_query, request, org_id, user_id)
    base_query = _apply_confidential_filter(base_query, request, user_id, user_role)

    from sqlalchemy import func as sa_func

    count_stmt = select(sa_func.count()).select_from(base_query.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    detail_stmt = (
        select(
            LeaveRequest,
            StaffMember.first_name.label("staff_first_name"),
            StaffMember.last_name.label("staff_last_name"),
            LT.code.label("leave_type_code"),
            LT.name.label("leave_type_name"),
            requested_by_user.c.first_name.label("requested_by_first_name"),
            requested_by_user.c.last_name.label("requested_by_last_name"),
            requested_by_user.c.email.label("requested_by_email"),
        )
        .join(StaffMember, LeaveRequest.staff_id == StaffMember.id)
        .join(LT, LeaveRequest.leave_type_id == LT.id)
        .outerjoin(
            requested_by_user,
            LeaveRequest.requested_by == requested_by_user.c.id,
        )
        .where(LeaveRequest.org_id == org_id)
    )
    if status and status != "all":
        detail_stmt = detail_stmt.where(LeaveRequest.status == status)
    if start_lte is not None and end_gte is not None:
        detail_stmt = detail_stmt.where(
            LeaveRequest.start_date <= start_lte,
            LeaveRequest.end_date >= end_gte,
        )
    detail_stmt = _scope_approval_queue(detail_stmt, request, org_id, user_id)
    detail_stmt = _apply_confidential_filter(
        detail_stmt, request, user_id, user_role
    )
    detail_stmt = (
        detail_stmt.order_by(LeaveRequest.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(detail_stmt)
    rows = result.all()

    items: list[LeaveRequestResponse] = []
    for row in rows:
        leave_request: LeaveRequest = row[0]
        staff_first = row.staff_first_name or ""
        staff_last = row.staff_last_name or ""
        staff_name = f"{staff_first} {staff_last}".strip() or None

        first = row.requested_by_first_name
        last = row.requested_by_last_name
        if first or last:
            requested_by_name = " ".join(p for p in (first, last) if p)
        else:
            requested_by_name = row.requested_by_email

        items.append(
            LeaveRequestResponse(
                id=leave_request.id,
                org_id=leave_request.org_id,
                staff_id=leave_request.staff_id,
                staff_name=staff_name,
                leave_type_id=leave_request.leave_type_id,
                leave_type_code=row.leave_type_code,
                leave_type_name=row.leave_type_name,
                start_date=leave_request.start_date,
                end_date=leave_request.end_date,
                hours_requested=leave_request.hours_requested,
                status=leave_request.status,
                reason=leave_request.reason,
                relationship_to_subject=leave_request.relationship_to_subject,
                partial_day_start_time=leave_request.partial_day_start_time,
                attachment_upload_id=leave_request.attachment_upload_id,
                requested_by=leave_request.requested_by,
                requested_by_name=requested_by_name,
                decided_by=leave_request.decided_by,
                decided_at=leave_request.decided_at,
                decision_notes=leave_request.decision_notes,
                created_at=leave_request.created_at,
                updated_at=leave_request.updated_at,
            )
        )

    return LeaveRequestListResponse(items=items, total=total)
