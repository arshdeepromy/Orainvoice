"""Pydantic schemas for the In-App Notifications module.

Requirements: 5
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Allowed severity values (validated by Literal type)
SEVERITY_VALUES = ("info", "success", "warning", "error")

# Allowed category values (validated in service, not DB CHECK)
CATEGORY_VALUES = (
    "email_failure",
    "sms_failure",
    "stock_alert",
    "quote_accepted",
    "quote_declined",
    "payment_received",
    "payment_failed",
    "invoice_overdue",
    "account_locked",
    "xero_sync_failed",
    "system",
)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class InboxItem(BaseModel):
    """A single notification in the inbox list.

    Requirements: 5
    """

    id: str = Field(..., description="Notification UUID")
    category: Literal[
        "email_failure",
        "sms_failure",
        "stock_alert",
        "quote_accepted",
        "quote_declined",
        "payment_received",
        "payment_failed",
        "invoice_overdue",
        "account_locked",
        "xero_sync_failed",
        "system",
    ] = Field(..., description="Notification category")
    severity: Literal["info", "success", "warning", "error"] = Field(
        ..., description="Notification severity level"
    )
    title: str = Field(..., description="Short notification title")
    body: str | None = Field(None, description="Notification body text")
    link_url: str | None = Field(None, description="Relative deep-link URL")
    entity_type: str | None = Field(None, description="Related entity type")
    entity_id: str | None = Field(None, description="Related entity UUID")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Category-specific structured data"
    )
    created_at: str = Field(..., description="ISO 8601 creation timestamp")
    is_read: bool = Field(False, description="Whether current user has read this")
    read_at: str | None = Field(None, description="ISO 8601 timestamp when read")


class InboxResponse(BaseModel):
    """GET /inbox response — paginated inbox list.

    Requirements: 5
    """

    items: list[InboxItem] = Field(
        default_factory=list, description="Inbox notification items"
    )
    total: int = Field(0, description="Total matching notifications")
    unread_count: int = Field(0, description="Total unread notifications")


class UnreadCountResponse(BaseModel):
    """GET /inbox/unread-count response — for bell badge polling.

    Requirements: 5
    """

    count: int = Field(0, description="Number of unread notifications")


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class MarkReadRequest(BaseModel):
    """POST /inbox/{id}/read request body.

    Currently empty — the notification ID comes from the URL path.
    Kept as a schema for forward compatibility (e.g. adding timestamp).

    Requirements: 5
    """

    pass


class DismissRequest(BaseModel):
    """POST /inbox/{id}/dismiss request body.

    Currently empty — the notification ID comes from the URL path.
    Kept as a schema for forward compatibility.

    Requirements: 5
    """

    pass
