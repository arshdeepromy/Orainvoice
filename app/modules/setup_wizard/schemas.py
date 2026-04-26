"""Pydantic v2 schemas for the setup wizard.

Step-specific data schemas and response models.

**Validates: Requirement 5.1, 5.2, 5.3, 5.9, 5.10**
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Step 1 — Country selection
# ---------------------------------------------------------------------------

class CountryStepData(BaseModel):
    """Data submitted for wizard step 1 (Country)."""

    country_code: str = Field(..., min_length=2, max_length=2)


# ---------------------------------------------------------------------------
# Step 2 — Trade category selection
# ---------------------------------------------------------------------------

class TradeStepData(BaseModel):
    """Data submitted for wizard step 2 (Trade)."""

    trade_category_slug: str = Field(..., min_length=1, max_length=100)


# ---------------------------------------------------------------------------
# Step 3 — Business details
# ---------------------------------------------------------------------------

class BusinessStepData(BaseModel):
    """Data submitted for wizard step 3 (Business Details)."""

    business_name: str = Field(..., min_length=1, max_length=255)
    trading_name: str | None = Field(None, max_length=255)
    registration_number: str | None = Field(None, max_length=100)
    tax_number: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=50)
    address_unit: str | None = Field(None, max_length=100)
    address_street: str | None = Field(None, max_length=255)
    address_city: str | None = Field(None, max_length=100)
    address_state: str | None = Field(None, max_length=100)
    address_postcode: str | None = Field(None, max_length=20)
    website: str | None = Field(None, max_length=255)


# ---------------------------------------------------------------------------
# Step 4 — Branding
# ---------------------------------------------------------------------------

class BrandingStepData(BaseModel):
    """Data submitted for wizard step 4 (Branding)."""

    logo_url: str | None = None
    primary_colour: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    secondary_colour: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")


# ---------------------------------------------------------------------------
# Step 5 — Module selection
# ---------------------------------------------------------------------------

class ModulesStepData(BaseModel):
    """Data submitted for wizard step 5 (Modules)."""

    enabled_modules: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Step 6 — Catalogue seeding
# ---------------------------------------------------------------------------

class CatalogueItem(BaseModel):
    """A single service or product for initial catalogue seeding."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    price: float = Field(0.0, ge=0)
    unit_of_measure: str = "each"
    item_type: str = "service"  # "service" or "product"


class CatalogueStepData(BaseModel):
    """Data submitted for wizard step 6 (Catalogue)."""

    items: list[CatalogueItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Step submission request / response
# ---------------------------------------------------------------------------

class WizardStepRequest(BaseModel):
    """Generic wrapper — the caller sends step-specific data."""

    data: dict = Field(default_factory=dict)
    skip: bool = False


class StepResult(BaseModel):
    """Result of processing a single wizard step."""

    step_number: int
    completed: bool
    skipped: bool = False
    message: str = ""
    applied_defaults: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Progress response
# ---------------------------------------------------------------------------

class WizardProgressResponse(BaseModel):
    """Current wizard progress for an organisation."""

    org_id: UUID
    steps: dict[str, bool]
    wizard_completed: bool
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
