"""Pydantic v2 schemas for scheduling CRUD and conflict detection.

**Validates: Requirement 18 — Scheduling Module**
"""

from __future__ import annotations

from datetime import datetime
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
    entry_type: str = Field(default="job", pattern="^(job|booking|break|other)$")
    notes: str | None = None


class ScheduleEntryUpdate(BaseModel):
    staff_id: UUID | None = None
    job_id: UUID | None = None
    booking_id: UUID | None = None
    location_id: UUID | None = None
    title: str | None = None
    description: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    entry_type: str | None = Field(None, pattern="^(job|booking|break|other)$")
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
