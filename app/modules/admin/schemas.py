"""Pydantic schemas for the Global Admin module."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class ProvisionOrganisationRequest(BaseModel):
    """POST /api/v1/admin/organisations request body."""

    name: str = Field(..., min_length=1, max_length=255, description="Organisation name")
    plan_id: str = Field(..., description="UUID of the subscription plan to assign")
    admin_email: EmailStr = Field(..., description="Email for the new Org_Admin user")
    status: str = Field(
        default="active",
        description="Initial org status (trial, active)",
    )


class ProvisionOrganisationResponse(BaseModel):
    """Response after provisioning a new organisation."""

    message: str
    organisation_id: str
    organisation_name: str
    plan_id: str
    admin_user_id: str
    admin_email: str
    invitation_expires_at: datetime


# ---------------------------------------------------------------------------
# Global Admin user creation
# ---------------------------------------------------------------------------


class CreateGlobalAdminRequest(BaseModel):
    """POST /api/v1/admin/users/global-admin request body."""

    email: EmailStr = Field(..., description="Email for the new Global Admin user")
    first_name: str | None = Field(None, max_length=100, description="First name")
    last_name: str | None = Field(None, max_length=100, description="Last name")
    password: str = Field(..., min_length=8, max_length=128, description="Initial password")


class CreateGlobalAdminResponse(BaseModel):
    """Response after creating a global admin user."""

    message: str
    user_id: str
    email: str


# ---------------------------------------------------------------------------
# Carjam usage monitoring (Req 16.1, 16.4)
# ---------------------------------------------------------------------------


class OrgCarjamUsageRow(BaseModel):
    """Single organisation's Carjam usage for the current billing month."""

    organisation_id: str
    organisation_name: str
    total_lookups: int = Field(..., description="Total Carjam lookups this month")
    included_in_plan: int = Field(..., description="Lookups included in subscription plan")
    overage_count: int = Field(..., description="Lookups exceeding plan allowance")
    overage_charge_nzd: float = Field(..., description="Overage charge accrued (NZD)")


class AdminCarjamUsageResponse(BaseModel):
    """GET /api/v1/admin/carjam-usage — all orgs' Carjam usage table."""

    per_lookup_cost_nzd: float = Field(..., description="Current per-lookup overage cost")
    organisations: list[OrgCarjamUsageRow]


class OrgCarjamUsageResponse(BaseModel):
    """GET /api/v1/org/carjam-usage — single org's own Carjam usage."""

    organisation_id: str
    organisation_name: str
    total_lookups: int
    included_in_plan: int
    overage_count: int
    overage_charge_nzd: float
    per_lookup_cost_nzd: float


# ---------------------------------------------------------------------------
# SMS usage monitoring & package schemas (Req 5.2, 5.4, 2.6, 2.7)
# ---------------------------------------------------------------------------


class SmsPackageTierPricing(BaseModel):
    """A single SMS package tier pricing entry (mirrors StorageTierPricing)."""

    tier_name: str = Field(..., min_length=1, max_length=100, description="Tier label (e.g. '500 SMS')")
    sms_quantity: int = Field(..., gt=0, description="Number of SMS credits in this package")
    price_nzd: float = Field(..., ge=0, description="One-time price in NZD for this package")


class OrgSmsUsageRow(BaseModel):
    """Single organisation's SMS usage for the current billing month."""

    organisation_id: str
    organisation_name: str
    total_sent: int = Field(..., description="Total business SMS sent this month")
    included_in_plan: int = Field(..., description="SMS included in subscription plan")
    package_credits_remaining: int = Field(..., description="Remaining credits from purchased packages")
    effective_quota: int = Field(..., description="Plan quota + package credits")
    overage_count: int = Field(..., description="SMS exceeding effective quota")
    overage_charge_nzd: float = Field(..., description="Overage charge accrued (NZD)")


class AdminSmsUsageResponse(BaseModel):
    """GET /api/v1/admin/sms-usage — all orgs' SMS usage table."""

    organisations: list[OrgSmsUsageRow]


class OrgSmsUsageResponse(BaseModel):
    """GET /api/v1/org/sms-usage — single org's own SMS usage."""

    organisation_id: str
    organisation_name: str
    total_sent: int
    included_in_plan: int
    package_credits_remaining: int
    effective_quota: int
    overage_count: int
    overage_charge_nzd: float
    per_sms_cost_nzd: float


class SmsPackagePurchaseResponse(BaseModel):
    """Single SMS package purchase record."""

    id: str
    tier_name: str
    sms_quantity: int
    price_nzd: float
    credits_remaining: int
    purchased_at: datetime


