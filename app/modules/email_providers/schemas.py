"""Pydantic schemas for Email Providers."""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class EmailProviderResponse(BaseModel):
    """Single email provider."""
    id: str
    provider_key: str
    display_name: str
    description: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_encryption: str | None = None
    priority: int = 1
    is_active: bool
    credentials_set: bool
    config: dict = Field(default_factory=dict)
    setup_guide: str | None = None
    created_at: datetime
    updated_at: datetime


class EmailProviderListResponse(BaseModel):
    """GET /api/v2/admin/email-providers response."""
    providers: list[EmailProviderResponse]
    active_provider: str | None = None


class EmailProviderActivateResponse(BaseModel):
    """Response after activating a provider."""
    message: str
    provider: EmailProviderResponse


class EmailProviderCredentialsRequest(BaseModel):
    """PUT credentials for an email provider."""
    credentials: dict = Field(..., description="Provider-specific credentials")
    smtp_host: str | None = Field(None, description="Override SMTP host")
    smtp_port: int | None = Field(None, ge=1, le=65535, description="Override SMTP port")
    smtp_encryption: str | None = Field(None, pattern=r"^(none|tls|ssl)$", description="SMTP encryption type")
    from_email: str | None = Field(None, description="Default from email")
    from_name: str | None = Field(None, description="Default from display name")
    reply_to: str | None = Field(None, description="Reply-to address")


class EmailProviderCredentialsResponse(BaseModel):
    """Response after saving credentials."""
    message: str
    credentials_set: bool


class EmailProviderTestRequest(BaseModel):
    """POST test email."""
    to_email: str = Field(..., min_length=1, description="Recipient email")


class EmailProviderTestResponse(BaseModel):
    """Response after sending test email."""
    success: bool
    message: str
    error: str | None = None


class EmailProviderPriorityRequest(BaseModel):
    """PUT priority for an email provider."""
    priority: int = Field(..., ge=1, le=10, description="Priority (1 = highest)")


class EmailProviderPriorityResponse(BaseModel):
    """Response after updating priority."""
    message: str
    priority: int
