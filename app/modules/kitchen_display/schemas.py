"""Pydantic v2 schemas for the kitchen display module.

**Validates: Requirement — Kitchen Display Module**
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KitchenOrderCreate(BaseModel):
    pos_transaction_id: uuid.UUID | None = None
    table_id: uuid.UUID | None = None
    item_name: str = Field(max_length=200)
    quantity: int = Field(default=1, ge=1)
    modifications: str | None = None
    station: str = Field(default="main", max_length=50)


class KitchenOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    pos_transaction_id: uuid.UUID | None = None
    table_id: uuid.UUID | None = None
    item_name: str
    quantity: int
    modifications: str | None = None
    station: str
    status: str
    created_at: datetime
    prepared_at: datetime | None = None


class KitchenOrderStatusUpdate(BaseModel):
    status: str = Field(description="New status: pending, preparing, prepared, served")


class KitchenOrderListResponse(BaseModel):
    orders: list[KitchenOrderResponse]
    total: int


class StationMapping(BaseModel):
    category: str
    station: str


class KitchenOrderItem(BaseModel):
    """A single item from a POS transaction to route to the kitchen."""
    item_name: str = Field(max_length=200)
    quantity: int = Field(default=1, ge=1)
    modifications: str | None = None
    category: str | None = Field(default=None, description="Product category for station routing")


class KitchenOrderBulkCreate(BaseModel):
    """Create kitchen orders from a POS transaction."""
    pos_transaction_id: uuid.UUID
    table_id: uuid.UUID | None = None
    items: list[KitchenOrderItem] = Field(min_length=1)
    station_map: dict[str, str] | None = Field(
        default=None,
        description="Custom category→station mapping. Falls back to defaults.",
    )
