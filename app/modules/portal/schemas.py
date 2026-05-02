"""Pydantic schemas for the Customer Portal module.

Requirements: 61.1, 61.2, 61.3, 61.4, 61.5
Enhanced: Requirement 49 — Customer Portal Enhancements
"""

from __future__ import annotations

import datetime as _dt
import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Organisation branding (Req 61.5, Req 49.5)
# ---------------------------------------------------------------------------


class PoweredByFooter(BaseModel):
    """Platform 'Powered By' footer data."""

    platform_name: str = "OraInvoice"
    logo_url: str | None = None
    signup_url: str | None = None
    website_url: str | None = None
    show_powered_by: bool = True


class PortalBranding(BaseModel):
    """Organisation branding returned with every portal response."""

    org_name: str
    logo_url: str | None = None
    primary_colour: str | None = None
    secondary_colour: str | None = None
    powered_by: PoweredByFooter | None = None
    language: str | None = None


# ---------------------------------------------------------------------------
# Portal access (Req 61.1)
# ---------------------------------------------------------------------------


class PortalCustomerInfo(BaseModel):
    """Basic customer info shown on the portal landing page."""

    customer_id: uuid.UUID
    first_name: str
    last_name: str
    email: str | None = None
    phone: str | None = None


class PortalAccessResponse(BaseModel):
    """Response from GET /portal/{token} — validates token, returns context."""

    customer: PortalCustomerInfo
    branding: PortalBranding
    outstanding_balance: Decimal = Field(
        ..., description="Total outstanding balance across all invoices"
    )
    invoice_count: int = Field(
        ..., description="Total number of invoices for this customer"
    )
    total_paid: Decimal = Field(
        default=Decimal("0"),
        description="Sum of amount_paid across non-draft non-voided invoices",
    )


# ---------------------------------------------------------------------------
# Invoice history (Req 61.2)
# ---------------------------------------------------------------------------


class PortalPaymentSummary(BaseModel):
    """A single payment event shown in the portal."""

    id: uuid.UUID
    amount: Decimal
    method: str
    is_refund: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class PortalInvoiceItem(BaseModel):
    """A single invoice in the portal invoice list."""

    id: uuid.UUID
    invoice_number: str | None = None
    status: str
    issue_date: date | None = None
    due_date: date | None = None
    currency: str = "NZD"
    subtotal: Decimal
    gst_amount: Decimal
    total: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    vehicle_rego: str | None = None
    line_items_summary: str = ""
    payments: list[PortalPaymentSummary] = []

    model_config = {"from_attributes": True}


class PortalInvoicesResponse(BaseModel):
    """Response from GET /portal/{token}/invoices."""

    branding: PortalBranding
    invoices: list[PortalInvoiceItem]
    total_outstanding: Decimal
    total_paid: Decimal
    org_has_stripe_connect: bool = False
    total: int = 0


# ---------------------------------------------------------------------------
# Vehicle service history (Req 61.4)
# ---------------------------------------------------------------------------


class PortalServiceRecord(BaseModel):
    """A service event for a vehicle (derived from invoices)."""

    invoice_id: uuid.UUID
    invoice_number: str | None = None
    date: _dt.date | None = None
    status: str
    total: Decimal
    description: str = Field(
        ..., description="Comma-separated list of services performed"
    )


class PortalVehicleItem(BaseModel):
    """A vehicle with its service history."""

    rego: str
    make: str | None = None
    model: str | None = None
    year: int | None = None
    colour: str | None = None
    wof_expiry: date | None = None
    rego_expiry: date | None = None
    service_history: list[PortalServiceRecord] = []


class PortalVehiclesResponse(BaseModel):
    """Response from GET /portal/{token}/vehicles."""

    branding: PortalBranding
    vehicles: list[PortalVehicleItem]
    total: int = 0


# ---------------------------------------------------------------------------
# Portal payment (Req 61.3)
# ---------------------------------------------------------------------------


class PortalPayRequest(BaseModel):
    """Request body for POST /portal/{token}/pay/{invoice_id}."""

    amount: Decimal | None = Field(
        None,
        gt=0,
        description="Optional partial amount. If omitted, pays full balance.",
    )


class PortalPayResponse(BaseModel):
    """Response from POST /portal/{token}/pay/{invoice_id}."""

    payment_url: str = Field(
        ..., description="Stripe Checkout URL for the customer"
    )
    invoice_id: uuid.UUID
    amount: Decimal
    message: str = "Payment link generated"


# ---------------------------------------------------------------------------
# Quote acceptance (Req 49.2)
# ---------------------------------------------------------------------------


class PortalQuoteLineItem(BaseModel):
    """A single line item on a quote shown in the portal."""

    description: str
    quantity: Decimal = Decimal("1")
    unit_price: Decimal = Decimal("0")
    total: Decimal | None = None


class PortalQuoteItem(BaseModel):
    """A quote visible in the customer portal."""

    id: uuid.UUID
    quote_number: str
    status: str
    expiry_date: date | None = None
    terms: str | None = None
    line_items: list[PortalQuoteLineItem] = []
    subtotal: Decimal = Decimal("0")
    tax_amount: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    currency: str | None = None
    accepted_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PortalQuotesResponse(BaseModel):
    """Response from GET /portal/{token}/quotes."""

    branding: PortalBranding
    quotes: list[PortalQuoteItem]
    total: int = 0


