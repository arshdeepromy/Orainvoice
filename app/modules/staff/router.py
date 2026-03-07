"""Staff management API router.

Endpoints:
- GET    /api/v2/staff                          — list (paginated/filterable)
- POST   /api/v2/staff                          — create
- GET    /api/v2/staff/{id}                     — get
- PUT    /api/v2/staff/{id}                     — update
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
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.staff.schemas import (
    AssignToLocationRequest,
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
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = StaffService(db)
    staff, total = await svc.list_staff(
        org_id, page=page, page_size=page_size,
        role_type=role_type, is_active=is_active,
    )
    return StaffMemberListResponse(
        staff=[StaffMemberResponse.model_validate(s) for s in staff],
        total=total, page=page, page_size=page_size,
    )


@router.post("", response_model=StaffMemberResponse, status_code=201, summary="Create staff member")
async def create_staff(
    payload: StaffMemberCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = StaffService(db)
    staff = await svc.create_staff(org_id, payload)
    return StaffMemberResponse.model_validate(staff)


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
    return StaffMemberResponse.model_validate(staff)


@router.put("/{staff_id}", response_model=StaffMemberResponse, summary="Update staff member")
async def update_staff(
    staff_id: UUID,
    payload: StaffMemberUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = StaffService(db)
    staff = await svc.update_staff(org_id, staff_id, payload)
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")
    return StaffMemberResponse.model_validate(staff)


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
