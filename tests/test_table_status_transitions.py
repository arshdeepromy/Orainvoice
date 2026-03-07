"""Test: table status transitions follow correct flow.

**Validates: Requirement — Table Module — Task 31.7**

Verifies that TableService.update_status() enforces the valid transition map:
  available → occupied, reserved
  occupied → needs_cleaning
  needs_cleaning → available
  reserved → occupied, available
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.tables.models import RestaurantTable
from app.modules.tables.service import TableService, VALID_STATUS_TRANSITIONS

ORG_ID = uuid.uuid4()


def _make_table(*, status: str = "available") -> RestaurantTable:
    return RestaurantTable(
        id=uuid.uuid4(),
        org_id=ORG_ID,
        table_number="T1",
        seat_count=4,
        status=status,
    )


def _make_mock_db(table: RestaurantTable | None = None):
    mock_db = AsyncMock()

    async def fake_execute(stmt):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = table
        return mock_result

    mock_db.execute = fake_execute
    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock()
    return mock_db


class TestValidTransitions:
    """Test that valid status transitions are accepted."""

    @pytest.mark.asyncio
    async def test_available_to_occupied(self):
        table = _make_table(status="available")
        svc = TableService(_make_mock_db(table))
        result = await svc.update_status(ORG_ID, table.id, "occupied")
        assert result.status == "occupied"

    @pytest.mark.asyncio
    async def test_available_to_reserved(self):
        table = _make_table(status="available")
        svc = TableService(_make_mock_db(table))
        result = await svc.update_status(ORG_ID, table.id, "reserved")
        assert result.status == "reserved"

    @pytest.mark.asyncio
    async def test_occupied_to_needs_cleaning(self):
        table = _make_table(status="occupied")
        svc = TableService(_make_mock_db(table))
        result = await svc.update_status(ORG_ID, table.id, "needs_cleaning")
        assert result.status == "needs_cleaning"

    @pytest.mark.asyncio
    async def test_needs_cleaning_to_available(self):
        table = _make_table(status="needs_cleaning")
        svc = TableService(_make_mock_db(table))
        result = await svc.update_status(ORG_ID, table.id, "available")
        assert result.status == "available"

    @pytest.mark.asyncio
    async def test_reserved_to_occupied(self):
        table = _make_table(status="reserved")
        svc = TableService(_make_mock_db(table))
        result = await svc.update_status(ORG_ID, table.id, "occupied")
        assert result.status == "occupied"

    @pytest.mark.asyncio
    async def test_reserved_to_available(self):
        table = _make_table(status="reserved")
        svc = TableService(_make_mock_db(table))
        result = await svc.update_status(ORG_ID, table.id, "available")
        assert result.status == "available"

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        """available → occupied → needs_cleaning → available."""
        table = _make_table(status="available")
        svc = TableService(_make_mock_db(table))

        result = await svc.update_status(ORG_ID, table.id, "occupied")
        assert result.status == "occupied"

        result = await svc.update_status(ORG_ID, table.id, "needs_cleaning")
        assert result.status == "needs_cleaning"

        result = await svc.update_status(ORG_ID, table.id, "available")
        assert result.status == "available"


class TestInvalidTransitions:
    """Test that invalid status transitions are rejected."""

    @pytest.mark.asyncio
    async def test_available_to_needs_cleaning_rejected(self):
        table = _make_table(status="available")
        svc = TableService(_make_mock_db(table))
        with pytest.raises(ValueError, match="Invalid transition"):
            await svc.update_status(ORG_ID, table.id, "needs_cleaning")

    @pytest.mark.asyncio
    async def test_occupied_to_available_rejected(self):
        table = _make_table(status="occupied")
        svc = TableService(_make_mock_db(table))
        with pytest.raises(ValueError, match="Invalid transition"):
            await svc.update_status(ORG_ID, table.id, "available")

    @pytest.mark.asyncio
    async def test_occupied_to_reserved_rejected(self):
        table = _make_table(status="occupied")
        svc = TableService(_make_mock_db(table))
        with pytest.raises(ValueError, match="Invalid transition"):
            await svc.update_status(ORG_ID, table.id, "reserved")

    @pytest.mark.asyncio
    async def test_needs_cleaning_to_occupied_rejected(self):
        table = _make_table(status="needs_cleaning")
        svc = TableService(_make_mock_db(table))
        with pytest.raises(ValueError, match="Invalid transition"):
            await svc.update_status(ORG_ID, table.id, "occupied")

    @pytest.mark.asyncio
    async def test_invalid_status_value_rejected(self):
        table = _make_table(status="available")
        svc = TableService(_make_mock_db(table))
        with pytest.raises(ValueError, match="Invalid status"):
            await svc.update_status(ORG_ID, table.id, "nonexistent")

    @pytest.mark.asyncio
    async def test_table_not_found_rejected(self):
        svc = TableService(_make_mock_db(None))
        with pytest.raises(ValueError, match="Table not found"):
            await svc.update_status(ORG_ID, uuid.uuid4(), "occupied")
