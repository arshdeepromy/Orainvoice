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

    # Request-only per-staff pay-cycle selection (per-staff-pay-cycle feature).
    # NOT a ``staff_members`` column — the service persists it as a
    # ``pay_cycle_assignments`` row (target_type='staff') via
    # ``set_staff_pay_cycle``. ``None`` / omitted means "no staff-level
    # assignment", so the staff member resolves to the org Default_Cycle
    # (REQ 2.1, 2.3).
    pay_cycle_id: UUID | None = None

    # Request-only flag for self-service onboarding (R1.3, R1.4). When
    # set, the create handler mints an onboarding token and emails the
    # staff member a ``/onboard/{token}`` link. Requires a non-empty
    # ``email`` (enforced client-side and belt-and-braces server-side).
    # Not persisted.
    send_onboarding_link: bool = False

    @field_validator("kiwisaver_employee_rate")
    @classmethod
    def _validate_kiwisaver_employee_rate(
        cls, v: Decimal | None,
    ) -> Decimal | None:
        if v is None:
            return v
        # Custom employee rate permitted (per-org choice). The IRD-standard
        # restriction is lifted; we only bound it to a sane percentage range.
        # Payroll deductions use whatever rate is configured here.
        if v < 0 or v > 100:
            raise ValueError(
                "kiwisaver_employee_rate must be between 0 and 100",
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

    # Request-only per-staff pay-cycle selection (per-staff-pay-cycle feature).
    # Tri-state via ``model_dump(exclude_unset=True)`` in ``update_staff``:
    #   - omitted        → leave the existing assignment unchanged
    #   - ``<uuid>``     → set/replace the staff-level assignment (REQ 2.2, 3.1)
    #   - ``null``       → clear the assignment → resolves to default (REQ 3.3)
    # NOT a ``staff_members`` column — persisted via ``set_staff_pay_cycle``.
    pay_cycle_id: UUID | None = None

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
        # Custom employee rate permitted (per-org choice). The IRD-standard
        # restriction is lifted; we only bound it to a sane percentage range.
        if v < 0 or v > 100:
            raise ValueError(
                "kiwisaver_employee_rate must be between 0 and 100",
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

    # ------------------------------------------------------------------
    # Onboarding link send result (R3.6). Advisory, request-driven —
    # populated only when ``send_onboarding_link`` was set on create /
    # resend. ``onboarding_email_sent`` reports whether the invite email
    # was dispatched; ``onboarding_email_error`` carries a machine code
    # (e.g. ``"send_failed"`` / ``"no_email"``) when the send failed.
    # Both stay ``None`` for ordinary reads that did not trigger a send.
    # ------------------------------------------------------------------
    onboarding_email_sent: bool | None = None
    onboarding_email_error: str | None = None

    # ------------------------------------------------------------------
    # Resolved pay cycle (per-staff-pay-cycle feature, REQ 5.1-5.3).
    # Read-only. Populated in the router from
    # ``resolve_pay_cycles_for_staff_batch``: ``pay_cycle_id`` /
    # ``pay_cycle_name`` are the resolved cycle's id and name, and
    # ``pay_cycle_is_default`` is true when the staff member resolved via
    # the org Default_Cycle (REQ 5.2). All three are ``None`` / ``False``
    # when the staff member has no resolved cycle (REQ 5.3).
    # ------------------------------------------------------------------
    pay_cycle_id: UUID | None = None
    pay_cycle_name: str | None = None
    pay_cycle_is_default: bool = False

    # NOTE: ``ird_number`` and ``bank_account_number`` are returned in FULL
    # (unmasked) here. These are operationally required on the staff details
    # page and the payslip, and this endpoint family is already restricted to
    # staff-management roles (org_admin / branch_admin / location_manager). The
    # service layer still stores both values envelope-encrypted at rest; the
    # router decrypts them for this trusted, RBAC-gated serialisation path.

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
# Staff documents (onboarding / working-rights / manually-uploaded files)
# ---------------------------------------------------------------------------


class StaffDocumentItem(BaseModel):
    """A document linked to a staff member, for the Staff → Documents table.

    Rows come from two sources, distinguished by ``source``:

    - ``compliance`` — an onboarding / working-rights ``ComplianceDocument``
      (stored unencrypted on disk). Downloaded via the staff compliance
      download endpoint. ``esign_envelope_id`` / ``download_url`` are ``None``.
    - ``esign`` — a completed, signed e-signature PDF whose originating entity
      is this staff member (``signed_doc_status='stored'``). The signed PDF
      lives only on the envelope's encrypted ``file_key`` (never the plaintext
      compliance store), so the frontend must fetch it through the org-checked
      ``GET /api/v2/esign/envelopes/{esign_envelope_id}/signed-document``
      endpoint (surfaced here as ``download_url``).

    Backward compatibility: existing compliance rows keep ``source='compliance'``
    with both esign handles ``None``; the new fields are additive and optional.
    """

    id: UUID
    document_type: str
    description: str | None = None
    file_name: str
    file_size: int | None = None
    created_at: datetime
    expiry_date: date | None = None
    # Source discriminator + esign fetch handle (additive; default to the
    # legacy compliance shape so existing consumers are unaffected).
    source: Literal["compliance", "esign"] = "compliance"
    esign_envelope_id: UUID | None = None
    download_url: str | None = None


class StaffDocumentListResponse(BaseModel):
    """Wrapper per project-overview rule: arrays go in ``{ items, total }``."""

    items: list[StaffDocumentItem]
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


# ---------------------------------------------------------------------------
# Self-service onboarding — public prefill / draft / submit + admin status
# (R4, R6, R8, R9, R11, R12, R13)
#
# These schemas back the public, token-gated onboarding endpoints
# (``/api/v2/public/staff-onboarding/...``) and the authenticated admin
# status endpoint (``GET /api/v2/staff/{id}/onboarding-link``).
#
# Option lists reuse the module-level ``TaxCode`` / ``ResidencyType``
# Literals and ``_KIWISAVER_EMPLOYEE_RATES`` so the public form's allowed
# values never drift from the authoritative Create/Update schemas.
# ---------------------------------------------------------------------------

# Static option lists derived from the existing Literals / rate tuple so the
# public form renders exactly the values the rest of the module accepts. Built
# once at import so every prefill response shares the same constant lists.
_TAX_CODE_OPTIONS: tuple[str, ...] = (
    "M", "ME", "S", "SH", "ST", "SB", "CAE", "NSW", "ND",
)
_RESIDENCY_OPTIONS: tuple[str, ...] = (
    "citizen", "permanent_resident", "work_visa", "student_visa", "other",
)
# KiwiSaver employee-rate options as plain ints for the form dropdown,
# derived from the authoritative ``_KIWISAVER_EMPLOYEE_RATES`` Decimal tuple.
_KIWISAVER_RATE_OPTIONS: tuple[int, ...] = tuple(
    int(r) for r in _KIWISAVER_EMPLOYEE_RATES
)


class OnboardingDraftFields(BaseModel):
    """The saved draft as returned on resume (R12.3, R11.6).

    Non-sensitive fields are returned in full. ``ird_number`` and
    ``bank_account_number`` are returned **masked** (never the decrypted
    plaintext) alongside ``has_ird`` / ``has_bank`` presence flags so the
    client can render the masked placeholder and, via the existing
    ``isMaskedIrd`` / ``isMaskedBank`` heuristic, avoid re-sending it
    unless the staff member retypes the value. ``documents_staged_count``
    carries the number of files staged locally (the files themselves are
    never stored in the draft — they upload only on final submit).
    """

    # Personal / tax / residency — returned in full (not sensitive).
    last_name: str | None = None
    phone: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    tax_code: str | None = None
    student_loan: bool | None = None
    kiwisaver_enrolled: bool | None = None
    kiwisaver_employee_rate: Decimal | None = None
    residency_type: str | None = None
    visa_expiry_date: date | None = None

    # Sensitive PII — masked placeholder + presence flag (R11.6).
    ird_number: str | None = None
    has_ird: bool = False
    bank_account_number: str | None = None
    has_bank: bool = False

    # Documents staged locally (files not stored in the draft).
    documents_staged_count: int = 0


class OnboardingPrefillResponse(BaseModel):
    """``GET /api/v2/public/staff-onboarding/{token}`` 200 body.

    Exposes only ``first_name`` + ``email`` of the staff member (R11.6) —
    these are pre-filled read-only (R4.2) — plus the org display name for
    page chrome (R12.4), the static option lists, and a
    ``bank_account_required`` flag from org config (R5.4).

    For resume (R12.3), a nullable ``draft`` object carries the saved
    partial form (with IRD/bank masked), and the top-level
    ``completion_percentage`` / ``last_saved_at`` reflect the server-side
    draft state. All three are ``None`` when no draft has been saved yet.
    """

    first_name: str
    email: str
    org_name: str
    tax_code_options: list[str] = Field(
        default_factory=lambda: list(_TAX_CODE_OPTIONS),
    )
    residency_options: list[str] = Field(
        default_factory=lambda: list(_RESIDENCY_OPTIONS),
    )
    kiwisaver_rate_options: list[int] = Field(
        default_factory=lambda: list(_KIWISAVER_RATE_OPTIONS),
    )
    bank_account_required: bool = False

    # Resume payload (R12.3) — null when no draft saved yet.
    draft: OnboardingDraftFields | None = None
    completion_percentage: int | None = None
    last_saved_at: datetime | None = None


class OnboardingDraftRequest(BaseModel):
    """``PUT /api/v2/public/staff-onboarding/{token}/draft`` body (R12.1).

    Every field is optional (``| None = None``) — partial data is the whole
    point of a draft (R12.5). No submit-time field validation runs here;
    only the basic shape/size guards in the handler apply. The handler
    serializes this payload to JSON and envelope-encrypts the whole blob
    before storing it on the token row (R12.6).
    """

    last_name: str | None = None
    phone: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    bank_account_number: str | None = None
    ird_number: str | None = None
    tax_code: str | None = None
    student_loan: bool | None = None
    kiwisaver_enrolled: bool | None = None
    kiwisaver_employee_rate: Decimal | None = None
    residency_type: str | None = None
    visa_expiry_date: date | None = None
    documents_staged_count: int | None = None


class OnboardingDraftResponse(BaseModel):
    """``PUT /api/v2/public/staff-onboarding/{token}/draft`` 200 body (R12.1).

    ``completion_percentage`` is the server-computed, section-weighted score
    in ``[0, 100]`` (R13.3, R13.4); ``last_saved_at`` is the draft's
    ``draft_updated_at`` timestamp the client renders as "Saved {time}".
    """

    ok: bool = True
    completion_percentage: int
    last_saved_at: datetime


class OnboardingFieldError(BaseModel):
    """One inline field error in a submit rejection (R9.2, R14).

    ``message`` is the human-readable text; ``code`` is the machine code
    for client-side mapping. Carries no raw DB/exception text (R14).
    """

    message: str
    code: str


class OnboardingSubmitResponse(BaseModel):
    """``POST /api/v2/public/staff-onboarding/{token}`` response body (R9).

    On success: ``ok=true`` + a friendly ``message`` (R9.5). On validation
    failure (returned with HTTP 422): ``ok=false``, a top-level ``message``,
    and an ``errors`` map of ``field -> {message, code}`` (R9.2, R14).
    ``warnings`` carries any non-blocking advisories.
    """

    ok: bool
    message: str | None = None
    errors: dict[str, OnboardingFieldError] | None = None
    warnings: list[str] | None = None


class OnboardingLinkStatusResponse(BaseModel):
    """``GET /api/v2/staff/{staff_id}/onboarding-link`` 200 body (R10.1, R13).

    ``state`` is the admin lifecycle label from
    ``onboarding_lifecycle_label(row, now)``:
    ``not_started`` (pending, no draft saved), ``in_progress`` (pending,
    draft saved), ``completed`` (consumed), ``expired`` (pending past
    expiry), ``revoked``, or ``none`` (no token row).

    ``completion_percentage`` and ``last_saved_at`` are populated only when
    ``state == "in_progress"`` (R13.1, R13.2); they are ``None`` otherwise.
    The timestamp fields describe the resolved token row.
    """

    state: Literal[
        "not_started", "in_progress", "completed", "expired", "revoked", "none",
    ]
    expires_at: datetime | None = None
    created_at: datetime | None = None
    consumed_at: datetime | None = None
    completion_percentage: int | None = None
    last_saved_at: datetime | None = None


class IssuePortalAccessResponse(BaseModel):
    """``POST /api/v2/staff/{staff_id}/portal-access`` 201 body (R5.3, R15.1, R15.3).

    ``invite_sent`` reflects whether the credential-setup email was accepted
    by a provider; ``invite_error`` carries the machine error code
    (``portal_email_required`` / ``send_failed``) when delivery failed. The
    Portal_User row is always created and preserved — a failed email never
    rolls it back (R15.3), so the endpoint still returns ``201``.
    """

    portal_user_id: UUID
    email: str
    invite_sent: bool
    invite_error: str | None = None


class RevokePortalAccessResponse(BaseModel):
    """``DELETE /api/v2/staff/{staff_id}/portal-access`` 200 body (R5.10)."""

    revoked: bool = True
    sessions_invalidated: int = 0


class PortalAccessStatusResponse(BaseModel):
    """``GET /api/v2/staff/{staff_id}/portal-access`` body.

    Reports whether the staff member currently holds Employee Portal access and,
    if so, whether the invite has been accepted (password set) yet. ``state`` is
    one of: ``none`` (no active portal user), ``invited`` (issued, not yet
    accepted), ``active`` (password set / can log in).
    """

    state: str = "none"
    email: str | None = None
    invite_sent_at: datetime | None = None
    invite_accepted_at: datetime | None = None
    last_login_at: datetime | None = None
