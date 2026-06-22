"""Pydantic v2 schemas for the time-clock + scheduling-ops surface.

Maps the six ORM models in :mod:`app.modules.time_clock.models` to
inbound ``Create`` / ``Update`` / action payloads and outbound
``Response`` / ``ListResponse`` envelopes. List shapes follow the
project rule ``{ items, total }`` (see ``project-overview.md`` — "All
API responses wrap arrays in objects").

**Validates: Requirements R1, R3, R4, R5, R6, R6a, R7, R9, R10, R11,
R12, R13, R14, R14a, R14b — Staff Management Phase 3**

Notes:
- Pydantic v2 syntax throughout (``Literal`` types, ``Field(...)``,
  ``model_config = {"from_attributes": True}``).
- Photo identifier is ``photo_file_key`` everywhere (per P3-N1) — the
  string returned as ``file_key`` from ``POST /api/v2/uploads/clock-photos``.
- Source enums + status enums mirror the DB-level CHECK constraints
  declared in migration 0207 (the canonical list lives in
  :mod:`app.modules.time_clock.models` as ``Literal`` aliases — they
  are re-imported here for symmetry).
- Response schemas with service-resolved JOIN fields (e.g.
  ``staff_name``, ``leave_type_code``) declare those fields as
  ``Optional`` because the JOIN may legitimately return ``None``
  (e.g. a row created by a since-deleted user).
- ``ClockInPolicyResponse`` and ``OvertimePolicyResponse`` mirror the
  JSONB defaults on ``organisations.clock_in_policy`` /
  ``organisations.overtime_policy`` (migration 0207). All keys default
  to the documented defaults so the GET endpoints can return a
  populated object even when the JSONB field is empty / partially
  set.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enum-style Literal aliases — kept here so Create/Update/Response stay
# aligned with the DB-side CHECK constraints in migration 0207 + the
# matching aliases on :mod:`app.modules.time_clock.models`.
# ---------------------------------------------------------------------------

TimeClockSource = Literal[
    "kiosk", "self_service_mobile", "self_service_web", "admin_manual",
]
BreakType = Literal["rest_paid", "meal_unpaid"]
TimesheetStatus = Literal[
    "pending", "approved", "rejected", "edited_after_approval",
]
ToilChoice = Literal["pay_cash", "toil"]
OvertimeStatus = Literal["pending", "approved", "rejected"]
# G8 — 'awaiting_manager' is the new state when manager approval is
# required by clock_in_policy.shift_swap_requires_manager_approval.
ShiftSwapStatus = Literal[
    "pending", "awaiting_manager", "accepted", "rejected", "cancelled",
]
ShiftCoverStatus = Literal["open", "accepted", "cancelled", "expired"]
ClockAction = Literal["in", "out"]
DefaultChannel = Literal["kiosk_only", "kiosk_and_self_service"]


# ===========================================================================
# Time clock entry schemas (R1, R5, R8)
# ===========================================================================


class TimeClockEntryCreate(BaseModel):
    """Inbound payload for ``POST /api/v2/staff/:id/clock/manual``.

    Admin-manual entry path (R5). ``source`` defaults to
    ``'admin_manual'`` and is the only value the manual create flow
    sets — kiosk + self-service entries are created via their
    dedicated action endpoints (see :class:`KioskClockActionRequest`
    and :class:`SelfServiceClockActionRequest`).
    """

    staff_id: UUID
    clock_in_at: datetime
    clock_out_at: datetime | None = None
    source: TimeClockSource = "admin_manual"
    clock_in_photo_url: str | None = None
    clock_out_photo_url: str | None = None
    clock_in_lat: Decimal | None = None
    clock_in_lng: Decimal | None = None
    clock_out_lat: Decimal | None = None
    clock_out_lng: Decimal | None = None
    scheduled_entry_id: UUID | None = None
    break_minutes: int = Field(default=0, ge=0)
    notes: str | None = None


class TimeClockEntryUpdate(BaseModel):
    """Inbound payload for ``PATCH /api/v2/staff/:id/clock/manual/:entry_id``.

    All fields optional — admin can fix individual columns (e.g. just
    ``clock_out_at`` on a forgotten clock-out). The service refuses
    edits when the entry falls inside an approved week (per R9 lock
    check) — this schema only enforces shape.
    """

    clock_in_at: datetime | None = None
    clock_out_at: datetime | None = None
    clock_in_photo_url: str | None = None
    clock_out_photo_url: str | None = None
    clock_in_lat: Decimal | None = None
    clock_in_lng: Decimal | None = None
    clock_out_lat: Decimal | None = None
    clock_out_lng: Decimal | None = None
    scheduled_entry_id: UUID | None = None
    break_minutes: int | None = Field(default=None, ge=0)
    notes: str | None = None


class TimeClockEntryResponse(BaseModel):
    """Outbound time-clock entry record.

    Photo URLs are masked to ``None`` by the service serializer for
    callers below the ``location_manager`` role (G10 — buddy-punch
    photos are RBAC-gated). The schema accepts ``None`` regardless so
    no extra branching is needed downstream.

    The ``flags`` JSONB is exposed as a free-form dict; the frontend
    typed model declares the keys it cares about
    (``flagged_for_review``, ``review_reason``, ``flagged_by``).
    """

    id: UUID
    org_id: UUID
    staff_id: UUID
    staff_name: str | None = None
    clock_in_at: datetime
    clock_out_at: datetime | None = None
    source: str
    clock_in_photo_url: str | None = None
    clock_out_photo_url: str | None = None
    clock_in_lat: Decimal | None = None
    clock_in_lng: Decimal | None = None
    clock_out_lat: Decimal | None = None
    clock_out_lng: Decimal | None = None
    scheduled_entry_id: UUID | None = None
    break_minutes: int = 0
    notes: str | None = None
    created_by: UUID | None = None
    worked_minutes: int | None = None
    flags: dict = Field(default_factory=dict)
    created_at: datetime

    model_config = {"from_attributes": True}


class TimeClockEntryListResponse(BaseModel):
    """Wrapper per project rule: arrays go in ``{ items, total }``."""

    items: list[TimeClockEntryResponse]
    total: int


# ===========================================================================
# Currently-clocked-in dashboard schemas (admin visibility)
# ===========================================================================


class ClockedInStaffEntry(BaseModel):
    """One row in the "who is currently on the clock" admin dashboard.

    Surfaces only the fields the dashboard needs (staff identity +
    clock-in start time + the open ``time_clock_entries`` row id) so
    callers can render a live "elapsed" timer (computed client-side
    from ``clock_in_at`` so no per-second polling is required) and
    issue a manual clock-out via
    ``POST /api/v2/staff/:id/clock/admin-clock-out/:entry_id``.

    Excludes photos, notes, and break records — those live on the
    main timesheet view, not the realtime dashboard.
    """

    time_clock_entry_id: UUID
    staff_id: UUID
    staff_name: str
    employee_id: str | None = None
    position: str | None = None
    on_file_photo_url: str | None = None
    clock_in_at: datetime
    source: str
    break_minutes: int = 0


class ClockedInStaffListResponse(BaseModel):
    """Wrapper per project rule: arrays go in ``{ items, total }``."""

    items: list[ClockedInStaffEntry]
    total: int


class AdminClockOutRequest(BaseModel):
    """Body for ``POST /api/v2/staff/:id/clock/admin-clock-out/:entry_id``.

    Admin-initiated forced clock-out. The reason note is REQUIRED for
    record-keeping — the audit row carries the staff id and reason
    inside ``after_value`` so post-hoc review can answer "who closed
    this and why".
    """

    reason_note: str = Field(min_length=3, max_length=500)
    clock_out_at: datetime | None = Field(
        default=None,
        description=(
            "Optional explicit clock-out timestamp. Defaults to now() when "
            "omitted — the common case. Override only for back-dated edits "
            "(e.g. closing a Friday shift on Monday morning)."
        ),
    )


# ===========================================================================
# Break record schemas (R2, R7)
# ===========================================================================


class BreakRecordCreate(BaseModel):
    """Inbound payload for ``POST /api/v2/staff/:id/clock/break-start``.

    The parent ``time_clock_entry_id`` is required — the service
    looks up the open entry for the staff to validate the FK belongs
    to them. ``start_at`` defaults to ``now()`` server-side when
    omitted (the service applies the default; the schema leaves it
    optional so the client can override for back-dated admin edits).
    """

    time_clock_entry_id: UUID
    break_type: BreakType
    start_at: datetime | None = None


class BreakRecordResponse(BaseModel):
    """Outbound break-record row.

    ``minutes`` is populated on break-end (``minutes = (end_at -
    start_at) / 60``). For ``break_type='meal_unpaid'`` rows the
    parent ``TimeClockEntry.break_minutes`` aggregator is bumped by
    this value — see :mod:`app.modules.time_clock.breaks`.
    """

    id: UUID
    org_id: UUID
    time_clock_entry_id: UUID
    break_type: str
    start_at: datetime
    end_at: datetime | None = None
    minutes: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ===========================================================================
# Kiosk schemas (R3)
# ===========================================================================


class KioskLookupRequest(BaseModel):
    """Body for ``POST /api/v1/kiosk/clock/lookup``.

    The kiosk tablet sends the staff's ``employee_id`` (the human
    code printed on lanyards / locker tags). The service hashes it
    via SHA-256 before any Redis / audit writes (G12) so the raw
    code never appears in logs or scans.
    """

    employee_id: str = Field(..., min_length=1, max_length=64)


class KioskLookupResponse(BaseModel):
    """Body returned by ``POST /api/v1/kiosk/clock/lookup``.

    ``on_file_photo_url`` is the staff's stored on-file photo
    (Phase 1 R2) shown side-by-side with the just-taken photo on
    the confirmation screen (R3.9, G10).
    """

    staff_id: UUID
    first_name: str
    on_file_photo_url: str | None = None
    currently_clocked_in: bool


class KioskClockActionRequest(BaseModel):
    """Body for ``POST /api/v1/kiosk/clock/action``.

    ``photo_file_key`` is the string returned as ``file_key`` from a
    prior ``POST /api/v2/uploads/clock-photos`` (P3-N1 — note the
    rename from earlier-draft ``photo_upload_id``). The endpoint
    refuses with 422 ``photo_required`` when missing — see R3.5.
    """

    staff_id: UUID
    action: ClockAction
    photo_file_key: str = Field(..., min_length=1)
    lat: Decimal | None = None
    lng: Decimal | None = None


class KioskClockActionResponse(BaseModel):
    """Body returned by ``POST /api/v1/kiosk/clock/action``.

    On clock-in the response surfaces the freshly-created entry's id
    + the on-file/just-taken photo URLs for the side-by-side
    confirmation screen (R3.9). On clock-out the ``worked_minutes``
    field is populated.
    """

    time_clock_entry_id: UUID
    action: ClockAction
    clock_in_at: datetime
    clock_out_at: datetime | None = None
    worked_minutes: int | None = None
    on_file_photo_url: str | None = None
    just_taken_photo_url: str | None = None


# ===========================================================================
# Self-service schemas (R4)
# ===========================================================================


class SelfServiceClockActionRequest(BaseModel):
    """Body for ``POST /api/v2/staff/me/clock-action``.

    ``photo_file_key`` is the string returned by
    ``POST /api/v2/uploads/clock-photos`` (P3-N1). The endpoint
    refuses with 403 ``self_service_disabled`` when the staff
    record's ``self_service_clock_enabled=false`` (R4.2).

    ``source`` is set server-side from the request user-agent
    (``self_service_mobile`` vs ``self_service_web``) — clients do
    not provide it.
    """

    action: ClockAction
    photo_file_key: str | None = None
    lat: Decimal | None = None
    lng: Decimal | None = None


class SelfServiceClockActionResponse(BaseModel):
    """Body returned by ``POST /api/v2/staff/me/clock-action``."""

    time_clock_entry_id: UUID
    action: ClockAction
    source: str
    clock_in_at: datetime
    clock_out_at: datetime | None = None
    worked_minutes: int | None = None


# ===========================================================================
# Timesheet approval schemas (R9, R11)
# ===========================================================================


class TimesheetApprovalRequest(BaseModel):
    """Body for ``POST /api/v2/staff/:id/timesheets/:week_start/approve``.

    ``toil_choice`` is required when the org's ``overtime_handling``
    setting is ``'employee_chooses'`` (R11.2) — the service raises
    422 when omitted in that mode. ``acknowledge_flagged`` is
    required (must be ``true``) when the week contains any entries
    with ``flags.flagged_for_review=true`` (G10) — the service
    raises 422 ``flagged_acknowledgement_required`` otherwise so
    the modal in the admin UI forces an explicit tick.
    """

    toil_choice: ToilChoice | None = None
    notes: str | None = None
    acknowledge_flagged: bool = False


class TimesheetApprovalResponse(BaseModel):
    """Outbound timesheet approval row.

    ``staff_name`` and ``approved_by_email`` are resolved by the
    service via JOIN so the admin UI can render the approval banner
    without an extra round-trip. Both may legitimately be ``None``.
    """

    id: UUID
    org_id: UUID
    staff_id: UUID
    staff_name: str | None = None
    week_start: date
    week_end: date
    status: str
    total_worked_minutes: int | None = None
    total_scheduled_minutes: int | None = None
    total_overtime_minutes: int = 0
    total_break_minutes: int = 0
    ordinary_minutes: int = 0
    public_holiday_minutes: int = 0
    toil_choice: str | None = None
    approved_by: UUID | None = None
    approved_by_email: str | None = None
    approved_at: datetime | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TimesheetApprovalListResponse(BaseModel):
    items: list[TimesheetApprovalResponse]
    total: int


# ===========================================================================
# Overtime request schemas (R10)
# ===========================================================================


class OvertimeRequestCreate(BaseModel):
    """Inbound payload for ``POST /api/v2/overtime-requests``.

    Either staff or admin can submit. When staff submits,
    ``staff_id`` defaults to the caller's own staff record (the
    service resolves it). When admin submits on behalf of someone,
    ``staff_id`` is provided explicitly.
    """

    staff_id: UUID | None = None
    schedule_entry_id: UUID | None = None
    proposed_extra_minutes: int = Field(..., gt=0, le=1440)
    reason: str | None = None


class OvertimeRequestDecisionRequest(BaseModel):
    """Body for ``POST /api/v2/overtime-requests/:id/approve|reject``.

    Optional ``decision_notes`` — the approver may decide without a
    note. The service still writes an audit row.
    """

    decision_notes: str | None = None


class OvertimeRequestResponse(BaseModel):
    """Outbound overtime-request record.

    ``staff_name`` / ``requested_by_name`` / ``decided_by_name`` are
    resolved by the service via JOIN.
    """

    id: UUID
    org_id: UUID
    staff_id: UUID
    staff_name: str | None = None
    schedule_entry_id: UUID | None = None
    proposed_extra_minutes: int
    reason: str | None = None
    requested_by: UUID
    requested_by_name: str | None = None
    status: str
    decided_by: UUID | None = None
    decided_by_name: str | None = None
    decided_at: datetime | None = None
    decision_notes: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class OvertimeRequestListResponse(BaseModel):
    items: list[OvertimeRequestResponse]
    total: int


# ===========================================================================
# Shift swap schemas (R12)
# ===========================================================================


class ShiftSwapCreate(BaseModel):
    """Inbound payload for ``POST /api/v2/shift-swaps``.

    ``target_staff_id`` is optional — when ``None`` the swap is
    "open" (any eligible staff can claim). Currently Phase 3 only
    supports targeted swaps in the workflow described in design §4.8;
    the column is nullable for forward compatibility.
    """

    target_staff_id: UUID | None = None
    schedule_entry_id: UUID
    reason: str | None = None


class ShiftSwapResponse(BaseModel):
    """Outbound shift-swap record.

    ``status`` is one of the 5-state machine values (G8 —
    ``awaiting_manager`` is the new state). Service-resolved JOIN
    fields (``requester_name``, ``target_name``, ``decided_by_name``)
    let the swap-list UI render names without an extra round-trip.
    """

    id: UUID
    org_id: UUID
    requester_staff_id: UUID
    requester_name: str | None = None
    target_staff_id: UUID | None = None
    target_name: str | None = None
    schedule_entry_id: UUID
    status: str
    reason: str | None = None
    decided_by: UUID | None = None
    decided_by_name: str | None = None
    created_at: datetime
    decided_at: datetime | None = None

    model_config = {"from_attributes": True}


class ShiftSwapListResponse(BaseModel):
    items: list[ShiftSwapResponse]
    total: int


# ===========================================================================
# Shift cover schemas (R13)
# ===========================================================================


class ShiftCoverCreate(BaseModel):
    """Inbound payload for ``POST /api/v2/shift-cover``.

    ``expires_at`` defaults to ``broadcast_at + 8 hours`` server-side
    when omitted (the service applies the default).
    """

    schedule_entry_id: UUID
    expires_at: datetime | None = None


class ShiftCoverResponse(BaseModel):
    """Outbound shift-cover record."""

    id: UUID
    org_id: UUID
    schedule_entry_id: UUID
    requester_staff_id: UUID
    requester_name: str | None = None
    status: str
    accepted_by: UUID | None = None
    accepted_by_name: str | None = None
    broadcast_at: datetime
    expires_at: datetime | None = None
    accepted_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ShiftCoverListResponse(BaseModel):
    items: list[ShiftCoverResponse]
    total: int


# ===========================================================================
# Running-late schemas (R14b, G3)
# ===========================================================================


class RunningLateRequest(BaseModel):
    """Body for ``POST /api/v2/staff/me/running-late``.

    ``minutes_late`` is bounded ``[1, 180]`` per R14b.1.
    ``reason`` is capped at 200 chars to fit a single SMS segment
    when concatenated with the standard prefix template.
    """

    minutes_late: int = Field(..., ge=1, le=180)
    reason: str | None = Field(default=None, max_length=200)


class RunningLateResponse(BaseModel):
    """Body returned by ``POST /api/v2/staff/me/running-late``.

    ``snoozed_until`` is the timestamp until which the
    ``check_late_arrivals`` task will skip this shift's automated
    alert (R14b.4 — Redis ``late:{shift_id}`` key TTL =
    ``minutes_late + 30`` minutes).
    """

    ok: bool
    snoozed_until: datetime


# ===========================================================================
# Flag-for-review schema (R8, G10)
# ===========================================================================


class FlagForReviewRequest(BaseModel):
    """Body for ``POST /api/v2/staff/:id/clock-entries/:entry_id/flag``.

    ``reason`` is optional free-text persisted in
    ``time_clock_entries.flags->>'review_reason'``. The flag-set
    action is RBAC-gated (org_admin / branch_admin /
    location_manager) — enforced by the router, not the schema.
    """

    reason: str | None = Field(default=None, max_length=500)


# ===========================================================================
# Org-level policy response schemas (R6, R6a)
# ===========================================================================


class ClockInPolicyResponse(BaseModel):
    """Outbound shape of ``organisations.clock_in_policy`` JSONB.

    Mirrors the migration-0207 default block. Defaults are
    documented in R6.1 + the ``shift_swap_requires_manager_approval``
    addition in R12.2 (G8). All keys carry the documented default so
    the GET endpoint can return a populated object even when the
    JSONB is empty / partially set.
    """

    default_channel: DefaultChannel = "kiosk_only"
    self_service_require_photo: bool = True
    self_service_require_geofence: bool = False
    branch_radius_metres: int = 200
    allow_late_clock_out_edits: bool = True
    kiosk_employee_id_rate_limit: int = 10
    shift_swap_requires_manager_approval: bool = False


class OvertimePolicyResponse(BaseModel):
    """Outbound shape of ``organisations.overtime_policy`` JSONB (G1).

    Mirrors the migration-0207 default block. ``weekly_threshold_minutes``
    default ``2400`` = 40h; ``daily_threshold_minutes`` default ``480``
    = 8h. The cash-vs-TOIL handling lives on the typed
    ``organisations.overtime_handling`` column (Phase 2 P2-N5) — not
    repeated here per P3-N4.
    """

    weekly_threshold_minutes: int = 2400
    daily_threshold_minutes: int = 480
    require_pre_approval: bool = False


# ===========================================================================
# Admin assign of an open cover request (Open Shifts page)
# ===========================================================================


class ShiftCoverAssignRequest(BaseModel):
    """Admin/manager assigns an open cover request to a specific staff member.

    The chosen staff member must be eligible (active, has employee_id or
    user_id, is not the requester) and must have no conflicting shift in the
    cover window — re-checked server-side at assign time.
    """

    staff_id: UUID


class EligibleStaffItem(BaseModel):
    """A staff member who can be assigned an open cover (no time conflict)."""

    id: UUID
    name: str
    position: str | None = None


class EligibleStaffListResponse(BaseModel):
    items: list[EligibleStaffItem]
    total: int
