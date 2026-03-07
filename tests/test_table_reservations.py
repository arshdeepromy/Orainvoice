"""Test: reservation appears on floor plan at reserved time.

**Validates: Requirement — Table Module — Task 31.8**

Verifies that TableService.get_floor_plan_state() includes reservations
for the queried date, and that create_reservation() works correctly.
"""

from __future__ import annotations

import uuid
from datetime import date, time, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.tables.models import FloorPlan, RestaurantTable, TableReservation
from app.modules.tables.schemas import ReservationCreate
from app.modules.tables.service import TableService

ORG_ID = uuid.uuid4()
FLOOR_PLAN_ID = uuid.uuid4()
TABLE_ID = uuid.uuid4()


def _make_floor_plan() -> FloorPlan:
    return FloorPlan(
        id=FLOOR_PLAN_ID,
        org_id=ORG_ID,
        name="Main Floor",
        width=Decimal("800"),
        height=Decimal("600"),
        is_active=True,
    )


def _make_table() -> RestaurantTable:
    return RestaurantTable(
        id=TABLE_ID,
        org_id=ORG_ID,
        table_number="T1",
        seat_count=4,
        status="available",
        floor_plan_id=FLOOR_PLAN_ID,
    )


def _make_reservation(
    *,
    res_date: date | None = None,
    res_time: time | None = None,
    status: str = "confirmed",
) -> TableReservation:
    return TableReservation(
        id=uuid.uuid4(),
        org_id=ORG_ID,
        table_id=TABLE_ID,
        customer_name="Jane Doe",
        party_size=4,
        reservation_date=res_date or date.today(),
        reservation_time=res_time or time(19, 0),
        duration_minutes=90,
        status=status,
    )


class TestCreateReservation:
    """Test reservation creation."""

    @pytest.mark.asyncio
    async def test_create_reservation_success(self):
        table = _make_table()
        mock_db = AsyncMock()

        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = table
            return mock_result

        mock_db.execute = fake_execute
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        svc = TableService(mock_db)
        payload = ReservationCreate(
            table_id=TABLE_ID,
            customer_name="Jane Doe",
            party_size=4,
            reservation_date=date.today(),
            reservation_time=time(19, 0),
            duration_minutes=90,
        )
        res = await svc.create_reservation(ORG_ID, payload)
        assert res.customer_name == "Jane Doe"
        assert res.party_size == 4
        assert res.status == "confirmed"
        assert res.table_id == TABLE_ID

    @pytest.mark.asyncio
    async def test_create_reservation_table_not_found(self):
        mock_db = AsyncMock()

        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            return mock_result

        mock_db.execute = fake_execute
        mock_db.flush = AsyncMock()

        svc = TableService(mock_db)
        payload = ReservationCreate(
            table_id=uuid.uuid4(),
            customer_name="Jane Doe",
            party_size=4,
            reservation_date=date.today(),
            reservation_time=time(19, 0),
        )
        with pytest.raises(ValueError, match="Table not found"):
            await svc.create_reservation(ORG_ID, payload)


class TestReservationOnFloorPlan:
    """Test that reservations appear on floor plan state for the correct date."""

    @pytest.mark.asyncio
    async def test_reservation_appears_on_floor_plan_for_today(self):
        """Reservation for today shows up in get_floor_plan_state()."""
        floor_plan = _make_floor_plan()
        table = _make_table()
        today_reservation = _make_reservation(res_date=date.today())

        call_count = 0

        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()

            if call_count == 1:
                # get_floor_plan
                mock_result.scalar_one_or_none.return_value = floor_plan
            elif call_count == 2:
                # list_tables count
                mock_result.scalar.return_value = 1
            elif call_count == 3:
                # list_tables results
                mock_result.scalars.return_value.all.return_value = [table]
            elif call_count == 4:
                # reservations query
                mock_result.scalars.return_value.all.return_value = [today_reservation]
            return mock_result

        mock_db = AsyncMock()
        mock_db.execute = fake_execute
        mock_db.flush = AsyncMock()

        svc = TableService(mock_db)
        state = await svc.get_floor_plan_state(ORG_ID, FLOOR_PLAN_ID)

        assert state["floor_plan"].id == FLOOR_PLAN_ID
        assert len(state["tables"]) == 1
        assert state["tables"][0].table_number == "T1"
        assert len(state["reservations"]) == 1
        assert state["reservations"][0].customer_name == "Jane Doe"

    @pytest.mark.asyncio
    async def test_cancelled_reservations_excluded(self):
        """Cancelled reservations should not appear in floor plan state."""
        floor_plan = _make_floor_plan()
        table = _make_table()

        call_count = 0

        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()

            if call_count == 1:
                mock_result.scalar_one_or_none.return_value = floor_plan
            elif call_count == 2:
                mock_result.scalar.return_value = 1
            elif call_count == 3:
                mock_result.scalars.return_value.all.return_value = [table]
            elif call_count == 4:
                # No reservations (cancelled ones filtered by query)
                mock_result.scalars.return_value.all.return_value = []
            return mock_result

        mock_db = AsyncMock()
        mock_db.execute = fake_execute
        mock_db.flush = AsyncMock()

        svc = TableService(mock_db)
        state = await svc.get_floor_plan_state(ORG_ID, FLOOR_PLAN_ID)

        assert len(state["reservations"]) == 0

    @pytest.mark.asyncio
    async def test_floor_plan_not_found(self):
        """get_floor_plan_state raises ValueError for missing floor plan."""
        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            return mock_result

        mock_db = AsyncMock()
        mock_db.execute = fake_execute

        svc = TableService(mock_db)
        with pytest.raises(ValueError, match="Floor plan not found"):
            await svc.get_floor_plan_state(ORG_ID, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_reservation_for_specific_date(self):
        """Querying a specific date returns reservations for that date."""
        floor_plan = _make_floor_plan()
        table = _make_table()
        tomorrow = date.today() + timedelta(days=1)
        tomorrow_reservation = _make_reservation(res_date=tomorrow)

        call_count = 0

        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()

            if call_count == 1:
                mock_result.scalar_one_or_none.return_value = floor_plan
            elif call_count == 2:
                mock_result.scalar.return_value = 1
            elif call_count == 3:
                mock_result.scalars.return_value.all.return_value = [table]
            elif call_count == 4:
                mock_result.scalars.return_value.all.return_value = [tomorrow_reservation]
            return mock_result

        mock_db = AsyncMock()
        mock_db.execute = fake_execute
        mock_db.flush = AsyncMock()

        svc = TableService(mock_db)
        state = await svc.get_floor_plan_state(ORG_ID, FLOOR_PLAN_ID, target_date=tomorrow)

        assert len(state["reservations"]) == 1
        assert state["reservations"][0].reservation_date == tomorrow
