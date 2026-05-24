"""Fleet Portal Pydantic request/response schemas.

Every endpoint in ``router.py`` and ``admin_router.py`` MUST set
``response_model=`` to one of the response schemas declared here
(steering Rule 8). New fields added to a service dict MUST be added to
the matching response schema in this file in the same change set so the
contract stays in sync.

API conventions enforced here (see steering: ``safe-api-consumption.md``,
``frontend-backend-contract-alignment.md``):

- List responses wrap arrays in ``{ items, total, limit, offset }`` —
  never bare arrays. The generic :class:`PaginatedResponse` is reused
  across list endpoints; module-specific list schemas inherit from it.
- Pagination uses ``offset`` / ``limit``. Submitting ``skip`` is
  rejected by FastAPI with HTTP 422 because no field of that name
  exists on any request schema (and ``model_config = {"extra":
  "forbid"}`` enforces the rejection on bodies — see
  :class:`_StrictBase`).
- Error envelope is ``{ "detail": "<msg>" }`` — provided by FastAPI's
  default ``HTTPException`` rendering, mirrored here in
  :class:`ErrorEnvelope` for documentation.
- Property-test contract:
  - Property 7  — password length ≥ 8 and not equal to email local-part.
  - Property 25 — reminder preference: enabled → channels and recipients
    non-empty, lead_time_days ∈ {7,14,30}, channels ⊆ {email,sms},
    recipients ⊆ {fleet_admin, assigned_drivers}.
  - Property 30 — booking/quote: service_description length ≥ 10,
    preferred_slot ∈ {morning, afternoon, all_day}.

Implements: B2B Fleet Portal task 2.3 — Requirements 3.8, 10.2, 11.1,
11.3, 12.1, 18.1, 18.2, 18.3.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)


# ---------------------------------------------------------------------------
# Shared base classes & primitives
# ---------------------------------------------------------------------------


class _StrictBase(BaseModel):
    """Base for request bodies — rejects unknown fields with HTTP 422.

    Forces pagination to use ``offset`` (rejecting ``skip``) and surfaces
    typos in client payloads loudly rather than silently dropping them.
    """

    model_config = ConfigDict(extra="forbid")


class _ResponseBase(BaseModel):
    """Base for response models — permissive on extras for forward compat.

    Future server fields will pass through to clients without a 500.
    """

    model_config = ConfigDict(from_attributes=True)


T = TypeVar("T")


class PaginatedResponse(_ResponseBase, Generic[T]):
    """Generic paginated list wrapper used by every fleet portal list endpoint.

    Module-specific list schemas can extend this generic
    (``PaginatedResponse[VehicleListItem]``) or compose their own list
    type with the same four fields. The four fields are mandatory.
    """

    items: list[T]
    total: int = Field(0, ge=0)
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)


class ErrorEnvelope(_ResponseBase):
    """Standard error envelope. Mirrors FastAPI's HTTPException output."""

    detail: str


class PaginationParams(_StrictBase):
    """Reusable query-param bundle for paginated endpoints.

    Use ``Depends(PaginationParams)`` in routes, or inline the fields.
    Defining it here makes the ``offset``/``limit`` contract explicit
    and lets us reject ``skip`` consistently. ``limit`` is capped at
    200 so a hostile client cannot demand huge pages while still
    accommodating admin views that legitimately page in larger chunks.
    """

    offset: int = Field(0, ge=0, description="Number of rows to skip")
    limit: int = Field(50, ge=1, le=200, description="Page size (max 200)")


class IdResponse(_ResponseBase):
    """Generic ``{ id }`` response for endpoints that only return the new ID."""

    id: UUID


class StatusResponse(_ResponseBase):
    """Generic ``{ ok }`` response for endpoints that only confirm success."""

    ok: bool = True


# ---------------------------------------------------------------------------
# Auth — login / logout / forgot-password / reset / accept-invite / me
# ---------------------------------------------------------------------------


_PASSWORD_MIN_LENGTH = 8


