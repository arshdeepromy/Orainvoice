"""Pydantic schemas for the SMS Chat module.

Requirements: 8.10
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Conversation schemas
# ---------------------------------------------------------------------------


class ConversationListItem(BaseModel):
    """Single conversation in the list response."""

    id: str = Field(..., description="Conversation UUID")
    org_id: str = Field(..., description="Organisation UUID")
    phone_number: str = Field(..., description="External party phone number")
    contact_name: Optional[str] = Field(None, description="Optional display name")
    last_message_at: datetime = Field(..., description="Timestamp of last message")
    last_message_preview: str = Field(..., description="Truncated last message (max 100 chars)")
    unread_count: int = Field(0, description="Number of unread inbound messages")
    is_archived: bool = Field(False, description="Whether conversation is archived")
    created_at: datetime = Field(..., description="Conversation creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


class ConversationListResponse(BaseModel):
    """GET /org/sms/conversations — paginated conversation list."""

    conversations: list[ConversationListItem] = Field(
        default_factory=list, description="List of conversations"
    )
    total: int = Field(0, description="Total number of conversations")
    limit: int = Field(20, description="Page size")
    offset: int = Field(0, description="Current offset")


# ---------------------------------------------------------------------------
# Message schemas
# ---------------------------------------------------------------------------


class MessageListItem(BaseModel):
    """Single message in the conversation thread."""

    id: str = Field(..., description="Message UUID")
    conversation_id: str = Field(..., description="Parent conversation UUID")
    direction: str = Field(..., description="'inbound' or 'outbound'")
    body: str = Field(..., description="Message text")
    from_number: str = Field(..., description="Sender phone number")
    to_number: str = Field(..., description="Recipient phone number")
    external_message_id: Optional[str] = Field(None, description="Connexus message ID")
    status: str = Field("pending", description="Delivery status")
    parts_count: int = Field(1, description="SMS part count")
    cost_nzd: Optional[Decimal] = Field(None, description="Cost in NZD (GST inclusive)")
    sent_at: Optional[datetime] = Field(None, description="When the message was sent")
    delivered_at: Optional[datetime] = Field(None, description="When delivery was confirmed")
    created_at: datetime = Field(..., description="Record creation timestamp")


class MessageListResponse(BaseModel):
    """GET /org/sms/conversations/{id}/messages — paginated message list."""

    messages: list[MessageListItem] = Field(
        default_factory=list, description="List of messages"
    )
    total: int = Field(0, description="Total number of messages")
    limit: int = Field(50, description="Page size")
    offset: int = Field(0, description="Current offset")


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class ReplyRequest(BaseModel):
    """POST /org/sms/conversations/{id}/reply — send a reply."""

    body: str = Field(..., min_length=1, max_length=1600, description="Message text to send")


class NewConversationRequest(BaseModel):
    """POST /org/sms/conversations/new — start a new conversation."""

    phone_number: str = Field(
        ..., min_length=1, max_length=20, description="Recipient phone number (international format)"
    )
    body: str = Field(..., min_length=1, max_length=1600, description="Initial message text")


# ---------------------------------------------------------------------------
# Webhook payload schemas (inbound from Connexus)
# ---------------------------------------------------------------------------


class IncomingWebhookPayload(BaseModel):
    """POST /api/webhooks/connexus/incoming — incoming SMS from Connexus."""

    messageId: str = Field(..., description="Connexus message identifier")
    # Using Field alias-style naming to match Connexus API payload keys
    sender: str = Field(..., alias="from", description="Sender phone number")
    to: str = Field(..., description="Recipient phone number (our sender ID)")
    body: str = Field(..., description="SMS message body")
    timestamp: Optional[str] = Field(None, description="Message timestamp from Connexus")

    model_config = {"populate_by_name": True}


class DeliveryStatusWebhookPayload(BaseModel):
    """POST /api/webhooks/connexus/status — delivery status update from Connexus."""

    messageId: str = Field(..., description="Connexus message identifier")
    status: int = Field(..., description="Connexus status code (1=DELIVRD, 2=UNDELIV, 4=QUEUED, 8=ACCEPTD, 16=UNDELIV)")


# ---------------------------------------------------------------------------
# Usage summary schema
# ---------------------------------------------------------------------------


class UsageSummaryResponse(BaseModel):
    """GET /org/sms/usage-summary — org SMS usage for current month."""

    total_sent: int = Field(0, description="Total outbound SMS sent this month")
    total_cost: Decimal = Field(Decimal("0.0000"), description="Total cost in NZD this month")
    included_quota: int = Field(0, description="SMS included in plan")
    package_credits_remaining: int = Field(0, description="Remaining purchased package credits")
    overage_count: int = Field(0, description="SMS sent beyond effective quota")
    overage_charge: Decimal = Field(Decimal("0.0000"), description="Overage charge in NZD")
    warning: bool = Field(False, description="True when usage exceeds 80% of effective quota")


# ---------------------------------------------------------------------------
# Number validation schema
# ---------------------------------------------------------------------------


class NumberValidationRequest(BaseModel):
    """POST /org/sms/validate-number — validate a phone number."""

    phone_number: str = Field(
        ..., min_length=1, max_length=20, description="Phone number to validate"
    )


class NumberValidationResponse(BaseModel):
    """POST /org/sms/validate-number — number validation result."""

    success: bool = Field(..., description="Whether the lookup succeeded")
    phone_number: Optional[str] = Field(None, description="Normalised phone number")
    carrier: Optional[str] = Field(None, description="Current carrier name")
    porting_status: Optional[str] = Field(None, description="Porting status")
    original_network: Optional[str] = Field(None, description="Original network")
    current_network: Optional[str] = Field(None, description="Current network")
    network_code: Optional[str] = Field(None, description="Network code")
    error: Optional[str] = Field(None, description="Error message if lookup failed")
