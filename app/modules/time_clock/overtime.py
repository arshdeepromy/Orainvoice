"""Overtime-request service: submit, approve, reject, cancel.

Implements task B6 from `.kiro/specs/staff-management-p3` (R10).
Public surface:

  - :func:`submit_overtime_request` — staff or admin submits a
    pre-approval request. Status → ``'pending'``. Audit row
    ``overtime_request.submitted``.
  - :func:`approve_overtime_request` — manager approves. Status
    transitions ``'pending' -> 'approved'``. Audit row
    ``overtime_request.approved``.
  - :func:`reject_overtime_request` — manager rejects. Status
    transitions ``'pending' -> 'rejected'``. Audit row
    ``overtime_request.rejected``.
  - :func:`cancel_overtime_request` — requester cancels their own
    pending request. Status transitions ``'pending' -> 'rejected'``
    with ``decision_notes='cancelled_by_requester'`` so the row
    survives audit but no longer counts toward the
    ``compute_week_totals`` covered-overtime sum (G1.5).

Cross-references:
  - The schema is defined by :class:`OvertimeRequestCreate` in
    ``schemas.py`` (``proposed_extra_minutes`` ∈ [1, 1440]).
  - The DB row contains ``schedule_entry_id`` (nullable — free-form OT
    requests not tied to a specific shift), ``proposed_extra_minutes``,
    ``reason``, ``requested_by`` (users.id), ``status``,
    ``decided_by``, ``decided_at``, ``decision_notes``.
  - The 3-state CHECK enum (``pending``, ``approved``, ``rejected``)
    is declared in migration 0207 and mirrored in the ORM model.
  - When ``compute_week_totals`` runs with the org's
    ``overtime_policy.require_pre_approval=true``, it sums the
    ``proposed_extra_minutes`` of approved requests covering the
    week's shifts to compute the G1.5 ``unapproved_overtime`` warning.

Project conventions (project-overview.md):
  - All write paths use ``await db.flush()`` then
    ``await db.refresh(obj)`` (P1-N15) — never ``commit()`` because
    ``get_db_session`` runs the transaction with ``session.begin()``.
  - Audit rows go through :func:`app.core.audit.write_audit_log`
    against the ``audit_log`` table (P3-N2: singular).

**Validates: Requirements R10 — Staff Management Phase 3 task B6**
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.scheduling_v2.models import ScheduleEntry
from app.modules.staff.models import StaffMember
from app.modules.time_clock.models import OvertimeRequest
from app.modules.time_clock.service import TimeClockServiceError


logger = logging.getLogger(__name__)


__all__ = [
    "OvertimeRequestServiceError",
    "OvertimeRequestNotFoundError",
    "OvertimeRequestInvalidStateError",
    "OvertimeRequestNotAuthorisedError",
    "OvertimeRequestValidationError",
    "submit_overtime_request",
    "approve_overtime_request",
    "reject_overtime_request",
    "cancel_overtime_request",
]


# Bounds — mirror the Pydantic ``Field(..., gt=0, le=1440)`` in
# :class:`OvertimeRequestCreate`. The service layer re-checks them so
# callers that bypass the Pydantic schema (tests, internal flows) still
# get the same guard.
_MIN_PROPOSED_MINUTES = 1
_MAX_PROPOSED_MINUTES = 1440  # 24h cap


# ---------------------------------------------------------------------------
# Service-layer exceptions
# ---------------------------------------------------------------------------


class OvertimeRequestServiceError(TimeClockServiceError):
    """Base class for overtime-request service errors. Routers map
    each subclass to the documented HTTP status + body shape (R10).
    """


class OvertimeRequestNotFoundError(OvertimeRequestServiceError):
    """Raised when a referenced ``request_id`` does not exist or
    belongs to another org. Router maps to HTTP 404.
    """


class OvertimeRequestInvalidStateError(OvertimeRequestServiceError):
    """Raised when the request is not in ``'pending'`` for an
    approve / reject / cancel transition. Router maps to HTTP 409.
    """


class OvertimeRequestNotAuthorisedError(OvertimeRequestServiceError):
    """Raised when the caller is not the documented actor (e.g.
    ``cancel_overtime_request`` called by a user who didn't submit
    the row). Router maps to HTTP 403.
    """


class OvertimeRequestValidationError(OvertimeRequestServiceError):
    """Raised when a payload value is outside the documented bounds
    (e.g. ``proposed_extra_minutes <= 0`` or > 1440). Router maps to
    HTTP 422.
    """


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _request_to_dict(request: OvertimeRequest) -> dict[str, Any]:
    """Serialise an :class:`OvertimeRequest` for the audit log."""
    return {
        "id": str(request.id),
        "staff_id": str(request.staff_id),
        "schedule_entry_id": (
            str(request.schedule_entry_id)
            if request.schedule_entry_id else None
        ),
        "proposed_extra_minutes": request.proposed_extra_minutes,
        "reason": request.reason,
        "requested_by": str(request.requested_by),
        "status": request.status,
        "decided_by": (
            str(request.decided_by) if request.decided_by else None
        ),
        "decided_at": (
            request.decided_at.isoformat() if request.decided_at else None
        ),
        "decision_notes": request.decision_notes,
    }


async def _load_request(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    request_id: uuid.UUID,
) -> OvertimeRequest:
    """Load an :class:`OvertimeRequest` and 404 when missing or
    belonging to another org. ``decided_at`` and ``decision_notes``
    survive even for terminal rows so the audit history reads
    end-to-end.
    """
    row = await db.get(OvertimeRequest, request_id)
    if row is None or row.org_id != org_id:
        raise OvertimeRequestNotFoundError("overtime_request_not_found")
    return row


# ---------------------------------------------------------------------------
# Public API: submit_overtime_request
# ---------------------------------------------------------------------------


async def submit_overtime_request(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    proposed_extra_minutes: int,
    requested_by: uuid.UUID,
    schedule_entry_id: uuid.UUID | None = None,
    reason: str | None = None,
    ip_address: str | None = None,
) -> OvertimeRequest:
    """Insert an ``overtime_requests`` row in ``status='pending'``.

    Args:
      org_id: tenant org.
      staff_id: subject staff member (the one whose hours will exceed
        the threshold). When admin submits on behalf of another
        staff, ``staff_id`` is the other staff; when staff submits
        for themselves, ``staff_id`` is their own staff record.
      proposed_extra_minutes: requested overtime budget for the
        shift / week — bounded ``[1, 1440]`` per
        :class:`OvertimeRequestCreate`.
      requested_by: ``users.id`` of the caller (the one who clicked
        Submit).
      schedule_entry_id: optional link to a specific shift; when set
        the eligibility checks in approval flow can scope the
        request to that shift's week.
      reason: optional free-form text shown on the manager queue UI.

    Raises:
      :class:`OvertimeRequestValidationError`: when
        ``proposed_extra_minutes`` is outside ``[1, 1440]``.
      :class:`OvertimeRequestNotFoundError`: when ``staff_id`` or
        ``schedule_entry_id`` doesn't exist in the org.
    """
    if (
        not isinstance(proposed_extra_minutes, int)
        or proposed_extra_minutes < _MIN_PROPOSED_MINUTES
        or proposed_extra_minutes > _MAX_PROPOSED_MINUTES
    ):
        raise OvertimeRequestValidationError(
            "invalid_proposed_extra_minutes"
        )

    staff = await db.get(StaffMember, staff_id)
    if staff is None or staff.org_id != org_id:
        raise OvertimeRequestNotFoundError("staff_not_found")

    if schedule_entry_id is not None:
        entry = await db.get(ScheduleEntry, schedule_entry_id)
        if entry is None or entry.org_id != org_id:
            raise OvertimeRequestNotFoundError("schedule_entry_not_found")

    request = OvertimeRequest(
        org_id=org_id,
        staff_id=staff_id,
        schedule_entry_id=schedule_entry_id,
        proposed_extra_minutes=proposed_extra_minutes,
        reason=reason,
        requested_by=requested_by,
        status="pending",
    )
    db.add(request)
    await db.flush()
    await db.refresh(request)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=requested_by,
        action="overtime_request.submitted",
        entity_type="overtime_request",
        entity_id=request.id,
        after_value=_request_to_dict(request),
        ip_address=ip_address,
    )
    return request


# ---------------------------------------------------------------------------
# Public API: approve_overtime_request
# ---------------------------------------------------------------------------


async def approve_overtime_request(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    request_id: uuid.UUID,
    decided_by: uuid.UUID,
    decision_notes: str | None = None,
    ip_address: str | None = None,
) -> OvertimeRequest:
    """Manager approves a pending overtime request.

    Status → ``'approved'``; ``decided_by`` set to the manager's
    ``users.id``; ``decided_at`` set to ``now()``. Audit row
    ``overtime_request.approved`` with both pre/post snapshots.

    Raises:
      :class:`OvertimeRequestInvalidStateError`: when the row is not
        in ``'pending'``.
    """
    request = await _load_request(
        db, org_id=org_id, request_id=request_id,
    )
    if request.status != "pending":
        raise OvertimeRequestInvalidStateError("not_pending")

    before = _request_to_dict(request)
    request.status = "approved"
    request.decided_by = decided_by
    request.decided_at = datetime.now(timezone.utc)
    request.decision_notes = decision_notes
    await db.flush()
    await db.refresh(request)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=decided_by,
        action="overtime_request.approved",
        entity_type="overtime_request",
        entity_id=request.id,
        before_value=before,
        after_value=_request_to_dict(request),
        ip_address=ip_address,
    )
    return request


# ---------------------------------------------------------------------------
# Public API: reject_overtime_request
# ---------------------------------------------------------------------------


async def reject_overtime_request(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    request_id: uuid.UUID,
    decided_by: uuid.UUID,
    decision_notes: str | None = None,
    ip_address: str | None = None,
) -> OvertimeRequest:
    """Manager rejects a pending overtime request.

    Status → ``'rejected'``; ``decided_by`` set to the manager's
    ``users.id``; ``decided_at`` set to ``now()``. Audit row
    ``overtime_request.rejected`` with both pre/post snapshots.

    Raises:
      :class:`OvertimeRequestInvalidStateError`: when the row is not
        in ``'pending'``.
    """
    request = await _load_request(
        db, org_id=org_id, request_id=request_id,
    )
    if request.status != "pending":
        raise OvertimeRequestInvalidStateError("not_pending")

    before = _request_to_dict(request)
    request.status = "rejected"
    request.decided_by = decided_by
    request.decided_at = datetime.now(timezone.utc)
    request.decision_notes = decision_notes
    await db.flush()
    await db.refresh(request)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=decided_by,
        action="overtime_request.rejected",
        entity_type="overtime_request",
        entity_id=request.id,
        before_value=before,
        after_value=_request_to_dict(request),
        ip_address=ip_address,
    )
    return request


# ---------------------------------------------------------------------------
# Public API: cancel_overtime_request
# ---------------------------------------------------------------------------


async def cancel_overtime_request(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    request_id: uuid.UUID,
    acting_user_id: uuid.UUID,
    ip_address: str | None = None,
) -> OvertimeRequest:
    """Requester cancels their own pending overtime request.

    The schema enum has only three values (``pending`` / ``approved``
    / ``rejected``) — there is no dedicated ``'cancelled'`` state. To
    keep the audit trail intact while removing the request from the
    "covered-overtime" sum that ``compute_week_totals`` relies on, a
    cancel transitions the row to ``'rejected'`` with
    ``decision_notes='cancelled_by_requester'``. The audit row uses
    ``action='overtime_request.cancelled'`` so dashboards can tell
    cancelled rows apart from manager-rejected rows.

    Raises:
      :class:`OvertimeRequestNotAuthorisedError`: caller is not the
        original ``requested_by`` (only the requester can cancel
        their own request — admins use reject_overtime_request).
      :class:`OvertimeRequestInvalidStateError`: row is not in
        ``'pending'``.
    """
    request = await _load_request(
        db, org_id=org_id, request_id=request_id,
    )
    if request.requested_by != acting_user_id:
        raise OvertimeRequestNotAuthorisedError("not_overtime_requester")
    if request.status != "pending":
        raise OvertimeRequestInvalidStateError("not_pending")

    before = _request_to_dict(request)
    request.status = "rejected"
    request.decided_by = acting_user_id
    request.decided_at = datetime.now(timezone.utc)
    request.decision_notes = "cancelled_by_requester"
    await db.flush()
    await db.refresh(request)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=acting_user_id,
        action="overtime_request.cancelled",
        entity_type="overtime_request",
        entity_id=request.id,
        before_value=before,
        after_value=_request_to_dict(request),
        ip_address=ip_address,
    )
    return request
