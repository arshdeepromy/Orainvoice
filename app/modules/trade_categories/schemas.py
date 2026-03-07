"""Pydantic v2 schemas for trade category and trade family CRUD.

**Validates: Requirement 3.1, 3.2, 3.4, 3.6**
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Nested value objects
# ---------------------------------------------------------------------------

class DefaultServiceItem(BaseModel):
    """A default service pre-populated for new orgs in this trade."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    default_price: float = 0.0
    unit_of_measure: str = "each"


class DefaultProductItem(BaseModel):
    """A default product pre-populated for new orgs in this trade."""

    name: str = Field(..., min_length=1, max_length=255)
    default_price: float = 0.0
    unit_of_measure: str = "each"


# ---------------------------------------------------------------------------
# Trade Family schemas
# ---------------------------------------------------------------------------

class TradeFamilyCreate(BaseModel):
    """Create a new trade family."""

    slug: str = Field(..., min_length=1, max_length=100)
    display_name: str = Field(..., min_length=1, max_length=255)
    icon: str | None = None
    display_order: int = 0


class TradeFamilyResponse(BaseModel):
    """Full trade family representation."""

    id: UUID
    slug: str
    display_name: str
    icon: str | None = None
    display_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TradeFamilyListResponse(BaseModel):
    """List of trade families."""

    families: list[TradeFamilyResponse]
    total: int


# ---------------------------------------------------------------------------
# Trade Category schemas
# ---------------------------------------------------------------------------

class TradeCategoryCreate(BaseModel):
    """Create a new trade category."""

    slug: str = Field(..., min_length=1, max_length=100)
    display_name: str = Field(..., min_length=1, max_length=255)
    family_id: UUID
    icon: str | None = None
    description: str | None = None
    invoice_template_layout: str = "standard"
    recommended_modules: list[str] = Field(default_factory=list)
    terminology_overrides: dict[str, str] = Field(default_factory=dict)
    default_services: list[DefaultServiceItem] = Field(default_factory=list)
    default_products: list[DefaultProductItem] = Field(default_factory=list)
    default_expense_categories: list[dict] = Field(default_factory=list)
    default_job_templates: list[dict] = Field(default_factory=list)
    compliance_notes: dict[str, str] = Field(default_factory=dict)


class TradeCategoryUpdate(BaseModel):
    """Update an existing trade category."""

    display_name: str | None = Field(None, min_length=1, max_length=255)
    icon: str | None = None
    description: str | None = None
    invoice_template_layout: str | None = None
    recommended_modules: list[str] | None = None
    terminology_overrides: dict[str, str] | None = None
    default_services: list[DefaultServiceItem] | None = None
    default_products: list[DefaultProductItem] | None = None
    default_expense_categories: list[dict] | None = None
    default_job_templates: list[dict] | None = None
    compliance_notes: dict[str, str] | None = None
    is_retired: bool | None = None


class TradeCategoryResponse(BaseModel):
    """Full trade category representation."""

    id: UUID
    slug: str
    display_name: str
    family_id: UUID
    icon: str | None = None
    description: str | None = None
    invoice_template_layout: str
    recommended_modules: list[str]
    terminology_overrides: dict[str, str]
    default_services: list[DefaultServiceItem]
    default_products: list[DefaultProductItem]
    default_expense_categories: list[dict]
    default_job_templates: list[dict]
    compliance_notes: dict[str, str]
    seed_data_version: int
    is_active: bool
    is_retired: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TradeCategoryListResponse(BaseModel):
    """List of trade categories."""

    categories: list[TradeCategoryResponse]
    total: int


class SeedDataExport(BaseModel):
    """Full seed data export for version control and cross-env deployment."""

    families: list[TradeFamilyResponse]
    categories: list[TradeCategoryResponse]
