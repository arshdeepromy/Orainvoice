"""Pydantic schemas for Booking module.

Requirements: 64.1, 64.2, 64.3, 64.4
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class BookingStatus(str, Enum):
    scheduled = "scheduled"
    confirmed = "confirmed"
    completed = "completed"
    cancelled = "cancelled"
    no_show = "no_show"


class CalendarView(str, Enum):
    day = "day"
    week = "week"
    month = "month"


class BookingCreate(BaseModel):
    """Request body for POST /api/v1/bookings."""

    customer_id: uuid.UUID
    vehicle_rego: str | None = None
    branch_id: uuid.UUID | None = None
    service_type: str | None = None
    scheduled_at: datetime
    duration_minutes: int = Field(default=60, ge=15, le=480)
    notes: str | None = None
    assigned_to: uuid.UUID | None = None
    send_confirmation: bool = False


class BookingUpdate(BaseModel):
    """Request body for PUT /api/v1/bookings/{id}."""

    customer_id: uuid.UUID | None = None
    vehicle_rego: str | None = None
    branch_id: uuid.UUID | None = None
    service_type: str | None = None
    scheduled_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=15, le=480)
    notes: str | None = None
    status: BookingStatus | None = None
    assigned_to: uuid.UUID | None = None


class BookingResponse(BaseModel):
    """Response schema for a booking."""

    id: uuid.UUID
    org_id: uuid.UUID
    customer_id: uuid.UUID | None = None
    customer_name: str | None = None
    vehicle_rego: str | None = None
    branch_id: uuid.UUID | None = None
    service_type: str | None = None
    scheduled_at: datetime
    duration_minutes: int
    notes: str | None = None
    status: str
    reminder_sent: bool
    assigned_to: uuid.UUID | None = None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class BookingCreateResponse(BaseModel):
    """Wrapper response for booking creation."""

    booking: BookingResponse
    message: str
    confirmation_sent: bool = False


class BookingSearchResult(BaseModel):
    """Lightweight booking for list/calendar views."""

    id: uuid.UUID
    customer_name: str | None = None
    vehicle_rego: str | None = None
    service_type: str | None = None
    scheduled_at: datetime
    duration_minutes: int
    status: str


class BookingListResponse(BaseModel):
    """Paginated list of bookings with calendar view support."""

    bookings: list[BookingSearchResult]
    total: int
    view: str
    start_date: datetime
    end_date: datetime


class BookingConvertTarget(str, Enum):
    """Allowed conversion targets for a booking."""

    job_card = "job_card"
    invoice = "invoice"


class BookingConvertResponse(BaseModel):
    """Response after converting a booking to a job card or draft invoice.

    Requirements: 64.5
    """

    booking_id: uuid.UUID
    target: str
    created_id: uuid.UUID
    message: str