class SmsPackagePurchaseRequest(BaseModel):
    """POST /api/v1/org/sms-packages/purchase request body."""

    tier_name: str = Field(..., min_length=1, description="Name of the SMS package tier to purchase")



# ---------------------------------------------------------------------------
# SMTP / Email integration configuration (Req 33.1, 33.2, 33.3)
# ---------------------------------------------------------------------------


class SmtpConfigRequest(BaseModel):
    """PUT /api/v1/admin/integrations/smtp request body."""

    provider: str = Field(
        default="smtp",
        description="Email provider: brevo, sendgrid, or smtp",
    )
    api_key: str = Field(default="", description="API key for Brevo/SendGrid, or SMTP password")
    host: str = Field(default="", description="SMTP host (for custom SMTP provider)")
    port: int = Field(default=587, description="SMTP port (for custom SMTP provider)")
    username: str = Field(default="", description="SMTP username (for custom SMTP provider)")
    password: str = Field(default="", description="SMTP password (for custom SMTP provider)")
    domain: str = Field(..., min_length=1, description="Sending domain (e.g. workshoppro.nz)")
    from_email: str = Field(..., min_length=1, description="Default from email address")
    from_name: str = Field(..., min_length=1, description="Default from display name")
    reply_to: str = Field(default="", description="Default reply-to email address")


class SmtpConfigResponse(BaseModel):
    """Response after saving SMTP configuration."""

    message: str
    provider: str
    domain: str
    from_email: str
    from_name: str
    reply_to: str
    is_verified: bool


class SmtpTestEmailResponse(BaseModel):
    """Response after sending a test email."""

    success: bool
    message: str
    provider: str = ""
    error: str | None = None


# ---------------------------------------------------------------------------
# Twilio / SMS integration configuration (Req 36.1)
# ---------------------------------------------------------------------------


class TwilioConfigRequest(BaseModel):
    """PUT /api/v1/admin/integrations/twilio request body."""

    account_sid: str = Field(..., min_length=1, description="Twilio Account SID")
    auth_token: str = Field(..., min_length=1, description="Twilio Auth Token")
    sender_number: str = Field(
        ..., min_length=1, description="Default sender phone number (E.164 format)"
    )


class TwilioConfigResponse(BaseModel):
    """Response after saving Twilio configuration."""

    message: str
    account_sid_last4: str = Field(
        ..., description="Last 4 chars of Account SID for display"
    )
    sender_number: str
    is_verified: bool


class TwilioTestSmsRequest(BaseModel):
    """POST /api/v1/admin/integrations/twilio/test request body."""

    to_number: str = Field(
        ..., min_length=1, description="Phone number to send test SMS to (E.164)"
    )
    message: str | None = Field(
        None, max_length=320, description="Custom message body (optional, defaults to test message)"
    )


class TwilioTestSmsResponse(BaseModel):
    """Response after sending a test SMS."""

    success: bool
    message: str
    error: str | None = None


# ---------------------------------------------------------------------------
# Carjam integration configuration (Req 48.3)
# ---------------------------------------------------------------------------


class CarjamConfigRequest(BaseModel):
    """PUT /api/v1/admin/integrations/carjam request body."""

    api_key: str | None = Field(None, min_length=1, description="Carjam API key (only send if changing)")
    endpoint_url: str | None = Field(None, min_length=1, description="Carjam API endpoint URL")
    per_lookup_cost_nzd: float | None = Field(
        None, ge=0, description="Cost per basic Carjam lookup in NZD"
    )
    abcd_per_lookup_cost_nzd: float | None = Field(
        None, ge=0, description="Cost per ABCD (lower-cost) Carjam lookup in NZD"
    )
    global_rate_limit_per_minute: int | None = Field(
        None, gt=0, description="Maximum Carjam API calls per minute (platform-wide)"
    )


class CarjamConfigResponse(BaseModel):
    """Response after saving Carjam configuration."""

    message: str
    endpoint_url: str
    per_lookup_cost_nzd: float
    abcd_per_lookup_cost_nzd: float = 0.05
    global_rate_limit_per_minute: int
    api_key_last4: str = Field(
        ..., description="Last 4 chars of API key for display"
    )
    is_verified: bool


class CarjamTestResponse(BaseModel):
    """Response after testing Carjam connection."""

    success: bool
    message: str
    error: str | None = None


# ---------------------------------------------------------------------------
# Global Stripe integration configuration (Req 48.4)
# ---------------------------------------------------------------------------


