"""Timesheet aggregation service — computes rostered/actual/matched minutes.

Aggregates data from schedule_entries and time_clock_entries into a single
TimesheetComputation result that the service layer persists on the Timesheet row.

Code-truth notes:
- ScheduleEntry uses `location_id` (not `branch_id`). Rostered minutes are 
  per-person per-period regardless of location. Branch scoping applies to the
  Timesheet entity via TimeClockEntry.branch_id, not the roster query.
- TimeClockEntry.source column is named `source` (not `clock_in_source`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal
from uuid import UUID

from app.modules.timesheets.match_engine import (
    ClockEntryData,
    MatchResult,
    MatchSettings,
    ScheduleEntryData,
    match_clock_to_roster,
)


@dataclass
class TimesheetComputation:
    """Result of aggregating clock + roster data for one staff in one period."""
    rostered_minutes: int = 0
    actual_minutes: int = 0
    ordinary_minutes: int = 0
    overtime_minutes: int = 0  # Phase C
    public_holiday_minutes: int = 0  # Phase C
    exception_flags: list[dict] = field(default_factory=list)
    matched_entries: list[MatchResult] = field(default_factory=list)


def compute_timesheet_from_data(
    *,
    schedule_entries: list[ScheduleEntryData],
    clock_entries: list[ClockEntryData],
    settings: MatchSettings,
    period_start: date,
    period_end: date,
) -> TimesheetComputation:
    """Pure computation of timesheet aggregation (no DB access).
    
    Steps:
    1. Sum scheduled shift durations → rostered_minutes
    2. Sum worked_minutes from clock entries → actual_minutes
    3. Run match engine on each clock entry
    4. All matched minutes → ordinary_minutes (Phase A; Phase C adds OT/PH)
    5. Detect exceptions (missed shifts, unmatched clocks, missing clock-outs)
    6. Return TimesheetComputation
    """
    result = TimesheetComputation()
    
    # 1. Rostered minutes
    for sched in schedule_entries:
        result.rostered_minutes += sched.duration_minutes
    
    # 2. Actual minutes
    for clock in clock_entries:
        result.actual_minutes += clock.worked_minutes
    
    # 3. Match each clock entry against schedule
    matched_schedule_ids: set[UUID] = set()
    for clock in clock_entries:
        match_result = match_clock_to_roster(clock, schedule_entries, settings)
        result.matched_entries.append(match_result)
        result.ordinary_minutes += match_result.matched_minutes
        if match_result.schedule_entry_id:
            matched_schedule_ids.add(match_result.schedule_entry_id)
    
    # 5. Exception detection
    # Missing clock-outs
    for clock in clock_entries:
        if clock.clock_out_at is None:
            result.exception_flags.append({
                "type": "missing_clock_out",
                "detail": "Staff still clocked in — no clock-out recorded",
                "clock_entry_id": str(clock.id),
            })
    
    # Unmatched clock entries
    for match_result in result.matched_entries:
        if match_result.match_type == "unmatched":
            result.exception_flags.append({
                "type": "unmatched_clock",
                "detail": "Clock entry does not match any scheduled shift",
                "clock_entry_id": str(match_result.clock_entry_id),
            })
    
    # Missed shifts (scheduled but no clock entry matched)
    for sched in schedule_entries:
        if sched.id not in matched_schedule_ids:
            result.exception_flags.append({
                "type": "missed_shift",
                "detail": "No clock-in for scheduled shift",
                "schedule_entry_id": str(sched.id),
            })
    
    # High variance
    if result.rostered_minutes > 0:
        variance = abs(result.actual_minutes - result.rostered_minutes)
        if variance > 60:  # more than 1 hour difference
            result.exception_flags.append({
                "type": "high_variance",
                "detail": f"Actual differs from rostered by {variance} minutes",
            })
    
    return result
