"""Pydantic v2 schemas for purchase order CRUD and receiving.

**Validates: Requirement 16 — Purchase Order Module**
"""

from __future__ import annotations

from datetime import date as _date_type, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


# ------------------------------------------------------------------
# Line item schemas
# ------------------------------------------------------------------

class POLineCreate(BaseModel):
    product_id: UUID
    description: str | None = None
    quantity_ordered: Decimal = Field(..., gt=0)
    unit_cost: Decimal = Field(..., ge=0)


class POLineResponse(BaseModel):
    id: UUID
    po_id: UUID
    product_id: UUID
    description: str | None = None
    quantity_ordered: Decimal
    quantity_received: Decimal = Decimal("0")
    unit_cost: Decimal
    line_total: Decimal

    model_config = {"from_attributes": True}


class ReceiveLine(BaseModel):
    """Quantity to receive for a specific PO line."""
    line_id: UUID
    quantity: Decimal = Field(..., gt=0)


# ------------------------------------------------------------------
# PO schemas
# ------------------------------------------------------------------

class PurchaseOrderCreate(BaseModel):
    supplier_id: UUID
    job_id: UUID | None = None
    project_id: UUID | None = None
    expected_delivery: _date_type | None = None
    notes: str | None = None
    lines: list[POLineCreate] = Field(default_factory=list)


class PurchaseOrderUpdate(BaseModel):
    supplier_id: UUID | None = None
    job_id: UUID | None = None
    project_id: UUID | None = None
    expected_delivery: _date_type | None = None
    notes: str | None = None
    status: str | None = None


class PurchaseOrderResponse(BaseModel):
    id: UUID
    org_id: UUID
    po_number: str
    supplier_id: UUID
    job_id: UUID | None = None
    project_id: UUID | None = None
    status: str
    expected_delivery: _date_type | None = None
    total_amount: Decimal = Decimal("0")
    notes: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime
    lines: list[POLineResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class PurchaseOrderListResponse(BaseModel):
    purchase_orders: list[PurchaseOrderResponse]
    total: int
    page: int = 1
    page_size: int = 50


class ReceiveGoodsRequest(BaseModel):
    """Receive goods against PO lines."""
    lines: list[ReceiveLine] = Field(..., min_length=1)