class StripeConfigRequest(BaseModel):
    """PUT /api/v1/admin/integrations/stripe request body."""

    platform_account_id: str | None = Field(
        default=None, min_length=1, description="Stripe platform account ID"
    )
    webhook_endpoint: str | None = Field(
        default=None, min_length=1, description="Stripe webhook endpoint URL"
    )
    signing_secret: str | None = Field(
        default=None, min_length=1, description="Stripe webhook signing secret"
    )
    publishable_key: str | None = Field(
        default=None, description="Stripe publishable key (pk_test_... or pk_live_...)"
    )
    secret_key: str | None = Field(
        default=None, description="Stripe secret key (sk_test_... or sk_live_...)"
    )


class StripeConfigResponse(BaseModel):
    """Response after saving Stripe configuration."""

    message: str
    platform_account_last4: str = Field(
        ..., description="Last 4 chars of platform account ID for display"
    )
    webhook_endpoint: str
    is_verified: bool


class StripeTestResponse(BaseModel):
    """Response after testing Stripe connection."""

    success: bool
    message: str
    error: str | None = None


# ---------------------------------------------------------------------------
# Generic integration config GET response (Req 48.1)
# ---------------------------------------------------------------------------


class IntegrationConfigGetResponse(BaseModel):
    """GET /api/v1/admin/integrations/{name} response — non-secret fields only."""

    name: str
    is_verified: bool
    updated_at: datetime | None = None
    fields: dict = Field(
        default_factory=dict,
        description="Non-secret configuration fields",
    )


# ---------------------------------------------------------------------------
# Subscription Plan Management (Req 40.1, 40.2, 40.3, 40.4)
# ---------------------------------------------------------------------------


class StorageTierPricing(BaseModel):
    """A single storage tier pricing entry."""

    tier_name: str = Field(..., min_length=1, max_length=100, description="Tier label (e.g. '10 GB')")
    size_gb: int = Field(..., gt=0, description="Storage increment in GB")
    price_nzd_per_month: float = Field(..., ge=0, description="Monthly price in NZD for this tier")


class IntervalConfigItem(BaseModel):
    """Single interval configuration entry."""

    interval: Literal["weekly", "fortnightly", "monthly", "annual"]
    enabled: bool = False
    discount_percent: float = Field(default=0, ge=0, le=100)


class IntervalPricing(BaseModel):
    """Computed interval pricing for API responses."""

    interval: str
    enabled: bool
    discount_percent: float
    effective_price: float
    savings_amount: float
    equivalent_monthly: float


class PlanCreateRequest(BaseModel):
    """POST /api/v1/admin/plans request body."""

    name: str = Field(..., min_length=1, max_length=100, description="Plan name")
    monthly_price_nzd: float = Field(..., ge=0, description="Monthly price in NZD")
    user_seats: int = Field(..., gt=0, description="Number of user seats included")
    storage_quota_gb: int = Field(..., gt=0, description="Storage quota in GB")
    carjam_lookups_included: int = Field(..., ge=0, description="Carjam lookups included per month")
    enabled_modules: list[str] = Field(default_factory=list, description="List of enabled feature modules")
    is_public: bool = Field(default=True, description="Visible on public signup page")
    storage_tier_pricing: list[StorageTierPricing] = Field(
        default_factory=list,
        description="Storage add-on pricing tiers",
    )
    trial_duration: int = Field(default=0, ge=0, description="Trial period length (0 = no trial)")
    trial_duration_unit: str = Field(default="days", description="Trial period unit: days, weeks, or months")
    sms_included: bool = Field(default=False, description="Whether SMS services are enabled for this plan")
    per_sms_cost_nzd: float = Field(default=0, ge=0, description="Cost per SMS message in NZD beyond included quota")
    sms_included_quota: int = Field(default=0, ge=0, description="Number of SMS messages included per billing month")
    sms_package_pricing: list[SmsPackageTierPricing] = Field(
        default_factory=list,
        description="SMS package add-on pricing tiers",
    )
    interval_config: list[IntervalConfigItem] | None = Field(
        default=None,
        description="Billing interval configuration; defaults to monthly-only when not provided",
    )


