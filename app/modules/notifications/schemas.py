"""Pydantic schemas for the Notifications module — email template customisation.

Requirements: 34.1, 34.2, 34.3, 35.1, 35.2
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The 16 customisable email template types per org (Req 34.3)
EMAIL_TEMPLATE_TYPES: list[str] = [
    "invoice_issued",
    "payment_received",
    "payment_overdue_reminder",
    "invoice_voided",
    "storage_warning_80",
    "storage_critical_90",
    "storage_full_100",
    "subscription_renewal_reminder",
    "subscription_payment_failed",
    "wof_expiry_reminder",
    "registration_expiry_reminder",
    "service_due_reminder",
    "booking_confirmation",
    "booking_cancellation",
    "quote_sent",
    "quote_accepted",
    "quote_expired",
    "user_invitation",
    "password_reset",
    "mfa_enrolment",
    "login_alert",
    "account_locked",
]

# Supported template variables (Req 34.2)
TEMPLATE_VARIABLES: list[dict[str, str]] = [
    {"name": "customer_first_name", "description": "Customer's first name"},
    {"name": "customer_last_name", "description": "Customer's last name"},
    {"name": "customer_email", "description": "Customer's email address"},
    {"name": "invoice_number", "description": "Invoice reference number"},
    {"name": "total_due", "description": "Total amount due"},
    {"name": "due_date", "description": "Invoice due date"},
    {"name": "payment_link", "description": "Stripe payment link URL"},
    {"name": "org_name", "description": "Organisation name"},
    {"name": "org_phone", "description": "Organisation phone number"},
    {"name": "org_email", "description": "Organisation email address"},
    {"name": "vehicle_rego", "description": "Vehicle registration number"},
    {"name": "vehicle_make", "description": "Vehicle make"},
    {"name": "vehicle_model", "description": "Vehicle model"},
    {"name": "expiry_date", "description": "WOF or registration expiry date"},
    {"name": "service_due_date", "description": "Next service due date"},
    {"name": "booking_date", "description": "Booking date and time"},
    {"name": "booking_service", "description": "Booked service type"},
    {"name": "quote_number", "description": "Quote reference number"},
    {"name": "quote_total", "description": "Quote total amount"},
    {"name": "quote_valid_until", "description": "Quote expiry date"},
    {"name": "user_name", "description": "User's full name"},
    {"name": "reset_link", "description": "Password reset link URL"},
    {"name": "signup_link", "description": "User invitation signup link URL"},
]

# Valid delivery statuses for notification log (Req 35.1)
VALID_DELIVERY_STATUSES: list[str] = [
    "queued", "sent", "delivered", "bounced", "opened", "failed",
]

# The 4 SMS template types per org (Req 36.4)
SMS_TEMPLATE_TYPES: list[str] = [
    "invoice_issued",
    "payment_overdue_reminder",
    "wof_expiry_reminder",
    "registration_expiry_reminder",
    "service_due_reminder",
    "booking_confirmation",
    "booking_cancellation",
    "quote_sent",
    "quote_accepted",
    "quote_expired",
]

# Default SMS body text for each template type (Req 36.4)
# GSM-7 safe only (no smart quotes, em dashes, or emojis).
# Keep templates short so they fit in a single 160-char SMS segment
# after variable expansion.
DEFAULT_SMS_BODIES: dict[str, str] = {
    "invoice_issued": (
        "Hi {{customer_first_name}}, invoice {{invoice_number}} "
        "for {{total_due}} is ready. Pay online: {{payment_link}}"
    ),
    "payment_overdue_reminder": (
        "Hi {{customer_first_name}}, invoice {{invoice_number}} "
        "for {{total_due}} is overdue. Please pay now: {{payment_link}}"
    ),
    "wof_expiry_reminder": (
        "Hi {{customer_first_name}}, WOF for {{vehicle_rego}} "
        "expires {{expiry_date}}. Call {{org_name}} to book."
    ),
    "registration_expiry_reminder": (
        "Hi {{customer_first_name}}, rego for {{vehicle_rego}} "
        "expires {{expiry_date}}. Call {{org_name}} to arrange."
    ),
    "service_due_reminder": (
        "Hi {{customer_first_name}}, {{vehicle_rego}} is due for "
        "a service on {{service_due_date}}. Call {{org_name}} to book."
    ),
    "booking_confirmation": (
        "Hi {{customer_first_name}}, your {{booking_service}} "
        "on {{booking_date}} is confirmed. - {{org_name}}"
    ),
    "booking_cancellation": (
        "Hi {{customer_first_name}}, your {{booking_service}} "
        "on {{booking_date}} has been cancelled. Call {{org_name}} to rebook."
    ),
    "quote_sent": (
        "Hi {{customer_first_name}}, quote {{quote_number}} "
        "for {{quote_total}} is ready. Valid until {{quote_valid_until}}."
    ),
    "quote_accepted": (
        "Hi {{customer_first_name}}, quote {{quote_number}} "
        "has been accepted. We will be in touch. - {{org_name}}"
    ),
    "quote_expired": (
        "Hi {{customer_first_name}}, quote {{quote_number}} "
        "has expired. Call {{org_name}} for a new quote."
    ),
}

# Default body blocks for each template type
_DEFAULT_BODY_BLOCKS: dict[str, list[dict[str, Any]]] = {
    "invoice_issued": [
        {"type": "header", "content": "Invoice {{invoice_number}}"},
        {"type": "text", "content": "Hi {{customer_first_name}}, your invoice is ready."},
        {"type": "text", "content": "Total due: {{total_due}} by {{due_date}}."},
        {"type": "button", "content": "Pay Now", "url": "{{payment_link}}"},
    ],
    "payment_received": [
        {"type": "header", "content": "Payment Received"},
        {"type": "text", "content": "Hi {{customer_first_name}}, we received your payment for invoice {{invoice_number}}."},
        {"type": "text", "content": "Thank you for your business!"},
    ],
    "payment_overdue_reminder": [
        {"type": "header", "content": "Payment Overdue"},
        {"type": "text", "content": "Hi {{customer_first_name}}, invoice {{invoice_number}} is overdue."},
        {"type": "text", "content": "Amount due: {{total_due}}. Please pay at your earliest convenience."},
        {"type": "button", "content": "Pay Now", "url": "{{payment_link}}"},
    ],
    "invoice_voided": [
        {"type": "header", "content": "Invoice Voided"},
        {"type": "text", "content": "Hi {{customer_first_name}}, invoice {{invoice_number}} has been voided."},
        {"type": "text", "content": "Please contact us if you have any questions."},
    ],
    "storage_warning_80": [
        {"type": "header", "content": "Storage Warning"},
        {"type": "text", "content": "Your organisation is using 80% of its storage quota."},
        {"type": "text", "content": "Consider purchasing additional storage to avoid disruption."},
    ],
    "storage_critical_90": [
        {"type": "header", "content": "Storage Critical"},
        {"type": "text", "content": "Your organisation is using 90% of its storage quota."},
        {"type": "text", "content": "Please purchase additional storage immediately."},
    ],
    "storage_full_100": [
        {"type": "header", "content": "Storage Full"},
        {"type": "text", "content": "Your organisation has reached 100% storage. Invoice creation is blocked."},
        {"type": "text", "content": "Purchase additional storage to resume operations."},
    ],
    "subscription_renewal_reminder": [
        {"type": "header", "content": "Subscription Renewal"},
        {"type": "text", "content": "Your subscription will renew soon. No action is required."},
    ],
    "subscription_payment_failed": [
        {"type": "header", "content": "Payment Failed"},
        {"type": "text", "content": "We were unable to process your subscription payment."},
        {"type": "text", "content": "Please update your payment method to avoid service interruption."},
    ],
    "wof_expiry_reminder": [
        {"type": "header", "content": "WOF Expiry Reminder"},
        {"type": "text", "content": "Hi {{customer_first_name}}, the WOF for {{vehicle_rego}} ({{vehicle_make}} {{vehicle_model}}) expires on {{expiry_date}}."},
        {"type": "text", "content": "Book your WOF inspection with us today."},
    ],
    "registration_expiry_reminder": [
        {"type": "header", "content": "Registration Expiry Reminder"},
        {"type": "text", "content": "Hi {{customer_first_name}}, the registration for {{vehicle_rego}} ({{vehicle_make}} {{vehicle_model}}) expires on {{expiry_date}}."},
    ],
    "service_due_reminder": [
        {"type": "header", "content": "Service Due Reminder"},
        {"type": "text", "content": "Hi {{customer_first_name}}, your vehicle {{vehicle_rego}} ({{vehicle_make}} {{vehicle_model}}) is due for service on {{service_due_date}}."},
        {"type": "text", "content": "Book your service with {{org_name}} to keep your vehicle in top condition."},
    ],
    "booking_confirmation": [
        {"type": "header", "content": "Booking Confirmed"},
        {"type": "text", "content": "Hi {{customer_first_name}}, your booking for {{booking_service}} on {{booking_date}} has been confirmed."},
        {"type": "text", "content": "If you need to reschedule, please contact us at {{org_phone}}."},
    ],
    "booking_cancellation": [
        {"type": "header", "content": "Booking Cancelled"},
        {"type": "text", "content": "Hi {{customer_first_name}}, your booking for {{booking_service}} on {{booking_date}} has been cancelled."},
        {"type": "text", "content": "Please contact {{org_name}} if you'd like to rebook."},
    ],
    "quote_sent": [
        {"type": "header", "content": "Quote {{quote_number}}"},
        {"type": "text", "content": "Hi {{customer_first_name}}, your quote is ready."},
        {"type": "text", "content": "Total: {{quote_total}}. Valid until {{quote_valid_until}}."},
    ],
    "quote_accepted": [
        {"type": "header", "content": "Quote Accepted"},
        {"type": "text", "content": "Hi {{customer_first_name}}, thanks for accepting quote {{quote_number}}."},
        {"type": "text", "content": "We'll be in touch shortly to arrange the work."},
    ],
    "quote_expired": [
        {"type": "header", "content": "Quote Expired"},
        {"type": "text", "content": "Hi {{customer_first_name}}, quote {{quote_number}} has expired."},
        {"type": "text", "content": "Contact {{org_name}} if you'd like a new quote."},
    ],
    "user_invitation": [
        {"type": "header", "content": "You're Invited"},
        {"type": "text", "content": "Hi {{user_name}}, you've been invited to join {{org_name}}."},
        {"type": "button", "content": "Accept Invitation", "url": "{{signup_link}}"},
    ],
    "password_reset": [
        {"type": "header", "content": "Password Reset"},
        {"type": "text", "content": "Hi {{user_name}}, click below to reset your password."},
        {"type": "button", "content": "Reset Password", "url": "{{reset_link}}"},
    ],
    "mfa_enrolment": [
        {"type": "header", "content": "MFA Enrolment"},
        {"type": "text", "content": "Hi {{user_name}}, multi-factor authentication has been set up for your account."},
    ],
    "login_alert": [
        {"type": "header", "content": "New Login Detected"},
        {"type": "text", "content": "Hi {{user_name}}, a new login to your account was detected."},
        {"type": "text", "content": "If this wasn't you, please secure your account immediately."},
    ],
    "account_locked": [
        {"type": "header", "content": "Account Locked"},
        {"type": "text", "content": "Hi {{user_name}}, your account has been locked due to multiple failed login attempts."},
        {"type": "text", "content": "Please contact your administrator or use the password reset link."},
    ],
}

DEFAULT_SUBJECTS: dict[str, str] = {
    "invoice_issued": "Invoice {{invoice_number}} from {{org_name}}",
    "payment_received": "Payment received for invoice {{invoice_number}}",
    "payment_overdue_reminder": "Payment overdue — invoice {{invoice_number}}",
    "invoice_voided": "Invoice {{invoice_number}} voided",
    "storage_warning_80": "Storage warning — 80% used",
    "storage_critical_90": "Storage critical — 90% used",
    "storage_full_100": "Storage full — action required",
    "subscription_renewal_reminder": "Subscription renewal reminder",
    "subscription_payment_failed": "Subscription payment failed",
    "wof_expiry_reminder": "WOF expiry reminder for {{vehicle_rego}}",
    "registration_expiry_reminder": "Registration expiry reminder for {{vehicle_rego}}",
    "service_due_reminder": "Service due reminder for {{vehicle_rego}}",
    "booking_confirmation": "Booking confirmed — {{booking_service}} on {{booking_date}}",
    "booking_cancellation": "Booking cancelled — {{booking_service}} on {{booking_date}}",
    "quote_sent": "Quote {{quote_number}} from {{org_name}}",
    "quote_accepted": "Quote {{quote_number}} accepted",
    "quote_expired": "Quote {{quote_number}} has expired",
    "user_invitation": "You're invited to join {{org_name}}",
    "password_reset": "Password reset request",
    "mfa_enrolment": "MFA enrolment confirmation",
    "login_alert": "New login detected on your account",
    "account_locked": "Your account has been locked",
}


def get_default_body_blocks(template_type: str) -> list[dict[str, Any]]:
    """Return default body blocks for a template type."""
    return _DEFAULT_BODY_BLOCKS.get(template_type, [])


# ---------------------------------------------------------------------------
# Block schemas
# ---------------------------------------------------------------------------


class TemplateBlock(BaseModel):
    """A single block in the visual block editor (Req 34.1)."""

    type: Literal["header", "text", "button", "image", "divider", "footer"] = Field(
        ..., description="Block type"
    )
    content: Optional[str] = Field(
        None, description="Block content (supports {{variable}} syntax)"
    )
    url: Optional[str] = Field(
        None, description="URL for button/image blocks"
    )


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class TemplateUpdateRequest(BaseModel):
    """PUT /api/v1/notifications/templates/{template_type} request body.

    Requirements: 34.1, 34.2
    """

    subject: Optional[str] = Field(
        None, max_length=255, description="Email subject (supports {{variables}})"
    )
    body_blocks: Optional[list[TemplateBlock]] = Field(
        None, description="Visual block editor content (JSONB)"
    )
    is_enabled: Optional[bool] = Field(
        None, description="Enable/disable this template"
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class TemplateResponse(BaseModel):
    """Single email template in API responses.

    Requirements: 34.1, 34.2, 34.3
    """

    id: str = Field(..., description="Template UUID")
    template_type: str = Field(..., description="Template type identifier")
    channel: str = Field(..., description="Channel (email)")
    subject: Optional[str] = Field(None, description="Email subject line")
    body_blocks: list[dict[str, Any]] = Field(
        default_factory=list, description="Visual block editor content"
    )
    is_enabled: bool = Field(False, description="Whether template is enabled")
    updated_at: str = Field(..., description="ISO 8601 last update timestamp")


class TemplateListResponse(BaseModel):
    """GET /api/v1/notifications/templates response."""

    templates: list[TemplateResponse] = Field(
        default_factory=list, description="List of email templates"
    )
    total: int = Field(0, description="Total number of templates")
    available_variables: list[dict[str, str]] = Field(
        default_factory=list, description="Supported template variables"
    )


class TemplateUpdateResponse(BaseModel):
    """PUT /api/v1/notifications/templates/{template_type} response."""

    message: str
    template: TemplateResponse


class TemplatePreviewResponse(BaseModel):
    """GET /api/v1/notifications/templates/{template_type}/preview response."""

    subject: str = Field(..., description="Rendered subject line")
    html_body: str = Field(..., description="Rendered HTML body")


# ---------------------------------------------------------------------------
# Email delivery tracking schemas (Req 35.1, 35.2)
# ---------------------------------------------------------------------------


class NotificationLogEntry(BaseModel):
    """A single entry in the email delivery log."""

    id: str = Field(..., description="Log entry UUID")
    channel: str = Field(..., description="Channel (email or sms)")
    recipient: str = Field(..., description="Recipient address")
    template_type: str = Field(..., description="Template type used")
    subject: Optional[str] = Field(None, description="Rendered subject line")
    status: str = Field(..., description="Delivery status")
    error_message: Optional[str] = Field(None, description="Error details if failed/bounced")
    sent_at: Optional[str] = Field(None, description="ISO 8601 timestamp when sent")
    created_at: str = Field(..., description="ISO 8601 timestamp when queued")


class NotificationLogResponse(BaseModel):
    """GET /api/v1/notifications/log response."""

    entries: list[NotificationLogEntry] = Field(
        default_factory=list, description="Log entries"
    )
    total: int = Field(0, description="Total matching entries")
    page: int = Field(1, description="Current page")
    page_size: int = Field(50, description="Entries per page")


# ---------------------------------------------------------------------------
# SMS template schemas (Req 36.3, 36.4, 36.5)
# ---------------------------------------------------------------------------


class SmsTemplateUpdateRequest(BaseModel):
    """PUT /api/v1/notifications/sms-templates/{template_type} request body.

    Requirements: 36.3, 36.4
    """

    body: Optional[str] = Field(
        None,
        description="SMS body text (supports {{variables}})",
    )
    is_enabled: Optional[bool] = Field(
        None, description="Enable/disable this SMS template"
    )


class SmsTemplateResponse(BaseModel):
    """Single SMS template in API responses.

    Requirements: 36.3, 36.4, 36.5
    """

    id: str = Field(..., description="Template UUID")
    template_type: str = Field(..., description="Template type identifier")
    channel: str = Field(default="sms", description="Channel (sms)")
    body: str = Field(default="", description="SMS body text")
    char_count: int = Field(0, description="Character count of body")
    exceeds_limit: bool = Field(
        False, description="True if body exceeds 160 chars"
    )
    is_enabled: bool = Field(False, description="Whether template is enabled")
    updated_at: str = Field(..., description="ISO 8601 last update timestamp")


class SmsTemplateListResponse(BaseModel):
    """GET /api/v1/notifications/sms-templates response."""

    templates: list[SmsTemplateResponse] = Field(
        default_factory=list, description="List of SMS templates"
    )
    total: int = Field(0, description="Total number of SMS templates")
    available_variables: list[dict[str, str]] = Field(
        default_factory=list, description="Supported template variables"
    )


class SmsTemplateUpdateResponse(BaseModel):
    """PUT /api/v1/notifications/sms-templates/{template_type} response."""

    message: str
    template: SmsTemplateResponse


class OrgSmsSettingsRequest(BaseModel):
    """PUT /api/v1/notifications/sms-settings request body.

    Requirements: 36.2, 36.3
    """

    sms_enabled: Optional[bool] = Field(
        None, description="Enable/disable SMS for this organisation"
    )
    sender_name: Optional[str] = Field(
        None, max_length=11, description="Org sender name or number for SMS"
    )


class OrgSmsSettingsResponse(BaseModel):
    """GET /api/v1/notifications/sms-settings response."""

    sms_enabled: bool = Field(False, description="Whether SMS is enabled for this org")
    sender_name: str = Field("", description="Org sender name or number")



# ---------------------------------------------------------------------------
# Overdue reminder rule schemas (Req 38.1, 38.2, 38.3, 38.4)
# ---------------------------------------------------------------------------


class OverdueReminderRuleCreate(BaseModel):
    """POST /api/v1/notifications/overdue-rules request body.

    Requirements: 38.1
    """

    days_after_due: int = Field(
        ..., ge=1, le=365, description="Number of days after due date to trigger reminder"
    )
    send_email: bool = Field(True, description="Send reminder via email")
    send_sms: bool = Field(False, description="Send reminder via SMS")
    is_enabled: bool = Field(True, description="Whether this rule is active")


class OverdueReminderRuleUpdate(BaseModel):
    """PUT /api/v1/notifications/overdue-rules/{rule_id} request body.

    Requirements: 38.1
    """

    days_after_due: Optional[int] = Field(
        None, ge=1, le=365, description="Number of days after due date"
    )
    send_email: Optional[bool] = Field(None, description="Send via email")
    send_sms: Optional[bool] = Field(None, description="Send via SMS")
    is_enabled: Optional[bool] = Field(None, description="Whether rule is active")


class OverdueReminderRuleResponse(BaseModel):
    """Single overdue reminder rule in API responses.

    Requirements: 38.1
    """

    id: str = Field(..., description="Rule UUID")
    org_id: str = Field(..., description="Organisation UUID")
    days_after_due: int = Field(..., description="Days after due date")
    send_email: bool = Field(..., description="Send via email")
    send_sms: bool = Field(..., description="Send via SMS")
    sort_order: int = Field(0, description="Display sort order")
    is_enabled: bool = Field(..., description="Whether rule is active")


class OverdueReminderRuleListResponse(BaseModel):
    """GET /api/v1/notifications/overdue-rules response.

    Requirements: 38.1
    """

    rules: list[OverdueReminderRuleResponse] = Field(
        default_factory=list, description="Overdue reminder rules (max 3)"
    )
    total: int = Field(0, description="Total number of rules")
    reminders_enabled: bool = Field(
        False, description="Whether overdue reminders are enabled for this org"
    )


# ---------------------------------------------------------------------------
# WOF / Registration expiry reminder schemas (Req 39.1, 39.2, 39.3, 39.4)
# ---------------------------------------------------------------------------


class WofRegoReminderSettingsRequest(BaseModel):
    """PUT /api/v1/notifications/wof-rego-settings request body.

    Requirements: 39.1, 39.2, 39.4
    """

    enabled: Optional[bool] = Field(
        None, description="Enable/disable WOF & rego expiry reminders"
    )
    days_in_advance: Optional[int] = Field(
        None,
        ge=1,
        le=365,
        description="Days before expiry to send reminder (default 30)",
    )
    channel: Optional[Literal["email", "sms", "both"]] = Field(
        None, description="Notification channel: email, sms, or both"
    )


class WofRegoReminderSettingsResponse(BaseModel):
    """GET /api/v1/notifications/wof-rego-settings response.

    Requirements: 39.1, 39.2, 39.4
    """

    enabled: bool = Field(False, description="Whether WOF/rego reminders are enabled")
    days_in_advance: int = Field(
        30, description="Days before expiry to send reminder"
    )
    channel: str = Field("email", description="Notification channel")


# ---------------------------------------------------------------------------
# Notification preference schemas (Req 83.1, 83.2, 83.3, 83.4)
# ---------------------------------------------------------------------------

# All notification types grouped by category
NOTIFICATION_CATEGORIES: dict[str, list[str]] = {
    "Invoicing": [
        "invoice_issued",
        "invoice_voided",
        "payment_overdue_reminder",
    ],
    "Payments": [
        "payment_received",
    ],
    "Quotes": [
        "quote_sent",
        "quote_accepted",
        "quote_expired",
    ],
    "Bookings": [
        "booking_confirmation",
        "booking_cancellation",
    ],
    "Vehicle Reminders": [
        "wof_expiry_reminder",
        "registration_expiry_reminder",
        "service_due_reminder",
    ],
    "System Alerts": [
        "storage_warning_80",
        "storage_critical_90",
        "storage_full_100",
        "subscription_renewal_reminder",
        "subscription_payment_failed",
        "login_alert",
        "account_locked",
    ],
}

# Flat set of all valid notification types
ALL_NOTIFICATION_TYPES: set[str] = {
    nt for types in NOTIFICATION_CATEGORIES.values() for nt in types
}


class NotificationPreferenceItem(BaseModel):
    """A single notification type preference.

    Requirements: 83.1, 83.4
    """

    notification_type: str = Field(..., description="Notification type identifier")
    is_enabled: bool = Field(False, description="Whether this notification is enabled")
    channel: Literal["email", "sms", "both"] = Field(
        "email", description="Delivery channel"
    )


class NotificationPreferenceCategoryGroup(BaseModel):
    """A group of notification preferences under a category.

    Requirements: 83.3
    """

    category: str = Field(..., description="Category name")
    preferences: list[NotificationPreferenceItem] = Field(
        default_factory=list, description="Preferences in this category"
    )


class NotificationPreferencesResponse(BaseModel):
    """GET /api/v1/notifications/settings response.

    Requirements: 83.1, 83.3
    """

    categories: list[NotificationPreferenceCategoryGroup] = Field(
        default_factory=list, description="Preferences grouped by category"
    )


class NotificationPreferenceUpdateRequest(BaseModel):
    """PUT /api/v1/notifications/settings request body.

    Requirements: 83.1, 83.2, 83.4
    """

    notification_type: str = Field(..., description="Notification type to update")
    is_enabled: Optional[bool] = Field(
        None, description="Enable or disable this notification type"
    )
    channel: Optional[Literal["email", "sms", "both"]] = Field(
        None, description="Delivery channel: email, sms, or both"
    )


# ---------------------------------------------------------------------------
# Bounce webhook schemas (Req 2.20 — Brevo & SendGrid bounce handling)
# ---------------------------------------------------------------------------


class BrevoBounceEvent(BaseModel):
    """Single event in a Brevo bounce webhook payload."""

    event: str = Field(..., description="Event type, e.g. 'hard_bounce', 'soft_bounce', 'blocked'")
    email: str = Field(..., description="Bounced email address")
    message_id: Optional[str] = Field(None, alias="message-id", description="Brevo message ID")
    ts_event: Optional[int] = Field(None, description="Unix timestamp of the event")


class BrevoBounceWebhookRequest(BaseModel):
    """POST /notifications/webhooks/brevo-bounce request body.

    Brevo sends an array of events or a single event object.
    """

    events: Optional[list[BrevoBounceEvent]] = Field(
        None, description="Array of bounce events (batch mode)"
    )
    # Single-event fallback fields
    event: Optional[str] = Field(None, description="Event type for single-event mode")
    email: Optional[str] = Field(None, description="Bounced email for single-event mode")

    model_config = {"populate_by_name": True}


class SendGridBounceEvent(BaseModel):
    """Single event in a SendGrid Event Webhook payload."""

    event: str = Field(..., description="Event type, e.g. 'bounce', 'dropped', 'deferred'")
    email: str = Field(..., description="Bounced email address")
    sg_message_id: Optional[str] = Field(None, description="SendGrid message ID")
    timestamp: Optional[int] = Field(None, description="Unix timestamp of the event")
    reason: Optional[str] = Field(None, description="Bounce reason")



# ---------------------------------------------------------------------------
# Bounce webhook schemas (Req 2.20 — Brevo & SendGrid bounce handling)
# ---------------------------------------------------------------------------


class BrevoBounceEvent(BaseModel):
    """Single event in a Brevo bounce webhook payload."""

    event: str = Field(..., description="Event type, e.g. 'hard_bounce', 'soft_bounce', 'blocked'")
    email: str = Field(..., description="Bounced email address")
    message_id: Optional[str] = Field(None, alias="message-id", description="Brevo message ID")
    ts_event: Optional[int] = Field(None, description="Unix timestamp of the event")


class BrevoBounceWebhookRequest(BaseModel):
    """POST /notifications/webhooks/brevo-bounce request body.

    Brevo sends an array of events or a single event object.
    """

    events: Optional[list[BrevoBounceEvent]] = Field(
        None, description="Array of bounce events (batch mode)"
    )
    # Single-event fallback fields
    event: Optional[str] = Field(None, description="Event type for single-event mode")
    email: Optional[str] = Field(None, description="Bounced email for single-event mode")

    model_config = {"populate_by_name": True}


class SendGridBounceEvent(BaseModel):
    """Single event in a SendGrid Event Webhook payload."""

    event: str = Field(..., description="Event type, e.g. 'bounce', 'dropped', 'deferred'")
    email: str = Field(..., description="Bounced email address")
    sg_message_id: Optional[str] = Field(None, description="SendGrid message ID")
    timestamp: Optional[int] = Field(None, description="Unix timestamp of the event")
    reason: Optional[str] = Field(None, description="Bounce reason")


# ---------------------------------------------------------------------------
# Reminder rule schemas (Zoho-style configurable reminders)
# ---------------------------------------------------------------------------

VALID_REMINDER_TYPES: list[str] = [
    "payment_due",
    "payment_expected",
    "invoice_issued",
    "quote_expiry",
    "service_due",
    "custom",
]

VALID_TARGETS: list[str] = ["customer", "me", "both"]
VALID_TIMINGS: list[str] = ["before", "after"]
VALID_REFERENCE_DATES: list[str] = [
    "due_date",
    "expected_payment_date",
    "invoice_date",
    "quote_expiry_date",
    "service_due_date",
]

# Manual reminders are informational — no DB config needed
MANUAL_REMINDERS: list[dict[str, str]] = [
    {
        "id": "manual_overdue",
        "name": "Reminder For Overdue Invoices",
        "description": "You can send this reminder to your customers manually, from an overdue invoice's details page.",
    },
    {
        "id": "manual_sent",
        "name": "Reminder For Sent Invoices",
        "description": "You can send this reminder to your customers manually, from a sent (but not overdue) invoice's details page.",
    },
]


class ReminderRuleResponse(BaseModel):
    """Single reminder rule."""

    id: str
    org_id: str
    name: str
    reminder_type: str
    target: str
    days_offset: int
    timing: str
    reference_date: str
    send_email: bool
    send_sms: bool
    is_enabled: bool
    sort_order: int


class ReminderRulesListResponse(BaseModel):
    """GET /notifications/reminders response."""

    manual_reminders: list[dict] = Field(default_factory=list)
    automated_reminders: list[ReminderRuleResponse] = Field(default_factory=list)
    total: int = 0


class ReminderRuleCreateRequest(BaseModel):
    """POST /notifications/reminders request."""

    name: str = Field(..., min_length=1, max_length=100)
    reminder_type: str = Field(..., description="Type: payment_due, payment_expected, etc.")
    target: str = Field("customer", description="Who to remind: customer, me, both")
    days_offset: int = Field(0, ge=0, le=365)
    timing: str = Field("after", description="before or after the reference date")
    reference_date: str = Field("due_date", description="Which date to base the reminder on")
    send_email: bool = Field(True)
    send_sms: bool = Field(False)
    is_enabled: bool = Field(True)


class ReminderRuleUpdateRequest(BaseModel):
    """PUT /notifications/reminders/{id} request."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    target: Optional[str] = None
    days_offset: Optional[int] = Field(None, ge=0, le=365)
    timing: Optional[str] = None
    reference_date: Optional[str] = None
    send_email: Optional[bool] = None
    send_sms: Optional[bool] = None
    is_enabled: Optional[bool] = None
