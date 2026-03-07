"""SQLAlchemy ORM models for ecommerce module tables.

Maps to tables created by migration 0051.

**Validates: Requirement — Ecommerce Module**
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, LargeBinary, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class WooCommerceConnection(Base):
    """A WooCommerce store connection for an organisation."""

    __tablename__ = "woocommerce_connections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False,
    )
    store_url: Mapped[str] = mapped_column(String(500), nullable=False)
    consumer_key_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    consumer_secret_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sync_frequency_minutes: Mapped[int] = mapped_column(
        Integer, server_default="15", nullable=False,
    )
    auto_create_invoices: Mapped[bool] = mapped_column(
        Boolean, server_default="true", nullable=False,
    )
    invoice_status_on_import: Mapped[str] = mapped_column(
        String(20), server_default="draft", nullable=False,
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default="true", nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class EcommerceSyncLog(Base):
    """Log entry for an ecommerce sync operation."""

    __tablename__ = "ecommerce_sync_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class SkuMapping(Base):
    """Maps an external SKU to an internal product."""

    __tablename__ = "sku_mappings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    external_sku: Mapped[str] = mapped_column(String(100), nullable=False)
    internal_product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class ApiCredential(Base):
    """API credential for Zapier-compatible REST API access."""

    __tablename__ = "api_credentials"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    scopes: Mapped[dict] = mapped_column(JSONB, server_default='["read"]', nullable=False)
    rate_limit_per_minute: Mapped[int] = mapped_column(
        Integer, server_default="100", nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default="true", nullable=False,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
