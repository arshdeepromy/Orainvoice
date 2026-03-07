"""Pydantic v2 schemas for bookings CRUD and public booking endpoints.

**Validates: Requirement 19 — Booking Module**
"""

from __future__ import annotations

from datetime import datetime, date
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class BookingCreate(BaseModel):
    customer_name: str = Field(..., min_length=1, max_length=255)
    customer_email: str | None = None
    customer_phone: str | None = None
    staff_id: UUID | None = None
    service_type: str | None = None
    start_time: datetime
    end_time: datetime
    notes: str | None = None


class BookingUpdate(BaseModel):
    customer_name: str | None = None
    customer_email: str | None = None
    customer_phone: str | None = None
    staff_id: UUID | None = None
    service_type: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    status: str | None = Field(None, pattern="^(pending|confirmed|cancelled|completed)$")
    notes: str | None = None


class BookingResponse(BaseModel):
    id: UUID
    org_id: UUID
    customer_name: str
    customer_email: str | None = None
    customer_phone: str | None = None
    staff_id: UUID | None = None
    service_type: str | None = None
    start_time: datetime
    end_time: datetime
    status: str
    notes: str | None = None
    confirmation_token: str | None = None
    converted_job_id: UUID | None = None
    converted_invoice_id: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BookingListResponse(BaseModel):
    bookings: list[BookingResponse]
    total: int


class PublicBookingSubmit(BaseModel):
    customer_name: str = Field(..., min_length=1, max_length=255)
    customer_email: str | None = None
    customer_phone: str | None = None
    service_type: str | None = None
    start_time: datetime
    notes: str | None = None


class TimeSlot(BaseModel):
    start_time: datetime
    end_time: datetime
    available: bool = True


class AvailableSlotsResponse(BaseModel):
    date: date
    slots: list[TimeSlot]


class BookingRuleResponse(BaseModel):
    id: UUID
    org_id: UUID
    service_type: str | None = None
    duration_minutes: int
    min_advance_hours: int
    max_advance_days: int
    buffer_minutes: int
    available_days: list
    available_hours: dict
    max_per_day: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BookingRuleUpdate(BaseModel):
    service_type: str | None = None
    duration_minutes: int | None = None
    min_advance_hours: int | None = None
    max_advance_days: int | None = None
    buffer_minutes: int | None = None
    available_days: list | None = None
    available_hours: dict | None = None
    max_per_day: int | None = None


class PublicBookingPageData(BaseModel):
    org_name: str
    org_slug: str
    logo_url: str | None = None
    primary_colour: str | None = None
    services: list[str] = Field(default_factory=list)
    booking_rules: BookingRuleResponse | None = None
