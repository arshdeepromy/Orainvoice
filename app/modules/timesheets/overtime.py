"""Overtime auto-detection for timesheet aggregation.

Classifies minutes exceeding daily/weekly thresholds into overtime_minutes.
Integrates with the aggregation pipeline to split ordinary vs overtime hours.

Phase C implementation per design § Phase C Architecture Notes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID


@dataclass
class DailyBreakdown:
    """Per-day breakdown of worked hours for overtime classification."""
    date: date
    ordinary_minutes: int = 0
    overtime_minutes: int = 0
    public_holiday_minutes: int = 0
    total_minutes: int = 0
    is_public_holiday: bool = False


@dataclass
class OvertimeSettings:
    """Settings controlling overtime auto-detection."""
    daily_overtime_threshold_minutes: int = 480  # 8 hours
    weekly_overtime_threshold_minutes: int = 2400  # 40 hours
    overtime_rate_multiplier: float = 1.5
    public_holiday_rate_multiplier: float = 1.5


@dataclass
class OvertimeResult:
    """Result of overtime classification for a period."""
    ordinary_minutes: int = 0
    overtime_minutes: int = 0
    public_holiday_minutes: int = 0
    daily_breakdown: list[DailyBreakdown] = field(default_factory=list)
    exception_flags: list[dict] = field(default_factory=list)


def classify_overtime(
    *,
    clock_entries: list[dict],
    public_holiday_dates: set[date],
    settings: OvertimeSettings,
    period_start: date,
    period_end: date,
) -> OvertimeResult:
    """Classify worked minutes into ordinary, overtime, and public holiday bands.

    Algorithm:
    1. Group clock entries by day (using clock_in date in local timezone).
    2. For each day:
       - If it's a public holiday → all minutes are public_holiday_minutes.
       - Else: minutes up to daily_threshold → ordinary; excess → overtime.
    3. After all days are classified, check weekly total:
       - If cumulative ordinary exceeds weekly_threshold, reclassify the excess
         as overtime (works across day boundaries).

    Parameters:
        clock_entries: list of dicts with 'clock_in_date' (date) and 'worked_minutes' (int).
        public_holiday_dates: set of dates that are public holidays.
        settings: OvertimeSettings controlling thresholds.
        period_start: start of the pay period.
        period_end: end of the pay period.
    """
    result = OvertimeResult()

    # Group by day
    daily_minutes: dict[date, int] = {}
    current = period_start
    while current <= period_end:
        daily_minutes[current] = 0
        current += timedelta(days=1)

    for entry in clock_entries:
        entry_date = entry.get("clock_in_date")
        minutes = entry.get("worked_minutes", 0)
        if entry_date and minutes > 0:
            daily_minutes[entry_date] = daily_minutes.get(entry_date, 0) + minutes

    # Classify each day
    weekly_ordinary_accumulator = 0

    for day in sorted(daily_minutes.keys()):
        total = daily_minutes[day]
        breakdown = DailyBreakdown(date=day, total_minutes=total)

        if day in public_holiday_dates:
            # All minutes on a public holiday are PH minutes
            breakdown.is_public_holiday = True
            breakdown.public_holiday_minutes = total
            result.public_holiday_minutes += total
        else:
            # Daily threshold check
            if total <= settings.daily_overtime_threshold_minutes:
                breakdown.ordinary_minutes = total
                weekly_ordinary_accumulator += total
            else:
                ordinary = settings.daily_overtime_threshold_minutes
                overtime = total - ordinary
                breakdown.ordinary_minutes = ordinary
                breakdown.overtime_minutes = overtime
                weekly_ordinary_accumulator += ordinary
                result.overtime_minutes += overtime

        result.daily_breakdown.append(breakdown)

    # Weekly threshold check — reclassify excess ordinary as overtime
    if weekly_ordinary_accumulator > settings.weekly_overtime_threshold_minutes:
        excess = weekly_ordinary_accumulator - settings.weekly_overtime_threshold_minutes
        result.overtime_minutes += excess

        # Walk backwards through days to reclassify ordinary → overtime
        remaining_to_reclassify = excess
        for breakdown in reversed(result.daily_breakdown):
            if remaining_to_reclassify <= 0:
                break
            if breakdown.is_public_holiday:
                continue
            reclassifiable = min(breakdown.ordinary_minutes, remaining_to_reclassify)
            breakdown.ordinary_minutes -= reclassifiable
            breakdown.overtime_minutes += reclassifiable
            remaining_to_reclassify -= reclassifiable

    # Sum up ordinary minutes
    result.ordinary_minutes = sum(
        b.ordinary_minutes for b in result.daily_breakdown
    )

    # Add exception flag if any overtime detected
    if result.overtime_minutes > 0:
        result.exception_flags.append({
            "type": "overtime_detected",
            "detail": (
                f"Overtime detected: {result.overtime_minutes} minutes "
                f"(daily threshold: {settings.daily_overtime_threshold_minutes}, "
                f"weekly threshold: {settings.weekly_overtime_threshold_minutes})"
            ),
        })

    return result
