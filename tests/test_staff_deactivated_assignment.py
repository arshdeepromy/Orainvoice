"""Test: deactivated staff cannot be assigned to new locations/jobs.

**Validates: Requirement — Staff Module — Task 24.5**

Verifies that when a staff member is deactivated (is_active=False),
they cannot be assigned to new locations via StaffService.assign_to_location().
"""

from __future__ import annotations

import uuid
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
    is_active: bool = True,
    name: str = "Test Staff",
    hourly_rate: Decimal = Decimal("50.00"),
) -> StaffMember:
    """Create a StaffMember instance for testing."""
    return StaffMember(
        id=uuid.uuid4(),
        org_id=org_id,
        name=name,
        email="test@example.com",
        role_type="employee",
        hourly_rate=hourly_rate,
        is_active=is_active,
        availability_schedule={},
        skills=[],
    )


class TestDeactivatedStaffAssignment:
    """Validates: deactivated staff cannot be assigned to new locations."""

    @pytest.mark.asyncio
    async def test_inactive_staff_cannot_be_assigned_to_location(self):
        """Assigning an inactive staff member to a location raises ValueError."""
        org_id = uuid.uuid4()
        staff = _make_staff(org_id, is_active=False, name="Inactive Worker")
        location_id = uuid.uuid4()

        mock_db = _make_mock_db()

        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = staff
            return mock_result

        mock_db.execute = fake_execute

        svc = StaffService(mock_db)
        with pytest.raises(ValueError, match="Cannot assign inactive staff"):
            await svc.assign_to_location(org_id, staff.id, location_id)

    @pytest.mark.asyncio
    async def test_active_staff_can_be_assigned_to_location(self):
        """Assigning an active staff member to a location succeeds."""
        org_id = uuid.uuid4()
        staff = _make_staff(org_id, is_active=True, name="Active Worker")
        location_id = uuid.uuid4()

        mock_db = _make_mock_db()
        call_count = 0

        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                # First call: get_staff lookup
                mock_result.scalar_one_or_none.return_value = staff
            else:
                # Second call: check existing assignment
                mock_result.scalar_one_or_none.return_value = None
            return mock_result

        mock_db.execute = fake_execute

        svc = StaffService(mock_db)
        assignment = await svc.assign_to_location(org_id, staff.id, location_id)

        assert assignment.staff_id == staff.id
        assert assignment.location_id == location_id

    @pytest.mark.asyncio
    async def test_deactivated_after_creation_cannot_be_reassigned(self):
        """Staff deactivated after initial creation cannot be assigned to new locations."""
        org_id = uuid.uuid4()
        staff = _make_staff(org_id, is_active=True, name="Soon Inactive")
        # Simulate deactivation
        staff.is_active = False
        location_id = uuid.uuid4()

        mock_db = _make_mock_db()

        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = staff
            return mock_result

        mock_db.execute = fake_execute

        svc = StaffService(mock_db)
        with pytest.raises(ValueError, match="Cannot assign inactive staff"):
            await svc.assign_to_location(org_id, staff.id, location_id)

    @pytest.mark.asyncio
    async def test_nonexistent_staff_raises_error(self):
        """Assigning a non-existent staff member raises ValueError."""
        org_id = uuid.uuid4()
        fake_staff_id = uuid.uuid4()
        location_id = uuid.uuid4()

        mock_db = _make_mock_db()

        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            return mock_result

        mock_db.execute = fake_execute

        svc = StaffService(mock_db)
        with pytest.raises(ValueError, match="Staff member not found"):
            await svc.assign_to_location(org_id, fake_staff_id, location_id)
