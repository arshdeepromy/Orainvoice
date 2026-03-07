"""Pydantic v2 schemas for time tracking CRUD, timer, and timesheet.

**Validates: Requirement 13.1, 13.2, 13.3, 13.4, 13.5, 13.6**
"""

from __future__ import annotations

from datetime import datetime, date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class TimeEntryCreate(BaseModel):
    """Manual time entry creation."""
    job_id: UUID | None = None
    project_id: UUID | None = None
    staff_id: UUID | None = None
    description: str | None = None
    start_time: datetime
    end_time: datetime | None = None
    duration_minutes: int | None = None
    is_billable: bool = True
    hourly_rate: Decimal | None = None


class TimeEntryUpdate(BaseModel):
    """Update an existing time entry."""
    job_id: UUID | None = None
    project_id: UUID | None = None
    staff_id: UUID | None = None
    description: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_minutes: int | None = None
    is_billable: bool | None = None
    hourly_rate: Decimal | None = None


class TimeEntryResponse(BaseModel):
    id: UUID
    org_id: UUID
    user_id: UUID
    staff_id: UUID | None = None
    job_id: UUID | None = None
    project_id: UUID | None = None
    description: str | None = None
    start_time: datetime
    end_time: datetime | None = None
    duration_minutes: int | None = None
    is_billable: bool
    hourly_rate: Decimal | None = None
    is_invoiced: bool
    invoice_id: UUID | None = None
    is_timer_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TimeEntryListResponse(BaseModel):
    entries: list[TimeEntryResponse]
    total: int
    page: int = 1
    page_size: int = 50


class TimerStartRequest(BaseModel):
    """Start a running timer."""
    job_id: UUID | None = None
    project_id: UUID | None = None
    staff_id: UUID | None = None
    description: str | None = None
    is_billable: bool = True
    hourly_rate: Decimal | None = None


class TimerStopResponse(BaseModel):
    entry: TimeEntryResponse
    duration_minutes: int


class TimesheetDay(BaseModel):
    date: date
    entries: list[TimeEntryResponse]
    total_minutes: int
    billable_minutes: int


class TimesheetResponse(BaseModel):
    week_start: date
    week_end: date
    days: list[TimesheetDay]
    weekly_total_minutes: int
    weekly_billable_minutes: int


class AddToInvoiceRequest(BaseModel):
    """Add time entries to an invoice as Labour line items."""
    time_entry_ids: list[UUID] = Field(..., min_length=1)
    invoice_id: UUID


class AddToInvoiceResponse(BaseModel):
    invoice_id: UUID
    line_items_created: int
    total_hours: Decimal
    total_amount: Decimal
    entries_marked: int
