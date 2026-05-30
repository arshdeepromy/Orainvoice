"""Pydantic schemas for Quote module.

Requirements: 58.1, 58.2, 58.4, 58.6
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class QuoteItemType(str, Enum):
    service = "service"
    part = "part"
    labour = "labour"


class QuoteStatus(str, Enum):
    draft = "draft"
    issued = "issued"
    sent = "sent"
    accepted = "accepted"
    declined = "declined"
    expired = "expired"
    cancelled = "cancelled"


VALID_VALIDITY_DAYS = {7, 14, 30}


class VehicleItem(BaseModel):
    """A vehicle entry for multi-vehicle quotes."""

    model_config = {"extra": "ignore"}
    id: uuid.UUID | None = None
    rego: str | None = None
    make: str | None = None
    model: str | None = None
    year: int | None = None
    odometer: int | None = None
    wof_expiry: str | None = None
    cof_expiry: str | None = None


class FluidUsageItem(BaseModel):
    """A fluid/oil usage entry tracked for inventory purposes (non-billable)."""

    model_config = {"extra": "ignore"}
    stock_item_id: uuid.UUID
    catalogue_item_id: uuid.UUID
    litres: Decimal = Field(..., gt=0)
    item_name: str = ""


class QuoteLineItemCreate(BaseModel):
    """Schema for creating a single quote line item."""

    item_type: QuoteItemType
    description: str = Field(..., min_length=1, max_length=2000)
    quantity: Decimal = Field(default=Decimal("1"), gt=0)
    unit_price: Decimal = Field(..., ge=0)
    hours: Decimal | None = Field(default=None, ge=0)
    hourly_rate: Decimal | None = Field(default=None, ge=0)
    is_gst_exempt: bool = False
    warranty_note: str | None = None
    sort_order: int = 0
    # NEW — Phase 5 (Quote ↔ Invoice Parity)
    catalogue_item_id: uuid.UUID | None = None
    stock_item_id: uuid.UUID | None = None
    gst_inclusive: bool = False
    inclusive_price: Decimal | None = Field(default=None, ge=0)
    tax_rate: Decimal | None = Field(default=None, ge=0, le=100)


class QuoteCreate(BaseModel):
    """Request body for POST /api/v1/quotes."""

    customer_id: uuid.UUID
    vehicle_rego: str | None = None
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    vehicle_year: int | None = None
    vehicle_odometer: int | None = None
    vehicle_wof_expiry: date | None = None
    vehicle_cof_expiry: date | None = None
    project_id: uuid.UUID | None = None
    validity_days: int = Field(default=30)
    line_items: list[QuoteLineItemCreate] = Field(default_factory=list)
    notes: str | None = None
    terms: str | None = None
    subject: str | None = None
    discount_type: str | None = Field(default="percentage")
    discount_value: Decimal = Field(default=Decimal("0"), ge=0)
    shipping_charges: Decimal = Field(default=Decimal("0"), ge=0)
    adjustment: Decimal = Field(default=Decimal("0"))
    # NEW — Phase 5 (Quote ↔ Invoice Parity)
    order_number: str | None = Field(default=None, max_length=100)
    salesperson_id: uuid.UUID | None = None
    vehicles: list[VehicleItem] | None = None
    fluid_usage: list[FluidUsageItem] = Field(default_factory=list)
    save_terms_as_default: bool = False

    @field_validator("validity_days")
    @classmethod
    def validate_validity_days(cls, v: int) -> int:
        if v not in VALID_VALIDITY_DAYS:
            raise ValueError(f"validity_days must be one of {sorted(VALID_VALIDITY_DAYS)}")
        return v


class QuoteUpdate(BaseModel):
    """Request body for PUT /api/v1/quotes/{id}."""

    customer_id: uuid.UUID | None = None
    vehicle_rego: str | None = None
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    vehicle_year: int | None = None
    vehicle_odometer: int | None = None
    vehicle_wof_expiry: date | None = None
    vehicle_cof_expiry: date | None = None
    project_id: uuid.UUID | None = None
    status: QuoteStatus | None = None
    validity_days: int | None = None
    line_items: list[QuoteLineItemCreate] | None = None
    notes: str | None = None
    terms: str | None = None
    subject: str | None = None
    discount_type: str | None = None
    discount_value: Decimal | None = None
    shipping_charges: Decimal | None = None
    adjustment: Decimal | None = None
    # NEW — Phase 5 (Quote ↔ Invoice Parity)
    order_number: str | None = Field(default=None, max_length=100)
    salesperson_id: uuid.UUID | None = None
    vehicles: list[VehicleItem] | None = None
    fluid_usage: list[FluidUsageItem] = Field(default_factory=list)
    save_terms_as_default: bool = False

    @field_validator("validity_days")
    @classmethod
    def validate_validity_days(cls, v: int | None) -> int | None:
        if v is not None and v not in VALID_VALIDITY_DAYS:
            raise ValueError(f"validity_days must be one of {sorted(VALID_VALIDITY_DAYS)}")
        return v


class QuoteLineItemResponse(BaseModel):
    """Response schema for a single quote line item."""

    id: uuid.UUID
    item_type: str
    description: str
    quantity: Decimal
    unit_price: Decimal
    hours: Decimal | None = None
    hourly_rate: Decimal | None = None
    is_gst_exempt: bool
    warranty_note: str | None = None
    line_total: Decimal
    sort_order: int
    # NEW — Phase 5 (Quote ↔ Invoice Parity)
    catalogue_item_id: uuid.UUID | None = None
    stock_item_id: uuid.UUID | None = None
    gst_inclusive: bool = False
    inclusive_price: Decimal | None = None
    tax_rate: Decimal = Decimal("15")


class QuoteResponse(BaseModel):
    """Response schema for a quote."""

    id: uuid.UUID
    org_id: uuid.UUID
    customer_id: uuid.UUID
    quote_number: str
    vehicle_rego: str | None = None
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    vehicle_year: int | None = None
    vehicle_odometer: int | None = None
    vehicle_wof_expiry: date | None = None
    vehicle_cof_expiry: date | None = None
    project_id: uuid.UUID | None = None
    status: str
    valid_until: date | None = None
    subtotal: Decimal
    gst_amount: Decimal
    total: Decimal
    discount_type: str | None = None
    discount_value: Decimal = Decimal("0")
    discount_amount: Decimal = Decimal("0")
    shipping_charges: Decimal = Decimal("0")
    adjustment: Decimal = Decimal("0")
    notes: str | None = None
    terms: str | None = None
    subject: str | None = None
    acceptance_token: str | None = None
    converted_invoice_id: uuid.UUID | None = None
    customer_portal_token: str | None = None
    customer_enable_portal: bool = False
    line_items: list[QuoteLineItemResponse] = Field(default_factory=list)
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    # NEW — Phase 5 (Quote ↔ Invoice Parity)
    order_number: str | None = None
    salesperson_id: uuid.UUID | None = None
    salesperson_name: str | None = None
    additional_vehicles: list[dict] = Field(default_factory=list)
    fluid_usage: list[dict] = Field(default_factory=list)
    attachment_count: int = 0
    # Org info for template preview (Phase 6 — mobile parity)
    org_name: str | None = None
    org_logo_url: str | None = None
    org_address: str | None = None
    org_address_unit: str | None = None
    org_address_street: str | None = None
    org_address_city: str | None = None
    org_address_state: str | None = None
    org_address_country: str | None = None
    org_address_postcode: str | None = None
    org_phone: str | None = None
    org_email: str | None = None
    org_website: str | None = None
    org_gst_number: str | None = None
    invoice_template_id: str | None = None
    invoice_template_colours: dict | None = None
    customer_name: str | None = None
    customer_email: str | None = None
    # NEW — Quote Cancellation Workflow
    cancel_reason: str | None = None
    cancelled_at: datetime | None = None
    cancelled_by: uuid.UUID | None = None
    # NEW — Quote ↔ Invoice Settings Parity
    payment_terms_text: str | None = None
    terms_and_conditions: str | None = None
    terms_and_conditions_enabled: bool = False


class QuoteCreateResponse(BaseModel):
    """Wrapper response for quote creation."""

    quote: QuoteResponse
    message: str


class QuoteSearchResult(BaseModel):
    """Lightweight quote for list views."""

    id: uuid.UUID
    quote_number: str
    customer_name: str | None = None
    vehicle_rego: str | None = None
    total: Decimal
    status: str
    valid_until: date | None = None
    created_at: datetime | None = None
    # NEW — Phase 5 (Quote ↔ Invoice Parity)
    attachment_count: int = 0


class QuoteListResponse(BaseModel):
    """Paginated list of quotes."""

    quotes: list[QuoteSearchResult]
    total: int
    limit: int
    offset: int


class QuoteSendResponse(BaseModel):
    """Response after sending a quote to a customer."""

    quote_id: uuid.UUID
    quote_number: str
    recipient_email: str
    pdf_size_bytes: int
    status: str


class QuoteConvertResponse(BaseModel):
    """Response after converting a quote to a draft invoice."""

    quote_id: uuid.UUID
    quote_number: str
    invoice_id: uuid.UUID
    invoice_status: str
    message: str


class QuoteCancelRequest(BaseModel):
    """Request body for PUT /api/v1/quotes/{id}/cancel."""

    reason: str = Field(..., min_length=1)
