"""Scheduling service: CRUD, conflict detection, reschedule, reminders.

**Validates: Requirement 18 — Scheduling Module**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.scheduling_v2.models import ScheduleEntry, ShiftTemplate
from app.modules.scheduling_v2.schemas import (
    ScheduleEntryCreate,
    ScheduleEntryUpdate,
    ShiftTemplateCreate,
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

    async def create_recurring_entry(
        self,
        org_id: uuid.UUID,
        payload: ScheduleEntryCreate,
    ) -> list[ScheduleEntry]:
        """Create recurring schedule entries for the recurrence period (up to 4 weeks).

        Generates individual entries linked by a shared recurrence_group_id.
        Supports daily, weekly, and fortnightly frequencies.

        Requirements: 56.1, 56.2
        """
        if payload.end_time <= payload.start_time:
            raise ValueError("end_time must be after start_time")

        recurrence = getattr(payload, "recurrence", "none")
        if recurrence == "none":
            # Fall back to single entry creation
            entry = await self.create_entry(org_id, payload)
            return [entry]

        # Determine interval between occurrences
        interval_map = {
            "daily": timedelta(days=1),
            "weekly": timedelta(weeks=1),
            "fortnightly": timedelta(weeks=2),
        }
        interval = interval_map.get(recurrence)
        if interval is None:
            raise ValueError(f"Invalid recurrence: {recurrence}")

        # Generate entries up to 4 weeks from the first entry's start
        max_horizon = payload.start_time + timedelta(weeks=4)
        group_id = uuid.uuid4()
        duration = payload.end_time - payload.start_time

        entries: list[ScheduleEntry] = []
        current_start = payload.start_time

        while current_start < max_horizon:
            current_end = current_start + duration
            entry = ScheduleEntry(
                org_id=org_id,
                staff_id=payload.staff_id,
                job_id=payload.job_id,
                booking_id=payload.booking_id,
                location_id=payload.location_id,
                title=payload.title,
                description=payload.description,
                start_time=current_start,
                end_time=current_end,
                entry_type=payload.entry_type,
                notes=payload.notes,
                recurrence_group_id=group_id,
            )
            self.db.add(entry)
            entries.append(entry)
            current_start += interval

        await self.db.flush()
        return entries

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
        """Update an existing schedule entry.

        Fires the roster-change SMS hook (G2 / R14a / task B7a) after
        the row is mutated when one of ``start_time``, ``end_time``,
        or ``staff_id`` changed and the shift falls within the next
        48 hours. The hook is fire-and-forget — failures inside it
        are logged but do not fail the update.
        """
        entry = await self.get_entry(org_id, entry_id)
        if entry is None:
            return None

        # Snapshot pre-mutation state so the hook can emit the
        # correct "was X, now Y" template (design §4.6).
        from app.modules.time_clock.roster_change_sms import (
            _emit_roster_change_sms,
            snapshot_schedule_entry,
        )
        before_snapshot = snapshot_schedule_entry(entry)

        update_data = payload.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(entry, field, value)
        # Validate times after update
        if entry.end_time <= entry.start_time:
            raise ValueError("end_time must be after start_time")
        await self.db.flush()

        # Detect what changed — fire the hook only when one of the
        # in-window fields moved.
        change_type: str | None = None
        if before_snapshot.staff_id != entry.staff_id:
            change_type = "staff_reassigned"
        elif (
            before_snapshot.start_time != entry.start_time
            or before_snapshot.end_time != entry.end_time
        ):
            change_type = "time_changed"
        if change_type is not None:
            await _emit_roster_change_sms(
                self.db,
                entry_before=before_snapshot,
                entry_after=entry,
                change_type=change_type,
            )

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
        """Move a schedule entry to new start/end times.

        Fires the roster-change SMS hook (G2 / R14a / task B7a) when
        the new ``start_time`` falls within the next 48 hours and the
        times actually moved. The hook is fire-and-forget.
        """
        entry = await self.get_entry(org_id, entry_id)
        if entry is None:
            return None
        if new_end <= new_start:
            raise ValueError("end_time must be after start_time")

        from app.modules.time_clock.roster_change_sms import (
            _emit_roster_change_sms,
            snapshot_schedule_entry,
        )
        before_snapshot = snapshot_schedule_entry(entry)

        entry.start_time = new_start
        entry.end_time = new_end
        await self.db.flush()

        if (
            before_snapshot.start_time != entry.start_time
            or before_snapshot.end_time != entry.end_time
        ):
            await _emit_roster_change_sms(
                self.db,
                entry_before=before_snapshot,
                entry_after=entry,
                change_type="time_changed",
            )

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

    # ------------------------------------------------------------------
    # Shift Templates (Req 57)
    # ------------------------------------------------------------------

    async def list_templates(
        self,
        org_id: uuid.UUID,
    ) -> tuple[list[ShiftTemplate], int]:
        """List all shift templates for an organisation."""
        stmt = select(ShiftTemplate).where(ShiftTemplate.org_id == org_id)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0

        stmt = stmt.order_by(ShiftTemplate.name)
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total

    async def create_template(
        self,
        org_id: uuid.UUID,
        payload: ShiftTemplateCreate,
    ) -> ShiftTemplate:
        """Create a new shift template."""
        from datetime import time as dt_time

        parts_start = payload.start_time.split(":")
        parts_end = payload.end_time.split(":")
        start_t = dt_time(int(parts_start[0]), int(parts_start[1]))
        end_t = dt_time(int(parts_end[0]), int(parts_end[1]))

        template = ShiftTemplate(
            org_id=org_id,
            name=payload.name,
            start_time=start_t,
            end_time=end_t,
            entry_type=payload.entry_type,
        )
        self.db.add(template)
        await self.db.flush()
        return template

    async def delete_template(
        self,
        org_id: uuid.UUID,
        template_id: uuid.UUID,
    ) -> bool:
        """Delete a shift template. Returns True if deleted."""
        stmt = select(ShiftTemplate).where(
            and_(ShiftTemplate.org_id == org_id, ShiftTemplate.id == template_id),
        )
        result = await self.db.execute(stmt)
        template = result.scalar_one_or_none()
        if template is None:
            return False
        await self.db.delete(template)
        await self.db.flush()
        return True
