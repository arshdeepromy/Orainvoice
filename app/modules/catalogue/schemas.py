"""Pydantic schemas for the Service Catalogue module.

Requirements: 27.1, 27.2, 27.3
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class ServiceCreateRequest(BaseModel):
    """POST /api/v1/catalogue/services request body.

    Requirements: 27.1
    """

    name: str = Field(
        ..., min_length=1, max_length=255, description="Service name"
    )
    description: Optional[str] = Field(
        None, max_length=5000, description="Service description"
    )
    default_price: str = Field(
        ..., description="Default price ex-GST as decimal string (e.g. '85.00')"
    )
    is_gst_exempt: bool = Field(
        False, description="True if GST does not apply to this service"
    )
    category: Literal["warrant", "service", "repair", "diagnostic"] = Field(
        ..., description="Service category"
    )
    is_active: bool = Field(True, description="Whether the service is active")


class ServiceUpdateRequest(BaseModel):
    """PUT /api/v1/catalogue/services/{id} request body.

    All fields optional — only provided fields are updated.
    Requirements: 27.1
    """

    name: Optional[str] = Field(
        None, min_length=1, max_length=255, description="Service name"
    )
    description: Optional[str] = Field(
        None, max_length=5000, description="Service description"
    )
    default_price: Optional[str] = Field(
        None, description="Default price ex-GST as decimal string"
    )
    is_gst_exempt: Optional[bool] = Field(
        None, description="True if GST does not apply"
    )
    category: Optional[Literal["warrant", "service", "repair", "diagnostic"]] = Field(
        None, description="Service category"
    )
    is_active: Optional[bool] = Field(
        None, description="Active/inactive toggle"
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ServiceResponse(BaseModel):
    """Single service catalogue entry in API responses.

    Requirements: 27.1
    """

    id: str = Field(..., description="Service UUID")
    name: str = Field(..., description="Service name")
    description: Optional[str] = Field(None, description="Service description")
    default_price: str = Field(..., description="Default price ex-GST")
    is_gst_exempt: bool = Field(False, description="GST exemption flag")
    category: str = Field(..., description="Service category")
    is_active: bool = Field(True, description="Active/inactive status")
    created_at: str = Field(..., description="ISO 8601 creation timestamp")
    updated_at: str = Field(..., description="ISO 8601 last update timestamp")


class ServiceListResponse(BaseModel):
    """GET /api/v1/catalogue/services response."""

    services: list[ServiceResponse] = Field(
        default_factory=list, description="List of services"
    )
    total: int = Field(0, description="Total number of results")


class ServiceCreateResponse(BaseModel):
    """POST /api/v1/catalogue/services response."""

    message: str
    service: ServiceResponse


class ServiceUpdateResponse(BaseModel):
    """PUT /api/v1/catalogue/services/{id} response."""

    message: str
    service: ServiceResponse


# ===========================================================================
# Items Catalogue schemas — Requirements: 7.3, 7.4, 7.5
# ===========================================================================


class ItemCreateRequest(BaseModel):
    """POST /api/v1/catalogue/items request body.

    Requirements: 7.3
    """

    name: str = Field(
        ..., min_length=1, max_length=255, description="Item name"
    )
    description: Optional[str] = Field(
        None, max_length=5000, description="Item description"
    )
    default_price: str = Field(
        ..., description="Default price ex-GST as decimal string (e.g. '85.00')"
    )
    is_gst_exempt: bool = Field(
        False, description="True if GST does not apply to this item"
    )
    category: Optional[str] = Field(
        None, max_length=100, description="Free-text category"
    )
    is_active: bool = Field(True, description="Whether the item is active")


class ItemUpdateRequest(BaseModel):
    """PUT /api/v1/catalogue/items/{id} request body.

    All fields optional — only provided fields are updated.
    Requirements: 7.4
    """

    name: Optional[str] = Field(
        None, min_length=1, max_length=255, description="Item name"
    )
    description: Optional[str] = Field(
        None, max_length=5000, description="Item description"
    )
    default_price: Optional[str] = Field(
        None, description="Default price ex-GST as decimal string"
    )
    is_gst_exempt: Optional[bool] = Field(
        None, description="True if GST does not apply"
    )
    category: Optional[str] = Field(
        None, max_length=100, description="Free-text category"
    )
    is_active: Optional[bool] = Field(
        None, description="Active/inactive toggle"
    )


class ItemResponse(BaseModel):
    """Single item catalogue entry in API responses.

    Requirements: 7.5
    """

    id: str = Field(..., description="Item UUID")
    name: str = Field(..., description="Item name")
    description: Optional[str] = Field(None, description="Item description")
    default_price: str = Field(..., description="Default price ex-GST")
    is_gst_exempt: bool = Field(False, description="GST exemption flag")
    category: Optional[str] = Field(None, description="Free-text category")
    is_active: bool = Field(True, description="Active/inactive status")
    created_at: str = Field(..., description="ISO 8601 creation timestamp")
    updated_at: str = Field(..., description="ISO 8601 last update timestamp")


class ItemListResponse(BaseModel):
    """GET /api/v1/catalogue/items response."""

    items: list[ItemResponse] = Field(
        default_factory=list, description="List of items"
    )
    total: int = Field(0, description="Total number of results")


class ItemCreateResponse(BaseModel):
    """POST /api/v1/catalogue/items response."""

    message: str
    item: ItemResponse


class ItemUpdateResponse(BaseModel):
    """PUT /api/v1/catalogue/items/{id} response."""

    message: str
    item: ItemResponse


# ===========================================================================
# Parts Catalogue schemas — Requirements: 28.1, 28.2
# ===========================================================================


class PartCreateRequest(BaseModel):
    """POST /api/v1/catalogue/parts request body.

    Requirements: 28.1
    """

    name: str = Field(
        ..., min_length=1, max_length=255, description="Part name"
    )
    part_number: Optional[str] = Field(
        None, max_length=100, description="Part number / SKU"
    )
    default_price: str = Field(
        ..., description="Default price as decimal string (e.g. '29.95')"
    )
    supplier: Optional[str] = Field(
        None, max_length=255, description="Supplier name (optional)"
    )
    is_active: bool = Field(True, description="Whether the part is active")


class PartResponse(BaseModel):
    """Single parts catalogue entry in API responses.

    Requirements: 28.1
    """

    id: str = Field(..., description="Part UUID")
    name: str = Field(..., description="Part name")
    part_number: Optional[str] = Field(None, description="Part number / SKU")
    default_price: str = Field(..., description="Default price")
    supplier: Optional[str] = Field(None, description="Supplier name")
    is_active: bool = Field(True, description="Active/inactive status")
    created_at: str = Field(..., description="ISO 8601 creation timestamp")
    updated_at: str = Field(..., description="ISO 8601 last update timestamp")


class PartListResponse(BaseModel):
    """GET /api/v1/catalogue/parts response."""

    parts: list[PartResponse] = Field(
        default_factory=list, description="List of parts"
    )
    total: int = Field(0, description="Total number of results")


class PartCreateResponse(BaseModel):
    """POST /api/v1/catalogue/parts response."""

    message: str
    part: PartResponse


# ===========================================================================
# Labour Rate schemas — Requirements: 28.3
# ===========================================================================


class LabourRateCreateRequest(BaseModel):
    """POST /api/v1/catalogue/labour-rates request body.

    Requirements: 28.3
    """

    name: str = Field(
        ..., min_length=1, max_length=100, description="Rate name (e.g. 'Standard Rate')"
    )
    hourly_rate: str = Field(
        ..., description="Hourly rate as decimal string (e.g. '95.00')"
    )
    is_active: bool = Field(True, description="Whether the rate is active")


class LabourRateResponse(BaseModel):
    """Single labour rate entry in API responses.

    Requirements: 28.3
    """

    id: str = Field(..., description="Labour rate UUID")
    name: str = Field(..., description="Rate name")
    hourly_rate: str = Field(..., description="Hourly rate")
    is_active: bool = Field(True, description="Active/inactive status")
    created_at: str = Field(..., description="ISO 8601 creation timestamp")
    updated_at: str = Field(..., description="ISO 8601 last update timestamp")


class LabourRateListResponse(BaseModel):
    """GET /api/v1/catalogue/labour-rates response."""

    labour_rates: list[LabourRateResponse] = Field(
        default_factory=list, description="List of labour rates"
    )
    total: int = Field(0, description="Total number of results")


class LabourRateCreateResponse(BaseModel):
    """POST /api/v1/catalogue/labour-rates response."""

    message: str
    labour_rate: LabourRateResponse
