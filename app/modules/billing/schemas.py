"""Billing schemas — trial status and subscription lifecycle.

Requirements: 41.1, 41.2, 41.3, 41.4, 41.5
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class TrialStatusResponse(BaseModel):
    """Response for GET /api/v1/billing/trial — trial countdown data.

    Requirements: 41.3
    """

    is_trial: bool = Field(description="Whether the organisation is currently on a free trial")
    trial_ends_at: datetime | None = Field(
        default=None,
        description="UTC timestamp when the trial ends (null if not on trial)",
    )
    days_remaining: int = Field(
        default=0,
        description="Number of full days remaining in the trial (0 if not on trial)",
    )
    plan_name: str = Field(description="Name of the subscription plan")
    plan_monthly_price_nzd: float = Field(
        description="Monthly price in NZD that will be charged after trial ends",
    )
    status: str = Field(description="Current organisation status (trial, active, etc.)")


# ---------------------------------------------------------------------------
# Subscription invoice schemas — Requirements: 42.3
# ---------------------------------------------------------------------------


class InvoiceLineSummary(BaseModel):
    """Single line item summary from a Stripe invoice."""

    description: str = Field(default="", description="Line item description")
    amount: int = Field(default=0, description="Amount in cents")


class SubscriptionInvoiceResponse(BaseModel):
    """Past Stripe subscription invoice data.

    Requirements: 42.3
    """

    id: str = Field(description="Stripe invoice ID")
    number: str | None = Field(default=None, description="Invoice number")
    amount_due: int = Field(default=0, description="Amount due in cents")
    amount_paid: int = Field(default=0, description="Amount paid in cents")
    currency: str = Field(default="nzd", description="Currency code")
    status: str | None = Field(default=None, description="Invoice status")
    created: int | None = Field(default=None, description="Unix timestamp of creation")
    period_start: int | None = Field(default=None, description="Billing period start")
    period_end: int | None = Field(default=None, description="Billing period end")
    invoice_pdf: str | None = Field(default=None, description="URL to download PDF")
    hosted_invoice_url: str | None = Field(
        default=None, description="Hosted invoice page URL"
    )
    description: str | None = Field(default=None, description="Invoice description")
    lines_summary: list[InvoiceLineSummary] = Field(
        default_factory=list, description="Summary of line items"
    )


class BillingDashboardResponse(BaseModel):
    """Billing dashboard data for Org_Admin.

    Requirements: 42.3, 44.1
    """

    current_plan: str = Field(description="Current plan name")
    plan_monthly_price_nzd: float = Field(description="Base plan monthly price")
    next_billing_date: datetime | None = Field(
        default=None, description="Next billing date"
    )
    estimated_next_invoice_nzd: float = Field(
        default=0.0,
        description="Estimated next invoice subtotal excl. GST (plan + storage + overages)",
    )
    gst_amount_nzd: float = Field(
        default=0.0,
        description="Estimated GST amount on the next invoice",
    )
    processing_fee_nzd: float = Field(
        default=0.0,
        description="Estimated Stripe processing fee on the next invoice",
    )
    estimated_total_incl_nzd: float = Field(
        default=0.0,
        description="Estimated total including GST and processing fee",
    )
    storage_addon_charge_nzd: float = Field(
        default=0.0, description="Storage add-on charges this period"
    )
    carjam_overage_charge_nzd: float = Field(
        default=0.0, description="Carjam overage charges accrued"
    )
    carjam_lookups_used: int = Field(
        default=0, description="Carjam lookups used this month"
    )
    carjam_lookups_included: int = Field(
        default=0, description="Carjam lookups included in plan"
    )
    storage_used_gb: float = Field(default=0.0, description="Storage used in GB")
    storage_quota_gb: int = Field(default=0, description="Total storage quota in GB")
    user_seats: int = Field(default=0, description="User seats included in plan")
    carjam_lookups_included: int = Field(
        default=0, description="Carjam lookups included in plan"
    )
    org_status: str = Field(description="Organisation status")
    trial_ends_at: datetime | None = Field(
        default=None, description="UTC timestamp when the trial ends"
    )
    # Billing interval fields — Requirements: 9.1, 9.3, 9.4
    billing_interval: str = Field(
        default="monthly",
        description="Current billing interval (weekly, fortnightly, monthly, annual)",
    )
    interval_effective_price: float = Field(
        default=0.0,
        description="Effective price per billing cycle at the current interval",
    )
    equivalent_monthly_price: float = Field(
        default=0.0,
        description="Equivalent monthly cost for the current interval",
    )
    pending_interval_change: dict | None = Field(
        default=None,
        description="Pending interval change details (null if none scheduled)",
    )
    # Coupon fields
    active_coupon_code: str | None = Field(
        default=None, description="Active coupon code applied to this org"
    )
    discount_type: str | None = Field(
        default=None, description="Coupon discount type (percentage, fixed_amount, trial_extension)"
    )
    discount_value: float | None = Field(
        default=None, description="Coupon discount value"
    )
    duration_months: int | None = Field(
        default=None, description="Coupon duration in months (null = perpetual)"
    )
    coupon_duration_cycles: int | None = Field(
        default=None,
        description="Coupon duration converted to billing cycles for the active interval (null = perpetual)",
    )
    effective_price_nzd: float | None = Field(
        default=None, description="Effective monthly price after coupon discount"
    )
    coupon_is_expired: bool = Field(
        default=False, description="Whether the applied coupon has expired"
    )
    # SMS usage fields
    sms_included: bool = Field(
        default=False, description="Whether SMS is included in the plan"
    )
    sms_included_quota: int = Field(
        default=0, description="SMS messages included in plan per month"
    )
    sms_sent_this_month: int = Field(
        default=0, description="SMS messages sent this billing month"
    )
    per_sms_cost_nzd: float = Field(
        default=0.0, description="Cost per SMS beyond included quota"
    )
    sms_overage_charge_nzd: float = Field(
        default=0.0, description="SMS overage charges accrued this month"
    )
    sms_credits_remaining: int = Field(
        default=0, description="Prepaid SMS credits remaining from package purchases"
    )
    # Storage add-on fields — Requirements: 6.1–6.4
    storage_addon_gb: int | None = Field(
        default=None, description="Current storage add-on GB (null if no add-on)"
    )
    storage_addon_price_nzd: float | None = Field(
        default=None, description="Storage add-on monthly price in NZD"
    )
    storage_addon_package_name: str | None = Field(
        default=None, description="Storage add-on package name (null for custom or no add-on)"
    )
    past_invoices: list[SubscriptionInvoiceResponse] = Field(
        default_factory=list, description="Past subscription invoices"
    )

# ---------------------------------------------------------------------------
# Interval change schemas — Requirements: 7.1, 7.2, 9.1, 9.3, 9.4
# ---------------------------------------------------------------------------


class IntervalChangeRequest(BaseModel):
    """POST /api/v1/billing/change-interval request body.

    Requirements: 7.1, 7.2
    """

    billing_interval: Literal["weekly", "fortnightly", "monthly", "annual"] = Field(
        description="Target billing interval"
    )


class IntervalChangeResponse(BaseModel):
    """Response for interval change.

    Requirements: 7.1, 7.2
    """

    success: bool = Field(description="Whether the interval change was applied or scheduled")
    message: str = Field(description="Human-readable result message")
    new_interval: str = Field(description="The new billing interval")
    new_effective_price: float = Field(description="Effective price at the new interval")
    effective_immediately: bool = Field(
        description="Whether the change was applied immediately (True) or scheduled (False)"
    )
    effective_at: datetime | None = Field(
        default=None,
        description="When the change takes effect (null if immediate)",
    )


# ---------------------------------------------------------------------------
# Plan upgrade / downgrade schemas — Requirements: 43.1, 43.2, 43.3, 43.4
# ---------------------------------------------------------------------------


class PlanChangeRequest(BaseModel):
    """Request body for POST /api/v1/billing/upgrade and /downgrade.

    Requirements: 43.1, 8.4
    """

    new_plan_id: str = Field(description="UUID of the target subscription plan")
    billing_interval: str | None = Field(
        default=None,
        description="Optional billing interval for the new plan (defaults to current org interval)",
    )


class PlanUpgradeResponse(BaseModel):
    """Response for POST /api/v1/billing/upgrade.

    Requirements: 43.2
    """

    success: bool = Field(description="Whether the upgrade was applied")
    message: str = Field(description="Human-readable result message")
    new_plan_name: str = Field(description="Name of the new plan")
    prorated_charge_nzd: float = Field(
        default=0.0,
        description="Prorated charge in NZD for the remainder of the current billing period",
    )
    effective_immediately: bool = Field(
        default=True,
        description="Whether the change was applied immediately",
    )


class PlanDowngradeResponse(BaseModel):
    """Response for POST /api/v1/billing/downgrade.

    Requirements: 43.3, 43.4
    """

    success: bool = Field(description="Whether the downgrade was scheduled")
    message: str = Field(description="Human-readable result message")
    new_plan_name: str = Field(description="Name of the target plan")
    effective_at: datetime | None = Field(
        default=None,
        description="When the downgrade takes effect (start of next billing period)",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Warnings about storage or user limits that must be resolved",
    )


# ---------------------------------------------------------------------------
# Storage add-on schemas — Requirements: 4.1–4.5, 5.1–5.2
# ---------------------------------------------------------------------------


class StorageAddonPurchaseRequest(BaseModel):
    """POST /api/v1/billing/storage-addon request body.

    Exactly one of package_id or custom_gb must be provided.
    """

    package_id: str | None = Field(None, description="UUID of the storage package to purchase")
    custom_gb: int | None = Field(None, gt=0, description="Custom storage amount in GB")

    @model_validator(mode="after")
    def _exactly_one(self) -> StorageAddonPurchaseRequest:
        if self.package_id and self.custom_gb:
            raise ValueError("Provide either package_id or custom_gb, not both")
        if not self.package_id and not self.custom_gb:
            raise ValueError("Provide either package_id or custom_gb")
        return self


class StorageAddonResizeRequest(BaseModel):
    """PUT /api/v1/billing/storage-addon request body.

    Exactly one of package_id or custom_gb must be provided.
    """

    package_id: str | None = Field(None, description="UUID of the storage package to resize to")
    custom_gb: int | None = Field(None, gt=0, description="Custom storage amount in GB")

    @model_validator(mode="after")
    def _exactly_one(self) -> StorageAddonResizeRequest:
        if self.package_id and self.custom_gb:
            raise ValueError("Provide either package_id or custom_gb, not both")
        if not self.package_id and not self.custom_gb:
            raise ValueError("Provide either package_id or custom_gb")
        return self


class StorageAddonResponse(BaseModel):
    """Single storage add-on response."""

    id: str
    package_name: str | None = Field(description="Package name (null for custom add-ons)")
    quantity_gb: int
    price_nzd_per_month: float
    is_custom: bool
    purchased_at: datetime


class StorageAddonStatusResponse(BaseModel):
    """GET /api/v1/billing/storage-addon response."""

    current_addon: StorageAddonResponse | None
    available_packages: list[dict] = Field(
        description="Available storage packages for purchase/resize"
    )
    fallback_price_per_gb_nzd: float
    base_quota_gb: int
    total_quota_gb: int
    storage_used_gb: float


# ---------------------------------------------------------------------------
# Payment method enforcement schemas — Requirements: 4.2, 4.7
# ---------------------------------------------------------------------------


class ExpiringMethodDetail(BaseModel):
    """Card details for the soonest-expiring payment method.

    Requirements: 4.2, 4.7
    """

    brand: str = Field(description="Card brand (e.g. Visa, Mastercard)")
    last4: str = Field(description="Last four digits of the card number")
    exp_month: int = Field(description="Card expiry month (1-12)")
    exp_year: int = Field(description="Card expiry year (e.g. 2025)")


class PaymentMethodStatusResponse(BaseModel):
    """Response for GET /billing/payment-method-status.

    Field names match exactly what the frontend expects
    (per frontend-backend-contract-alignment steering, Rule 1).

    Requirements: 4.2, 4.7
    """

    has_payment_method: bool = Field(
        description="Whether the organisation has at least one payment method on file"
    )
    has_expiring_soon: bool = Field(
        description="Whether any payment method is expiring within 30 days"
    )
    expiring_method: ExpiringMethodDetail | None = Field(
        default=None,
        description="Details of the soonest-expiring method, or null if none expiring soon",
    )


# ---------------------------------------------------------------------------
# Payment method schemas — Requirements: 5.1, 12.3
# ---------------------------------------------------------------------------


class PaymentMethodResponse(BaseModel):
    """Single payment method for an organisation.

    Requirements: 5.1
    """

    id: uuid.UUID
    stripe_payment_method_id: str
    brand: str
    last4: str
    exp_month: int
    exp_year: int
    is_default: bool
    is_verified: bool
    is_expiring_soon: bool = Field(
        description="True when card expiry is within 2 months of the current date",
    )


class PaymentMethodListResponse(BaseModel):
    """Response for GET /billing/payment-methods.

    Requirements: 5.1
    """

    payment_methods: list[PaymentMethodResponse]


class SetupIntentResponse(BaseModel):
    """Response for POST /billing/setup-intent.

    Requirements: 5.2
    """

    client_secret: str
    setup_intent_id: str


class StripeTestResult(BaseModel):
    """Individual result from the Stripe test suite.

    Requirements: 12.3
    """

    test_name: str
    category: str = Field(description='Either "api_functions" or "webhook_handlers"')
    status: str = Field(description='One of "passed", "failed", "skipped"')
    error_message: str | None = None
    skip_reason: str | None = None


class StripeTestAllResponse(BaseModel):
    """Response for POST /admin/integrations/stripe/test-all.

    Requirements: 12.3
    """

    results: list[StripeTestResult]
    summary: dict = Field(
        description="Counts: total, passed, failed, skipped",
    )


# ---------------------------------------------------------------------------
# Branch billing schemas — Requirements: 4.5, 5.1, 5.2, 6.4
# ---------------------------------------------------------------------------


class BranchCostPreviewResponse(BaseModel):
    """GET /api/v1/billing/branch-cost-preview response.

    Shows the cost impact of adding one more branch.
    Requirements: 4.5, 5.1, 5.2
    """

    current_branch_count: int = Field(description="Current number of active branches")
    new_branch_count: int = Field(description="Branch count after adding one")
    per_branch_cost: float = Field(description="Cost per branch per billing cycle")
    prorated_charge: float = Field(description="Prorated charge for remainder of current period")
    current_total: float = Field(description="Current total subscription cost")
    new_total: float = Field(description="Projected total after adding the branch")
    billing_interval: str = Field(description="Current billing interval")
    currency: str = Field(default="nzd", description="Currency code")


class BranchCostBreakdownItem(BaseModel):
    """Single branch in the cost breakdown."""

    branch_id: str = Field(description="Branch UUID")
    branch_name: str = Field(description="Branch name")
    is_hq: bool = Field(description="Whether this is the HQ branch")
    cost_per_cycle: float = Field(description="Cost per billing cycle for this branch")


class BranchCostBreakdownResponse(BaseModel):
    """GET /api/v1/billing/branch-cost-breakdown response.

    Per-branch cost breakdown for the billing dashboard.
    Requirements: 4.5, 6.4
    """

    branches: list[BranchCostBreakdownItem] = Field(
        default_factory=list, description="Per-branch cost breakdown"
    )
    per_branch_cost: float = Field(description="Cost per branch per billing cycle")
    total_cost: float = Field(description="Total subscription cost for all branches")
    branch_count: int = Field(description="Number of active branches")
    billing_interval: str = Field(description="Current billing interval")
    currency: str = Field(default="nzd", description="Currency code")


# ---------------------------------------------------------------------------
# Billing receipt schemas
# ---------------------------------------------------------------------------


class BillingReceiptResponse(BaseModel):
    """Single billing receipt for the receipts list."""

    id: uuid.UUID
    billing_date: datetime
    billing_interval: str
    plan_name: str
    plan_amount_cents: int
    sms_overage_cents: int = 0
    carjam_overage_cents: int = 0
    storage_addon_cents: int = 0
    subtotal_excl_gst_cents: int
    gst_amount_cents: int
    processing_fee_cents: int
    total_amount_cents: int
    sms_overage_count: int = 0
    carjam_overage_count: int = 0
    storage_addon_gb: int = 0
    status: str
    created_at: datetime


class BillingReceiptListResponse(BaseModel):
    """Response for GET /billing/receipts."""

    receipts: list[BillingReceiptResponse] = Field(
        default_factory=list, description="List of billing receipts"
    )
    total: int = Field(default=0, description="Total number of receipts")
