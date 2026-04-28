"""Pydantic schemas for the public landing page endpoints."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class DemoRequestPayload(BaseModel):
    """POST /api/v1/public/demo-request request body."""

    full_name: str = Field(..., min_length=1, max_length=200)
    business_name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    phone: str | None = Field(None, max_length=50)
    message: str | None = Field(None, max_length=2000)
    website: str | None = None  # honeypot field — hidden from real users


class DemoRequestResponse(BaseModel):
    """POST /api/v1/public/demo-request response."""

    success: bool
    message: str


class PrivacyPolicyResponse(BaseModel):
    """GET /api/v1/public/privacy-policy response."""

    content: str | None = None
    last_updated: str | None = None


class PrivacyPolicyUpdatePayload(BaseModel):
    """PUT /api/v1/admin/privacy-policy request body."""

    content: str = Field(..., min_length=1, max_length=100000)


class PrivacyPolicyUpdateResponse(BaseModel):
    """PUT /api/v1/admin/privacy-policy response."""

    success: bool
    last_updated: str