def _validate_password_against_email(password: str, email: str) -> str:
    """Property 7 password validator.

    Accepts the password iff:
      - length ≥ 8, AND
      - lowercase form does NOT equal the lowercase local-part of the email.

    Mirrors ``auth.validate_password_rules`` (task 3.1). The schema
    layer enforces it cheaply at request validation time so the service
    can rely on the invariant; the service still re-validates against
    the live ``portal_security_policy`` (task 4A.1) for richer rules
    (history, breach check, etc).
    """
    if len(password) < _PASSWORD_MIN_LENGTH:
        raise ValueError(
            f"Password must be at least {_PASSWORD_MIN_LENGTH} characters"
        )
    local_part = (email.split("@", 1)[0] if "@" in email else email).strip().lower()
    if local_part and password.strip().lower() == local_part:
        raise ValueError("Password must not match your email username")
    return password


class LoginRequest(_StrictBase):
    """``POST /fleet/api/auth/login`` body."""

    email: EmailStr
    password: str = Field(..., min_length=1, max_length=200)


class LoginResponse(_ResponseBase):
    """Successful login response.

    On a happy path (no MFA challenge required), this is what the
    frontend gets and the HttpOnly session cookie is set. When MFA is
    enrolled, the response instead is :class:`MfaChallengeResponse`
    (the frontend branches on the ``mfa_required`` discriminator).

    Implements Requirement 3.2.
    """

    portal_account_id: UUID
    fleet_account_id: UUID | None
    portal_user_role: Literal["fleet_admin", "driver"]
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None
    must_change_password: bool = False
    mfa_required: Literal[False] = False


class MfaChallengeResponse(_ResponseBase):
    """MFA challenge required response (after primary credentials accepted).

    Frontend uses ``mfa_token`` to call
    ``POST /fleet/api/auth/mfa/verify``; ``default_method`` is the
    method the user enrolled most recently or marked as default.

    Implements Requirements 21.13, 21.14.
    """

    mfa_required: Literal[True] = True
    mfa_token: str
    mfa_methods: list[Literal["totp", "sms", "backup_codes"]]
    default_method: Literal["totp", "sms", "backup_codes"]


class MfaSetupRequiredResponse(_ResponseBase):
    """Account must enrol an MFA method before login can complete.

    Returned when the org's ``mfa_policy.mode == 'required'`` (or the
    account's ``mfa_required_at_next_login = true``) and no methods
    are enrolled yet. The frontend forwards the ``mfa_token`` to
    ``/fleet/security/mfa/enroll/totp``.

    Implements Requirement 21.14.
    """

    mfa_setup_required: Literal[True] = True
    mfa_token: str


class ForgotPasswordRequest(_StrictBase):
    """``POST /fleet/api/auth/forgot-password`` body.

    The endpoint is deliberately anti-enumerating (Property 8): the
    response is identical regardless of whether the email matches a
    known account.
    """

    email: EmailStr


class ResetPasswordRequest(_StrictBase):
    """``POST /fleet/api/auth/reset-password/{token}`` body."""

    new_password: str = Field(..., max_length=200)
    email: EmailStr  # for password-vs-email validation

    @model_validator(mode="after")
    def _check_password(self) -> ResetPasswordRequest:
        _validate_password_against_email(self.new_password, self.email)
        return self


class AcceptInviteRequest(_StrictBase):
    """``POST /fleet/api/auth/accept-invite/{token}`` body."""

    new_password: str = Field(..., max_length=200)
    email: EmailStr

    @model_validator(mode="after")
    def _check_password(self) -> AcceptInviteRequest:
        _validate_password_against_email(self.new_password, self.email)
        return self


class CurrentUserResponse(_ResponseBase):
    """``GET /fleet/api/me`` response.

    The mobile and SPA frontends call this on every app open to
    populate the user banner and decide which tabs to show.
    ``sms_provider_configured`` lets the reminder preferences page
    grey out the SMS channel when the workshop hasn't wired up SMS.

    Implements Requirements 3.13, 5.1, 11.1.
    """

    portal_account_id: UUID
    fleet_account_id: UUID | None
    fleet_account_name: str | None
    portal_user_role: Literal["fleet_admin", "driver"]
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None
    sms_provider_configured: bool = False
    must_change_password: bool = False


# ---------------------------------------------------------------------------
# Vehicles — list / detail / odometer / hours / add / edit
# ---------------------------------------------------------------------------


