"""SQLAlchemy ORM models for organisation-scoped tables.

Tables:
- branches: org branch locations (RLS enabled)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Branch(Base):
    """Branch location within an organisation."""

    __tablename__ = "branches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    operating_hours: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="'{}'"
    )
    timezone: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="'Pacific/Auckland'"
    )
    is_hq: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    notification_preferences: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="'{}'"
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    organisation = relationship("Organisation", backref="branches")


class DashboardReminderDismissal(Base):
    """Tracks dismissed or 'reminder sent' WOF/service expiry reminders."""

    __tablename__ = "dashboard_reminder_dismissals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    reminder_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # 'wof' or 'service'
    action: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # 'dismissed' or 'reminder_sent'
    expiry_date = mapped_column(
        DateTime(timezone=False), nullable=False
    )
    dismissed_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    dismissed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DashboardReminderConfig(Base):
    """Per-org reminder threshold configuration for WOF/service expiry."""

    __tablename__ = "dashboard_reminder_config"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False, unique=True
    )
    wof_days: Mapped[int] = mapped_column(
        nullable=False, server_default="30"
    )
    service_days: Mapped[int] = mapped_column(
        nullable=False, server_default="30"
    )
    updated_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
