"""Time tracking service: CRUD, timer, timesheet, overlap detection, invoicing.

**Validates: Requirement 13.1, 13.2, 13.3, 13.4, 13.5, 13.6**
"""

from __future__ import annotations

import uuid
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.time_tracking_v2.models import TimeEntry


class OverlapError(ValueError):
    """Raised when a time entry overlaps an existing entry for the same user."""

    def __init__(self, existing_id: uuid.UUID) -> None:
        self.existing_id = existing_id
        super().__init__(
            f"Time entry overlaps with existing entry {existing_id}"
        )


class AlreadyInvoicedError(ValueError):
    """Raised when trying to invoice an already-invoiced time entry."""

    def __init__(self, entry_ids: list[uuid.UUID]) -> None:
        self.entry_ids = entry_ids
        super().__init__(
            f"Time entries already invoiced: {entry_ids}"
        )


class TimeTrackingService:
    """Service layer for time entry operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Overlap detection
    # ------------------------------------------------------------------

    async def _check_overlap(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        start_time: datetime,
        end_time: datetime | None,
        exclude_id: uuid.UUID | None = None,
    ) -> TimeEntry | None:
        """Check if a time entry overlaps any existing entry for the same user.

        Two entries overlap when their time ranges intersect:
        existing.start_time < new.end_time AND existing.end_time > new.start_time

        For entries with no end_time (active timers), we treat them as
        extending to infinity.
        """
        if end_time is None:
            # Active timer — overlaps anything that starts before now or has no end
            end_time = datetime.now(timezone.utc) + timedelta(days=365 * 10)

        conditions = [
            TimeEntry.org_id == org_id,
            TimeEntry.user_id == user_id,
            TimeEntry.start_time < end_time,
            or_(
                TimeEntry.end_time.is_(None),
                TimeEntry.end_time > start_time,
            ),
        ]
        if exclude_id is not None:
            conditions.append(TimeEntry.id != exclude_id)

        stmt = select(TimeEntry).where(and_(*conditions)).limit(1)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list_entries(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
        job_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[TimeEntry], int]:
        """List time entries with optional filters."""
        conditions = [TimeEntry.org_id == org_id]
        if user_id is not None:
            conditions.append(TimeEntry.user_id == user_id)
        if job_id is not None:
            conditions.append(TimeEntry.job_id == job_id)
        if project_id is not None:
            conditions.append(TimeEntry.project_id == project_id)

        count_stmt = select(func.count()).select_from(TimeEntry).where(and_(*conditions))
        total = (await self.db.execute(count_stmt)).scalar() or 0

        stmt = (
            select(TimeEntry)
            .where(and_(*conditions))
            .order_by(TimeEntry.start_time.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return list(rows), total

    async def create_entry(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        start_time: datetime,
        end_time: datetime | None = None,
        duration_minutes: int | None = None,
        job_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        staff_id: uuid.UUID | None = None,
        description: str | None = None,
        is_billable: bool = True,
        hourly_rate: Decimal | None = None,
    ) -> TimeEntry:
        """Create a manual time entry with overlap detection."""
        # Calculate duration if end_time provided but duration not
        if end_time is not None and duration_minutes is None:
            delta = end_time - start_time
            duration_minutes = int(delta.total_seconds() / 60)

        # Check for overlaps
        overlap = await self._check_overlap(org_id, user_id, start_time, end_time)
        if overlap is not None:
            raise OverlapError(overlap.id)

        entry = TimeEntry(
            org_id=org_id,
            user_id=user_id,
            staff_id=staff_id,
            job_id=job_id,
            project_id=project_id,
            description=description,
            start_time=start_time,
            end_time=end_time,
            duration_minutes=duration_minutes,
            is_billable=is_billable,
            hourly_rate=hourly_rate,
            is_timer_active=False,
        )
        self.db.add(entry)
        await self.db.flush()
        return entry

    async def get_entry(
        self, org_id: uuid.UUID, entry_id: uuid.UUID,
    ) -> TimeEntry | None:
        stmt = select(TimeEntry).where(
            TimeEntry.org_id == org_id, TimeEntry.id == entry_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_entry(
        self,
        org_id: uuid.UUID,
        entry_id: uuid.UUID,
        **kwargs,
    ) -> TimeEntry | None:
        entry = await self.get_entry(org_id, entry_id)
        if entry is None:
            return None
        if entry.is_invoiced:
            raise ValueError("Cannot update an invoiced time entry")

        start_time = kwargs.get("start_time", entry.start_time)
        end_time = kwargs.get("end_time", entry.end_time)

        # Re-check overlap if times changed
        if start_time != entry.start_time or end_time != entry.end_time:
            overlap = await self._check_overlap(
                org_id, entry.user_id, start_time, end_time, exclude_id=entry_id,
            )
            if overlap is not None:
                raise OverlapError(overlap.id)

        for key, value in kwargs.items():
            if value is not None and hasattr(entry, key):
                setattr(entry, key, value)

        # Recalculate duration if times changed
        if entry.end_time is not None:
            delta = entry.end_time - entry.start_time
            entry.duration_minutes = int(delta.total_seconds() / 60)

        await self.db.flush()
        return entry

    # ------------------------------------------------------------------
    # Timer operations
    # ------------------------------------------------------------------

    async def start_timer(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        job_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        staff_id: uuid.UUID | None = None,
        description: str | None = None,
        is_billable: bool = True,
        hourly_rate: Decimal | None = None,
    ) -> TimeEntry:
        """Start a running timer. Only one active timer per user allowed."""
        # Check for existing active timer
        active = await self.get_active_timer(org_id, user_id)
        if active is not None:
            raise ValueError("A timer is already running. Stop it first.")

        now = datetime.now(timezone.utc)

        # Check for overlaps with the new timer
        overlap = await self._check_overlap(org_id, user_id, now, None)
        if overlap is not None:
            raise OverlapError(overlap.id)

        entry = TimeEntry(
            org_id=org_id,
            user_id=user_id,
            staff_id=staff_id,
            job_id=job_id,
            project_id=project_id,
            description=description,
            start_time=now,
            end_time=None,
            duration_minutes=None,
            is_billable=is_billable,
            hourly_rate=hourly_rate,
            is_timer_active=True,
        )
        self.db.add(entry)
        await self.db.flush()
        return entry

    async def stop_timer(
        self, org_id: uuid.UUID, user_id: uuid.UUID,
    ) -> TimeEntry:
        """Stop the active timer, calculate duration."""
        active = await self.get_active_timer(org_id, user_id)
        if active is None:
            raise ValueError("No active timer to stop")

        now = datetime.now(timezone.utc)
        active.end_time = now
        active.duration_minutes = int(
            (now - active.start_time).total_seconds() / 60
        )
        active.is_timer_active = False
        await self.db.flush()
        return active

    async def get_active_timer(
        self, org_id: uuid.UUID, user_id: uuid.UUID,
    ) -> TimeEntry | None:
        """Get the currently active timer for a user."""
        stmt = select(TimeEntry).where(
            TimeEntry.org_id == org_id,
            TimeEntry.user_id == user_id,
            TimeEntry.is_timer_active.is_(True),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Timesheet
    # ------------------------------------------------------------------

    async def get_timesheet(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        week_start: date,
    ) -> dict:
        """Get weekly timesheet: entries grouped by day with totals."""
        week_end = week_start + timedelta(days=6)
        start_dt = datetime(
            week_start.year, week_start.month, week_start.day,
            tzinfo=timezone.utc,
        )
        end_dt = datetime(
            week_end.year, week_end.month, week_end.day,
            23, 59, 59, tzinfo=timezone.utc,
        )

        stmt = (
            select(TimeEntry)
            .where(
                TimeEntry.org_id == org_id,
                TimeEntry.user_id == user_id,
                TimeEntry.start_time >= start_dt,
                TimeEntry.start_time <= end_dt,
            )
            .order_by(TimeEntry.start_time)
        )
        rows = (await self.db.execute(stmt)).scalars().all()

        # Group by day
        days: dict[date, list[TimeEntry]] = {}
        for d in range(7):
            day = week_start + timedelta(days=d)
            days[day] = []

        for entry in rows:
            day = entry.start_time.date()
            if day in days:
                days[day].append(entry)

        weekly_total = 0
        weekly_billable = 0
        day_list = []
        for day_date in sorted(days.keys()):
            entries = days[day_date]
            total_min = sum(e.duration_minutes or 0 for e in entries)
            billable_min = sum(
                e.duration_minutes or 0 for e in entries if e.is_billable
            )
            weekly_total += total_min
            weekly_billable += billable_min
            day_list.append({
                "date": day_date,
                "entries": entries,
                "total_minutes": total_min,
                "billable_minutes": billable_min,
            })

        return {
            "week_start": week_start,
            "week_end": week_end,
            "days": day_list,
            "weekly_total_minutes": weekly_total,
            "weekly_billable_minutes": weekly_billable,
        }

    # ------------------------------------------------------------------
    # Add to invoice
    # ------------------------------------------------------------------

    async def add_to_invoice(
        self,
        org_id: uuid.UUID,
        time_entry_ids: list[uuid.UUID],
        invoice_id: uuid.UUID,
    ) -> dict:
        """Mark time entries as invoiced and return Labour line item data.

        Creates line items: hours × rate for each entry.
        Raises AlreadyInvoicedError if any entry is already invoiced.
        """
        stmt = select(TimeEntry).where(
            TimeEntry.org_id == org_id,
            TimeEntry.id.in_(time_entry_ids),
        )
        rows = (await self.db.execute(stmt)).scalars().all()

        if len(rows) != len(time_entry_ids):
            raise ValueError("Some time entries not found")

        # Check for already-invoiced entries
        already_invoiced = [e.id for e in rows if e.is_invoiced]
        if already_invoiced:
            raise AlreadyInvoicedError(already_invoiced)

        total_hours = Decimal("0")
        total_amount = Decimal("0")
        line_items = []

        for entry in rows:
            minutes = entry.duration_minutes or 0
            hours = Decimal(str(minutes)) / Decimal("60")
            rate = entry.hourly_rate or Decimal("0")
            amount = hours * rate

            total_hours += hours
            total_amount += amount

            line_items.append({
                "description": entry.description or "Labour",
                "quantity": str(hours.quantize(Decimal("0.01"))),
                "unit_price": str(rate),
                "amount": str(amount.quantize(Decimal("0.01"))),
                "time_entry_id": str(entry.id),
            })

            entry.is_invoiced = True
            entry.invoice_id = invoice_id

        await self.db.flush()

        return {
            "invoice_id": invoice_id,
            "line_items_created": len(line_items),
            "line_items": line_items,
            "total_hours": total_hours.quantize(Decimal("0.01")),
            "total_amount": total_amount.quantize(Decimal("0.01")),
            "entries_marked": len(rows),
        }
