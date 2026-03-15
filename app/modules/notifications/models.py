"""SQLAlchemy ORM models for notification-scoped tables.

Tables:
- notification_templates: customisable email/SMS templates per org (RLS enabled)
- notification_log: delivery log for all sent notifications (RLS enabled)
- overdue_reminder_rules: configurable overdue payment reminder rules (RLS enabled)
- notification_preferences: per-org notification type preferences (RLS enabled)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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


class ReminderRule(Base):
    """Configurable automated reminder rule per organisation (Zoho-style)."""

    __tablename__ = "reminder_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    reminder_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="'customer'"
    )
    days_offset: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    timing: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="'after'"
    )
    reference_date: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="'due_date'"
    )
    send_email: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    send_sms: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "reminder_type IN ('payment_due', 'payment_expected', 'invoice_issued', 'quote_expiry', 'service_due', 'custom')",
            name="ck_reminder_rules_type",
        ),
        CheckConstraint(
            "target IN ('customer', 'me', 'both')",
            name="ck_reminder_rules_target",
        ),
        CheckConstraint(
            "timing IN ('before', 'after')",
            name="ck_reminder_rules_timing",
        ),
        CheckConstraint(
            "reference_date IN ('due_date', 'expected_payment_date', 'invoice_date', 'quote_expiry_date', 'service_due_date')",
            name="ck_reminder_rules_reference_date",
        ),
    )

    organisation = relationship("Organisation", backref="reminder_rules")


class ReminderQueue(Base):
    """Queue table for batched, rate-limited reminder delivery.

    Phase 1 (daily scan) inserts rows with status='pending'.
    Phase 2 (worker loop) picks up batches, sends, marks sent/failed.
    """

    __tablename__ = "reminder_queue"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False
    )
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    reminder_type: Mapped[str] = mapped_column(String(50), nullable=False)
    channel: Mapped[str] = mapped_column(String(10), nullable=False)
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="'pending'"
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    max_retries: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="3"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    scheduled_date: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=func.current_date()
    )
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    locked_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "channel IN ('email','sms')",
            name="ck_reminder_queue_channel",
        ),
        CheckConstraint(
            "status IN ('pending','locked','sent','failed','skipped')",
            name="ck_reminder_queue_status",
        ),
    )

    organisation = relationship("Organisation")
