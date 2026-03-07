"""Scheduling service: CRUD, conflict detection, reschedule, reminders.

**Validates: Requirement 18 — Scheduling Module**
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.scheduling_v2.models import ScheduleEntry
from app.modules.scheduling_v2.schemas import (
    ScheduleEntryCreate,
    ScheduleEntryUpdate,
)


class SchedulingService:
    """Service layer for schedule entry management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list_entries(
        self,
        org_id: uuid.UUID,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        staff_id: uuid.UUID | None = None,
        location_id: uuid.UUID | None = None,
    ) -> tuple[list[ScheduleEntry], int]:
        """List schedule entries with optional date range and filters."""
        stmt = select(ScheduleEntry).where(ScheduleEntry.org_id == org_id)

        if start is not None:
            stmt = stmt.where(ScheduleEntry.end_time >= start)
        if end is not None:
            stmt = stmt.where(ScheduleEntry.start_time <= end)
        if staff_id is not None:
            stmt = stmt.where(ScheduleEntry.staff_id == staff_id)
        if location_id is not None:
            stmt = stmt.where(ScheduleEntry.location_id == location_id)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0

        stmt = stmt.order_by(ScheduleEntry.start_time)
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total

    async def create_entry(
        self,
        org_id: uuid.UUID,
        payload: ScheduleEntryCreate,
    ) -> ScheduleEntry:
        """Create a new schedule entry."""
        if payload.end_time <= payload.start_time:
            raise ValueError("end_time must be after start_time")

        entry = ScheduleEntry(
            org_id=org_id,
            staff_id=payload.staff_id,
            job_id=payload.job_id,
            booking_id=payload.booking_id,
            location_id=payload.location_id,
            title=payload.title,
            description=payload.description,
            start_time=payload.start_time,
            end_time=payload.end_time,
            entry_type=payload.entry_type,
            notes=payload.notes,
        )
        self.db.add(entry)
        await self.db.flush()
        return entry

    async def get_entry(
        self, org_id: uuid.UUID, entry_id: uuid.UUID,
    ) -> ScheduleEntry | None:
        """Get a single schedule entry by ID."""
        stmt = select(ScheduleEntry).where(
            and_(ScheduleEntry.org_id == org_id, ScheduleEntry.id == entry_id),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_entry(
        self,
        org_id: uuid.UUID,
        entry_id: uuid.UUID,
        payload: ScheduleEntryUpdate,
    ) -> ScheduleEntry | None:
        """Update an existing schedule entry."""
        entry = await self.get_entry(org_id, entry_id)
        if entry is None:
            return None
        update_data = payload.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(entry, field, value)
        # Validate times after update
        if entry.end_time <= entry.start_time:
            raise ValueError("end_time must be after start_time")
        await self.db.flush()
        return entry

    # ------------------------------------------------------------------
    # Conflict detection
    # ------------------------------------------------------------------

    async def detect_conflicts(
        self,
        org_id: uuid.UUID,
        staff_id: uuid.UUID,
        start_time: datetime,
        end_time: datetime,
        *,
        exclude_entry_id: uuid.UUID | None = None,
    ) -> list[ScheduleEntry]:
        """Find overlapping schedule entries for the same staff member.

        Two entries overlap when:
          existing.start_time < new.end_time AND existing.end_time > new.start_time
        """
        stmt = select(ScheduleEntry).where(
            and_(
                ScheduleEntry.org_id == org_id,
                ScheduleEntry.staff_id == staff_id,
                ScheduleEntry.status != "cancelled",
                ScheduleEntry.start_time < end_time,
                ScheduleEntry.end_time > start_time,
            ),
        )
        if exclude_entry_id is not None:
            stmt = stmt.where(ScheduleEntry.id != exclude_entry_id)

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Reschedule
    # ------------------------------------------------------------------

    async def reschedule(
        self,
        org_id: uuid.UUID,
        entry_id: uuid.UUID,
        new_start: datetime,
        new_end: datetime,
    ) -> ScheduleEntry | None:
        """Move a schedule entry to new start/end times."""
        entry = await self.get_entry(org_id, entry_id)
        if entry is None:
            return None
        if new_end <= new_start:
            raise ValueError("end_time must be after start_time")
        entry.start_time = new_start
        entry.end_time = new_end
        await self.db.flush()
        return entry

    # ------------------------------------------------------------------
    # Reminders (used by Celery task)
    # ------------------------------------------------------------------

    async def get_entries_needing_reminders(
        self,
        reminder_window_start: datetime,
        reminder_window_end: datetime,
    ) -> list[ScheduleEntry]:
        """Get scheduled entries starting within the given time window.

        Used by the Celery reminder task to find entries that need
        staff notifications.
        """
        stmt = select(ScheduleEntry).where(
            and_(
                ScheduleEntry.status == "scheduled",
                ScheduleEntry.staff_id.isnot(None),
                ScheduleEntry.start_time >= reminder_window_start,
                ScheduleEntry.start_time < reminder_window_end,
            ),
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