class PortalAcceptQuoteResponse(BaseModel):
    """Response from POST /portal/{token}/quotes/{quote_id}/accept."""

    quote_id: uuid.UUID
    status: str
    accepted_at: datetime
    message: str = "Quote accepted successfully"


# ---------------------------------------------------------------------------
# Asset / service history (Req 49.2)
# ---------------------------------------------------------------------------


class PortalAssetServiceEntry(BaseModel):
    """A single service history entry for an asset."""

    reference_type: str  # "invoice", "job", "quote"
    reference_id: uuid.UUID
    reference_number: str | None = None
    description: str | None = None
    date: datetime | None = None
    status: str | None = None


class PortalAssetItem(BaseModel):
    """An asset with its service history for the portal."""

    id: uuid.UUID
    asset_type: str
    identifier: str | None = None
    make: str | None = None
    model: str | None = None
    year: int | None = None
    description: str | None = None
    serial_number: str | None = None
    service_history: list[PortalAssetServiceEntry] = []


class PortalAssetsResponse(BaseModel):
    """Response from GET /portal/{token}/assets."""

    branding: PortalBranding
    assets: list[PortalAssetItem]
    total: int = 0


# ---------------------------------------------------------------------------
# Booking management (Req 49.4)
# ---------------------------------------------------------------------------


class PortalBookingItem(BaseModel):
    """A booking visible in the customer portal."""

    id: uuid.UUID
    service_type: str | None = None
    start_time: datetime
    end_time: datetime
    status: str
    notes: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PortalBookingsResponse(BaseModel):
    """Response from GET /portal/{token}/bookings."""

    branding: PortalBranding
    bookings: list[PortalBookingItem]
    total: int = 0


class PortalBookingCreateRequest(BaseModel):
    """Request body for POST /portal/{token}/bookings."""

    service_type: str | None = None
    start_time: datetime
    notes: str | None = None


class PortalBookingCreateResponse(BaseModel):
    """Response from POST /portal/{token}/bookings."""

    booking_id: uuid.UUID
    status: str
    start_time: datetime
    end_time: datetime
    message: str = "Booking created successfully"


class PortalTimeSlot(BaseModel):
    """A single available time slot."""

    start_time: datetime
    end_time: datetime
    available: bool = True


class PortalAvailableSlotsResponse(BaseModel):
    """Response from GET /portal/{token}/bookings/slots."""

    branding: PortalBranding
    date: date
    slots: list[PortalTimeSlot]


# ---------------------------------------------------------------------------
# Loyalty balance (Req 49.2, Req 38.6)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Job status visibility (Req 16)
# ---------------------------------------------------------------------------


class PortalJobItem(BaseModel):
    """A job card visible in the customer portal."""

    id: uuid.UUID
    status: str
    description: str | None = None
    assigned_staff_name: str | None = None
    vehicle_rego: str | None = None
    linked_invoice_number: str | None = None
    estimated_completion: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PortalJobsResponse(BaseModel):
    """Response from GET /portal/{token}/jobs."""

    branding: PortalBranding
    jobs: list[PortalJobItem] = []
    total: int = 0


# ---------------------------------------------------------------------------
# Claims visibility (Req 17)
# ---------------------------------------------------------------------------


class PortalClaimActionItem(BaseModel):
    """A single action/event in a claim's timeline."""

    action_type: str
    from_status: str | None = None
    to_status: str | None = None
    notes: str | None = None
    performed_at: datetime

    model_config = {"from_attributes": True}


class PortalClaimItem(BaseModel):
    """A customer claim visible in the customer portal."""

    id: uuid.UUID
    reference: str | None = None
    claim_type: str
    status: str
    description: str
    resolution_type: str | None = None
    resolution_notes: str | None = None
    created_at: datetime
    actions: list[PortalClaimActionItem] = []

    model_config = {"from_attributes": True}


class PortalClaimsResponse(BaseModel):
    """Response from GET /portal/{token}/claims."""

    branding: PortalBranding
    claims: list[PortalClaimItem] = []
    total: int = 0


# ---------------------------------------------------------------------------
# Loyalty balance (Req 49.2, Req 38.6)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Compliance documents (Req 19)
# ---------------------------------------------------------------------------


class PortalDocumentItem(BaseModel):
    """A compliance document visible in the customer portal."""

    id: uuid.UUID
    document_type: str
    description: str | None = None
    linked_invoice_number: str | None = None
    download_url: str

    model_config = {"from_attributes": True}


class PortalDocumentsResponse(BaseModel):
    """Response from GET /portal/{token}/documents."""

    branding: PortalBranding
    documents: list[PortalDocumentItem] = []
    total: int = 0


# ---------------------------------------------------------------------------
# Profile update (Req 21)
# ---------------------------------------------------------------------------


class PortalProfileUpdateRequest(BaseModel):
    """Request body for PATCH /portal/{token}/profile."""

    email: str | None = None
    phone: str | None = None


