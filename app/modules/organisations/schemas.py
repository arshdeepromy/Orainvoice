"""Pydantic schemas for the Organisation module — onboarding wizard & public signup."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field


class OnboardingStepRequest(BaseModel):
    """POST /api/v1/org/onboarding request body.

    Each field corresponds to one wizard step. All fields are optional so
    that any step can be skipped. The frontend sends whichever fields the
    user has filled in for the current step.

    Requirements: 8.2, 8.3, 8.4, 8.5
    """

    # Step 1 — Organisation name & contact
    org_name: Optional[str] = Field(
        None, min_length=1, max_length=255, description="Organisation display name"
    )

    # Step 2 — Logo upload (URL after upload)
    logo_url: Optional[str] = Field(
        None, max_length=2048, description="URL of the uploaded logo"
    )

    # Step 3 — Brand colours
    primary_colour: Optional[str] = Field(
        None,
        max_length=7,
        pattern=r"^#[0-9A-Fa-f]{6}$",
        description="Primary brand colour as hex (e.g. #FF5733)",
    )
    secondary_colour: Optional[str] = Field(
        None,
        max_length=7,
        pattern=r"^#[0-9A-Fa-f]{6}$",
        description="Secondary brand colour as hex",
    )

    # Step 4 — GST details
    gst_number: Optional[str] = Field(
        None,
        max_length=20,
        description="IRD GST number",
    )
    gst_percentage: Optional[float] = Field(
        None,
        ge=0,
        le=100,
        description="GST percentage (default 15%)",
    )

    # Step 5 — Invoice numbering
    invoice_prefix: Optional[str] = Field(
        None,
        max_length=20,
        description="Invoice number prefix (e.g. INV-, WS-)",
    )
    invoice_start_number: Optional[int] = Field(
        None,
        ge=1,
        description="Starting invoice number",
    )

    # Step 6 — Payment terms
    default_due_days: Optional[int] = Field(
        None,
        ge=0,
        le=365,
        description="Default payment terms in days from issue date",
    )
    payment_terms_text: Optional[str] = Field(
        None,
        max_length=500,
        description="Custom payment terms statement for invoice PDFs",
    )

    # Step 7 — First service type
    first_service_name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=255,
        description="Name of the first service type to add to the catalogue",
    )
    first_service_price: Optional[float] = Field(
        None,
        ge=0,
        description="Default price (ex-GST) for the first service",
    )


class OnboardingStepResponse(BaseModel):
    """Response after saving an onboarding wizard step."""

    message: str
    updated_fields: list[str] = Field(
        default_factory=list,
        description="List of settings fields that were updated",
    )
    onboarding_complete: bool = Field(
        False,
        description="Whether all onboarding steps have been completed",
    )
    skipped: bool = Field(
        False,
        description="True if no fields were provided (step was skipped)",
    )


# ---------------------------------------------------------------------------
# Organisation Settings schemas (Task 6.3)
# Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6
# ---------------------------------------------------------------------------

import re

_IRD_GST_PATTERN = re.compile(r"^\d{2,3}-?\d{3}-?\d{3}$")


def validate_ird_gst_number(value: str) -> str:
    """Validate NZ IRD GST number format.

    Accepted formats: XX-XXX-XXX or XXX-XXX-XXX (8 or 9 digits,
    optionally separated by hyphens).
    """
    digits_only = value.replace("-", "")
    if not digits_only.isdigit() or len(digits_only) not in (8, 9):
        raise ValueError(
            "GST number must be 8 or 9 digits in IRD format "
            "(e.g. 12-345-678 or 123-456-789)"
        )
    if not _IRD_GST_PATTERN.match(value) and value != digits_only:
        raise ValueError(
            "GST number format must be XX-XXX-XXX or XXX-XXX-XXX"
        )
    return value


class OrgSettingsResponse(BaseModel):
    """GET /api/v1/org/settings response — full org settings + branding."""

    # Identity
    org_name: str = Field(..., description="Organisation display name")

    # Branding
    logo_url: Optional[str] = Field(None, description="Logo URL (PNG or SVG)")
    primary_colour: Optional[str] = Field(None, description="Primary brand colour hex")
    secondary_colour: Optional[str] = Field(None, description="Secondary brand colour hex")

    # Contact / Address
    address: Optional[str] = Field(None, description="Legacy single-line address")
    address_unit: Optional[str] = Field(None, description="Unit/Suite number")
    address_street: Optional[str] = Field(None, description="Street number and name")
    address_city: Optional[str] = Field(None, description="City/Town")
    address_state: Optional[str] = Field(None, description="State/Region")
    address_country: Optional[str] = Field(None, description="Country")
    address_postcode: Optional[str] = Field(None, description="Postal/Zip code")
    website: Optional[str] = Field(None, max_length=500, description="Organisation website URL")
    phone: Optional[str] = Field(None, max_length=50, description="Organisation phone number")
    email: Optional[str] = Field(None, max_length=255, description="Organisation email")

    # Invoice branding
    invoice_header_text: Optional[str] = Field(None, description="Custom invoice header text")
    invoice_footer_text: Optional[str] = Field(None, description="Custom invoice footer text")
    email_signature: Optional[str] = Field(None, description="Custom email signature")

    # GST
    gst_number: Optional[str] = Field(None, description="IRD GST number")
    gst_percentage: Optional[float] = Field(None, description="GST percentage")
    gst_inclusive: Optional[bool] = Field(None, description="GST-inclusive display toggle")

    # Invoice settings
    invoice_prefix: Optional[str] = Field(None, description="Invoice number prefix")
    invoice_start_number: Optional[int] = Field(None, description="Starting invoice number")
    default_due_days: Optional[int] = Field(None, description="Default due days from issue date")
    default_notes: Optional[str] = Field(None, description="Default invoice notes")

    # Payment terms
    payment_terms_days: Optional[int] = Field(None, description="Payment terms in days")
    payment_terms_text: Optional[str] = Field(None, description="Custom payment terms statement")
    allow_partial_payments: Optional[bool] = Field(None, description="Allow partial payments")

    # Terms & conditions (rich text)
    terms_and_conditions: Optional[str] = Field(
        None, description="Custom T&C (rich text HTML with headings, bold, lists, links)"
    )

    # Sidebar display mode
    sidebar_display_mode: Optional[str] = Field(
        None, description="Sidebar branding display: icon_and_name, icon_only, or name_only"
    )

    # Trade info (for trade-specific UI gating)
    trade_family: Optional[str] = Field(
        None, description="Trade family slug (e.g. 'automotive-transport', 'plumbing-gas')"
    )
    trade_category: Optional[str] = Field(
        None, description="Trade category slug (e.g. 'general-automotive', 'plumber')"
    )


class OrgSettingsUpdateRequest(BaseModel):
    """PUT /api/v1/org/settings request body.

    All fields are optional — only provided fields are updated.
    Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6
    """

    # Identity
    org_name: Optional[str] = Field(
        None, min_length=1, max_length=255, description="Organisation display name"
    )

    # Branding
    logo_url: Optional[str] = Field(
        None, max_length=500000, description="Logo URL or base64 data URI (PNG or SVG)"
    )
    primary_colour: Optional[str] = Field(
        None,
        max_length=7,
        pattern=r"^#[0-9A-Fa-f]{6}$",
        description="Primary brand colour hex",
    )
    secondary_colour: Optional[str] = Field(
        None,
        max_length=7,
        pattern=r"^#[0-9A-Fa-f]{6}$",
        description="Secondary brand colour hex",
    )

    # Contact / Address
    address_unit: Optional[str] = Field(None, max_length=50, description="Unit/Suite number")
    address_street: Optional[str] = Field(None, max_length=255, description="Street number and name")
    address_city: Optional[str] = Field(None, max_length=100, description="City/Town")
    address_state: Optional[str] = Field(None, max_length=100, description="State/Region")
    address_country: Optional[str] = Field(None, max_length=100, description="Country")
    address_postcode: Optional[str] = Field(None, max_length=20, description="Postal/Zip code")
    website: Optional[str] = Field(None, max_length=500, description="Organisation website URL")
    phone: Optional[str] = Field(None, max_length=50, description="Organisation phone number")
    email: Optional[str] = Field(None, max_length=255, description="Organisation email")

    # Invoice branding
    invoice_header_text: Optional[str] = Field(
        None, max_length=500, description="Custom invoice header text"
    )
    invoice_footer_text: Optional[str] = Field(
        None, max_length=500, description="Custom invoice footer text"
    )
    email_signature: Optional[str] = Field(
        None, max_length=2000, description="Custom email signature"
    )

    # GST
    gst_number: Optional[str] = Field(
        None, max_length=20, description="IRD GST number"
    )
    gst_percentage: Optional[float] = Field(
        None, ge=0, le=100, description="GST percentage"
    )
    gst_inclusive: Optional[bool] = Field(
        None, description="GST-inclusive display toggle"
    )

    # Invoice settings
    invoice_prefix: Optional[str] = Field(
        None, max_length=20, description="Invoice number prefix (e.g. INV-, WS-)"
    )
    invoice_start_number: Optional[int] = Field(
        None, ge=1, description="Starting invoice number"
    )
    default_due_days: Optional[int] = Field(
        None, ge=0, le=365, description="Default due days from issue date"
    )
    default_notes: Optional[str] = Field(
        None, max_length=2000, description="Default invoice notes"
    )

    # Payment terms
    payment_terms_days: Optional[int] = Field(
        None, ge=0, le=365, description="Payment terms in days"
    )
    payment_terms_text: Optional[str] = Field(
        None, max_length=500, description="Custom payment terms statement"
    )
    allow_partial_payments: Optional[bool] = Field(
        None, description="Allow partial payments"
    )

    # Terms & conditions (rich text)
    terms_and_conditions: Optional[str] = Field(
        None, max_length=50000, description="Custom T&C (rich text HTML)"
    )

    # Sidebar display mode
    sidebar_display_mode: Optional[str] = Field(
        None,
        pattern=r"^(icon_and_name|icon_only|name_only)$",
        description="Sidebar branding display: icon_and_name, icon_only, or name_only",
    )

    # Trade category
    trade_category_slug: Optional[str] = Field(
        None,
        max_length=100,
        description="Trade category slug (e.g. 'general-automotive', 'plumber'). Changes the org's trade type.",
    )


class OrgSettingsUpdateResponse(BaseModel):
    """Response after updating organisation settings."""

    message: str
    updated_fields: list[str] = Field(
        default_factory=list,
        description="List of settings fields that were updated",
    )


# ---------------------------------------------------------------------------
# Branch schemas (Task 6.4)
# Requirements: 9.7, 9.8
# ---------------------------------------------------------------------------


class BranchCreateRequest(BaseModel):
    """POST /api/v1/org/branches request body."""

    name: str = Field(..., min_length=1, max_length=255, description="Branch name")
    address: Optional[str] = Field(None, max_length=2000, description="Branch address")
    phone: Optional[str] = Field(None, max_length=50, description="Branch phone number")


class BranchUpdateRequest(BaseModel):
    """PUT /api/v1/org/branches/{branch_id} request body.

    All fields are optional — only provided (non-null) fields are updated.
    Requirements: 1.1, 1.2, 1.3, 1.4, 1.5
    """

    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Branch name")
    address: Optional[str] = Field(None, max_length=2000, description="Branch address")
    phone: Optional[str] = Field(None, max_length=50, description="Branch phone number")
    email: Optional[str] = Field(None, max_length=255, description="Branch email")
    logo_url: Optional[str] = Field(None, max_length=2048, description="Branch logo URL")
    operating_hours: Optional[dict] = Field(None, description="Operating hours JSON (day-of-week keys)")
    timezone: Optional[str] = Field(None, max_length=50, description="IANA timezone string")


class BranchResponse(BaseModel):
    """Single branch in API responses."""

    id: str = Field(..., description="Branch UUID")
    name: str = Field(..., description="Branch name")
    address: Optional[str] = Field(None, description="Branch address")
    phone: Optional[str] = Field(None, description="Branch phone number")
    is_active: bool = Field(True, description="Whether the branch is active")
    created_at: str = Field(..., description="ISO 8601 creation timestamp")


class BranchListResponse(BaseModel):
    """GET /api/v1/org/branches response."""

    branches: list[BranchResponse] = Field(
        default_factory=list, description="List of branches"
    )


class BranchCreateResponse(BaseModel):
    """POST /api/v1/org/branches response."""

    message: str
    branch: BranchResponse


class BranchDetailResponse(BaseModel):
    """Extended branch response with all fields including settings.

    Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.6
    """

    id: str = Field(..., description="Branch UUID")
    name: str = Field(..., description="Branch name")
    address: Optional[str] = Field(None, description="Branch address")
    phone: Optional[str] = Field(None, description="Branch phone number")
    email: Optional[str] = Field(None, description="Branch email")
    logo_url: Optional[str] = Field(None, description="Branch logo URL")
    operating_hours: Optional[dict] = Field(None, description="Operating hours JSON")
    timezone: Optional[str] = Field(None, description="IANA timezone string")
    is_hq: bool = Field(False, description="Whether this is the HQ branch")
    is_active: bool = Field(True, description="Whether the branch is active")
    created_at: Optional[str] = Field(None, description="ISO 8601 creation timestamp")
    updated_at: Optional[str] = Field(None, description="ISO 8601 update timestamp")


class BranchUpdateResponse(BaseModel):
    """PUT /api/v1/org/branches/{branch_id} response."""

    message: str
    branch: BranchDetailResponse


class BranchDeactivateResponse(BaseModel):
    """DELETE /api/v1/org/branches/{branch_id} response."""

    message: str
    branch: BranchDetailResponse


class BranchReactivateResponse(BaseModel):
    """POST /api/v1/org/branches/{branch_id}/reactivate response."""

    message: str
    branch: BranchDetailResponse


class BranchSettingsResponse(BaseModel):
    """GET /api/v1/org/branches/{branch_id}/settings response.

    Requirements: 3.1
    """

    id: str = Field(..., description="Branch UUID")
    name: str = Field(..., description="Branch name")
    address: Optional[str] = Field(None, description="Branch address")
    phone: Optional[str] = Field(None, description="Branch phone number")
    email: Optional[str] = Field(None, description="Branch email")
    logo_url: Optional[str] = Field(None, description="Branch logo URL")
    operating_hours: Optional[dict] = Field(None, description="Operating hours JSON")
    timezone: Optional[str] = Field(None, description="IANA timezone string")
    notification_preferences: Optional[dict] = Field(None, description="Notification preferences JSON")


class BranchSettingsUpdateRequest(BaseModel):
    """PUT /api/v1/org/branches/{branch_id}/settings request body.

    All fields are optional — only provided (non-null) fields are updated.
    Requirements: 3.1, 3.5, 22.4
    """

    address: Optional[str] = Field(None, max_length=2000, description="Branch address")
    phone: Optional[str] = Field(None, max_length=50, description="Branch phone number")
    email: Optional[str] = Field(None, max_length=255, description="Branch email")
    logo_url: Optional[str] = Field(None, max_length=2048, description="Branch logo URL")
    operating_hours: Optional[dict] = Field(None, description="Operating hours JSON (day-of-week keys)")
    timezone: Optional[str] = Field(None, max_length=50, description="IANA timezone string")
    notification_preferences: Optional[dict] = Field(None, description="Notification preferences JSON")


class BranchSettingsUpdateResponse(BaseModel):
    """PUT /api/v1/org/branches/{branch_id}/settings response."""

    message: str
    settings: BranchSettingsResponse


class AssignUserBranchesRequest(BaseModel):
    """Request body for assigning a user to branches."""

    user_id: str = Field(..., description="User UUID to assign")
    branch_ids: list[str] = Field(
        ..., description="List of branch UUIDs to assign the user to"
    )


class AssignUserBranchesResponse(BaseModel):
    """Response after assigning user to branches."""

    message: str
    user_id: str
    branch_ids: list[str]


# ---------------------------------------------------------------------------
# User Management schemas (Task 6.5)
# Requirements: 10.1, 10.2, 10.3, 10.4, 10.5
# ---------------------------------------------------------------------------


class UserInviteRequest(BaseModel):
    """POST /api/v1/org/users/invite request body.

    When ``password`` is provided (kiosk accounts), the user is created
    directly with the password set and email marked as verified — no
    invitation email is sent.  When ``password`` is omitted, the existing
    invite-token flow is used.
    """

    email: str = Field(
        ..., min_length=5, max_length=255, description="Email address of the user to invite"
    )
    role: str = Field(
        "salesperson",
        description="Role to assign: 'org_admin', 'salesperson', or 'kiosk'",
    )
    password: str | None = Field(
        None,
        min_length=8,
        max_length=128,
        description="Password for direct account creation (kiosk only). When provided, skips the invite email.",
    )



class OrgUserResponse(BaseModel):
    """Single user in API responses."""

    id: str = Field(..., description="User UUID")
    email: str = Field(..., description="User email")
    role: str = Field(..., description="User role")
    is_active: bool = Field(..., description="Whether the user is active")
    is_email_verified: bool = Field(..., description="Whether email is verified")
    last_login_at: Optional[str] = Field(None, description="ISO 8601 last login timestamp")
    created_at: str = Field(..., description="ISO 8601 creation timestamp")


class UserInviteResponse(BaseModel):
    """POST /api/v1/org/users/invite response."""

    message: str
    user: OrgUserResponse


class UserListResponse(BaseModel):
    """GET /api/v1/org/users response."""

    users: list[OrgUserResponse] = Field(default_factory=list, description="List of org users")
    total: int = Field(0, description="Total number of users")
    seat_limit: int = Field(0, description="Max user seats for the plan")


class UserUpdateRequest(BaseModel):
    """PUT /api/v1/org/users/{id} request body."""

    role: Optional[str] = Field(None, description="New role: 'org_admin', 'salesperson', or 'kiosk'")
    is_active: Optional[bool] = Field(None, description="Activate or deactivate the user")


class UserUpdateResponse(BaseModel):
    """PUT /api/v1/org/users/{id} response."""

    message: str
    user: OrgUserResponse


class UserDeactivateResponse(BaseModel):
    """DELETE /api/v1/org/users/{id} response."""

    message: str
    user_id: str
    sessions_invalidated: int = Field(0, description="Number of sessions invalidated")


class MFAPolicyUpdateRequest(BaseModel):
    """Request body for updating MFA policy."""

    mfa_policy: str = Field(
        ..., description="MFA policy: 'optional' or 'mandatory'"
    )


class MFAPolicyUpdateResponse(BaseModel):
    """Response after updating MFA policy."""

    message: str
    mfa_policy: str


class SeatLimitResponse(BaseModel):
    """Response when seat limit is reached."""

    detail: str
    current_users: int
    seat_limit: int
    upgrade_required: bool = True


# ---------------------------------------------------------------------------
# Public signup (Requirement 8.6)
# ---------------------------------------------------------------------------


class PublicSignupRequest(BaseModel):
    """POST /api/v1/auth/signup request body — public, no auth required."""

    org_name: str = Field(
        ..., min_length=1, max_length=255, description="Workshop / organisation name"
    )
    admin_email: EmailStr = Field(..., description="Email for the Org_Admin account")
    admin_first_name: str = Field(
        ..., min_length=1, max_length=100, description="Admin first name"
    )
    admin_last_name: str = Field(
        ..., min_length=1, max_length=100, description="Admin last name"
    )
    password: str = Field(
        ..., min_length=8, max_length=128, description="Password for the admin account"
    )
    plan_id: str = Field(..., description="UUID of the subscription plan to sign up for")
    captcha_code: str = Field(
        ..., min_length=6, max_length=6, description="CAPTCHA verification code"
    )
    coupon_code: str | None = Field(
        None, max_length=100, description="Optional coupon code for signup discount"
    )
    billing_interval: Literal["weekly", "fortnightly", "monthly", "annual"] = Field(
        "monthly",
        description="Billing interval for the subscription (defaults to monthly)",
    )
    country_code: str | None = Field(
        None, max_length=2, description="ISO 3166-1 alpha-2 country code (e.g. NZ, AU)"
    )
    trade_family_slug: str | None = Field(
        None, max_length=100, description="Trade family slug (e.g. automotive-transport)"
    )


class OrgCarjamUsageResponse(BaseModel):
    """GET /api/v1/org/carjam-usage — org's own Carjam usage."""

    organisation_id: str
    organisation_name: str
    total_lookups: int
    included_in_plan: int
    overage_count: int
    overage_charge_nzd: float
    per_lookup_cost_nzd: float


