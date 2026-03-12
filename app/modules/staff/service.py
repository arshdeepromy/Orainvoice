"""Staff service: CRUD, location assignment, utilisation, and labour costs.

**Validates: Requirement — Staff Module**
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.staff.models import StaffLocationAssignment, StaffMember
from app.modules.staff.schemas import StaffMemberCreate, StaffMemberUpdate
from app.modules.time_tracking_v2.models import TimeEntry


class StaffService:
    """Service layer for staff and contractor management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list_staff(
        self,
        org_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 50,
        role_type: str | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[StaffMember], int]:
        """List staff members with pagination and filtering."""
        stmt = select(StaffMember).where(StaffMember.org_id == org_id)

        if role_type is not None:
            stmt = stmt.where(StaffMember.role_type == role_type)
        if is_active is not None:
            stmt = stmt.where(StaffMember.is_active == is_active)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0

        offset = (page - 1) * page_size
        stmt = stmt.order_by(StaffMember.name).offset(offset).limit(page_size)
        result = await self.db.execute(stmt)
        return list(result.scalars().unique().all()), total

    async def create_staff(
        self,
        org_id: uuid.UUID,
        payload: StaffMemberCreate,
    ) -> StaffMember:
        """Create a new staff member."""
        # Check for duplicates within the same org
        await self._check_duplicates(org_id, payload.email, payload.phone, payload.employee_id)

        first = payload.first_name.strip()
        last = (payload.last_name or "").strip()
        full_name = f"{first} {last}".strip()
        staff = StaffMember(
            org_id=org_id,
            user_id=payload.user_id,
            name=full_name,
            first_name=first,
            last_name=last or None,
            email=payload.email,
            phone=payload.phone,
            employee_id=payload.employee_id,
            position=payload.position,
            reporting_to=payload.reporting_to,
            shift_start=payload.shift_start,
            shift_end=payload.shift_end,
            role_type=payload.role_type,
            hourly_rate=payload.hourly_rate,
            overtime_rate=payload.overtime_rate,
            availability_schedule=payload.availability_schedule,
            skills=payload.skills,
        )
        self.db.add(staff)
        await self.db.flush()
        return staff
    async def _check_duplicates(
        self,
        org_id: uuid.UUID,
        email: str | None,
        phone: str | None,
        employee_id: str | None,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        """Raise ValueError if email, phone, or employee_id already exists for another active staff member."""
        conflicts: list[str] = []
        for field_name, value in [("email", email), ("phone", phone), ("employee_id", employee_id)]:
            if not value or not value.strip():
                continue
            col = getattr(StaffMember, field_name)
            stmt = select(StaffMember.id).where(
                StaffMember.org_id == org_id,
                col == value.strip(),
                StaffMember.is_active.is_(True),
            )
            if exclude_id:
                stmt = stmt.where(StaffMember.id != exclude_id)
            result = await self.db.execute(stmt.limit(1))
            if result.scalar_one_or_none() is not None:
                label = field_name.replace("_", " ").title()
                conflicts.append(f"{label} '{value.strip()}' is already in use by another staff member")
        if conflicts:
            raise ValueError("; ".join(conflicts))



    async def get_staff(
        self, org_id: uuid.UUID, staff_id: uuid.UUID,
    ) -> StaffMember | None:
        """Get a single staff member by ID."""
        stmt = select(StaffMember).where(
            and_(StaffMember.org_id == org_id, StaffMember.id == staff_id),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_staff(
        self, org_id: uuid.UUID, staff_id: uuid.UUID, payload: StaffMemberUpdate,
    ) -> StaffMember | None:
        """Update an existing staff member."""
        staff = await self.get_staff(org_id, staff_id)
        if staff is None:
            return None
        update_data = payload.model_dump(exclude_unset=True)
        # Check for duplicates, excluding the current staff member
        await self._check_duplicates(
            org_id,
            update_data.get("email", staff.email),
            update_data.get("phone", staff.phone),
            update_data.get("employee_id", staff.employee_id),
            exclude_id=staff_id,
        )
        for field, value in update_data.items():
            setattr(staff, field, value)
        # Keep legacy 'name' field in sync
        if "first_name" in update_data or "last_name" in update_data:
            first = staff.first_name or ""
            last = staff.last_name or ""
            staff.name = f"{first} {last}".strip()
        await self.db.flush()
        return staff

    # ------------------------------------------------------------------
    # Location assignment
    # ------------------------------------------------------------------

    async def assign_to_location(
        self, org_id: uuid.UUID, staff_id: uuid.UUID, location_id: uuid.UUID,
    ) -> StaffLocationAssignment:
        """Assign a staff member to a location. Inactive staff cannot be assigned."""
        staff = await self.get_staff(org_id, staff_id)
        if staff is None:
            raise ValueError("Staff member not found")
        if not staff.is_active:
            raise ValueError("Cannot assign inactive staff to a location")

        # Check for existing assignment
        stmt = select(StaffLocationAssignment).where(
            and_(
                StaffLocationAssignment.staff_id == staff_id,
                StaffLocationAssignment.location_id == location_id,
            ),
        )
        existing = (await self.db.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            raise ValueError("Staff member is already assigned to this location")

        assignment = StaffLocationAssignment(
            staff_id=staff_id,
            location_id=location_id,
        )
        self.db.add(assignment)
        await self.db.flush()
        return assignment

    async def remove_from_location(
        self, org_id: uuid.UUID, staff_id: uuid.UUID, location_id: uuid.UUID,
    ) -> bool:
        """Remove a staff member from a location."""
        staff = await self.get_staff(org_id, staff_id)
        if staff is None:
            return False
        stmt = select(StaffLocationAssignment).where(
            and_(
                StaffLocationAssignment.staff_id == staff_id,
                StaffLocationAssignment.location_id == location_id,
            ),
        )
        assignment = (await self.db.execute(stmt)).scalar_one_or_none()
        if assignment is None:
            return False
        await self.db.delete(assignment)
        await self.db.flush()
        return True

    # ------------------------------------------------------------------
    # Utilisation calculation
    # ------------------------------------------------------------------

    async def calculate_utilisation(
        self,
        org_id: uuid.UUID,
        date_from: date,
        date_to: date,
        *,
        staff_id: uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Calculate utilisation: billable hours / available hours for date range."""
        staff_stmt = select(StaffMember).where(StaffMember.org_id == org_id)
        if staff_id is not None:
            staff_stmt = staff_stmt.where(StaffMember.id == staff_id)
        staff_result = await self.db.execute(staff_stmt)
        staff_list = list(staff_result.scalars().unique().all())

        results: list[dict[str, Any]] = []
        for member in staff_list:
            # Get time entries for this staff member in the date range
            te_stmt = (
                select(
                    func.coalesce(func.sum(TimeEntry.duration_minutes), 0).label("total_minutes"),
                    func.coalesce(
                        func.sum(
                            func.case(
                                (TimeEntry.is_billable.is_(True), TimeEntry.duration_minutes),
                                else_=0,
                            )
                        ), 0,
                    ).label("billable_minutes"),
                )
                .where(
                    and_(
                        TimeEntry.org_id == org_id,
                        TimeEntry.staff_id == member.id,
                        TimeEntry.start_time >= date_from.isoformat(),
                        TimeEntry.start_time < date_to.isoformat(),
                    ),
                )
            )
            row = (await self.db.execute(te_stmt)).one()
            total_minutes = int(row[0])
            billable_minutes = int(row[1])

            # Calculate available minutes from availability schedule
            available_minutes = self._calculate_available_minutes(
                member.availability_schedule, date_from, date_to,
            )

            utilisation = (
                Decimal(str(billable_minutes)) / Decimal(str(available_minutes)) * 100
                if available_minutes > 0
                else Decimal("0")
            )

            results.append({
                "staff_id": member.id,
                "staff_name": member.name,
                "billable_minutes": billable_minutes,
                "total_minutes": total_minutes,
                "available_minutes": available_minutes,
                "utilisation_percent": round(utilisation, 2),
            })

        return results

    @staticmethod
    def _calculate_available_minutes(
        schedule: dict, date_from: date, date_to: date,
    ) -> int:
        """Calculate total available minutes from a weekly availability schedule.

        Schedule format: {"monday": {"start": "09:00", "end": "17:00"}, ...}
        Falls back to 8 hours/day, 5 days/week if schedule is empty.
        """
        if not schedule:
            # Default: 8 hours/day, Mon-Fri
            num_days = (date_to - date_from).days
            if num_days <= 0:
                return 0
            # Rough estimate: 5/7 of days are working days
            working_days = max(1, int(num_days * 5 / 7))
            return working_days * 8 * 60

        total = 0
        day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        current = date_from
        while current < date_to:
            day_name = day_names[current.weekday()]
            day_schedule = schedule.get(day_name)
            if day_schedule and isinstance(day_schedule, dict):
                start = day_schedule.get("start", "09:00")
                end = day_schedule.get("end", "17:00")
                try:
                    sh, sm = map(int, start.split(":"))
                    eh, em = map(int, end.split(":"))
                    minutes = (eh * 60 + em) - (sh * 60 + sm)
                    if minutes > 0:
                        total += minutes
                except (ValueError, AttributeError):
                    total += 480  # fallback 8 hours
            current = date(current.year, current.month, current.day)
            from datetime import timedelta
            current = current + timedelta(days=1)
        return total

    # ------------------------------------------------------------------
    # Labour costs
    # ------------------------------------------------------------------

    async def get_labour_costs(
        self,
        org_id: uuid.UUID,
        date_from: date,
        date_to: date,
        *,
        staff_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Calculate labour costs from time entries × hourly rate for date range."""
        staff_stmt = select(StaffMember).where(StaffMember.org_id == org_id)
        if staff_id is not None:
            staff_stmt = staff_stmt.where(StaffMember.id == staff_id)
        staff_result = await self.db.execute(staff_stmt)
        staff_list = list(staff_result.scalars().unique().all())

        entries: list[dict[str, Any]] = []
        grand_total = Decimal("0")

        for member in staff_list:
            te_stmt = (
                select(func.coalesce(func.sum(TimeEntry.duration_minutes), 0))
                .where(
                    and_(
                        TimeEntry.org_id == org_id,
                        TimeEntry.staff_id == member.id,
                        TimeEntry.start_time >= date_from.isoformat(),
                        TimeEntry.start_time < date_to.isoformat(),
                    ),
                )
            )
            total_minutes = (await self.db.execute(te_stmt)).scalar() or 0
            total_minutes = int(total_minutes)

            rate = member.hourly_rate or Decimal("0")
            hours = Decimal(str(total_minutes)) / Decimal("60")
            cost = round(hours * rate, 2)

            entries.append({
                "staff_id": member.id,
                "staff_name": member.name,
                "total_minutes": total_minutes,
                "hourly_rate": rate,
                "total_cost": cost,
            })
            grand_total += cost

        return {
            "entries": entries,
            "total_cost": grand_total,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
        }
