"""Leave-request workflow service.

Implements the full request lifecycle described in the Phase 2 design
document (§4.3) plus the supporting balance / ledger / list helpers
called from the router. All write paths follow the project's standard
"flush + refresh" pattern (P1-N15) and route audit-log writes through
:func:`app.core.audit.write_audit_log`.

Key invariants enforced here:

- **Bereavement gate (R4.7 / G1).** ``relationship_to_subject`` is
  required on submit, and the per-event cap (3 working days for
  ``close_family``, 1 working day for ``other``) is enforced server
  side. The balance check is skipped because bereavement is
  ``event_based``.
- **TOIL Phase 2 guard (R4.8 / G6).** Even though the ``toil`` leave
  type is ``event_based`` (no accrual job in Phase 2), the service
  refuses to let the staff drop below zero. P3's overtime-toil flow
  will accrue hours; until then the balance is whatever a manager has
  manually adjusted in.
- **Confidential-leave audit redaction (P2-N6).** When the underlying
  leave type has ``confidential_visibility=true`` (i.e.
  ``family_violence``), the ``after_value`` payloads written to the
  audit log strip ``reason``, ``decision_notes``,
  ``relationship_to_subject``, and ``attachment_upload_id`` so the
  audit row never leaks the confidential text. Non-confidential types
  write the full payload — existing behaviour.
- **Confidential-leave permission check (R4.6 / G2).** Approve / reject /
  cancel of a confidential leave request require the actor to hold the
  ``leave.fv_view`` permission via ``user_permission_overrides`` (the
  RBAC middleware already loads these into
  ``request.state.permission_overrides``).
- **Append-only ledger.** The service NEVER updates or deletes
  ``leave_ledger`` rows; corrections write a new compensating row.

**Validates: Requirements R1–R4, R12 — Staff Management Phase 2 task B3**
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any, TYPE_CHECKING

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.auth.rbac import has_permission
from app.modules.leave.models import (
    LeaveBalance,
    LeaveLedger,
    LeaveRequest,
    LeaveType,
)
from app.modules.leave.visibility import (
    FV_LEAVE_VIEW_PERMISSION,
    _apply_confidential_filter,
)
from app.modules.scheduling_v2.models import ScheduleEntry
from app.modules.staff.models import StaffMember

if TYPE_CHECKING:
    from fastapi import Request


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Service-layer exceptions
# ---------------------------------------------------------------------------


class LeaveServiceError(Exception):
    """Base for all leave-service errors. Routers translate to HTTP."""


class InsufficientLeaveError(LeaveServiceError):
    """Raised when a non-event-based, non-unaccrued request would push the
    balance negative (``hours_requested > accrued - used - pending``).
    The router maps this to HTTP 422 ``insufficient_balance``.
    """

    def __init__(self, available: Decimal) -> None:
        self.available = available
        super().__init__(
            f"insufficient_balance: only {available} hours available",
        )


class InsufficientToilBalanceError(LeaveServiceError):
    """Phase 2 TOIL guard (R4.8). Even though ``toil`` is ``event_based``,
    the service refuses requests that would push the staff below zero
    hours. Router maps this to HTTP 422 ``insufficient_toil_balance``
    with the available figure attached.
    """

    def __init__(self, available: Decimal) -> None:
        self.available = available
        super().__init__(
            f"insufficient_toil_balance: only {available} TOIL hours available",
        )


class BereavementValidationError(LeaveServiceError):
    """Raised when a bereavement request is submitted without
    ``relationship_to_subject`` (or with an invalid value). Router
    returns HTTP 422 ``relationship_required``.
    """

    def __init__(self, field: str = "relationship_to_subject") -> None:
        self.field = field
        super().__init__(f"{field}: required for bereavement leave")


class BereavementCapExceededError(LeaveServiceError):
    """Raised when ``hours_requested`` exceeds the per-event cap
    (3 working days for close family, 1 working day for other).
    Router returns HTTP 422 ``bereavement_cap_exceeded`` with the cap.
    """

    def __init__(self, cap_hours: Decimal) -> None:
        self.cap_hours = cap_hours
        super().__init__(
            f"bereavement_cap_exceeded: max {cap_hours} hours per event",
        )


class LeavePermissionDenied(LeaveServiceError):
    """Raised when an actor lacks ``leave.fv_view`` for a confidential
    leave request. Router returns HTTP 403 with the reason payload.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Leave-type accrual methods that don't track a running balance — submits
# for these types skip the available-hours check and don't increment
# ``pending_hours``.
_NON_BALANCE_METHODS: frozenset[str] = frozenset({"event_based", "unaccrued"})

# Set of free-text / payload keys redacted from audit ``after_value``
# dicts when the leave type is ``confidential_visibility=true``.
_CONFIDENTIAL_REDACTED_KEYS: frozenset[str] = frozenset(
    {
        "reason",
        "decision_notes",
        "relationship_to_subject",
        "attachment_upload_id",
    }
)


