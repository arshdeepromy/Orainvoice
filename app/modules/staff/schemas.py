"""Pydantic v2 schemas for staff CRUD, location assignment, and reporting.

**Validates: Requirements R2, R3, R4, R8, R9 — Staff Management Phase 1**

Phase 1 extensions (task B3):
- ``StaffMemberCreate`` and ``StaffMemberUpdate`` gain the 22 new
  employment / payroll / contact / opt-in fields enumerated in R2.1, plus
  the request-only ``minimum_wage_override`` flag (R4).
- ``StaffMemberResponse`` masks ``ird_number`` and ``bank_account_number``
  on outbound serialisation via field validators so the plaintext PII
  never leaves the service layer.
- ``StaffMemberUpdate`` rejects mask-pattern values for those two fields
  with HTTP 422 (so the client gets fast feedback). The service-layer
  mask detection in ``StaffService.update_staff`` is the real guard.
- ``StaffPayRateResponse`` + ``StaffPayRateListResponse`` for the
  ``/api/v2/staff/:id/pay-rates`` endpoint (R3.5).
- ``RosterEmailRequest`` / ``RosterSmsRequest`` / ``RosterSendResponse``
  for the new roster delivery endpoints (R8, R9).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.modules.staff.security import (
    is_masked_bank,
    is_masked_ird,
    mask_bank_account,
    mask_ird,
)


# ---------------------------------------------------------------------------
# Enum-style Literal aliases (kept here so Create/Update/Response stay aligned)
# ---------------------------------------------------------------------------

EmploymentType = Literal["permanent", "casual", "fixed_term"]
EmploymentBasis = Literal["full_time", "part_time", "casual", "contractor"]
WorkingArrangement = Literal["fixed", "rostered", "casual_on_demand"]
TaxCode = Literal["M", "ME", "S", "SH", "ST", "SB", "CAE", "NSW", "ND"]
ResidencyType = Literal[
    "citizen", "permanent_resident", "work_visa", "student_visa", "other",
]

# KiwiSaver employee contribution rates allowed by IRD as of 2024 (R2.1).
_KIWISAVER_EMPLOYEE_RATES: tuple[Decimal, ...] = (
    Decimal("3"), Decimal("4"), Decimal("6"), Decimal("8"), Decimal("10"),
)


# ---------------------------------------------------------------------------
# Staff member schemas
# ---------------------------------------------------------------------------


class StaffMemberCreate(BaseModel):
    """Inbound payload for ``POST /api/v2/staff``.

    Phase 1 added the employment / payroll / contact / opt-in fields per
    R2.1. ``ird_number`` and ``bank_account_number`` are accepted as
    plaintext and envelope-encrypted by the service before storage.
    """

    user_id: UUID | None = None
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    employee_id: str | None = None
    position: str | None = None
    reporting_to: UUID | None = None
    shift_start: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    shift_end: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    role_type: str = Field(default="employee", pattern="^(employee|contractor)$")
    employment_basis: EmploymentBasis = "full_time"
    working_arrangement: WorkingArrangement = "rostered"
    hourly_rate: Decimal | None = None
    overtime_rate: Decimal | None = None
    availability_schedule: dict = Field(default_factory=dict)
    skills: list[str] = Field(default_factory=list)

    # ------------------------------------------------------------------
    # Phase 1 — employment record (R2.1).
    # ------------------------------------------------------------------
    employment_start_date: date | None = None
    employment_end_date: date | None = None
    employment_type: EmploymentType = "permanent"
    standard_hours_per_week: Decimal | None = None
    tax_code: TaxCode | None = None
    ird_number: str | None = None
    student_loan: bool = False
    kiwisaver_enrolled: bool = False
    kiwisaver_employee_rate: Decimal | None = None
    kiwisaver_employer_rate: Decimal = Decimal("3.00")
    bank_account_number: str | None = None
    probation_end_date: date | None = None
    residency_type: ResidencyType = "citizen"
    visa_expiry_date: date | None = None
    # Phase 3 task B3a (G9): tri-state ``None`` lets the service
    # distinguish "caller didn't say" from "explicitly false". When
    # omitted, ``StaffService.create_staff`` reads the org's
    # ``clock_in_policy.default_channel`` and derives the value
    # (``kiosk_and_self_service`` → True, ``kiosk_only`` → False).
    self_service_clock_enabled: bool | None = None
    on_file_photo_url: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    weekly_roster_email_enabled: bool = True
    weekly_roster_sms_enabled: bool = False

    # Request-only flag for the minimum-wage gate (R4). Not persisted.
    minimum_wage_override: bool = False

    @field_validator("kiwisaver_employee_rate")
    @classmethod
    def _validate_kiwisaver_employee_rate(
        cls, v: Decimal | None,
    ) -> Decimal | None:
        if v is None:
            return v
        if v not in _KIWISAVER_EMPLOYEE_RATES:
            allowed = ", ".join(str(r) for r in _KIWISAVER_EMPLOYEE_RATES)
            raise ValueError(
                f"kiwisaver_employee_rate must be one of [{allowed}]",
            )
        return v


class StaffMemberUpdate(BaseModel):
    """Inbound payload for ``PUT /api/v2/staff/:id``.

    All fields optional. Mask-pattern values for ``ird_number`` and
    ``bank_account_number`` are rejected with a fast ``422`` so the
    client knows it tried to re-submit a previously-masked display
    value. The service-layer mask check in ``update_staff`` remains the
    authoritative guard (see R2.4).
    """

    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    employee_id: str | None = None
    position: str | None = None
    reporting_to: UUID | None = None
    shift_start: str | None = None
    shift_end: str | None = None
    role_type: str | None = Field(None, pattern="^(employee|contractor)$")
    employment_basis: EmploymentBasis | None = None
    working_arrangement: WorkingArrangement | None = None
    hourly_rate: Decimal | None = None
    overtime_rate: Decimal | None = None
    is_active: bool | None = None
    availability_schedule: dict | None = None
    skills: list[str] | None = None

    # ------------------------------------------------------------------
    # Phase 1 — employment record (R2.1).
    # ------------------------------------------------------------------
    employment_start_date: date | None = None
    employment_end_date: date | None = None
    employment_type: EmploymentType | None = None
    standard_hours_per_week: Decimal | None = None
    tax_code: TaxCode | None = None
    ird_number: str | None = None
    student_loan: bool | None = None
    kiwisaver_enrolled: bool | None = None
    kiwisaver_employee_rate: Decimal | None = None
    kiwisaver_employer_rate: Decimal | None = None
    bank_account_number: str | None = None
    probation_end_date: date | None = None
    residency_type: ResidencyType | None = None
    visa_expiry_date: date | None = None
    self_service_clock_enabled: bool | None = None
    on_file_photo_url: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    weekly_roster_email_enabled: bool | None = None
    weekly_roster_sms_enabled: bool | None = None

    # Request-only flag for the minimum-wage gate (R4). Not persisted.
    minimum_wage_override: bool = False

    @field_validator("ird_number")
    @classmethod
    def _reject_masked_ird(cls, v: str | None) -> str | None:
        # Fast 422 when client submits the masked display value. The
        # service layer also runs ``is_masked_ird`` as the real guard
        # (in case the client bypasses the schema, e.g. via a different
        # client library) — this validator is purely for UX feedback.
        if v is not None and is_masked_ird(v):
            raise ValueError(
                "ird_number appears to be a masked display value "
                "(e.g. '***123'); type the full IRD or omit the field "
                "to keep the existing value",
            )
        return v

    @field_validator("bank_account_number")
    @classmethod
    def _reject_masked_bank(cls, v: str | None) -> str | None:
        if v is not None and is_masked_bank(v):
            raise ValueError(
                "bank_account_number appears to be a masked display "
                "value; type the full account number or omit the field "
                "to keep the existing value",
            )
        return v

    @field_validator("kiwisaver_employee_rate")
    @classmethod
    def _validate_kiwisaver_employee_rate(
        cls, v: Decimal | None,
    ) -> Decimal | None:
        if v is None:
            return v
        if v not in _KIWISAVER_EMPLOYEE_RATES:
            allowed = ", ".join(str(r) for r in _KIWISAVER_EMPLOYEE_RATES)
            raise ValueError(
                f"kiwisaver_employee_rate must be one of [{allowed}]",
            )
        return v


class LocationAssignmentResponse(BaseModel):
    id: UUID
    staff_id: UUID
    location_id: UUID
    assigned_at: datetime

    model_config = {"from_attributes": True}


class StaffMemberResponse(BaseModel):
    """Outbound staff record.

    ``ird_number`` and ``bank_account_number`` are masked here via field
    validators so callers never receive plaintext PII through the API.
    The service layer is responsible for populating these fields with
    the decrypted plaintext (or ``None``); this schema masks whatever
    plaintext is provided so a stray plaintext would still be caught.
    """

    id: UUID
    org_id: UUID
    user_id: UUID | None = None
    name: str
    first_name: str
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    employee_id: str | None = None
    position: str | None = None
    reporting_to: UUID | None = None
    reporting_to_name: str | None = None
    shift_start: str | None = None
    shift_end: str | None = None
    role_type: str
    employment_basis: str = "full_time"
    working_arrangement: str = "rostered"
    hourly_rate: Decimal | None = None
    overtime_rate: Decimal | None = None
    is_active: bool
    availability_schedule: dict = Field(default_factory=dict)
    skills: list = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    location_assignments: list[LocationAssignmentResponse] = Field(default_factory=list)

    # ------------------------------------------------------------------
    # Phase 1 — employment record (R2). Returned masked on outbound.
    # ------------------------------------------------------------------
    employment_start_date: date | None = None
    employment_end_date: date | None = None
    employment_type: str = "permanent"
    standard_hours_per_week: Decimal | None = None
    tax_code: str | None = None
    ird_number: str | None = None
    student_loan: bool = False
    kiwisaver_enrolled: bool = False
    kiwisaver_employee_rate: Decimal | None = None
    kiwisaver_employer_rate: Decimal = Decimal("3.00")
    bank_account_number: str | None = None
    probation_end_date: date | None = None
    residency_type: str = "citizen"
    visa_expiry_date: date | None = None
    self_service_clock_enabled: bool = False
    on_file_photo_url: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    weekly_roster_email_enabled: bool = True
    weekly_roster_sms_enabled: bool = False
    last_pay_review_date: date | None = None
    employment_agreement_upload_id: UUID | None = None

    @field_validator("ird_number", mode="before")
    @classmethod
    def _mask_ird_field(cls, v: str | None) -> str | None:
        # If the value is already masked (i.e. round-tripped through the
        # service or stored that way somewhere), pass it through. If
        # plaintext somehow leaked into this serialisation path, mask
        # it now as a defence-in-depth.
        if v is None:
            return None
        if is_masked_ird(v):
            return v
        return mask_ird(v)

    @field_validator("bank_account_number", mode="before")
    @classmethod
    def _mask_bank_field(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if is_masked_bank(v):
            return v
        return mask_bank_account(v)

    model_config = {"from_attributes": True}


class ComplianceSummary(BaseModel):
    """Aggregate counters surfaced on ``GET /api/v2/staff`` (Phase 1 R6).

    All seven keys are integers; default-zero so callers can rely on
    the field being present even when the underlying SELECT returned a
    ``NULL`` (which shouldn't happen with ``COUNT(*) FILTER`` but
    defence-in-depth).

    The list-endpoint shape stays ``{ staff, total, page, page_size }``
    (P1-N8 — not renamed to ``items``); ``compliance_summary`` is added
    as a parallel top-level key on :class:`StaffMemberListResponse`.
    """

    probation_ending_soon: int = 0
    visa_expiring_soon: int = 0
    missing_agreement: int = 0
    pay_review_due: int = 0
    below_minimum_wage: int = 0
    missing_employee_id: int = 0
    missing_start_date: int = 0


class StaffMemberListResponse(BaseModel):
    staff: list[StaffMemberResponse]
    total: int
    page: int = 1
    page_size: int = 50
    compliance_summary: ComplianceSummary | None = None


class AssignToLocationRequest(BaseModel):
    location_id: UUID


class CreateStaffAccountRequest(BaseModel):
    password: str = Field(..., min_length=8, max_length=128)


class UtilisationReport(BaseModel):
    staff_id: UUID
    staff_name: str
    billable_minutes: int = 0
    total_minutes: int = 0
    available_minutes: int = 0
    utilisation_percent: Decimal = Decimal("0")


class UtilisationReportResponse(BaseModel):
    staff: list[UtilisationReport]
    date_from: str
    date_to: str


class LabourCostEntry(BaseModel):
    staff_id: UUID
    staff_name: str
    total_minutes: int = 0
    hourly_rate: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")


class LabourCostResponse(BaseModel):
    entries: list[LabourCostEntry]
    total_cost: Decimal = Decimal("0")
    date_from: str
    date_to: str


# ---------------------------------------------------------------------------
# Pay rate history schemas (R3)
# ---------------------------------------------------------------------------


class StaffPayRateResponse(BaseModel):
    """One row of the staff pay-rate audit ledger.

    ``changed_by_email`` is resolved by the service via a join to
    ``users.email`` so the UI can render "by jane@acme.co.nz" without an
    extra round-trip.
    """

    id: UUID
    effective_from: date
    hourly_rate: Decimal | None = None
    overtime_rate: Decimal | None = None
    change_reason: str | None = None
    changed_by_email: str | None = None

    model_config = {"from_attributes": True}


class StaffPayRateListResponse(BaseModel):
    """Wrapper per project-overview rule: arrays go in ``{ items, total }``."""

    items: list[StaffPayRateResponse]
    total: int


# ---------------------------------------------------------------------------
# Roster delivery schemas (R8, R9)
# ---------------------------------------------------------------------------


class RosterEmailRequest(BaseModel):
    """Body for ``POST /api/v2/staff/:id/email-roster``."""

    week_start: date


class RosterSmsRequest(BaseModel):
    """Body for ``POST /api/v2/staff/:id/sms-roster``."""

    week_start: date


class RosterSendResponse(BaseModel):
    """Common response shape for both roster delivery endpoints.

    ``ok`` is the success flag, ``message_id`` is the provider's id when
    the send succeeds, ``reason`` carries a machine-readable failure
    code (``no_shifts_in_week``, ``no_email``, ``opt_out``, ...) when
    ``ok=false``.
    """

    ok: bool
    message_id: str | None = None
    reason: str | None = None


# ---------------------------------------------------------------------------
# Employment agreement attach (R5, task C8)
# ---------------------------------------------------------------------------


class EmploymentAgreementRequest(BaseModel):
    """Body for ``POST /api/v2/staff/:id/employment-agreement``.

    ``upload_id`` is the UUID portion of the ``file_key`` returned by
    the existing ``POST /api/v2/uploads/attachments`` flow — the
    frontend extracts the hex segment between the org_id path and the
    file extension and sends it here as a real UUID. The router
    validates that the corresponding file is present on disk under the
    requesting org's ``attachments/`` namespace before persisting the
    reference.

    See gap-analysis A1-O3 for the rationale: the spec assumed an
    ``uploads`` ORM model exists (FK to ``uploads.id``) but the actual
    uploads pipeline is filesystem-only and returns
    ``{file_key, file_name, file_size}``. Phase 1 keeps the column as
    a free-standing ``uuid`` (no FK) and validates org ownership via
    the file path, which is already org-scoped (P1-N16).
    """

    upload_id: UUID


# ---------------------------------------------------------------------------
# Staff redesign — month stats + list KPIs (R11, R12, R14, R1.6, R9.2)
# ---------------------------------------------------------------------------


class StaffMetricValue(BaseModel):
    """One month metric: a numeric value plus a ``has_data`` flag.

    ``has_data=false`` signals the frontend to render ``'—'`` rather
    than the (meaningless) zero value. ``value`` is always a number so
    the schema stays a structured object, never null-in-a-bare-field
    (R12.5).
    """

    value: Decimal
    has_data: bool


class StaffMonthStatsResponse(BaseModel):
    """``GET /api/v2/staff/{id}/stats`` response — a structured object,
    NOT a bare array (R14.5).

    One sub-object per metric so each can carry its own ``has_data``
    flag (R11.1, R12.1).
    """

    staff_id: UUID
    period: Literal["this_month"]
    hours_logged: StaffMetricValue       # hours, 1 dp
    jobs_completed: StaffMetricValue     # integer count
    billable_ratio: StaffMetricValue     # whole percent 0–100
    on_time_rate: StaffMetricValue       # whole percent 0–100
    last_sign_in: datetime | None = None  # from users.last_login_at
    user_role: str | None = None          # from users.role (null when no linked user)


class StaffListKpisResponse(BaseModel):
    """Org-wide staff list KPIs (R1.6)."""

    total_staff: int
    employee_count: int
    with_login_count: int
    avg_hourly_rate: Decimal | None = None  # null → '—'