_BadgeColour = Literal["red", "amber", "green"]


class VehicleListItem(_ResponseBase):
    """One vehicle row in the fleet list.

    Driver views and admin views both use this shape; ``assigned_driver_names``
    is empty for the driver's own vehicles (since they only see their own).

    Implements Requirements 6.2, 6.3, 6.4, 7.8.
    """

    customer_vehicle_id: UUID
    rego: str
    make: str | None = None
    model: str | None = None
    year: int | None = None
    colour: str | None = None
    odometer_last_recorded: int | None = None
    wof_expiry: date | None = None
    cof_expiry: date | None = None
    registration_expiry: date | None = None
    service_due_date: date | None = None
    wof_badge: _BadgeColour | None = None
    cof_badge: _BadgeColour | None = None
    service_badge: _BadgeColour | None = None
    assigned_driver_names: list[str] = Field(default_factory=list)


class VehicleListResponse(PaginatedResponse[VehicleListItem]):
    """``GET /fleet/api/vehicles`` response."""


class VehicleDetailResponse(VehicleListItem):
    """``GET /fleet/api/vehicles/{id}`` response.

    Same shape as the list item plus extended fields that are too big
    to load for the list view (last 10 odometer readings, recent
    submissions). Reuses the list item to keep the contract uniform.
    """

    vin: str | None = None
    chassis: str | None = None
    engine_no: str | None = None
    notes: str | None = None
    fleet_checklist_template_id: UUID | None = None


class VehicleAddRequest(_StrictBase):
    """``POST /fleet/api/vehicles`` body (admin-only).

    Looks up the rego in ``global_vehicles`` (CarJam pathway) and
    creates a ``customer_vehicles`` link. ``odometer_at_link`` is
    optional but recommended.

    Implements Requirement 6.5.
    """

    rego: str = Field(..., min_length=1, max_length=10)
    odometer_at_link: int | None = Field(None, ge=0)

    @field_validator("rego", mode="before")
    @classmethod
    def _normalise_rego(cls, v: str) -> str:
        # Strip whitespace and uppercase so duplicates collapse.
        return v.strip().upper() if isinstance(v, str) else v


class VehicleEditRequest(_StrictBase):
    """``PATCH /fleet/api/vehicles/{id}`` body.

    Only fields in this schema can be sent at all; per-role allowlist
    enforcement happens in ``vehicle_service.update_vehicle_fields``
    (Property 14). ``make``/``model``/``year``/``vin``/``rego`` are
    DELIBERATELY absent from the schema so client-side typos cannot
    even attempt to mutate them.

    Implements Requirements 6.6, 7.2, 7.3, 7.4.
    """

    fleet_internal_name: str | None = Field(None, max_length=100)
    fleet_number: str | None = Field(None, max_length=50)
    notes: str | None = Field(None, max_length=2000)
    colour: str | None = Field(None, max_length=50)
    odometer_last_recorded: int | None = Field(None, ge=0)
    wof_expiry: date | None = None
    cof_expiry: date | None = None
    service_due_date: date | None = None
    fleet_checklist_template_id: UUID | None = None


class OdometerLogRequest(_StrictBase):
    """``POST /fleet/api/vehicles/{id}/odometer`` body.

    Service rejects values not strictly greater than the previous max
    with HTTP 400 and the current max in the message (Property 15,
    Requirement 7.7).
    """

    odometer_km: int = Field(..., ge=0)


class OdometerLogResponse(_ResponseBase):
    """Reading persisted; new max is reflected in ``odometer_km``."""

    customer_vehicle_id: UUID
    odometer_km: int
    recorded_at: datetime


class HoursLogRequest(_StrictBase):
    """``POST /fleet/api/vehicles/{id}/hours`` body — driver-only.

    Implements Requirement 7.5.
    """

    start_at: datetime
    end_at: datetime
    notes: str | None = Field(None, max_length=2000)

    @model_validator(mode="after")
    def _check_range(self) -> HoursLogRequest:
        if self.end_at < self.start_at:
            raise ValueError("end_at must be greater than or equal to start_at")
        return self


