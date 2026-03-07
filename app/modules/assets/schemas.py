"""Pydantic v2 schemas for the extended asset tracking module.

**Validates: Extended Asset Tracking — Tasks 45.4, 45.5, 45.6**
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Trade-category → asset-type mapping
# ---------------------------------------------------------------------------

TRADE_FAMILY_ASSET_TYPE_MAP: dict[str, str] = {
    "automotive-transport": "vehicle",
    "electrical-mechanical": "equipment",
    "plumbing-gas": "equipment",
    "building-construction": "property",
    "landscaping-outdoor": "property",
    "cleaning-facilities": "property",
    "it-technology": "device",
    "creative-professional": "device",
    "accounting-legal-financial": "device",
    "health-wellness": "device",
    "food-hospitality": "equipment",
    "retail": "equipment",
    "hair-beauty-personal-care": "equipment",
    "trades-support-hire": "equipment",
    "freelancing-contracting": "equipment",
}

AUTOMOTIVE_FAMILIES = {"automotive-transport"}


def asset_type_for_trade_family(family_slug: str) -> str:
    """Return the default asset type for a trade family slug."""
    return TRADE_FAMILY_ASSET_TYPE_MAP.get(family_slug, "equipment")


def is_automotive_trade(family_slug: str | None) -> bool:
    """Return True if the trade family is automotive."""
    return family_slug in AUTOMOTIVE_FAMILIES if family_slug else False


# ---------------------------------------------------------------------------
# Custom field definition schema
# ---------------------------------------------------------------------------

class CustomFieldDefinition(BaseModel):
    """Schema for a single custom field definition set by Org_Admin."""
    name: str = Field(..., min_length=1, max_length=100)
    field_type: str = Field(..., pattern=r"^(text|number|date|dropdown)$")
    required: bool = False
    options: list[str] | None = Field(
        None,
        description="Dropdown options; required when field_type is 'dropdown'",
    )


# ---------------------------------------------------------------------------
# Asset CRUD schemas
# ---------------------------------------------------------------------------

class AssetCreate(BaseModel):
    customer_id: UUID | None = None
    asset_type: str = Field(..., min_length=1, max_length=50)
    identifier: str | None = Field(None, max_length=200)
    make: str | None = Field(None, max_length=100)
    model: str | None = Field(None, max_length=100)
    year: int | None = None
    description: str | None = None
    serial_number: str | None = Field(None, max_length=200)
    location: str | None = None
    custom_fields: dict[str, Any] = Field(default_factory=dict)


class AssetUpdate(BaseModel):
    customer_id: UUID | None = None
    asset_type: str | None = Field(None, min_length=1, max_length=50)
    identifier: str | None = Field(None, max_length=200)
    make: str | None = Field(None, max_length=100)
    model: str | None = Field(None, max_length=100)
    year: int | None = None
    description: str | None = None
    serial_number: str | None = Field(None, max_length=200)
    location: str | None = None
    custom_fields: dict[str, Any] | None = None
    is_active: bool | None = None


class AssetResponse(BaseModel):
    id: UUID
    org_id: UUID
    customer_id: UUID | None = None
    asset_type: str
    identifier: str | None = None
    make: str | None = None
    model: str | None = None
    year: int | None = None
    description: str | None = None
    serial_number: str | None = None
    location: str | None = None
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    carjam_data: dict[str, Any] | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Service history response
# ---------------------------------------------------------------------------

class ServiceHistoryEntry(BaseModel):
    """A single entry in an asset's service history."""
    reference_type: str  # "invoice", "job", "quote"
    reference_id: UUID
    reference_number: str | None = None
    description: str | None = None
    date: datetime | None = None
    status: str | None = None


class AssetServiceHistory(BaseModel):
    asset_id: UUID
    entries: list[ServiceHistoryEntry] = []
