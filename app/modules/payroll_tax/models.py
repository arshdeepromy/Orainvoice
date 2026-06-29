"""SQLAlchemy ORM models for the payroll tax settings surface.

Maps 1:1 to the two tables created by the seed migration
``0231_payroll_tax_settings``:

  - ``platform_tax_default`` — the single, global baseline tax configuration
    record. A boolean ``is_singleton`` sentinel (always ``true``, ``UNIQUE``)
    structurally guarantees exactly one row exists, so a second insert
    conflicts. The nested tax structures are stored as a single JSONB
    ``config`` document; the scalar ``tax_year_label`` is duplicated as a
    column for cheap display. Not org-scoped → **no RLS**; access is gated
    entirely by ``global_admin`` RBAC on the ``/api/v2/admin/...`` prefix.
  - ``org_tax_settings`` — one row per organisation that has ever set an
    override. The ``overrides`` JSONB holds a **sparse** set of only the
    Tax_Fields the org has explicitly overridden; an absent field inherits the
    platform default. ``UNIQUE(org_id)`` ensures one row per org. RLS-enabled
    with the standard tenant-isolation policy (applied in the migration).

Column lists, defaults, and constraints mirror the migration so introspection
(``Table.columns.keys()``) matches the live schema.

No ORM relationships are declared (mirrors :mod:`app.modules.timesheets.models`)
to keep the models lean and avoid import-time graph cycles.

**Validates: Requirements 1.1, 3.4 — Payroll Tax Settings**
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

__all__ = [
    "PlatformTaxDefault",
    "OrgTaxSettings",
]


# ===========================================================================
# 1. PlatformTaxDefault — single global baseline tax configuration (singleton).
# ===========================================================================


class PlatformTaxDefault(Base):
    """The one global baseline tax configuration record.

    Exactly one row exists for the platform (Req 1.1). The singleton is
    enforced by the ``is_singleton`` boolean: it always holds ``true`` and is
    ``UNIQUE``, so any second insert conflicts on that constraint.

    ``config`` is the full JSONB document holding ``paye_brackets``,
    ``secondary_rates``, ``acc_levy_rate``, ``acc_max_liable_earnings``,
    ``student_loan_rate``, ``student_loan_threshold``, ``ietc``,
    ``default_kiwisaver_employee_rate``, and
    ``default_kiwisaver_employer_rate``.

    ``tax_year_label`` is duplicated as a column for cheap display (Req 1.2).

    Not org-scoped → **no RLS**.
    """

    __tablename__ = "platform_tax_default"
    __table_args__ = (
        UniqueConstraint(
            "is_singleton",
            name="uq_platform_tax_default_singleton",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    is_singleton: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"),
    )
    config: Mapped[dict] = mapped_column(
        JSONB, nullable=False,
    )
    tax_year_label: Mapped[str] = mapped_column(
        Text, nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True,
    )


# ===========================================================================
# 2. OrgTaxSettings — per-org sparse tax overrides (RLS table).
# ===========================================================================


class OrgTaxSettings(Base):
    """Per-organisation tax configuration overrides.

    One row per organisation that has ever set an override. ``UNIQUE(org_id)``
    guarantees one row per org (Req 3.4).

    ``overrides`` is a **sparse** JSONB document: it contains only the
    Tax_Fields the org has explicitly overridden. A field absent from
    ``overrides`` inherits the platform default — it is never treated as zero
    ("defaults win over blanks"). Resetting a field deletes its key; resetting
    all sets ``overrides`` to ``{}``.

    RLS is enabled in the migration with the standard ``tenant_isolation``
    policy keyed on ``current_setting('app.current_org_id', true)::uuid``.
    """

    __tablename__ = "org_tax_settings"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            name="uq_org_tax_settings_org",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False,
    )
    overrides: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True,
    )
