"""Pydantic v2 schemas for compliance profile CRUD.

**Validates: Requirement 5.2**
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TaxRate(BaseModel):
    """A single tax rate entry within a compliance profile."""

    name: str = Field(..., min_length=1, max_length=100)
    rate: float = Field(..., ge=0, le=100)
    is_default: bool = False


class ComplianceProfileCreate(BaseModel):
    """Create a new compliance profile."""

    country_code: str = Field(..., min_length=2, max_length=2)
    country_name: str = Field(..., min_length=1, max_length=100)
    tax_label: str = Field(..., min_length=1, max_length=20)
    default_tax_rates: list[TaxRate] = Field(..., min_length=1)
    tax_number_label: str | None = None
    tax_number_regex: str | None = None
    tax_inclusive_default: bool = True
    date_format: str = Field(..., min_length=1, max_length=20)
    number_format: str = Field(..., min_length=1, max_length=20)
    currency_code: str = Field(..., min_length=3, max_length=3)
    report_templates: list[str] = Field(default_factory=list)
    gdpr_applicable: bool = False


class ComplianceProfileUpdate(BaseModel):
    """Update an existing compliance profile."""

    country_name: str | None = Field(None, min_length=1, max_length=100)
    tax_label: str | None = Field(None, min_length=1, max_length=20)
    default_tax_rates: list[TaxRate] | None = None
    tax_number_label: str | None = None
    tax_number_regex: str | None = None
    tax_inclusive_default: bool | None = None
    date_format: str | None = Field(None, min_length=1, max_length=20)
    number_format: str | None = Field(None, min_length=1, max_length=20)
    currency_code: str | None = Field(None, min_length=3, max_length=3)
    report_templates: list[str] | None = None
    gdpr_applicable: bool | None = None


class ComplianceProfileResponse(BaseModel):
    """Full compliance profile representation."""

    id: UUID
    country_code: str
    country_name: str
    tax_label: str
    default_tax_rates: list[TaxRate]
    tax_number_label: str | None = None
    tax_number_regex: str | None = None
    tax_inclusive_default: bool
    date_format: str
    number_format: str
    currency_code: str
    report_templates: list[str]
    gdpr_applicable: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ComplianceProfileListResponse(BaseModel):
    """List of compliance profiles."""

    profiles: list[ComplianceProfileResponse]
    total: int
