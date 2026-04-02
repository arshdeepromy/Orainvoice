"""Staff Scheduling router — endpoints for per-branch shift management.

Requirements: 19.1, 19.2, 19.3, 19.4, 19.5
"""

from __future__ import annotations

import uuid
from datetime import date, time
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.scheduling.service import (
    OverlapError,
    create_schedule_entry,
    delete_schedule_entry,
    list_schedule_entries,
    update_schedule_entry,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class CreateScheduleRequest(BaseModel):
    """POST /scheduling — create a new schedule entry."""

    branch_id: uuid.UUID = Field(..., description="Target branch UUID")
    user_id: uuid.UUID = Field(..., description="User UUID to schedule")
    shift_date: date = Field(..., description="Date of the shift")
    start_time: time = Field(..., description="Shift start time")
    end_time: time = Field(..., description="Shift end time")
    notes: Optional[str] = Field(None, max_length=1000, description="Optional notes")


class UpdateScheduleRequest(BaseModel):
    """PUT /scheduling/{id} — update a schedule entry."""

    branch_id: Optional[uuid.UUID] = Field(None, description="New branch UUID")
    user_id: Optional[uuid.UUID] = Field(None, description="New user UUID")
    shift_date: Optional[date] = Field(None, description="New shift date")
    start_time: Optional[time] = Field(None, description="New start time")
    end_time: Optional[time] = Field(None, description="New end time")
    notes: Optional[str] = Field(None, max_length=1000, description="Updated notes")


class ScheduleResponse(BaseModel):
    """Single schedule entry response."""

    id: str
    org_id: str
    branch_id: str
    user_id: str
    shift_date: str
    start_time: str
    end_time: str
    notes: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ScheduleListResponse(BaseModel):
    """List of schedule entries."""

    entries: list[ScheduleResponse]


class ScheduleActionResponse(BaseModel):
    """Response for schedule lifecycle actions."""

    message: str
    entry: ScheduleResponse


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _extract_org_context(request: Request) -> uuid.UUID | None:
    """Extract org_id from request state."""
    org_id = getattr(request.state, "org_id", None)
    try:
        return uuid.UUID(org_id) if org_id else None
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=ScheduleActionResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error (user not assigned to branch)"},
        401: {"description": "Authentication required"},
        403: {"description": "Role required"},
        409: {"description": "Schedule overlap"},
    },
    summary="Create a schedule entry",
    dependencies=[require_role("org_admin")],
)
async def create_schedule_endpoint(
    payload: CreateScheduleRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new staff schedule entry with overlap and assignment validation.

    Requirements: 19.1, 19.2, 19.5
    """
    org_uuid = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await create_schedule_entry(
            db,
            org_id=org_uuid,
            branch_id=payload.branch_id,
            user_id=payload.user_id,
            shift_date=payload.shift_date,
            start_time=payload.start_time,
            end_time=payload.end_time,
            notes=payload.notes,
        )
    except OverlapError as exc:
        return JSONResponse(status_code=409, content={"detail": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return ScheduleActionResponse(
        message="Schedule entry created",
        entry=ScheduleResponse(**result),
    )


@router.get(
    "",
    response_model=ScheduleListResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Role required"},
    },
    summary="List schedule entries",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_schedule_endpoint(
    request: Request,
    branch_id: uuid.UUID | None = Query(None, description="Filter by branch"),
    start_date: date | None = Query(None, description="Start of date range"),
    end_date: date | None = Query(None, description="End of date range"),
    db: AsyncSession = Depends(get_db_session),
):
    """List schedule entries with optional branch and date range filtering.

    Requirements: 19.3, 19.4
    """
    org_uuid = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    date_range = None
    if start_date and end_date:
        date_range = (start_date, end_date)

    results = await list_schedule_entries(
        db,
        org_id=org_uuid,
        branch_id=branch_id,
        date_range=date_range,
    )

    return ScheduleListResponse(
        entries=[ScheduleResponse(**e) for e in results],
    )


@router.put(
    "/{entry_id}",
    response_model=ScheduleActionResponse,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Role required"},
        404: {"description": "Entry not found"},
        409: {"description": "Schedule overlap"},
    },
    summary="Update a schedule entry",
    dependencies=[require_role("org_admin")],
)
async def update_schedule_endpoint(
    entry_id: str,
    payload: UpdateScheduleRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update an existing schedule entry with re-validation.

    Requirements: 19.1, 19.2, 19.5
    """
    org_uuid = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        entry_uuid = uuid.UUID(entry_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid entry ID"})

    # Build update fields dict, excluding None values
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}

    try:
        result = await update_schedule_entry(
            db,
            org_id=org_uuid,
            entry_id=entry_uuid,
            **fields,
        )
    except OverlapError as exc:
        return JSONResponse(status_code=409, content={"detail": str(exc)})
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "not found" in detail.lower() else 400
        return JSONResponse(status_code=status_code, content={"detail": detail})

    return ScheduleActionResponse(
        message="Schedule entry updated",
        entry=ScheduleResponse(**result),
    )


@router.delete(
    "/{entry_id}",
    response_model=ScheduleActionResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Role required"},
        404: {"description": "Entry not found"},
    },
    summary="Delete a schedule entry",
    dependencies=[require_role("org_admin")],
)
async def delete_schedule_endpoint(
    entry_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Delete a schedule entry.

    Requirements: 19.1
    """
    org_uuid = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        entry_uuid = uuid.UUID(entry_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid entry ID"})

    try:
        result = await delete_schedule_entry(
            db,
            org_id=org_uuid,
            entry_id=entry_uuid,
        )
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    return ScheduleActionResponse(
        message="Schedule entry deleted",
        entry=ScheduleResponse(**result),
    )
