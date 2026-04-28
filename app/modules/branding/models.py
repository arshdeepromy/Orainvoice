"""SQLAlchemy ORM model for the platform branding module.

Maps to the platform_branding table created by migration 0022 (with
created_at added in 0056).

**Validates: Requirement 1 — Platform Rebranding**
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, LargeBinary, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PlatformBranding(Base):
    """Singleton-style platform branding configuration.

    Only one row should exist.  ``BrandingService`` always fetches the
    first row ordered by ``created_at``.
    """

    __tablename__ = "platform_branding"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    platform_name: Mapped[str] = mapped_column(
        String(100), server_default="OraInvoice", nullable=False,
    )
    logo_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
    )
    dark_logo_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
    )
    favicon_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
    )
    primary_colour: Mapped[str] = mapped_column(
        String(7), server_default="#2563EB", nullable=False,
    )
    secondary_colour: Mapped[str] = mapped_column(
        String(7), server_default="#1E40AF", nullable=False,
    )
    website_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
    )
    signup_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
    )
    support_email: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
    )
    terms_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
    )
    auto_detect_domain: Mapped[bool] = mapped_column(
        Boolean, server_default="true", nullable=False,
    )
    platform_theme: Mapped[str] = mapped_column(
        String(50), server_default="classic", nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    # --- BYTEA file storage (migration 0165) ---

    # Binary file data
    logo_data: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True,
    )
    dark_logo_data: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True,
    )
    favicon_data: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True,
    )

    # MIME types
    logo_content_type: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
    )
    dark_logo_content_type: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
    )
    favicon_content_type: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
    )

    # Original filenames
    logo_filename: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
    )
    dark_logo_filename: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
    )
    favicon_filename: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
    )
