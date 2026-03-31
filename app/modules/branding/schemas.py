"""Pydantic v2 schemas for the platform branding module.

**Validates: Requirement 1 — Platform Rebranding**
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class BrandingUpdate(BaseModel):
    platform_name: str | None = Field(None, min_length=1, max_length=100)
    logo_url: str | None = None
    primary_colour: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    secondary_colour: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    website_url: str | None = None
    signup_url: str | None = None
    support_email: str | None = None
    terms_url: str | None = None
    auto_detect_domain: bool | None = None
    platform_theme: str | None = Field(None, max_length=50, description="Active theme ID (e.g. classic, violet)")


class BrandingResponse(BaseModel):
    id: UUID
    platform_name: str
    logo_url: str | None = None
    primary_colour: str
    secondary_colour: str
    website_url: str | None = None
    signup_url: str | None = None
    support_email: str | None = None
    terms_url: str | None = None
    auto_detect_domain: bool
    platform_theme: str = "classic"
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PublicBrandingResponse(BaseModel):
    """Public-facing branding for login/signup/public pages."""
    platform_name: str
    logo_url: str | None = None
    primary_colour: str
    secondary_colour: str
    support_email: str | None = None
    terms_url: str | None = None
    website_url: str | None = None
    platform_theme: str = "classic"

    model_config = {"from_attributes": True}


class PoweredByConfig(BaseModel):
    """Subset of branding used in PDF/email footers."""
    platform_name: str
    logo_url: str | None = None
    signup_url: str | None = None
    website_url: str | None = None
    show_powered_by: bool = True

    class PublicBrandingResponse(BaseModel):
        """Public-facing branding for login/signup/public pages."""
        platform_name: str
        logo_url: str | None = None
        primary_colour: str
        secondary_colour: str
        support_email: str | None = None
        terms_url: str | None = None
        website_url: str | None = None

        model_config = {"from_attributes": True}

