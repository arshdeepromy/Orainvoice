"""SQLAlchemy ORM model for the dead_letter_queue table.

Maps to the ``dead_letter_queue`` table created by migration 0017.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DeadLetterTask(Base):
    """A failed background task awaiting retry or manual resolution."""

    __tablename__ = "dead_letter_queue"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id"),
        nullable=True,
    )
    task_name: Mapped[str] = mapped_column(String(255), nullable=False)
    task_args: Mapped[dict] = mapped_column(
        JSONB, server_default="'{}'::jsonb", nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False
    )
    max_retries: Mapped[int] = mapped_column(
        Integer, server_default="3", nullable=False
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), server_default="'pending'", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
