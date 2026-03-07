"""Recurring invoices API router — schedule CRUD and dashboard.

Endpoints (all under /api/v2/recurring):
- GET    /              — list recurring schedules
- POST   /              — create a recurring schedule
- GET    /dashboard     — dashboard summary
- GET    /{schedule_id} — get a single schedule
- PUT    /{schedule_id} — update a schedule
- DELETE /{schedule_id} — cancel a schedule

**Validates: Recurring Module**
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.recurring_invoices.schemas import (
    RecurringDashboardResponse,
    RecurringScheduleCreate,
    RecurringScheduleListResponse,
    RecurringScheduleResponse,
    RecurringScheduleUpdate,
)
from app.modules.recurring_invoices.service import RecurringService

router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


@router.get("/", response_model=RecurringScheduleListResponse, summary="List recurring schedules")
async def list_schedules(
    request: Request,
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = RecurringService(db)
    schedules, total = await svc.list_schedules(
        org_id, status=status, limit=limit, offset=offset,
    )
    return RecurringScheduleListResponse(
        schedules=[RecurringScheduleResponse.model_validate(s) for s in schedules],
        total=total,
    )


@router.post("/", response_model=RecurringScheduleResponse, status_code=201, summary="Create recurring schedule")
async def create_schedule(
    payload: RecurringScheduleCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = RecurringService(db)
    schedule = await svc.create_schedule(org_id, payload)
    return RecurringScheduleResponse.model_validate(schedule)


@router.get("/dashboard", response_model=RecurringDashboardResponse, summary="Recurring dashboard")
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = RecurringService(db)
    data = await svc.get_dashboard(org_id)
    return RecurringDashboardResponse(**data)


@router.get("/{schedule_id}", response_model=RecurringScheduleResponse, summary="Get recurring schedule")
async def get_schedule(
    schedule_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = RecurringService(db)
    schedule = await svc.get_schedule(org_id, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Recurring schedule not found")
    return RecurringScheduleResponse.model_validate(schedule)


@router.put("/{schedule_id}", response_model=RecurringScheduleResponse, summary="Update recurring schedule")
async def update_schedule(
    schedule_id: UUID,
    payload: RecurringScheduleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = RecurringService(db)
    schedule = await svc.update_schedule(org_id, schedule_id, payload)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Recurring schedule not found")
    return RecurringScheduleResponse.model_validate(schedule)


@router.delete("/{schedule_id}", status_code=204, summary="Cancel recurring schedule")
async def delete_schedule(
    schedule_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = RecurringService(db)
    deleted = await svc.delete_schedule(org_id, schedule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Recurring schedule not found")
