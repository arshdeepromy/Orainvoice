"""Pydantic v2 schemas for stock movements, adjustments, and stocktakes.

**Validates: Requirement 9.7, 9.8**
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class StockMovementResponse(BaseModel):
    id: UUID
    org_id: UUID
    product_id: UUID
    location_id: UUID | None = None
    movement_type: str
    quantity_change: Decimal
    resulting_quantity: Decimal
    reference_type: str | None = None
    reference_id: UUID | None = None
    notes: str | None = None
    performed_by: UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class StockMovementListResponse(BaseModel):
    movements: list[StockMovementResponse]
    total: int


class StockAdjustmentRequest(BaseModel):
    """Manual stock adjustment."""
    product_id: UUID
    quantity_change: Decimal
    reason: str = Field(..., min_length=1, max_length=500)
    location_id: UUID | None = None


class StocktakeLineItem(BaseModel):
    product_id: UUID
    counted_quantity: Decimal


class StocktakeCreate(BaseModel):
    """Start a new stocktake."""
    location_id: UUID | None = None
    lines: list[StocktakeLineItem] = Field(default_factory=list)


class StocktakeVarianceLine(BaseModel):
    product_id: UUID
    product_name: str
    system_quantity: Decimal
    counted_quantity: Decimal
    variance: Decimal


class StocktakeResponse(BaseModel):
    id: UUID
    location_id: UUID | None = None
    lines: list[StocktakeVarianceLine]
    status: str
    adjustments_applied: int = 0
