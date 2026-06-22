"""Organisation Employee Portal SQLAlchemy ORM models.

Mirrors the schema created by Alembic migration
``0224_employee_portal``. Every column, constraint, and index declared
here was verified against the migration DDL — when the two diverge, the
migration is the source of truth and these models must be reconciled.

These models mirror the security-relevant column shapes of the B2B Fleet
Portal's ``PortalAccount`` / ``PortalAuditLog`` (see
``app/modules/fleet_portal/models.py``) but are rooted at
``staff_members`` instead of customer fleets, and store invite/reset/session
tokens as **SHA-256 hashes** (``varchar(64)``) rather than raw values.

Tables modelled here (3 new):

    - EmployeePortalUser      (employee_portal_users)
    - EmployeePortalSession   (employee_portal_sessions)
    - EmployeePortalAuditLog  (employee_portal_audit_log)

The unique / lookup indexes (``uq_emp_portal_users_org_email_active``,
``idx_emp_portal_users_staff``, ``uq_emp_portal_users_invite_hash``,
``uq_emp_portal_users_reset_hash``, ``uq_emp_portal_sessions_token_hash``)
are created CONCURRENTLY by the migration and are **not** re-declared here —
they exist in the database and SQLAlchemy uses them via the underlying
constraints at INSERT time. This mirrors the fleet portal's convention of
not redeclaring migration-owned partial/functional indexes in the ORM.

These models are imported in ``app/main.py`` so SQLAlchemy can resolve
string-based relationship references and Alembic/metadata can see the tables.

Implements: Organisation Employee Portal task 2.1 — Requirements 5.1, 5.2,
5.3, 6.1, 6.2, 6.9, 6.10, 16.5, 16.6.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class EmployeePortalUser(Base):
    """Org-scoped login credential for a staff member's Employee Portal access.

    Separate identity store from the global ``users`` table (R5.1): a portal
    user can authenticate ONLY at ``/e/api/auth/*``, never at
    ``/api/v*/auth/*``. Linked to ``staff_members`` via ``staff_id``.

    Lockout state machine columns (``failed_login_attempts``, ``locked_until``)
    mirror ``PortalAccount`` / the fleet portal's ``auth.py``. Invite and reset
    tokens are stored as SHA-256 hashes (never raw) so a DB-read attacker
    cannot replay a live link — the raw token lives only in the emailed URL.

    Per-org case-insensitive email uniqueness over active rows is enforced by
    the partial unique index ``uq_emp_portal_users_org_email_active`` from the
    migration (allowing re-issue after revoke/deactivation, and the same email
    across different orgs).

    Validates: Requirements 5.1, 5.2, 5.3, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10,
    5.11, 6.5, 14.*.
    """

    __tablename__ = "employee_portal_users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
    )
    staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("staff_members.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Stored lowercased + trimmed; the partial unique index keys on lower(email).
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    # Lockout state machine (mirrors PortalAccount / fleet auth.py).
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Invite (set-password) — single-use, 7-day validity (R5.5, R5.8, R5.9).
    invite_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    invite_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    invite_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Password reset — single-use, 60-min validity (R14.3, R14.5).
    reset_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reset_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
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
    sessions: Mapped[list[EmployeePortalSession]] = relationship(
        back_populates="portal_user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class EmployeePortalSession(Base):
    """HttpOnly-cookie session for an employee portal user.

    A dedicated session table (not a reuse of the customer-portal
    ``PortalSession``). Keeping employee sessions in their own table makes
    cross-portal cookie rejection structural: a token minted for another
    portal simply does not exist here, so it can never validate (R6.2,
    R16.8).

    ``session_token_hash`` is ``sha256(raw_token)``; the raw 32-byte token
    lives only in the HttpOnly cookie. Its uniqueness is enforced by the
    migration's ``uq_emp_portal_sessions_token_hash`` index. Absolute lifetime
    is 12h (``expires_at = created_at + 12h``) with a 30-minute idle window on
    ``last_seen_at`` (R6.10).

    Validates: Requirements 6.1, 6.2, 6.9, 6.10, 4.6, 5.10, 5.11, 14.8, 16.8.
    """

    __tablename__ = "employee_portal_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
    )
    portal_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employee_portal_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    portal_user: Mapped[EmployeePortalUser] = relationship(back_populates="sessions")


class EmployeePortalAuditLog(Base):
    """Auth/security event log for the employee portal.

    Mirrors ``PortalAuditLog``: org-scoped, with a **nullable**
    ``portal_user_id`` (``ON DELETE SET NULL``) so failed logins against
    unknown emails are recorded without revealing existence (R16.6).
    ``actor_user_id`` references the global ``users`` table — populated for
    org_admin-side actions and NULL for self-actions by the portal user.

    Validates: Requirements 16.5, 16.6, 4.7.
    """

    __tablename__ = "employee_portal_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
    )
    portal_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employee_portal_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = [
    "EmployeePortalUser",
    "EmployeePortalSession",
    "EmployeePortalAuditLog",
]
