"""Billing schemas — trial status and subscription lifecycle.

Requirements: 41.1, 41.2, 41.3, 41.4, 41.5
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


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
        description="Estimated next invoice total (plan + storage + Carjam overage)",
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
    org_status: str = Field(description="Organisation status")
    past_invoices: list[SubscriptionInvoiceResponse] = Field(
        default_factory=list, description="Past subscription invoices"
    )

# ---------------------------------------------------------------------------
# Plan upgrade / downgrade schemas — Requirements: 43.1, 43.2, 43.3, 43.4
# ---------------------------------------------------------------------------


class PlanChangeRequest(BaseModel):
    """Request body for POST /api/v1/billing/upgrade and /downgrade.

    Requirements: 43.1
    """

    new_plan_id: str = Field(description="UUID of the target subscription plan")


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