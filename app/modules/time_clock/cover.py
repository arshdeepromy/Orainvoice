"""Open-shift cover service: broadcast + claim with eligibility checks (G6).

Implements task B6 from `.kiro/specs/staff-management-p3` (G6 +
R13). Public surface:

  - :func:`create_cover_request` — admin/staff opens a shift for
    cover. Inserts a ``shift_cover_requests`` row, computes the
    eligible-staff list per the R13.2 filter, broadcasts a "Cover
    needed" SMS to each, and writes audit rows.
  - :func:`accept_cover_request` — eligible staff claims an open
    cover. Re-checks eligibility at the flip moment (409
    ``scheduling_conflict_at_claim`` if the staff has been scheduled
    into the window since broadcast); audit row
    ``shift_cover.claim_conflict`` on conflict. On success: flips
    ``schedule_entries.staff_id`` to the claimer; status →
    ``'accepted'``; SMS to the requester.
  - :func:`cancel_cover_request` — requester or admin cancels an
    open cover. Status → ``'cancelled'``.
  - :func:`expire_cover_request` — internal helper used by the
    scheduled task to flip past-due open covers to ``'expired'``.

Eligibility filter at broadcast time (R13.2 / G6):
  1. ``is_active = true``
  2. ``employee_id IS NOT NULL OR user_id IS NOT NULL`` (at least one
     channel to clock in — kiosk needs employee_id, self-service
     needs user_id)
  3. NOT already scheduled in the window
     ``[shift.start - 30min, shift.end + 30min]`` —
     ``schedule_entries`` rows for ``entry_type IN ('job', 'booking',
     'other')`` overlapping that window.
  4. **(P3-N8)** ``skills_overlap`` is currently a NO-OP because
     ``schedule_entries.required_skills`` does not yet exist as a
     column. The filter is included for forward compatibility — once
     a future schema addition introduces required_skills, an
     additional ``staff.skills`` JSONB intersection check kicks in
     here without code changes elsewhere.
  5. ``id != requester_staff_id`` — the requester themselves is
     excluded from the broadcast.

Project conventions (project-overview.md):
  - All write paths use ``await db.flush()`` then
    ``await db.refresh(obj)`` (P1-N15) — never ``commit()`` because
    ``get_db_session`` runs the transaction with ``session.begin()``.
  - Audit rows go through :func:`app.core.audit.write_audit_log`
    against the ``audit_log`` table (P3-N2: singular).

**Validates: Requirements R13 — Staff Management Phase 3 task B6**
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.integrations.sms_sender import send_sms
from app.modules.scheduling_v2.models import ScheduleEntry
from app.modules.staff.models import StaffMember
from app.modules.time_clock.models import ShiftCoverRequest
from app.modules.time_clock.service import TimeClockServiceError


logger = logging.getLogger(__name__)


__all__ = [
    "ShiftCoverServiceError",
    "ShiftCoverNotFoundError",
    "ShiftCoverInvalidStateError",
    "ShiftCoverNotAuthorisedError",
    "ShiftCoverConflictError",
    "create_cover_request",
    "accept_cover_request",
    "cancel_cover_request",
    "expire_cover_request",
    "list_eligible_staff",
]


# Default broadcast TTL — design §R13 says SMS does not have a
# magic-link claim path, but broadcasts get stale after 8 hours.
_DEFAULT_EXPIRES_HOURS = 8

# Window padding around the shift for the eligibility filter (R13.2).
_WINDOW_PADDING = timedelta(minutes=30)


# ---------------------------------------------------------------------------
# Service-layer exceptions
# ---------------------------------------------------------------------------


class ShiftCoverServiceError(TimeClockServiceError):
    """Base class for shift-cover service errors. Routers map each
    subclass to the documented HTTP status + body shape (R13).
    """


class ShiftCoverNotFoundError(ShiftCoverServiceError):
    """Raised when the referenced ``cover_id`` does not exist or
    belongs to another org. Router maps to HTTP 404.
    """


class ShiftCoverInvalidStateError(ShiftCoverServiceError):
    """Raised when the cover row is not in ``'open'`` (e.g. accept on
    an expired or accepted row). Router maps to HTTP 409.
    """


class ShiftCoverNotAuthorisedError(ShiftCoverServiceError):
    """Raised when the caller is not eligible to take the requested
    action (e.g. accepting a cover for a staff member who's not
    eligible at all per R13.2). Router maps to HTTP 403.
    """


class ShiftCoverConflictError(ShiftCoverServiceError):
    """Raised by :func:`accept_cover_request` when the claiming staff
    has been scheduled into a conflicting shift since broadcast
    (R13.4). Router maps to HTTP 409 with body
    ``{"detail": "scheduling_conflict_at_claim"}``.
    """

    def __init__(self) -> None:
        super().__init__("scheduling_conflict_at_claim")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _cover_to_dict(cover: ShiftCoverRequest) -> dict[str, Any]:
    """Serialise a :class:`ShiftCoverRequest` for the audit log."""
    return {
        "id": str(cover.id),
        "schedule_entry_id": str(cover.schedule_entry_id),
        "requester_staff_id": str(cover.requester_staff_id),
        "status": cover.status,
        "accepted_by": (
            str(cover.accepted_by) if cover.accepted_by else None
        ),
        "broadcast_at": (
            cover.broadcast_at.isoformat() if cover.broadcast_at else None
        ),
        "expires_at": (
            cover.expires_at.isoformat() if cover.expires_at else None
        ),
        "accepted_at": (
            cover.accepted_at.isoformat() if cover.accepted_at else None
        ),
    }


def _shift_summary(entry: ScheduleEntry) -> str:
    """Short label used in the broadcast SMS body: ``"Sat 10:00-16:00"``.

    Matches the format used by :mod:`app.modules.time_clock.swaps`.
    """
    start = entry.start_time
    end = entry.end_time
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return (
        f"{start.strftime('%a')} {start.strftime('%H:%M')}"
        f"-{end.strftime('%H:%M')}"
    )


async def list_eligible_staff(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    schedule_entry: ScheduleEntry,
    requester_staff_id: uuid.UUID,
) -> list[StaffMember]:
    """Compute the eligible-staff list for a cover broadcast (R13.2).

    Public so the router can return the list to the admin UI when
    creating a cover. The filter is applied in two passes:
      1. SQL-side: ``is_active=true``, has employee_id OR user_id, is
         not the requester.
      2. Python-side: not already scheduled in the
         ``[shift.start - 30min, shift.end + 30min]`` window — done
         with a follow-up query per candidate.

    Pass 1 is an indexed lookup. Pass 2 is N+1 against the
    ``schedule_entries`` index on ``(org_id, staff_id, start_time)``;
    Phase 3 organisations have ~50 active staff so this is cheap.

    **(P3-N8)** ``skills_overlap`` is intentionally not implemented —
    ``schedule_entries.required_skills`` does not yet exist. All
    otherwise-eligible staff currently receive the broadcast.
    """
    # Pass 1 — base eligibility.
    base_stmt = select(StaffMember).where(
        and_(
            StaffMember.org_id == org_id,
            StaffMember.is_active.is_(True),
            StaffMember.id != requester_staff_id,
            or_(
                StaffMember.employee_id.is_not(None),
                StaffMember.user_id.is_not(None),
            ),
        ),
    )
    candidates = list(
        (await db.execute(base_stmt)).scalars().all()
    )

    if not candidates:
        return []

    window_start = schedule_entry.start_time - _WINDOW_PADDING
    window_end = schedule_entry.end_time + _WINDOW_PADDING

    eligible: list[StaffMember] = []
    for staff in candidates:
        if not await _has_no_window_conflict(
            db,
            org_id=org_id,
            staff_id=staff.id,
            window_start=window_start,
            window_end=window_end,
            ignore_entry_id=schedule_entry.id,
        ):
            continue
        eligible.append(staff)
    return eligible


async def _has_no_window_conflict(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    window_start: datetime,
    window_end: datetime,
    ignore_entry_id: uuid.UUID | None = None,
) -> bool:
    """Return ``True`` when the staff has no scheduled shift overlapping
    the ``[window_start, window_end]`` interval.

    ``ignore_entry_id`` excludes a specific ``schedule_entries.id``
    from the conflict check — used so the cover shift itself doesn't
    count as a conflict against its own claimer.
    """
    conditions = [
        ScheduleEntry.org_id == org_id,
        ScheduleEntry.staff_id == staff_id,
        ScheduleEntry.status.in_(["scheduled", "completed"]),
        ScheduleEntry.entry_type.in_(["job", "booking", "other"]),
        # Overlap test: existing.start < window.end AND
        # existing.end > window.start.
        ScheduleEntry.start_time < window_end,
        ScheduleEntry.end_time > window_start,
    ]
    if ignore_entry_id is not None:
        conditions.append(ScheduleEntry.id != ignore_entry_id)
    stmt = select(ScheduleEntry.id).where(and_(*conditions)).limit(1)
    return (await db.execute(stmt)).scalar_one_or_none() is None


async def _broadcast_cover_sms(
    db: AsyncSession,
    *,
    cover: ShiftCoverRequest,
    schedule_entry: ScheduleEntry,
    eligible: list[StaffMember],
    user_id: uuid.UUID | None,
    ip_address: str | None,
) -> None:
    """Dispatch the "Cover needed" SMS to each eligible staff and
    write per-recipient audit rows.

    Recipients without a ``phone`` set produce a
    ``shift_cover.sms_skipped`` audit row reason=``no_phone``.
    Successful sends produce ``shift_cover.sms_sent``. Send failures
    are best-effort — they log and continue, with the dead-letter
    queue picking up retry via ``dlq_task_name='cover_broadcast_sms'``.
    """
    summary = _shift_summary(schedule_entry)
    body = f"Cover needed: {summary}. Open the app to claim."

    for staff in eligible:
        if not staff.phone:
            await write_audit_log(
                session=db,
                org_id=cover.org_id,
                user_id=user_id,
                action="shift_cover.sms_skipped",
                entity_type="shift_cover_request",
                entity_id=cover.id,
                after_value={
                    "recipient_staff_id": str(staff.id),
                    "reason": "no_phone",
                },
                ip_address=ip_address,
            )
            continue
        try:
            result = await send_sms(
                db,
                to_phone=staff.phone,
                body=body,
                dlq_task_name="cover_broadcast_sms",
                dlq_task_args={
                    "cover_request_id": str(cover.id),
                    "recipient_staff_id": str(staff.id),
                },
                org_id=cover.org_id,
            )
            ok = bool(getattr(result, "ok", False))
        except Exception:  # noqa: BLE001 - SMS failure is best-effort
            logger.exception(
                "shift_cover._broadcast_cover_sms: send_sms raised "
                "cover=%s recipient=%s",
                cover.id, staff.id,
            )
            ok = False
        await write_audit_log(
            session=db,
            org_id=cover.org_id,
            user_id=user_id,
            action=(
                "shift_cover.sms_sent" if ok else "shift_cover.sms_skipped"
            ),
            entity_type="shift_cover_request",
            entity_id=cover.id,
            after_value={
                "recipient_staff_id": str(staff.id),
                "ok": ok,
                "reason": None if ok else "send_failed",
            },
            ip_address=ip_address,
        )


# ---------------------------------------------------------------------------
# Public API: create_cover_request
# ---------------------------------------------------------------------------


async def create_cover_request(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    schedule_entry_id: uuid.UUID,
    requester_staff_id: uuid.UUID,
    expires_at: datetime | None = None,
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> ShiftCoverRequest:
    """Open a shift for cover and broadcast to eligible staff.

    Inserts a ``shift_cover_requests`` row in ``status='open'``,
    computes the eligible-staff list per :func:`list_eligible_staff`,
    sends the broadcast SMS, and writes an audit row
    ``shift_cover.requested`` with the eligibility-list summary.

    ``expires_at`` defaults to ``broadcast_at + 8 hours`` when omitted.

    Raises:
      :class:`ShiftCoverNotFoundError`: schedule_entry or requester
        staff doesn't exist in the org.
    """
    schedule_entry = await db.get(ScheduleEntry, schedule_entry_id)
    if schedule_entry is None or schedule_entry.org_id != org_id:
        raise ShiftCoverNotFoundError("schedule_entry_not_found")

    requester = await db.get(StaffMember, requester_staff_id)
    if requester is None or requester.org_id != org_id:
        raise ShiftCoverNotFoundError("requester_staff_not_found")

    now = datetime.now(timezone.utc)
    if expires_at is None:
        expires_at = now + timedelta(hours=_DEFAULT_EXPIRES_HOURS)

    cover = ShiftCoverRequest(
        org_id=org_id,
        schedule_entry_id=schedule_entry_id,
        requester_staff_id=requester_staff_id,
        status="open",
        broadcast_at=now,
        expires_at=expires_at,
    )
    db.add(cover)
    await db.flush()
    await db.refresh(cover)

    eligible = await list_eligible_staff(
        db,
        org_id=org_id,
        schedule_entry=schedule_entry,
        requester_staff_id=requester_staff_id,
    )

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="shift_cover.requested",
        entity_type="shift_cover_request",
        entity_id=cover.id,
        after_value={
            **_cover_to_dict(cover),
            "eligible_staff_ids": [str(s.id) for s in eligible],
            "eligible_count": len(eligible),
        },
        ip_address=ip_address,
    )

    await _broadcast_cover_sms(
        db,
        cover=cover,
        schedule_entry=schedule_entry,
        eligible=eligible,
        user_id=user_id,
        ip_address=ip_address,
    )

    return cover


# ---------------------------------------------------------------------------
# Public API: accept_cover_request
# ---------------------------------------------------------------------------


async def accept_cover_request(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    cover_id: uuid.UUID,
    accepting_staff_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> ShiftCoverRequest:
    """Eligible staff claims an open cover.

    Re-checks the window-conflict eligibility at the flip moment
    (R13.4 / G6 — race-at-claim). When the claiming staff has been
    scheduled into a conflicting shift since broadcast, raises
    :class:`ShiftCoverConflictError` and writes an audit row
    ``shift_cover.claim_conflict`` (the cover stays ``'open'``).

    On success: flips ``schedule_entries.staff_id`` to the claimer,
    sets ``status='accepted'``, ``accepted_by`` + ``accepted_at``;
    SMS to the requester.

    Raises:
      :class:`ShiftCoverNotFoundError`: cover or schedule_entry missing.
      :class:`ShiftCoverInvalidStateError`: cover not in ``'open'``.
      :class:`ShiftCoverNotAuthorisedError`: claimer is the requester
        themselves OR is not active OR has neither employee_id nor
        user_id (R13.2 base eligibility).
      :class:`ShiftCoverConflictError`: claimer overlaps another
        shift — code ``scheduling_conflict_at_claim``.
    """
    cover = await db.get(ShiftCoverRequest, cover_id)
    if cover is None or cover.org_id != org_id:
        raise ShiftCoverNotFoundError("shift_cover_not_found")
    if cover.status != "open":
        raise ShiftCoverInvalidStateError("invalid_state")

    schedule_entry = await db.get(ScheduleEntry, cover.schedule_entry_id)
    if schedule_entry is None:
        raise ShiftCoverNotFoundError("schedule_entry_not_found")

    claimer = await db.get(StaffMember, accepting_staff_id)
    if claimer is None or claimer.org_id != org_id:
        raise ShiftCoverNotFoundError("accepting_staff_not_found")

    # R13.2 base eligibility check at claim time.
    if (
        not claimer.is_active
        or claimer.id == cover.requester_staff_id
        or (not claimer.employee_id and not claimer.user_id)
    ):
        raise ShiftCoverNotAuthorisedError("ineligible_for_cover")

    requester = await db.get(StaffMember, cover.requester_staff_id)

    # Window-conflict re-check.
    window_start = schedule_entry.start_time - _WINDOW_PADDING
    window_end = schedule_entry.end_time + _WINDOW_PADDING
    if not await _has_no_window_conflict(
        db,
        org_id=org_id,
        staff_id=accepting_staff_id,
        window_start=window_start,
        window_end=window_end,
        ignore_entry_id=schedule_entry.id,
    ):
        await write_audit_log(
            session=db,
            org_id=org_id,
            user_id=user_id,
            action="shift_cover.claim_conflict",
            entity_type="shift_cover_request",
            entity_id=cover.id,
            after_value={
                "accepting_staff_id": str(accepting_staff_id),
                "reason": "scheduling_conflict_at_claim",
            },
            ip_address=ip_address,
        )
        raise ShiftCoverConflictError()

    before = _cover_to_dict(cover)

    # Snapshot pre-flip schedule_entry for the roster-change SMS hook (G2).
    from app.modules.time_clock.roster_change_sms import (
        _emit_roster_change_sms,
        snapshot_schedule_entry,
    )
    entry_before_snapshot = snapshot_schedule_entry(schedule_entry)

    schedule_entry.staff_id = accepting_staff_id
    cover.status = "accepted"
    cover.accepted_by = accepting_staff_id
    cover.accepted_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(cover)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="shift_cover.accepted",
        entity_type="shift_cover_request",
        entity_id=cover.id,
        before_value=before,
        after_value=_cover_to_dict(cover),
        ip_address=ip_address,
    )

    # SMS the requester so they know cover landed.
    if requester is not None and requester.phone:
        body = (
            f"{claimer.first_name or claimer.name or 'A colleague'} "
            f"has claimed your {_shift_summary(schedule_entry)} shift."
        )
        try:
            result = await send_sms(
                db,
                to_phone=requester.phone,
                body=body,
                dlq_task_name="cover_accepted_sms",
                dlq_task_args={
                    "cover_request_id": str(cover.id),
                    "recipient_staff_id": str(requester.id),
                },
                org_id=org_id,
            )
            ok = bool(getattr(result, "ok", False))
        except Exception:  # noqa: BLE001
            logger.exception(
                "shift_cover.accept_cover_request: requester SMS raised "
                "cover=%s",
                cover.id,
            )
            ok = False
        await write_audit_log(
            session=db,
            org_id=org_id,
            user_id=user_id,
            action=(
                "shift_cover.sms_sent" if ok else "shift_cover.sms_skipped"
            ),
            entity_type="shift_cover_request",
            entity_id=cover.id,
            after_value={
                "recipient_staff_id": str(requester.id),
                "event": "accepted",
                "ok": ok,
                "reason": None if ok else "send_failed",
            },
            ip_address=ip_address,
        )
    elif requester is not None:
        await write_audit_log(
            session=db,
            org_id=org_id,
            user_id=user_id,
            action="shift_cover.sms_skipped",
            entity_type="shift_cover_request",
            entity_id=cover.id,
            after_value={
                "recipient_staff_id": str(requester.id),
                "event": "accepted",
                "reason": "no_phone",
            },
            ip_address=ip_address,
        )

    # G2 — fire the roster-change SMS hook on the staff_id flip so
    # the claimer gets the standard "you're now on the X shift" SMS
    # alongside the cover-specific notification path.
    await _emit_roster_change_sms(
        db,
        entry_before=entry_before_snapshot,
        entry_after=schedule_entry,
        change_type="staff_reassigned",
    )

    return cover


# ---------------------------------------------------------------------------
# Public API: cancel_cover_request
# ---------------------------------------------------------------------------


async def cancel_cover_request(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    cover_id: uuid.UUID,
    acting_staff_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> ShiftCoverRequest:
    """Cancel an open cover request.

    Either the requester (``acting_staff_id == cover.requester_staff_id``)
    or an org admin (``acting_staff_id is None``, caller has the
    appropriate role enforced by the router) can cancel.

    Status → ``'cancelled'``. No SMS broadcast — recipients of the
    original "Cover needed" can simply ignore. Audit row
    ``shift_cover.cancelled`` written.

    Raises:
      :class:`ShiftCoverInvalidStateError`: cover not in ``'open'``.
      :class:`ShiftCoverNotAuthorisedError`: ``acting_staff_id`` is
        set but does not match ``requester_staff_id``.
    """
    cover = await db.get(ShiftCoverRequest, cover_id)
    if cover is None or cover.org_id != org_id:
        raise ShiftCoverNotFoundError("shift_cover_not_found")
    if cover.status != "open":
        raise ShiftCoverInvalidStateError("invalid_state")
    if (
        acting_staff_id is not None
        and acting_staff_id != cover.requester_staff_id
    ):
        raise ShiftCoverNotAuthorisedError("not_cover_requester")

    before = _cover_to_dict(cover)
    cover.status = "cancelled"
    await db.flush()
    await db.refresh(cover)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="shift_cover.cancelled",
        entity_type="shift_cover_request",
        entity_id=cover.id,
        before_value=before,
        after_value=_cover_to_dict(cover),
        ip_address=ip_address,
    )
    return cover


# ---------------------------------------------------------------------------
# Public API: expire_cover_request
# ---------------------------------------------------------------------------


async def expire_cover_request(
    db: AsyncSession,
    *,
    cover: ShiftCoverRequest,
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> ShiftCoverRequest:
    """Flip an open cover to ``'expired'`` once past its
    ``expires_at`` timestamp. Used by the scheduled task; routers
    don't call this directly. Idempotent — calling on a non-open row
    is a no-op.
    """
    if cover.status != "open":
        return cover
    before = _cover_to_dict(cover)
    cover.status = "expired"
    await db.flush()
    await db.refresh(cover)

    await write_audit_log(
        session=db,
        org_id=cover.org_id,
        user_id=user_id,
        action="shift_cover.expired",
        entity_type="shift_cover_request",
        entity_id=cover.id,
        before_value=before,
        after_value=_cover_to_dict(cover),
        ip_address=ip_address,
    )
    return cover
