"""SQLAlchemy ORM models for the staff timesheets surface.

Maps 1:1 to the two tables created by migration
``0195_staff_timesheets_schema``:

  - ``timesheets`` — per-staff, per-pay-period aggregated timesheet
    row with rostered / actual / adjusted / classified minute columns,
    exception flags (JSONB), and a 4-state status machine
    (``open`` / ``pending_approval`` / ``approved`` / ``locked``).
    UNIQUE on ``(staff_id, pay_period_id)`` ensures one row per person
    per period. Branch-scoped when ``branch_id`` is non-NULL.
  - ``timesheet_settings`` — per-org (and optionally per-branch
    override) configuration for clock rounding, grace windows, match
    policy, auto-approve thresholds, and approval-before-lock toggle.
    UNIQUE on ``(org_id, branch_id)`` ensures at most one settings row
    per org+branch combination.

Column lists, defaults, FK targets, and CHECK constraints mirror the
migration so introspection (``Table.columns.keys()``) matches the live
schema.

No ORM relationships are declared (mirrors
:mod:`app.modules.time_clock.models` and :mod:`app.modules.leave.models`)
to keep the models lean and avoid import-time graph cycles with the
payslips, scheduling, staff, and auth modules.

**Validates: Requirements 1.1, 4.2 — Staff Timesheets**
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
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

__all__ = [
    "Timesheet",
    "TimesheetSettings",
]


# ===========================================================================
# 1. Timesheet — per-staff, per-pay-period aggregation row.
# ===========================================================================


class Timesheet(Base):
    """Per-staff, per-pay-period timesheet aggregation row.

    Status enum:
      - ``open``             — entries are still being collected/matched.
      - ``pending_approval`` — submitted for manager review.
      - ``approved``         — manager has signed off; ready for lock.
      - ``locked``           — locked into a pay run; no further edits.

    UNIQUE on ``(staff_id, pay_period_id)`` prevents duplicate timesheets
    per staff per period — lazy creation via ``get_or_create_timesheet``
    is idempotent.

    ``exception_flags`` JSONB array holds dicts like
    ``{"type": "missed_shift", "detail": "..."}`` populated by the
    aggregation engine when anomalies are detected.
    """

    __tablename__ = "timesheets"
    __table_args__ = (
        UniqueConstraint(
            "staff_id", "pay_period_id",
            name="uq_timesheets_staff_period",
        ),
        CheckConstraint(
            "status IN ('open','pending_approval','approved','locked')",
            name="ck_timesheets_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False,
    )
    staff_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("staff_members.id"),
        nullable=False,
    )
    pay_period_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("pay_periods.id"),
        nullable=False,
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("branches.id"),
        nullable=True,
    )
    rostered_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    actual_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    adjusted_minutes: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )
    ordinary_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    overtime_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    public_holiday_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    exception_flags: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="open",
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    locked_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    payslip_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("payslips.id"),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ===========================================================================
# 2. TimesheetSettings — per-org (+ optional branch override) config.
# ===========================================================================


class TimesheetSettings(Base):
    """Per-org (and optionally per-branch) timesheet settings.

    UNIQUE on ``(org_id, branch_id)`` means:
      - One row with ``branch_id = NULL`` → org-wide defaults.
      - One row per branch → branch-level override.

    ``clock_rounding_minutes`` CHECK constrains to sensible intervals
    (1, 5, 10, 15, 30). ``clock_rounding_direction`` is one of
    ``nearest``, ``up``, ``down``. ``match_policy`` controls how
    actual minutes are reconciled with rostered shifts.
    """

    __tablename__ = "timesheet_settings"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "branch_id",
            name="uq_timesheet_settings_org_branch",
        ),
        CheckConstraint(
            "clock_rounding_minutes IN (1,5,10,15,30)",
            name="ck_timesheet_settings_rounding_minutes",
        ),
        CheckConstraint(
            "clock_rounding_direction IN ('nearest','up','down')",
            name="ck_timesheet_settings_rounding_direction",
        ),
        CheckConstraint(
            "match_policy IN ('pay_actual','round_to_roster','actual_rounded')",
            name="ck_timesheet_settings_match_policy",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False,
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("branches.id"),
        nullable=True,
    )
    clock_rounding_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1",
    )
    clock_rounding_direction: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="nearest",
    )
    early_grace_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    late_grace_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    match_policy: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="pay_actual",
    )
    auto_approve_threshold_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    require_approval_before_lock: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true",
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
