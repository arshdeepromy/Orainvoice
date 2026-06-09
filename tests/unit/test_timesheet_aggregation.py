# Feature: staff-timesheets
"""Unit tests for app.modules.timesheets.aggregation — compute_timesheet_from_data().

Pure unit tests — no DB required. Tests use ScheduleEntryData + ClockEntryData
dataclasses directly.

Validates: Requirements 1.9, 1.10, 8.4.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

import pytest

from app.modules.timesheets.aggregation import (
    TimesheetComputation,
    compute_timesheet_from_data,
)
from app.modules.timesheets.match_engine import (
    ClockEntryData,
    MatchSettings,
    ScheduleEntryData,
)


def _make_settings(
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


def _make_schedule(
    start: datetime,
    end: datetime,
    entry_id: uuid.UUID | None = None,
) -> ScheduleEntryData:
    eid = entry_id or uuid.uuid4()
    duration = int((end - start).total_seconds() // 60)
    return ScheduleEntryData(id=eid, start_time=start, end_time=end, duration_minutes=duration)


def _make_clock(
    clock_in: datetime,
    clock_out: datetime | None,
    entry_id: uuid.UUID | None = None,
) -> ClockEntryData:
    eid = entry_id or uuid.uuid4()
    if clock_out:
        worked = int((clock_out - clock_in).total_seconds() // 60)
    else:
        worked = 0
    return ClockEntryData(id=eid, clock_in_at=clock_in, clock_out_at=clock_out, worked_minutes=worked)


class TestComputeTimesheetFromData:
    """Tests for compute_timesheet_from_data()."""

    def test_normal_shift_with_matching_clock(self):
        """(a) Normal shift with matching clock → correct rostered/actual/ordinary minutes."""
        shift_start = datetime(2024, 6, 10, 9, 0)
        shift_end = datetime(2024, 6, 10, 17, 0)
        schedule = [_make_schedule(shift_start, shift_end)]

        clock_in = datetime(2024, 6, 10, 9, 0)
        clock_out = datetime(2024, 6, 10, 17, 0)
        clocks = [_make_clock(clock_in, clock_out)]

        settings = _make_settings(policy="pay_actual")

        result = compute_timesheet_from_data(
            schedule_entries=schedule,
            clock_entries=clocks,
            settings=settings,
            period_start=date(2024, 6, 10),
            period_end=date(2024, 6, 16),
        )

        assert result.rostered_minutes == 480  # 8 hours
        assert result.actual_minutes == 480
        assert result.ordinary_minutes == 480
        # No exceptions for a normal matched shift
        exception_types = [f["type"] for f in result.exception_flags]
        assert "missed_shift" not in exception_types
        assert "unmatched_clock" not in exception_types

    def test_shift_with_no_clock_entry(self):
        """(b) Shift with no clock entry → missed_shift exception flag."""
        shift_start = datetime(2024, 6, 10, 9, 0)
        shift_end = datetime(2024, 6, 10, 17, 0)
        schedule = [_make_schedule(shift_start, shift_end)]

        settings = _make_settings()

        result = compute_timesheet_from_data(
            schedule_entries=schedule,
            clock_entries=[],
            settings=settings,
            period_start=date(2024, 6, 10),
            period_end=date(2024, 6, 16),
        )

        assert result.rostered_minutes == 480
        assert result.actual_minutes == 0
        assert result.ordinary_minutes == 0
        exception_types = [f["type"] for f in result.exception_flags]
        assert "missed_shift" in exception_types

    def test_clock_entry_with_no_matching_shift(self):
        """(c) Clock entry with no matching shift → unmatched_clock exception flag."""
        # No schedule entries
        clock_in = datetime(2024, 6, 10, 9, 0)
        clock_out = datetime(2024, 6, 10, 13, 0)
        clocks = [_make_clock(clock_in, clock_out)]

        settings = _make_settings()

        result = compute_timesheet_from_data(
            schedule_entries=[],
            clock_entries=clocks,
            settings=settings,
            period_start=date(2024, 6, 10),
            period_end=date(2024, 6, 16),
        )

        assert result.actual_minutes == 240
        exception_types = [f["type"] for f in result.exception_flags]
        assert "unmatched_clock" in exception_types

    def test_missing_clock_out(self):
        """(d) Missing clock-out (clock_out_at=None) → missing_clock_out exception flag."""
        shift_start = datetime(2024, 6, 10, 9, 0)
        shift_end = datetime(2024, 6, 10, 17, 0)
        schedule = [_make_schedule(shift_start, shift_end)]

        clock_in = datetime(2024, 6, 10, 9, 0)
        clocks = [_make_clock(clock_in, None)]

        settings = _make_settings()

        result = compute_timesheet_from_data(
            schedule_entries=schedule,
            clock_entries=clocks,
            settings=settings,
            period_start=date(2024, 6, 10),
            period_end=date(2024, 6, 16),
        )

        exception_types = [f["type"] for f in result.exception_flags]
        assert "missing_clock_out" in exception_types

    def test_high_variance_flag(self):
        """(e) High variance (actual > rostered + 60min) → high_variance flag."""
        shift_start = datetime(2024, 6, 10, 9, 0)
        shift_end = datetime(2024, 6, 10, 17, 0)  # 480 min
        schedule = [_make_schedule(shift_start, shift_end)]

        # Clocked for 10 hours — 120 min over rostered 480
        clock_in = datetime(2024, 6, 10, 9, 0)
        clock_out = datetime(2024, 6, 10, 19, 0)  # 600 min
        clocks = [_make_clock(clock_in, clock_out)]

        settings = _make_settings()

        result = compute_timesheet_from_data(
            schedule_entries=schedule,
            clock_entries=clocks,
            settings=settings,
            period_start=date(2024, 6, 10),
            period_end=date(2024, 6, 16),
        )

        assert result.actual_minutes == 600
        assert result.rostered_minutes == 480
        exception_types = [f["type"] for f in result.exception_flags]
        assert "high_variance" in exception_types

    def test_no_high_variance_when_within_threshold(self):
        """No high_variance flag when difference is <= 60 minutes."""
        shift_start = datetime(2024, 6, 10, 9, 0)
        shift_end = datetime(2024, 6, 10, 17, 0)  # 480 min
        schedule = [_make_schedule(shift_start, shift_end)]

        # Clocked for 9 hours — 60 min over rostered (exactly at threshold)
        clock_in = datetime(2024, 6, 10, 9, 0)
        clock_out = datetime(2024, 6, 10, 18, 0)  # 540 min
        clocks = [_make_clock(clock_in, clock_out)]

        settings = _make_settings()

        result = compute_timesheet_from_data(
            schedule_entries=schedule,
            clock_entries=clocks,
            settings=settings,
            period_start=date(2024, 6, 10),
            period_end=date(2024, 6, 16),
        )

        exception_types = [f["type"] for f in result.exception_flags]
        assert "high_variance" not in exception_types

    def test_multiple_shifts_in_period(self):
        """(f) Multiple shifts in period → correct sum of rostered minutes."""
        schedules = [
            _make_schedule(datetime(2024, 6, 10, 9, 0), datetime(2024, 6, 10, 17, 0)),  # 480
            _make_schedule(datetime(2024, 6, 11, 9, 0), datetime(2024, 6, 11, 17, 0)),  # 480
            _make_schedule(datetime(2024, 6, 12, 9, 0), datetime(2024, 6, 12, 13, 0)),  # 240
        ]

        clocks = [
            _make_clock(datetime(2024, 6, 10, 9, 0), datetime(2024, 6, 10, 17, 0)),
            _make_clock(datetime(2024, 6, 11, 9, 0), datetime(2024, 6, 11, 17, 0)),
            _make_clock(datetime(2024, 6, 12, 9, 0), datetime(2024, 6, 12, 13, 0)),
        ]

        settings = _make_settings()

        result = compute_timesheet_from_data(
            schedule_entries=schedules,
            clock_entries=clocks,
            settings=settings,
            period_start=date(2024, 6, 10),
            period_end=date(2024, 6, 16),
        )

        assert result.rostered_minutes == 480 + 480 + 240  # 1200
        assert result.actual_minutes == 1200
        assert result.ordinary_minutes == 1200
