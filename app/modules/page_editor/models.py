"""SQLAlchemy ORM models for the visual page editor module.

Tables:
- editor_pages: one row per managed page (hand-coded or editor-created)
- editor_page_revisions: immutable publish snapshots (revision history)
- editor_media_assets: uploaded images with variant metadata
- editor_page_redirects: slug redirects (301/302)

All tables are global (no org_id, no RLS).

Requirements: 2.1, 5.1, 11.1, 12.1
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
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class EditorPage(Base):
    """One row per managed page (hand-coded or editor-created).

    Maps to the editor_pages table created by migration 0183.
    """

    __tablename__ = "editor_pages"

    page_key: Mapped[str] = mapped_column(
        String(120), primary_key=True,
    )
    page_origin: Mapped[str] = mapped_column(
        String(20), nullable=False,
    )
    page_slug: Mapped[str] = mapped_column(
        String(80), nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(120), nullable=False, server_default="",
    )
    draft_content: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
    )
    published_content: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
    )
    published_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )
    draft_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    draft_updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    published_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    seo: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="'{}'",
    )
    noindex: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "page_origin IN ('hand-coded', 'editor-created')",
            name="ck_editor_pages_origin",
        ),
    )

    # Relationships
    revisions: Mapped[list["EditorPageRevision"]] = relationship(
        "EditorPageRevision", back_populates="page", lazy="selectin",
    )


class EditorPageRevision(Base):
    """Immutable publish snapshot for revision history.

    Maps to the editor_page_revisions table created by migration 0183.
    """

    __tablename__ = "editor_page_revisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    page_key: Mapped[str] = mapped_column(
        String(120),
        ForeignKey("editor_pages.page_key"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False,
    )
    content: Mapped[dict] = mapped_column(
        JSONB, nullable=False,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    published_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    note: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    # Relationships
    page: Mapped["EditorPage"] = relationship(
        "EditorPage", back_populates="revisions",
    )


class EditorMediaAsset(Base):
    """Uploaded image with variant metadata.

    Maps to the editor_media_assets table created by migration 0183.
    """

    __tablename__ = "editor_media_assets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    filename: Mapped[str] = mapped_column(
        String(255), nullable=False,
    )
    original_path: Mapped[str] = mapped_column(
        String(500), nullable=False,
    )
    content_type: Mapped[str] = mapped_column(
        String(100), nullable=False,
    )
    size_bytes: Mapped[int] = mapped_column(
        Integer, nullable=False,
    )
    width: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )
    height: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )
    variants: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="'{}'",
    )
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )


class EditorPageRedirect(Base):
    """Slug redirect (301/302) for renamed pages.

    Maps to the editor_page_redirects table created by migration 0183.
    """

    __tablename__ = "editor_page_redirects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    from_slug: Mapped[str] = mapped_column(
        String(80), nullable=False,
    )
    to_slug_or_url: Mapped[str] = mapped_column(
        String(500), nullable=False,
    )
    status_code: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="301",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "status_code IN (301, 302)",
            name="ck_editor_redirects_status",
        ),
    )
