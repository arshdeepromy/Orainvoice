"""Pydantic schemas for fluid/oil products."""
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from pydantic import BaseModel, Field


class FluidOilCreate(BaseModel):
    fluid_type: str = Field(..., pattern=r"^(oil|non-oil)$")
    oil_type: str | None = None
    grade: str | None = None
    synthetic_type: str | None = None
    product_name: str | None = None
    brand_name: str | None = None
    description: str | None = None
    pack_size: str | None = None
    qty_per_pack: Decimal | None = None
    unit_type: str = "litre"
    container_type: str | None = None
    total_quantity: Decimal | None = None
    purchase_price: Decimal | None = None
    gst_mode: str | None = None
    sell_price_per_unit: Decimal | None = None
    supplier_id: UUID | None = None
    min_stock_volume: Decimal = Decimal("0")
    reorder_volume: Decimal = Decimal("0")


class FluidOilResponse(BaseModel):
    id: UUID
    org_id: UUID
    fluid_type: str
    oil_type: str | None = None
    grade: str | None = None
    synthetic_type: str | None = None
    product_name: str | None = None
    brand_name: str | None = None
    description: str | None = None
    pack_size: str | None = None
    qty_per_pack: Decimal | None = None
    unit_type: str
    container_type: str | None = None
    total_quantity: Decimal | None = None
    total_volume: Decimal | None = None
    purchase_price: Decimal | None = None
    gst_mode: str | None = None
    cost_per_unit: Decimal | None = None
    sell_price_per_unit: Decimal | None = None
    margin: Decimal | None = None
    margin_pct: Decimal | None = None
    current_stock_volume: Decimal = Decimal("0")
    min_stock_volume: Decimal = Decimal("0")
    reorder_volume: Decimal = Decimal("0")
    is_active: bool = True
    supplier_id: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FluidOilListResponse(BaseModel):
    products: list[FluidOilResponse]
    total: int
