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
]

# Default SMS body text for each template type (Req 36.4)
DEFAULT_SMS_BODIES: dict[str, str] = {
    "invoice_issued": (
        "Hi {{customer_first_name}}, invoice {{invoice_number}} "
        "for {{total_due}} is ready. Pay here: {{payment_link}}"
    ),
    "payment_overdue_reminder": (
        "Hi {{customer_first_name}}, invoice {{invoice_number}} "
        "is overdue. Amount: {{total_due}}. Please pay promptly."
    ),
    "wof_expiry_reminder": (
        "Hi {{customer_first_name}}, WOF for {{vehicle_rego}} "
        "expires {{expiry_date}}. Book with {{org_name}} today."
    ),
    "registration_expiry_reminder": (
        "Hi {{customer_first_name}}, rego for {{vehicle_rego}} "
        "expires {{expiry_date}}. Contact {{org_name}}."
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
    "Vehicle Reminders": [
        "wof_expiry_reminder",
        "registration_expiry_reminder",
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