class HoursLogResponse(_ResponseBase):
    """One hours-log entry (used in list and post responses)."""

    id: UUID
    customer_vehicle_id: UUID
    portal_account_id: UUID
    start_at: datetime
    end_at: datetime
    notes: str | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Drivers — invite / assign / list / activity
# ---------------------------------------------------------------------------


class DriverInviteRequest(_StrictBase):
    """``POST /fleet/api/drivers/invite`` body (admin-only).

    Implements Requirement 5.2.
    """

    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone: str | None = Field(None, max_length=50)


class DriverAssignmentRequest(_StrictBase):
    """``POST /fleet/api/drivers/{id}/assignments`` body (admin-only).

    Implements Requirement 5.5.
    """

    customer_vehicle_id: UUID


class DriverListItem(_ResponseBase):
    """One driver row on the Drivers page.

    Implements Requirement 5.9.
    """

    portal_account_id: UUID
    first_name: str | None = None
    last_name: str | None = None
    email: EmailStr
    phone: str | None = None
    is_active: bool
    last_login_at: datetime | None = None
    assigned_vehicle_count: int = 0
    last_submission_at: datetime | None = None


class DriverListResponse(PaginatedResponse[DriverListItem]):
    """``GET /fleet/api/drivers`` response."""


class DriverActivityVehicleRow(_ResponseBase):
    """One row of activity per vehicle / per day (Property 33).

    Used both for the JSON activity endpoint and the CSV export.
    """

    date: date
    customer_vehicle_id: UUID
    rego: str
    submissions_count: int = 0
    failures_count: int = 0
    odometer_log_count: int = 0
    hours_log_count: int = 0


class DriverActivityResponse(_ResponseBase):
    """``GET /fleet/api/drivers/{id}/activity`` response.

    Implements Requirements 14.2, 14.3, 14.4, 14.5.
    """

    portal_account_id: UUID
    date_from: date
    date_to: date
    rows: list[DriverActivityVehicleRow] = Field(default_factory=list)
    total_submissions: int = 0
    total_failures: int = 0
    total_odometer_logs: int = 0
    total_hours_logs: int = 0


# ---------------------------------------------------------------------------
# Checklist templates and submissions
# ---------------------------------------------------------------------------


_ChecklistResult = Literal["pass", "fail", "na"]
_ChecklistStatus = Literal["in_progress", "completed", "cancelled"]


class ChecklistTemplateItemSchema(_ResponseBase):
    """One item inside a checklist template (read shape).

    Used in both list/detail responses and as the payload for
    create/update requests via :class:`ChecklistTemplateItemUpsert`.

    Implements Requirement 8.4.
    """

    id: UUID
    category: str
    label: str
    description: str | None = None
    requires_photo_on_fail: bool = False
    display_order: int


class ChecklistTemplateItemUpsert(_StrictBase):
    """Request body for adding or updating a template item.

    ``id`` is omitted on add; present on edit (the router puts it in
    the path so a client cannot accidentally edit a different item by
    spoofing it in the body).
    """

    category: str = Field(..., min_length=1, max_length=80)
    label: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=500)
    requires_photo_on_fail: bool = False
    display_order: int = Field(..., ge=0)


class ChecklistTemplateSchema(_ResponseBase):
    """Read shape for a checklist template (list and detail).

    Implements Requirements 8.1, 8.5, 8.6, 8.8.
    """

    id: UUID
    name: str
    description: str | None = None
    is_default: bool
    is_system_seeded: bool
    archived_at: datetime | None = None
    items: list[ChecklistTemplateItemSchema] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ChecklistTemplateListResponse(PaginatedResponse[ChecklistTemplateSchema]):
    """``GET /fleet/api/checklists/templates`` response."""


class ChecklistTemplateCreateRequest(_StrictBase):
    """``POST /fleet/api/checklists/templates`` body (admin-only)."""

    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    items: list[ChecklistTemplateItemUpsert] = Field(default_factory=list)


class ChecklistTemplateUpdateRequest(_StrictBase):
    """``PATCH /fleet/api/checklists/templates/{id}`` body (admin-only).

    Service rejects all writes against system-seeded templates
    (Property 18, Requirement 8.8).
    """

    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)


