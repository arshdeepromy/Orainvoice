"""Shift-swap service: target accept/reject, manager approve/reject, cancel.

Implements task B6 from `.kiro/specs/staff-management-p3` (G8 + G13).
Public surface:

  - :func:`target_accepts_swap` — target staff accepts a pending swap.
    When the org's ``clock_in_policy.shift_swap_requires_manager_approval``
    is ``False`` (default), auto-approves: re-checks target eligibility
    at the flip moment (409 ``scheduling_conflict_at_accept`` if the
    target has been scheduled into a conflicting shift since the
    request was raised), flips ``schedule_entries.staff_id`` to the
    target, status → ``'accepted'``, dispatches the per-event SMS
    matrix (R12.5).
    When the toggle is ``True``, transitions to ``'awaiting_manager'``
    instead and notifies the manager (no schedule change yet).
  - :func:`target_rejects_swap` — target rejects a pending swap;
    status → ``'rejected'``; SMS to requester only (R12.5 matrix).
  - :func:`manager_approves_swap` — manager approves an
    ``awaiting_manager`` swap; re-checks eligibility (409
    ``scheduling_conflict_at_manager_approval``); flips
    ``schedule_entries.staff_id``; status → ``'accepted'``; SMS to
    both staff.
  - :func:`manager_rejects_swap` — manager rejects an
    ``awaiting_manager`` swap; status → ``'rejected'``; SMS to both
    staff (no schedule change).
  - :func:`cancel_swap` — requester cancels their own pending /
    awaiting_manager swap; status → ``'cancelled'``; SMS to target
    when set.

The :func:`_notify_swap` helper composes one of the seven event-keyed
templates from R12.5 and dispatches via ``send_sms``. Each dispatch
writes one of:
  - ``shift_swap.sms_sent`` audit row on success;
  - ``shift_swap.sms_skipped`` audit row when the recipient has no
    ``phone`` set (per R12.5 — recipients without a phone are skipped
    quietly, not raised as errors).

Project conventions (project-overview.md):
  - All write paths use ``await db.flush()`` then
    ``await db.refresh(obj)`` (P1-N15) — never ``commit()`` because
    ``get_db_session`` runs the transaction with ``session.begin()``.
  - Audit rows go through :func:`app.core.audit.write_audit_log`
    against the ``audit_log`` table (P3-N2: singular).

**Validates: Requirements R12 — Staff Management Phase 3 task B6**
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.integrations.sms_sender import send_sms
from app.modules.scheduling_v2.models import ScheduleEntry
from app.modules.staff.models import StaffMember
from app.modules.time_clock.models import ShiftSwapRequest
from app.modules.time_clock.service import TimeClockServiceError


logger = logging.getLogger(__name__)


__all__ = [
    "ShiftSwapServiceError",
    "ShiftSwapNotFoundError",
    "ShiftSwapInvalidStateError",
    "ShiftSwapNotAuthorisedError",
    "ShiftSwapConflictError",
    "create_swap_request",
    "target_accepts_swap",
    "target_rejects_swap",
    "manager_approves_swap",
    "manager_rejects_swap",
    "cancel_swap",
]


# ---------------------------------------------------------------------------
# Service-layer exceptions
# ---------------------------------------------------------------------------


class ShiftSwapServiceError(TimeClockServiceError):
    """Base class for shift-swap service errors. Routers map each
    subclass to the documented HTTP status + body shape (R12).
    """


class ShiftSwapNotFoundError(ShiftSwapServiceError):
    """Raised when a referenced ``swap_id`` does not exist or belongs
    to another org. Router maps to HTTP 404.
    """


class ShiftSwapInvalidStateError(ShiftSwapServiceError):
    """Raised when the swap's current state is not compatible with the
    requested transition (e.g. ``manager_approves_swap`` on a
    ``'pending'`` row, or ``cancel_swap`` on a terminal row). Router
    maps to HTTP 409 with the documented error code in the message
    body (e.g. ``invalid_state``, ``not_awaiting_manager``).
    """


class ShiftSwapNotAuthorisedError(ShiftSwapServiceError):
    """Raised when the caller is not the documented actor for the
    requested transition (e.g. ``target_accepts_swap`` called by a
    staff member who is not the swap's ``target_staff_id``). Router
    maps to HTTP 403.
    """


class ShiftSwapConflictError(ShiftSwapServiceError):
    """Raised when the target's eligibility has lapsed since the swap
    was raised (e.g. a new schedule_entry now overlaps the swap's
    shift). Router maps to HTTP 409 with one of:
      - ``scheduling_conflict_at_accept`` (auto-approve flip)
      - ``scheduling_conflict_at_manager_approval`` (manager flip)
    """

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _swap_to_dict(swap: ShiftSwapRequest) -> dict[str, Any]:
    """Serialise a :class:`ShiftSwapRequest` for the audit log."""
    return {
        "id": str(swap.id),
        "requester_staff_id": str(swap.requester_staff_id),
        "target_staff_id": (
            str(swap.target_staff_id) if swap.target_staff_id else None
        ),
        "schedule_entry_id": str(swap.schedule_entry_id),
        "status": swap.status,
        "reason": swap.reason,
        "decided_by": str(swap.decided_by) if swap.decided_by else None,
        "decided_at": (
            swap.decided_at.isoformat() if swap.decided_at else None
        ),
    }


async def _load_clock_in_policy(
    db: AsyncSession, org_id: uuid.UUID,
) -> dict[str, Any]:
    """Return the org's ``clock_in_policy`` JSONB dict (or ``{}``)."""
    result = await db.execute(
        text("SELECT clock_in_policy FROM organisations WHERE id = :org_id"),
        {"org_id": str(org_id)},
    )
    row = result.scalar_one_or_none()
    return row if isinstance(row, dict) else {}


async def _is_target_still_eligible(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    target_staff_id: uuid.UUID,
    schedule_entry: ScheduleEntry,
) -> bool:
    """Return ``True`` when the target can still take the swap shift.

    A target is eligible when there is NO other ``schedule_entries``
    row for the target whose ``[start_time, end_time]`` window overlaps
    the swap shift's window. Cancelled entries are excluded via the
    ``status.in_(['scheduled', 'completed'])`` positive set (P3-N7).
    The swap shift itself is excluded from the conflict check — the
    target obviously isn't conflicting with the shift they're about to
    take.
    """
    stmt = (
        select(ScheduleEntry.id)
        .where(
            and_(
                ScheduleEntry.org_id == org_id,
                ScheduleEntry.staff_id == target_staff_id,
                ScheduleEntry.id != schedule_entry.id,
                ScheduleEntry.status.in_(["scheduled", "completed"]),
                ScheduleEntry.entry_type.in_(["job", "booking", "other"]),
                # Overlap test: existing.start < swap.end AND
                # existing.end > swap.start.
                ScheduleEntry.start_time < schedule_entry.end_time,
                ScheduleEntry.end_time > schedule_entry.start_time,
            ),
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none() is None


def _shift_label(entry: ScheduleEntry) -> str:
    """Return a short human-readable shift label (e.g. ``"Sat 10–4"``)
    for embedding in SMS bodies. Times are rendered in the entry's
    own timezone (``start_time.astimezone()`` falls through to local).
    """
    start = entry.start_time
    end = entry.end_time
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    weekday = start.strftime("%a")
    start_t = start.strftime("%H:%M")
    end_t = end.strftime("%H:%M")
    return f"{weekday} {start_t}-{end_t}"


async def _resolve_manager(
    db: AsyncSession, *, staff: StaffMember,
) -> StaffMember | None:
    """Walk ``staff.reporting_to`` chain and return the first manager
    whose record has a ``phone`` set.

    Used by :func:`_notify_swap` to dispatch the manager SMS in
    auto-approve and manager-approval flows. When no chain manager is
    reachable, the function returns ``None`` and the caller skips the
    manager dispatch (audit ``shift_swap.sms_skipped``
    reason=``no_manager``).
    """
    seen: set[uuid.UUID] = set()
    cursor = staff
    while cursor.reporting_to and cursor.reporting_to not in seen:
        seen.add(cursor.id)
        manager = await db.get(StaffMember, cursor.reporting_to)
        if manager is None:
            break
        if manager.phone:
            return manager
        cursor = manager
    return None


# ---------------------------------------------------------------------------
# R12.5 — Notification matrix
# ---------------------------------------------------------------------------


_SWAP_TEMPLATES: dict[str, dict[str, str]] = {
    # Event → recipient role → template body. Recipient roles:
    # 'requester', 'target', 'manager'. Missing entry = no SMS for
    # that role on that event.
    "request_created": {
        "target": (
            "{requester_first} asked you to take their {shift_label} shift. "
            "Open the app to accept or reject."
        ),
    },
    "auto_approved": {
        "requester": (
            "{target_first} took your {shift_label} shift — it's now theirs."
        ),
        "target": "You're now on the {shift_label} shift.",
    },
    "target_accepted_pending_manager": {
        "requester": (
            "{target_first} accepted your swap — pending manager approval."
        ),
        "target": (
            "Pending manager approval — you're not on the shift yet."
        ),
        "manager": (
            "Shift-swap request needs your approval: "
            "{requester_first} -> {target_first} on {shift_label}."
        ),
    },
    "target_rejected": {
        "requester": "{target_first} can't take your {shift_label} shift.",
    },
    "manager_approved": {
        "requester": (
            "Manager approved: {shift_label} is now {target_first}'s shift."
        ),
        "target": (
            "Manager approved — you're now on the {shift_label} shift."
        ),
    },
    "manager_rejected": {
        "requester": (
            "Swap rejected by manager — you're still on {shift_label}."
        ),
        "target": "Swap rejected by manager.",
    },
    "requester_cancelled": {
        "target": (
            "{requester_first} cancelled the swap request for {shift_label}."
        ),
    },
}


async def _notify_swap(
    db: AsyncSession,
    *,
    swap: ShiftSwapRequest,
    event: str,
    schedule_entry: ScheduleEntry,
    requester: StaffMember,
    target: StaffMember | None,
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> None:
    """Dispatch the per-event SMS matrix from R12.5 + write audit rows.

    Each recipient (requester, target, manager) gets at most one SMS
    per call. Recipients without a ``phone`` set produce an audit row
    ``shift_swap.sms_skipped`` reason=``no_phone`` and no SMS is sent.
    Successful sends produce ``shift_swap.sms_sent`` audit rows.

    The manager is resolved lazily — only looked up when the event's
    template includes a ``manager`` role.

    SMS dispatch happens through the shared ``send_sms`` helper with
    ``dlq_task_name='shift_swap_sms'`` so failed sends land in the
    DLQ for retry.
    """
    templates = _SWAP_TEMPLATES.get(event, {})
    if not templates:
        return

    shift_label = _shift_label(schedule_entry)
    requester_first = requester.first_name or requester.name or "Your colleague"
    target_first = (
        (target.first_name or target.name) if target else "Your colleague"
    )

    fmt_args = {
        "requester_first": requester_first,
        "target_first": target_first,
        "shift_label": shift_label,
    }

    # Resolve the manager only when needed.
    manager: StaffMember | None = None
    if "manager" in templates:
        manager = await _resolve_manager(db, staff=requester)

    role_to_recipient: dict[str, StaffMember | None] = {
        "requester": requester,
        "target": target,
        "manager": manager,
    }

    for role, body_template in templates.items():
        recipient = role_to_recipient.get(role)
        if recipient is None:
            await write_audit_log(
                session=db,
                org_id=swap.org_id,
                user_id=user_id,
                action="shift_swap.sms_skipped",
                entity_type="shift_swap_request",
                entity_id=swap.id,
                after_value={
                    "event": event,
                    "role": role,
                    "reason": "no_recipient",
                },
                ip_address=ip_address,
            )
            continue
        if not recipient.phone:
            await write_audit_log(
                session=db,
                org_id=swap.org_id,
                user_id=user_id,
                action="shift_swap.sms_skipped",
                entity_type="shift_swap_request",
                entity_id=swap.id,
                after_value={
                    "event": event,
                    "role": role,
                    "recipient_staff_id": str(recipient.id),
                    "reason": "no_phone",
                },
                ip_address=ip_address,
            )
            continue
        body = body_template.format(**fmt_args)
        try:
            result = await send_sms(
                db,
                to_phone=recipient.phone,
                body=body,
                dlq_task_name="shift_swap_sms",
                dlq_task_args={
                    "swap_request_id": str(swap.id),
                    "event": event,
                    "role": role,
                },
                org_id=swap.org_id,
            )
            ok = bool(getattr(result, "ok", False))
        except Exception:  # noqa: BLE001 - SMS failure is best-effort
            logger.exception(
                "shift_swap._notify_swap: send_sms raised "
                "swap=%s event=%s role=%s",
                swap.id, event, role,
            )
            ok = False
        await write_audit_log(
            session=db,
            org_id=swap.org_id,
            user_id=user_id,
            action=(
                "shift_swap.sms_sent" if ok else "shift_swap.sms_skipped"
            ),
            entity_type="shift_swap_request",
            entity_id=swap.id,
            after_value={
                "event": event,
                "role": role,
                "recipient_staff_id": str(recipient.id),
                "ok": ok,
                "reason": None if ok else "send_failed",
            },
            ip_address=ip_address,
        )


# ---------------------------------------------------------------------------
# Internal: load helpers
# ---------------------------------------------------------------------------


async def _load_swap(
    db: AsyncSession, *, org_id: uuid.UUID, swap_id: uuid.UUID,
) -> ShiftSwapRequest:
    swap = await db.get(ShiftSwapRequest, swap_id)
    if swap is None or swap.org_id != org_id:
        raise ShiftSwapNotFoundError("shift_swap_not_found")
    return swap


async def _load_staff(
    db: AsyncSession, *, org_id: uuid.UUID, staff_id: uuid.UUID,
) -> StaffMember | None:
    staff = await db.get(StaffMember, staff_id)
    if staff is None or staff.org_id != org_id:
        return None
    return staff


# ---------------------------------------------------------------------------
# Public API: create_swap_request
# ---------------------------------------------------------------------------


async def create_swap_request(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    requester_staff_id: uuid.UUID,
    schedule_entry_id: uuid.UUID,
    target_staff_id: uuid.UUID | None = None,
    reason: str | None = None,
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> ShiftSwapRequest:
    """Insert a new ``shift_swap_requests`` row in ``status='pending'``.

    When ``target_staff_id`` is supplied the row is a targeted swap
    and the target receives a ``request_created`` SMS. When it's
    ``None`` the row is "open" — Phase 3 routes still pass through
    here for forward-compatibility with the open-swap UX.
    """
    schedule_entry = await db.get(ScheduleEntry, schedule_entry_id)
    if schedule_entry is None or schedule_entry.org_id != org_id:
        raise ShiftSwapNotFoundError("schedule_entry_not_found")

    requester = await _load_staff(
        db, org_id=org_id, staff_id=requester_staff_id,
    )
    if requester is None:
        raise ShiftSwapNotFoundError("requester_staff_not_found")

    target: StaffMember | None = None
    if target_staff_id is not None:
        target = await _load_staff(
            db, org_id=org_id, staff_id=target_staff_id,
        )
        if target is None:
            raise ShiftSwapNotFoundError("target_staff_not_found")

    swap = ShiftSwapRequest(
        org_id=org_id,
        requester_staff_id=requester_staff_id,
        target_staff_id=target_staff_id,
        schedule_entry_id=schedule_entry_id,
        status="pending",
        reason=reason,
    )
    db.add(swap)
    await db.flush()
    await db.refresh(swap)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="shift_swap.requested",
        entity_type="shift_swap_request",
        entity_id=swap.id,
        after_value=_swap_to_dict(swap),
        ip_address=ip_address,
    )

    if target is not None:
        await _notify_swap(
            db,
            swap=swap,
            event="request_created",
            schedule_entry=schedule_entry,
            requester=requester,
            target=target,
            user_id=user_id,
            ip_address=ip_address,
        )

    return swap


# ---------------------------------------------------------------------------
# Public API: target_accepts_swap
# ---------------------------------------------------------------------------


async def target_accepts_swap(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    swap_id: uuid.UUID,
    acting_staff_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> ShiftSwapRequest:
    """Target accepts a pending swap.

    Two paths per design §4.8:
      - ``shift_swap_requires_manager_approval=False`` (default) →
        re-check eligibility, flip ``schedule_entries.staff_id``,
        status → ``'accepted'``, ``decided_by=acting_staff_id``,
        SMS matrix event ``auto_approved``.
      - ``shift_swap_requires_manager_approval=True`` →
        status → ``'awaiting_manager'`` (no schedule change yet),
        SMS matrix event ``target_accepted_pending_manager``.

    Raises:
      :class:`ShiftSwapNotFoundError`: swap or schedule_entry missing.
      :class:`ShiftSwapNotAuthorisedError`: caller is not the
        ``target_staff_id``.
      :class:`ShiftSwapInvalidStateError`: swap not in ``'pending'``.
      :class:`ShiftSwapConflictError`: target now overlaps another
        scheduled shift — code ``scheduling_conflict_at_accept``.
    """
    swap = await _load_swap(db, org_id=org_id, swap_id=swap_id)

    if swap.target_staff_id != acting_staff_id:
        raise ShiftSwapNotAuthorisedError("not_swap_target")
    if swap.status != "pending":
        raise ShiftSwapInvalidStateError("invalid_state")

    schedule_entry = await db.get(ScheduleEntry, swap.schedule_entry_id)
    if schedule_entry is None:
        raise ShiftSwapNotFoundError("schedule_entry_not_found")

    requester = await _load_staff(
        db, org_id=org_id, staff_id=swap.requester_staff_id,
    )
    target = await _load_staff(
        db, org_id=org_id, staff_id=swap.target_staff_id,
    )
    if requester is None or target is None:
        raise ShiftSwapNotFoundError("staff_not_found")

    before = _swap_to_dict(swap)
    policy = await _load_clock_in_policy(db, org_id)
    requires_manager = bool(
        policy.get("shift_swap_requires_manager_approval", False)
    )
    now = datetime.now(timezone.utc)

    if requires_manager:
        swap.status = "awaiting_manager"
        swap.decided_at = now
        # decided_by stays NULL until a manager decides — design §4.8
        # attributes only the manager-decision step to a user_id.
        await db.flush()
        await db.refresh(swap)
        await write_audit_log(
            session=db,
            org_id=org_id,
            user_id=user_id,
            action="shift_swap.target_accepted",
            entity_type="shift_swap_request",
            entity_id=swap.id,
            before_value=before,
            after_value=_swap_to_dict(swap),
            ip_address=ip_address,
        )
        await _notify_swap(
            db,
            swap=swap,
            event="target_accepted_pending_manager",
            schedule_entry=schedule_entry,
            requester=requester,
            target=target,
            user_id=user_id,
            ip_address=ip_address,
        )
        return swap

    # Auto-approve path — re-check eligibility, then flip.
    if not await _is_target_still_eligible(
        db,
        org_id=org_id,
        target_staff_id=swap.target_staff_id,
        schedule_entry=schedule_entry,
    ):
        raise ShiftSwapConflictError("scheduling_conflict_at_accept")

    # Snapshot pre-flip state for the roster-change SMS hook (G2).
    from app.modules.time_clock.roster_change_sms import (
        _emit_roster_change_sms,
        snapshot_schedule_entry,
    )
    entry_before_snapshot = snapshot_schedule_entry(schedule_entry)

    schedule_entry.staff_id = swap.target_staff_id
    swap.status = "accepted"
    swap.decided_by = None  # auto-approve has no user actor
    swap.decided_at = now
    await db.flush()
    await db.refresh(swap)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="shift_swap.target_accepted",
        entity_type="shift_swap_request",
        entity_id=swap.id,
        before_value=before,
        after_value=_swap_to_dict(swap),
        ip_address=ip_address,
    )
    await _notify_swap(
        db,
        swap=swap,
        event="auto_approved",
        schedule_entry=schedule_entry,
        requester=requester,
        target=target,
        user_id=user_id,
        ip_address=ip_address,
    )
    # G2 — also fire the generic roster-change SMS hook so out-of-band
    # subscribers (and the dedupe key) see the staff reassignment.
    await _emit_roster_change_sms(
        db,
        entry_before=entry_before_snapshot,
        entry_after=schedule_entry,
        change_type="staff_reassigned",
    )
    return swap


# ---------------------------------------------------------------------------
# Public API: target_rejects_swap
# ---------------------------------------------------------------------------


async def target_rejects_swap(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    swap_id: uuid.UUID,
    acting_staff_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> ShiftSwapRequest:
    """Target rejects a pending swap.

    Status → ``'rejected'``; SMS to requester only (R12.5 — target
    rejects row in the matrix). No schedule change.
    """
    swap = await _load_swap(db, org_id=org_id, swap_id=swap_id)

    if swap.target_staff_id != acting_staff_id:
        raise ShiftSwapNotAuthorisedError("not_swap_target")
    if swap.status != "pending":
        raise ShiftSwapInvalidStateError("invalid_state")

    schedule_entry = await db.get(ScheduleEntry, swap.schedule_entry_id)
    requester = await _load_staff(
        db, org_id=org_id, staff_id=swap.requester_staff_id,
    )
    target = await _load_staff(
        db, org_id=org_id, staff_id=swap.target_staff_id,
    )

    before = _swap_to_dict(swap)
    swap.status = "rejected"
    swap.decided_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(swap)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="shift_swap.target_rejected",
        entity_type="shift_swap_request",
        entity_id=swap.id,
        before_value=before,
        after_value=_swap_to_dict(swap),
        ip_address=ip_address,
    )

    if schedule_entry is not None and requester is not None:
        await _notify_swap(
            db,
            swap=swap,
            event="target_rejected",
            schedule_entry=schedule_entry,
            requester=requester,
            target=target,
            user_id=user_id,
            ip_address=ip_address,
        )

    return swap


# ---------------------------------------------------------------------------
# Public API: manager_approves_swap
# ---------------------------------------------------------------------------


async def manager_approves_swap(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    swap_id: uuid.UUID,
    manager_user_id: uuid.UUID,
    ip_address: str | None = None,
) -> ShiftSwapRequest:
    """Manager approves a swap from ``awaiting_manager``.

    Re-checks eligibility (raises
    :class:`ShiftSwapConflictError` with code
    ``scheduling_conflict_at_manager_approval`` if a new conflicting
    shift was scheduled since the request was raised). Flips
    ``schedule_entries.staff_id`` to the target. Status → ``'accepted'``.
    SMS matrix event ``manager_approved``.

    Raises:
      :class:`ShiftSwapInvalidStateError`: swap not in
        ``'awaiting_manager'`` (code ``not_awaiting_manager``).
    """
    swap = await _load_swap(db, org_id=org_id, swap_id=swap_id)
    if swap.status != "awaiting_manager":
        raise ShiftSwapInvalidStateError("not_awaiting_manager")

    schedule_entry = await db.get(ScheduleEntry, swap.schedule_entry_id)
    if schedule_entry is None:
        raise ShiftSwapNotFoundError("schedule_entry_not_found")
    if swap.target_staff_id is None:
        # Open swap with no target reaching awaiting_manager would be
        # a state-machine bug — guard defensively.
        raise ShiftSwapInvalidStateError("missing_target_staff")

    requester = await _load_staff(
        db, org_id=org_id, staff_id=swap.requester_staff_id,
    )
    target = await _load_staff(
        db, org_id=org_id, staff_id=swap.target_staff_id,
    )
    if requester is None or target is None:
        raise ShiftSwapNotFoundError("staff_not_found")

    if not await _is_target_still_eligible(
        db,
        org_id=org_id,
        target_staff_id=swap.target_staff_id,
        schedule_entry=schedule_entry,
    ):
        raise ShiftSwapConflictError("scheduling_conflict_at_manager_approval")

    # Snapshot pre-flip state for the roster-change SMS hook (G2).
    from app.modules.time_clock.roster_change_sms import (
        _emit_roster_change_sms,
        snapshot_schedule_entry,
    )
    entry_before_snapshot = snapshot_schedule_entry(schedule_entry)

    before = _swap_to_dict(swap)
    schedule_entry.staff_id = swap.target_staff_id
    swap.status = "accepted"
    swap.decided_by = manager_user_id
    swap.decided_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(swap)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=manager_user_id,
        action="shift_swap.manager_approved",
        entity_type="shift_swap_request",
        entity_id=swap.id,
        before_value=before,
        after_value=_swap_to_dict(swap),
        ip_address=ip_address,
    )
    await _notify_swap(
        db,
        swap=swap,
        event="manager_approved",
        schedule_entry=schedule_entry,
        requester=requester,
        target=target,
        user_id=manager_user_id,
        ip_address=ip_address,
    )
    # G2 — fire the roster-change SMS hook on the staff_id flip.
    await _emit_roster_change_sms(
        db,
        entry_before=entry_before_snapshot,
        entry_after=schedule_entry,
        change_type="staff_reassigned",
    )
    return swap


# ---------------------------------------------------------------------------
# Public API: manager_rejects_swap
# ---------------------------------------------------------------------------


async def manager_rejects_swap(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    swap_id: uuid.UUID,
    manager_user_id: uuid.UUID,
    ip_address: str | None = None,
) -> ShiftSwapRequest:
    """Manager rejects a swap from ``awaiting_manager``.

    Status → ``'rejected'``; no schedule change; SMS matrix event
    ``manager_rejected`` (both staff notified).
    """
    swap = await _load_swap(db, org_id=org_id, swap_id=swap_id)
    if swap.status != "awaiting_manager":
        raise ShiftSwapInvalidStateError("not_awaiting_manager")

    schedule_entry = await db.get(ScheduleEntry, swap.schedule_entry_id)
    requester = await _load_staff(
        db, org_id=org_id, staff_id=swap.requester_staff_id,
    )
    target = (
        await _load_staff(
            db, org_id=org_id, staff_id=swap.target_staff_id,
        )
        if swap.target_staff_id
        else None
    )

    before = _swap_to_dict(swap)
    swap.status = "rejected"
    swap.decided_by = manager_user_id
    swap.decided_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(swap)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=manager_user_id,
        action="shift_swap.manager_rejected",
        entity_type="shift_swap_request",
        entity_id=swap.id,
        before_value=before,
        after_value=_swap_to_dict(swap),
        ip_address=ip_address,
    )
    if schedule_entry is not None and requester is not None:
        await _notify_swap(
            db,
            swap=swap,
            event="manager_rejected",
            schedule_entry=schedule_entry,
            requester=requester,
            target=target,
            user_id=manager_user_id,
            ip_address=ip_address,
        )
    return swap


# ---------------------------------------------------------------------------
# Public API: cancel_swap
# ---------------------------------------------------------------------------


async def cancel_swap(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    swap_id: uuid.UUID,
    acting_staff_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> ShiftSwapRequest:
    """Requester cancels their own pending / awaiting_manager swap.

    Status → ``'cancelled'``; SMS to target only (R12.5 matrix
    ``requester_cancelled``); no schedule change.

    Raises:
      :class:`ShiftSwapNotAuthorisedError`: caller is not the
        ``requester_staff_id``.
      :class:`ShiftSwapInvalidStateError`: swap is in a terminal
        state (``accepted`` / ``rejected`` / ``cancelled``).
    """
    swap = await _load_swap(db, org_id=org_id, swap_id=swap_id)
    if swap.requester_staff_id != acting_staff_id:
        raise ShiftSwapNotAuthorisedError("not_swap_requester")
    if swap.status not in ("pending", "awaiting_manager"):
        raise ShiftSwapInvalidStateError("invalid_state")

    schedule_entry = await db.get(ScheduleEntry, swap.schedule_entry_id)
    requester = await _load_staff(
        db, org_id=org_id, staff_id=swap.requester_staff_id,
    )
    target = (
        await _load_staff(
            db, org_id=org_id, staff_id=swap.target_staff_id,
        )
        if swap.target_staff_id
        else None
    )

    before = _swap_to_dict(swap)
    swap.status = "cancelled"
    swap.decided_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(swap)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="shift_swap.cancelled",
        entity_type="shift_swap_request",
        entity_id=swap.id,
        before_value=before,
        after_value=_swap_to_dict(swap),
        ip_address=ip_address,
    )

    if schedule_entry is not None and requester is not None and target is not None:
        await _notify_swap(
            db,
            swap=swap,
            event="requester_cancelled",
            schedule_entry=schedule_entry,
            requester=requester,
            target=target,
            user_id=user_id,
            ip_address=ip_address,
        )
    return swap