class PlanUpdateRequest(BaseModel):
    """PUT /api/v1/admin/plans/{id} request body. All fields optional."""

    name: str | None = Field(None, min_length=1, max_length=100, description="Plan name")
    monthly_price_nzd: float | None = Field(None, ge=0, description="Monthly price in NZD")
    user_seats: int | None = Field(None, gt=0, description="Number of user seats included")
    storage_quota_gb: int | None = Field(None, gt=0, description="Storage quota in GB")
    carjam_lookups_included: int | None = Field(None, ge=0, description="Carjam lookups included per month")
    enabled_modules: list[str] | None = Field(None, description="List of enabled feature modules")
    is_public: bool | None = Field(None, description="Visible on public signup page")
    storage_tier_pricing: list[StorageTierPricing] | None = Field(
        None,
        description="Storage add-on pricing tiers",
    )
    trial_duration: int | None = Field(None, ge=0, description="Trial period length (0 = no trial)")
    trial_duration_unit: str | None = Field(None, description="Trial period unit: days, weeks, or months")
    sms_included: bool | None = Field(None, description="Whether SMS services are enabled for this plan")
    per_sms_cost_nzd: float | None = Field(None, ge=0, description="Cost per SMS message in NZD beyond included quota")
    sms_included_quota: int | None = Field(None, ge=0, description="Number of SMS messages included per billing month")
    sms_package_pricing: list[SmsPackageTierPricing] | None = Field(
        None,
        description="SMS package add-on pricing tiers",
    )
    interval_config: list[IntervalConfigItem] | None = Field(
        default=None,
        description="Billing interval configuration",
    )


class PlanResponse(BaseModel):
    """Single subscription plan response."""

    id: str
    name: str
    monthly_price_nzd: float
    user_seats: int
    storage_quota_gb: int
    carjam_lookups_included: int
    enabled_modules: list[str]
    is_public: bool
    is_archived: bool
    storage_tier_pricing: list[StorageTierPricing]
    trial_duration: int = 0
    trial_duration_unit: str = "days"
    sms_included: bool = False
    per_sms_cost_nzd: float = 0
    sms_included_quota: int = 0
    sms_package_pricing: list[SmsPackageTierPricing] = Field(default_factory=list)
    interval_config: list[IntervalConfigItem] = Field(default_factory=list)
    intervals: list[IntervalPricing] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class PlanListResponse(BaseModel):
    """GET /api/v1/admin/plans response."""

    plans: list[PlanResponse]
    total: int


# ---------------------------------------------------------------------------
# Global Admin Reports (Req 46.1–46.5)
# ---------------------------------------------------------------------------


class MrrPlanBreakdown(BaseModel):
    """MRR contribution from a single plan."""

    plan_id: str
    plan_name: str
    active_orgs: int = Field(..., description="Number of active orgs on this plan")
    mrr_nzd: float = Field(..., description="MRR from this plan (active_orgs × monthly_price)")


class MrrMonthTrend(BaseModel):
    """MRR for a single month in the trend series."""

    month: str = Field(..., description="Month label (YYYY-MM)")
    mrr_nzd: float


class MrrIntervalBreakdown(BaseModel):
    """MRR contribution from a single billing interval."""

    interval: str = Field(..., description="Billing interval (weekly, fortnightly, monthly, annual)")
    org_count: int = Field(..., description="Number of active orgs on this interval")
    mrr_nzd: float = Field(..., description="Total MRR contribution from this interval")


class MrrReportResponse(BaseModel):
    """GET /api/v1/admin/reports/mrr — Platform MRR report."""

    total_mrr_nzd: float = Field(..., description="Total platform MRR")
    plan_breakdown: list[MrrPlanBreakdown]
    month_over_month: list[MrrMonthTrend]
    interval_breakdown: list[MrrIntervalBreakdown] = Field(
        default_factory=list,
        description="MRR breakdown by billing interval",
    )


class OrgOverviewRow(BaseModel):
    """Single row in the organisation overview table."""

    organisation_id: str
    organisation_name: str
    plan_name: str
    signup_date: datetime
    trial_status: str = Field(..., description="trial / active / expired")
    billing_status: str = Field(..., description="Organisation status")
    storage_used_bytes: int
    storage_quota_gb: int
    carjam_lookups_this_month: int
    last_login_at: datetime | None = None


class OrgOverviewResponse(BaseModel):
    """GET /api/v1/admin/reports/organisations — Organisation overview."""

    organisations: list[OrgOverviewRow]
    total: int


class CarjamCostReportResponse(BaseModel):
    """GET /api/v1/admin/reports/carjam-cost — Carjam cost vs revenue."""

    total_lookups: int = Field(..., description="Total Carjam API calls this month")
    total_cost_nzd: float = Field(..., description="Total cost to platform")
    total_revenue_nzd: float = Field(..., description="Total overage revenue from orgs")
    net_nzd: float = Field(..., description="Revenue minus cost (positive = profit)")
    per_lookup_cost_nzd: float


