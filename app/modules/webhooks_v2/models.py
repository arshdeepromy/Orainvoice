"""SQLAlchemy ORM models for the outbound webhook management module.

Maps to tables created by migration 0054: outbound_webhooks, webhook_delivery_log.

**Validates: Requirement 47 — Webhook Management and Security**
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, LargeBinary, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OutboundWebhook(Base):
    """An outbound webhook registration for an organisation."""

    __tablename__ = "outbound_webhooks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    target_url: Mapped[str] = mapped_column(
        String(500), nullable=False,
    )
    event_types: Mapped[list] = mapped_column(
        JSONB, nullable=False,
    )
    secret_encrypted: Mapped[bytes] = mapped_column(
        LargeBinary, nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default="true", nullable=False,
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False,
    )
    last_delivery_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class WebhookDeliveryLog(Base):
    """A single delivery attempt for an outbound webhook."""

    __tablename__ = "webhook_delivery_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    webhook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    event_type: Mapped[str] = mapped_column(
        String(100), nullable=False,
    )
    payload: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
    )
    response_status: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )
    response_time_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False,
    )
    error_details: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
