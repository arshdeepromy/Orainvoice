"""Pydantic v2 schemas for the franchise & multi-location module.

**Validates: Requirement 8 — Extended RBAC / Multi-Location**
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


# --- Location ---

class LocationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    invoice_prefix: str | None = Field(None, max_length=20)
    has_own_inventory: bool = False


class LocationUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    invoice_prefix: str | None = Field(None, max_length=20)
    has_own_inventory: bool | None = None
    is_active: bool | None = None


class LocationResponse(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    invoice_prefix: str | None = None
    has_own_inventory: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Stock Transfer ---

class StockTransferCreate(BaseModel):
    from_location_id: UUID
    to_location_id: UUID
    product_id: UUID
    quantity: Decimal = Field(..., gt=0)


class StockTransferResponse(BaseModel):
    id: UUID
    org_id: UUID
    from_location_id: UUID
    to_location_id: UUID
    product_id: UUID
    quantity: Decimal
    status: str
    requested_by: UUID | None = None
    approved_by: UUID | None = None
    created_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


# --- Franchise Group ---

class FranchiseGroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class FranchiseGroupResponse(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    created_by: UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Dashboard / Aggregate views ---

class LocationMetrics(BaseModel):
    location_id: UUID
    location_name: str
    revenue: Decimal = Decimal("0")
    outstanding: Decimal = Decimal("0")
    invoice_count: int = 0


class HeadOfficeView(BaseModel):
    total_revenue: Decimal = Decimal("0")
    total_outstanding: Decimal = Decimal("0")
    location_metrics: list[LocationMetrics] = []


class FranchiseDashboardMetrics(BaseModel):
    total_organisations: int = 0
    total_revenue: Decimal = Decimal("0")
    total_outstanding: Decimal = Decimal("0")
    total_locations: int = 0