class ChurnOrgRow(BaseModel):
    """Single churned organisation in the churn report."""

    organisation_id: str
    organisation_name: str
    plan_name: str
    status: str = Field(..., description="suspended or deleted")
    signup_date: datetime
    churned_at: datetime = Field(..., description="When the org was suspended/deleted")
    subscription_duration_days: int


class ChurnReportResponse(BaseModel):
    """GET /api/v1/admin/reports/churn — Churn report."""

    churned_organisations: list[ChurnOrgRow]
    total: int


class VehicleDbStatsResponse(BaseModel):
    """GET /api/v1/admin/vehicle-db — Global Vehicle Database stats."""

    total_records: int
    total_lookups_all_orgs: int = Field(..., description="Sum of all org Carjam lookups this month")
    cache_hit_rate: float = Field(..., description="Estimated cache hit rate (0.0–1.0)")



# ---------------------------------------------------------------------------
# Organisation Management (Req 47.1, 47.2, 47.3)
# ---------------------------------------------------------------------------


class OrgListParams(BaseModel):
    """Query parameters for GET /api/v1/admin/organisations."""

    search: str | None = Field(None, description="Search by org name")
    status: str | None = Field(None, description="Filter by status")
    plan_id: str | None = Field(None, description="Filter by plan UUID")
    sort_by: str = Field(default="created_at", description="Sort field")
    sort_order: str = Field(default="desc", description="asc or desc")
    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=25, ge=1, le=100, description="Items per page")


class OrgListItem(BaseModel):
    """Single organisation row in the admin list."""

    id: str
    name: str
    plan_id: str
    plan_name: str
    status: str
    storage_quota_gb: int
    storage_used_bytes: int
    carjam_lookups_this_month: int
    next_billing_date: datetime | None = None
    billing_interval: str = "monthly"
    created_at: datetime
    updated_at: datetime


class OrgListResponse(BaseModel):
    """GET /api/v1/admin/organisations response."""

    organisations: list[OrgListItem]
    total: int
    page: int
    page_size: int


class OrgUpdateRequest(BaseModel):
    """PUT /api/v1/admin/organisations/{id} request body."""

    action: str = Field(
        ...,
        description="Action: suspend, reinstate, activate, deactivate, delete_request, hard_delete_request, move_plan, set_billing_date",
    )
    reason: str | None = Field(
        None,
        min_length=1,
        max_length=1000,
        description="Reason for suspend/delete/deactivate (required for those actions)",
    )
    new_plan_id: str | None = Field(
        None,
        description="Target plan UUID (required for move_plan action)",
    )
    next_billing_date: str | None = Field(
        None,
        description="Next billing date in ISO format (required for set_billing_date action)",
    )
    notify_org_admin: bool = Field(
        default=False,
        description="Send email notification to Org_Admin",
    )


class OrgUpdateResponse(BaseModel):
    """Response after updating an organisation."""

    message: str
    organisation_id: str
    organisation_name: str
    status: str
    previous_status: str | None = None
    previous_plan_id: str | None = None
    new_plan_id: str | None = None


class OrgDeleteRequest(BaseModel):
    """DELETE /api/v1/admin/organisations/{id} request body."""

    reason: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Reason for deletion (required, stored in audit log)",
    )
    confirmation_token: str = Field(
        ...,
        description="Confirmation token from the delete_request step",
    )
    notify_org_admin: bool = Field(
        default=False,
        description="Send email notification to Org_Admin",
    )


class OrgDeleteResponse(BaseModel):
    """Response after deleting an organisation."""

    message: str
    organisation_id: str
    organisation_name: str


class OrgDeleteRequestResponse(BaseModel):
    """Response from the delete_request action (step 1 of multi-step delete)."""

    message: str
    organisation_id: str
    organisation_name: str
    confirmation_token: str
    expires_in_seconds: int = Field(default=300, description="Token validity in seconds")


class OrgHardDeleteRequest(BaseModel):
    """DELETE /api/v1/admin/organisations/{id}/hard request body."""

    reason: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Reason for permanent deletion (required, stored in audit log)",
    )
    confirmation_token: str = Field(
        ...,
        description="Confirmation token from the hard_delete_request step",
    )
    confirm_text: str = Field(
        ...,
        description="User must type 'PERMANENTLY DELETE' to confirm",
    )


