"""SQLAlchemy ORM models for authentication tables.

Tables:
- users: org users and global admins (RLS enabled)
- sessions: user sessions with refresh token rotation (RLS enabled)
- user_mfa_methods: normalised MFA method enrolments per user
- user_passkey_credentials: WebAuthn/FIDO2 passkey credentials per user
- user_backup_codes: single-use backup recovery codes per user
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
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
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    is_email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    # NOTE: mfa_methods, backup_codes_hash, and passkey_credentials JSONB
    # columns were removed in migration 0098 and replaced by normalised
    # tables: user_mfa_methods, user_backup_codes, user_passkey_credentials.
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
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    custom_role_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("custom_roles.id", ondelete="SET NULL"),
        nullable=True,
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
    mfa_methods: Mapped[list[UserMfaMethod]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="raise",
    )
    passkey_credentials: Mapped[list[UserPasskeyCredential]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="raise",
    )
    backup_codes: Mapped[list[UserBackupCode]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="raise",
    )
    custom_role: Mapped[CustomRole | None] = relationship(
        back_populates="users", lazy="raise",
        foreign_keys="[User.custom_role_id]",
    )


class CustomRole(Base):
    """Org-defined role with a custom set of permissions."""

    __tablename__ = "custom_roles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    permissions: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="'[]'"
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
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
        UniqueConstraint("org_id", "slug", name="uq_custom_roles_org_slug"),
        Index("idx_custom_roles_org", "org_id"),
    )

    # Relationships
    users: Mapped[list[User]] = relationship(
        back_populates="custom_role", lazy="raise",
        foreign_keys="[User.custom_role_id]",
    )


class PasswordHistory(Base):
    """Stores password hashes for history-based reuse prevention."""

    __tablename__ = "password_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_password_history_user", "user_id"),
        Index("idx_password_history_created", "user_id", "created_at"),
    )


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

    __table_args__ = (
        Index("idx_sessions_refresh_token_hash", "refresh_token_hash"),
        Index("idx_sessions_family_id", "family_id"),
        Index("idx_sessions_user_id", "user_id"),
        Index("idx_sessions_expires_at", "expires_at"),
    )


class UserMfaMethod(Base):
    """Normalised MFA method enrolment — one row per (user, method) pair."""

    __tablename__ = "user_mfa_methods"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False,
    )
    phone_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    secret_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True,
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False,
    )

    __table_args__ = (
        UniqueConstraint("user_id", "method", name="uq_user_mfa_method"),
        CheckConstraint(
            "method IN ('totp', 'sms', 'email', 'passkey')",
            name="chk_method",
        ),
        Index("idx_user_mfa_methods_user", "user_id"),
    )

    # Relationships
    user: Mapped[User] = relationship(back_populates="mfa_methods")


class UserPasskeyCredential(Base):
    """WebAuthn/FIDO2 passkey credential stored per user."""

    __tablename__ = "user_passkey_credentials"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    credential_id: Mapped[str] = mapped_column(
        String(512), nullable=False, unique=True,
    )
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    public_key_alg: Mapped[int] = mapped_column(Integer, nullable=False)
    sign_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0", default=0,
    )
    device_name: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="'My Passkey'", default="My Passkey",
    )
    flagged: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    __table_args__ = (
        Index("idx_passkey_creds_user", "user_id"),
        Index("idx_passkey_creds_credential_id", "credential_id"),
    )

    # Relationships
    user: Mapped[User] = relationship(back_populates="passkey_credentials")


class UserBackupCode(Base):
    """Single-use backup recovery code (bcrypt-hashed)."""

    __tablename__ = "user_backup_codes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    __table_args__ = (
        Index("idx_backup_codes_user", "user_id"),
    )

    # Relationships
    user: Mapped[User] = relationship(back_populates="backup_codes")
