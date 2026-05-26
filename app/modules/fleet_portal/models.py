"""Fleet Portal SQLAlchemy ORM models.

Mirrors the schema created by Alembic migration ``0191_b2b_fleet_portal``.
Every column, constraint, and index declared here was verified against
the migration DDL — when the two diverge, the migration is the source of
truth and these models must be reconciled.

Naming note: the new portal-side fleet account table is
``portal_fleet_accounts`` (the legacy ``fleet_accounts`` table from
migration 0002 is unrelated). Internal column names stay
``fleet_account_id`` so service code reads naturally.

Tables modelled here (16 new + 2 existing-table extensions):

    Portal account / security parity (6):
        - PortalAccount                 (portal_accounts)
        - PortalAccountMfaMethod        (portal_account_mfa_methods)
        - PortalAccountBackupCode       (portal_account_backup_codes)
        - PortalAccountPasswordHistory  (portal_account_password_history)
        - PortalAuditLog                (portal_audit_log)
        - PortalAccountDevice           (portal_account_devices)

    Fleet domain (10):
        - PortalFleetAccount            (portal_fleet_accounts)
        - FleetDriverAssignment         (fleet_driver_assignments)
        - FleetChecklistTemplate        (fleet_checklist_templates)
        - FleetChecklistTemplateItem    (fleet_checklist_template_items)
        - FleetChecklistSubmission      (fleet_checklist_submissions)
        - FleetChecklistSubmissionItem  (fleet_checklist_submission_items)
        - FleetReminderPreference       (fleet_reminder_preferences)
        - FleetServiceBookingRequest    (fleet_service_booking_requests)
        - FleetQuotationRequest         (fleet_quotation_requests)
        - FleetDriverHours              (fleet_driver_hours)

The two existing-table extensions
(``customer_vehicles.fleet_checklist_template_id`` and
``portal_sessions.portal_account_id``) are added to
``app.modules.vehicles.models`` and ``app.modules.portal.models``
respectively rather than re-declared here.

These models are imported in ``app/main.py`` so SQLAlchemy can resolve
string-based relationship references at startup.

Implements: B2B Fleet Portal task 2.2 — Requirements 1.1, 4.2, 5.2, 8.1,
9.2, 10.3, 11.2, 12.2, 14.1.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# ---------------------------------------------------------------------------
# Portal account & security parity tables
# ---------------------------------------------------------------------------


class PortalAccount(Base):
    """Login credentials for a Fleet Portal user (Fleet Admin or Driver).

    One row per ``(org_id, email)`` pair. ``portal_user_role`` discriminates
    between fleet admins (full access to a fleet) and drivers (vehicle-scoped
    via ``fleet_driver_assignments``). The ``fleet_account_id`` FK references
    ``portal_fleet_accounts.id`` and is nullable only because legacy /
    bootstrap rows may exist briefly without a fleet linkage during invite
    creation; production rows always have it populated.

    Lockout state machine columns (``failed_login_attempts``, ``locked_until``,
    ``is_locked_permanently``) implement Property 6 — see
    ``.kiro/specs/b2b-fleet-portal/design.md`` and
    ``app/modules/fleet_portal/auth.py``.

    Implements Requirements: 3.2, 3.7, 3.10, 4.2, 5.2, 21.7, 21.18.
    """

    __tablename__ = "portal_accounts"

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
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    invite_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invite_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    invite_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reset_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reset_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    is_locked_permanently: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    portal_user_role: Mapped[str] = mapped_column(String(20), nullable=False)
    fleet_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("portal_fleet_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mfa_required_at_next_login: Mapped[bool] = mapped_column(
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
        CheckConstraint(
            "portal_user_role IN ('fleet_admin', 'driver')",
            name="ck_portal_accounts_role",
        ),
        # Unique indexes from the migration are case-insensitive on email
        # (``lower(email)``); we don't redeclare them here — they exist
        # in the database and SQLAlchemy will use them via the underlying
        # constraint at INSERT time.
    )

    # Relationships
    fleet_account: Mapped[PortalFleetAccount | None] = relationship(
        "PortalFleetAccount",
        foreign_keys=[fleet_account_id],
        back_populates="portal_accounts",
    )
    mfa_methods: Mapped[list[PortalAccountMfaMethod]] = relationship(
        back_populates="portal_account",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    backup_codes: Mapped[list[PortalAccountBackupCode]] = relationship(
        back_populates="portal_account",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    password_history: Mapped[list[PortalAccountPasswordHistory]] = relationship(
        back_populates="portal_account",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    devices: Mapped[list[PortalAccountDevice]] = relationship(
        back_populates="portal_account",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PortalAccountMfaMethod(Base):
    """One row per enrolled MFA method for a portal account.

    Mirrors the staff ``UserMfaMethod`` shape but rooted at
    ``portal_account_id``. ``secret_encrypted`` stores the envelope-encrypted
    TOTP secret (see ``app.core.encryption``); ``phone_number`` is populated
    only for SMS methods.

    Implements Requirements: 21.10, 21.11, 21.13, 21.14.
    """

    __tablename__ = "portal_account_mfa_methods"

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
    portal_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("portal_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    phone_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "method IN ('totp', 'sms', 'backup_codes')",
            name="ck_portal_account_mfa_methods_method",
        ),
    )

    portal_account: Mapped[PortalAccount] = relationship(back_populates="mfa_methods")


class PortalAccountBackupCode(Base):
    """One-time backup recovery code (10 generated on first MFA enrolment).

    ``code_hash`` is a bcrypt hash. ``consumed_at IS NULL`` means the code
    is still valid; once a code is used it is set to ``now()`` and never
    re-consumed.

    Implements Requirement: 21.12.
    """

    __tablename__ = "portal_account_backup_codes"

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
    portal_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("portal_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    portal_account: Mapped[PortalAccount] = relationship(back_populates="backup_codes")


class PortalAccountPasswordHistory(Base):
    """Per-account password history for ``password_policy.history_count``.

    Append-only on every password change; FIFO-evicted by the service
    layer when more than ``history_count`` rows exist.

    Implements Requirement: 21.5.
    """

    __tablename__ = "portal_account_password_history"

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
    portal_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("portal_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    portal_account: Mapped[PortalAccount] = relationship(
        back_populates="password_history"
    )


class PortalAuditLog(Base):
    """Authentication and admin event log for portal accounts.

    ``portal_account_id`` is nullable so we can record login attempts
    against unknown emails (anti-enumeration). ``actor_user_id`` is the
    Workshop_Admin staff user for admin-side actions and NULL for
    self-actions by the portal user. ``details`` carries arbitrary
    per-event context (e.g. before/after diff for security policy
    changes).

    Implements Requirements: 21.15, 21.17.
    """

    __tablename__ = "portal_audit_log"

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
    portal_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("portal_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PortalAccountDevice(Base):
    """Mobile device push notification token for a portal account.

    ``last_seen_at`` is touched whenever the mobile app foregrounds and
    re-registers the token, so stale tokens can be aged out.

    Implements Requirement: 24.15.
    """

    __tablename__ = "portal_account_devices"

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
    portal_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("portal_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    device_token: Mapped[str] = mapped_column(String(500), nullable=False)
    platform: Mapped[str] = mapped_column(String(10), nullable=False)
    app_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    os_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "platform IN ('ios', 'android')",
            name="ck_portal_account_devices_platform",
        ),
    )

    portal_account: Mapped[PortalAccount] = relationship(back_populates="devices")


# ---------------------------------------------------------------------------
# Fleet domain tables
# ---------------------------------------------------------------------------


class PortalFleetAccount(Base):
    """A business customer's portal tenant — one row per ``(org, customer)``.

    Renamed from the spec's ``fleet_accounts`` because that name is taken
    by an unrelated migration-0002 table (see Naming Note in the spec).
    Internal column names stay ``fleet_account_id`` so the rest of the
    code reads naturally.

    Implements Requirement: 4.2.
    """

    __tablename__ = "portal_fleet_accounts"

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
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
    )
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
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

    # Relationships
    portal_accounts: Mapped[list[PortalAccount]] = relationship(
        "PortalAccount",
        foreign_keys="[PortalAccount.fleet_account_id]",
        back_populates="fleet_account",
    )
    driver_assignments: Mapped[list[FleetDriverAssignment]] = relationship(
        back_populates="fleet_account",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    checklist_templates: Mapped[list[FleetChecklistTemplate]] = relationship(
        back_populates="fleet_account",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    reminder_preferences: Mapped[list[FleetReminderPreference]] = relationship(
        back_populates="fleet_account",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class FleetDriverAssignment(Base):
    """Links a driver portal account to a customer vehicle they may operate.

    Driver visibility is enforced by joining ``customer_vehicles`` against
    this table: vehicles without a row here are 404 for the driver
    (Property 13).

    Implements Requirements: 5.5, 5.6, 7.1.
    """

    __tablename__ = "fleet_driver_assignments"

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
    fleet_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("portal_fleet_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    portal_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("portal_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    customer_vehicle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customer_vehicles.id", ondelete="CASCADE"),
        nullable=False,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    assigned_by_portal_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("portal_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )

    fleet_account: Mapped[PortalFleetAccount] = relationship(
        back_populates="driver_assignments"
    )
    driver: Mapped[PortalAccount] = relationship(
        "PortalAccount", foreign_keys=[portal_account_id]
    )
    assigned_by: Mapped[PortalAccount] = relationship(
        "PortalAccount", foreign_keys=[assigned_by_portal_account_id]
    )


class FleetChecklistTemplate(Base):
    """A reusable pre-trip checklist template for a fleet account.

    ``is_system_seeded = true`` marks the NZTA default which is read-only
    and only cloneable. The partial unique index
    ``(fleet_account_id) WHERE is_default = true`` enforces at-most-one
    default per fleet (Property 19).

    Implements Requirements: 8.1, 8.3, 8.4, 8.5, 8.7, 8.8.
    """

    __tablename__ = "fleet_checklist_templates"

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
    fleet_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("portal_fleet_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    is_system_seeded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    archived_at: Mapped[datetime | None] = mapped_column(
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

    fleet_account: Mapped[PortalFleetAccount] = relationship(
        back_populates="checklist_templates"
    )
    items: Mapped[list[FleetChecklistTemplateItem]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="FleetChecklistTemplateItem.display_order",
    )


class FleetChecklistTemplateItem(Base):
    """A single check entry within a checklist template.

    ``requires_photo_on_fail = true`` means the item, when failed during
    a submission, must have at least one photo attached before the
    submission can be completed (Property 23).

    Implements Requirement: 8.4.
    """

    __tablename__ = "fleet_checklist_template_items"

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
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fleet_checklist_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    requires_photo_on_fail: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    template: Mapped[FleetChecklistTemplate] = relationship(back_populates="items")


class FleetChecklistSubmission(Base):
    """One run-through of a checklist by a driver on a specific vehicle.

    ``passed_item_count`` / ``failed_item_count`` / ``na_item_count`` are
    finalised at completion time (see ``checklist_service.complete_submission``).
    Status state machine: ``in_progress → completed`` or ``in_progress → cancelled``.

    Implements Requirements: 9.2, 9.6, 9.7.
    """

    __tablename__ = "fleet_checklist_submissions"

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
    fleet_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("portal_fleet_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    customer_vehicle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customer_vehicles.id", ondelete="CASCADE"),
        nullable=False,
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fleet_checklist_templates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    portal_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("portal_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="in_progress"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    passed_item_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    failed_item_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    na_item_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
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
            "status IN ('in_progress', 'completed', 'cancelled')",
            name="ck_fleet_checklist_submissions_status",
        ),
    )

    items: Mapped[list[FleetChecklistSubmissionItem]] = relationship(
        back_populates="submission",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class FleetChecklistSubmissionItem(Base):
    """A single per-item result within a submission.

    ``category`` / ``label`` / ``requires_photo_on_fail`` are snapshotted
    from the template item at submission-start time so historical
    submissions remain readable even if templates are later edited
    (Property 22).

    ``photo_urls`` is a JSON array of storage URLs (e.g. S3 keys).

    Implements Requirements: 9.2, 9.3, 9.4, 9.5.
    """

    __tablename__ = "fleet_checklist_submission_items"

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
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fleet_checklist_submissions.id", ondelete="CASCADE"),
        nullable=False,
    )
    template_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fleet_checklist_template_items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    requires_photo_on_fail: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    result: Mapped[str | None] = mapped_column(String(10), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    photo_urls: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="'[]'::jsonb"
    )
    recorded_at: Mapped[datetime | None] = mapped_column(
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
            "result IS NULL OR result IN ('pass', 'fail', 'na')",
            name="ck_fleet_checklist_submission_items_result",
        ),
    )

    submission: Mapped[FleetChecklistSubmission] = relationship(back_populates="items")


class FleetReminderPreference(Base):
    """Per-vehicle, per-reminder-type subscription configuration.

    UNIQUE on ``(customer_vehicle_id, reminder_type)``: one row per
    vehicle/type pair. ``channels`` and ``recipients`` are JSON arrays;
    ``service_interval_km`` and ``service_interval_months`` are populated
    only for ``service_due_reminder`` rows.

    ``reminder_type`` matches the existing notification reminder type
    names (``app/modules/notifications/schemas.py``) so the reminder
    queue can dedup org-wide and per-fleet enqueues by the same key.

    Implements Requirements: 10.2, 10.3, 10.6, 10.8, 10.9.
    """

    __tablename__ = "fleet_reminder_preferences"

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
    fleet_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("portal_fleet_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    customer_vehicle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customer_vehicles.id", ondelete="CASCADE"),
        nullable=False,
    )
    reminder_type: Mapped[str] = mapped_column(String(40), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    lead_time_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="14"
    )
    channels: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="'[]'::jsonb"
    )
    recipients: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="'[]'::jsonb"
    )
    service_interval_km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    service_interval_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
            "lead_time_days IN (7, 14, 30)",
            name="ck_fleet_reminder_preferences_lead_time",
        ),
        CheckConstraint(
            "reminder_type IN ("
            "'wof_expiry_reminder', "
            "'cof_expiry_reminder', "
            "'service_due_reminder', "
            "'registration_expiry_reminder')",
            name="ck_fleet_reminder_preferences_type",
        ),
    )

    fleet_account: Mapped[PortalFleetAccount] = relationship(
        back_populates="reminder_preferences"
    )


class FleetServiceBookingRequest(Base):
    """Portal-originated service booking request.

    On acceptance by a Workshop_Admin, ``booking_id`` is populated with
    the resulting ``bookings`` row. Status state machine:
    ``pending → (accepted | declined | cancelled) → (completed)``.

    Implements Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7,
    11.8.
    """

    __tablename__ = "fleet_service_booking_requests"

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
    fleet_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("portal_fleet_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    customer_vehicle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customer_vehicles.id", ondelete="CASCADE"),
        nullable=False,
    )
    requested_by_portal_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("portal_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    preferred_date: Mapped[date] = mapped_column(Date, nullable=False)
    preferred_slot: Mapped[str] = mapped_column(String(20), nullable=False)
    service_description: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )
    decline_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    booking_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bookings.id", ondelete="SET NULL"),
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
            "preferred_slot IN ('morning', 'afternoon', 'all_day')",
            name="ck_fleet_service_booking_requests_slot",
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'declined', "
            "'completed', 'cancelled')",
            name="ck_fleet_service_booking_requests_status",
        ),
    )


class FleetQuotationRequest(Base):
    """Portal-originated quotation request.

    On linking by a Workshop_Admin, ``quote_id`` references the resulting
    ``quotes`` row. Status state machine: ``pending → (quoted →
    (accepted | declined) | declined | cancelled) → (expired)``.

    Implements Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7.
    """

    __tablename__ = "fleet_quotation_requests"

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
    fleet_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("portal_fleet_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    customer_vehicle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customer_vehicles.id", ondelete="CASCADE"),
        nullable=False,
    )
    requested_by_portal_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("portal_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    service_description: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )
    quote_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("quotes.id", ondelete="SET NULL"),
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
            "status IN ('pending', 'quoted', 'accepted', "
            "'declined', 'expired', 'cancelled')",
            name="ck_fleet_quotation_requests_status",
        ),
    )


class FleetDriverHours(Base):
    """Driving-hours log entry.

    A driver records ``start_at``/``end_at`` for a vehicle they have an
    assignment for. ``end_at >= start_at`` is enforced both here and in
    the database CHECK constraint.

    Implements Requirement: 7.5.
    """

    __tablename__ = "fleet_driver_hours"

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
    fleet_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("portal_fleet_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    customer_vehicle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customer_vehicles.id", ondelete="CASCADE"),
        nullable=False,
    )
    portal_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("portal_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "end_at >= start_at",
            name="ck_fleet_driver_hours_range",
        ),
    )


__all__ = [
    "PortalAccount",
    "PortalAccountMfaMethod",
    "PortalAccountBackupCode",
    "PortalAccountPasswordHistory",
    "PortalAuditLog",
    "PortalAccountDevice",
    "PortalFleetAccount",
    "FleetDriverAssignment",
    "FleetChecklistTemplate",
    "FleetChecklistTemplateItem",
    "FleetChecklistSubmission",
    "FleetChecklistSubmissionItem",
    "FleetReminderPreference",
    "FleetServiceBookingRequest",
    "FleetQuotationRequest",
    "FleetDriverHours",
]
