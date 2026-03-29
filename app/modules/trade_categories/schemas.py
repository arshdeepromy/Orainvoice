"""Pydantic v2 schemas for trade category and trade family CRUD.

**Validates: Requirement 3.1, 3.2, 3.4, 3.6**
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


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
    invoice_template_layout: str = "standard"
    recommended_modules: list[str] = Field(default_factory=list)
    terminology_overrides: dict[str, str] = Field(default_factory=dict)
    default_services: list[DefaultServiceItem] = Field(default_factory=list)
    default_products: list[DefaultProductItem] = Field(default_factory=list)
    default_expense_categories: list[dict] = Field(default_factory=list)
    default_job_templates: list[dict] = Field(default_factory=list)
    compliance_notes: dict[str, str] = Field(default_factory=dict)
    seed_data_version: int = 0
    is_active: bool = True
    is_retired: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def _parse_json_field(cls, v, expected_type):
        """Parse a field that might be a JSON string instead of a native type."""
        import json as _json
        if isinstance(v, str):
            try:
                return _json.loads(v)
            except (ValueError, TypeError):
                return expected_type()
        if v is None:
            return expected_type()
        return v

    @field_validator("recommended_modules", mode="before")
    @classmethod
    def parse_recommended_modules(cls, v):
        return cls._parse_json_field(v, list)

    @field_validator("terminology_overrides", mode="before")
    @classmethod
    def parse_terminology_overrides(cls, v):
        result = cls._parse_json_field(v, dict)
        return result if isinstance(result, dict) else {}

    @field_validator("default_services", mode="before")
    @classmethod
    def parse_default_services(cls, v):
        return cls._parse_json_field(v, list)

    @field_validator("default_products", mode="before")
    @classmethod
    def parse_default_products(cls, v):
        return cls._parse_json_field(v, list)

    @field_validator("default_expense_categories", mode="before")
    @classmethod
    def parse_default_expense_categories(cls, v):
        return cls._parse_json_field(v, list)

    @field_validator("default_job_templates", mode="before")
    @classmethod
    def parse_default_job_templates(cls, v):
        return cls._parse_json_field(v, list)

    @field_validator("compliance_notes", mode="before")
    @classmethod
    def parse_compliance_notes(cls, v):
        result = cls._parse_json_field(v, dict)
        # DB has some rows with [] instead of {} for this field
        return result if isinstance(result, dict) else {}


class TradeCategoryListResponse(BaseModel):
    """List of trade categories."""

    categories: list[TradeCategoryResponse]
    total: int


class SeedDataExport(BaseModel):
    """Full seed data export for version control and cross-env deployment."""

    families: list[TradeFamilyResponse]
    categories: list[TradeCategoryResponse]
