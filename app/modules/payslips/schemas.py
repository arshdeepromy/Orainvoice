"""Pydantic v2 schemas for the payslips + allowances + termination surface.

Maps the eight ORM models in :mod:`app.modules.payslips.models` to
inbound ``Create`` / ``Update`` / action payloads and outbound
``Response`` / ``ListResponse`` envelopes. List shapes follow the
project rule ``{ items, total }`` (see ``project-overview.md`` — "All
API responses wrap arrays in objects").

**Validates: Requirements R1, R1a, R2, R3, R4, R7, R8a, R10 — Staff
Management Phase 4 task B2**

Key design notes:
  - Pydantic v2 syntax throughout (``Literal`` types, ``Field(...)``,
    ``model_config = {"from_attributes": True}``).
  - PDF identifier is :attr:`PayslipResponse.pdf_file_key` (path-style
    text — N3) — admin-facing. The frontend builds the public download
    URL as ``/api/v2/payslips/{id}/pdf`` rather than exposing the path.
  - Self-service (G9) responses (:class:`MyPayslipResponse`,
    :class:`MyPayslipDetailResponse`) deliberately EXCLUDE
    ``pdf_file_key`` and any other internal-only fields. Staff get a
    typed download URL only.
  - Status enums mirror the DB-level CHECK constraints declared in
    migration 0209 (the canonical list lives in
    :mod:`app.modules.payslips.models` as ``Literal`` aliases — they
    are re-imported here for symmetry).
  - Detail responses for payslips include the four nested line lists
    (allowances, deductions, reimbursements, leave_lines) per design §6.2.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enum-style Literal aliases — kept here so Create/Update/Response stay
# aligned with the DB-side CHECK constraints in migration 0209 + the
# matching aliases on :mod:`app.modules.payslips.models`.
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
PayPeriodCadence = Literal["weekly", "fortnightly", "monthly"]


# ===========================================================================
# Pay-period schemas (R1, R1a)
# ===========================================================================


class PayPeriodCreate(BaseModel):
    """Inbound payload for ``POST /api/v2/pay-periods``.

    Admin can manually create a period (e.g. for an off-cycle one-off
    pay run); the daily ``roll_pay_periods`` task creates the standard
    cadence-driven rows. Status defaults to ``'open'`` server-side; a
    period created in any other state is a 422 validation error so the
    schema doesn't expose ``status`` here.
    """

    start_date: date
    end_date: date
    pay_date: date


class PayPeriodUpdate(BaseModel):
    """Inbound payload for ``PATCH /api/v2/pay-periods/:id``.

    Limited surface: admin can move ``pay_date`` (e.g. when the bank
    rejects a Sunday transfer) and flip ``status`` between the three
    enum values. ``start_date`` / ``end_date`` are immutable post-
    creation — changing them would invalidate every payslip already in
    the period.
    """

    pay_date: date | None = None
    status: PayPeriodStatus | None = None


class PayPeriodResponse(BaseModel):
    """Outbound pay-period record.

    The four ``*_at`` timestamps are populated as the period
    progresses through its lifecycle:
      - ``created_at`` — set on INSERT.
      - ``finalised_at`` — set when admin clicks "Finalise all"
                          (or the bulk endpoint flips status). NULL
                          again after a reopen (G21).
      - ``paid_at`` — set when admin marks the period paid (PATCH
                     status to ``'paid'``).
    """

    id: UUID
    org_id: UUID
    start_date: date
    end_date: date
    pay_date: date
    status: str
    created_at: datetime
    finalised_at: datetime | None = None
    paid_at: datetime | None = None

    model_config = {"from_attributes": True}


class PayPeriodListResponse(BaseModel):
    """Wrapper per project rule: arrays go in ``{ items, total }``."""

    items: list[PayPeriodResponse]
    total: int


class PayPeriodReopenRequest(BaseModel):
    """Body for ``POST /api/v2/pay-periods/:id/reopen`` (G21).

    The caller MUST supply a reason — it's persisted on the audit row
    ``pay_period.reopened`` so future reviewers can see why the period
    was unlocked. The service refuses 409 ``period_already_paid`` when
    status is ``'paid'``, and 422 when the period is already
    ``'open'`` (per R1a.2 / R1a.3).
    """

    reason: str = Field(..., min_length=1, max_length=500)


# ===========================================================================
# Allowance type schemas (R2)
# ===========================================================================


class AllowanceTypeCreate(BaseModel):
    """Inbound payload for ``POST /api/v2/allowance-types``.

    ``code`` is UNIQUE per org and used as a stable identifier for
    auto-attached allowances (e.g. ``casual_8pct_holiday``); admin
    can rename ``name`` freely without breaking the recurring/
    auto-attach logic. ``unit`` defaults to ``'shift'`` to match the
    migration default.
    """

    code: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=200)
    taxable: bool = True
    default_amount: Decimal | None = None
    unit: AllowanceUnit = "shift"
    active: bool = True
    display_order: int = 0


class AllowanceTypeUpdate(BaseModel):
    """Inbound payload for ``PATCH /api/v2/allowance-types/:id``.

    All fields optional — admin can flip ``active=false`` to
    deactivate without touching the rest. ``code`` is intentionally
    excluded (see :class:`AllowanceTypeCreate` docstring) — once a
    code is in use as the auto-attach handle for casual 8% / etc.,
    renaming it would silently break recurring rules.
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    taxable: bool | None = None
    default_amount: Decimal | None = None
    unit: AllowanceUnit | None = None
    active: bool | None = None
    display_order: int | None = None


