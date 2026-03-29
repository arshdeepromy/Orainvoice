"""Pydantic schemas for the Stock Items (catalogue-to-inventory) module.

Requirements: 5.2, 5.3, 5.4, 7.1, 9.3, 9.4, 9.5, 10.5
"""

from __future__ import annotations

import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CreateStockItemRequest(BaseModel):
    """POST /api/v1/inventory/stock-items — add a catalogue item to inventory.

    Requirements: 5.2, 5.3, 5.4, 10.5
    """

    catalogue_item_id: uuid.UUID = Field(
        ..., description="UUID of the catalogue item to add to stock"
    )
    catalogue_type: Literal["part", "tyre", "fluid"] = Field(
        ..., description="Catalogue source type"
    )
    quantity: float = Field(
        ..., gt=0, description="Initial stock quantity (must be > 0)"
    )
    reason: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Reason for adding stock (e.g. 'Purchase Order received')",
    )
    barcode: Optional[str] = Field(
        None, max_length=255, description="Optional barcode / product code / serial"
    )
    location: Optional[str] = Field(
        None, max_length=255, description="Optional inventory location name (stored as text)"
    )
    supplier_id: Optional[uuid.UUID] = Field(
        None, description="Optional supplier override; defaults to catalogue supplier"
    )
    purchase_price: Optional[float] = Field(
        None, ge=0, description="Purchase price override for this stock entry"
    )
    sell_price: Optional[float] = Field(
        None, ge=0, description="Sell price per unit/litre override"
    )
    cost_per_unit: Optional[float] = Field(
        None, ge=0, description="Cost per unit/litre override"
    )


class UpdateStockItemRequest(BaseModel):
    """PUT /api/v1/inventory/stock-items/{id} — update stock item metadata.

    Requirements: 7.1
    """

    barcode: Optional[str] = Field(
        None, description="Barcode / product code / serial"
    )
    location: Optional[str] = Field(
        None, max_length=255, description="Inventory location name"
    )
    supplier_id: Optional[uuid.UUID] = Field(
        None, description="Supplier override UUID"
    )
    min_threshold: Optional[float] = Field(
        None, ge=0, description="Minimum stock threshold"
    )
    reorder_quantity: Optional[float] = Field(
        None, ge=0, description="Reorder quantity when below threshold"
    )


class AdjustStockItemRequest(BaseModel):
    """POST /api/v1/inventory/stock-items/{id}/adjust — manual stock adjustment."""

    quantity_change: float = Field(
        ..., description="Positive to add stock, negative to remove"
    )
    reason: str = Field(
        ..., min_length=1, max_length=500, description="Reason for adjustment"
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class StockItemResponse(BaseModel):
    """Single stock item in API responses, with joined catalogue fields.

    Requirements: 9.3, 9.4, 9.5, 7.1
    """

    id: str = Field(..., description="Stock item UUID")
    catalogue_item_id: str = Field(..., description="Source catalogue item UUID")
    catalogue_type: str = Field(
        ..., description="Catalogue type: part, tyre, or fluid"
    )
    item_name: str = Field(..., description="Name from the catalogue record")
    part_number: Optional[str] = Field(
        None, description="Part number / SKU from catalogue"
    )
    brand: Optional[str] = Field(None, description="Brand from catalogue")
    subtitle: Optional[str] = Field(None, description="Extra info line: tyre size, fluid type, etc.")
    current_quantity: float = Field(..., description="Current stock quantity")
    reserved_quantity: float = Field(0, description="Quantity reserved/held for drafts and bookings")
    available_quantity: float = Field(..., description="Available = current - reserved")
    min_threshold: float = Field(..., description="Minimum stock threshold")
    reorder_quantity: float = Field(..., description="Reorder quantity")
    is_below_threshold: bool = Field(
        ...,
        description="True when current_quantity <= min_threshold and min_threshold > 0",
    )
    supplier_id: Optional[str] = Field(None, description="Supplier UUID")
    supplier_name: Optional[str] = Field(
        None, description="Supplier name from suppliers table"
    )
    barcode: Optional[str] = Field(
        None, description="Barcode / product code / serial"
    )
    location: Optional[str] = Field(
        None, description="Inventory location name"
    )
    cost_per_unit: Optional[float] = Field(
        None, description="Cost per unit/litre stored on this stock entry"
    )
    sell_price: Optional[float] = Field(
        None, description="Sell price per unit/litre stored on this stock entry"
    )
    gst_mode: Optional[str] = Field(
        None, description="GST mode from catalogue: inclusive, exclusive, exempt, or None"
    )
    created_at: str = Field(..., description="ISO 8601 timestamp")


class StockItemListResponse(BaseModel):
    """GET /api/v1/inventory/stock-items response.

    Requirements: 9.3, 9.4, 9.5
    """

    stock_items: list[StockItemResponse] = Field(
        default_factory=list, description="Stock item records"
    )
    total: int = Field(0, description="Total number of stock items")


# ---------------------------------------------------------------------------
# Location schemas
# ---------------------------------------------------------------------------


class CreateLocationRequest(BaseModel):
    """POST /api/v1/inventory/stock-items/locations — create a reusable location."""

    name: str = Field(
        ..., min_length=1, max_length=255, description="Location name"
    )


class LocationResponse(BaseModel):
    """Single inventory location in API responses."""

    id: str = Field(..., description="Location UUID")
    name: str = Field(..., description="Location name")
    created_at: str = Field(..., description="ISO 8601 timestamp")


class LocationListResponse(BaseModel):
    """GET /api/v1/inventory/stock-items/locations response."""

    locations: list[LocationResponse] = Field(
        default_factory=list, description="Location records"
    )
