"""Roster-change SMS hook (G2 / R14a / task B7a).

Fires fire-and-forget SMS notifications when a ``schedule_entries`` row
within the next 48 hours has its ``start_time``, ``end_time``, or
``staff_id`` changed. Uses Redis ``SET NX EX 3600`` dedupe (key
``roster_change:{schedule_entry_id}``) so multiple edits in quick
succession produce one SMS per hour per entry.

Hooked into:
  - :func:`app.modules.scheduling_v2.service.SchedulingService.update_entry`
  - :func:`app.modules.scheduling_v2.service.SchedulingService.reschedule`
  - :func:`app.modules.time_clock.swaps.target_accepts_swap`
    (auto-approve flip)
  - :func:`app.modules.time_clock.swaps.manager_approves_swap`
  - :func:`app.modules.time_clock.cover.accept_cover_request`

Public surface:
  - :func:`_emit_roster_change_sms` — call from any scheduling write
    path after the row is mutated. Idempotent within the dedupe
    window. Honours ``staff.weekly_roster_sms_enabled`` opt-out
    (R14a.4) and skips ``status='cancelled'`` entries (P3-N10).
  - :func:`compose_change_sms_body` — pure helper that returns the
    160-char SMS body for the given ``change_type``. Templates per
    design §4.6.
  - :func:`snapshot_schedule_entry` — capture the pre-mutation state
    of a :class:`ScheduleEntry` so the caller can pass ``entry_before``
    to the hook after the in-place mutation.

The hook never raises — failures are logged and the surrounding
transaction is unaffected. Project-overview convention: writes use
``await db.flush()`` only (the outer ``get_db_session`` is configured
with ``session.begin()`` so commits happen at request boundary).

**Validates: Requirement R14a — Staff Management Phase 3 task B7a**
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.redis import redis_pool
from app.integrations.sms_sender import send_sms
from app.modules.staff.models import StaffMember


logger = logging.getLogger(__name__)


__all__ = [
    "compose_change_sms_body",
    "snapshot_schedule_entry",
    "_emit_roster_change_sms",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Look-ahead window for "in-window" detection — design §4.6 + R14a.6.
# Shifts further out than this are picked up by the Friday auto-roster
# broadcast from Phase 1 R10, not by this hook.
_IN_WINDOW_HOURS = 48

# Redis dedupe TTL — design §4.6 + R14a.3. Any second edit within 60
# minutes of the first is suppressed so a flurry of admin tweaks
# doesn't blast the staff with repeated SMS.
_DEDUPE_TTL_SECONDS = 3600


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def snapshot_schedule_entry(entry: Any) -> SimpleNamespace:
    """Capture the fields the hook needs from a :class:`ScheduleEntry`
    BEFORE mutation, so the caller can pass it as ``entry_before``
    after the in-place setattr/flush.

    Uses :class:`types.SimpleNamespace` rather than a dataclass to
    keep the call sites cheap (no allocation of an extra ORM-shaped
    type) and to avoid forcing the caller to import a Pydantic model.
    """
    start = entry.start_time
    end = entry.end_time
    return SimpleNamespace(
        id=entry.id,
        org_id=entry.org_id,
        staff_id=entry.staff_id,
        start_time=start,
        end_time=end,
        status=entry.status,
    )


def _format_dd_mmm(dt: datetime) -> str:
    """Render ``"9 Jun"`` — locale-independent, no leading zero on the
    day-of-month. Cross-platform: ``%-d`` is GNU-only and breaks on
    Windows; ``int(.day)`` works everywhere.
    """
    return f"{dt.day} {dt.strftime('%b')}"


def _format_hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def compose_change_sms_body(
    entry_before: Any,
    entry_after: Any,
    change_type: str,
    staff: StaffMember,
) -> str:
    """Build the SMS body for a roster-change notification.

    Templates per design §4.6:

      - ``staff_reassigned`` to outgoing staff (``staff.id ==
        entry_before.staff_id``):
          ``"Your shift on {weekday} {dd_mmm} {hhmm}-{hhmm} has been
          reassigned. Open the app for details."``
      - ``staff_reassigned`` to incoming staff (``staff.id ==
        entry_after.staff_id``):
          ``"You're now on the {weekday} {dd_mmm} {hhmm}-{hhmm}
          shift. Open the app for details."``
      - ``time_changed``:
          ``"Your shift on {weekday} {dd_mmm} changed: now
          {new_start}-{new_end} (was {old_start}-{old_end})."``

    Times are rendered against the supplied datetime's own tzinfo —
    the caller is responsible for passing tz-aware datetimes (the
    ORM column is ``DateTime(timezone=True)``).
    """
    if change_type == "staff_reassigned":
        # Outgoing — the staff member being notified WAS on this shift.
        # We render against ``entry_before`` because the shift's time
        # may also have moved as part of the same edit; the message
        # refers to the shift the staff was on.
        if (
            entry_before.staff_id is not None
            and entry_before.staff_id == staff.id
        ):
            weekday = entry_before.start_time.strftime("%a")
            dd_mmm = _format_dd_mmm(entry_before.start_time)
            hhmm_start = _format_hhmm(entry_before.start_time)
            hhmm_end = _format_hhmm(entry_before.end_time)
            return (
                f"Your shift on {weekday} {dd_mmm} {hhmm_start}-{hhmm_end} "
                f"has been reassigned. Open the app for details."
            )
        # Incoming — the staff member is now on the shift.
        weekday = entry_after.start_time.strftime("%a")
        dd_mmm = _format_dd_mmm(entry_after.start_time)
        hhmm_start = _format_hhmm(entry_after.start_time)
        hhmm_end = _format_hhmm(entry_after.end_time)
        return (
            f"You're now on the {weekday} {dd_mmm} {hhmm_start}-{hhmm_end} "
            f"shift. Open the app for details."
        )

    if change_type == "time_changed":
        weekday = entry_after.start_time.strftime("%a")
        dd_mmm = _format_dd_mmm(entry_after.start_time)
        new_start = _format_hhmm(entry_after.start_time)
        new_end = _format_hhmm(entry_after.end_time)
        old_start = _format_hhmm(entry_before.start_time)
        old_end = _format_hhmm(entry_before.end_time)
        return (
            f"Your shift on {weekday} {dd_mmm} changed: "
            f"now {new_start}-{new_end} (was {old_start}-{old_end})."
        )

    # Unknown change_type — return empty so the caller can guard.
    return ""


# ---------------------------------------------------------------------------
# Internal: redis dedupe
# ---------------------------------------------------------------------------


async def _claim_dedupe_slot(schedule_entry_id: Any) -> bool:
    """Atomically claim the per-entry dedupe slot.

    Returns ``True`` when the slot was free (this caller is the one
    sending the SMS) and ``False`` when another caller already claimed
    it inside the rolling 60-minute window.

    Soft-fails to ``True`` when Redis is unavailable so a transient
    Redis outage doesn't suppress legitimate SMS — the same
    soft-fail philosophy used by ``time_clock.service`` for kiosk
    rate limiting.
    """
    redis_key = f"roster_change:{schedule_entry_id}"
    try:
        was_set = await redis_pool.set(
            redis_key, "1", nx=True, ex=_DEDUPE_TTL_SECONDS,
        )
    except Exception:  # noqa: BLE001 - dedupe is best-effort.
        logger.warning(
            "roster_change_sms: redis dedupe error key=%s — proceeding",
            redis_key,
        )
        return True
    return bool(was_set)


# ---------------------------------------------------------------------------
# Public: main hook
# ---------------------------------------------------------------------------


async def _emit_roster_change_sms(
    db: AsyncSession,
    *,
    entry_before: Any,
    entry_after: Any,
    change_type: str,
) -> None:
    """Fire-and-forget SMS notifications for an in-window roster change.

    ``change_type`` is one of:
      - ``'staff_reassigned'`` — ``schedule_entries.staff_id`` changed
        (sends SMS to BOTH the outgoing ``entry_before.staff_id`` and
        the incoming ``entry_after.staff_id`` when set).
      - ``'time_changed'`` — ``start_time`` or ``end_time`` changed
        with the same staff (sends SMS to ``entry_after.staff_id``).

    Skips when:
      - ``entry_after.start_time`` is more than 48 hours in the
        future (Friday auto-broadcast from Phase 1 R10 covers it).
      - ``entry_after.status == 'cancelled'`` (P3-N10) — writes audit
        ``roster.change_sms_skipped`` reason=``cancelled_entry``.
      - The Redis dedupe slot for ``entry_after.id`` is already
        claimed within the last 60 minutes.
      - The recipient staff has ``weekly_roster_sms_enabled=false``
        (audit reason=``opt_out``).
      - The recipient staff has no ``phone`` set (audit
        reason=``no_phone``).

    Audits every send: ``roster.change_sms_sent`` on success and
    ``roster.change_sms_skipped`` on every failure / opt-out / no-phone
    branch.

    Wraps the whole flow in a top-level ``try``/``except`` so the
    surrounding write path (e.g. ``SchedulingService.update_entry``)
    is never destabilised by a hook failure.
    """
    try:
        await _emit_roster_change_sms_inner(
            db,
            entry_before=entry_before,
            entry_after=entry_after,
            change_type=change_type,
        )
    except Exception:  # noqa: BLE001 - hook is fire-and-forget.
        logger.exception(
            "_emit_roster_change_sms: unexpected error entry_id=%s",
            getattr(entry_after, "id", None),
        )


async def _emit_roster_change_sms_inner(
    db: AsyncSession,
    *,
    entry_before: Any,
    entry_after: Any,
    change_type: str,
) -> None:
    """Inner implementation — see :func:`_emit_roster_change_sms`."""
    # 1. Out-of-window — skip silently (R14a.6).
    now = datetime.now(timezone.utc)
    start_time = entry_after.start_time
    if start_time is not None and start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if start_time is None or start_time > now + timedelta(hours=_IN_WINDOW_HOURS):
        return

    # 2. Cancelled entries (P3-N10) — audit + skip, no SMS.
    if entry_after.status == "cancelled":
        await write_audit_log(
            session=db,
            org_id=entry_after.org_id,
            action="roster.change_sms_skipped",
            entity_type="schedule_entry",
            entity_id=entry_after.id,
            after_value={
                "schedule_entry_id": str(entry_after.id),
                "change_type": change_type,
                "reason": "cancelled_entry",
            },
        )
        return

    # 3. Redis dedupe — first writer wins, rest skip silently.
    if not await _claim_dedupe_slot(entry_after.id):
        return

    # 4. Resolve affected staff list per change_type.
    affected_staff_ids: list[Any] = []
    if change_type == "staff_reassigned":
        if entry_before.staff_id is not None:
            affected_staff_ids.append(entry_before.staff_id)
        if (
            entry_after.staff_id is not None
            and entry_after.staff_id != entry_before.staff_id
        ):
            affected_staff_ids.append(entry_after.staff_id)
    elif change_type == "time_changed":
        if entry_after.staff_id is not None:
            affected_staff_ids.append(entry_after.staff_id)
    else:
        # Unknown change_type — nothing to do.
        return

    # 5. Per-staff fan-out.
    for staff_id in affected_staff_ids:
        await _dispatch_to_staff(
            db,
            staff_id=staff_id,
            entry_before=entry_before,
            entry_after=entry_after,
            change_type=change_type,
        )


async def _dispatch_to_staff(
    db: AsyncSession,
    *,
    staff_id: Any,
    entry_before: Any,
    entry_after: Any,
    change_type: str,
) -> None:
    """Send the per-staff SMS or write the appropriate skip audit row.

    Honours:
      - ``staff.weekly_roster_sms_enabled`` opt-in (R14a.4 — flag
        defaults to ``false`` per Phase 1 migration 0203).
      - ``staff.phone is not None`` precondition.

    Failures of the underlying ``send_sms`` (provider error, no
    active provider) audit ``roster.change_sms_skipped`` reason=
    ``send_failed`` and are not re-raised — the DLQ helper inside
    ``send_sms`` records the failure for replay.
    """
    staff = await db.get(StaffMember, staff_id)
    if staff is None:
        # Defensive — should not happen because the FK constrains
        # schedule_entries.staff_id, but a deleted staff would land
        # here. Audit so the reconciliation tooling can spot it.
        await write_audit_log(
            session=db,
            org_id=entry_after.org_id,
            action="roster.change_sms_skipped",
            entity_type="schedule_entry",
            entity_id=entry_after.id,
            after_value={
                "schedule_entry_id": str(entry_after.id),
                "staff_id": str(staff_id),
                "change_type": change_type,
                "reason": "staff_not_found",
            },
        )
        return

    if not staff.weekly_roster_sms_enabled:
        await write_audit_log(
            session=db,
            org_id=entry_after.org_id,
            action="roster.change_sms_skipped",
            entity_type="schedule_entry",
            entity_id=entry_after.id,
            after_value={
                "schedule_entry_id": str(entry_after.id),
                "staff_id": str(staff_id),
                "change_type": change_type,
                "reason": "opt_out",
            },
        )
        return

    if not staff.phone:
        await write_audit_log(
            session=db,
            org_id=entry_after.org_id,
            action="roster.change_sms_skipped",
            entity_type="schedule_entry",
            entity_id=entry_after.id,
            after_value={
                "schedule_entry_id": str(entry_after.id),
                "staff_id": str(staff_id),
                "change_type": change_type,
                "reason": "no_phone",
            },
        )
        return

    body = compose_change_sms_body(
        entry_before, entry_after, change_type, staff,
    )
    if not body:
        # Unknown change_type slipped through — audit + skip.
        await write_audit_log(
            session=db,
            org_id=entry_after.org_id,
            action="roster.change_sms_skipped",
            entity_type="schedule_entry",
            entity_id=entry_after.id,
            after_value={
                "schedule_entry_id": str(entry_after.id),
                "staff_id": str(staff_id),
                "change_type": change_type,
                "reason": "unknown_change_type",
            },
        )
        return

    ok = False
    try:
        result = await send_sms(
            db,
            to_phone=staff.phone,
            body=body,
            dlq_task_name="roster_change_sms",
            dlq_task_args={
                "schedule_entry_id": str(entry_after.id),
                "staff_id": str(staff_id),
                "change_type": change_type,
            },
            org_id=entry_after.org_id,
        )
        ok = bool(getattr(result, "ok", False))
    except Exception:  # noqa: BLE001 - send_sms failures are best-effort.
        logger.exception(
            "roster_change_sms: send_sms raised entry=%s staff=%s",
            entry_after.id, staff_id,
        )
        ok = False

    if ok:
        await write_audit_log(
            session=db,
            org_id=entry_after.org_id,
            action="roster.change_sms_sent",
            entity_type="schedule_entry",
            entity_id=entry_after.id,
            after_value={
                "schedule_entry_id": str(entry_after.id),
                "staff_id": str(staff_id),
                "change_type": change_type,
            },
        )
    else:
        await write_audit_log(
            session=db,
            org_id=entry_after.org_id,
            action="roster.change_sms_skipped",
            entity_type="schedule_entry",
            entity_id=entry_after.id,
            after_value={
                "schedule_entry_id": str(entry_after.id),
                "staff_id": str(staff_id),
                "change_type": change_type,
                "reason": "send_failed",
            },
        )
