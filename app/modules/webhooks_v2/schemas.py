"""Pydantic v2 schemas for the outbound webhook management module.

**Validates: Requirement 47 — Webhook Management and Security**
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


VALID_EVENT_TYPES = [
    "invoice.created",
    "invoice.paid",
    "customer.created",
    "job.status_changed",
    "booking.created",
    "payment.received",
    "stock.low",
]


class WebhookCreate(BaseModel):
    target_url: str = Field(..., min_length=1, max_length=500)
    event_types: list[str] = Field(..., min_length=1)
    is_active: bool = True

    @field_validator("target_url")
    @classmethod
    def url_must_be_https(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("Webhook URL must use HTTPS")
        return v

    @field_validator("event_types")
    @classmethod
    def validate_event_types(cls, v: list[str]) -> list[str]:
        for et in v:
            if et not in VALID_EVENT_TYPES:
                raise ValueError(f"Invalid event type: {et}")
        return v


class WebhookUpdate(BaseModel):
    target_url: str | None = Field(None, min_length=1, max_length=500)
    event_types: list[str] | None = Field(None, min_length=1)
    is_active: bool | None = None

    @field_validator("target_url")
    @classmethod
    def url_must_be_https(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("https://"):
            raise ValueError("Webhook URL must use HTTPS")
        return v

    @field_validator("event_types")
    @classmethod
    def validate_event_types(cls, v: list[str] | None) -> list[str] | None:
        if v is not None:
            for et in v:
                if et not in VALID_EVENT_TYPES:
                    raise ValueError(f"Invalid event type: {et}")
        return v


class WebhookResponse(BaseModel):
    id: UUID
    org_id: UUID
    target_url: str
    event_types: list[str]
    is_active: bool
    consecutive_failures: int
    last_delivery_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DeliveryLogResponse(BaseModel):
    id: UUID
    webhook_id: UUID
    event_type: str
    payload: dict | None = None
    response_status: int | None = None
    response_time_ms: int | None = None
    retry_count: int
    status: str
    error_details: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class WebhookTestResponse(BaseModel):
    success: bool
    response_status: int | None = None
    response_time_ms: int | None = None
    error: str | None = None
