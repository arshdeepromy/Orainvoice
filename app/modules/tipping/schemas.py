"""Pydantic v2 schemas for the tipping module.

**Validates: Requirement 24 — Tipping Module**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class TipCreate(BaseModel):
    """Payload to record a new tip."""
    invoice_id: uuid.UUID | None = None
    pos_transaction_id: uuid.UUID | None = None
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    payment_method: str = Field(max_length=20)


class TipAllocationCreate(BaseModel):
    """A single staff allocation within a tip."""
    staff_member_id: uuid.UUID
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class TipAllocateRequest(BaseModel):
    """Request to allocate a tip across staff members."""
    allocations: list[TipAllocationCreate] = Field(min_length=1)


class TipEvenSplitRequest(BaseModel):
    """Request to split a tip evenly across staff members."""
    staff_member_ids: list[uuid.UUID] = Field(min_length=1)


class InvoiceTipCreate(BaseModel):
    """Payload for adding a tip during online invoice payment."""
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    payment_method: str = Field(default="card", max_length=20)


class TipAllocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tip_id: uuid.UUID
    staff_member_id: uuid.UUID
    amount: Decimal
    created_at: datetime


class TipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    invoice_id: uuid.UUID | None = None
    pos_transaction_id: uuid.UUID | None = None
    amount: Decimal
    payment_method: str
    created_at: datetime
    allocations: list[TipAllocationResponse] = []


class TipListResponse(BaseModel):
    tips: list[TipResponse]
    total: int


class StaffTipSummary(BaseModel):
    """Aggregated tip data for a single staff member."""
    staff_member_id: uuid.UUID
    total_tips: Decimal
    tip_count: int
    average_tip: Decimal


class TipSummaryResponse(BaseModel):
    """Tip summary report response."""
    total_tips: Decimal
    total_count: int
    average_tip_percentage: Decimal | None = None
    staff_summaries: list[StaffTipSummary]
    start_date: date | None = None
    end_date: date | None = None
