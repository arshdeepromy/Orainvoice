"""Scheduling API router.

Endpoints:
- GET    /api/v2/schedule              — list entries (date range, filters)
- POST   /api/v2/schedule              — create entry
- GET    /api/v2/schedule/{id}         — get entry
- PUT    /api/v2/schedule/{id}         — update entry
- PUT    /api/v2/schedule/{id}/reschedule — reschedule (move times)
- POST   /api/v2/schedule/bulk         — bulk-create entries (org_admin/salesperson)
- POST   /api/v2/schedule/copy-week    — copy a week of entries (org_admin/salesperson)

**Validates: Requirement 18 — Scheduling Module**
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.scheduling_v2.schemas import (
    BulkScheduleEntryCreateRequest,
    BulkScheduleEntryResponse,
    ConflictCheckResponse,
    ConflictInfo,
    CopyWeekRequest,
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


# ------------------------------------------------------------------
# Shift Templates (Req 57)
#
# IMPORTANT: these static-path routes MUST be registered BEFORE the
# dynamic ``/{entry_id}`` routes below — otherwise FastAPI matches
# ``GET /templates`` to ``GET /{entry_id}`` (registration order wins
# for same-method conflicts) and returns 422 because "templates" is
# not a valid UUID. Verified by reproducing the bug in dev: every
# call from the new Roster Grid Editor's `listTemplates()` returned
# 422 until this re-ordering landed.
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


@router.delete("/{entry_id}", status_code=204, summary="Delete schedule entry")
async def delete_entry(
    entry_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = SchedulingService(db)
    deleted = await svc.delete_entry(org_id, entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Schedule entry not found")


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
# Bulk + Copy-Week (Roster Grid Editor — Workstream A)
# ------------------------------------------------------------------


@router.post(
    "/bulk",
    response_model=BulkScheduleEntryResponse,
    summary="Bulk-create schedule entries (up to 200 per request)",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def bulk_create_entries(
    payload: BulkScheduleEntryCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create up to 200 schedule entries in a single transaction with
    per-entry SAVEPOINT rollback.

    Returns ``200`` with ``{ created, conflicts }``. Per-entry conflicts
    do not abort the batch — successful entries persist and the
    response lists the conflicting entries with their original index.

    **Validates: R11.1 — R11.5, R11.6, R11.9.**
    """
    org_id = _get_org_id(request)
    user_id_raw = getattr(request.state, "user_id", None)
    user_id = UUID(str(user_id_raw)) if user_id_raw else None

    svc = SchedulingService(db)
    try:
        created, conflicts = await svc.bulk_create(
            org_id, payload, user_id=user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return BulkScheduleEntryResponse(
        created=[ScheduleEntryResponse.model_validate(e) for e in created],
        conflicts=conflicts,
    )


@router.post(
    "/copy-week",
    response_model=BulkScheduleEntryResponse,
    summary="Copy a week of schedule entries (delta must be a non-zero multiple of 7 days)",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def copy_week_entries(
    payload: CopyWeekRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Copy every entry in the source 7-day window into the target
    7-day window with the times shifted by ``target - source`` days.

    Per R8.5 the copy is NOT recurring (``recurrence_group_id``
    forced to NULL); per R8.6 the copy's ``status`` is reset to
    ``'scheduled'``. ``overwrite_existing`` toggles destructive
    overwrite of overlapping target entries.

    **Validates: R8.3 — R8.9, R11.7, R11.8.**
    """
    org_id = _get_org_id(request)
    user_id_raw = getattr(request.state, "user_id", None)
    user_id = UUID(str(user_id_raw)) if user_id_raw else None

    svc = SchedulingService(db)
    try:
        created, conflicts = await svc.copy_week(
            org_id, payload, user_id=user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return BulkScheduleEntryResponse(
        created=[ScheduleEntryResponse.model_validate(e) for e in created],
        conflicts=conflicts,
    )