class PublicSignupResponse(BaseModel):
    """Response after a successful public signup.

    For paid plans (requires_payment=True): returns pending_signup_id,
    stripe_client_secret, plan_name, and payment_amount_cents so the
    frontend can proceed to the payment step. No Organisation or User
    records exist yet.

    For trial plans (requires_payment=False): returns organisation_id,
    admin_user_id, trial_ends_at, and signup_token as before.
    """

    message: str
    requires_payment: bool = False
    payment_amount_cents: int = 0
    admin_email: str

    # Billing breakdown (present when requires_payment is True)
    plan_amount_cents: int = 0
    gst_amount_cents: int = 0
    processing_fee_cents: int = 0
    gst_percentage: float = 0.0

    # Present when requires_payment is True (paid plan deferred flow)
    pending_signup_id: str | None = None
    stripe_client_secret: str | None = None
    plan_name: str | None = None

    # Present when requires_payment is False (trial plan immediate flow)
    organisation_id: str | None = None
    organisation_name: str | None = None
    plan_id: str | None = None
    admin_user_id: str | None = None
    trial_ends_at: datetime | None = None
    signup_token: str | None = None




class ConfirmPaymentRequest(BaseModel):
    """POST /api/v1/auth/signup/confirm-payment request body.

    Uses pending_signup_id (not organisation_id) to look up the
    Pending_Signup from Redis, preventing callers from referencing
    arbitrary organisations.

    Requirements: 7.1
    """

    payment_intent_id: str = Field(..., description="Stripe PaymentIntent ID")
    pending_signup_id: str = Field(
        ..., description="UUID of the pending signup stored in Redis"
    )


