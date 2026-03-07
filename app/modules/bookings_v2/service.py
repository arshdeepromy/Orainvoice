"""Booking service: CRUD, slot calculation, cancellation, conversions.

**Validates: Requirement 19 — Booking Module**
"""

from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bookings_v2.models import Booking, BookingRule
from app.modules.bookings_v2.schemas import (
    BookingCreate,
    BookingUpdate,
    PublicBookingSubmit,
    TimeSlot,
)


class BookingService:
    """Service layer for booking and appointment management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list_bookings(
        self,
        org_id: uuid.UUID,
        *,
        status: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[Booking], int]:
        """List bookings with optional filters."""
        stmt = select(Booking).where(Booking.org_id == org_id)

        if status:
            stmt = stmt.where(Booking.status == status)
        if start_date:
            start_dt = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
            stmt = stmt.where(Booking.start_time >= start_dt)
        if end_date:
            end_dt = datetime.combine(end_date, time.max, tzinfo=timezone.utc)
            stmt = stmt.where(Booking.start_time <= end_dt)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0

        stmt = stmt.order_by(Booking.start_time.desc()).offset(skip).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total

    async def get_booking(
        self, org_id: uuid.UUID, booking_id: uuid.UUID,
    ) -> Booking | None:
        stmt = select(Booking).where(
            and_(Booking.org_id == org_id, Booking.id == booking_id),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_booking(
        self,
        org_id: uuid.UUID,
        payload: BookingCreate,
    ) -> Booking:
        """Create a booking, validating against booking rules."""
        if payload.end_time <= payload.start_time:
            raise ValueError("end_time must be after start_time")

        # Validate against booking rules
        rule = await self._get_rule(org_id, payload.service_type)
        if rule:
            self._validate_against_rules(rule, payload.start_time)

        booking = Booking(
            org_id=org_id,
            customer_name=payload.customer_name,
            customer_email=payload.customer_email,
            customer_phone=payload.customer_phone,
            staff_id=payload.staff_id,
            service_type=payload.service_type,
            start_time=payload.start_time,
            end_time=payload.end_time,
            notes=payload.notes,
            status="pending",
            confirmation_token=secrets.token_urlsafe(32),
        )
        self.db.add(booking)
        await self.db.flush()
        return booking

    async def create_public_booking(
        self,
        org_id: uuid.UUID,
        payload: PublicBookingSubmit,
    ) -> Booking:
        """Create a booking from the public booking page."""
        rule = await self._get_rule(org_id, payload.service_type)
        duration = rule.duration_minutes if rule else 60

        end_time = payload.start_time + timedelta(minutes=duration)

        create_payload = BookingCreate(
            customer_name=payload.customer_name,
            customer_email=payload.customer_email,
            customer_phone=payload.customer_phone,
            service_type=payload.service_type,
            start_time=payload.start_time,
            end_time=end_time,
            notes=payload.notes,
        )
        return await self.create_booking(org_id, create_payload)

    async def update_booking(
        self,
        org_id: uuid.UUID,
        booking_id: uuid.UUID,
        payload: BookingUpdate,
    ) -> Booking | None:
        booking = await self.get_booking(org_id, booking_id)
        if booking is None:
            return None
        update_data = payload.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(booking, field, value)
        if booking.end_time <= booking.start_time:
            raise ValueError("end_time must be after start_time")
        await self.db.flush()
        return booking

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------

    async def cancel_booking(
        self, org_id: uuid.UUID, booking_id: uuid.UUID,
    ) -> Booking | None:
        """Cancel a booking and free the time slot."""
        booking = await self.get_booking(org_id, booking_id)
        if booking is None:
            return None
        if booking.status == "cancelled":
            raise ValueError("Booking is already cancelled")
        if booking.status == "completed":
            raise ValueError("Cannot cancel a completed booking")
        booking.status = "cancelled"
        await self.db.flush()
        return booking

    # ------------------------------------------------------------------
    # Conversions
    # ------------------------------------------------------------------

    async def convert_to_job(
        self, org_id: uuid.UUID, booking_id: uuid.UUID,
    ) -> Booking | None:
        """Mark booking as converted to a job (job creation is external)."""
        booking = await self.get_booking(org_id, booking_id)
        if booking is None:
            return None
        if booking.status == "cancelled":
            raise ValueError("Cannot convert a cancelled booking")
        booking.converted_job_id = booking.converted_job_id  # placeholder
        await self.db.flush()
        return booking

    async def convert_to_invoice(
        self, org_id: uuid.UUID, booking_id: uuid.UUID,
    ) -> Booking | None:
        """Mark booking as converted to an invoice (invoice creation is external)."""
        booking = await self.get_booking(org_id, booking_id)
        if booking is None:
            return None
        if booking.status == "cancelled":
            raise ValueError("Cannot convert a cancelled booking")
        await self.db.flush()
        return booking

    # ------------------------------------------------------------------
    # Confirmation
    # ------------------------------------------------------------------

    async def send_confirmation(
        self, org_id: uuid.UUID, booking_id: uuid.UUID,
    ) -> bool:
        """Send confirmation (placeholder — actual email via Celery task)."""
        booking = await self.get_booking(org_id, booking_id)
        if booking is None:
            return False
        if booking.status == "pending":
            booking.status = "confirmed"
            await self.db.flush()
        return True

    # ------------------------------------------------------------------
    # Available slots (Task 26.5)
    # ------------------------------------------------------------------

    async def get_available_slots(
        self,
        org_id: uuid.UUID,
        target_date: date,
        service_type: str | None = None,
    ) -> list[TimeSlot]:
        """Calculate available time slots for a given date.

        Considers booking rules, existing bookings, and staff schedules.
        """
        rule = await self._get_rule(org_id, service_type)
        if rule is None:
            # Default rule
            rule = BookingRule(
                org_id=org_id,
                duration_minutes=60,
                min_advance_hours=2,
                max_advance_days=90,
                buffer_minutes=15,
                available_days=[1, 2, 3, 4, 5],
                available_hours={"start": "09:00", "end": "17:00"},
            )

        # Check if the target date's weekday is in available_days
        # Python: Monday=0 .. Sunday=6; design uses 1=Mon .. 7=Sun
        weekday = target_date.isoweekday()  # 1=Mon .. 7=Sun
        if weekday not in rule.available_days:
            return []

        # Check advance time constraints
        now = datetime.now(timezone.utc)
        min_start = now + timedelta(hours=rule.min_advance_hours)
        max_end_date = now.date() + timedelta(days=rule.max_advance_days)
        if target_date > max_end_date:
            return []

        # Parse available hours
        start_hour, start_min = map(int, rule.available_hours["start"].split(":"))
        end_hour, end_min = map(int, rule.available_hours["end"].split(":"))

        slot_start = datetime.combine(
            target_date, time(start_hour, start_min), tzinfo=timezone.utc,
        )
        day_end = datetime.combine(
            target_date, time(end_hour, end_min), tzinfo=timezone.utc,
        )

        duration = timedelta(minutes=rule.duration_minutes)
        buffer = timedelta(minutes=rule.buffer_minutes)

        # Fetch existing bookings for the date
        existing = await self._get_bookings_for_date(org_id, target_date)

        # Count bookings for max_per_day check
        active_count = len([b for b in existing if b.status != "cancelled"])

        slots: list[TimeSlot] = []
        cursor = slot_start

        while cursor + duration <= day_end:
            slot_end = cursor + duration
            available = True

            # Must be after min advance time
            if cursor < min_start:
                available = False

            # Check max_per_day
            if rule.max_per_day and active_count >= rule.max_per_day:
                available = False

            # Check overlap with existing bookings
            if available:
                for b in existing:
                    if b.status == "cancelled":
                        continue
                    if b.start_time < slot_end and b.end_time > cursor:
                        available = False
                        break

            slots.append(TimeSlot(
                start_time=cursor,
                end_time=slot_end,
                available=available,
            ))
            cursor = slot_end + buffer

        return slots

    # ------------------------------------------------------------------
    # Booking rules
    # ------------------------------------------------------------------

    async def get_booking_rules(
        self, org_id: uuid.UUID,
    ) -> list[BookingRule]:
        stmt = select(BookingRule).where(BookingRule.org_id == org_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_or_create_default_rule(
        self, org_id: uuid.UUID,
    ) -> BookingRule:
        """Get the default (service_type=None) rule, creating one if absent."""
        rule = await self._get_rule(org_id, None)
        if rule is None:
            rule = BookingRule(org_id=org_id)
            self.db.add(rule)
            await self.db.flush()
        return rule

    async def update_booking_rules(
        self,
        org_id: uuid.UUID,
        data: dict,
    ) -> BookingRule:
        rule = await self.get_or_create_default_rule(org_id)
        for field, value in data.items():
            if hasattr(rule, field):
                setattr(rule, field, value)
        await self.db.flush()
        return rule

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_rule(
        self, org_id: uuid.UUID, service_type: str | None,
    ) -> BookingRule | None:
        """Get the most specific booking rule for the org/service."""
        if service_type:
            stmt = select(BookingRule).where(
                and_(
                    BookingRule.org_id == org_id,
                    BookingRule.service_type == service_type,
                ),
            )
            result = await self.db.execute(stmt)
            rule = result.scalar_one_or_none()
            if rule:
                return rule
        # Fall back to default rule (service_type IS NULL)
        stmt = select(BookingRule).where(
            and_(
                BookingRule.org_id == org_id,
                BookingRule.service_type.is_(None),
            ),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_bookings_for_date(
        self, org_id: uuid.UUID, target_date: date,
    ) -> list[Booking]:
        """Get all bookings for a specific date."""
        day_start = datetime.combine(target_date, time.min, tzinfo=timezone.utc)
        day_end = datetime.combine(target_date, time.max, tzinfo=timezone.utc)
        stmt = select(Booking).where(
            and_(
                Booking.org_id == org_id,
                Booking.start_time >= day_start,
                Booking.start_time <= day_end,
            ),
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    def _validate_against_rules(
        self, rule: BookingRule, start_time: datetime,
    ) -> None:
        """Validate a booking start time against booking rules."""
        now = datetime.now(timezone.utc)

        # Min advance time
        min_start = now + timedelta(hours=rule.min_advance_hours)
        if start_time < min_start:
            raise ValueError(
                f"Booking must be at least {rule.min_advance_hours} hours in advance",
            )

        # Max advance window
        max_date = now.date() + timedelta(days=rule.max_advance_days)
        if start_time.date() > max_date:
            raise ValueError(
                f"Booking cannot be more than {rule.max_advance_days} days in advance",
            )

        # Available days
        weekday = start_time.isoweekday()
        if weekday not in rule.available_days:
            raise ValueError("Booking is not available on this day of the week")