class OrgHardDeleteResponse(BaseModel):
    """Response after permanently deleting an organisation from database."""

    message: str
    organisation_id: str
    organisation_name: str
    records_deleted: dict  # Count of related records deleted


# ---------------------------------------------------------------------------
# Error Logging (Req 49.1–49.7)
# ---------------------------------------------------------------------------


class ErrorLogSummaryCount(BaseModel):
    """Error count for a single severity or category bucket."""

    label: str
    count_1h: int = 0
    count_24h: int = 0
    count_7d: int = 0


class ErrorLogDashboardResponse(BaseModel):
    """GET /api/v1/admin/errors/dashboard — real-time error counts."""

    by_severity: list[ErrorLogSummaryCount]
    by_category: list[ErrorLogSummaryCount]
    total_1h: int = 0
    total_24h: int = 0
    total_7d: int = 0


class ErrorLogListItem(BaseModel):
    """Single error in the live feed / list view."""

    id: str
    severity: str
    category: str
    module: str
    function_name: str | None = None
    message: str
    org_id: str | None = None
    user_id: str | None = None
    status: str
    created_at: datetime


class ErrorLogListParams(BaseModel):
    """Query parameters for GET /api/v1/admin/errors."""

    severity: str | None = Field(None, description="Filter by severity")
    category: str | None = Field(None, description="Filter by category")
    status: str | None = Field(None, description="Filter by status")
    org_id: str | None = Field(None, description="Filter by organisation")
    keyword: str | None = Field(None, description="Search keyword in message")
    date_from: datetime | None = Field(None, description="Start of date range")
    date_to: datetime | None = Field(None, description="End of date range")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=100)


class ErrorLogListResponse(BaseModel):
    """GET /api/v1/admin/errors — paginated error list."""

    errors: list[ErrorLogListItem]
    total: int
    page: int
    page_size: int


class ErrorLogDetailResponse(BaseModel):
    """GET /api/v1/admin/errors/{id} — full error detail."""

    id: str
    severity: str
    category: str
    module: str
    function_name: str | None = None
    message: str
    stack_trace: str | None = None
    org_id: str | None = None
    user_id: str | None = None
    http_method: str | None = None
    http_endpoint: str | None = None
    request_body_sanitised: dict | None = None
    response_body_sanitised: dict | None = None
    status: str
    resolution_notes: str | None = None
    created_at: datetime


class ErrorLogStatusUpdateRequest(BaseModel):
    """PUT /api/v1/admin/errors/{id}/status — update error status."""

    status: str = Field(..., description="New status: open, investigating, or resolved")
    resolution_notes: str | None = Field(None, description="Notes about the resolution")


class ErrorLogStatusUpdateResponse(BaseModel):
    """Response after updating error status."""

    message: str
    id: str
    status: str
    resolution_notes: str | None = None


class ErrorLogExportParams(BaseModel):
    """Query parameters for GET /api/v1/admin/errors/export."""

    format: str = Field(default="json", description="Export format: csv or json")
    date_from: datetime | None = Field(None, description="Start of date range")
    date_to: datetime | None = Field(None, description="End of date range")
    severity: str | None = Field(None, description="Filter by severity")
    category: str | None = Field(None, description="Filter by category")


# ---------------------------------------------------------------------------
# Platform Settings (Task 23.4)
# ---------------------------------------------------------------------------


class TermsAndConditionsEntry(BaseModel):
    """A single version of the platform T&C."""

    version: int
    content: str
    updated_at: str


class StoragePricingConfig(BaseModel):
    """Storage pricing configuration."""

    increment_gb: int = 1
    price_per_gb_nzd: float = 0.50


class SignupBillingConfig(BaseModel):
    """GST and Stripe fee configuration for signup billing."""

    gst_percentage: float = Field(default=15.0, description="GST percentage applied to plan price")
    stripe_fee_percentage: float = Field(default=2.9, description="Stripe fee percentage")
    stripe_fee_fixed_cents: int = Field(default=30, description="Stripe fixed fee per transaction in cents")
    pass_fees_to_customer: bool = Field(default=True, description="Whether to pass Stripe fees to customer")


class PlatformSettingsResponse(BaseModel):
    """GET /api/v1/admin/settings response."""

    terms_and_conditions: TermsAndConditionsEntry | None = None
    terms_history: list[TermsAndConditionsEntry] = Field(default_factory=list)
    announcement_banner: str | None = None
    announcement_active: bool = False
    storage_pricing: StoragePricingConfig = Field(default_factory=StoragePricingConfig)
    signup_billing: SignupBillingConfig = Field(default_factory=SignupBillingConfig)