class AllowanceTypeResponse(BaseModel):
    """Outbound allowance-type record."""

    id: UUID
    org_id: UUID
    code: str
    name: str
    taxable: bool
    default_amount: Decimal | None = None
    unit: str
    active: bool
    display_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AllowanceTypeListResponse(BaseModel):
    items: list[AllowanceTypeResponse]
    total: int


# ===========================================================================
# Payslip line schemas (R3.2 — allowances / deductions / reimbursements / leave)
# ===========================================================================


class PayslipAllowanceCreate(BaseModel):
    """Inbound payload for adding a manual allowance line to a draft.

    ``allowance_type_id`` is optional — admin can attach a one-off
    ad-hoc line without a catalogue entry. When provided, the service
    copies ``unit`` from the catalogue at attach time (G18) so a
    later edit to the catalogue's unit doesn't change the
    interpretation of an already-attached line.

    ``quantity`` defaults to ``Decimal('1')`` and ``unit`` defaults
    to ``'period'`` to match the column defaults.
    """

    allowance_type_id: UUID | None = None
    label: str = Field(..., min_length=1, max_length=200)
    quantity: Decimal = Field(default=Decimal("1"))
    unit: AllowanceUnit = "period"
    amount: Decimal
    taxable: bool = True


class PayslipAllowanceResponse(BaseModel):
    """Outbound allowance-line record on a payslip."""

    id: UUID
    payslip_id: UUID
    allowance_type_id: UUID | None = None
    label: str
    quantity: Decimal
    unit: str
    amount: Decimal
    taxable: bool

    model_config = {"from_attributes": True}


class PayslipDeductionCreate(BaseModel):
    """Inbound payload for adding a manual deduction line to a draft.

    PAYE + ACC are entered manually by admin (we don't compute
    statutory tax). KiwiSaver employee/employer + student_loan rows
    are auto-computed by the service on draft generation but admin
    can override via PATCH.
    """

    kind: DeductionKind
    label: str = Field(..., min_length=1, max_length=200)
    amount: Decimal


class PayslipDeductionResponse(BaseModel):
    """Outbound deduction-line record on a payslip."""

    id: UUID
    payslip_id: UUID
    kind: str
    label: str
    amount: Decimal

    model_config = {"from_attributes": True}


class PayslipReimbursementCreate(BaseModel):
    """Inbound payload for adding a manual reimbursement line."""

    label: str = Field(..., min_length=1, max_length=200)
    amount: Decimal


class PayslipReimbursementResponse(BaseModel):
    """Outbound reimbursement-line record on a payslip."""

    id: UUID
    payslip_id: UUID
    label: str
    amount: Decimal

    model_config = {"from_attributes": True}


class PayslipLeaveLineResponse(BaseModel):
    """Outbound leave-line record on a payslip (Holidays Act s130A).

    ``balance_after`` is the staff's remaining accrued-minus-used
    balance for that leave type AFTER this payslip's hours are
    subtracted — required on the PDF per s130A.

    ``leave_type_code`` and ``leave_type_name`` are JOIN-resolved
    by the service so the PDF/template can render the line without
    a second round-trip.
    """

    id: UUID
    payslip_id: UUID
    leave_type_id: UUID
    leave_type_code: str | None = None
    leave_type_name: str | None = None
    hours: Decimal
    rate: Decimal
    amount: Decimal
    balance_after: Decimal

    model_config = {"from_attributes": True}


# ===========================================================================
# Payslip schemas (R3, R4)
# ===========================================================================


