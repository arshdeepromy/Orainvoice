"""Match-to-roster policy engine for timesheet computation.

Matches individual TimeClockEntry records against ScheduleEntry records
using configurable policies (pay_actual, round_to_roster, actual_rounded)
with grace window support for early/late clock-in detection.

Code-truth note: TimeClockEntry.source column is named `source` (not 
`clock_in_source`). Values: kiosk, self_service_mobile, self_service_web, 
admin_manual.

Code-truth note: ScheduleEntry uses `location_id` (not `branch_id`).
Rostered minutes are per-person per-period regardless of location.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID


@dataclass
class MatchResult:
    clock_entry_id: UUID
    schedule_entry_id: UUID | None  # None if unmatched
    raw_minutes: int  # from time_clock_entry.worked_minutes
    matched_minutes: int  # after policy application
    match_type: Literal["exact", "grace", "rounded", "unmatched"]


def round_time(
    t: datetime,
    interval_minutes: int,
    direction: Literal["nearest", "up", "down"],
) -> datetime:
    """Round a timestamp to the nearest interval boundary.
    
    - 'nearest': standard rounding (>= half rounds up)
    - 'up': always round to the next boundary (for clock-in: rounds forward)
    - 'down': always round to the previous boundary (for clock-out: rounds backward)
    
    interval_minutes=1 means no rounding (returns t unchanged).
    """
    if interval_minutes <= 1:
        return t
    
    # Get minutes past the hour
    total_minutes = t.hour * 60 + t.minute
    remainder = total_minutes % interval_minutes
    
    if remainder == 0:
        # Already on a boundary
        rounded = t.replace(second=0, microsecond=0)
    elif direction == "down":
        # Round down to previous boundary
        rounded_minutes = total_minutes - remainder
        rounded = t.replace(
            hour=rounded_minutes // 60,
            minute=rounded_minutes % 60,
            second=0, microsecond=0,
        )
    elif direction == "up":
        # Round up to next boundary
        rounded_minutes = total_minutes + (interval_minutes - remainder)
        if rounded_minutes >= 1440:  # past midnight
            rounded_minutes = 1440 - interval_minutes  # clamp to last boundary of day
        rounded = t.replace(
            hour=rounded_minutes // 60,
            minute=rounded_minutes % 60,
            second=0, microsecond=0,
        )
    else:  # nearest
        if remainder >= interval_minutes / 2:
            # Round up
            rounded_minutes = total_minutes + (interval_minutes - remainder)
            if rounded_minutes >= 1440:
                rounded_minutes = 1440 - interval_minutes
            rounded = t.replace(
                hour=rounded_minutes // 60,
                minute=rounded_minutes % 60,
                second=0, microsecond=0,
            )
        else:
            # Round down
            rounded_minutes = total_minutes - remainder
            rounded = t.replace(
                hour=rounded_minutes // 60,
                minute=rounded_minutes % 60,
                second=0, microsecond=0,
            )
    
    return rounded


@dataclass
class ScheduleEntryData:
    """Minimal schedule entry data needed for matching."""
    id: UUID
    start_time: datetime
    end_time: datetime
    duration_minutes: int  # (end_time - start_time) in minutes


@dataclass
class ClockEntryData:
    """Minimal clock entry data needed for matching."""
    id: UUID
    clock_in_at: datetime
    clock_out_at: datetime | None
    worked_minutes: int


@dataclass
class MatchSettings:
    """Settings that control the match engine."""
    match_policy: Literal["pay_actual", "round_to_roster", "actual_rounded"]
    clock_rounding_minutes: int  # 1, 5, 10, 15, or 30
    clock_rounding_direction: Literal["nearest", "up", "down"]
    early_grace_minutes: int
    late_grace_minutes: int


def match_clock_to_roster(
    clock_entry: ClockEntryData,
    schedule_entries: list[ScheduleEntryData],
    settings: MatchSettings,
) -> MatchResult:
    """Match a single clock entry against available schedule entries.
    
    Algorithm:
    1. Find the best-matching schedule entry (clock_in within grace window of schedule start).
    2. Apply match_policy to determine matched_minutes.
    3. Return MatchResult with the determination.
    """
    best_match: ScheduleEntryData | None = None
    best_match_type: Literal["exact", "grace"] = "exact"
    
    for sched in schedule_entries:
        # Check if clock_in is within the grace window of this schedule entry
        earliest_acceptable = sched.start_time - timedelta(minutes=settings.early_grace_minutes)
        latest_acceptable = sched.start_time + timedelta(minutes=settings.late_grace_minutes)
        
        if earliest_acceptable <= clock_entry.clock_in_at <= latest_acceptable:
            # Within grace window — check if it's exact or grace match
            if clock_entry.clock_in_at == sched.start_time:
                match_type: Literal["exact", "grace"] = "exact"
            else:
                match_type = "grace"
            
            # Pick this if no match yet, or if it's a better (closer) match
            if best_match is None:
                best_match = sched
                best_match_type = match_type
            else:
                # Prefer the schedule entry whose start_time is closest to clock_in
                current_diff = abs((clock_entry.clock_in_at - best_match.start_time).total_seconds())
                new_diff = abs((clock_entry.clock_in_at - sched.start_time).total_seconds())
                if new_diff < current_diff:
                    best_match = sched
                    best_match_type = match_type
    
    # No match found
    if best_match is None:
        # Apply policy for unmatched entries
        if settings.match_policy == "actual_rounded" and clock_entry.clock_out_at:
            rounded_in = round_time(clock_entry.clock_in_at, settings.clock_rounding_minutes, settings.clock_rounding_direction)
            rounded_out = round_time(clock_entry.clock_out_at, settings.clock_rounding_minutes, settings.clock_rounding_direction)
            matched_mins = max(0, int((rounded_out - rounded_in).total_seconds() // 60))
            return MatchResult(
                clock_entry_id=clock_entry.id,
                schedule_entry_id=None,
                raw_minutes=clock_entry.worked_minutes,
                matched_minutes=matched_mins,
                match_type="rounded",
            )
        return MatchResult(
            clock_entry_id=clock_entry.id,
            schedule_entry_id=None,
            raw_minutes=clock_entry.worked_minutes,
            matched_minutes=clock_entry.worked_minutes,
            match_type="unmatched",
        )
    
    # Match found — apply policy
    if settings.match_policy == "pay_actual":
        matched_minutes = clock_entry.worked_minutes
    elif settings.match_policy == "round_to_roster":
        matched_minutes = best_match.duration_minutes
    elif settings.match_policy == "actual_rounded":
        if clock_entry.clock_out_at:
            rounded_in = round_time(clock_entry.clock_in_at, settings.clock_rounding_minutes, settings.clock_rounding_direction)
            rounded_out = round_time(clock_entry.clock_out_at, settings.clock_rounding_minutes, settings.clock_rounding_direction)
            matched_minutes = max(0, int((rounded_out - rounded_in).total_seconds() // 60))
        else:
            matched_minutes = clock_entry.worked_minutes
    else:
        matched_minutes = clock_entry.worked_minutes
    
    return MatchResult(
        clock_entry_id=clock_entry.id,
        schedule_entry_id=best_match.id,
        raw_minutes=clock_entry.worked_minutes,
        matched_minutes=matched_minutes,
        match_type=best_match_type,
    )
