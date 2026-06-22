"""Scheduling service: CRUD, conflict detection, reschedule, reminders.

**Validates: Requirement 18 — Scheduling Module**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.scheduling_v2.models import ScheduleEntry, ShiftTemplate
from app.modules.scheduling_v2.schemas import (
    BulkConflictItem,
    BulkScheduleEntryCreateRequest,
    CopyWeekRequest,
    ScheduleEntryCreate,
    ScheduleEntryResponse,
    ScheduleEntryUpdate,
    ShiftTemplateCreate,
)


def _starts_in_past(start_time: datetime) -> bool:
    """True when ``start_time`` is before 'now' (UTC).

    Schedule entries are created with UTC-aware ``start_time`` values (the
    frontend sends ISO ``...Z`` strings via ``Date.toISOString()``), so this is
    a timezone-independent absolute-instant comparison. A naive datetime is
    treated as UTC defensively.
    """
    st = start_time if start_time.tzinfo is not None else start_time.replace(tzinfo=timezone.utc)
    return st < datetime.now(timezone.utc)


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
        if _starts_in_past(payload.start_time):
            raise ValueError("Cannot add a shift that starts in the past.")

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

    # ------------------------------------------------------------------
    # Bulk + Copy-Week (Roster Grid Editor — Workstream A)
    # ------------------------------------------------------------------

    async def bulk_create(
        self,
        org_id: uuid.UUID,
        payload: BulkScheduleEntryCreateRequest,
        *,
        user_id: uuid.UUID | None = None,
    ) -> tuple[list[ScheduleEntry], list[BulkConflictItem]]:
        """Bulk-create up to 200 schedule entries with per-entry SAVEPOINT
        rollback.

        Each entry is wrapped in ``db.begin_nested()`` so that a single
        validation failure or conflict-detected entry does NOT abort the
        whole batch — it only rolls back that one entry's INSERT. The
        outer transaction is committed by the ``get_db_session``
        ``session.begin()`` context manager owned by the request, so
        per-`.kiro/steering/performance-and-resilience.md` rule 1 we
        never call ``db.commit()`` / ``db.rollback()`` here.

        Writes a single audit_log row per call (R17.3) summarising the
        counts only — never per-entry payloads.

        **Validates: R11.3, R11.4, R11.5, R11.9**
        """
        from app.core.audit import write_audit_log

        created: list[ScheduleEntry] = []
        conflicts: list[BulkConflictItem] = []

        class _InvalidEntry(Exception):
            pass

        class _ConflictsDetected(Exception):
            def __init__(self, overlapping: list[ScheduleEntry]) -> None:
                self.overlapping = overlapping

        for index, entry_payload in enumerate(payload.entries):
            try:
                async with self.db.begin_nested():
                    if entry_payload.end_time <= entry_payload.start_time:
                        raise _InvalidEntry()
                    if _starts_in_past(entry_payload.start_time):
                        # A shift starting in the past is reported as a
                        # non-created entry (R: no past shifts) — the batch's
                        # future entries still persist.
                        raise _InvalidEntry()

                    if entry_payload.staff_id is not None:
                        overlapping = await self.detect_conflicts(
                            org_id,
                            entry_payload.staff_id,
                            entry_payload.start_time,
                            entry_payload.end_time,
                        )
                        if overlapping:
                            raise _ConflictsDetected(overlapping)

                    entry = ScheduleEntry(
                        org_id=org_id,  # ALWAYS resolved org — never trust payload
                        staff_id=entry_payload.staff_id,
                        job_id=entry_payload.job_id,
                        booking_id=entry_payload.booking_id,
                        location_id=entry_payload.location_id,
                        title=entry_payload.title,
                        description=entry_payload.description,
                        start_time=entry_payload.start_time,
                        end_time=entry_payload.end_time,
                        entry_type=entry_payload.entry_type,
                        notes=entry_payload.notes,
                    )
                    self.db.add(entry)
                    await self.db.flush()
                    await self.db.refresh(entry)
                    created.append(entry)
            except _InvalidEntry:
                conflicts.append(
                    BulkConflictItem(
                        index=index,
                        attempted=entry_payload,
                        conflicts_with=[],
                    ),
                )
            except _ConflictsDetected as exc:
                conflicts.append(
                    BulkConflictItem(
                        index=index,
                        attempted=entry_payload,
                        conflicts_with=[
                            ScheduleEntryResponse.model_validate(o)
                            for o in exc.overlapping
                        ],
                    ),
                )

        # Audit summary (R17.3 — counts only, no per-entry payload)
        await write_audit_log(
            session=self.db,
            action="schedule.bulk_created",
            entity_type="schedule_entry",
            entity_id=None,
            org_id=org_id,
            user_id=user_id,
            before_value=None,
            after_value={
                "created_count": len(created),
                "conflicts_count": len(conflicts),
            },
        )

        return created, conflicts

    async def copy_week(
        self,
        org_id: uuid.UUID,
        payload: CopyWeekRequest,
        *,
        user_id: uuid.UUID | None = None,
    ) -> tuple[list[ScheduleEntry], list[BulkConflictItem]]:
        """Copy every Schedule_Entry in the source 7-day window to the
        target 7-day window with the times shifted by ``delta``.

        ``delta`` must be a non-zero multiple of 7 days; otherwise the
        method raises ``ValueError`` (the router maps to HTTP 422).
        ``recurrence_group_id`` is forced to NULL on every copy
        (R8.5); ``status`` is the default ``'scheduled'`` (R8.6).

        When ``overwrite_existing`` is true, every overlapping target
        entry is deleted before the new copy is inserted (R8.9).

        Audit row written once at the end of the call summarising the
        counts plus the source / target weeks and the overwrite flag.

        **Validates: R8.3, R8.4, R8.5, R8.6, R8.7, R8.9, R11.7, R11.8**
        """
        from app.core.audit import write_audit_log

        delta = payload.target_week_start - payload.source_week_start
        if delta.days == 0 or delta.days % 7 != 0:
            raise ValueError(
                "target_week_start must be a non-zero multiple of 7 days "
                "from source_week_start",
            )

        source_window_start = datetime.combine(
            payload.source_week_start, time.min, tzinfo=timezone.utc,
        )
        source_window_end = datetime.combine(
            payload.source_week_start + timedelta(days=7),
            time.min,
            tzinfo=timezone.utc,
        )

        stmt = select(ScheduleEntry).where(
            ScheduleEntry.org_id == org_id,
            ScheduleEntry.start_time >= source_window_start,
            ScheduleEntry.start_time < source_window_end,
        )
        sources = list((await self.db.execute(stmt)).scalars().all())

        # Build the bulk_create payload from the source rows.
        entries: list[ScheduleEntryCreate] = []
        for src in sources:
            entries.append(
                ScheduleEntryCreate(
                    staff_id=src.staff_id,
                    job_id=src.job_id,
                    booking_id=src.booking_id,
                    location_id=src.location_id,
                    title=src.title,
                    description=src.description,
                    start_time=src.start_time + delta,
                    end_time=src.end_time + delta,
                    entry_type=src.entry_type,
                    notes=src.notes,
                    recurrence="none",  # explicitly NOT recurring (R8.5)
                ),
            )

        # Overwrite: delete every overlapping target entry before insert.
        if payload.overwrite_existing:
            for entry in entries:
                if entry.staff_id is None:
                    continue
                existing = await self.detect_conflicts(
                    org_id,
                    entry.staff_id,
                    entry.start_time,
                    entry.end_time,
                )
                for e in existing:
                    await self.db.delete(e)
            await self.db.flush()

        # Short-circuit: nothing to copy → write audit + return empty.
        if not entries:
            await write_audit_log(
                session=self.db,
                action="schedule.copied_week",
                entity_type="schedule_entry",
                entity_id=None,
                org_id=org_id,
                user_id=user_id,
                before_value=None,
                after_value={
                    "created_count": 0,
                    "conflicts_count": 0,
                    "source_week_start": payload.source_week_start.isoformat(),
                    "target_week_start": payload.target_week_start.isoformat(),
                    "overwrite_existing": payload.overwrite_existing,
                },
            )
            return [], []

        bulk_payload = BulkScheduleEntryCreateRequest(entries=entries)
        # bulk_create writes its own ``schedule.bulk_created`` audit row;
        # we ALSO write a ``schedule.copied_week`` audit row so the two
        # operations are individually traceable. Both rows carry only
        # summary counts (R17.3).
        created, conflicts = await self.bulk_create(
            org_id, bulk_payload, user_id=user_id,
        )

        await write_audit_log(
            session=self.db,
            action="schedule.copied_week",
            entity_type="schedule_entry",
            entity_id=None,
            org_id=org_id,
            user_id=user_id,
            before_value=None,
            after_value={
                "created_count": len(created),
                "conflicts_count": len(conflicts),
                "source_week_start": payload.source_week_start.isoformat(),
                "target_week_start": payload.target_week_start.isoformat(),
                "overwrite_existing": payload.overwrite_existing,
            },
        )

        return created, conflicts

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
        if _starts_in_past(payload.start_time):
            raise ValueError("Cannot add a shift that starts in the past.")

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

    async def delete_entry(
        self, org_id: uuid.UUID, entry_id: uuid.UUID,
    ) -> bool:
        """Delete a single org-scoped schedule entry.

        Returns ``True`` when a row was deleted, ``False`` when no entry with
        that id exists for the org (so the router can return 404). Uses
        ``flush()`` only — the request's ``session.begin()`` owns the commit.
        """
        entry = await self.get_entry(org_id, entry_id)
        if entry is None:
            return False
        await self.db.delete(entry)
        await self.db.flush()
        return True

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
