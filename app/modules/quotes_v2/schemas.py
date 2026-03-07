"""Pydantic v2 schemas for quote CRUD, status changes, and conversion.

**Validates: Requirement 12.1, 12.2, 12.5, 12.7**
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


QUOTE_STATUSES = [
    "draft", "sent", "accepted", "declined", "expired", "converted",
]


# ---------------------------------------------------------------------------
# Line item schema
# ---------------------------------------------------------------------------

class QuoteLineItem(BaseModel):
    description: str = Field(..., min_length=1)
    quantity: Decimal = Field(default=Decimal("1"))
    unit_price: Decimal = Field(default=Decimal("0"))
    tax_rate: Decimal | None = None
    total: Decimal | None = None


# ---------------------------------------------------------------------------
# Quote CRUD schemas
# ---------------------------------------------------------------------------

class QuoteCreate(BaseModel):
    customer_id: UUID
    project_id: UUID | None = None
    expiry_date: date | None = None
    terms: str | None = None
    internal_notes: str | None = None
    line_items: list[dict] = Field(default_factory=list)
    currency: str | None = None


class QuoteUpdate(BaseModel):
    customer_id: UUID | None = None
    project_id: UUID | None = None
    expiry_date: date | None = None
    terms: str | None = None
    internal_notes: str | None = None
    line_items: list[dict] | None = None
    currency: str | None = None


class QuoteResponse(BaseModel):
    id: UUID
    org_id: UUID
    quote_number: str
    customer_id: UUID
    project_id: UUID | None = None
    status: str
    expiry_date: date | None = None
    terms: str | None = None
    internal_notes: str | None = None
    line_items: list[dict] = Field(default_factory=list)
    subtotal: Decimal = Decimal("0")
    tax_amount: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    currency: str | None = None
    version_number: int = 1
    previous_version_id: UUID | None = None
    converted_invoice_id: UUID | None = None
    acceptance_token: str | None = None
    accepted_at: datetime | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QuoteListResponse(BaseModel):
    quotes: list[QuoteResponse]
    total: int
    page: int = 1
    page_size: int = 50


# ---------------------------------------------------------------------------
# Conversion / acceptance schemas
# ---------------------------------------------------------------------------

class ConvertToInvoiceResponse(BaseModel):
    quote_id: UUID
    invoice_id: UUID
    line_items_count: int
    message: str


class AcceptQuoteResponse(BaseModel):
    quote_id: UUID
    status: str
    accepted_at: datetime
    message: str
