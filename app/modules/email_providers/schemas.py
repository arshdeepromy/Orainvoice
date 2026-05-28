"""Pydantic schemas for Email Providers."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field, field_serializer


class EmailProviderResponse(BaseModel):
    """Single email provider.

    Bug 2 fix (email-delivery-visibility-fixes spec, task 14): any
    ``*_webhook_secret`` key in the ``config`` dict is redacted to the
    sentinel string ``"***"`` before the payload leaves this process.
    The raw secret is needed only by the bounce-webhook handler at
    ``app/modules/notifications/router.py``, which reads it directly
    from the ORM ``email_providers.config`` column — never via this
    response shape — so redacting here closes the read-side leak
    without breaking webhook signature verification.
    """
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

    @field_serializer("config")
    def _redact_webhook_secrets(self, config: dict[str, Any]) -> dict[str, Any]:
        """Replace any ``*_webhook_secret`` value with ``"***"``.

        Per Bug 2 / Req 3.9 + 4.9: redact ``brevo_webhook_secret`` and
        ``sendgrid_webhook_secret`` (and any future ``<provider>_webhook_secret``
        key by suffix match) when present; pass other config keys
        (``from_email``, ``from_name``, ``reply_to``) through unchanged.
        """
        if not config:
            return config
        return {
            key: ("***" if key.endswith("_webhook_secret") and value else value)
            for key, value in config.items()
        }


class EmailProviderListResponse(BaseModel):
    """GET /api/v2/admin/email-providers response.

    Phase 5 (task 5.3) extension: ``active_providers`` lists every active
    provider key in ``priority ASC`` order so the admin UI can render
    the multi-active failover chain. ``active_provider`` (singular) is
    retained for one release for backwards compatibility with any
    pre-Phase-5 frontend build still in the wild — it is the first
    element of ``active_providers`` (or ``None``).
    """
    providers: list[EmailProviderResponse]
    active_provider: str | None = None
    active_providers: list[str] = Field(default_factory=list)


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
    webhook_secret: str | None = Field(
        None,
        description=(
            "Webhook signing secret (provider-specific). Persisted "
            "under config['<provider_key>_webhook_secret']. Empty "
            "string is treated as 'no change'."
        ),
    )


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



# ---------------------------------------------------------------------------
# Delivery Health (Phase 8c, task 9.9 — design API Endpoints)
# ---------------------------------------------------------------------------


class BounceWindowStats(BaseModel):
    """Per-window aggregate bounce statistics.

    The Delivery Health UI renders one card per window (24h / 7d / 30d)
    showing ``total`` plus a horizontal bar by ``provider_key``.
    """

    total: int = Field(0, description="Total bounces in the window")
    by_provider: dict[str, int] = Field(
        default_factory=dict,
        description="Bounce count keyed by provider_key (excludes nulls)",
    )


class DeliveryHealthStats(BaseModel):
    """Stats payload for the three windows shown on the Delivery Health page."""

    last_24h: BounceWindowStats = Field(default_factory=BounceWindowStats)
    last_7d: BounceWindowStats = Field(default_factory=BounceWindowStats)
    last_30d: BounceWindowStats = Field(default_factory=BounceWindowStats)


class BounceRow(BaseModel):
    """A single ``bounced_addresses`` row, decorated with linked-entity hints."""

    id: str
    org_id: str | None = None
    email_address: str
    bounce_kind: str
    reason: str | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    hit_count: int
    expires_at: datetime | None = None
    # Convenience fields computed at response time per design API
    # Endpoints — let the UI render a "View customer" link without a
    # second round-trip.
    linked_customer_id: str | None = None
    linked_user_id: str | None = None
    # The most recent provider that bounced this address, derived from
    # ``notification_log.provider_key`` matching the recipient. Optional;
    # NULL when no log row matches.
    provider_key: str | None = None


class DeliveryHealthResponse(BaseModel):
    """``GET /api/v2/admin/email-providers/delivery-health`` response."""

    stats: DeliveryHealthStats
    recent_bounces: list[BounceRow]
    total: int = Field(
        0,
        description="Total bounce rows visible to the caller after RLS",
    )


class ClearBounceResponse(BaseModel):
    """``DELETE /api/v2/admin/email-providers/bounced-addresses/{id}`` response."""

    message: str
    cleared: bool
