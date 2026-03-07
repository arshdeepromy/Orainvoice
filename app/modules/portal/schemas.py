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
    payments: list[PortalPaymentSummary] = []

    model_config = {"from_attributes": True}


class PortalInvoicesResponse(BaseModel):
    """Response from GET /portal/{token}/invoices."""

    branding: PortalBranding
    invoices: list[PortalInvoiceItem]
    total_outstanding: Decimal
    total_paid: Decimal


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
    service_history: list[PortalServiceRecord] = []


class PortalVehiclesResponse(BaseModel):
    """Response from GET /portal/{token}/vehicles."""

    branding: PortalBranding
    vehicles: list[PortalVehicleItem]


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
    acceptance_token: str | None = None
    accepted_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PortalQuotesResponse(BaseModel):
    """Response from GET /portal/{token}/quotes."""

    branding: PortalBranding
    quotes: list[PortalQuoteItem]


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
    total_points: int
    current_tier: PortalLoyaltyTier | None = None
    next_tier: PortalLoyaltyTier | None = None
    points_to_next_tier: int | None = None
    transactions: list[PortalLoyaltyTransaction] = []