class PayslipCreate(BaseModel):
    """Inbound payload for the rare manual-create path.

    Most payslips are created by ``POST /pay-periods/:id/payslips``
    which dispatches one draft per active staff. The single-draft
    create endpoint is provided for off-cycle adjustments.
    ``compute_payslip`` runs server-side after INSERT to populate
    every numeric field.
    """

    staff_id: UUID
    pay_period_id: UUID
    notes: str | None = Field(default=None, max_length=2000)


class PayslipUpdate(BaseModel):
    """Inbound payload for ``PATCH /api/v2/payslips/:id``.

    Only valid on drafts (status='draft'). Finalised payslips refuse
    UPDATEs at the service layer with HTTP 409 — the only column
    allowed to change post-finalise is ``emailed_at``, mutated via
    the email endpoint (P4-N26 column allowlist).

    Hours / rates are admin-overridable — the calculator recomputes
    gross/net on every save. Override fields are intentionally
    nullable so an explicit ``null`` resets back to the auto-derived
    value on the next compute.
    """

    ordinary_hours: Decimal | None = None
    overtime_hours: Decimal | None = None
    public_holiday_hours: Decimal | None = None
    ordinary_rate: Decimal | None = None
    overtime_rate: Decimal | None = None
    public_holiday_rate: Decimal | None = None
    notes: str | None = Field(default=None, max_length=2000)


class PayslipResponse(BaseModel):
    """Outbound payslip summary record (admin view).

    Used in list endpoints + the per-staff history tab. The detail
    drawer/page hydrates the four nested line lists via
    :class:`PayslipDetailResponse` instead.

    Service-resolved JOIN fields (``staff_name``, ``pay_period``) are
    declared optional because the JOIN may legitimately return
    ``None`` (e.g. an orphaned row). Front-end callers MUST be
    defensive (`?? null` / `?.`).
    """

    id: UUID
    org_id: UUID
    staff_id: UUID
    staff_name: str | None = None
    pay_period_id: UUID
    pay_period: PayPeriodResponse | None = None
    status: str
    ordinary_hours: Decimal
    overtime_hours: Decimal
    public_holiday_hours: Decimal
    ordinary_rate: Decimal | None = None
    overtime_rate: Decimal | None = None
    public_holiday_rate: Decimal | None = None
    gross_pay: Decimal
    gross_ytd: Decimal
    net_pay: Decimal
    pdf_file_key: str | None = None
    emailed_at: datetime | None = None
    finalised_at: datetime | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PayslipDetailResponse(PayslipResponse):
    """Outbound payslip detail with nested line lists (R3.2).

    Returned by ``GET /api/v2/payslips/:id`` for the drawer / detail
    page. The four nested lists default to empty so the schema
    serialises cleanly even when none of the line tables have rows
    (e.g. a freshly-INSERTed draft pre-compute).
    """

    allowances: list[PayslipAllowanceResponse] = Field(default_factory=list)
    deductions: list[PayslipDeductionResponse] = Field(default_factory=list)
    reimbursements: list[PayslipReimbursementResponse] = Field(
        default_factory=list,
    )
    leave_lines: list[PayslipLeaveLineResponse] = Field(default_factory=list)


class PayslipListResponse(BaseModel):
    """Wrapper per project rule: arrays go in ``{ items, total }``."""

    items: list[PayslipResponse]
    total: int


# ===========================================================================
# Self-service payslip schemas (G9 — R8a)
# ===========================================================================


class MyPayslipResponse(BaseModel):
    """Outbound self-service payslip record (own data — staff view).

    Deliberately EXCLUDES internal fields like ``pdf_file_key``,
    ``org_id``, and editor metadata. The download URL is built
    client-side as ``/api/v2/staff/me/payslips/{id}/pdf`` so the
    server never exposes the path-traversal-sensitive file_key string
    on this surface.

    Per R8a, only finalised payslips are returned — drafts and
    voided are NOT visible to the staff (only their admin sees those).
    """

    id: UUID
    pay_period_id: UUID
    pay_period: PayPeriodResponse | None = None
    status: str
    ordinary_hours: Decimal
    overtime_hours: Decimal
    public_holiday_hours: Decimal
    ordinary_rate: Decimal | None = None
    overtime_rate: Decimal | None = None
    public_holiday_rate: Decimal | None = None
    gross_pay: Decimal
    gross_ytd: Decimal
    net_pay: Decimal
    finalised_at: datetime | None = None
    emailed_at: datetime | None = None
    pdf_url: str | None = None  # built server-side as /staff/me/payslips/:id/pdf

    model_config = {"from_attributes": True}


class MyPayslipsListResponse(BaseModel):
    """Wrapper for ``GET /api/v2/staff/me/payslips``.

    Pagination shape matches the rest of the project (``{ items,
    total }``) per project-overview rule.
    """

    items: list[MyPayslipResponse]
    total: int