class SalespersonItem(BaseModel):
    """Single salesperson in the dropdown list."""

    id: str = Field(..., description="User UUID")
    name: str = Field(..., description="Display name (email)")


class SalespersonListResponse(BaseModel):
    """GET /api/v1/org/salespeople response."""

    salespeople: list[SalespersonItem] = Field(default_factory=list, description="List of salespeople")


# ---------------------------------------------------------------------------
# Sprint 7 — Business Entity Type (Req 29.1, 29.2, 30.1, 30.2)
# ---------------------------------------------------------------------------

import re
from datetime import date as _date
from pydantic import field_validator


class BusinessTypeUpdateRequest(BaseModel):
    """PUT /api/v1/organisations/{id}/business-type request body."""

    business_type: Literal[
        "sole_trader", "partnership", "company", "trust", "other"
    ] = Field(..., description="Legal entity classification")
    nzbn: str | None = Field(None, description="NZ Business Number (exactly 13 digits)")
    nz_company_number: str | None = Field(None, description="NZ Companies Office number")
    gst_registered: bool | None = Field(None, description="Whether GST registered")
    gst_registration_date: _date | None = Field(None, description="GST registration date")
    income_tax_year_end: _date | None = Field(None, description="Income tax year end date")
    provisional_tax_method: Literal["standard", "estimation", "ratio"] | None = Field(
        None, description="Provisional tax method"
    )

    @field_validator("nzbn")
    @classmethod
    def validate_nzbn(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not re.fullmatch(r"\d{13}", v):
            raise ValueError("NZBN must be exactly 13 digits")
        return v


class BusinessTypeResponse(BaseModel):
    """Response after updating business type."""

    business_type: str
    nzbn: str | None = None
    nz_company_number: str | None = None
    gst_registered: bool = False
    gst_registration_date: _date | None = None
    income_tax_year_end: _date | None = None
    provisional_tax_method: str | None = None
    message: str = "Business type updated"
