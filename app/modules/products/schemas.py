"""Pydantic v2 schemas for product CRUD, category tree, and CSV import.

**Validates: Requirement 9.1, 9.2, 9.9**
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Product Category schemas
# ---------------------------------------------------------------------------

class ProductCategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    parent_id: UUID | None = None
    display_order: int = 0


class ProductCategoryUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    parent_id: UUID | None = None
    display_order: int | None = None


class ProductCategoryResponse(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    parent_id: UUID | None = None
    display_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProductCategoryTreeNode(BaseModel):
    """Category with nested children for tree representation."""
    id: UUID
    name: str
    parent_id: UUID | None = None
    display_order: int
    children: list["ProductCategoryTreeNode"] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ProductCategoryListResponse(BaseModel):
    categories: list[ProductCategoryResponse]
    total: int


class ProductCategoryTreeResponse(BaseModel):
    tree: list[ProductCategoryTreeNode]
    total: int


# ---------------------------------------------------------------------------
# Product schemas
# ---------------------------------------------------------------------------

class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=300)
    sku: str | None = Field(None, max_length=100)
    barcode: str | None = Field(None, max_length=100)
    category_id: UUID | None = None
    description: str | None = None
    unit_of_measure: str = "each"
    sale_price: Decimal = Decimal("0")
    cost_price: Decimal | None = Decimal("0")
    tax_applicable: bool = True
    tax_rate_override: Decimal | None = None
    stock_quantity: Decimal = Decimal("0")
    low_stock_threshold: Decimal | None = Decimal("0")
    reorder_quantity: Decimal | None = Decimal("0")
    allow_backorder: bool = False
    supplier_id: UUID | None = None
    supplier_sku: str | None = None
    images: list[str] = Field(default_factory=list)
    location_id: UUID | None = None


class ProductUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=300)
    sku: str | None = None
    barcode: str | None = None
    category_id: UUID | None = None
    description: str | None = None
    unit_of_measure: str | None = None
    sale_price: Decimal | None = None
    cost_price: Decimal | None = None
    tax_applicable: bool | None = None
    tax_rate_override: Decimal | None = None
    low_stock_threshold: Decimal | None = None
    reorder_quantity: Decimal | None = None
    allow_backorder: bool | None = None
    supplier_id: UUID | None = None
    supplier_sku: str | None = None
    images: list[str] | None = None
    location_id: UUID | None = None


class ProductResponse(BaseModel):
    id: UUID
    org_id: UUID
    location_id: UUID | None = None
    name: str
    sku: str | None = None
    barcode: str | None = None
    category_id: UUID | None = None
    description: str | None = None
    unit_of_measure: str
    sale_price: Decimal
    cost_price: Decimal | None = None
    tax_applicable: bool
    tax_rate_override: Decimal | None = None
    stock_quantity: Decimal
    low_stock_threshold: Decimal | None = None
    reorder_quantity: Decimal | None = None
    allow_backorder: bool
    supplier_id: UUID | None = None
    supplier_sku: str | None = None
    images: list
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProductListResponse(BaseModel):
    products: list[ProductResponse]
    total: int
    page: int = 1
    page_size: int = 50


# ---------------------------------------------------------------------------
# CSV Import schemas
# ---------------------------------------------------------------------------

class CSVFieldMapping(BaseModel):
    """Maps CSV column headers to product fields."""
    source_column: str
    target_field: str


class CSVImportPreview(BaseModel):
    """Preview of parsed CSV data before committing."""
    total_rows: int
    valid_rows: int
    error_rows: int
    errors: list[dict] = Field(default_factory=list)
    preview_data: list[dict] = Field(default_factory=list)


class CSVImportRequest(BaseModel):
    """Request to import products from CSV data."""
    data: list[dict]
    field_mapping: list[CSVFieldMapping] = Field(default_factory=list)
    preview_only: bool = True


class CSVImportResult(BaseModel):
    """Result of a committed CSV import."""
    imported_count: int
    skipped_count: int
    error_count: int
    errors: list[dict] = Field(default_factory=list)
