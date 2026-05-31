"""SQLAlchemy ORM models for the payslips + allowances surface.

Maps 1:1 to the eight tables created by migration
``0209_payslip_schema``:

  - ``pay_periods`` — per-org pay-period state machine
    (``open``/``finalised``/``paid``). UNIQUE on ``(org_id, start_date)``
    backs ``roll_pay_periods`` idempotency (R1.5).
  - ``allowance_types`` — per-org allowance catalogue with three
    documented units (``shift``/``period``/``km``). Seeded with six
    default rows per existing org (R2.3).
  - ``payslips`` — core payslip row with separate hour bands for
    ordinary / overtime / public_holiday (G2). ``pdf_file_key`` is a
    path-style ``Text`` column matching the ``invoice_attachments`` /
    ``job_card_attachments`` convention (N3 — NOT a UUID FK).
    UNIQUE on ``(staff_id, pay_period_id)`` prevents duplicate drafts
    per staff per period (P4-N28). ``gross_pay`` and ``net_pay`` are
    ``NOT NULL DEFAULT 0`` so a draft row can be inserted before
    ``compute_payslip`` runs (P4-N29).
  - ``payslip_allowances`` — per-line allowance with ``quantity`` and
    ``unit`` columns (G18). The ``unit`` is COPIED from
    ``allowance_types.unit`` at attach time so a retroactive edit to
    the catalogue doesn't change the interpretation of an
    already-finalised payslip line.
  - ``payslip_deductions`` — typed deductions (PAYE, ACC, KiwiSaver
    employee/employer split, student loan, child support, voluntary).
  - ``payslip_reimbursements`` — tax-free, never subtracted from
    gross.
  - ``payslip_leave_lines`` — Holidays Act s130A "leave taken in
    this period" + remaining-balance-after rows.
  - ``staff_recurring_allowances`` (G4) — per-staff recurring
    allowance rules. ``ON DELETE CASCADE`` from ``staff_members`` (the
    rule dies with the staff record); ``ON DELETE RESTRICT`` from
    ``allowance_types``.

Column lists, defaults, FK targets, ON DELETE behaviour, and CHECK
constraints all mirror the migration so introspection
(``Table.columns.keys()``) matches the live schema. The CHECK enums
are duplicated here as table-level constraints so a developer running
`select(Payslip).where(Payslip.status == "bogus")` would still get a
DB-level rejection — the ORM never adds the constraint by itself,
only the migration does.

No ORM relationships are declared (mirrors :mod:`app.modules.leave.models`
and :mod:`app.modules.time_clock.models`) to keep the models lean and
avoid import-time graph cycles. Service layer joins via explicit
``select(...).join(...)`` calls when needed.

**Validates: Requirements R1, R1a, R2, R3, R4, R7, R8a — Staff
Management Phase 4 task B1**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

__all__ = [
    "PayPeriod",
    "AllowanceType",
    "Payslip",
    "PayslipAllowance",
    "PayslipDeduction",
    "PayslipReimbursement",
    "PayslipLeaveLine",
    "StaffRecurringAllowance",
    # Literal type aliases re-exported for symmetry with schemas.py.
    "PayPeriodStatus",
    "PayslipStatus",
    "AllowanceUnit",
    "DeductionKind",
]


# ---------------------------------------------------------------------------
# Literal type aliases — kept here so service + schema layers can import
# the canonical enum lists from a single place. The DB-side CHECK
# constraints in migration 0209 are the source of truth; these mirrors
# exist to surface the enums at the type-checker level.
# ---------------------------------------------------------------------------

PayPeriodStatus = Literal["open", "finalised", "paid"]
PayslipStatus = Literal["draft", "finalised", "voided"]
AllowanceUnit = Literal["shift", "period", "km"]
DeductionKind = Literal[
    "paye",
    "acc_levy",
    "kiwisaver_employee",
    "kiwisaver_employer",
    "student_loan",
    "child_support",
    "voluntary",
]


# ===========================================================================
# 1. PayPeriod — per-org pay-period state machine.
# ===========================================================================


class PayPeriod(Base):
    """Per-org pay-period state machine row.

    Status enum:
      - ``open``      — drafts can be created, edited, finalised.
      - ``finalised`` — drafts locked; period waiting for payment to
                        clear. Reopen flow (R1a / G21) can flip back to
                        ``open`` for corrections.
      - ``paid``      — money is out the door; reopen refused (R1a.2).

    UNIQUE on ``(org_id, start_date)`` makes ``roll_pay_periods``
    idempotent — re-running on an org that already has a period
    starting on that date is a silent no-op.
    """

    __tablename__ = "pay_periods"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "start_date", name="uq_pay_periods_org_start",
        ),
        CheckConstraint(
            "status IN ('open','finalised','paid')",
            name="ck_pay_periods_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    pay_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="open",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    finalised_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )


# ===========================================================================
# 2. AllowanceType — per-org allowance catalogue (R2).
# ===========================================================================


class AllowanceType(Base):
    """Per-org allowance catalogue.

    ``unit`` enum (G18):
      - ``period`` — fixed amount per pay period (quantity always 1).
      - ``shift``  — quantity × default_amount, where quantity is the
                     count of approved shifts in the period.
      - ``km``     — quantity × default_amount, where quantity is km
                     entered by admin on the draft.

    Migration ``0209_payslip_schema`` seeds six defaults per existing
    org (``meal_allowance``, ``tool_allowance``, ``vehicle_allowance``,
    ``on_call_allowance``, ``travel_per_km``, ``uniform_laundering``)
    that admin can rename / deactivate. ``code`` is UNIQUE per org.
    """

    __tablename__ = "allowance_types"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "code", name="uq_allowance_types_org_code",
        ),
        CheckConstraint(
            "unit IN ('shift','period','km')",
            name="ck_allowance_types_unit",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False,
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    taxable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true",
    )
    default_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True,
    )
    unit: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="shift",
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true",
    )
    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
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


# ===========================================================================
# 3. Payslip — core payslip row.
# ===========================================================================


class Payslip(Base):
    """Core payslip row.

    Status enum (R3.1):
      - ``draft``     — totals can be recomputed, lines edited, etc.
      - ``finalised`` — PDF rendered, locked. Only ``emailed_at`` may
                        be updated thereafter (P4-N26 column-allowlist).
      - ``voided``    — admin compensating-flow marked the payslip as
                        voided; new replacement draft must be issued
                        in an open / reopened period.

    Public-holiday band (G2). ``public_holiday_rate`` defaults to
    ``ordinary_rate × Decimal('1.5')`` per Holidays Act s50; admin can
    override on a draft. The ACTUAL rate that paid out is stored on
    the row (not just the multiplier) so the PDF + future audits show
    the exact amount.

    PDF storage (N3). ``pdf_file_key`` is a path-style ``Text`` column
    matching the existing ``invoice_attachments`` /
    ``job_card_attachments`` convention. NOT a UUID FK; NULL until
    finalised.

    Idempotency (P4-N28). UNIQUE on ``(staff_id, pay_period_id)``
    prevents duplicate drafts per staff per period — admin clicking
    "Generate drafts" twice is a no-op for staff who already have a
    draft.

    Draft creation order (P4-N29). ``gross_pay`` and ``net_pay`` are
    ``NOT NULL DEFAULT 0`` so a draft row can be INSERTed before
    ``compute_payslip`` writes the totals back.

    YTD reset (N16). ``gross_ytd`` is recomputed against the NZ tax
    year (1 April → 31 March) on every draft generation — never
    cached forever — so it stays correct across tax-year boundaries.
    """

    __tablename__ = "payslips"
    __table_args__ = (
        UniqueConstraint(
            "staff_id", "pay_period_id",
            name="uq_payslips_staff_period",
        ),
        CheckConstraint(
            "status IN ('draft','finalised','voided')",
            name="ck_payslips_status",
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
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="draft",
    )
    ordinary_hours: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False, server_default="0",
    )
    overtime_hours: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False, server_default="0",
    )
    public_holiday_hours: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False, server_default="0",
    )
    ordinary_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True,
    )
    overtime_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True,
    )
    public_holiday_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True,
    )
    gross_pay: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0",
    )
    gross_ytd: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0",
    )
    net_pay: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0",
    )
    pdf_file_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    emailed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    finalised_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
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
# 4. PayslipAllowance — per-payslip allowance line (G18 quantity + unit).
# ===========================================================================


class PayslipAllowance(Base):
    """Per-payslip allowance line item.

    ``quantity`` + ``unit`` (G18). Unit is COPIED from
    ``allowance_types.unit`` at attach time so a future edit to
    ``allowance_types.unit`` doesn't retroactively change a
    finalised payslip's interpretation. The PDF row renders as
    ``{label}: {quantity} {unit} × ${unit_price} = ${amount}`` for
    shift/km, and just ``{label}: ${amount}`` for period.

    ``allowance_type_id`` is nullable so admin can attach an ad-hoc
    line that doesn't correspond to a catalogue entry (e.g. a
    one-off adjustment).
    """

    __tablename__ = "payslip_allowances"
    __table_args__ = (
        CheckConstraint(
            "unit IN ('shift','period','km')",
            name="ck_payslip_allowances_unit",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    payslip_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("payslips.id", ondelete="CASCADE"),
        nullable=False,
    )
    allowance_type_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("allowance_types.id"),
        nullable=True,
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default="1",
    )
    unit: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="period",
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    taxable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true",
    )


# ===========================================================================
# 5. PayslipDeduction — typed deductions.
# ===========================================================================


class PayslipDeduction(Base):
    """Typed deduction line on a payslip.

    ``kind`` enum (R3.2):
      - ``paye``                — admin enters from IRD lookup.
      - ``acc_levy``            — admin enters.
      - ``kiwisaver_employee``  — auto-computed; subtracts from gross.
      - ``kiwisaver_employer``  — auto-computed; INFORMATIONAL only,
                                  NOT subtracted from gross when
                                  computing net_pay (R6.2).
      - ``student_loan``        — visible only when
                                  ``staff.student_loan=true``.
      - ``child_support``       — manual.
      - ``voluntary``           — manual (KiwiSaver top-up, etc.).
    """

    __tablename__ = "payslip_deductions"
    __table_args__ = (
        CheckConstraint(
            "kind IN ("
            "'paye','acc_levy','kiwisaver_employee','kiwisaver_employer',"
            "'student_loan','child_support','voluntary'"
            ")",
            name="ck_payslip_deductions_kind",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    payslip_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("payslips.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)


# ===========================================================================
# 6. PayslipReimbursement — tax-free, separate from wages.
# ===========================================================================


class PayslipReimbursement(Base):
    """Tax-free reimbursement line (e.g. fuel claim).

    Never subtracted from gross — added to net (R4.3):
    ``net_pay = gross - sum(deductions kind!=kiwisaver_employer) + sum(reimbursements)``.
    """

    __tablename__ = "payslip_reimbursements"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    payslip_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("payslips.id", ondelete="CASCADE"),
        nullable=False,
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)


# ===========================================================================
# 7. PayslipLeaveLine — Holidays Act s130A leave-taken + balance-after.
# ===========================================================================


class PayslipLeaveLine(Base):
    """Per-payslip leave line (Holidays Act s130A).

    Records "leave taken in this period" (hours × rate = amount) plus
    ``balance_after`` which is the staff's remaining accrued-minus-used
    balance for that leave type AFTER this payslip's hours are
    subtracted. Both fields are required on the PDF per s130A.
    """

    __tablename__ = "payslip_leave_lines"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    payslip_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("payslips.id", ondelete="CASCADE"),
        nullable=False,
    )
    leave_type_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("leave_types.id"),
        nullable=False,
    )
    hours: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False,
    )


# ===========================================================================
# 8. StaffRecurringAllowance (G4) — per-staff recurring rules.
# ===========================================================================


class StaffRecurringAllowance(Base):
    """Per-staff recurring allowance rule (G4).

    Auto-attaches a ``payslip_allowances`` row on every draft generated
    for the staff while ``active=true``. ``amount`` and ``quantity``
    are nullable overrides — when NULL, the service falls back to
    ``allowance_types.default_amount`` and the unit-derived quantity
    per the G18 semantics in :func:`_resolve_allowance_quantity`.

    FK behaviour:
      - ``staff_id`` ON DELETE CASCADE — the rule dies with the staff
        record (a deleted staff has nothing to recur).
      - ``allowance_type_id`` ON DELETE RESTRICT — deactivating an
        allowance type while staff still depend on it is a user error
        that should surface as an FK violation rather than a silent
        dangling rule.

    UNIQUE on ``(staff_id, allowance_type_id)`` — a staff has at most
    one rule per allowance type; admin updates the existing row to
    change the override.
    """

    __tablename__ = "staff_recurring_allowances"
    __table_args__ = (
        UniqueConstraint(
            "staff_id", "allowance_type_id",
            name="uq_staff_recurring_allowances_staff_type",
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
        ForeignKey("staff_members.id", ondelete="CASCADE"),
        nullable=False,
    )
    allowance_type_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("allowance_types.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True,
    )
    quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True,
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true",
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
