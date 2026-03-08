"""Pydantic schemas for SMS Verification Providers."""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class SmsProviderResponse(BaseModel):
    """Single SMS provider in list responses."""
    id: str
    provider_key: str
    display_name: str
    description: str | None = None
    icon: str | None = None
    is_active: bool
    is_default: bool
    priority: int
    credentials_set: bool
    config: dict = Field(default_factory=dict)
    setup_guide: str | None = None
    created_at: datetime
    updated_at: datetime


class SmsProviderListResponse(BaseModel):
    """GET /api/v2/admin/sms-providers response."""
    providers: list[SmsProviderResponse]
    fallback_chain: list[SmsProviderChainItem] = Field(default_factory=list)


class SmsProviderChainItem(BaseModel):
    """A provider in the fallback chain order."""
    provider_key: str
    display_name: str
    priority: int


# Rebuild model to resolve forward ref
SmsProviderListResponse.model_rebuild()


class SmsProviderUpdateRequest(BaseModel):
    """PATCH /api/v2/admin/sms-providers/{provider_key} request body."""
    is_active: bool | None = None
    is_default: bool | None = None
    priority: int | None = Field(None, ge=0)
    config: dict | None = None


class SmsProviderUpdateResponse(BaseModel):
    """Response after updating a provider."""
    message: str
    provider: SmsProviderResponse


class SmsProviderCredentialsRequest(BaseModel):
    """PUT /api/v2/admin/sms-providers/{provider_key}/credentials."""
    credentials: dict = Field(..., description="Provider-specific credential fields")


class SmsProviderCredentialsResponse(BaseModel):
    """Response after saving credentials."""
    message: str
    credentials_set: bool


class SmsProviderTestRequest(BaseModel):
    """POST /api/v2/admin/sms-providers/{provider_key}/test."""
    to_number: str = Field(..., min_length=1, description="Phone number to test (E.164)")


class SmsProviderTestResponse(BaseModel):
    """Response after testing a provider."""
    success: bool
    message: str
    error: str | None = None
