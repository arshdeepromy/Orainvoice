"""Business logic for staff scheduling per branch.

Manages schedule entry CRUD with overlap detection and user-branch
assignment validation.

Requirements: 19.1, 19.2, 19.3, 19.4, 19.5
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, time, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.scheduling.models import Schedule

logger = logging.getLogger(__name__)


async def create_schedule_entry(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    branch_id: uuid.UUID,
    user_id: uuid.UUID,
    shift_date: date,
    start_time: time,
    end_time: time,
    notes: str | None = None,
) -> dict:
    """Create a schedule entry with overlap and user-branch validation.

    Raises ValueError if:
    - user is not assigned to the target branch
    - the time range overlaps an existing entry for the same user/date

    Requirements: 19.1, 19.2, 19.5
    """
    if start_time >= end_time:
        raise ValueError("start_time must be before end_time")

    # Validate user is assigned to the target branch
    await _validate_user_branch_assignment(db, user_id=user_id, branch_id=branch_id)

    # Check for overlapping schedules
    await _check_overlap(
        db,
        user_id=user_id,
        shift_date=shift_date,
        start_time=start_time,
        end_time=end_time,
        exclude_entry_id=None,
    )

    entry = Schedule(
        org_id=org_id,
        branch_id=branch_id,
        user_id=user_id,
        shift_date=shift_date,
        start_time=start_time,
        end_time=end_time,
        notes=notes,
    )
    db.add(entry)
    await db.flush()

    return _schedule_to_dict(entry)


async def list_schedule_entries(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    branch_id: uuid.UUID | None = None,
    date_range: tuple[date, date] | None = None,
) -> list[dict]:
    """List schedule entries with optional branch and date range filters.

    Requirements: 19.3, 19.4
    """
    query = (
        select(Schedule)
        .where(Schedule.org_id == org_id)
        .order_by(Schedule.shift_date, Schedule.start_time)
    )

    if branch_id is not None:
        query = query.where(Schedule.branch_id == branch_id)

    if date_range is not None:
        start_date, end_date = date_range
        query = query.where(
            and_(
                Schedule.shift_date >= start_date,
                Schedule.shift_date <= end_date,
            )
        )

    result = await db.execute(query)
    entries = result.scalars().all()

    return [_schedule_to_dict(e) for e in entries]


async def update_schedule_entry(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    entry_id: uuid.UUID,
    **fields,
) -> dict:
    """Update a schedule entry with re-validation of overlap and user-branch.

    Requirements: 19.1, 19.2, 19.5
    """
    entry = await _get_schedule_entry(db, org_id=org_id, entry_id=entry_id)

    # Apply field updates
    new_branch_id = fields.get("branch_id", entry.branch_id)
    new_user_id = fields.get("user_id", entry.user_id)
    new_shift_date = fields.get("shift_date", entry.shift_date)
    new_start_time = fields.get("start_time", entry.start_time)
    new_end_time = fields.get("end_time", entry.end_time)
    new_notes = fields.get("notes", entry.notes)

    if new_start_time >= new_end_time:
        raise ValueError("start_time must be before end_time")

    # Re-validate user-branch assignment if user or branch changed
    if new_user_id != entry.user_id or new_branch_id != entry.branch_id:
        await _validate_user_branch_assignment(db, user_id=new_user_id, branch_id=new_branch_id)

    # Re-check overlap if time/date/user changed
    if (
        new_user_id != entry.user_id
        or new_shift_date != entry.shift_date
        or new_start_time != entry.start_time
        or new_end_time != entry.end_time
    ):
        await _check_overlap(
            db,
            user_id=new_user_id,
            shift_date=new_shift_date,
            start_time=new_start_time,
            end_time=new_end_time,
            exclude_entry_id=entry.id,
        )

    entry.branch_id = new_branch_id
    entry.user_id = new_user_id
    entry.shift_date = new_shift_date
    entry.start_time = new_start_time
    entry.end_time = new_end_time
    entry.notes = new_notes

    await db.flush()
    return _schedule_to_dict(entry)


async def delete_schedule_entry(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    entry_id: uuid.UUID,
) -> dict:
    """Delete a schedule entry.

    Requirements: 19.1
    """
    entry = await _get_schedule_entry(db, org_id=org_id, entry_id=entry_id)
    result = _schedule_to_dict(entry)
    await db.delete(entry)
    await db.flush()
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_schedule_entry(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    entry_id: uuid.UUID,
) -> Schedule:
    """Fetch a schedule entry by ID, scoped to org. Raises ValueError if not found."""
    result = await db.execute(
        select(Schedule).where(
            Schedule.id == entry_id,
            Schedule.org_id == org_id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise ValueError("Schedule entry not found")
    return entry


async def _validate_user_branch_assignment(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    branch_id: uuid.UUID,
) -> None:
    """Validate that the user's branch_ids array includes the target branch.

    Raises ValueError if the user is not assigned to the branch.

    Requirements: 19.2
    """
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError("User not found")

    user_branch_ids = user.branch_ids or []
    # branch_ids is a JSONB array of UUID strings
    if str(branch_id) not in [str(bid) for bid in user_branch_ids]:
        raise ValueError("User is not assigned to this branch")


async def _check_overlap(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    shift_date: date,
    start_time: time,
    end_time: time,
    exclude_entry_id: uuid.UUID | None = None,
) -> None:
    """Check for overlapping schedule entries for the same user on the same date.

    Two time ranges overlap when: start_time < existing.end_time AND end_time > existing.start_time

    Raises OverlapError (ValueError subclass) with 409-appropriate message.

    Requirements: 19.5
    """
    query = select(Schedule).where(
        Schedule.user_id == user_id,
        Schedule.shift_date == shift_date,
        Schedule.start_time < end_time,
        Schedule.end_time > start_time,
    )

    if exclude_entry_id is not None:
        query = query.where(Schedule.id != exclude_entry_id)

    result = await db.execute(query)
    existing = result.scalar_one_or_none()

    if existing is not None:
        raise OverlapError("Schedule overlaps with existing entry for this user")


class OverlapError(ValueError):
    """Raised when a schedule entry overlaps with an existing one.

    Service layer raises this; the router maps it to HTTP 409.
    """
    pass


def _schedule_to_dict(entry: Schedule) -> dict:
    """Convert a Schedule ORM instance to a response dict."""
    return {
        "id": str(entry.id),
        "org_id": str(entry.org_id),
        "branch_id": str(entry.branch_id),
        "user_id": str(entry.user_id),
        "shift_date": entry.shift_date.isoformat(),
        "start_time": entry.start_time.isoformat(),
        "end_time": entry.end_time.isoformat(),
        "notes": entry.notes,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
        "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
    }