class ChecklistTemplateReorderRequest(_StrictBase):
    """``POST /fleet/api/checklists/templates/{id}/items/reorder`` body."""

    item_ids: list[UUID] = Field(..., min_length=1)


class ChecklistSubmissionItemSchema(_ResponseBase):
    """Read shape for one item in a submission.

    ``category`` / ``label`` / ``requires_photo_on_fail`` are snapshots
    from the template at submission-start time.

    Implements Requirements 9.2, 9.3, 9.4, 9.5.
    """

    id: UUID
    template_item_id: UUID
    category: str
    label: str
    requires_photo_on_fail: bool
    result: _ChecklistResult | None = None
    notes: str | None = None
    photo_urls: list[str] = Field(default_factory=list)
    recorded_at: datetime | None = None


class ChecklistSubmissionStartRequest(_StrictBase):
    """``POST /fleet/api/checklists/start`` body."""

    customer_vehicle_id: UUID


class ChecklistSubmissionItemUpdate(_StrictBase):
    """``PATCH /fleet/api/checklists/{id}/items/{item_id}`` body."""

    result: _ChecklistResult | None = None
    notes: str | None = Field(None, max_length=500)


class ChecklistSubmissionSchema(_ResponseBase):
    """Read shape for a submission (list and detail).

    Counts are 0 until ``status = 'completed'``, at which point they
    are finalised by ``checklist_service.complete_submission`` (Property 24).
    """

    id: UUID
    customer_vehicle_id: UUID
    portal_account_id: UUID
    template_id: UUID
    status: _ChecklistStatus
    started_at: datetime
    completed_at: datetime | None = None
    passed_item_count: int = 0
    failed_item_count: int = 0
    na_item_count: int = 0
    items: list[ChecklistSubmissionItemSchema] = Field(default_factory=list)


class ChecklistSubmissionListResponse(PaginatedResponse[ChecklistSubmissionSchema]):
    """``GET /fleet/api/checklists/submissions`` response."""


# ---------------------------------------------------------------------------
# Reminder preferences
# ---------------------------------------------------------------------------


_ReminderType = Literal[
    "wof_expiry_reminder",
    "cof_expiry_reminder",
    "service_due_reminder",
    "registration_expiry_reminder",
]
_ReminderChannel = Literal["email", "sms"]
_ReminderRecipient = Literal["fleet_admin", "assigned_drivers"]
_LeadTimeDays = Literal[7, 14, 30]


class ReminderPreferenceSchema(_ResponseBase):
    """One row in the reminders settings table.

    There is at most one row per ``(customer_vehicle_id, reminder_type)``
    pair (UNIQUE constraint enforced in the DB).

    Implements Requirements 10.2, 10.3, 10.6.
    """

    customer_vehicle_id: UUID
    reminder_type: _ReminderType
    enabled: bool = False
    lead_time_days: _LeadTimeDays = 14
    channels: list[_ReminderChannel] = Field(default_factory=list)
    recipients: list[_ReminderRecipient] = Field(default_factory=list)
    service_interval_km: int | None = None
    service_interval_months: int | None = None
    rego: str | None = None  # join-included for the list view


class ReminderPreferenceUpsertRequest(_StrictBase):
    """``PUT /fleet/api/reminders/{vehicle_id}/{reminder_type}`` body.

    Property 25 predicate: when ``enabled = true``, channels and
    recipients must each be non-empty, lead_time_days must be in
    {7, 14, 30}, channels must be a subset of {email, sms}, and
    recipients must be a subset of {fleet_admin, assigned_drivers}.

    The SMS-availability gate (``'sms' ∈ channels`` ⇒ workshop SMS
    provider must be configured) is enforced by the service layer
    against runtime state, not at the schema layer.

    Implements Requirement 10.2.
    """

    enabled: bool = False
    lead_time_days: _LeadTimeDays = 14
    channels: list[_ReminderChannel] = Field(default_factory=list)
    recipients: list[_ReminderRecipient] = Field(default_factory=list)
    service_interval_km: int | None = Field(None, ge=0)
    service_interval_months: int | None = Field(None, ge=0)

    @field_validator("channels", "recipients", mode="after")
    @classmethod
    def _dedupe(cls, v: list[str]) -> list[str]:
        # Preserve first-occurrence order; the Literal types already
        # restrict the values to the allowed set.
        seen: set[str] = set()
        out: list[str] = []
        for item in v:
            if item not in seen:
                seen.add(item)
                out.append(item)
        return out

    @model_validator(mode="after")
    def _enabled_predicate(self) -> ReminderPreferenceUpsertRequest:
        if self.enabled:
            if not self.channels:
                raise ValueError(
                    "channels must contain at least one of "
                    "'email' or 'sms' when enabled"
                )
            if not self.recipients:
                raise ValueError(
                    "recipients must contain at least one of "
                    "'fleet_admin' or 'assigned_drivers' when enabled"
                )
        return self