class MyPayslipDetailResponse(MyPayslipResponse):
    """Outbound self-service payslip detail with nested line lists.

    Same redactions as :class:`MyPayslipResponse` — the four nested
    line lists are exposed (the staff is the data subject, so they
    have a right to see their own breakdown) but the internal
    ``pdf_file_key`` is not. Staff use the ``pdf_url`` field to
    download the rendered PDF.
    """

    allowances: list[PayslipAllowanceResponse] = Field(default_factory=list)
    deductions: list[PayslipDeductionResponse] = Field(default_factory=list)
    reimbursements: list[PayslipReimbursementResponse] = Field(
        default_factory=list,
    )
    leave_lines: list[PayslipLeaveLineResponse] = Field(default_factory=list)


# ===========================================================================
# Staff recurring allowance schemas (G4 — R3.5)
# ===========================================================================


class StaffRecurringAllowanceCreate(BaseModel):
    """Inbound payload for ``POST /api/v2/staff/:id/payslips/recurring-allowances``.

    Both ``amount`` and ``quantity`` are nullable overrides — when
    NULL, the service falls back to ``allowance_types.default_amount``
    and the unit-derived quantity per the G18 semantics.

    UNIQUE on ``(staff_id, allowance_type_id)`` is enforced at the DB
    level — a duplicate POST returns a 409 conflict with the existing
    row's id so admin can PATCH instead.
    """

    allowance_type_id: UUID
    amount: Decimal | None = None
    quantity: Decimal | None = None
    active: bool = True
    notes: str | None = Field(default=None, max_length=500)


class StaffRecurringAllowanceUpdate(BaseModel):
    """Inbound payload for PATCH on a recurring allowance rule.

    All fields optional. ``allowance_type_id`` is intentionally
    excluded — to "switch" the allowance type the admin should
    delete the rule and create a new one.
    """

    amount: Decimal | None = None
    quantity: Decimal | None = None
    active: bool | None = None
    notes: str | None = Field(default=None, max_length=500)


class StaffRecurringAllowanceResponse(BaseModel):
    """Outbound recurring-allowance record.

    The nested ``allowance_type`` is JOIN-resolved by the service so
    the Recurring Allowances panel on the Staff Detail Overview tab
    can render the unit / default amount without a second round-trip.
    """

    id: UUID
    org_id: UUID
    staff_id: UUID
    allowance_type_id: UUID
    allowance_type: AllowanceTypeResponse | None = None
    amount: Decimal | None = None
    quantity: Decimal | None = None
    active: bool
    notes: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RecurringAllowanceListResponse(BaseModel):
    """Wrapper per project rule: arrays go in ``{ items, total }``."""

    items: list[StaffRecurringAllowanceResponse]
    total: int


# ===========================================================================
# Termination schemas (R10)
# ===========================================================================


class TerminationFinalPayOptions(BaseModel):
    """Optional per-staff toggles supplied with a termination request.

    All fields default to ``True`` — admin opts OUT of a payout
    component by setting it to ``False`` (e.g. a contractor with no
    accrued annual leave). The service ignores toggles for components
    that don't apply (e.g. ``pay_casual_8pct_remainder=False`` is a
    no-op for permanent staff).
    """

    pay_annual_leave: bool = True
    pay_alt_days: bool = True
    pay_casual_8pct_remainder: bool = True


class TerminationRequest(BaseModel):
    """Body for ``POST /api/v2/staff/:id/terminate`` (R10.1).

    ``end_date`` is the last day of employment (Holidays Act s27
    "termination" date). ``reason`` is mandatory free-text persisted
    on both the staff_member row and the audit log. ``final_pay_options``
    is optional — when omitted the service computes every applicable
    component.
    """

    end_date: date
    reason: str = Field(..., min_length=1, max_length=2000)
    final_pay_options: TerminationFinalPayOptions = Field(
        default_factory=TerminationFinalPayOptions,
    )


# ===========================================================================
# Allowance auto-quantity helper response (G18) — exposed for the
# draft-edit UI so the admin can see why a quantity was derived.
# ===========================================================================


class AllowanceQuantityResolution(BaseModel):
    """Returned alongside an auto-attached allowance line.

    Surfaces the source of the quantity to the admin UI so a derived
    value (e.g. "5 shifts because 5 schedule_entries were approved
    this period") can be rendered as a tooltip on the draft editor.
    Not persisted — computed on demand.
    """

    quantity: Decimal
    unit: AllowanceUnit
    source: Literal["fixed", "shift_count", "km_entered"]
    detail: str | None = None
