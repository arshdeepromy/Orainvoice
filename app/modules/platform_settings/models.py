"""SQLAlchemy ORM model for the platform_settings table.

The platform_settings table already exists in the DB with columns:
  key (PK, VARCHAR), value (JSONB), version (INT), updated_at (TIMESTAMPTZ)

Migration 0139 adds a value_encrypted (BYTEA) column for storing
envelope-encrypted secrets alongside the existing JSONB value column.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, LargeBinary, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PlatformSetting(Base):
    """Global platform setting — matches the existing platform_settings table."""

    __tablename__ = "platform_settings"
    __table_args__ = {"extend_existing": True}

    key: Mapped[str] = mapped_column(
        String(100), primary_key=True, nullable=False
    )
    value: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, server_default="'{}'::jsonb"
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    value_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
