"""Test: labour costs correctly calculated from time entries × hourly rate.

**Validates: Requirement — Staff Module — Task 24.6**

Verifies that StaffService.get_labour_costs() correctly computes
total_cost = sum(duration_minutes / 60 × hourly_rate) for each staff member
within a given date range.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.staff.models import StaffMember
from app.modules.staff.service import StaffService


def _make_mock_db():
    """Create a mock async DB session."""
    mock_db = AsyncMock()

    async def fake_flush():
        pass

    def fake_add(obj):
        pass

    mock_db.flush = fake_flush
    mock_db.add = fake_add
    return mock_db


def _make_staff(
    org_id: uuid.UUID,
    *,
    name: str = "Test Staff",
    hourly_rate: Decimal = Decimal("50.00"),
    staff_id: uuid.UUID | None = None,
) -> StaffMember:
    """Create a StaffMember instance for testing."""
    return StaffMember(
        id=staff_id or uuid.uuid4(),
        org_id=org_id,
        name=name,
        email="test@example.com",
        role_type="employee",
        hourly_rate=hourly_rate,
        is_active=True,
        availability_schedule={},
        skills=[],
    )


class TestLabourCostCalculation:
    """Validates: labour costs = time entries × hourly rate."""

    @pytest.mark.asyncio
    async def test_single_staff_labour_cost(self):
        """Labour cost for one staff member: 120 min at $50/hr = $100."""
        org_id = uuid.uuid4()
        staff = _make_staff(org_id, name="Alice", hourly_rate=Decimal("50.00"))

        mock_db = _make_mock_db()
        call_count = 0

        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                # Staff list query
                mock_scalars = MagicMock()
                mock_unique = MagicMock()
                mock_unique.all.return_value = [staff]
                mock_scalars.unique.return_value = mock_unique
                mock_result.scalars.return_value = mock_scalars
            else:
                # Time entry sum query: 120 minutes
                mock_result.scalar.return_value = 120
            return mock_result

        mock_db.execute = fake_execute

        svc = StaffService(mock_db)
        result = await svc.get_labour_costs(
            org_id, date(2024, 6, 1), date(2024, 6, 30),
        )

        assert len(result["entries"]) == 1
        entry = result["entries"][0]
        assert entry["staff_name"] == "Alice"
        assert entry["total_minutes"] == 120
        assert entry["hourly_rate"] == Decimal("50.00")
        # 120 min / 60 = 2 hours × $50 = $100
        assert entry["total_cost"] == Decimal("100.00")
        assert result["total_cost"] == Decimal("100.00")

    @pytest.mark.asyncio
    async def test_multiple_staff_labour_costs(self):
        """Labour costs for multiple staff members are summed correctly."""
        org_id = uuid.uuid4()
        alice = _make_staff(org_id, name="Alice", hourly_rate=Decimal("50.00"))
        bob = _make_staff(org_id, name="Bob", hourly_rate=Decimal("75.00"))

        mock_db = _make_mock_db()
        call_count = 0

        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                # Staff list query
                mock_scalars = MagicMock()
                mock_unique = MagicMock()
                mock_unique.all.return_value = [alice, bob]
                mock_scalars.unique.return_value = mock_unique
                mock_result.scalars.return_value = mock_scalars
            elif call_count == 2:
                # Alice: 180 minutes
                mock_result.scalar.return_value = 180
            elif call_count == 3:
                # Bob: 90 minutes
                mock_result.scalar.return_value = 90
            return mock_result

        mock_db.execute = fake_execute

        svc = StaffService(mock_db)
        result = await svc.get_labour_costs(
            org_id, date(2024, 6, 1), date(2024, 6, 30),
        )

        assert len(result["entries"]) == 2
        # Alice: 180/60 × 50 = 150
        assert result["entries"][0]["total_cost"] == Decimal("150.00")
        # Bob: 90/60 × 75 = 112.50
        assert result["entries"][1]["total_cost"] == Decimal("112.50")
        # Grand total: 150 + 112.50 = 262.50
        assert result["total_cost"] == Decimal("262.50")

    @pytest.mark.asyncio
    async def test_zero_time_entries_zero_cost(self):
        """Staff with no time entries has zero labour cost."""
        org_id = uuid.uuid4()
        staff = _make_staff(org_id, name="Idle Worker", hourly_rate=Decimal("60.00"))

        mock_db = _make_mock_db()
        call_count = 0

        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_scalars = MagicMock()
                mock_unique = MagicMock()
                mock_unique.all.return_value = [staff]
                mock_scalars.unique.return_value = mock_unique
                mock_result.scalars.return_value = mock_scalars
            else:
                mock_result.scalar.return_value = 0
            return mock_result

        mock_db.execute = fake_execute

        svc = StaffService(mock_db)
        result = await svc.get_labour_costs(
            org_id, date(2024, 6, 1), date(2024, 6, 30),
        )

        assert result["entries"][0]["total_cost"] == Decimal("0")
        assert result["total_cost"] == Decimal("0")

    @pytest.mark.asyncio
    async def test_null_hourly_rate_zero_cost(self):
        """Staff with no hourly rate set has zero labour cost."""
        org_id = uuid.uuid4()
        staff = _make_staff(org_id, name="No Rate", hourly_rate=None)

        mock_db = _make_mock_db()
        call_count = 0

        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_scalars = MagicMock()
                mock_unique = MagicMock()
                mock_unique.all.return_value = [staff]
                mock_scalars.unique.return_value = mock_unique
                mock_result.scalars.return_value = mock_scalars
            else:
                mock_result.scalar.return_value = 60
            return mock_result

        mock_db.execute = fake_execute

        svc = StaffService(mock_db)
        result = await svc.get_labour_costs(
            org_id, date(2024, 6, 1), date(2024, 6, 30),
        )

        # 60 min at $0/hr = $0
        assert result["entries"][0]["total_cost"] == Decimal("0")
        assert result["entries"][0]["hourly_rate"] == Decimal("0")
