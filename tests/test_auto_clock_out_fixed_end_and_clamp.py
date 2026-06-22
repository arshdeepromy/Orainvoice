"""Unit tests for Task 2.3 — fixed-end helper + clamp/eligibility edges.

Example-based (pytest) coverage of the two pure functions added in Task 2.1 to
``app/tasks/scheduled.py``:

  - ``_fixed_end_minutes_for_date(availability_schedule, on_date)`` — derives the
    fixed-arrangement configured end time (minutes-since-midnight) for a date's
    weekday, reusing the timesheets ``_WEEKDAY_KEYS`` / ``_parse_hhmm`` parsing.
    Covered cases: present / absent / malformed / overnight days, and an
    empty/missing schedule.
  - ``_resolve_auto_clock_out_end(...)`` — the end-time basis hierarchy
    (rostered scheduled shift → fixed day end → elapsed-cap) plus the
    ``[clock_in_at, now]`` clamp edges and the overnight/wrapped fixed shift.

The Hypothesis property tests for the resolver invariants live separately
(Task 2.2); this file deliberately sticks to concrete example cases for the
fixed-end helper and the basis-hierarchy / clamp behaviour.

Requirements: 9.1
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.tasks.scheduled import (
    _fixed_end_minutes_for_date,
    _resolve_auto_clock_out_end,
)


def _utc(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


# 2024-01-01 is a Monday; weekday() == 0 -> "monday".
MONDAY = datetime(2024, 1, 1).date()
TUESDAY = datetime(2024, 1, 2).date()


# ---------------------------------------------------------------------------
# _fixed_end_minutes_for_date
# ---------------------------------------------------------------------------

class TestFixedEndMinutesForDate:
    """Derive the configured fixed end-minutes for a given date's weekday."""

    def test_present_day_returns_end_minutes(self):
        """A weekday with a ``{start, end}`` entry returns end minutes-since-midnight."""
        schedule = {
            "monday": {"start": "09:00", "end": "17:30"},
            "tuesday": {"start": "08:00", "end": "16:00"},
        }
        # 17:30 -> 17*60 + 30 == 1050
        assert _fixed_end_minutes_for_date(schedule, MONDAY) == 1050

    def test_present_day_uses_correct_weekday(self):
        """The lookup is keyed by the date's weekday, not the first entry."""
        schedule = {
            "monday": {"start": "09:00", "end": "17:30"},
            "tuesday": {"start": "08:00", "end": "16:00"},
        }
        # Tuesday end 16:00 -> 16*60 == 960
        assert _fixed_end_minutes_for_date(schedule, TUESDAY) == 960

    def test_absent_weekday_returns_none(self):
        """A weekday with no configured entry yields None."""
        schedule = {"monday": {"start": "09:00", "end": "17:30"}}
        # Tuesday is absent from the schedule.
        assert _fixed_end_minutes_for_date(schedule, TUESDAY) is None

    def test_empty_schedule_returns_none(self):
        assert _fixed_end_minutes_for_date({}, MONDAY) is None

    def test_none_schedule_returns_none(self):
        assert _fixed_end_minutes_for_date(None, MONDAY) is None

    def test_malformed_entry_not_a_dict_returns_none(self):
        """An entry that is not a dict (e.g. a string) is treated as missing."""
        schedule = {"monday": "09:00-17:30"}
        assert _fixed_end_minutes_for_date(schedule, MONDAY) is None

    def test_malformed_entry_missing_end_returns_none(self):
        """An entry dict without an ``end`` key yields None."""
        schedule = {"monday": {"start": "09:00"}}
        assert _fixed_end_minutes_for_date(schedule, MONDAY) is None

    def test_malformed_end_value_returns_none(self):
        """A non-``HH:MM`` end value cannot be parsed and yields None."""
        schedule = {"monday": {"start": "09:00", "end": "not-a-time"}}
        assert _fixed_end_minutes_for_date(schedule, MONDAY) is None

    def test_overnight_day_returns_raw_end_minutes(self):
        """For an overnight shift (end < start) the helper still returns the raw
        end minutes; the next-day wrap is applied later by the resolver."""
        schedule = {"monday": {"start": "22:00", "end": "06:00"}}
        # 06:00 -> 6*60 == 360 (no wrapping at the helper level)
        assert _fixed_end_minutes_for_date(schedule, MONDAY) == 360

    def test_midnight_end_returns_zero(self):
        """A ``00:00`` end parses to 0 minutes (falsy-but-valid), not None."""
        schedule = {"monday": {"start": "16:00", "end": "00:00"}}
        assert _fixed_end_minutes_for_date(schedule, MONDAY) == 0


# ---------------------------------------------------------------------------
# _resolve_auto_clock_out_end — basis hierarchy
# ---------------------------------------------------------------------------