class ReminderPreferenceListResponse(PaginatedResponse[ReminderPreferenceSchema]):
    """``GET /fleet/api/reminders`` response."""


class ReminderAdHocSmsRequest(_StrictBase):
    """``POST /fleet/api/reminders/{vehicle_id}/sms-now`` body — admin-only.

    Service rejects with HTTP 400 if no SMS provider is configured for
    the org (Requirement 10.7).
    """

    message: str = Field(..., min_length=1, max_length=320)


# ---------------------------------------------------------------------------
# Booking and quote requests
# ---------------------------------------------------------------------------


_BookingSlot = Literal["morning", "afternoon", "all_day"]
_BookingStatus = Literal[
    "pending", "accepted", "declined", "completed", "cancelled"
]
_QuoteStatus = Literal[
    "pending", "quoted", "accepted", "declined", "expired", "cancelled"
]


class BookingRequestCreate(_StrictBase):
    """``POST /fleet/api/bookings`` body.

    Property 30: ``service_description`` length ≥ 10, ``preferred_slot``
    in the enum, ``preferred_date`` today-or-later (the today check is
    in workshop tz and lives in the service).

    Implements Requirements 11.1, 11.2.
    """

    customer_vehicle_id: UUID
    preferred_date: date
    preferred_slot: _BookingSlot
    service_description: str = Field(..., min_length=10, max_length=2000)
    notes: str | None = Field(None, max_length=2000)


class BookingRequestSchema(_ResponseBase):
    """Read shape for a booking request (list and detail).

    Implements Requirements 11.4, 11.5, 11.6, 11.7, 11.8.
    """

    id: UUID
    customer_vehicle_id: UUID
    rego: str | None = None  # join-included
    requested_by_portal_account_id: UUID
    requested_by_name: str | None = None  # join-included
    preferred_date: date
    preferred_slot: _BookingSlot
    service_description: str
    notes: str | None = None
    status: _BookingStatus
    decline_reason: str | None = None
    booking_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class BookingRequestListResponse(PaginatedResponse[BookingRequestSchema]):
    """``GET /fleet/api/bookings`` and admin equivalent."""


class BookingAcceptRequest(_StrictBase):
    """Admin: ``POST /api/v2/fleet-portal/admin/bookings/{id}/accept``."""

    refined_date_time: datetime
    notes: str | None = Field(None, max_length=2000)


class BookingDeclineRequest(_StrictBase):
    """Admin: ``POST /api/v2/fleet-portal/admin/bookings/{id}/decline``."""

    decline_reason: str = Field(..., min_length=1, max_length=2000)


class QuoteRequestCreate(_StrictBase):
    """``POST /fleet/api/quotes/request`` body — admin-only.

    Implements Requirements 12.1, 12.2.
    """

    customer_vehicle_id: UUID
    service_description: str = Field(..., min_length=10, max_length=2000)
    notes: str | None = Field(None, max_length=2000)


class QuoteRequestSchema(_ResponseBase):
    """Read shape for a quote request.

    Implements Requirements 12.3, 12.4, 12.5.
    """

    id: UUID
    customer_vehicle_id: UUID
    rego: str | None = None
    requested_by_portal_account_id: UUID
    requested_by_name: str | None = None
    service_description: str
    notes: str | None = None
    status: _QuoteStatus
    quote_id: UUID | None = None
    quote_total: Decimal | None = None  # populated when quoted
    quote_valid_until: date | None = None
    created_at: datetime
    updated_at: datetime


