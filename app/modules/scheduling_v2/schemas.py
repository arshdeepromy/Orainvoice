"""Pydantic v2 schemas for scheduling CRUD and conflict detection.

**Validates: Requirement 18 — Scheduling Module**
"""

from __future__ import annotations

from datetime import datetime, time
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
