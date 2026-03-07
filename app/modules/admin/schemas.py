"""Pydantic schemas for the Global Admin module."""

from __future__ import annotations

import uuid
from datetime import datetime

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

    api_key: str = Field(..., min_length=1, description="Carjam API key")
    endpoint_url: str = Field(..., min_length=1, description="Carjam API endpoint URL")
    per_lookup_cost_nzd: float = Field(
        ..., ge=0, description="Cost per Carjam lookup in NZD"
    )
    global_rate_limit_per_minute: int = Field(
        ..., gt=0, description="Maximum Carjam API calls per minute (platform-wide)"
    )


class CarjamConfigResponse(BaseModel):
    """Response after saving Carjam configuration."""

    message: str
    endpoint_url: str
    per_lookup_cost_nzd: float
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

    platform_account_id: str = Field(
        ..., min_length=1, description="Stripe platform account ID"
    )
    webhook_endpoint: str = Field(
        ..., min_length=1, description="Stripe webhook endpoint URL"
    )
    signing_secret: str = Field(
        ..., min_length=1, description="Stripe webhook signing secret"
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
    config: dict = Field(
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


class MrrReportResponse(BaseModel):
    """GET /api/v1/admin/reports/mrr — Platform MRR report."""

    total_mrr_nzd: float = Field(..., description="Total platform MRR")
    plan_breakdown: list[MrrPlanBreakdown]
    month_over_month: list[MrrMonthTrend]


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
        description="Action: suspend, reinstate, delete_request, move_plan",
    )
    reason: str | None = Field(
        None,
        min_length=1,
        max_length=1000,
        description="Reason for suspend/delete (required for those actions)",
    )
    new_plan_id: str | None = Field(
        None,
        description="Target plan UUID (required for move_plan action)",
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


class PlatformSettingsResponse(BaseModel):
    """GET /api/v1/admin/settings response."""

    terms_and_conditions: TermsAndConditionsEntry | None = None
    terms_history: list[TermsAndConditionsEntry] = Field(default_factory=list)
    announcement_banner: str | None = None
    announcement_active: bool = False


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


class PlatformSettingsUpdateResponse(BaseModel):
    """PUT /api/v1/admin/settings response."""

    message: str
    terms_version: int | None = None
    announcement_banner: str | None = None
    announcement_active: bool | None = None


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
