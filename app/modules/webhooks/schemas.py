"""Pydantic schemas for the Webhooks module — outbound webhook CRUD.

Requirements: 70.1, 70.2, 70.3, 70.4
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, HttpUrl

# Supported webhook event types (Req 70.1)
WEBHOOK_EVENT_TYPES: list[str] = [
    "invoice.created",
    "invoice.paid",
    "invoice.overdue",
    "payment.received",
    "customer.created",
    "vehicle.added",
]


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class WebhookCreate(BaseModel):
    """POST /api/v1/webhooks request body.

    Requirements: 70.1
    """

    event_type: str = Field(
        ..., description="Event type to subscribe to"
    )
    url: str = Field(
        ..., max_length=500, description="Destination URL for webhook delivery"
    )
    secret: str = Field(
        ..., min_length=8, max_length=256, description="Shared secret for HMAC-SHA256 signing"
    )
    is_active: bool = Field(True, description="Whether the webhook is active")


class WebhookUpdate(BaseModel):
    """PUT /api/v1/webhooks/{webhook_id} request body.

    Requirements: 70.1
    """

    event_type: Optional[str] = Field(None, description="Event type")
    url: Optional[str] = Field(None, max_length=500, description="Destination URL")
    secret: Optional[str] = Field(
        None, min_length=8, max_length=256, description="New shared secret"
    )
    is_active: Optional[bool] = Field(None, description="Active state")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class WebhookResponse(BaseModel):
    """Single webhook in API responses.

    Requirements: 70.1
    """

    id: str = Field(..., description="Webhook UUID")
    org_id: str = Field(..., description="Organisation UUID")
    event_type: str = Field(..., description="Subscribed event type")
    url: str = Field(..., description="Destination URL")
    is_active: bool = Field(..., description="Whether webhook is active")
    created_at: str = Field(..., description="ISO 8601 creation timestamp")


class WebhookListResponse(BaseModel):
    """GET /api/v1/webhooks response."""

    webhooks: list[WebhookResponse] = Field(
        default_factory=list, description="Registered webhooks"
    )
    total: int = Field(0, description="Total count")


class WebhookDeliveryResponse(BaseModel):
    """Single webhook delivery attempt in API responses.

    Requirements: 70.4
    """

    id: str = Field(..., description="Delivery UUID")
    webhook_id: str = Field(..., description="Parent webhook UUID")
    event_type: str = Field(..., description="Event type")
    payload: dict[str, Any] = Field(default_factory=dict, description="JSON payload sent")
    response_status: Optional[int] = Field(None, description="HTTP response status code")
    retry_count: int = Field(0, description="Number of retries attempted")
    status: str = Field(..., description="Delivery status: pending, delivered, failed")
    created_at: str = Field(..., description="ISO 8601 creation timestamp")


class WebhookDeliveryListResponse(BaseModel):
    """GET /api/v1/webhooks/{webhook_id}/deliveries response."""

    deliveries: list[WebhookDeliveryResponse] = Field(
        default_factory=list, description="Delivery attempts"
    )
    total: int = Field(0, description="Total count")
