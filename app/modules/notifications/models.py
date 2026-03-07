"""SQLAlchemy ORM models for notification-scoped tables.

Tables:
- notification_templates: customisable email/SMS templates per org (RLS enabled)
- notification_log: delivery log for all sent notifications (RLS enabled)
- overdue_reminder_rules: configurable overdue payment reminder rules (RLS enabled)
- notification_preferences: per-org notification type preferences (RLS enabled)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class NotificationTemplate(Base):
    """Customisable email/SMS template per organisation."""

    __tablename__ = "notification_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    template_type: Mapped[str] = mapped_column(String(50), nullable=False)
    channel: Mapped[str] = mapped_column(String(10), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body_blocks: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="'[]'"
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "channel IN ('email','sms')",
            name="ck_notification_templates_channel",
        ),
        UniqueConstraint(
            "org_id",
            "template_type",
            "channel",
            name="uq_notification_templates_org_type_channel",
        ),
    )

    organisation = relationship("Organisation", backref="notification_templates")


class NotificationLog(Base):
    """Delivery log entry for a sent notification."""

    __tablename__ = "notification_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(10), nullable=False)
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    template_type: Mapped[str] = mapped_column(String(50), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="'queued'"
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "channel IN ('email','sms')",
            name="ck_notification_log_channel",
        ),
        CheckConstraint(
            "status IN ('queued','sent','delivered','bounced','opened','failed')",
            name="ck_notification_log_status",
        ),
    )

    organisation = relationship("Organisation", backref="notification_logs")


class OverdueReminderRule(Base):
    """Configurable overdue payment reminder rule per organisation."""

    __tablename__ = "overdue_reminder_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    days_after_due: Mapped[int] = mapped_column(Integer, nullable=False)
    send_email: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    send_sms: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "days_after_due",
            name="uq_overdue_reminder_rules_org_days",
        ),
    )

    organisation = relationship("Organisation", backref="overdue_reminder_rules")


class NotificationPreference(Base):
    """Per-org notification type preference."""

    __tablename__ = "notification_preferences"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    channel: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="'email'"
    )
    config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="'{}'"
    )

    __table_args__ = (
        CheckConstraint(
            "channel IN ('email','sms','both')",
            name="ck_notification_preferences_channel",
        ),
        UniqueConstraint(
            "org_id",
            "notification_type",
            name="uq_notification_preferences_org_type",
        ),
    )

    organisation = relationship("Organisation", backref="notification_preferences")
