"""Recurring invoices service: CRUD, invoice generation, date advancement.

**Validates: Recurring Module**
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.recurring_invoices.models import RecurringSchedule
from app.modules.recurring_invoices.schemas import (
    RecurringScheduleCreate,
    RecurringScheduleUpdate,
)


# Frequency → relativedelta mapping
_FREQUENCY_DELTAS = {
    "weekly": timedelta(days=7),
    "fortnightly": timedelta(days=14),
    "monthly": relativedelta(months=1),
    "quarterly": relativedelta(months=3),
    "annually": relativedelta(years=1),
}


class RecurringService:
    """Service layer for recurring invoice schedule management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_schedule(
        self, org_id: uuid.UUID, payload: RecurringScheduleCreate,
    ) -> RecurringSchedule:
        """Create a new recurring schedule."""
        schedule = RecurringSchedule(
            org_id=org_id,
            customer_id=payload.customer_id,
            line_items=[item.model_dump(mode="json") for item in payload.line_items],
            frequency=payload.frequency,
            start_date=payload.start_date,
            end_date=payload.end_date,
            next_generation_date=payload.next_generation_date or payload.start_date,
            auto_issue=payload.auto_issue,
            auto_email=payload.auto_email,
        )
        self.db.add(schedule)
        await self.db.flush()
        return schedule

    async def get_schedule(
        self, org_id: uuid.UUID, schedule_id: uuid.UUID,
    ) -> RecurringSchedule | None:
        """Get a single recurring schedule by ID."""
        stmt = select(RecurringSchedule).where(
            and_(
                RecurringSchedule.org_id == org_id,
                RecurringSchedule.id == schedule_id,
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_schedules(
        self,
        org_id: uuid.UUID,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[RecurringSchedule], int]:
        """List recurring schedules with optional status filter."""
        filters = [RecurringSchedule.org_id == org_id]
        if status:
            filters.append(RecurringSchedule.status == status)

        count_stmt = select(func.count(RecurringSchedule.id)).where(and_(*filters))
        count_result = await self.db.execute(count_stmt)
        total = count_result.scalar() or 0

        stmt = (
            select(RecurringSchedule)
            .where(and_(*filters))
            .order_by(RecurringSchedule.next_generation_date.asc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total

    async def update_schedule(
        self,
        org_id: uuid.UUID,
        schedule_id: uuid.UUID,
        payload: RecurringScheduleUpdate,
    ) -> RecurringSchedule | None:
        """Update an existing recurring schedule.

        Only updates fields that are explicitly set (not None).
        """
        schedule = await self.get_schedule(org_id, schedule_id)
        if schedule is None:
            return None

        update_data = payload.model_dump(exclude_none=True)
        if "line_items" in update_data and payload.line_items is not None:
            update_data["line_items"] = [
                item.model_dump(mode="json") for item in payload.line_items
            ]

        for field, value in update_data.items():
            setattr(schedule, field, value)

        await self.db.flush()
        return schedule

    async def delete_schedule(
        self, org_id: uuid.UUID, schedule_id: uuid.UUID,
    ) -> bool:
        """Cancel (soft-delete) a recurring schedule."""
        schedule = await self.get_schedule(org_id, schedule_id)
        if schedule is None:
            return False
        schedule.status = "cancelled"
        await self.db.flush()
        return True

    # ------------------------------------------------------------------
    # Invoice generation
    # ------------------------------------------------------------------

    async def generate_invoice(
        self, schedule: RecurringSchedule,
    ) -> dict:
        """Generate an invoice from a recurring schedule.

        Returns a dict representing the generated invoice data.
        In a full implementation this would call the invoice service
        to create a real invoice record.
        """
        invoice_data = {
            "org_id": str(schedule.org_id),
            "customer_id": str(schedule.customer_id),
            "line_items": schedule.line_items,
            "status": "issued" if schedule.auto_issue else "draft",
            "source": "recurring",
            "recurring_schedule_id": str(schedule.id),
        }
        return invoice_data

    # ------------------------------------------------------------------
    # Date advancement
    # ------------------------------------------------------------------

    @staticmethod
    def advance_next_date(schedule: RecurringSchedule) -> None:
        """Advance the next_generation_date based on frequency.

        If the new date exceeds end_date, mark the schedule as completed.
        """
        delta = _FREQUENCY_DELTAS[schedule.frequency]
        new_date = schedule.next_generation_date + delta

        if schedule.end_date and new_date > schedule.end_date:
            schedule.status = "completed"
        schedule.next_generation_date = new_date

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    async def get_dashboard(self, org_id: uuid.UUID) -> dict:
        """Return dashboard summary counts for recurring schedules."""
        today = date.today()
        week_end = today + timedelta(days=7)

        base = [RecurringSchedule.org_id == org_id]

        active_stmt = select(func.count(RecurringSchedule.id)).where(
            and_(*base, RecurringSchedule.status == "active")
        )
        paused_stmt = select(func.count(RecurringSchedule.id)).where(
            and_(*base, RecurringSchedule.status == "paused")
        )
        due_today_stmt = select(func.count(RecurringSchedule.id)).where(
            and_(
                *base,
                RecurringSchedule.status == "active",
                RecurringSchedule.next_generation_date <= today,
            )
        )
        due_week_stmt = select(func.count(RecurringSchedule.id)).where(
            and_(
                *base,
                RecurringSchedule.status == "active",
                RecurringSchedule.next_generation_date <= week_end,
            )
        )

        active = (await self.db.execute(active_stmt)).scalar() or 0
        paused = (await self.db.execute(paused_stmt)).scalar() or 0
        due_today = (await self.db.execute(due_today_stmt)).scalar() or 0
        due_week = (await self.db.execute(due_week_stmt)).scalar() or 0

        return {
            "active_count": active,
            "paused_count": paused,
            "due_today": due_today,
            "due_this_week": due_week,
        }

    # ------------------------------------------------------------------
    # Cron helper: find all due schedules
    # ------------------------------------------------------------------

    async def find_due_schedules(self) -> list[RecurringSchedule]:
        """Find all active schedules where next_generation_date <= today."""
        today = date.today()
        stmt = select(RecurringSchedule).where(
            and_(
                RecurringSchedule.status == "active",
                RecurringSchedule.next_generation_date <= today,
            )
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
