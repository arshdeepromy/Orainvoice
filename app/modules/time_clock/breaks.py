"""Break-record service: start/end breaks, suggested windows, ERA s69ZD compliance.

Implements task B4 from `.kiro/specs/staff-management-p3`. Public surface:

  - :func:`start_break` — insert a ``break_records`` row keyed to an open
    ``time_clock_entries`` parent. Writes audit ``break.started``.
  - :func:`end_break` — close a break, compute ``minutes``, and bump the
    parent entry's ``break_minutes`` aggregator by that count when the
    break_type is ``meal_unpaid`` (R7.3 — meal-unpaid breaks deduct
    from worked time on clock-out close). Writes audit ``break.ended``.
  - :func:`suggest_break_windows` — pure helper that returns the ERA
    s69ZD-aligned suggested break windows for a shift's start/end pair
    (R7.2). Used by the schedule-create flow to surface chips on the
    Hours tab.
  - :func:`validate_era_s69zd_breaks` — pure helper for the timesheet
    approval UI's "warning chip" (R7.4) — given a shift's worked
    minutes plus the list of break records actually recorded, returns
    a dict ``{compliant, missing_breaks, message}`` describing whether
    the legal minimum was met.

Project conventions (project-overview.md):
  - All write paths use ``await db.flush()`` then
    ``await db.refresh(obj)`` (P1-N15) — never ``commit()`` because
    ``get_db_session`` runs the transaction with ``session.begin()``.
  - Audit rows go through :func:`app.core.audit.write_audit_log`
    against the ``audit_log`` table (P3-N2: singular).

ERA s69ZD thresholds — mirrored against R7.2:
  - Shift ≥ 4h → 1 paid 10-min rest break at the midpoint.
  - Shift ≥ 6h → 1 paid 10-min rest + 1 unpaid 30-min meal break.
  - Shift ≥ 10h → 2 paid 10-min rests + 1 unpaid 30-min meal.

The thresholds are evaluated bottom-up: a 12h shift triggers the 10h+
band (2 rests + meal), not all three bands stacked. This matches both
the s69ZD legal text and the spec's R7.2 wording.

**Validates: Requirements R7 — Staff Management Phase 3 task B4**
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.time_clock.models import BreakRecord, TimeClockEntry
from app.modules.time_clock.service import (
    InvalidActionError,
    TimeClockEntryNotFoundError,
    TimeClockServiceError,
)


logger = logging.getLogger(__name__)


__all__ = [
    "BreakNotFoundError",
    "BreakAlreadyEndedError",
    "InvalidBreakTypeError",
    "start_break",
    "end_break",
    "suggest_break_windows",
    "validate_era_s69zd_breaks",
]


# ---------------------------------------------------------------------------
# Service-layer exceptions
# ---------------------------------------------------------------------------


class BreakNotFoundError(TimeClockServiceError):
    """Raised when a referenced ``break_record_id`` does not exist or
    belongs to a different org. Router maps to HTTP 404.
    """


class BreakAlreadyEndedError(TimeClockServiceError):
    """Raised by :func:`end_break` when the break already has an
    ``end_at`` set — closing twice is a no-op caller bug. Router maps
    to HTTP 409.
    """


class InvalidBreakTypeError(TimeClockServiceError):
    """Raised by :func:`start_break` when ``break_type`` is not one of
    the DB-CHECK enum values (``rest_paid`` / ``meal_unpaid``). Router
    maps to HTTP 422.
    """


# ---------------------------------------------------------------------------
# ERA s69ZD constants
# ---------------------------------------------------------------------------

# Per R7.2 — the ERA s69ZD-aligned thresholds and break durations.
# Values are in minutes so they line up directly with the
# ``BreakRecord.minutes`` integer column.
_REST_BREAK_MINUTES = 10
_MEAL_BREAK_MINUTES = 30
_THRESHOLD_REST_MIN = 240  # 4h — 1 rest required
_THRESHOLD_MEAL_MIN = 360  # 6h — rest + meal required
_THRESHOLD_LONG_MIN = 600  # 10h — 2 rests + meal required

_VALID_BREAK_TYPES = ("rest_paid", "meal_unpaid")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _break_to_dict(break_record: BreakRecord) -> dict[str, Any]:
    """Serialise a :class:`BreakRecord` for the audit log
    ``before_value`` / ``after_value`` columns. Datetime / UUID values
    are cast to strings so the audit serialiser doesn't choke.
    """
    return {
        "id": str(break_record.id),
        "time_clock_entry_id": str(break_record.time_clock_entry_id),
        "break_type": break_record.break_type,
        "start_at": (
            break_record.start_at.isoformat() if break_record.start_at else None
        ),
        "end_at": (
            break_record.end_at.isoformat() if break_record.end_at else None
        ),
        "minutes": break_record.minutes,
    }


def _required_breaks_for_shift(worked_minutes: int) -> dict[str, int]:
    """Return the ERA s69ZD-required break counts for a shift of the
    given worked-minutes length. Keys: ``rest_paid``, ``meal_unpaid``.

    Bands:
      - ``< 4h`` → 0 rest, 0 meal.
      - ``[4h, 6h)`` → 1 rest, 0 meal.
      - ``[6h, 10h)`` → 1 rest, 1 meal.
      - ``>= 10h`` → 2 rests, 1 meal.
    """
    if worked_minutes < _THRESHOLD_REST_MIN:
        return {"rest_paid": 0, "meal_unpaid": 0}
    if worked_minutes < _THRESHOLD_MEAL_MIN:
        return {"rest_paid": 1, "meal_unpaid": 0}
    if worked_minutes < _THRESHOLD_LONG_MIN:
        return {"rest_paid": 1, "meal_unpaid": 1}
    return {"rest_paid": 2, "meal_unpaid": 1}


def _minutes_for_break_type(break_type: str) -> int:
    """Return the ERA-mandated minimum minute count for a break type."""
    return (
        _REST_BREAK_MINUTES if break_type == "rest_paid" else _MEAL_BREAK_MINUTES
    )


# ---------------------------------------------------------------------------
# Public API: start a break
# ---------------------------------------------------------------------------


async def start_break(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    time_clock_entry_id: uuid.UUID,
    break_type: str,
    start_at: datetime | None = None,
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> BreakRecord:
    """Insert a ``break_records`` row keyed to an open
    :class:`TimeClockEntry` parent.

    Args:
      org_id: tenant org for the audit + org_id column.
      time_clock_entry_id: parent ``time_clock_entries.id``. Must
        belong to ``org_id`` and must currently be open
        (``clock_out_at IS NULL``) — closed entries can't take new
        breaks; a closed shift is final.
      break_type: one of ``rest_paid`` / ``meal_unpaid`` (R2 CHECK
        enum).
      start_at: defaults to ``datetime.now(timezone.utc)`` so the
        kiosk / mobile path can leave it unset. Supplied explicitly by
        admin back-dated edits.
      user_id: acting user for the audit row (``None`` for kiosk/system).
      ip_address: client IP for the audit row.

    Returns:
      The freshly-inserted :class:`BreakRecord`.

    Raises:
      :class:`InvalidBreakTypeError`: when ``break_type`` is not in
        the CHECK enum.
      :class:`TimeClockEntryNotFoundError`: when the parent entry
        doesn't exist or belongs to a different org.
      :class:`InvalidActionError`: when the parent entry is already
        closed (``clock_out_at`` is set) — a final shift can't take
        new breaks.
    """
    if break_type not in _VALID_BREAK_TYPES:
        raise InvalidBreakTypeError(
            f"invalid_break_type: {break_type!r} not in {_VALID_BREAK_TYPES}"
        )

    parent = await db.get(TimeClockEntry, time_clock_entry_id)
    if parent is None or parent.org_id != org_id:
        raise TimeClockEntryNotFoundError("time_clock_entry_not_found")
    if parent.clock_out_at is not None:
        raise InvalidActionError("entry_already_closed")

    when = start_at if start_at is not None else datetime.now(timezone.utc)
    record = BreakRecord(
        org_id=org_id,
        time_clock_entry_id=time_clock_entry_id,
        break_type=break_type,
        start_at=when,
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="break.started",
        entity_type="break_record",
        entity_id=record.id,
        after_value=_break_to_dict(record),
        ip_address=ip_address,
    )
    return record


# ---------------------------------------------------------------------------
# Public API: end a break
# ---------------------------------------------------------------------------


async def end_break(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    break_record_id: uuid.UUID,
    end_at: datetime | None = None,
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> BreakRecord:
    """Close an open break record.

    Sets ``end_at`` (defaulting to ``datetime.now(timezone.utc)``),
    computes ``minutes = (end_at - start_at) // 60``, and — when the
    break_type is ``meal_unpaid`` — bumps the parent entry's
    ``break_minutes`` aggregator by that count so the eventual
    ``worked_minutes = (clock_out_at - clock_in_at) - break_minutes``
    calculation deducts the meal break (R7.3).

    ``rest_paid`` breaks DO NOT bump ``break_minutes`` because they
    are paid time and shouldn't be deducted from worked minutes.

    Args:
      org_id: tenant org for the audit row.
      break_record_id: the ``break_records.id`` to close.
      end_at: defaults to ``datetime.now(timezone.utc)``.
      user_id: acting user for the audit row.
      ip_address: client IP for the audit row.

    Returns:
      The updated :class:`BreakRecord` with ``end_at`` and
      ``minutes`` populated.

    Raises:
      :class:`BreakNotFoundError`: when the break does not exist or
        is in another org.
      :class:`BreakAlreadyEndedError`: when ``end_at`` is already set.
    """
    record = await db.get(BreakRecord, break_record_id)
    if record is None or record.org_id != org_id:
        raise BreakNotFoundError("break_record_not_found")
    if record.end_at is not None:
        raise BreakAlreadyEndedError("break_already_ended")

    before = _break_to_dict(record)

    when = end_at if end_at is not None else datetime.now(timezone.utc)
    elapsed_seconds = (when - record.start_at).total_seconds()
    minutes = max(0, int(elapsed_seconds // 60))

    record.end_at = when
    record.minutes = minutes

    # R7.3 — only meal_unpaid breaks deduct from worked minutes.
    if record.break_type == "meal_unpaid":
        parent = await db.get(TimeClockEntry, record.time_clock_entry_id)
        if parent is not None:
            parent.break_minutes = (parent.break_minutes or 0) + minutes
            # Re-compute parent worked_minutes when the shift is
            # already closed (rare — typically breaks are closed
            # before clock-out, but admin manual flows can sequence
            # things differently). The standard close path on
            # service._perform_clock_action uses the latest
            # break_minutes when computing worked_minutes, so this
            # branch only matters for back-dated edits.
            if parent.clock_out_at is not None:
                elapsed = parent.clock_out_at - parent.clock_in_at
                elapsed_minutes = int(elapsed.total_seconds() // 60)
                parent.worked_minutes = max(
                    0, elapsed_minutes - parent.break_minutes
                )

    await db.flush()
    await db.refresh(record)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="break.ended",
        entity_type="break_record",
        entity_id=record.id,
        before_value=before,
        after_value=_break_to_dict(record),
        ip_address=ip_address,
    )
    return record


# ---------------------------------------------------------------------------
# Public API: suggest break windows for a planned shift (R7.2)
# ---------------------------------------------------------------------------


def suggest_break_windows(
    shift_start: datetime,
    shift_end: datetime,
) -> list[dict[str, Any]]:
    """Return the ERA s69ZD-aligned suggested break windows for a shift.

    Per R7.2:
      - Shift ≥ 4h → 1 paid 10-min rest at the midpoint.
      - Shift ≥ 6h → 1 paid rest + 1 unpaid 30-min meal.
      - Shift ≥ 10h → 2 paid rests + 1 unpaid meal.

    The windows are spaced so they're roughly evenly distributed
    across the shift (rests near the quarter / three-quarter marks,
    meal near the midpoint). Times returned are timezone-aware
    datetimes derived from the input pair.

    Returns:
      A list of dicts each shaped:
      ``{"type": "rest_paid"|"meal_unpaid", "start": dt, "end": dt,
      "minutes": int}``.
      The list is empty when the shift is shorter than 4h.

    The order is deterministic — windows are sorted by ``start``
    ascending so the frontend can render them in shift-order without
    extra sort logic.
    """
    if shift_end <= shift_start:
        return []

    duration = shift_end - shift_start
    duration_minutes = int(duration.total_seconds() // 60)

    if duration_minutes < _THRESHOLD_REST_MIN:
        return []

    suggestions: list[dict[str, Any]] = []

    if duration_minutes >= _THRESHOLD_LONG_MIN:
        # 10h+ — 2 paid rests at ~quarter / three-quarter marks +
        # 1 unpaid meal at the midpoint.
        first_rest_offset = duration / 4
        meal_offset = duration / 2
        second_rest_offset = duration * 3 / 4
        suggestions.extend(
            [
                _make_suggestion(
                    shift_start, first_rest_offset,
                    "rest_paid", _REST_BREAK_MINUTES,
                ),
                _make_suggestion(
                    shift_start, meal_offset,
                    "meal_unpaid", _MEAL_BREAK_MINUTES,
                ),
                _make_suggestion(
                    shift_start, second_rest_offset,
                    "rest_paid", _REST_BREAK_MINUTES,
                ),
            ]
        )
    elif duration_minutes >= _THRESHOLD_MEAL_MIN:
        # 6h–10h — 1 paid rest at ~third + 1 unpaid meal at ~two-thirds.
        rest_offset = duration / 3
        meal_offset = duration * 2 / 3
        suggestions.extend(
            [
                _make_suggestion(
                    shift_start, rest_offset,
                    "rest_paid", _REST_BREAK_MINUTES,
                ),
                _make_suggestion(
                    shift_start, meal_offset,
                    "meal_unpaid", _MEAL_BREAK_MINUTES,
                ),
            ]
        )
    else:
        # 4h–6h — 1 paid rest at the midpoint.
        rest_offset = duration / 2
        suggestions.append(
            _make_suggestion(
                shift_start, rest_offset,
                "rest_paid", _REST_BREAK_MINUTES,
            ),
        )

    suggestions.sort(key=lambda s: s["start"])
    return suggestions


def _make_suggestion(
    shift_start: datetime,
    offset: timedelta,
    break_type: str,
    minutes: int,
) -> dict[str, Any]:
    """Build one suggested-break dict centred on ``shift_start + offset``.

    The midpoint of the break is placed at the offset so the start
    sits ``minutes/2`` earlier and the end ``minutes/2`` later.
    """
    midpoint = shift_start + offset
    half = timedelta(minutes=minutes / 2)
    return {
        "type": break_type,
        "start": midpoint - half,
        "end": midpoint + half,
        "minutes": minutes,
    }


# ---------------------------------------------------------------------------
# Public API: ERA s69ZD compliance check (R7.4)
# ---------------------------------------------------------------------------


def validate_era_s69zd_breaks(
    worked_minutes: int,
    recorded_breaks: Iterable[Any],
) -> dict[str, Any]:
    """Check whether the recorded breaks meet the ERA s69ZD legal
    minimum for a shift of ``worked_minutes`` length.

    Per R7.4 — the timesheet-approval UI surfaces a warning chip on
    any approved-week's shifts that had less than the legally required
    break time recorded. This helper produces the chip's data.

    Args:
      worked_minutes: shift length in minutes (typically
        ``TimeClockEntry.worked_minutes`` post clock-out, OR a
        scheduled-shift duration when validating before-the-fact).
      recorded_breaks: iterable of break records — accepts any object
        with a ``break_type`` attribute OR a dict with a
        ``break_type`` key, AND optionally a ``minutes`` attribute /
        key for duration-checking. ``minutes`` defaults to the legal
        minimum for the type when missing (so an in-progress break
        without an end_at still counts as a recorded break).

    Returns:
      ``{
        "compliant": bool,
        "missing_breaks": list[str],   # break types still needed
        "message": str,                # human-readable summary
      }``

    The ``missing_breaks`` list is shaped like
    ``["rest_paid", "meal_unpaid"]`` — repeated entries when more than
    one of a type is needed (e.g. a 12h shift missing both rests
    yields ``["rest_paid", "rest_paid"]``).
    """
    required = _required_breaks_for_shift(int(worked_minutes))

    # Tally recorded breaks by type — only count ones that meet the
    # minimum-duration threshold for that type. A 5-min "rest" doesn't
    # discharge the 10-min legal rest break.
    recorded_counts: dict[str, int] = {"rest_paid": 0, "meal_unpaid": 0}
    for rec in recorded_breaks:
        bt = _read_field(rec, "break_type")
        if bt not in _VALID_BREAK_TYPES:
            continue
        minutes_value = _read_field(rec, "minutes")
        if minutes_value is None:
            # In-progress break — count as if it'll meet the minimum.
            counted_minutes = _minutes_for_break_type(bt)
        else:
            counted_minutes = int(minutes_value)
        if counted_minutes >= _minutes_for_break_type(bt):
            recorded_counts[bt] += 1

    missing_breaks: list[str] = []
    for break_type in _VALID_BREAK_TYPES:
        deficit = required[break_type] - recorded_counts[break_type]
        if deficit > 0:
            missing_breaks.extend([break_type] * deficit)

    compliant = not missing_breaks

    if compliant:
        message = (
            f"Compliant: {worked_minutes}min shift met the ERA s69ZD "
            f"minimum break requirement."
        )
    else:
        # Compose a friendly missing list for the warning chip.
        labels = []
        rest_missing = missing_breaks.count("rest_paid")
        meal_missing = missing_breaks.count("meal_unpaid")
        if rest_missing:
            labels.append(
                f"{rest_missing}× paid rest"
                + ("s" if rest_missing > 1 else "")
            )
        if meal_missing:
            labels.append(
                f"{meal_missing}× unpaid meal"
                + ("s" if meal_missing > 1 else "")
            )
        message = (
            f"Non-compliant: {worked_minutes}min shift is short "
            f"{', '.join(labels)} per ERA s69ZD."
        )

    return {
        "compliant": compliant,
        "missing_breaks": missing_breaks,
        "message": message,
    }


def _read_field(obj: Any, name: str) -> Any:
    """Read ``name`` from either a dict-like or attr-like object.

    Used by :func:`validate_era_s69zd_breaks` so callers can pass a
    list of ORM rows OR a list of dicts (the timesheet-approval UI
    serialises rows on the frontend; the backend prefers ORM objects).
    """
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)