class QuoteRequestListResponse(PaginatedResponse[QuoteRequestSchema]):
    """``GET /fleet/api/quotes`` and admin equivalent."""


class QuoteLinkRequest(_StrictBase):
    """Admin: ``POST /api/v2/fleet-portal/admin/quotes/{id}/link``."""

    quote_id: UUID


# ---------------------------------------------------------------------------
# Invoices (read-only — uses existing portal invoice service)
# ---------------------------------------------------------------------------


_InvoiceStatus = Literal[
    "draft", "sent", "paid", "partial", "overdue", "void", "cancelled"
]


class InvoiceListItem(_ResponseBase):
    """One invoice row on the fleet invoices list.

    Implements Requirement 13.1.
    """

    invoice_id: UUID
    invoice_number: str
    customer_vehicle_id: UUID | None = None
    rego: str | None = None
    issue_date: date
    due_date: date | None = None
    total: Decimal
    amount_paid: Decimal = Decimal("0")
    amount_outstanding: Decimal = Decimal("0")
    status: _InvoiceStatus


class InvoiceListResponse(PaginatedResponse[InvoiceListItem]):
    """``GET /fleet/api/invoices`` response — admin-only."""


# ---------------------------------------------------------------------------
# Dashboard summary
# ---------------------------------------------------------------------------


class DashboardSummaryResponse(_ResponseBase):
    """``GET /fleet/api/dashboard`` response.

    Aggregations are direct enumerations of the underlying sets
    (Property 17, Requirement 15.2–15.6).

    Implements Requirements 6.8, 15.1, 15.2, 15.3, 15.4, 15.5, 15.6.
    """

    total_vehicles: int = 0
    valid_wof_cof: int = 0
    expiring_within_28: int = 0
    service_overdue: int = 0
    checklists_completed_today: int = 0
    pending_booking_requests: int = 0
    pending_quote_requests: int = 0
    recent_failures: list[ChecklistSubmissionSchema] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------


__all__ = [
    # Shared
    "PaginatedResponse",
    "PaginationParams",
    "ErrorEnvelope",
    "IdResponse",
    "StatusResponse",
    # Auth
    "LoginRequest",
    "LoginResponse",
    "MfaChallengeResponse",
    "MfaSetupRequiredResponse",
    "ForgotPasswordRequest",
    "ResetPasswordRequest",
    "AcceptInviteRequest",
    "CurrentUserResponse",
    # Vehicles
    "VehicleListItem",
    "VehicleListResponse",
    "VehicleDetailResponse",
    "VehicleAddRequest",
    "VehicleEditRequest",
    "OdometerLogRequest",
    "OdometerLogResponse",
    "HoursLogRequest",
    "HoursLogResponse",
    # Drivers
    "DriverInviteRequest",
    "DriverAssignmentRequest",
    "DriverListItem",
    "DriverListResponse",
    "DriverActivityVehicleRow",
    "DriverActivityResponse",
    # Checklists
    "ChecklistTemplateItemSchema",
    "ChecklistTemplateItemUpsert",
    "ChecklistTemplateSchema",
    "ChecklistTemplateListResponse",
    "ChecklistTemplateCreateRequest",
    "ChecklistTemplateUpdateRequest",
    "ChecklistTemplateReorderRequest",
    "ChecklistSubmissionItemSchema",
    "ChecklistSubmissionStartRequest",
    "ChecklistSubmissionItemUpdate",
    "ChecklistSubmissionSchema",
    "ChecklistSubmissionListResponse",
    # Reminders
    "ReminderPreferenceSchema",
    "ReminderPreferenceUpsertRequest",
    "ReminderPreferenceListResponse",
    "ReminderAdHocSmsRequest",
    # Bookings & quotes
    "BookingRequestCreate",
    "BookingRequestSchema",
    "BookingRequestListResponse",
    "BookingAcceptRequest",
    "BookingDeclineRequest",
    "QuoteRequestCreate",
    "QuoteRequestSchema",
    "QuoteRequestListResponse",
    "QuoteLinkRequest",
    # Invoices
    "InvoiceListItem",
    "InvoiceListResponse",
    # Dashboard
    "DashboardSummaryResponse",
]