class TestResolveBasisHierarchy:
    """Rostered scheduled shift -> fixed day end -> elapsed cap, in priority."""

    def test_scheduled_end_basis(self):
        """A linked scheduled shift end uses ``scheduled_end + grace``."""
        end = _resolve_auto_clock_out_end(
            clock_in_at=_utc(2024, 1, 1, 8, 0),
            now=_utc(2024, 1, 2, 12, 0),
            after_hours=14,
            grace_minutes=15,
            scheduled_end=_utc(2024, 1, 1, 17, 0),
            fixed_end_minutes=None,
        )
        assert end == _utc(2024, 1, 1, 17, 15)

    def test_scheduled_end_takes_priority_over_fixed(self):
        """When both bases are present the scheduled shift wins."""
        end = _resolve_auto_clock_out_end(
            clock_in_at=_utc(2024, 1, 1, 8, 0),
            now=_utc(2024, 1, 2, 12, 0),
            after_hours=14,
            grace_minutes=15,
            scheduled_end=_utc(2024, 1, 1, 17, 0),
            fixed_end_minutes=20 * 60,  # 20:00 fixed end — must be ignored
        )
        assert end == _utc(2024, 1, 1, 17, 15)

    def test_fixed_end_basis(self):
        """No scheduled shift, fixed end available -> day's fixed end + grace."""
        end = _resolve_auto_clock_out_end(
            clock_in_at=_utc(2024, 1, 1, 8, 0),
            now=_utc(2024, 1, 2, 12, 0),
            after_hours=14,
            grace_minutes=15,
            scheduled_end=None,
            fixed_end_minutes=17 * 60,  # 17:00
        )
        # 17:00 + 15m grace, same calendar day as clock-in.
        assert end == _utc(2024, 1, 1, 17, 15)

    def test_elapsed_cap_basis(self):
        """No scheduled and no fixed end -> ``clock_in_at + after_hours``."""
        end = _resolve_auto_clock_out_end(
            clock_in_at=_utc(2024, 1, 1, 8, 0),
            now=_utc(2024, 1, 3, 0, 0),
            after_hours=14,
            grace_minutes=15,
            scheduled_end=None,
            fixed_end_minutes=None,
        )
        # 08:00 + 14h == 22:00 same day (grace does not apply to the cap).
        assert end == _utc(2024, 1, 1, 22, 0)

    def test_fixed_end_overnight_wraps_to_next_day(self):
        """A fixed end at/before the clock-in time-of-day belongs to the next day."""
        end = _resolve_auto_clock_out_end(
            clock_in_at=_utc(2024, 1, 1, 22, 0),  # 10pm start
            now=_utc(2024, 1, 2, 12, 0),
            after_hours=14,
            grace_minutes=0,
            scheduled_end=None,
            fixed_end_minutes=6 * 60,  # 06:00 — earlier in the day than 22:00
        )
        # Wraps to 06:00 the following calendar day.
        assert end == _utc(2024, 1, 2, 6, 0)


# ---------------------------------------------------------------------------
# _resolve_auto_clock_out_end — clamp edges [clock_in_at, now]
# ---------------------------------------------------------------------------

class TestResolveClampEdges:
    """The resolved end is always clamped into ``[clock_in_at, now]``."""

    def test_clamped_not_before_clock_in(self):
        """A scheduled end earlier than clock-in is clamped up to clock-in."""
        clock_in = _utc(2024, 1, 1, 8, 0)
        end = _resolve_auto_clock_out_end(
            clock_in_at=clock_in,
            now=_utc(2024, 1, 2, 12, 0),
            after_hours=14,
            grace_minutes=0,
            scheduled_end=_utc(2024, 1, 1, 6, 0),  # before clock-in
            fixed_end_minutes=None,
        )
        assert end == clock_in

    def test_clamped_not_after_now(self):
        """A cap end beyond ``now`` is clamped down to ``now``."""
        now = _utc(2024, 1, 1, 20, 0)
        end = _resolve_auto_clock_out_end(
            clock_in_at=_utc(2024, 1, 1, 8, 0),
            now=now,
            after_hours=14,  # 08:00 + 14h == 22:00, beyond now (20:00)
            grace_minutes=0,
            scheduled_end=None,
            fixed_end_minutes=None,
        )
        assert end == now

    def test_scheduled_end_in_future_clamped_to_now(self):
        """A scheduled end (plus grace) in the future is clamped to ``now``."""
        now = _utc(2024, 1, 1, 17, 0)
        end = _resolve_auto_clock_out_end(
            clock_in_at=_utc(2024, 1, 1, 8, 0),
            now=now,
            after_hours=14,
            grace_minutes=30,
            scheduled_end=_utc(2024, 1, 1, 17, 0),  # +30m grace == 17:30 > now
            fixed_end_minutes=None,
        )
        assert end == now

    def test_result_never_before_clock_in_with_zero_window(self):
        """When ``now`` equals ``clock_in_at`` the clamp collapses to that instant."""
        clock_in = _utc(2024, 1, 1, 8, 0)
        end = _resolve_auto_clock_out_end(
            clock_in_at=clock_in,
            now=clock_in,
            after_hours=14,
            grace_minutes=15,
            scheduled_end=_utc(2024, 1, 1, 17, 0),
            fixed_end_minutes=None,
        )
        assert end == clock_in