class PlatformSettingsUpdateRequest(BaseModel):
    """PUT /api/v1/admin/settings request body.

    All fields are optional — only supplied fields are updated.
    """

    terms_and_conditions: str | None = Field(
        None, description="New platform T&C content (triggers re-accept prompt)"
    )
    announcement_banner: str | None = Field(
        None, description="Announcement banner text (empty string to clear)"
    )
    announcement_active: bool | None = Field(
        None, description="Whether the announcement banner is visible"
    )
    storage_pricing: StoragePricingConfig | None = Field(
        None, description="Storage pricing configuration"
    )
    signup_billing: SignupBillingConfig | None = Field(
        None, description="GST and Stripe fee configuration for signup"
    )


class PlatformSettingsUpdateResponse(BaseModel):
    """PUT /api/v1/admin/settings response."""

    message: str
    terms_version: int | None = None
    announcement_banner: str | None = None
    announcement_active: bool | None = None
    storage_pricing: StoragePricingConfig | None = None
    signup_billing: SignupBillingConfig | None = None


class GlobalVehicleSearchResult(BaseModel):
    """A single vehicle record from the Global Vehicle DB."""

    id: str
    rego: str
    make: str | None = None
    model: str | None = None
    year: int | None = None
    colour: str | None = None
    body_type: str | None = None
    fuel_type: str | None = None
    engine_size: str | None = None
    num_seats: int | None = None
    wof_expiry: str | None = None
    registration_expiry: str | None = None
    odometer_last_recorded: int | None = None
    last_pulled_at: str | None = None
    created_at: str | None = None
    lookup_type: str | None = None
    # Extended Carjam fields
    vin: str | None = None
    chassis: str | None = None
    engine_no: str | None = None
    transmission: str | None = None
    country_of_origin: str | None = None
    number_of_owners: int | None = None
    vehicle_type: str | None = None
    reported_stolen: str | None = None
    power_kw: int | None = None
    tare_weight: int | None = None
    gross_vehicle_mass: int | None = None
    date_first_registered_nz: str | None = None
    plate_type: str | None = None
    submodel: str | None = None
    second_colour: str | None = None


class GlobalVehicleSearchResponse(BaseModel):
    """GET /api/v1/admin/vehicle-db/{rego} response."""

    results: list[GlobalVehicleSearchResult]
    total: int


class GlobalVehicleRefreshResponse(BaseModel):
    """POST /api/v1/admin/vehicle-db/{rego}/refresh response."""

    message: str
    vehicle: GlobalVehicleSearchResult | None = None


class GlobalVehicleDeleteResponse(BaseModel):
    """DELETE /api/v1/admin/vehicle-db/stale response."""

    message: str
    deleted_count: int


# ---------------------------------------------------------------------------
# Audit log viewing schemas (Req 51.1, 51.2, 51.4)
# ---------------------------------------------------------------------------


class AuditLogEntry(BaseModel):
    """Single audit log row returned to the caller."""

    id: str
    org_id: str | None = None
    user_id: str | None = None
    action: str
    entity_type: str
    entity_id: str | None = None
    before_value: dict | None = None
    after_value: dict | None = None
    ip_address: str | None = None
    device_info: str | None = None
    created_at: str


class AuditLogListParams(BaseModel):
    """Query parameters for audit log listing."""

    page: int = 1
    page_size: int = 50
    action: str | None = None
    entity_type: str | None = None
    user_id: str | None = None
    date_from: str | None = None
    date_to: str | None = None


class AuditLogListResponse(BaseModel):
    """Paginated audit log response."""

    entries: list[AuditLogEntry]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Integration Cost Dashboard (Global Admin)
# ---------------------------------------------------------------------------


class IntegrationCostCard(BaseModel):
    """Cost/usage summary for a single integration."""

    name: str
    status: str  # healthy | degraded | down | not_configured
    total_cost_nzd: float = 0.0
    total_usage: int = 0
    usage_label: str = "requests"
    breakdown: dict = Field(default_factory=dict)
    balance: float | None = None
    balance_currency: str | None = None
    last_checked: str | None = None
    token_last_refresh: str | None = None
    token_expires_at: str | None = None


class IntegrationCostDashboardResponse(BaseModel):
    """GET /api/v1/admin/dashboard/integration-costs — all integration costs."""

    period: str  # "daily" | "weekly" | "monthly"
    carjam: IntegrationCostCard
    sms: IntegrationCostCard
    smtp: IntegrationCostCard
    stripe: IntegrationCostCard


