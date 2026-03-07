"""Pydantic schemas for the Inventory Stock Tracking module.

Requirements: 62.1, 62.2, 62.3, 62.4, 62.5
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class StockAdjustmentRequest(BaseModel):
    """PUT /api/v1/inventory/stock/{part_id} — manual stock adjustment.

    Requirements: 62.5
    """

    quantity_change: int = Field(
        ..., description="Positive to add stock, negative to remove"
    )
    reason: str = Field(
        ..., min_length=1, max_length=500, description="Reason for adjustment"
    )


class StockDecrementRequest(BaseModel):
    """Internal schema for auto-decrementing stock when part added to invoice.

    Requirements: 62.2
    """

    part_id: str = Field(..., description="Part UUID")
    quantity: int = Field(..., gt=0, description="Quantity to decrement")
    invoice_id: str = Field(..., description="Invoice UUID reference")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class StockLevelResponse(BaseModel):
    """Single part stock level in API responses.

    Requirements: 62.1
    """

    part_id: str = Field(..., description="Part UUID")
    part_name: str = Field(..., description="Part name")
    part_number: Optional[str] = Field(None, description="Part number / SKU")
    current_stock: int = Field(..., description="Current stock quantity")
    min_threshold: int = Field(..., description="Minimum stock threshold")
    reorder_quantity: int = Field(..., description="Reorder quantity")
    is_below_threshold: bool = Field(..., description="True if stock <= threshold")


class StockLevelListResponse(BaseModel):
    """GET /api/v1/inventory/stock response.

    Requirements: 62.1, 62.4
    """

    stock_levels: list[StockLevelResponse] = Field(
        default_factory=list, description="Stock levels for all parts"
    )
    total: int = Field(0, description="Total number of parts")


class StockMovementResponse(BaseModel):
    """Single stock movement record."""

    id: str = Field(..., description="Movement UUID")
    part_id: str = Field(..., description="Part UUID")
    quantity_change: int = Field(..., description="Quantity change")
    reason: str = Field(..., description="Movement reason")
    reference_id: Optional[str] = Field(None, description="Reference UUID")
    recorded_by: str = Field(..., description="User UUID who recorded")
    created_at: str = Field(..., description="ISO 8601 timestamp")


class StockReportResponse(BaseModel):
    """GET /api/v1/inventory/stock/report response.

    Requirements: 62.4
    """

    current_levels: list[StockLevelResponse] = Field(
        default_factory=list, description="All part stock levels"
    )
    below_threshold: list[StockLevelResponse] = Field(
        default_factory=list, description="Parts below minimum threshold"
    )
    movement_history: list[StockMovementResponse] = Field(
        default_factory=list, description="Recent stock movements"
    )


class ReorderAlertResponse(BaseModel):
    """Single reorder alert.

    Requirements: 62.3
    """

    part_id: str = Field(..., description="Part UUID")
    part_name: str = Field(..., description="Part name")
    part_number: Optional[str] = Field(None, description="Part number / SKU")
    current_stock: int = Field(..., description="Current stock")
    min_threshold: int = Field(..., description="Minimum threshold")
    reorder_quantity: int = Field(..., description="Suggested reorder quantity")


class ReorderAlertListResponse(BaseModel):
    """GET /api/v1/inventory/stock/reorder-alerts response.

    Requirements: 62.3
    """

    alerts: list[ReorderAlertResponse] = Field(
        default_factory=list, description="Parts needing reorder"
    )
    total: int = Field(0, description="Total alerts")


class StockAdjustmentResponse(BaseModel):
    """PUT /api/v1/inventory/stock/{part_id} response.

    Requirements: 62.5
    """

    message: str
    stock_level: StockLevelResponse
    movement: StockMovementResponse


# ---------------------------------------------------------------------------
# Supplier schemas — Requirements: 63.1, 63.2, 63.3
# ---------------------------------------------------------------------------


class SupplierCreate(BaseModel):
    """POST /api/v1/inventory/suppliers — create a supplier.

    Requirements: 63.1
    """

    name: str = Field(..., min_length=1, max_length=255, description="Supplier name")
    contact_name: Optional[str] = Field(
        None, max_length=255, description="Contact person"
    )
    email: Optional[str] = Field(None, max_length=255, description="Email address")
    phone: Optional[str] = Field(None, max_length=50, description="Phone number")
    address: Optional[str] = Field(None, description="Physical address")
    account_number: Optional[str] = Field(
        None, max_length=100, description="Account number with supplier"
    )


class SupplierResponse(BaseModel):
    """Supplier record in API responses.

    Requirements: 63.1
    """

    id: str = Field(..., description="Supplier UUID")
    name: str = Field(..., description="Supplier name")
    contact_name: Optional[str] = Field(None, description="Contact person")
    email: Optional[str] = Field(None, description="Email address")
    phone: Optional[str] = Field(None, description="Phone number")
    address: Optional[str] = Field(None, description="Physical address")
    account_number: Optional[str] = Field(None, description="Account number")
    created_at: str = Field(..., description="ISO 8601 timestamp")


class SupplierListResponse(BaseModel):
    """GET /api/v1/inventory/suppliers response."""

    suppliers: list[SupplierResponse] = Field(
        default_factory=list, description="Supplier records"
    )
    total: int = Field(0, description="Total number of suppliers")


class PartSupplierLink(BaseModel):
    """POST /api/v1/inventory/suppliers/{id}/link-part — link a part to a supplier.

    Requirements: 63.2
    """

    part_id: str = Field(..., description="Part UUID from parts catalogue")
    supplier_part_number: Optional[str] = Field(
        None, max_length=100, description="Supplier-specific part number"
    )
    supplier_cost: Optional[float] = Field(
        None, ge=0, description="Supplier cost for this part"
    )
    is_preferred: bool = Field(
        False, description="Whether this is the preferred supplier for this part"
    )


class PartSupplierLinkResponse(BaseModel):
    """Response for a part-supplier link."""

    id: str = Field(..., description="Link UUID")
    part_id: str = Field(..., description="Part UUID")
    supplier_id: str = Field(..., description="Supplier UUID")
    supplier_part_number: Optional[str] = None
    supplier_cost: Optional[float] = None
    is_preferred: bool = False


class PurchaseOrderItem(BaseModel):
    """Single item in a purchase order request."""

    part_id: str = Field(..., description="Part UUID")
    quantity: int = Field(..., gt=0, description="Quantity to order")


class PurchaseOrderRequest(BaseModel):
    """POST /api/v1/inventory/purchase-orders — generate purchase order PDF.

    Requirements: 63.3
    """

    supplier_id: str = Field(..., description="Supplier UUID")
    items: list[PurchaseOrderItem] = Field(
        ..., min_length=1, description="Parts to order"
    )
    notes: Optional[str] = Field(None, description="Additional notes for the PO")
