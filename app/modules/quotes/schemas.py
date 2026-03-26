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
    sent = "sent"
    accepted = "accepted"
    declined = "declined"
    expired = "expired"


VALID_VALIDITY_DAYS = {7, 14, 30}


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


class QuoteCreate(BaseModel):
    """Request body for POST /api/v1/quotes."""

    customer_id: uuid.UUID
    vehicle_rego: str | None = None
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    vehicle_year: int | None = None
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
    line_items: list[QuoteLineItemResponse] = Field(default_factory=list)
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


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
