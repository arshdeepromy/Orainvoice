"""Pydantic v2 schemas for the leave engine.

Maps the four ORM models in :mod:`app.modules.leave.models` to inbound
``Create`` / ``Update`` payloads and outbound ``Response`` /
``ListResponse`` envelopes. List shapes follow the project rule
``{ items, total }`` (see ``project-overview.md`` — "All API responses
wrap arrays in objects").

**Validates: Requirements R1, R2, R3, R4 — Staff Management Phase 2**

Notes:
- Pydantic v2 syntax throughout (``Literal`` types, ``field_validator``,
  ``model_validator``, ``model_config = {"from_attributes": True}``).
- Response schemas include service-resolved join fields (e.g.
  ``leave_type_code``, ``staff_name``, ``created_by_email``) that the
  service layer must populate before constructing the response. They
  are typed ``Optional`` because the underlying join may legitimately
  return ``NULL`` (e.g. a ledger row created by a deleted user).
- ``LeaveBalanceResponse.available_hours`` is exposed as a Pydantic v2
  ``computed_field`` so callers always see ``accrued - used - pending``
  consistently regardless of how the service constructs the model.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, computed_field, field_validator

# ---------------------------------------------------------------------------
# Enum-style Literal aliases — kept here so Create/Update/Response stay aligned
# and match the CHECK constraints declared in migration 0205.
# ---------------------------------------------------------------------------

AccrualMethod = Literal[
    "anniversary",
    "fixed_annual",
    "per_period",
    "unaccrued",
    "event_based",
]
AccrualUnit = Literal["hours", "days"]
LeaveRequestStatus = Literal["pending", "approved", "rejected", "cancelled"]
RelationshipToSubject = Literal["close_family", "other"]
LedgerReason = Literal[
    "accrual",
    "request_approved",
    "request_cancelled",
    "adjustment",
    "carry_over",
    "expiry",
]


# ===========================================================================
# Leave type schemas
# ===========================================================================


class LeaveTypeCreate(BaseModel):
    """Inbound payload for ``POST /api/v2/leave/types``.

    ``is_statutory`` is intentionally not accepted on create — only the
    A1 backfill seeds statutory rows; user-created types are always
    custom (``is_statutory=false``).
    """

    code: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    is_paid: bool = True
    accrual_method: AccrualMethod
    accrual_amount: Decimal | None = None
    accrual_unit: AccrualUnit = "hours"
    carry_over_max: Decimal | None = None
    requires_doctor_note: bool = False
    confidential_visibility: bool = False
    active: bool = True
    display_order: int = 0


class LeaveTypeUpdate(BaseModel):
    """Inbound payload for ``PATCH /api/v2/leave/types/:id``.

    All fields optional. ``is_statutory`` is exposed read-only via
    ``model_config = {"from_attributes": True}`` so admin UIs can show
    the statutory flag without being able to mutate it (the service
    layer also blocks delete on statutory rows per R7).
    """

    code: str | None = Field(None, min_length=1, max_length=64)
    name: str | None = Field(None, min_length=1, max_length=128)
    is_paid: bool | None = None
    accrual_method: AccrualMethod | None = None
    accrual_amount: Decimal | None = None
    accrual_unit: AccrualUnit | None = None
    carry_over_max: Decimal | None = None
    requires_doctor_note: bool | None = None
    confidential_visibility: bool | None = None
    active: bool | None = None
    display_order: int | None = None

    model_config = {"from_attributes": True}


class LeaveTypeResponse(BaseModel):
    """Outbound leave type record."""

    id: UUID
    org_id: UUID
    code: str
    name: str
    is_paid: bool
    accrual_method: str
    accrual_amount: Decimal | None = None
    accrual_unit: str
    carry_over_max: Decimal | None = None
    is_statutory: bool
    requires_doctor_note: bool
    confidential_visibility: bool
    active: bool
    display_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LeaveTypeListResponse(BaseModel):
    """Wrapper per project rule: arrays go in ``{ items, total }``."""

    items: list[LeaveTypeResponse]
    total: int


# ===========================================================================
# Leave balance schemas
# ===========================================================================


class LeaveBalanceResponse(BaseModel):
    """Per-staff × per-leave-type rolling balance.

    ``leave_type_code`` and ``leave_type_name`` are populated by the
    service via a JOIN to ``leave_types`` so the UI can render the
    balance card without an extra round-trip. ``available_hours`` is a
    computed field — always ``accrued - used - pending``.
    """

    id: UUID
    leave_type_id: UUID
    leave_type_code: str | None = None
    leave_type_name: str | None = None
    accrued_hours: Decimal
    used_hours: Decimal
    pending_hours: Decimal
    anniversary_date: date | None = None
    last_accrual_at: datetime | None = None
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def available_hours(self) -> Decimal:
        return self.accrued_hours - self.used_hours - self.pending_hours

    model_config = {"from_attributes": True}


class LeaveBalanceListResponse(BaseModel):
    items: list[LeaveBalanceResponse]
    total: int


# ===========================================================================
# Leave request schemas
# ===========================================================================


class LeaveRequestCreate(BaseModel):
    """Inbound payload for ``POST /api/v2/staff/:id/leave/requests``.

    Bereavement-specific validation (``relationship_to_subject``
    required when ``leave_type.code='bereavement'``) and partial-day
    validation live in :mod:`app.modules.leave.service` — this schema
    only enforces shape and basic value constraints.
    """

    leave_type_id: UUID
    start_date: date
    end_date: date
    hours_requested: Decimal = Field(..., gt=0)
    reason: str | None = None
    relationship_to_subject: RelationshipToSubject | None = None
    partial_day_start_time: time | None = None
    attachment_upload_id: UUID | None = None

    @field_validator("end_date")
    @classmethod
    def _end_after_start(cls, v: date, info) -> date:  # type: ignore[no-untyped-def]
        start = info.data.get("start_date")
        if start is not None and v < start:
            raise ValueError("end_date must be on or after start_date")
        return v


class LeaveRequestDecisionRequest(BaseModel):
    """Body for approve / reject endpoints.

    ``decision_notes`` is optional — the approver can decide without a
    note (the service still writes an audit row). For confidential
    leave types, the service redacts ``decision_notes`` from the audit
    payload per design §4.3.1.
    """

    decision_notes: str | None = None


class LeaveRequestResponse(BaseModel):
    """Outbound leave request record.

    ``staff_name``, ``leave_type_code``, ``leave_type_name``, and
    ``requested_by_name`` are resolved by the service via JOIN and may
    legitimately be ``None`` (e.g. a request whose submitting user has
    been deleted).
    """

    id: UUID
    org_id: UUID
    staff_id: UUID
    staff_name: str | None = None
    leave_type_id: UUID
    leave_type_code: str | None = None
    leave_type_name: str | None = None
    start_date: date
    end_date: date
    hours_requested: Decimal
    status: str
    reason: str | None = None
    relationship_to_subject: str | None = None
    partial_day_start_time: time | None = None
    attachment_upload_id: UUID | None = None
    requested_by: UUID
    requested_by_name: str | None = None
    decided_by: UUID | None = None
    decided_at: datetime | None = None
    decision_notes: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LeaveRequestListResponse(BaseModel):
    items: list[LeaveRequestResponse]
    total: int


# ===========================================================================
# Leave ledger schemas
# ===========================================================================


class LeaveLedgerResponse(BaseModel):
    """One row of the append-only leave ledger.

    Per P2-N10, ``request_relationship_to_subject`` is surfaced via JOIN
    to ``leave_requests.relationship_to_subject`` when ``request_id``
    is non-null and the leave type is per-event (e.g. bereavement).
    ``created_by_email`` is resolved via JOIN to ``users.email``.
    """

    id: UUID
    leave_type_id: UUID
    leave_type_code: str | None = None
    delta_hours: Decimal
    reason: str
    request_id: UUID | None = None
    request_relationship_to_subject: str | None = None
    occurred_at: date
    created_at: datetime
    created_by: UUID | None = None
    created_by_email: str | None = None

    model_config = {"from_attributes": True}


class LeaveLedgerListResponse(BaseModel):
    items: list[LeaveLedgerResponse]
    total: int


# ===========================================================================
# Manual balance adjustment (admin)
# ===========================================================================


class AdjustBalanceRequest(BaseModel):
    """Body for ``POST /api/v2/staff/:id/leave/balances/:type_id/adjust``.

    ``reason`` is a short label persisted on the ledger row's free-text
    ``reason`` column (the enum slot is always ``adjustment``).
    ``notes`` is a longer justification surfaced in the audit log.
    """

    staff_id: UUID
    leave_type_id: UUID
    delta_hours: Decimal
    reason: str = Field(..., min_length=1, max_length=128)
    notes: str | None = None
