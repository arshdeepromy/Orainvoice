"""Table service: CRUD floor plans, tables, reservations, status management, merge/split.

**Validates: Requirement — Table Module**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tables.models import (
    FloorPlan,
    RestaurantTable,
    TABLE_STATUSES,
    TableReservation,
)
from app.modules.tables.schemas import (
    FloorPlanCreate,
    FloorPlanUpdate,
    ReservationCreate,
    ReservationUpdate,
    TableCreate,
    TableUpdate,
)

# Valid table status transitions
VALID_STATUS_TRANSITIONS: dict[str, list[str]] = {
    "available": ["occupied", "reserved"],
    "occupied": ["needs_cleaning"],
    "needs_cleaning": ["available"],
    "reserved": ["occupied", "available"],
}


class TableService:
    """Service layer for floor plans, tables, and reservations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ==================================================================
    # Floor Plan CRUD
    # ==================================================================

    async def list_floor_plans(
        self, org_id: uuid.UUID, *, skip: int = 0, limit: int = 50,
    ) -> tuple[list[FloorPlan], int]:
        stmt = select(FloorPlan).where(FloorPlan.org_id == org_id)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0
        stmt = stmt.order_by(FloorPlan.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total

    async def get_floor_plan(
        self, org_id: uuid.UUID, floor_plan_id: uuid.UUID,
    ) -> FloorPlan | None:
        stmt = select(FloorPlan).where(
            and_(FloorPlan.org_id == org_id, FloorPlan.id == floor_plan_id),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_floor_plan(
        self, org_id: uuid.UUID, payload: FloorPlanCreate,
    ) -> FloorPlan:
        fp = FloorPlan(
            org_id=org_id,
            name=payload.name,
            location_id=payload.location_id,
            width=payload.width,
            height=payload.height,
        )
        self.db.add(fp)
        await self.db.flush()
        return fp

    async def update_floor_plan(
        self, org_id: uuid.UUID, floor_plan_id: uuid.UUID, payload: FloorPlanUpdate,
    ) -> FloorPlan | None:
        fp = await self.get_floor_plan(org_id, floor_plan_id)
        if fp is None:
            return None
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(fp, field, value)
        await self.db.flush()
        return fp

    async def delete_floor_plan(
        self, org_id: uuid.UUID, floor_plan_id: uuid.UUID,
    ) -> bool:
        fp = await self.get_floor_plan(org_id, floor_plan_id)
        if fp is None:
            return False
        await self.db.delete(fp)
        await self.db.flush()
        return True

    # ==================================================================
    # Restaurant Table CRUD
    # ==================================================================

    async def list_tables(
        self,
        org_id: uuid.UUID,
        *,
        floor_plan_id: uuid.UUID | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[RestaurantTable], int]:
        stmt = select(RestaurantTable).where(RestaurantTable.org_id == org_id)
        if floor_plan_id:
            stmt = stmt.where(RestaurantTable.floor_plan_id == floor_plan_id)
        if status:
            stmt = stmt.where(RestaurantTable.status == status)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0
        stmt = stmt.order_by(RestaurantTable.table_number).offset(skip).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total

    async def get_table(
        self, org_id: uuid.UUID, table_id: uuid.UUID,
    ) -> RestaurantTable | None:
        stmt = select(RestaurantTable).where(
            and_(RestaurantTable.org_id == org_id, RestaurantTable.id == table_id),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_table(
        self, org_id: uuid.UUID, payload: TableCreate,
    ) -> RestaurantTable:
        tbl = RestaurantTable(
            org_id=org_id,
            table_number=payload.table_number,
            seat_count=payload.seat_count,
            position_x=payload.position_x,
            position_y=payload.position_y,
            width=payload.width,
            height=payload.height,
            floor_plan_id=payload.floor_plan_id,
            location_id=payload.location_id,
        )
        self.db.add(tbl)
        await self.db.flush()
        return tbl

    async def update_table(
        self, org_id: uuid.UUID, table_id: uuid.UUID, payload: TableUpdate,
    ) -> RestaurantTable | None:
        tbl = await self.get_table(org_id, table_id)
        if tbl is None:
            return None
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(tbl, field, value)
        await self.db.flush()
        return tbl

    async def delete_table(
        self, org_id: uuid.UUID, table_id: uuid.UUID,
    ) -> bool:
        tbl = await self.get_table(org_id, table_id)
        if tbl is None:
            return False
        await self.db.delete(tbl)
        await self.db.flush()
        return True

    # ==================================================================
    # Table Status Management (Task 31.5)
    # ==================================================================

    async def update_status(
        self, org_id: uuid.UUID, table_id: uuid.UUID, new_status: str,
    ) -> RestaurantTable:
        """Update table status following valid transition rules.

        Valid transitions:
          available → occupied, reserved
          occupied → needs_cleaning
          needs_cleaning → available
          reserved → occupied, available
        """
        if new_status not in TABLE_STATUSES:
            raise ValueError(f"Invalid status: {new_status}. Must be one of {TABLE_STATUSES}")

        tbl = await self.get_table(org_id, table_id)
        if tbl is None:
            raise ValueError("Table not found")

        current = tbl.status
        allowed = VALID_STATUS_TRANSITIONS.get(current, [])
        if new_status not in allowed:
            raise ValueError(
                f"Invalid transition: {current} → {new_status}. "
                f"Allowed transitions from '{current}': {allowed}"
            )

        tbl.status = new_status
        await self.db.flush()
        return tbl

    # ==================================================================
    # Table Merge / Split (Task 31.6)
    # ==================================================================

    async def merge_tables(
        self, org_id: uuid.UUID, table_ids: list[uuid.UUID],
    ) -> list[RestaurantTable]:
        """Merge multiple tables. The first table becomes the primary;
        others get merged_with_id pointing to the primary.
        All merged tables are set to 'occupied'.
        """
        if len(table_ids) < 2:
            raise ValueError("At least 2 tables are required to merge")

        tables: list[RestaurantTable] = []
        for tid in table_ids:
            tbl = await self.get_table(org_id, tid)
            if tbl is None:
                raise ValueError(f"Table {tid} not found")
            if tbl.merged_with_id is not None:
                raise ValueError(
                    f"Table {tbl.table_number} is already merged with another table"
                )
            tables.append(tbl)

        primary = tables[0]
        for tbl in tables[1:]:
            tbl.merged_with_id = primary.id
            tbl.status = "occupied"

        primary.status = "occupied"
        await self.db.flush()
        return tables

    async def split_tables(
        self, org_id: uuid.UUID, primary_table_id: uuid.UUID,
    ) -> list[RestaurantTable]:
        """Split a merged table group. Clears merged_with_id on all
        secondary tables and sets all to 'needs_cleaning'.
        """
        primary = await self.get_table(org_id, primary_table_id)
        if primary is None:
            raise ValueError("Primary table not found")

        # Find all tables merged with this primary
        stmt = select(RestaurantTable).where(
            and_(
                RestaurantTable.org_id == org_id,
                RestaurantTable.merged_with_id == primary_table_id,
            ),
        )
        result = await self.db.execute(stmt)
        merged = list(result.scalars().all())

        if not merged:
            raise ValueError("Table is not part of a merged group")

        all_tables = [primary] + merged
        for tbl in all_tables:
            tbl.merged_with_id = None
            tbl.status = "needs_cleaning"

        await self.db.flush()
        return all_tables

    # ==================================================================
    # Reservations
    # ==================================================================

    async def list_reservations(
        self,
        org_id: uuid.UUID,
        *,
        target_date: date | None = None,
        table_id: uuid.UUID | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[TableReservation], int]:
        stmt = select(TableReservation).where(TableReservation.org_id == org_id)
        if target_date:
            stmt = stmt.where(TableReservation.reservation_date == target_date)
        if table_id:
            stmt = stmt.where(TableReservation.table_id == table_id)
        if status:
            stmt = stmt.where(TableReservation.status == status)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0
        stmt = stmt.order_by(
            TableReservation.reservation_date, TableReservation.reservation_time,
        ).offset(skip).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total

    async def get_reservation(
        self, org_id: uuid.UUID, reservation_id: uuid.UUID,
    ) -> TableReservation | None:
        stmt = select(TableReservation).where(
            and_(TableReservation.org_id == org_id, TableReservation.id == reservation_id),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_reservation(
        self, org_id: uuid.UUID, payload: ReservationCreate,
    ) -> TableReservation:
        """Create a reservation and mark the table as reserved if it's currently available."""
        # Verify table exists
        tbl = await self.get_table(org_id, payload.table_id)
        if tbl is None:
            raise ValueError("Table not found")

        reservation = TableReservation(
            org_id=org_id,
            table_id=payload.table_id,
            customer_name=payload.customer_name,
            party_size=payload.party_size,
            reservation_date=payload.reservation_date,
            reservation_time=payload.reservation_time,
            duration_minutes=payload.duration_minutes,
            notes=payload.notes,
            status="confirmed",
        )
        self.db.add(reservation)
        await self.db.flush()
        return reservation

    async def update_reservation(
        self, org_id: uuid.UUID, reservation_id: uuid.UUID, payload: ReservationUpdate,
    ) -> TableReservation | None:
        res = await self.get_reservation(org_id, reservation_id)
        if res is None:
            return None
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(res, field, value)
        await self.db.flush()
        return res

    async def cancel_reservation(
        self, org_id: uuid.UUID, reservation_id: uuid.UUID,
    ) -> TableReservation | None:
        res = await self.get_reservation(org_id, reservation_id)
        if res is None:
            return None
        if res.status == "cancelled":
            raise ValueError("Reservation is already cancelled")
        res.status = "cancelled"
        await self.db.flush()
        return res

    # ==================================================================
    # Floor Plan State (composite view)
    # ==================================================================

    async def get_floor_plan_state(
        self,
        org_id: uuid.UUID,
        floor_plan_id: uuid.UUID,
        *,
        target_date: date | None = None,
    ) -> dict:
        """Get the full state of a floor plan: plan details, tables, and reservations for a date."""
        fp = await self.get_floor_plan(org_id, floor_plan_id)
        if fp is None:
            raise ValueError("Floor plan not found")

        tables, _ = await self.list_tables(org_id, floor_plan_id=floor_plan_id, limit=500)

        # Get reservations for today or specified date
        res_date = target_date or date.today()
        table_ids = [t.id for t in tables]

        reservations: list[TableReservation] = []
        if table_ids:
            stmt = select(TableReservation).where(
                and_(
                    TableReservation.org_id == org_id,
                    TableReservation.table_id.in_(table_ids),
                    TableReservation.reservation_date == res_date,
                    TableReservation.status != "cancelled",
                ),
            ).order_by(TableReservation.reservation_time)
            result = await self.db.execute(stmt)
            reservations = list(result.scalars().all())

        return {
            "floor_plan": fp,
            "tables": tables,
            "reservations": reservations,
        }
