"""Timezone conversion utilities for org-local date/time display."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


def to_org_timezone(dt: datetime | None, tz_name: str) -> datetime | None:
    """Convert a UTC-aware datetime to the organisation's local timezone."""
    if dt is None:
        return None
    try:
        tz = ZoneInfo(tz_name)
    except (KeyError, ValueError):
        tz = ZoneInfo("UTC")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(tz)


def format_datetime_local(
    dt: datetime | None,
    tz_name: str,
    fmt: str = "%d %b %Y %I:%M %p",
) -> str:
    """Convert UTC datetime to org timezone and format as string."""
    if dt is None:
        return ""
    local_dt = to_org_timezone(dt, tz_name)
    if local_dt is None:
        return ""
    return local_dt.strftime(fmt)


def format_date_local(d: date | None, fmt: str = "%d %b %Y") -> str:
    """Format a date object as string (no timezone conversion needed)."""
    if d is None:
        return ""
    return d.strftime(fmt)