# ---------------------------------------------------------------------------
# Coupon System (Req 10.1–10.8)
# ---------------------------------------------------------------------------


class CouponCreateRequest(BaseModel):
    """POST /api/v1/admin/coupons request body."""

    code: str = Field(..., min_length=3, max_length=50, description="Unique coupon code")
    description: str | None = Field(None, max_length=255, description="Coupon description")
    discount_type: str = Field(..., description="Discount type: percentage, fixed_amount, or trial_extension")
    discount_value: float = Field(..., gt=0, description="Discount value (percentage, NZD amount, or trial days)")
    duration_months: int | None = Field(None, gt=0, description="Number of billing months the discount applies")
    usage_limit: int | None = Field(None, gt=0, description="Maximum number of redemptions allowed")
    starts_at: datetime | None = None
    expires_at: datetime | None = None


class CouponUpdateRequest(BaseModel):
    """PUT /api/v1/admin/coupons/{id} request body. All fields optional."""

    description: str | None = Field(None, max_length=255, description="Coupon description")
    discount_value: float | None = Field(None, gt=0, description="Discount value")
    duration_months: int | None = Field(None, gt=0, description="Number of billing months")
    usage_limit: int | None = Field(None, gt=0, description="Maximum redemptions")
    is_active: bool | None = None
    starts_at: datetime | None = None
    expires_at: datetime | None = None


class CouponResponse(BaseModel):
    """Single coupon response."""

    id: str
    code: str
    description: str | None = None
    discount_type: str
    discount_value: float
    duration_months: int | None = None
    usage_limit: int | None = None
    times_redeemed: int = 0
    is_active: bool = True
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CouponListResponse(BaseModel):
    """GET /api/v1/admin/coupons response."""

    coupons: list[CouponResponse]
    total: int


class CouponRedemptionRow(BaseModel):
    """Single coupon redemption record."""

    id: str
    org_id: str
    organisation_name: str
    applied_at: datetime
    billing_months_used: int
    is_expired: bool


class CouponDetailResponse(CouponResponse):
    """GET /api/v1/admin/coupons/{id} response — coupon with redemptions."""

    redemptions: list[CouponRedemptionRow] = Field(default_factory=list)


class CouponValidateRequest(BaseModel):
    """POST /api/v1/coupons/validate request body."""

    code: str = Field(..., min_length=1, description="Coupon code to validate")


class CouponValidateResponse(BaseModel):
    """POST /api/v1/coupons/validate response."""

    valid: bool
    coupon: CouponResponse | None = None
    error: str | None = None


class CouponRedeemRequest(BaseModel):
    """POST /api/v1/coupons/redeem request body."""

    code: str = Field(..., min_length=1, description="Coupon code to redeem")
    org_id: str = Field(..., description="Organisation UUID to apply the coupon to")


class CouponRedeemResponse(BaseModel):
    """POST /api/v1/coupons/redeem response."""

    message: str
    organisation_coupon_id: str


# ---------------------------------------------------------------------------
# Storage Package schemas — Requirements: 2.1–2.5
# ---------------------------------------------------------------------------


class StoragePackageCreateRequest(BaseModel):
    """POST /api/v1/admin/storage-packages request body."""

    name: str = Field(..., min_length=1, max_length=100, description="Package name")
    storage_gb: int = Field(..., gt=0, description="Storage amount in GB")
    price_nzd_per_month: float = Field(..., ge=0, description="Monthly price in NZD")
    description: str | None = Field(None, max_length=255, description="Optional description")
    sort_order: int = Field(default=0, description="Display sort order")


class StoragePackageUpdateRequest(BaseModel):
    """PUT /api/v1/admin/storage-packages/{id} request body. All fields optional."""

    name: str | None = Field(None, min_length=1, max_length=100, description="Package name")
    storage_gb: int | None = Field(None, gt=0, description="Storage amount in GB")
    price_nzd_per_month: float | None = Field(None, ge=0, description="Monthly price in NZD")
    description: str | None = Field(None, max_length=255, description="Optional description")
    is_active: bool | None = Field(None, description="Whether the package is active")
    sort_order: int | None = Field(None, description="Display sort order")


class StoragePackageResponse(BaseModel):
    """Single storage package response."""

    id: str
    name: str
    storage_gb: int
    price_nzd_per_month: float
    description: str | None
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


class StoragePackageListResponse(BaseModel):
    """GET /api/v1/admin/storage-packages response."""

    packages: list[StoragePackageResponse]
    total: int