class PortalProfileUpdateResponse(BaseModel):
    """Response from PATCH /portal/{token}/profile."""

    email: str | None = None
    phone: str | None = None
    message: str = "Profile updated successfully"


class PortalLoyaltyTier(BaseModel):
    """Loyalty tier info for the portal."""

    name: str
    threshold_points: int
    discount_percent: Decimal = Decimal("0")


class PortalLoyaltyTransaction(BaseModel):
    """A single loyalty transaction for the portal."""

    transaction_type: str
    points: int
    balance_after: int
    reference_type: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PortalLoyaltyResponse(BaseModel):
    """Response from GET /portal/{token}/loyalty."""

    branding: PortalBranding
    programme_configured: bool = False
    total_points: int
    current_tier: PortalLoyaltyTier | None = None
    next_tier: PortalLoyaltyTier | None = None
    points_to_next_tier: int | None = None
    transactions: list[PortalLoyaltyTransaction] = []
    total: int = 0


# ---------------------------------------------------------------------------
# Recurring invoice schedules (Req 50)
# ---------------------------------------------------------------------------


class PortalRecurringItem(BaseModel):
    """A recurring invoice schedule visible in the customer portal."""

    id: uuid.UUID
    frequency: str
    next_generation_date: date
    status: str
    line_items: list = []
    start_date: date
    end_date: date | None = None
    auto_issue: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class PortalRecurringResponse(BaseModel):
    """Response from GET /portal/{token}/recurring."""

    branding: PortalBranding
    schedules: list[PortalRecurringItem] = []
    total: int = 0


# ---------------------------------------------------------------------------
# Progress Claims visibility (Req 51)
# ---------------------------------------------------------------------------


class PortalProgressClaimItem(BaseModel):
    """A progress claim visible in the customer portal."""

    id: uuid.UUID
    project_id: uuid.UUID
    claim_number: int
    status: str
    contract_value: Decimal
    revised_contract_value: Decimal
    work_completed_to_date: Decimal
    work_completed_this_period: Decimal
    materials_on_site: Decimal = Decimal("0")
    retention_withheld: Decimal = Decimal("0")
    amount_due: Decimal
    completion_percentage: Decimal
    submitted_at: datetime | None = None
    approved_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PortalProgressClaimsResponse(BaseModel):
    """Response from GET /portal/{token}/progress-claims."""

    branding: PortalBranding
    progress_claims: list[PortalProgressClaimItem] = []
    total: int = 0


# ---------------------------------------------------------------------------
# DSAR — Data Subject Access Request (Req 45)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Projects visibility (Req 49)
# ---------------------------------------------------------------------------


class PortalProjectItem(BaseModel):
    """A project visible in the customer portal."""

    id: uuid.UUID
    name: str
    status: str
    description: str | None = None
    budget_amount: Decimal | None = None
    contract_value: Decimal | None = None
    start_date: date | None = None
    target_end_date: date | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PortalProjectsResponse(BaseModel):
    """Response from GET /portal/{token}/projects."""

    branding: PortalBranding
    projects: list[PortalProjectItem] = []
    total: int = 0


class PortalRecoverRequest(BaseModel):
    """Request body for POST /portal/recover."""

    email: str = Field(
        ...,
        description="Email address to look up portal-enabled customers",
    )


class PortalRecoverResponse(BaseModel):
    """Response from POST /portal/recover — always generic to prevent enumeration."""

    message: str = "If an account exists with that email, a portal link has been sent."


class PortalDSARRequest(BaseModel):
    """Request body for POST /portal/{token}/dsar."""

    request_type: str = Field(
        ...,
        description="Type of DSAR: 'export' for data export, 'deletion' for account deletion",
    )


class PortalDSARResponse(BaseModel):
    """Response from POST /portal/{token}/dsar."""

    request_type: str
    message: str = "Your request has been submitted and will be reviewed by the organisation."


# ---------------------------------------------------------------------------
# Portal Analytics (Req 47)
# ---------------------------------------------------------------------------


class PortalAnalyticsDayItem(BaseModel):
    """Analytics counters for a single day."""

    date: str
    view: int = 0
    quote_accepted: int = 0
    booking_created: int = 0
    payment_initiated: int = 0


class PortalAnalyticsResponse(BaseModel):
    """Response from GET /api/v2/org/portal-analytics."""

    days: list[PortalAnalyticsDayItem] = []
    totals: PortalAnalyticsDayItem = PortalAnalyticsDayItem(date="total")


# ---------------------------------------------------------------------------
# SMS conversation history (Req 63)
# ---------------------------------------------------------------------------


class PortalMessageItem(BaseModel):
    """A single SMS message in the portal conversation history."""

    id: uuid.UUID
    direction: str  # "inbound" or "outbound"
    body: str
    created_at: datetime
    status: str | None = None

    model_config = {"from_attributes": True}


class PortalMessagesResponse(BaseModel):
    """Response from GET /portal/{token}/messages."""

    branding: PortalBranding
    messages: list[PortalMessageItem] = []
    total: int = 0
