"""SQLAlchemy ORM models for SMS chat tables.

Tables:
- sms_conversations: threaded SMS conversations per org+phone_number (RLS enabled)
- sms_messages: individual SMS message records within conversations (RLS enabled)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SmsConversation(Base):
    """SMS conversation — one per (org, phone_number) pair."""

    __tablename__ = "sms_conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_message_preview: Mapped[str] = mapped_column(String(100), nullable=False)
    unread_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
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

    __table_args__ = (
        UniqueConstraint("org_id", "phone_number", name="uq_sms_conversations_org_phone"),
        Index("ix_sms_conversations_org_last_msg", "org_id", "last_message_at"),
    )

    # Relationships
    organisation = relationship("Organisation", backref="sms_conversations")
    messages: Mapped[list[SmsMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="SmsMessage.created_at",
    )


class SmsMessage(Base):
    """Individual SMS message within a conversation."""

    __tablename__ = "sms_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sms_conversations.id"), nullable=False
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    from_number: Mapped[str] = mapped_column(String(20), nullable=False)
    to_number: Mapped[str] = mapped_column(String(20), nullable=False)
    external_message_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )
    parts_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    cost_nzd: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "direction IN ('inbound', 'outbound')",
            name="ck_sms_messages_direction",
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'queued', 'delivered', 'undelivered', 'failed')",
            name="ck_sms_messages_status",
        ),
        Index("ix_sms_messages_conv_created", "conversation_id", "created_at"),
    )

    # Relationships
    conversation: Mapped[SmsConversation] = relationship(
        back_populates="messages"
    )
    organisation = relationship("Organisation", backref="sms_messages")
