"""Pydantic v2 schemas for scheduling CRUD and conflict detection.

**Validates: Requirement 18 — Scheduling Module**
"""

from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, Field


class ScheduleEntryCreate(BaseModel):
    staff_id: UUID | None = None
    job_id: UUID | None = None
    booking_id: UUID | None = None
    location_id: UUID | None = None
    title: str | None = None
    description: str | None = None
    start_time: datetime
    end_time: datetime
    entry_type: str = Field(default="job", pattern="^(job|booking|break|other|leave)$")
    notes: str | None = None
    recurrence: str = Field(default="none", pattern="^(none|daily|weekly|fortnightly)$")


class ScheduleEntryUpdate(BaseModel):
    staff_id: UUID | None = None
    job_id: UUID | None = None
    booking_id: UUID | None = None
    location_id: UUID | None = None
    title: str | None = None
    description: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    entry_type: str | None = Field(None, pattern="^(job|booking|break|other|leave)$")
    status: str | None = Field(None, pattern="^(scheduled|completed|cancelled)$")
    notes: str | None = None


class RescheduleRequest(BaseModel):
    start_time: datetime
    end_time: datetime


class ScheduleEntryResponse(BaseModel):
    id: UUID
    org_id: UUID
    staff_id: UUID | None = None
    job_id: UUID | None = None
    booking_id: UUID | None = None
    location_id: UUID | None = None
    title: str | None = None
    description: str | None = None
    start_time: datetime
    end_time: datetime
    entry_type: str
    status: str
    notes: str | None = None
    recurrence_group_id: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ScheduleEntryListResponse(BaseModel):
    entries: list[ScheduleEntryResponse]
    total: int


class ConflictInfo(BaseModel):
    entry_id: UUID
    title: str | None = None
    start_time: datetime
    end_time: datetime
    entry_type: str


class ConflictCheckResponse(BaseModel):
    has_conflicts: bool
    conflicts: list[ConflictInfo] = Field(default_factory=list)


# ------------------------------------------------------------------
# Shift Templates (Req 57)
# ------------------------------------------------------------------


class ShiftTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="HH:MM format")
    end_time: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="HH:MM format")
    entry_type: str = Field(default="job", pattern="^(job|booking|break|other|leave)$")


class ShiftTemplateResponse(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    start_time: time
    end_time: time
    entry_type: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ShiftTemplateListResponse(BaseModel):
    templates: list[ShiftTemplateResponse]
    total: int


# ------------------------------------------------------------------
# Bulk + Copy-Week schemas (Roster Grid Editor — Workstream A)
# ------------------------------------------------------------------


class BulkScheduleEntryCreateRequest(BaseModel):
    """Request body for ``POST /api/v2/schedule/bulk``.

    Validates Requirement 11.1 / 11.2: between 1 and 200 entries per
    request. Pydantic enforces both bounds at the schema level so the
    service layer never sees an out-of-range list.
    """

    entries: list[ScheduleEntryCreate] = Field(
        ..., min_length=1, max_length=200,
    )


class BulkConflictItem(BaseModel):
    """A single per-entry conflict result returned in the bulk response.

    The ``index`` corresponds to the entry's position in the original
    ``entries`` array; ``attempted`` is the original create payload
    (so the frontend can replay or surface it to the user); and
    ``conflicts_with`` is the list of existing entries that overlap
    the attempted entry's time window.
    """

    index: int
    attempted: ScheduleEntryCreate
    conflicts_with: list[ScheduleEntryResponse] = Field(default_factory=list)


class BulkScheduleEntryResponse(BaseModel):
    """Response body for both ``/bulk`` and ``/copy-week``.

    Per R11.4: ``len(created) + len(conflicts) == len(entries)``.
    """

    created: list[ScheduleEntryResponse] = Field(default_factory=list)
    conflicts: list[BulkConflictItem] = Field(default_factory=list)


class CopyWeekRequest(BaseModel):
    """Request body for ``POST /api/v2/schedule/copy-week``.

    The service refuses 422 when ``target_week_start - source_week_start``
    is not a non-zero multiple of 7 days; ``overwrite_existing`` toggles
    the destructive overwrite path (R8.9).
    """

    source_week_start: date
    target_week_start: date
    overwrite_existing: bool = False
