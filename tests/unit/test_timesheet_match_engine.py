# Feature: staff-timesheets
"""Unit tests for app.modules.timesheets.match_engine — match_clock_to_roster() + round_time().

Pure unit tests — no DB required. Tests use ScheduleEntryData + ClockEntryData
dataclasses directly with constructed datetime values.

Validates: Requirements 8.1, 8.2, 8.3.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.modules.timesheets.match_engine import (
    ClockEntryData,
    MatchResult,
    MatchSettings,
    ScheduleEntryData,
    match_clock_to_roster,
    round_time,
)


def _settings(
    policy: str = "pay_actual",
    rounding: int = 1,
    direction: str = "nearest",
    early_grace: int = 10,
    late_grace: int = 10,
) -> MatchSettings:
    return MatchSettings(
        match_policy=policy,
        clock_rounding_minutes=rounding,
        clock_rounding_direction=direction,
        early_grace_minutes=early_grace,
        late_grace_minutes=late_grace,
    )


def _schedule(start: datetime, end: datetime) -> ScheduleEntryData:
    duration = int((end - start).total_seconds() // 60)
    return ScheduleEntryData(id=uuid.uuid4(), start_time=start, end_time=end, duration_minutes=duration)


def _clock(clock_in: datetime, clock_out: datetime | None) -> ClockEntryData:
    if clock_out:
        worked = int((clock_out - clock_in).total_seconds() // 60)
    else:
        worked = 0
    return ClockEntryData(id=uuid.uuid4(), clock_in_at=clock_in, clock_out_at=clock_out, worked_minutes=worked)


class TestPayActualPolicy:
    """(a) pay_actual policy — returns worked_minutes unchanged regardless of schedule."""

    def test_matched_entry_uses_actual_minutes(self):
        sched = _schedule(datetime(2024, 6, 10, 9, 0), datetime(2024, 6, 10, 17, 0))
        clock = _clock(datetime(2024, 6, 10, 9, 0), datetime(2024, 6, 10, 16, 30))

        result = match_clock_to_roster(clock, [sched], _settings(policy="pay_actual"))

        assert result.matched_minutes == clock.worked_minutes
        assert result.matched_minutes == 450  # 7.5 hours
        assert result.schedule_entry_id == sched.id
        assert result.match_type in ("exact", "grace")

    def test_unmatched_entry_uses_actual_minutes(self):
        clock = _clock(datetime(2024, 6, 10, 9, 0), datetime(2024, 6, 10, 13, 0))

        result = match_clock_to_roster(clock, [], _settings(policy="pay_actual"))

        assert result.matched_minutes == 240
        assert result.match_type == "unmatched"


class TestRoundToRosterPolicy:
    """(b) round_to_roster policy — matched entry uses shift duration, unmatched uses actual."""

    def test_matched_entry_uses_shift_duration(self):
        sched = _schedule(datetime(2024, 6, 10, 9, 0), datetime(2024, 6, 10, 17, 0))  # 480 min
        # Clock in matches schedule start, but leaves 30 min early
        clock = _clock(datetime(2024, 6, 10, 9, 0), datetime(2024, 6, 10, 16, 30))  # 450 min

        result = match_clock_to_roster(clock, [sched], _settings(policy="round_to_roster"))

        # Even though they worked 450 min, pays the full rostered 480
        assert result.matched_minutes == 480
        assert result.schedule_entry_id == sched.id

    def test_unmatched_entry_uses_actual_minutes(self):
        clock = _clock(datetime(2024, 6, 10, 9, 0), datetime(2024, 6, 10, 13, 0))

        result = match_clock_to_roster(clock, [], _settings(policy="round_to_roster"))

        assert result.matched_minutes == 240  # actual worked minutes
        assert result.match_type == "unmatched"


class TestActualRoundedPolicy:
    """(c) actual_rounded policy — applies rounding to clock times, computes from rounded."""

    def test_rounds_clock_times_and_computes_duration(self):
        sched = _schedule(datetime(2024, 6, 10, 9, 0), datetime(2024, 6, 10, 17, 0))
        # Clock in at 9:03, clock out at 16:57 — with 15-min rounding 'nearest':
        # 9:03 rounds to 9:00, 16:57 rounds to 17:00 → 480 min
        clock = _clock(datetime(2024, 6, 10, 9, 3), datetime(2024, 6, 10, 16, 57))

        settings = _settings(policy="actual_rounded", rounding=15, direction="nearest")
        result = match_clock_to_roster(clock, [sched], settings)

        assert result.matched_minutes == 480  # 9:00 to 17:00
        assert result.schedule_entry_id == sched.id

    def test_unmatched_with_rounding(self):
        """Unmatched entry with actual_rounded still applies rounding."""
        # No schedule — clock 9:07 to 13:08 with 15-min nearest rounding
        # 9:07 rounds to 9:00, 13:08 rounds to 13:15 → 255 min
        clock = _clock(datetime(2024, 6, 10, 9, 7), datetime(2024, 6, 10, 13, 8))

        settings = _settings(policy="actual_rounded", rounding=15, direction="nearest")
        result = match_clock_to_roster(clock, [], settings)

        assert result.matched_minutes == 255  # 9:00 to 13:15
        assert result.match_type == "rounded"


class TestGraceWindow:
    """(d) Grace window — clock_in within early_grace matches, outside is unmatched."""

    def test_clock_within_early_grace_matches(self):
        sched = _schedule(datetime(2024, 6, 10, 9, 0), datetime(2024, 6, 10, 17, 0))
        # Clock in 5 min early (within 10 min early_grace)
        clock = _clock(datetime(2024, 6, 10, 8, 55), datetime(2024, 6, 10, 17, 0))

        result = match_clock_to_roster(clock, [sched], _settings(early_grace=10, late_grace=10))

        assert result.schedule_entry_id == sched.id
        assert result.match_type == "grace"

    def test_clock_within_late_grace_matches(self):
        sched = _schedule(datetime(2024, 6, 10, 9, 0), datetime(2024, 6, 10, 17, 0))
        # Clock in 5 min late (within 10 min late_grace)
        clock = _clock(datetime(2024, 6, 10, 9, 5), datetime(2024, 6, 10, 17, 0))

        result = match_clock_to_roster(clock, [sched], _settings(early_grace=10, late_grace=10))

        assert result.schedule_entry_id == sched.id
        assert result.match_type == "grace"

    def test_clock_outside_grace_is_unmatched(self):
        sched = _schedule(datetime(2024, 6, 10, 9, 0), datetime(2024, 6, 10, 17, 0))
        # Clock in 15 min early (outside 10 min early_grace)
        clock = _clock(datetime(2024, 6, 10, 8, 45), datetime(2024, 6, 10, 17, 0))

        result = match_clock_to_roster(clock, [sched], _settings(early_grace=10, late_grace=10))

        assert result.schedule_entry_id is None
        assert result.match_type == "unmatched"


class TestRoundTime:
    """(e) round_time with nearest/up/down at 15-min intervals."""

    def test_nearest_rounds_down_when_below_half(self):
        t = datetime(2024, 6, 10, 9, 7)  # 7 min past → rounds down to :00
        assert round_time(t, 15, "nearest") == datetime(2024, 6, 10, 9, 0)

    def test_nearest_rounds_up_when_at_or_above_half(self):
        t = datetime(2024, 6, 10, 9, 8)  # 8 min past (>= 7.5) → rounds up to :15
        assert round_time(t, 15, "nearest") == datetime(2024, 6, 10, 9, 15)

    def test_up_always_rounds_up(self):
        t = datetime(2024, 6, 10, 9, 1)  # 1 min past → rounds up to :15
        assert round_time(t, 15, "up") == datetime(2024, 6, 10, 9, 15)

    def test_down_always_rounds_down(self):
        t = datetime(2024, 6, 10, 9, 14)  # 14 min past → rounds down to :00
        assert round_time(t, 15, "down") == datetime(2024, 6, 10, 9, 0)

    def test_on_boundary_stays_unchanged(self):
        t = datetime(2024, 6, 10, 9, 15)
        assert round_time(t, 15, "nearest") == datetime(2024, 6, 10, 9, 15)
        assert round_time(t, 15, "up") == datetime(2024, 6, 10, 9, 15)
        assert round_time(t, 15, "down") == datetime(2024, 6, 10, 9, 15)

    def test_30_min_intervals(self):
        t = datetime(2024, 6, 10, 9, 20)
        assert round_time(t, 30, "nearest") == datetime(2024, 6, 10, 9, 30)
        assert round_time(t, 30, "down") == datetime(2024, 6, 10, 9, 0)
        assert round_time(t, 30, "up") == datetime(2024, 6, 10, 9, 30)

    def test_5_min_intervals(self):
        t = datetime(2024, 6, 10, 9, 13)
        assert round_time(t, 5, "nearest") == datetime(2024, 6, 10, 9, 15)
        assert round_time(t, 5, "down") == datetime(2024, 6, 10, 9, 10)
        assert round_time(t, 5, "up") == datetime(2024, 6, 10, 9, 15)


class TestNoScheduleEntries:
    """(f) No schedule entries → unmatched result."""

    def test_no_schedule_returns_unmatched(self):
        clock = _clock(datetime(2024, 6, 10, 9, 0), datetime(2024, 6, 10, 17, 0))

        result = match_clock_to_roster(clock, [], _settings())

        assert result.schedule_entry_id is None
        assert result.match_type == "unmatched"
        assert result.matched_minutes == clock.worked_minutes


class TestRoundTimeInterval1:
    """(g) round_time with interval=1 → returns time unchanged."""

    def test_interval_1_returns_unchanged(self):
        t = datetime(2024, 6, 10, 9, 7, 33)
        result = round_time(t, 1, "nearest")
        assert result == t

    def test_interval_1_down_returns_unchanged(self):
        t = datetime(2024, 6, 10, 14, 22, 15)
        assert round_time(t, 1, "down") == t

    def test_interval_1_up_returns_unchanged(self):
        t = datetime(2024, 6, 10, 14, 22, 15)
        assert round_time(t, 1, "up") == t


class TestMultipleScheduleEntries:
    """(h) Multiple schedule entries → picks closest match."""

    def test_picks_closest_schedule_entry(self):
        sched_morning = _schedule(datetime(2024, 6, 10, 6, 0), datetime(2024, 6, 10, 14, 0))
        sched_afternoon = _schedule(datetime(2024, 6, 10, 14, 0), datetime(2024, 6, 10, 22, 0))

        # Clock in at 13:55 — within grace of afternoon (14:00) start, and also
        # beyond the morning shift end. Closest schedule start is 14:00 (5 min away).
        clock = _clock(datetime(2024, 6, 10, 13, 55), datetime(2024, 6, 10, 22, 0))

        settings = _settings(early_grace=10, late_grace=10)
        result = match_clock_to_roster(clock, [sched_morning, sched_afternoon], settings)

        assert result.schedule_entry_id == sched_afternoon.id
        assert result.match_type == "grace"

    def test_exact_match_preferred_over_grace(self):
        sched_a = _schedule(datetime(2024, 6, 10, 9, 0), datetime(2024, 6, 10, 17, 0))
        sched_b = _schedule(datetime(2024, 6, 10, 9, 5), datetime(2024, 6, 10, 17, 5))

        # Clock in at exactly 9:00 — matches sched_a exactly and sched_b via grace
        clock = _clock(datetime(2024, 6, 10, 9, 0), datetime(2024, 6, 10, 17, 0))

        settings = _settings(early_grace=10, late_grace=10)
        result = match_clock_to_roster(clock, [sched_a, sched_b], settings)

        # sched_a is closer (diff=0) vs sched_b (diff=5 min)
        assert result.schedule_entry_id == sched_a.id
