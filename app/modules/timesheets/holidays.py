"""Public holiday detection for timesheet computation.

Integrates with the existing `public_holidays` table to determine
which dates in a pay period are public holidays. Uses branch timezone
for date resolution.

Phase C implementation per design § Phase C Architecture Notes.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import PublicHoliday


async def get_public_holidays_in_range(
    db: AsyncSession,
    *,
    country_code: str = "NZ",
    start_date: date,
    end_date: date,
) -> set[date]:
    """Fetch public holiday dates within a date range.

    Uses the existing `public_holidays` table which is synced from
    external calendar APIs.

    Returns a set of dates that are public holidays within the range.
    """
    result = await db.execute(
        select(PublicHoliday.holiday_date).where(
            PublicHoliday.country_code == country_code,
            PublicHoliday.holiday_date >= start_date,
            PublicHoliday.holiday_date <= end_date,
        )
    )
    return {row[0] for row in result.all()}


def resolve_date_in_timezone(
    dt: datetime,
    timezone_name: str = "Pacific/Auckland",
) -> date:
    """Convert a UTC datetime to a local date in the given timezone.

    Used to determine which calendar day a clock-in falls on for
    public holiday classification.
    """
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = ZoneInfo("Pacific/Auckland")

    if dt.tzinfo is None:
        # Assume UTC if naive
        from datetime import timezone as tz_mod
        dt = dt.replace(tzinfo=tz_mod.utc)

    return dt.astimezone(tz).date()


def is_public_holiday(
    target_date: date,
    holiday_dates: set[date],
) -> bool:
    """Check if a specific date is a public holiday."""
    return target_date in holiday_dates


def classify_clock_entry_date(
    clock_in_at: datetime,
    branch_timezone: str = "Pacific/Auckland",
) -> date:
    """Determine the calendar date for a clock entry using branch timezone.

    This is the date used for:
    - Public holiday classification
    - Daily overtime threshold accumulation
    - Break enforcement per-shift grouping
    """
    return resolve_date_in_timezone(clock_in_at, branch_timezone)