def _std_daily_hours(staff: StaffMember) -> Decimal:
    """Working-day hours for a staff member. Defaults to 8h when the
    staff record's ``standard_hours_per_week`` is NULL — matches the
    fallback used by the accrual engine (design §4.1.1).
    """
    if staff.standard_hours_per_week:
        return (Decimal(staff.standard_hours_per_week) / Decimal(5)).quantize(
            Decimal("0.01")
        )
    return Decimal("8.00")


def _audit_after_value(
    *,
    leave_type: LeaveType,
    request: LeaveRequest,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct the ``after_value`` dict for an audit log entry, redacting
    the four confidential keys when the leave type is marked confidential.

    Per design §4.3.1, confidential leave types (currently only
    ``family_violence``) MUST NOT leak ``reason``, ``decision_notes``,
    ``relationship_to_subject``, or ``attachment_upload_id`` through
    audit rows. This helper centralises the rule so the lint test in
    ``tests/unit/test_leave_audit_redaction.py`` can verify all call
    sites in one place.
    """
    base: dict[str, Any] = {
        "leave_request_id": str(request.id),
        "staff_id": str(request.staff_id),
        "leave_type_code": leave_type.code,
        "start_date": request.start_date.isoformat(),
        "end_date": request.end_date.isoformat(),
        "hours_requested": str(request.hours_requested),
        "status": request.status,
    }

    if leave_type.confidential_visibility:
        # Strip any redacted keys an extra dict tries to add; never
        # include the four confidential fields from the request itself.
        if extra:
            for k, v in extra.items():
                if k not in _CONFIDENTIAL_REDACTED_KEYS:
                    base[k] = v
        return base

    # Non-confidential types: include the full payload.
    base["reason"] = request.reason
    base["relationship_to_subject"] = request.relationship_to_subject
    base["attachment_upload_id"] = (
        str(request.attachment_upload_id)
        if request.attachment_upload_id
        else None
    )
    base["decision_notes"] = request.decision_notes
    if extra:
        base.update(extra)
    return base


def _check_confidential_permission(
    request: "Request",
    leave_type: LeaveType,
    user_id: uuid.UUID,
    user_role: str,
    staff_user_id: uuid.UUID | None,
) -> None:
    """Enforce R4.6 / G2 on approve / reject / cancel for confidential
    leave types.

    The actor passes the gate when:
      - the leave type is non-confidential, OR
      - the actor is the request's subject (staff.user_id == user_id), OR
      - the actor holds ``leave.fv_view`` via permission overrides.

    Otherwise raise :class:`LeavePermissionDenied`.
    """
    if not leave_type.confidential_visibility:
        return

    # Subject branch — staff cancelling / managing their own request.
    if staff_user_id is not None and staff_user_id == user_id:
        return

    overrides = getattr(request.state, "permission_overrides", None) or []
    if has_permission(user_role, FV_LEAVE_VIEW_PERMISSION, overrides=overrides):
        return

    raise LeavePermissionDenied("fv_leave_no_approval_permission")


async def _load_request_for_decision(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    request_id: uuid.UUID,
) -> tuple[LeaveRequest, LeaveType, StaffMember, LeaveBalance]:
    """Load the request + leave_type + staff + balance row, FOR UPDATE.

    Returns a 4-tuple. Raises :class:`LeaveServiceError` when the row
    is missing or in the wrong tenant.
    """
    result = await db.execute(
        select(LeaveRequest)
        .where(LeaveRequest.id == request_id, LeaveRequest.org_id == org_id)
        .with_for_update()
    )
    leave_request: LeaveRequest | None = result.scalar_one_or_none()
    if leave_request is None:
        raise LeaveServiceError("leave_request_not_found")

    leave_type = await db.get(LeaveType, leave_request.leave_type_id)
    if leave_type is None:
        raise LeaveServiceError("leave_type_not_found")

    staff = await db.get(StaffMember, leave_request.staff_id)
    if staff is None:
        raise LeaveServiceError("staff_not_found")

    bal_result = await db.execute(
        select(LeaveBalance).where(
            LeaveBalance.staff_id == leave_request.staff_id,
            LeaveBalance.leave_type_id == leave_request.leave_type_id,
        )
    )
    balance: LeaveBalance | None = bal_result.scalar_one_or_none()
    if balance is None:
        # Should never happen — the migration backfills a balance row
        # for every staff × type pair. Fail loud rather than silently
        # creating one mid-decision.
        raise LeaveServiceError("leave_balance_not_found")

    return leave_request, leave_type, staff, balance


# ---------------------------------------------------------------------------
# Decision notifications (E1 + E2)
# ---------------------------------------------------------------------------


def _format_decision_email_body(
    *,
    leave_type: LeaveType,
    leave_request: LeaveRequest,
    decision: str,
    staff_first_name: str | None,
) -> tuple[str, str]:
    """Render the (text_body, html_body) pair for an approval/rejection email.

    For confidential leave types (``confidential_visibility=true``), the
    body is intentionally generic — it never includes the ``reason``,
    ``relationship_to_subject``, or ``decision_notes`` fields. Per design
    §4.3.1 the same redaction rule applied to audit rows applies to the
    notification surface area.
    """
    greeting_name = (staff_first_name or "team member").strip() or "team member"

    if leave_type.confidential_visibility:
        text = (
            f"Hi {greeting_name},\n\n"
            f"Your confidential leave request has been {decision}. "
            "Please log in to OraInvoice to view details.\n"
        )
        html = (
            f"<p>Hi {greeting_name},</p>"
            f"<p>Your confidential leave request has been "
            f"<strong>{decision}</strong>.</p>"
            f"<p>Please log in to OraInvoice to view details.</p>"
        )
        return text, html

    # Non-confidential — include date range, hours, decision notes.
    date_range = (
        leave_request.start_date.isoformat()
        if leave_request.start_date == leave_request.end_date
        else f"{leave_request.start_date.isoformat()} – "
             f"{leave_request.end_date.isoformat()}"
    )
    hours = str(leave_request.hours_requested)
    notes_block = ""
    if leave_request.decision_notes:
        notes_block = f"\n\nNotes from your manager:\n{leave_request.decision_notes}"

    text = (
        f"Hi {greeting_name},\n\n"
        f"Your {leave_type.name} leave request has been {decision}.\n\n"
        f"Dates: {date_range}\n"
        f"Hours: {hours}{notes_block}\n"
    )
    html_notes = (
        f"<p><strong>Notes from your manager:</strong> "
        f"{leave_request.decision_notes}</p>"
        if leave_request.decision_notes
        else ""
    )
    html = (
        f"<p>Hi {greeting_name},</p>"
        f"<p>Your {leave_type.name} leave request has been "
        f"<strong>{decision}</strong>.</p>"
        f"<ul>"
        f"<li><strong>Dates:</strong> {date_range}</li>"
        f"<li><strong>Hours:</strong> {hours}</li>"
        f"</ul>"
        f"{html_notes}"
    )
    return text, html


def _format_decision_sms_body(
    *,
    leave_type: LeaveType,
    leave_request: LeaveRequest,
    decision: str,
) -> str:
    """Compose the SMS body for an approve/reject decision.

    Confidential leave types get a generic message that never names the
    leave type, dates, or hours (per design §4.3.1). Other types get a
    short summary including the date range and hours.
    """
    if leave_type.confidential_visibility:
        return (
            f"Your leave request has been {decision}. "
            "View details in OraInvoice."
        )
    if leave_request.start_date == leave_request.end_date:
        date_range = leave_request.start_date.isoformat()
    else:
        date_range = (
            f"{leave_request.start_date.isoformat()} to "
            f"{leave_request.end_date.isoformat()}"
        )
    return (
        f"Your {leave_type.name} leave ({date_range}, "
        f"{leave_request.hours_requested}h) has been {decision}."
    )


async def _send_decision_notifications(
    db: AsyncSession,
    *,
    leave_request: LeaveRequest,
    leave_type: LeaveType,
    staff: StaffMember,
    decision: str,
) -> None:
    """Fire the approval / rejection email + SMS.

    Email is always attempted when the staff has an email address on
    file. SMS is only attempted when ``staff.weekly_roster_sms_enabled``
    is true AND a phone number is on file. Both calls are wrapped in
    individual try/except blocks so notification transport failures can
    NEVER roll back the underlying approval / rejection — the audit log
    captures the decision; the notification is best-effort.

    The :mod:`app.integrations.email_sender` and
    :mod:`app.integrations.sms_sender` modules are imported locally so
    that ``app.modules.leave.service`` remains importable in unit tests
    that don't fully wire up the SQLAlchemy mapper graph (the email
    sender transitively imports ``app.modules.admin.models`` which
    forces ``Organisation`` mapper configuration). Same workaround used
    by :func:`list_ledger` and :func:`list_requests` for the ``User``
    mapper.
    """
    # Local imports — see docstring for the mapper-config rationale.
    from app.integrations.email_sender import EmailMessage, send_email
    from app.integrations.sms_sender import send_sms

    subject_decision = decision  # 'approved' or 'rejected'
    org_id = leave_request.org_id

    # ------------------------------------------------------------------
    # Email — always when an address is on file (R10).
    # ------------------------------------------------------------------
    to_email = (staff.email or "").strip() if staff.email else ""
    if to_email:
        try:
            text_body, html_body = _format_decision_email_body(
                leave_type=leave_type,
                leave_request=leave_request,
                decision=subject_decision,
                staff_first_name=staff.first_name,
            )
            to_name = (
                f"{staff.first_name or ''} {staff.last_name or ''}".strip()
                or (staff.name or "")
            )
            message = EmailMessage(
                to_email=to_email,
                to_name=to_name,
                subject=f"Your leave request has been {subject_decision}",
                html_body=html_body,
                text_body=text_body,
                org_id=org_id,
            )
            await send_email(
                db,
                message,
                dlq_task_name="leave_decision_email",
                dlq_task_args={
                    "leave_request_id": str(leave_request.id),
                    "decision": subject_decision,
                    "org_id": str(org_id),
                },
            )
        except Exception:  # noqa: BLE001 - notification must not break the decision
            logger.exception(
                "leave_decision_email failed: org=%s request=%s decision=%s",
                org_id,
                leave_request.id,
                subject_decision,
            )

    # ------------------------------------------------------------------
    # SMS — opt-in only (R10 + Phase 1 helper).
    # ------------------------------------------------------------------
    sms_opt_in = bool(getattr(staff, "weekly_roster_sms_enabled", False))
    phone = (staff.phone or "").strip() if staff.phone else ""
    if sms_opt_in and phone:
        try:
            body = _format_decision_sms_body(
                leave_type=leave_type,
                leave_request=leave_request,
                decision=subject_decision,
            )
            await send_sms(
                db,
                to_phone=phone,
                body=body,
                org_id=org_id,
            )
        except Exception:  # noqa: BLE001 - notification must not break the decision
            logger.exception(
                "leave_decision_sms failed: org=%s request=%s decision=%s",
                org_id,
                leave_request.id,
                subject_decision,
            )


# ---------------------------------------------------------------------------
# submit_request
# ---------------------------------------------------------------------------


async def submit_request(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    payload: Any,
    requested_by_user_id: uuid.UUID,
) -> LeaveRequest:
    """Submit a leave request.

    See module docstring for the full set of guards. ``payload`` is a
    :class:`app.modules.leave.schemas.LeaveRequestCreate` instance (kept
    typing-light here so the service doesn't need to import the schema
    eagerly during test setup).
    """
    # Load staff + leave_type + balance.
    staff: StaffMember | None = await db.get(StaffMember, staff_id)
    if staff is None or staff.org_id != org_id:
        raise LeaveServiceError("staff_not_found")

    leave_type: LeaveType | None = await db.get(LeaveType, payload.leave_type_id)
    if leave_type is None or leave_type.org_id != org_id:
        raise LeaveServiceError("leave_type_not_found")

    bal_result = await db.execute(
        select(LeaveBalance).where(
            LeaveBalance.staff_id == staff_id,
            LeaveBalance.leave_type_id == payload.leave_type_id,
        )
    )
    balance: LeaveBalance | None = bal_result.scalar_one_or_none()
    if balance is None:
        raise LeaveServiceError("leave_balance_not_found")

    available = (
        Decimal(balance.accrued_hours)
        - Decimal(balance.used_hours)
        - Decimal(balance.pending_hours)
    )
    hours_requested = Decimal(payload.hours_requested)

    # ------------------------------------------------------------------
    # Bereavement gate (R4.7 / G1)
    # ------------------------------------------------------------------
    if leave_type.code == "bereavement":
        if payload.relationship_to_subject not in ("close_family", "other"):
            raise BereavementValidationError("relationship_to_subject")
        cap_multiplier = (
            Decimal(3) if payload.relationship_to_subject == "close_family"
            else Decimal(1)
        )
        cap_hours = (cap_multiplier * _std_daily_hours(staff)).quantize(
            Decimal("0.01")
        )
        if hours_requested > cap_hours:
            raise BereavementCapExceededError(cap_hours)
        # Balance check skipped — bereavement is event_based.

    # ------------------------------------------------------------------
    # TOIL Phase 2 guard (R4.8 / G6)
    # ------------------------------------------------------------------
    elif leave_type.code == "toil":
        if available < hours_requested:
            raise InsufficientToilBalanceError(available)

    # ------------------------------------------------------------------
    # Standard accruing-leave balance check
    # ------------------------------------------------------------------
    elif leave_type.accrual_method not in _NON_BALANCE_METHODS:
        if hours_requested > available:
            raise InsufficientLeaveError(available)

    # ------------------------------------------------------------------
    # Partial-day capture (R4.1, design §4.3 step 6)
    # ------------------------------------------------------------------
    partial_day_start_time: time | None = None
    if (
        payload.start_date == payload.end_date
        and hours_requested < _std_daily_hours(staff)
    ):
        partial_day_start_time = payload.partial_day_start_time

    # ------------------------------------------------------------------
    # Insert the request row
    # ------------------------------------------------------------------
    leave_request = LeaveRequest(
        org_id=org_id,
        staff_id=staff_id,
        leave_type_id=payload.leave_type_id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        hours_requested=hours_requested,
        status="pending",
        reason=payload.reason,
        relationship_to_subject=payload.relationship_to_subject,
        partial_day_start_time=partial_day_start_time,
        attachment_upload_id=payload.attachment_upload_id,
        requested_by=requested_by_user_id,
    )
    db.add(leave_request)

    # Increment pending_hours for accruing types only. event_based +
    # unaccrued types don't track a running balance.
    if leave_type.accrual_method not in _NON_BALANCE_METHODS:
        balance.pending_hours = Decimal(balance.pending_hours) + hours_requested
        balance.updated_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(leave_request)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=requested_by_user_id,
        action="leave_request.submitted",
        entity_type="leave_request",
        entity_id=leave_request.id,
        after_value=_audit_after_value(
            leave_type=leave_type, request=leave_request
        ),
    )

    return leave_request


# ---------------------------------------------------------------------------
# approve_request
# ---------------------------------------------------------------------------


async def approve_request(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    request_id: uuid.UUID,
    decided_by_user_id: uuid.UUID,
    request: "Request",
    decision_notes: str | None = None,
) -> LeaveRequest:
    """Approve a pending leave request.

    Permission gate (R4.6) runs before any state mutation. On approve:
      - decrements ``pending_hours`` (skipped for event_based/unaccrued),
      - increments ``used_hours`` (or just sets a marker for event_based
        like bereavement / public_holiday_alt / toil),
      - writes a ``leave_ledger`` row with ``reason='request_approved'``,
      - writes a ``schedule_entries`` row when the request is partial-day
        (full-day expansion is handled by the router/job — kept here as
        a single-row insert when ``partial_day_start_time`` is set).
    """
    leave_request, leave_type, staff, balance = await _load_request_for_decision(
        db, org_id=org_id, request_id=request_id
    )

    if leave_request.status != "pending":
        raise LeaveServiceError(
            f"leave_request_not_pending: status={leave_request.status}"
        )

    user_role = getattr(request.state, "role", "") or ""
    _check_confidential_permission(
        request, leave_type, decided_by_user_id, user_role, staff.user_id
    )

    leave_request.status = "approved"
    leave_request.decided_by = decided_by_user_id
    leave_request.decided_at = datetime.now(timezone.utc)
    leave_request.decision_notes = decision_notes

    hours = Decimal(leave_request.hours_requested)
    is_balance_type = leave_type.accrual_method not in _NON_BALANCE_METHODS

    if is_balance_type:
        balance.pending_hours = Decimal(balance.pending_hours) - hours
        balance.used_hours = Decimal(balance.used_hours) + hours
    else:
        # event_based types: no pending_hours decrement (we never
        # incremented). Track usage on used_hours so the ledger sum
        # remains the source of truth.
        balance.used_hours = Decimal(balance.used_hours) + hours
    balance.updated_at = datetime.now(timezone.utc)

    db.add(
        LeaveLedger(
            org_id=org_id,
            staff_id=leave_request.staff_id,
            leave_type_id=leave_request.leave_type_id,
            delta_hours=-hours,
            reason="request_approved",
            request_id=leave_request.id,
            occurred_at=leave_request.start_date,
            created_by=decided_by_user_id,
        )
    )

    # Partial-day schedule entry. Full-day expansion (one row per day in
    # range) belongs to a higher-level helper; the partial-day branch is
    # the one that captures the start_time the staff supplied.
    if leave_request.partial_day_start_time is not None:
        start_time = leave_request.partial_day_start_time
        # Compute end time = start + hours_requested.
        start_dt = datetime.combine(
            leave_request.start_date,
            start_time,
            tzinfo=timezone.utc,
        )
        # Use seconds for fractional hours.
        end_dt = datetime.fromtimestamp(
            start_dt.timestamp() + float(hours) * 3600,
            tz=timezone.utc,
        )
        db.add(
            ScheduleEntry(
                org_id=org_id,
                staff_id=leave_request.staff_id,
                start_time=start_dt,
                end_time=end_dt,
                entry_type="leave",
                status="scheduled",
                title=f"Leave: {leave_type.name}",
            )
        )
    elif staff.shift_start:
        # Full-day fallback when no partial_day_start_time was supplied.
        # Build a single span from staff.shift_start on start_date to
        # staff.shift_end (or +hours_requested) on end_date. Multi-day
        # range expansion is delegated to the public-holiday + s40A
        # helpers in app/modules/leave/public_holidays.py.
        try:
            sh_h, sh_m = staff.shift_start.split(":")
            shift_start = time(int(sh_h), int(sh_m))
        except (ValueError, AttributeError):
            shift_start = time(9, 0)
        start_dt = datetime.combine(
            leave_request.start_date, shift_start, tzinfo=timezone.utc
        )
        end_dt = datetime.fromtimestamp(
            start_dt.timestamp() + float(hours) * 3600, tz=timezone.utc
        )
        db.add(
            ScheduleEntry(
                org_id=org_id,
                staff_id=leave_request.staff_id,
                start_time=start_dt,
                end_time=end_dt,
                entry_type="leave",
                status="scheduled",
                title=f"Leave: {leave_type.name}",
            )
        )

    await db.flush()
    await db.refresh(leave_request)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=decided_by_user_id,
        action="leave_request.approved",
        entity_type="leave_request",
        entity_id=leave_request.id,
        after_value=_audit_after_value(
            leave_type=leave_type,
            request=leave_request,
            extra={"decided_at": leave_request.decided_at.isoformat()},
        ),
    )

    await _send_decision_notifications(
        db,
        leave_request=leave_request,
        leave_type=leave_type,
        staff=staff,
        decision="approved",
    )

    return leave_request


# ---------------------------------------------------------------------------
# reject_request
# ---------------------------------------------------------------------------


async def reject_request(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    request_id: uuid.UUID,
    decided_by_user_id: uuid.UUID,
    request: "Request",
    decision_notes: str | None = None,
) -> LeaveRequest:
    """Reject a pending leave request.

    Decrements ``pending_hours`` (no ``used_hours`` increment, no ledger
    row — Phase 1 design).
    """
    leave_request, leave_type, staff, balance = await _load_request_for_decision(
        db, org_id=org_id, request_id=request_id
    )

    if leave_request.status != "pending":
        raise LeaveServiceError(
            f"leave_request_not_pending: status={leave_request.status}"
        )

    user_role = getattr(request.state, "role", "") or ""
    _check_confidential_permission(
        request, leave_type, decided_by_user_id, user_role, staff.user_id
    )

    leave_request.status = "rejected"
    leave_request.decided_by = decided_by_user_id
    leave_request.decided_at = datetime.now(timezone.utc)
    leave_request.decision_notes = decision_notes

    if leave_type.accrual_method not in _NON_BALANCE_METHODS:
        balance.pending_hours = (
            Decimal(balance.pending_hours) - Decimal(leave_request.hours_requested)
        )
        balance.updated_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(leave_request)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=decided_by_user_id,
        action="leave_request.rejected",
        entity_type="leave_request",
        entity_id=leave_request.id,
        after_value=_audit_after_value(
            leave_type=leave_type,
            request=leave_request,
            extra={"decided_at": leave_request.decided_at.isoformat()},
        ),
    )

    await _send_decision_notifications(
        db,
        leave_request=leave_request,
        leave_type=leave_type,
        staff=staff,
        decision="rejected",
    )

    return leave_request


# ---------------------------------------------------------------------------
# cancel_request
# ---------------------------------------------------------------------------


async def cancel_request(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    request_id: uuid.UUID,
    user_id: uuid.UUID,
    request: "Request",
) -> LeaveRequest:
    """Cancel a pending OR approved leave request.

    For an approved request, writes a compensating ledger row with
    ``reason='request_cancelled_after_approval'`` and decrements
    ``used_hours`` so the balance returns to its pre-approval state.
    For a pending request, just decrements ``pending_hours``.
    """
    leave_request, leave_type, staff, balance = await _load_request_for_decision(
        db, org_id=org_id, request_id=request_id
    )

    if leave_request.status not in ("pending", "approved"):
        raise LeaveServiceError(
            f"leave_request_cannot_cancel: status={leave_request.status}"
        )

    user_role = getattr(request.state, "role", "") or ""
    _check_confidential_permission(
        request, leave_type, user_id, user_role, staff.user_id
    )

    prior_status = leave_request.status
    leave_request.status = "cancelled"
    leave_request.decided_by = user_id
    leave_request.decided_at = datetime.now(timezone.utc)

    hours = Decimal(leave_request.hours_requested)
    is_balance_type = leave_type.accrual_method not in _NON_BALANCE_METHODS

    if prior_status == "approved":
        # Compensating ledger row: positive delta restores the hours.
        db.add(
            LeaveLedger(
                org_id=org_id,
                staff_id=leave_request.staff_id,
                leave_type_id=leave_request.leave_type_id,
                delta_hours=hours,
                reason="request_cancelled_after_approval",
                request_id=leave_request.id,
                occurred_at=date.today(),
                created_by=user_id,
            )
        )
        balance.used_hours = Decimal(balance.used_hours) - hours
        balance.updated_at = datetime.now(timezone.utc)
    elif prior_status == "pending" and is_balance_type:
        balance.pending_hours = Decimal(balance.pending_hours) - hours
        balance.updated_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(leave_request)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="leave_request.cancelled",
        entity_type="leave_request",
        entity_id=leave_request.id,
        after_value=_audit_after_value(
            leave_type=leave_type,
            request=leave_request,
            extra={"prior_status": prior_status},
        ),
    )

    return leave_request


# ---------------------------------------------------------------------------
# adjust_balance (admin)
# ---------------------------------------------------------------------------


async def adjust_balance(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    leave_type_id: uuid.UUID,
    delta_hours: Decimal,
    reason: str,
    notes: str | None,
    created_by_user_id: uuid.UUID,
) -> LeaveLedger:
    """Apply a manual balance adjustment.

    Writes a ledger row with enum ``reason='manual_adjustment'`` and
    bumps ``balance.accrued_hours`` by ``delta_hours``. The ``reason``
    parameter is the human-friendly label; ``notes`` is the longer
    justification surfaced in the audit row.
    """
    bal_result = await db.execute(
        select(LeaveBalance).where(
            LeaveBalance.staff_id == staff_id,
            LeaveBalance.leave_type_id == leave_type_id,
        )
    )
    balance: LeaveBalance | None = bal_result.scalar_one_or_none()
    if balance is None:
        raise LeaveServiceError("leave_balance_not_found")

    balance.accrued_hours = Decimal(balance.accrued_hours) + Decimal(delta_hours)
    balance.updated_at = datetime.now(timezone.utc)

    ledger = LeaveLedger(
        org_id=org_id,
        staff_id=staff_id,
        leave_type_id=leave_type_id,
        delta_hours=Decimal(delta_hours),
        reason="manual_adjustment",
        request_id=None,
        occurred_at=date.today(),
        created_by=created_by_user_id,
    )
    db.add(ledger)

    await db.flush()
    await db.refresh(ledger)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=created_by_user_id,
        action="leave_balance.adjusted",
        entity_type="leave_balance",
        entity_id=balance.id,
        after_value={
            "staff_id": str(staff_id),
            "leave_type_id": str(leave_type_id),
            "delta_hours": str(delta_hours),
            "reason": reason,
            "notes": notes,
            "ledger_id": str(ledger.id),
        },
    )

    return ledger


# ---------------------------------------------------------------------------
# list_balances
# ---------------------------------------------------------------------------


async def list_balances(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
) -> tuple[list[dict[str, Any]], int]:
    """Return per-type balances for a staff member.

    Each item carries the joined ``leave_type_code`` / ``leave_type_name``
    plus the computed ``available_hours`` figure so the dashboard can
    render the balance cards without an extra round-trip.
    """
    stmt = (
        select(LeaveBalance, LeaveType)
        .join(LeaveType, LeaveBalance.leave_type_id == LeaveType.id)
        .where(
            LeaveBalance.org_id == org_id,
            LeaveBalance.staff_id == staff_id,
            LeaveType.active.is_(True),
        )
        .order_by(LeaveType.display_order)
    )
    result = await db.execute(stmt)
    rows = result.all()

    items: list[dict[str, Any]] = []
    for balance, leave_type in rows:
        accrued = Decimal(balance.accrued_hours)
        used = Decimal(balance.used_hours)
        pending = Decimal(balance.pending_hours)
        items.append(
            {
                "id": balance.id,
                "leave_type_id": balance.leave_type_id,
                "leave_type_code": leave_type.code,
                "leave_type_name": leave_type.name,
                "accrued_hours": accrued,
                "used_hours": used,
                "pending_hours": pending,
                "available_hours": accrued - used - pending,
                "anniversary_date": balance.anniversary_date,
                "last_accrual_at": balance.last_accrual_at,
                "updated_at": balance.updated_at,
            }
        )

    return items, len(items)


# ---------------------------------------------------------------------------
# list_ledger
# ---------------------------------------------------------------------------


async def list_ledger(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    leave_type_id: uuid.UUID | None = None,
    request: "Request",
    user_id: uuid.UUID,
    user_role: str,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    """Return ledger rows for a staff × (optional) leave-type pair.

    Joins ``users`` for ``created_by_email`` and (per P2-N10) joins
    ``leave_requests`` for ``request_relationship_to_subject`` so per
    event leave types (bereavement) can show the relationship inline.

    Confidentiality: when the row was generated by a leave_request, the
    same ``_apply_confidential_filter`` helper used by
    ``list_requests`` excludes confidential rows the actor isn't
    allowed to see. Rows without a ``request_id`` (manual adjustments,
    accrual postings) are tied directly to the staff and pass through
    unfiltered — the filter operates on ``LeaveRequest`` queries, not
    on ``LeaveLedger`` directly.
    """
    # Local User import keeps ``app.modules.leave.service`` free of an
    # import-time dependency on the User mapper (which transitively
    # forces the Organisation mapper to be configured before this
    # module is even importable in unit tests).
    from app.modules.auth.models import User

    # Subquery resolving the visible LeaveRequest IDs once. This
    # subquery embeds the confidential filter so any ledger row whose
    # ``request_id`` would have been hidden from this user is dropped
    # too. The filter operates on a ``select(LeaveRequest)`` per its
    # contract.
    visible_request_ids = _apply_confidential_filter(
        select(LeaveRequest.id).where(LeaveRequest.org_id == org_id),
        request,
        user_id,
        user_role,
    ).scalar_subquery()

    stmt = (
        select(
            LeaveLedger,
            LeaveType.code.label("leave_type_code"),
            User.email.label("created_by_email"),
            LeaveRequest.relationship_to_subject.label(
                "request_relationship_to_subject"
            ),
        )
        .join(LeaveType, LeaveLedger.leave_type_id == LeaveType.id)
        .outerjoin(User, LeaveLedger.created_by == User.id)
        .outerjoin(LeaveRequest, LeaveLedger.request_id == LeaveRequest.id)
        .where(
            LeaveLedger.org_id == org_id,
            LeaveLedger.staff_id == staff_id,
        )
    )
    if leave_type_id is not None:
        stmt = stmt.where(LeaveLedger.leave_type_id == leave_type_id)

    # Drop ledger rows whose linked LeaveRequest is hidden from this
    # actor by the confidential filter. Rows with NULL ``request_id``
    # (manual adjustments, scheduled accrual postings) are kept.
    stmt = stmt.where(
        (LeaveLedger.request_id.is_(None))
        | (LeaveLedger.request_id.in_(visible_request_ids))
    )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(
        LeaveLedger.occurred_at.desc(), LeaveLedger.created_at.desc()
    ).offset(offset).limit(limit)

    result = await db.execute(stmt)
    rows = result.all()

    items: list[dict[str, Any]] = []
    for row in rows:
        ledger = row[0]
        items.append(
            {
                "id": ledger.id,
                "leave_type_id": ledger.leave_type_id,
                "leave_type_code": row.leave_type_code,
                "delta_hours": ledger.delta_hours,
                "reason": ledger.reason,
                "request_id": ledger.request_id,
                "request_relationship_to_subject": (
                    row.request_relationship_to_subject
                ),
                "occurred_at": ledger.occurred_at,
                "created_at": ledger.created_at,
                "created_by": ledger.created_by,
                "created_by_email": row.created_by_email,
            }
        )

    return items, total


# ---------------------------------------------------------------------------
# list_requests
# ---------------------------------------------------------------------------


async def list_requests(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID | None = None,
    status: str | None = None,
    request: "Request",
    user_id: uuid.UUID,
    user_role: str,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    """Return leave requests, scoped + redacted per the confidential filter.

    Joins ``staff_members`` for ``staff_name``, ``leave_types`` for
    code + name, and ``users`` for ``requested_by_name``. The
    confidential filter from :mod:`app.modules.leave.visibility` is
    applied to the underlying query so the DB never returns rows the
    actor isn't permitted to see.
    """
    # Local User import — see ``list_ledger`` for the rationale.
    from app.modules.auth.models import User

    requested_by_user = User.__table__.alias("requested_by_user")

    base_query = select(LeaveRequest).where(LeaveRequest.org_id == org_id)
    if staff_id is not None:
        base_query = base_query.where(LeaveRequest.staff_id == staff_id)
    if status is not None:
        base_query = base_query.where(LeaveRequest.status == status)

    base_query = _apply_confidential_filter(
        base_query, request, user_id, user_role
    )

    # Re-build as a richer SELECT with joined columns. The filtered
    # ``base_query`` is used as a CTE-equivalent subquery for the count.
    count_stmt = select(func.count()).select_from(base_query.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(
            LeaveRequest,
            StaffMember.name.label("staff_name"),
            LeaveType.code.label("leave_type_code"),
            LeaveType.name.label("leave_type_name"),
            requested_by_user.c.first_name.label("requested_by_first_name"),
            requested_by_user.c.last_name.label("requested_by_last_name"),
            requested_by_user.c.email.label("requested_by_email"),
        )
        .join(StaffMember, LeaveRequest.staff_id == StaffMember.id)
        .join(LeaveType, LeaveRequest.leave_type_id == LeaveType.id)
        .outerjoin(
            requested_by_user,
            LeaveRequest.requested_by == requested_by_user.c.id,
        )
        .where(LeaveRequest.org_id == org_id)
    )
    if staff_id is not None:
        stmt = stmt.where(LeaveRequest.staff_id == staff_id)
    if status is not None:
        stmt = stmt.where(LeaveRequest.status == status)

    stmt = _apply_confidential_filter(stmt, request, user_id, user_role)
    stmt = stmt.order_by(LeaveRequest.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(stmt)
    rows = result.all()

    items: list[dict[str, Any]] = []
    for row in rows:
        leave_request: LeaveRequest = row[0]
        first = row.requested_by_first_name
        last = row.requested_by_last_name
        if first or last:
            requested_by_name = " ".join(p for p in (first, last) if p)
        else:
            requested_by_name = row.requested_by_email
        items.append(
            {
                "id": leave_request.id,
                "org_id": leave_request.org_id,
                "staff_id": leave_request.staff_id,
                "staff_name": row.staff_name,
                "leave_type_id": leave_request.leave_type_id,
                "leave_type_code": row.leave_type_code,
                "leave_type_name": row.leave_type_name,
                "start_date": leave_request.start_date,
                "end_date": leave_request.end_date,
                "hours_requested": leave_request.hours_requested,
                "status": leave_request.status,
                "reason": leave_request.reason,
                "relationship_to_subject": leave_request.relationship_to_subject,
                "partial_day_start_time": leave_request.partial_day_start_time,
                "attachment_upload_id": leave_request.attachment_upload_id,
                "requested_by": leave_request.requested_by,
                "requested_by_name": requested_by_name,
                "decided_by": leave_request.decided_by,
                "decided_at": leave_request.decided_at,
                "decision_notes": leave_request.decision_notes,
                "created_at": leave_request.created_at,
                "updated_at": leave_request.updated_at,
            }
        )

    return items, total
