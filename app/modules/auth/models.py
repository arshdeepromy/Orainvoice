"""SQLAlchemy ORM models for authentication tables.

Tables:
- users: org users and global admins (RLS enabled)
- sessions: user sessions with refresh token rotation (RLS enabled)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class User(Base):
    """Platform user — org-scoped (or global admin with org_id=NULL)."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id"),
        nullable=True,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    is_email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    mfa_methods: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="'[]'"
    )
    backup_codes_hash: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    passkey_credentials: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="'[]'"
    )
    google_oauth_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    branch_ids: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="'[]'"
    )
    assigned_location_ids: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="'[]'"
    )
    franchise_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    failed_login_count: Mapped[int] = mapped_column(
        nullable=False, server_default="0", default=0,
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
        CheckConstraint(
            "role IN ('global_admin','franchise_admin','org_admin','location_manager','salesperson','staff_member')",
            name="ck_users_role",
        ),
        Index("idx_users_org", "org_id"),
        Index("idx_users_email", "email"),
    )

    # Relationships
    organisation = relationship("Organisation", back_populates="users")
    sessions: Mapped[list[Session]] = relationship(back_populates="user")


class Session(Base):
    """User session with refresh token rotation support."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=True
    )
    refresh_token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    device_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    browser: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ip_address = mapped_column(INET, nullable=True)
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    is_revoked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    user: Mapped[User] = relationship(back_populates="sessions")
