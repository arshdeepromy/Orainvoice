"""Staff management API router.

Endpoints:
- GET    /api/v2/staff                          — list (paginated/filterable)
- POST   /api/v2/staff                          — create
- GET    /api/v2/staff/{id}                     — get
- PUT    /api/v2/staff/{id}                     — update
- DELETE /api/v2/staff/{id}                     — deactivate
- POST   /api/v2/staff/{id}/assign-location     — assign to location
- DELETE /api/v2/staff/{id}/locations/{loc_id}  — remove from location
- GET    /api/v2/staff/utilisation              — utilisation report
- GET    /api/v2/staff/labour-costs             — labour cost report

**Validates: Requirement — Staff Module**
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.staff.models import StaffMember
from app.modules.staff.schemas import (
    AssignToLocationRequest,
    CreateStaffAccountRequest,
    LabourCostResponse,
    LocationAssignmentResponse,
    StaffMemberCreate,
    StaffMemberListResponse,
    StaffMemberResponse,
    StaffMemberUpdate,
    UtilisationReportResponse,
)
from app.modules.staff.service import StaffService

router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


async def _enrich_reporting_to(db: AsyncSession, staff: StaffMember) -> dict:
    """Build response dict with reporting_to_name resolved."""
    data = StaffMemberResponse.model_validate(staff).model_dump()
    if staff.reporting_to:
        result = await db.execute(
            select(StaffMember.first_name, StaffMember.last_name)
            .where(StaffMember.id == staff.reporting_to)
        )
        row = result.first()
        if row:
            data["reporting_to_name"] = f"{row[0] or ''} {row[1] or ''}".strip()
    return data

@router.get("/check-duplicate")
async def check_staff_duplicate(
    request: Request,
    field: str = Query(..., pattern="^(email|phone|employee_id)$"),
    value: str = Query(..., min_length=1),
    exclude_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    """Check if a staff field value is already in use (real-time validation)."""
    org_id = _get_org_id(request)
    col = getattr(StaffMember, field)
    stmt = select(StaffMember.id).where(
        StaffMember.org_id == org_id,
        col == value.strip(),
        StaffMember.is_active.is_(True),
    )
    if exclude_id:
        stmt = stmt.where(StaffMember.id != exclude_id)
    result = await db.execute(stmt.limit(1))
    exists = result.scalar_one_or_none() is not None
    label = field.replace("_", " ").title()
    return {"duplicate": exists, "message": f"{label} already in use" if exists else ""}




# ---------------------------------------------------------------------------
# Reports (must be before /{staff_id} to avoid path conflict)
# ---------------------------------------------------------------------------

@router.get("/utilisation", response_model=UtilisationReportResponse, summary="Staff utilisation report")
async def utilisation_report(
    request: Request,
    date_from: date = Query(...),
    date_to: date = Query(...),
    staff_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = StaffService(db)
    data = await svc.calculate_utilisation(org_id, date_from, date_to, staff_id=staff_id)
    return UtilisationReportResponse(
        staff=data, date_from=date_from.isoformat(), date_to=date_to.isoformat(),
    )


@router.get("/labour-costs", response_model=LabourCostResponse, summary="Labour cost report")
async def labour_cost_report(
    request: Request,
    date_from: date = Query(...),
    date_to: date = Query(...),
    staff_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = StaffService(db)
    data = await svc.get_labour_costs(org_id, date_from, date_to, staff_id=staff_id)
    return LabourCostResponse(**data)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.get("", response_model=StaffMemberListResponse, summary="List staff members")
async def list_staff(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    role_type: str | None = Query(None),
    is_active: bool | None = Query(None),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = StaffService(db)
    staff_list, total = await svc.list_staff(
        org_id, page=page, page_size=page_size,
        role_type=role_type, is_active=is_active,
    )
    # Resolve reporting_to names in bulk
    manager_ids = {s.reporting_to for s in staff_list if s.reporting_to}
    manager_names: dict[UUID, str] = {}
    if manager_ids:
        result = await db.execute(
            select(StaffMember.id, StaffMember.first_name, StaffMember.last_name)
            .where(StaffMember.id.in_(manager_ids))
        )
        for row in result:
            manager_names[row[0]] = f"{row[1] or ''} {row[2] or ''}".strip()

    resp_staff = []
    for s in staff_list:
        data = StaffMemberResponse.model_validate(s).model_dump()
        if s.reporting_to and s.reporting_to in manager_names:
            data["reporting_to_name"] = manager_names[s.reporting_to]
        resp_staff.append(StaffMemberResponse(**data))

    return StaffMemberListResponse(
        staff=resp_staff, total=total, page=page, page_size=page_size,
    )


@router.post("", response_model=StaffMemberResponse, status_code=201, summary="Create staff member")
async def create_staff(
    payload: StaffMemberCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = StaffService(db)
    try:
        staff = await svc.create_staff(org_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await db.flush()
    await db.refresh(staff)
    enriched = await _enrich_reporting_to(db, staff)
    return StaffMemberResponse(**enriched)


@router.get("/{staff_id}", response_model=StaffMemberResponse, summary="Get staff member")
async def get_staff(
    staff_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = StaffService(db)
    staff = await svc.get_staff(org_id, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")
    enriched = await _enrich_reporting_to(db, staff)
    return StaffMemberResponse(**enriched)


@router.put("/{staff_id}", response_model=StaffMemberResponse, summary="Update staff member")
async def update_staff(
    staff_id: UUID,
    payload: StaffMemberUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = StaffService(db)
    try:
        staff = await svc.update_staff(org_id, staff_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")
    await db.flush()
    await db.refresh(staff)
    enriched = await _enrich_reporting_to(db, staff)
    return StaffMemberResponse(**enriched)


@router.delete("/{staff_id}", status_code=200, summary="Deactivate staff member")
async def deactivate_staff(
    staff_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = StaffService(db)
    staff = await svc.get_staff(org_id, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")
    staff.is_active = False
    await db.flush()
    return {"message": "Staff member deactivated", "id": str(staff_id)}


@router.post("/{staff_id}/activate", response_model=StaffMemberResponse, summary="Reactivate staff member")
async def activate_staff(
    staff_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = StaffService(db)
    staff = await svc.get_staff(org_id, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")
    if staff.is_active:
        raise HTTPException(status_code=400, detail="Staff member is already active")
    staff.is_active = True
    await db.flush()
    await db.refresh(staff)
    enriched = await _enrich_reporting_to(db, staff)
    return StaffMemberResponse(**enriched)


@router.post("/{staff_id}/create-account", summary="Create org user account for staff member")
async def create_staff_account(
    staff_id: UUID,
    payload: CreateStaffAccountRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a user account (org_admin) linked to this staff member.

    Requires the staff member to have an email address and not already
    have a linked user account.
    """
    org_id = _get_org_id(request)
    svc = StaffService(db)
    staff = await svc.get_staff(org_id, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")
    if staff.user_id is not None:
        raise HTTPException(status_code=400, detail="Staff member already has a user account")
    if not staff.email:
        raise HTTPException(status_code=400, detail="Staff member must have an email address to create an account")

    # Check email not already taken
    from app.modules.auth.models import User
    existing = (await db.execute(
        select(User).where(User.email == staff.email)
    )).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=400, detail="A user with this email already exists")

    # Create user with password
    from app.modules.auth.password import hash_password
    new_user = User(
        org_id=org_id,
        email=staff.email,
        password_hash=hash_password(payload.password),
        role="org_admin",
        is_active=True,
        is_email_verified=True,
    )
    db.add(new_user)
    await db.flush()

    # Link staff member to user
    staff.user_id = new_user.id
    await db.flush()
    await db.refresh(staff)

    enriched = await _enrich_reporting_to(db, staff)
    return {
        "message": "User account created successfully",
        "user_id": str(new_user.id),
        "email": new_user.email,
        "staff": StaffMemberResponse(**enriched),
    }


# ---------------------------------------------------------------------------
# Location assignment
# ---------------------------------------------------------------------------

@router.post(
    "/{staff_id}/assign-location",
    response_model=LocationAssignmentResponse,
    status_code=201,
    summary="Assign staff to location",
)
async def assign_to_location(
    staff_id: UUID,
    payload: AssignToLocationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = StaffService(db)
    try:
        assignment = await svc.assign_to_location(org_id, staff_id, payload.location_id)
        await db.flush()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return LocationAssignmentResponse.model_validate(assignment)


@router.delete(
    "/{staff_id}/locations/{location_id}",
    status_code=204,
    summary="Remove staff from location",
)
async def remove_from_location(
    staff_id: UUID,
    location_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = StaffService(db)
    removed = await svc.remove_from_location(org_id, staff_id, location_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Assignment not found")
