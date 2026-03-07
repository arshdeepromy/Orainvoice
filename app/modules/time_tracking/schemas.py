"""Pydantic schemas for Employee Time Tracking module.

Requirements: 65.1, 65.2, 65.3
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Timer start / stop
# ---------------------------------------------------------------------------


class TimerStartRequest(BaseModel):
    """Request body for POST /api/v1/job-cards/{id}/timer/start."""

    notes: str | None = None


class TimerStopRequest(BaseModel):
    """Request body for POST /api/v1/job-cards/{id}/timer/stop."""

    notes: str | None = None


class TimeEntryResponse(BaseModel):
    """Response schema for a single time entry."""

    id: uuid.UUID
    job_card_id: uuid.UUID | None = None
    user_id: uuid.UUID
    started_at: datetime
    stopped_at: datetime | None = None
    duration_minutes: int | None = None
    hourly_rate: Decimal | None = None
    notes: str | None = None
    created_at: datetime


class TimerStartResponse(BaseModel):
    """Response after starting a timer."""

    time_entry: TimeEntryResponse
    message: str


class TimerStopResponse(BaseModel):
    """Response after stopping a timer."""

    time_entry: TimeEntryResponse
    message: str


# ---------------------------------------------------------------------------
# Add time as labour line item
# ---------------------------------------------------------------------------


class AddTimeAsLabourRequest(BaseModel):
    """Request body for adding a time entry as a Labour line item."""

    time_entry_id: uuid.UUID
    labour_rate_id: uuid.UUID | None = None
    hourly_rate_override: Decimal | None = Field(default=None, ge=0)
    description: str | None = None


class AddTimeAsLabourResponse(BaseModel):
    """Response after adding time as a labour line item."""

    job_card_item_id: uuid.UUID
    hours: Decimal
    hourly_rate: Decimal
    line_total: Decimal
    message: str


# ---------------------------------------------------------------------------
# Employee hours report
# ---------------------------------------------------------------------------


class EmployeeHoursEntry(BaseModel):
    """A single row in the employee hours report."""

    user_id: uuid.UUID
    email: str | None = None
    total_minutes: int
    total_hours: Decimal
    entry_count: int


class EmployeeHoursReportResponse(BaseModel):
    """Response for the employee hours report."""

    entries: list[EmployeeHoursEntry]
    start_date: datetime
    end_date: datetime
    total_hours: Decimal
