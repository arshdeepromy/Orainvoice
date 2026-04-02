"""Shared branch validation helpers for service-layer use.

Provides ``validate_branch_active`` which checks that a given branch_id
references an active branch.  Used by create functions across all entity
services to reject writes targeting deactivated branches.

**Validates: Requirements 2.2**
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organisations.models import Branch


async def validate_branch_active(
    db: AsyncSession,
    branch_id: uuid.UUID,
) -> None:
    """Raise ``ValueError`` if *branch_id* does not reference an active branch.

    The caller is expected to catch ``ValueError`` and return a 400 response.
    """
    result = await db.execute(
        select(Branch.is_active).where(Branch.id == branch_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise ValueError("Branch not found")
    if not row:
        raise ValueError("Cannot assign to deactivated branch")


async def validate_booking_operating_hours(
    db: AsyncSession,
    branch_id: uuid.UUID,
    scheduled_at,  # datetime
    duration_minutes: int = 60,
) -> None:
    """Raise ``ValueError`` if the booking falls outside branch operating hours.

    Operating hours are stored as a JSONB dict with day-of-week keys
    (e.g. ``{"monday": {"open": "08:00", "close": "17:00"}, ...}``).

    If the branch has no operating_hours configured (empty dict), the
    booking is always allowed.

    **Validates: Requirements 3.4**
    """
    from datetime import timedelta

    result = await db.execute(
        select(Branch.operating_hours).where(Branch.id == branch_id)
    )
    operating_hours = result.scalar_one_or_none()

    if not operating_hours:
        return  # No operating hours configured — allow all bookings

    # Get the day of week name (lowercase)
    day_name = scheduled_at.strftime("%A").lower()
    day_hours = operating_hours.get(day_name)

    if not day_hours:
        raise ValueError(
            f"Booking time is outside branch operating hours (branch is closed on {day_name.capitalize()})"
        )

    open_str = day_hours.get("open", "")
    close_str = day_hours.get("close", "")

    if not open_str or not close_str:
        return  # Incomplete config — allow

    # Parse open/close times
    open_hour, open_min = (int(x) for x in open_str.split(":"))
    close_hour, close_min = (int(x) for x in close_str.split(":"))

    booking_start_minutes = scheduled_at.hour * 60 + scheduled_at.minute
    booking_end_minutes = booking_start_minutes + duration_minutes
    open_minutes = open_hour * 60 + open_min
    close_minutes = close_hour * 60 + close_min

    if booking_start_minutes < open_minutes or booking_end_minutes > close_minutes:
        raise ValueError("Booking time is outside branch operating hours")


async def get_invoice_logo_url(
    db: AsyncSession,
    branch_id: uuid.UUID | None,
    org_logo_url: str | None = None,
) -> str | None:
    """Return the logo URL to use on an invoice.

    If the invoice's branch has a ``logo_url`` configured, use it.
    Otherwise fall back to the organisation's logo.

    **Validates: Requirements 3.2**
    """
    if branch_id is not None:
        result = await db.execute(
            select(Branch.logo_url).where(Branch.id == branch_id)
        )
        branch_logo = result.scalar_one_or_none()
        if branch_logo:
            return branch_logo

    return org_logo_url
