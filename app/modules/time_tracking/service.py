"""Business logic for Employee Time Tracking.

Requirements: 65.1, 65.2, 65.3
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.job_cards.models import JobCard, JobCardItem, TimeEntry
from app.modules.catalogue.models import LabourRate


async def start_timer(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    job_card_id: uuid.UUID,
    notes: str | None = None,
    ip_address: str | None = None,
) -> dict:
    """Start a timer for a user on a job card.

    Only one active timer per user per job card is allowed.
    Requirements: 65.1
    """
    # Verify job card exists and belongs to org
    result = await db.execute(
        select(JobCard).where(
            and_(JobCard.id == job_card_id, JobCard.org_id == org_id)
        )
    )
    job_card = result.scalars().first()
    if not job_card:
        raise ValueError("Job card not found")

    if job_card.status == "invoiced":
        raise ValueError("Cannot start timer on an invoiced job card")

    # Check for existing active timer for this user on this job card
    result = await db.execute(
        select(TimeEntry).where(
            and_(
                TimeEntry.org_id == org_id,
                TimeEntry.user_id == user_id,
                TimeEntry.job_card_id == job_card_id,
                TimeEntry.stopped_at.is_(None),
            )
        )
    )
    existing = result.scalars().first()
    if existing:
        raise ValueError(
            "Active timer already exists for this user on this job card"
        )

    now = datetime.now(timezone.utc)
    entry = TimeEntry(
        org_id=org_id,
        user_id=user_id,
        job_card_id=job_card_id,
        started_at=now,
        notes=notes,
    )
    db.add(entry)
    await db.flush()

    await write_audit_log(
        db,
        org_id=org_id,
        user_id=user_id,
        action="time_entry.started",
        entity_type="time_entry",
        entity_id=entry.id,
        after_value={
            "job_card_id": str(job_card_id),
            "started_at": now.isoformat(),
        },
        ip_address=ip_address,
    )

    return _time_entry_to_dict(entry)


async def stop_timer(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    job_card_id: uuid.UUID,
    notes: str | None = None,
    ip_address: str | None = None,
) -> dict:
    """Stop the active timer for a user on a job card.

    Calculates duration_minutes from started_at to now.
    Requirements: 65.1
    """
    result = await db.execute(
        select(TimeEntry).where(
            and_(
                TimeEntry.org_id == org_id,
                TimeEntry.user_id == user_id,
                TimeEntry.job_card_id == job_card_id,
                TimeEntry.stopped_at.is_(None),
            )
        )
    )
    entry = result.scalars().first()
    if not entry:
        raise ValueError("No active timer found for this user on this job card")

    now = datetime.now(timezone.utc)
    duration_seconds = int((now - entry.started_at).total_seconds())
    duration_minutes = max(1, round(duration_seconds / 60))

    entry.stopped_at = now
    entry.duration_minutes = duration_minutes
    if notes is not None:
        entry.notes = notes

    await db.flush()

    await write_audit_log(
        db,
        org_id=org_id,
        user_id=user_id,
        action="time_entry.stopped",
        entity_type="time_entry",
        entity_id=entry.id,
        after_value={
            "job_card_id": str(job_card_id),
            "stopped_at": now.isoformat(),
            "duration_minutes": duration_minutes,
        },
        ip_address=ip_address,
    )

    return _time_entry_to_dict(entry)


async def get_time_entries(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    job_card_id: uuid.UUID,
) -> list[dict]:
    """Get all time entries for a job card.

    Requirements: 65.1
    """
    result = await db.execute(
        select(TimeEntry)
        .where(
            and_(
                TimeEntry.org_id == org_id,
                TimeEntry.job_card_id == job_card_id,
            )
        )
        .order_by(TimeEntry.started_at.desc())
    )
    entries = result.scalars().all()
    return [_time_entry_to_dict(e) for e in entries]


async def add_time_as_labour_line_item(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    job_card_id: uuid.UUID,
    time_entry_id: uuid.UUID,
    labour_rate_id: uuid.UUID | None = None,
    hourly_rate_override: Decimal | None = None,
    description: str | None = None,
    ip_address: str | None = None,
) -> dict:
    """Add a completed time entry as a Labour line item on the job card.

    Requirements: 65.2
    """
    # Fetch the time entry
    result = await db.execute(
        select(TimeEntry).where(
            and_(
                TimeEntry.id == time_entry_id,
                TimeEntry.org_id == org_id,
                TimeEntry.job_card_id == job_card_id,
            )
        )
    )
    entry = result.scalars().first()
    if not entry:
        raise ValueError("Time entry not found")

    if entry.stopped_at is None:
        raise ValueError("Cannot add an active timer as a line item — stop it first")

    if entry.duration_minutes is None or entry.duration_minutes <= 0:
        raise ValueError("Time entry has no recorded duration")

    # Determine hourly rate
    hourly_rate: Decimal | None = hourly_rate_override
    if hourly_rate is None and labour_rate_id is not None:
        result = await db.execute(
            select(LabourRate).where(
                and_(
                    LabourRate.id == labour_rate_id,
                    LabourRate.org_id == org_id,
                    LabourRate.is_active.is_(True),
                )
            )
        )
        rate = result.scalars().first()
        if not rate:
            raise ValueError("Labour rate not found or inactive")
        hourly_rate = rate.hourly_rate

    if hourly_rate is None:
        raise ValueError(
            "Hourly rate required — provide labour_rate_id or hourly_rate_override"
        )

    # Calculate hours and total
    hours = Decimal(str(entry.duration_minutes)) / Decimal("60")
    hours = hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    line_total = (hours * hourly_rate).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    # Store the hourly rate on the time entry
    entry.hourly_rate = hourly_rate
    await db.flush()

    # Get next sort order
    result = await db.execute(
        select(func.coalesce(func.max(JobCardItem.sort_order), 0)).where(
            JobCardItem.job_card_id == job_card_id
        )
    )
    next_sort = result.scalar() + 1

    desc = description or f"Labour — {entry.duration_minutes} min"
    item = JobCardItem(
        job_card_id=job_card_id,
        org_id=org_id,
        item_type="labour",
        description=desc,
        quantity=hours,
        unit_price=hourly_rate,
        sort_order=next_sort,
    )
    db.add(item)
    await db.flush()

    await write_audit_log(
        db,
        org_id=org_id,
        user_id=user_id,
        action="time_entry.added_as_labour",
        entity_type="time_entry",
        entity_id=entry.id,
        after_value={
            "job_card_item_id": str(item.id),
            "hours": str(hours),
            "hourly_rate": str(hourly_rate),
            "line_total": str(line_total),
        },
        ip_address=ip_address,
    )

    return {
        "job_card_item_id": item.id,
        "hours": hours,
        "hourly_rate": hourly_rate,
        "line_total": line_total,
    }


async def get_employee_hours_report(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    start_date: datetime,
    end_date: datetime,
) -> dict:
    """Get total hours per employee in a date range.

    Org_Admin only report.
    Requirements: 65.3
    """
    result = await db.execute(
        select(
            TimeEntry.user_id,
            func.sum(TimeEntry.duration_minutes).label("total_minutes"),
            func.count(TimeEntry.id).label("entry_count"),
        )
        .where(
            and_(
                TimeEntry.org_id == org_id,
                TimeEntry.stopped_at.isnot(None),
                TimeEntry.started_at >= start_date,
                TimeEntry.started_at <= end_date,
            )
        )
        .group_by(TimeEntry.user_id)
    )
    rows = result.all()

    entries = []
    grand_total_minutes = 0
    for row in rows:
        total_min = row.total_minutes or 0
        grand_total_minutes += total_min
        hours = Decimal(str(total_min)) / Decimal("60")
        hours = hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        entries.append({
            "user_id": row.user_id,
            "email": None,  # Populated by router if needed
            "total_minutes": total_min,
            "total_hours": hours,
            "entry_count": row.entry_count,
        })

    grand_total_hours = Decimal(str(grand_total_minutes)) / Decimal("60")
    grand_total_hours = grand_total_hours.quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    return {
        "entries": entries,
        "start_date": start_date,
        "end_date": end_date,
        "total_hours": grand_total_hours,
    }


def _time_entry_to_dict(entry: TimeEntry) -> dict:
    """Convert a TimeEntry ORM instance to a plain dict."""
    return {
        "id": entry.id,
        "job_card_id": entry.job_card_id,
        "user_id": entry.user_id,
        "started_at": entry.started_at,
        "stopped_at": entry.stopped_at,
        "duration_minutes": entry.duration_minutes,
        "hourly_rate": entry.hourly_rate,
        "notes": entry.notes,
        "created_at": entry.created_at,
    }
