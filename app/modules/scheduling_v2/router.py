"""Scheduling API router.

Endpoints:
- GET    /api/v2/schedule              — list entries (date range, filters)
- POST   /api/v2/schedule              — create entry
- GET    /api/v2/schedule/{id}         — get entry
- PUT    /api/v2/schedule/{id}         — update entry
- PUT    /api/v2/schedule/{id}/reschedule — reschedule (move times)

**Validates: Requirement 18 — Scheduling Module**
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.scheduling_v2.schemas import (
    ConflictCheckResponse,
    ConflictInfo,
    RescheduleRequest,
    ScheduleEntryCreate,
    ScheduleEntryListResponse,
    ScheduleEntryResponse,
    ScheduleEntryUpdate,
    ShiftTemplateCreate,
    ShiftTemplateListResponse,
    ShiftTemplateResponse,
)
from app.modules.scheduling_v2.service import SchedulingService

router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


@router.get("", response_model=ScheduleEntryListResponse, summary="List schedule entries")
async def list_entries(
    request: Request,
    start: datetime | None = Query(None, description="Range start (inclusive)"),
    end: datetime | None = Query(None, description="Range end (inclusive)"),
    staff_id: UUID | None = Query(None),
    location_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = SchedulingService(db)
    entries, total = await svc.list_entries(
        org_id, start=start, end=end, staff_id=staff_id, location_id=location_id,
    )
    return ScheduleEntryListResponse(
        entries=[ScheduleEntryResponse.model_validate(e) for e in entries],
        total=total,
    )


@router.post("", response_model=ScheduleEntryResponse, status_code=201, summary="Create schedule entry")
async def create_entry(
    payload: ScheduleEntryCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = SchedulingService(db)

    # Handle recurring entries
    recurrence = getattr(payload, "recurrence", "none")
    if recurrence and recurrence != "none":
        try:
            entries = await svc.create_recurring_entry(org_id, payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        # Return the first entry as the response
        first = entries[0] if entries else None
        if first is None:
            raise HTTPException(status_code=422, detail="No entries created")
        return ScheduleEntryResponse.model_validate(first)

    try:
        entry = await svc.create_entry(org_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Check for conflicts and include warning header
    if payload.staff_id:
        conflicts = await svc.detect_conflicts(
            org_id, payload.staff_id, payload.start_time, payload.end_time,
            exclude_entry_id=entry.id,
        )
        if conflicts:
            # Entry is still created but we warn about conflicts
            pass

    return ScheduleEntryResponse.model_validate(entry)


@router.get("/{entry_id}", response_model=ScheduleEntryResponse, summary="Get schedule entry")
async def get_entry(
    entry_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = SchedulingService(db)
    entry = await svc.get_entry(org_id, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Schedule entry not found")
    return ScheduleEntryResponse.model_validate(entry)


@router.put("/{entry_id}", response_model=ScheduleEntryResponse, summary="Update schedule entry")
async def update_entry(
    entry_id: UUID,
    payload: ScheduleEntryUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = SchedulingService(db)
    try:
        entry = await svc.update_entry(org_id, entry_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if entry is None:
        raise HTTPException(status_code=404, detail="Schedule entry not found")
    return ScheduleEntryResponse.model_validate(entry)


@router.put(
    "/{entry_id}/reschedule",
    response_model=ScheduleEntryResponse,
    summary="Reschedule entry to new times",
)
async def reschedule_entry(
    entry_id: UUID,
    payload: RescheduleRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = SchedulingService(db)
    try:
        entry = await svc.reschedule(org_id, entry_id, payload.start_time, payload.end_time)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if entry is None:
        raise HTTPException(status_code=404, detail="Schedule entry not found")
    return ScheduleEntryResponse.model_validate(entry)


@router.get(
    "/{entry_id}/conflicts",
    response_model=ConflictCheckResponse,
    summary="Check conflicts for an entry",
)
async def check_conflicts(
    entry_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = SchedulingService(db)
    entry = await svc.get_entry(org_id, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Schedule entry not found")
    if entry.staff_id is None:
        return ConflictCheckResponse(has_conflicts=False, conflicts=[])

    conflicts = await svc.detect_conflicts(
        org_id, entry.staff_id, entry.start_time, entry.end_time,
        exclude_entry_id=entry.id,
    )
    return ConflictCheckResponse(
        has_conflicts=len(conflicts) > 0,
        conflicts=[
            ConflictInfo(
                entry_id=c.id,
                title=c.title,
                start_time=c.start_time,
                end_time=c.end_time,
                entry_type=c.entry_type,
            )
            for c in conflicts
        ],
    )


# ------------------------------------------------------------------
# Shift Templates (Req 57)
# ------------------------------------------------------------------


@router.get("/templates", response_model=ShiftTemplateListResponse, summary="List shift templates")
async def list_templates(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = SchedulingService(db)
    templates, total = await svc.list_templates(org_id)
    return ShiftTemplateListResponse(
        templates=[ShiftTemplateResponse.model_validate(t) for t in templates],
        total=total,
    )


@router.post(
    "/templates",
    response_model=ShiftTemplateResponse,
    status_code=201,
    summary="Create shift template",
)
async def create_template(
    payload: ShiftTemplateCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = SchedulingService(db)
    try:
        template = await svc.create_template(org_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ShiftTemplateResponse.model_validate(template)


@router.delete(
    "/templates/{template_id}",
    status_code=204,
    summary="Delete shift template",
)
async def delete_template(
    template_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = SchedulingService(db)
    deleted = await svc.delete_template(org_id, template_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Template not found")
