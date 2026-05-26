"""Integration tests for enhanced POST /kiosk/check-in endpoint (v2).

Tests cover the full request/response cycle through the service function:
  - New customer + vehicles linked: customer created, vehicles linked, is_new_customer=True
  - Existing customer (existing_customer_id) + vehicles linked: customer updated, is_new_customer=False
  - No vehicles (backward compatibility): empty vehicles list, customer created, vehicles_linked=0
  - Odometer recording: vehicles with non-null odometer_km create OdometerReading records
  - Idempotent linking: duplicate vehicle entries don't create duplicate CustomerVehicle records

Requirements: 6.1, 6.2, 6.3, 6.4, 7.2, 7.3, 9.5, 9.6
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

# Ensure SQLAlchemy relationship models are loaded
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401
import app.modules.organisations.models  # noqa: F401

from app.modules.kiosk.schemas import KioskCheckInRequestV2, KioskVehicleEntry
from app.modules.kiosk.service import kiosk_check_in_v2
from app.modules.vehicles.models import OdometerReading


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_customer(**overrides):
    """Build a mock Customer ORM object."""
    c = MagicMock()
    c.id = overrides.get("id", uuid.uuid4())
    c.org_id = overrides.get("org_id", uuid.uuid4())
    c.first_name = overrides.get("first_name", "Jane")
    c.last_name = overrides.get("last_name", "Doe")
    c.phone = overrides.get("phone", "0211234567")
    c.email = overrides.get("email", "jane@example.com")
    c.is_anonymised = overrides.get("is_anonymised", False)
    return c


def _make_scalar_result(value):
    """Create a mock DB execute result that returns value from scalar_one_or_none."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _make_checkin_request(**overrides) -> KioskCheckInRequestV2:
    """Build a valid KioskCheckInRequestV2 with sensible defaults."""
    defaults = {
        "first_name": "John",
        "last_name": "Smith",
        "phone": "0211234567",
        "email": "john@example.com",
        "vehicles": [],
        "existing_customer_id": None,
    }
    defaults.update(overrides)
    return KioskCheckInRequestV2(**defaults)


# ---------------------------------------------------------------------------
# Integration Tests: New Customer + Vehicles Linked
# ---------------------------------------------------------------------------


class TestCheckInV2NewCustomerWithVehicles:
    """New customer + vehicles linked: customer created, vehicles linked.

    Requirements: 6.1, 6.2, 7.2, 7.3
    """

    @pytest.mark.asyncio
    async def test_new_customer_created_with_vehicles_linked(self):
        """When no existing customer matches, creates new customer and links vehicles."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        vehicle_id_1 = uuid.uuid4()
        vehicle_id_2 = uuid.uuid4()

        request = _make_checkin_request(
            first_name="Alice",
            last_name="Wonder",
            phone="0279876543",
            vehicles=[
                KioskVehicleEntry(global_vehicle_id=str(vehicle_id_1)),
                KioskVehicleEntry(global_vehicle_id=str(vehicle_id_2)),
            ],
        )

        customer_dict = {
            "id": str(uuid.uuid4()),
            "first_name": "Alice",
            "last_name": "Wonder",
            "phone": "0279876543",
        }

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(None))
        db.flush = AsyncMock()
        db.add = MagicMock()

        with patch(
            "app.modules.customers.service.create_customer",
            new_callable=AsyncMock,
            return_value=customer_dict,
        ), patch(
            "app.modules.kiosk.service._ensure_vehicle_linked",
            new_callable=AsyncMock,
        ) as mock_ensure_linked:
            result = await kiosk_check_in_v2(
                db,
                org_id=org_id,
                user_id=user_id,
                data=request,
                ip_address="10.0.0.1",
            )

        assert result.customer_first_name == "Alice"
        assert result.is_new_customer is True
        assert result.vehicles_linked == 2
        assert mock_ensure_linked.call_count == 2

    @pytest.mark.asyncio
    async def test_new_customer_response_has_correct_vehicle_count(self):
        """Response vehicles_linked matches the number of vehicles in the request."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        vehicle_ids = [uuid.uuid4() for _ in range(3)]

        request = _make_checkin_request(
            vehicles=[
                KioskVehicleEntry(global_vehicle_id=str(vid))
                for vid in vehicle_ids
            ],
        )

        customer_dict = {
            "id": str(uuid.uuid4()),
            "first_name": "John",
            "last_name": "Smith",
            "phone": "0211234567",
        }

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(None))
        db.flush = AsyncMock()
        db.add = MagicMock()

        with patch(
            "app.modules.customers.service.create_customer",
            new_callable=AsyncMock,
            return_value=customer_dict,
        ), patch(
            "app.modules.kiosk.service._ensure_vehicle_linked",
            new_callable=AsyncMock,
        ):
            result = await kiosk_check_in_v2(
                db,
                org_id=org_id,
                user_id=user_id,
                data=request,
            )

        assert result.vehicles_linked == 3
        assert result.is_new_customer is True


# ---------------------------------------------------------------------------
# Integration Tests: Existing Customer + Vehicles Linked
# ---------------------------------------------------------------------------


class TestCheckInV2ExistingCustomerWithVehicles:
    """Existing customer (existing_customer_id) + vehicles linked.

    Requirements: 6.1, 6.2, 7.2, 9.5, 9.6
    """

    @pytest.mark.asyncio
    async def test_existing_customer_updated_and_vehicles_linked(self):
        """When existing_customer_id is provided, updates customer and links vehicles."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        vehicle_id = uuid.uuid4()

        existing_customer = _make_mock_customer(
            id=customer_id,
            org_id=org_id,
            first_name="Jane",
            last_name="Doe",
            phone="0211234567",
        )

        request = _make_checkin_request(
            first_name="Janet",
            last_name="Doe",
            phone="0211234567",
            existing_customer_id=str(customer_id),
            vehicles=[
                KioskVehicleEntry(global_vehicle_id=str(vehicle_id)),
            ],
        )

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(existing_customer))
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()

        with patch(
            "app.modules.kiosk.service._ensure_vehicle_linked",
            new_callable=AsyncMock,
        ) as mock_ensure_linked:
            result = await kiosk_check_in_v2(
                db,
                org_id=org_id,
                user_id=user_id,
                data=request,
            )

        assert result.is_new_customer is False
        assert result.vehicles_linked == 1
        assert result.customer_first_name == "Janet"
        mock_ensure_linked.assert_called_once()

    @pytest.mark.asyncio
    async def test_existing_customer_not_found_raises_404(self):
        """When existing_customer_id doesn't match any customer, raises 404."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        fake_customer_id = uuid.uuid4()

        request = _make_checkin_request(
            existing_customer_id=str(fake_customer_id),
        )

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(None))

        with pytest.raises(HTTPException) as exc_info:
            await kiosk_check_in_v2(
                db,
                org_id=org_id,
                user_id=user_id,
                data=request,
            )

        assert exc_info.value.status_code == 404
        assert "customer" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_existing_customer_details_updated(self):
        """When existing customer details differ from request, they are updated."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        existing_customer = _make_mock_customer(
            id=customer_id,
            org_id=org_id,
            first_name="Old",
            last_name="Name",
            phone="0211234567",
            email="old@example.com",
        )

        request = _make_checkin_request(
            first_name="New",
            last_name="Name",
            phone="0219999999",
            email="new@example.com",
            existing_customer_id=str(customer_id),
        )

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(existing_customer))
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()

        with patch(
            "app.modules.kiosk.service._ensure_vehicle_linked",
            new_callable=AsyncMock,
        ):
            result = await kiosk_check_in_v2(
                db,
                org_id=org_id,
                user_id=user_id,
                data=request,
            )

        assert result.is_new_customer is False
        assert result.customer_first_name == "New"
        # Verify customer fields were updated
        assert existing_customer.first_name == "New"
        assert existing_customer.phone == "0219999999"
        assert existing_customer.email == "new@example.com"

    @pytest.mark.asyncio
    async def test_existing_customer_field_change_emits_audit_log(self):
        """When existing customer fields are updated, a customer.updated audit
        row is written so kiosk-driven edits are visible in the merge/audit
        history (Req 9.6)."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        existing_customer = _make_mock_customer(
            id=customer_id,
            org_id=org_id,
            first_name="Old",
            last_name="Name",
            phone="0211234567",
            email="old@example.com",
        )

        request = _make_checkin_request(
            first_name="Jane",
            last_name="Name",
            phone="0211234567",
            email="old@example.com",
            existing_customer_id=str(customer_id),
        )

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(existing_customer))
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()

        with patch(
            "app.modules.kiosk.service._ensure_vehicle_linked",
            new_callable=AsyncMock,
        ), patch(
            "app.core.audit.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            await kiosk_check_in_v2(
                db,
                org_id=org_id,
                user_id=user_id,
                data=request,
                ip_address="127.0.0.1",
            )

        mock_audit.assert_called_once()
        kwargs = mock_audit.call_args.kwargs
        assert kwargs["action"] == "customer.updated"
        assert kwargs["entity_type"] == "customer"
        assert kwargs["entity_id"] == customer_id
        assert kwargs["org_id"] == org_id
        assert kwargs["user_id"] == user_id
        assert kwargs["before_value"] == {"first_name": "Old"}
        assert kwargs["after_value"] == {"first_name": "Jane"}
        assert kwargs["ip_address"] == "127.0.0.1"

    @pytest.mark.asyncio
    async def test_existing_customer_no_changes_skips_audit_log(self):
        """When the kiosk submission matches existing customer fields exactly,
        no customer.updated audit row is emitted (no-op write)."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        existing_customer = _make_mock_customer(
            id=customer_id,
            org_id=org_id,
            first_name="Same",
            last_name="Name",
            phone="0211234567",
            email="same@example.com",
        )

        request = _make_checkin_request(
            first_name="Same",
            last_name="Name",
            phone="0211234567",
            email="same@example.com",
            existing_customer_id=str(customer_id),
        )

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(existing_customer))
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()

        with patch(
            "app.modules.kiosk.service._ensure_vehicle_linked",
            new_callable=AsyncMock,
        ), patch(
            "app.core.audit.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            await kiosk_check_in_v2(
                db,
                org_id=org_id,
                user_id=user_id,
                data=request,
            )

        mock_audit.assert_not_called()


# ---------------------------------------------------------------------------
# Integration Tests: No Vehicles (Backward Compatibility)
# ---------------------------------------------------------------------------


class TestCheckInV2NoVehicles:
    """No vehicles (backward compatibility): empty vehicles list, customer created.

    Requirements: 7.2, 7.3
    """

    @pytest.mark.asyncio
    async def test_empty_vehicles_creates_customer_only(self):
        """When vehicles list is empty, creates customer without any vehicle linking."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        request = _make_checkin_request(
            first_name="Bob",
            last_name="Builder",
            phone="0221112222",
            vehicles=[],
        )

        customer_dict = {
            "id": str(uuid.uuid4()),
            "first_name": "Bob",
            "last_name": "Builder",
            "phone": "0221112222",
        }

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(None))
        db.flush = AsyncMock()
        db.add = MagicMock()

        with patch(
            "app.modules.customers.service.create_customer",
            new_callable=AsyncMock,
            return_value=customer_dict,
        ) as mock_create, patch(
            "app.modules.kiosk.service._ensure_vehicle_linked",
            new_callable=AsyncMock,
        ) as mock_ensure_linked:
            result = await kiosk_check_in_v2(
                db,
                org_id=org_id,
                user_id=user_id,
                data=request,
            )

        assert result.customer_first_name == "Bob"
        assert result.is_new_customer is True
        assert result.vehicles_linked == 0
        mock_create.assert_called_once()
        mock_ensure_linked.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_vehicles_does_not_call_flush_for_vehicles(self):
        """When no vehicles are provided, flush is not called for vehicle linking."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        request = _make_checkin_request(vehicles=[])

        customer_dict = {
            "id": str(uuid.uuid4()),
            "first_name": "John",
            "last_name": "Smith",
            "phone": "0211234567",
        }

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(None))
        db.flush = AsyncMock()
        db.add = MagicMock()

        with patch(
            "app.modules.customers.service.create_customer",
            new_callable=AsyncMock,
            return_value=customer_dict,
        ):
            await kiosk_check_in_v2(
                db,
                org_id=org_id,
                user_id=user_id,
                data=request,
            )

        # flush should NOT be called since there are no vehicles to link
        db.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_vehicles_no_odometer_added(self):
        """When no vehicles are provided, no OdometerReading objects are added."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        request = _make_checkin_request(vehicles=[])

        customer_dict = {
            "id": str(uuid.uuid4()),
            "first_name": "John",
            "last_name": "Smith",
            "phone": "0211234567",
        }

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(None))
        db.flush = AsyncMock()
        db.add = MagicMock()

        with patch(
            "app.modules.customers.service.create_customer",
            new_callable=AsyncMock,
            return_value=customer_dict,
        ):
            await kiosk_check_in_v2(
                db,
                org_id=org_id,
                user_id=user_id,
                data=request,
            )

        # db.add should not be called (no OdometerReading objects)
        db.add.assert_not_called()


# ---------------------------------------------------------------------------
# Integration Tests: Odometer Recording
# ---------------------------------------------------------------------------


class TestCheckInV2OdometerRecording:
    """Odometer recording: vehicles with non-null odometer_km create OdometerReading records.

    Requirements: 6.3
    """

    @pytest.mark.asyncio
    async def test_odometer_reading_created_for_vehicle_with_km(self):
        """When a vehicle has odometer_km set, an OdometerReading is added to the session."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        vehicle_id = uuid.uuid4()

        request = _make_checkin_request(
            vehicles=[
                KioskVehicleEntry(global_vehicle_id=str(vehicle_id), odometer_km=85000),
            ],
        )

        customer_dict = {
            "id": str(uuid.uuid4()),
            "first_name": "John",
            "last_name": "Smith",
            "phone": "0211234567",
        }

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(None))
        db.flush = AsyncMock()
        db.add = MagicMock()

        # Mock promote_vehicle so the kiosk path's per-org odometer bump
        # has a target without hitting ModuleService / advisory locks.
        mock_org_vehicle = MagicMock()
        mock_org_vehicle.odometer_last_recorded = None

        with patch(
            "app.modules.customers.service.create_customer",
            new_callable=AsyncMock,
            return_value=customer_dict,
        ), patch(
            "app.modules.kiosk.service._ensure_vehicle_linked",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.vehicles.service.promote_vehicle",
            new_callable=AsyncMock,
            return_value=mock_org_vehicle,
        ):
            await kiosk_check_in_v2(
                db,
                org_id=org_id,
                user_id=user_id,
                data=request,
            )

        # Verify OdometerReading was added
        db.add.assert_called_once()
        odometer_obj = db.add.call_args[0][0]
        assert isinstance(odometer_obj, OdometerReading)
        assert odometer_obj.global_vehicle_id == vehicle_id
        assert odometer_obj.reading_km == 85000
        assert odometer_obj.source == "kiosk"
        assert odometer_obj.recorded_by == user_id
        assert odometer_obj.org_id == org_id
        # The per-org cache should have been bumped via promote_vehicle.
        assert mock_org_vehicle.odometer_last_recorded == 85000

    @pytest.mark.asyncio
    async def test_no_odometer_reading_when_km_is_none(self):
        """When a vehicle has odometer_km=None, no OdometerReading is created."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        vehicle_id = uuid.uuid4()

        request = _make_checkin_request(
            vehicles=[
                KioskVehicleEntry(global_vehicle_id=str(vehicle_id), odometer_km=None),
            ],
        )

        customer_dict = {
            "id": str(uuid.uuid4()),
            "first_name": "John",
            "last_name": "Smith",
            "phone": "0211234567",
        }

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(None))
        db.flush = AsyncMock()
        db.add = MagicMock()

        with patch(
            "app.modules.customers.service.create_customer",
            new_callable=AsyncMock,
            return_value=customer_dict,
        ), patch(
            "app.modules.kiosk.service._ensure_vehicle_linked",
            new_callable=AsyncMock,
        ):
            await kiosk_check_in_v2(
                db,
                org_id=org_id,
                user_id=user_id,
                data=request,
            )

        # db.add should NOT be called (no odometer reading)
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_vehicles_only_records_odometer_for_those_with_km(self):
        """Only vehicles with non-null odometer_km get OdometerReading records."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        vehicle_id_1 = uuid.uuid4()
        vehicle_id_2 = uuid.uuid4()
        vehicle_id_3 = uuid.uuid4()

        request = _make_checkin_request(
            vehicles=[
                KioskVehicleEntry(global_vehicle_id=str(vehicle_id_1), odometer_km=50000),
                KioskVehicleEntry(global_vehicle_id=str(vehicle_id_2), odometer_km=None),
                KioskVehicleEntry(global_vehicle_id=str(vehicle_id_3), odometer_km=120000),
            ],
        )

        customer_dict = {
            "id": str(uuid.uuid4()),
            "first_name": "John",
            "last_name": "Smith",
            "phone": "0211234567",
        }

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(None))
        db.flush = AsyncMock()
        db.add = MagicMock()

        mock_org_vehicle = MagicMock()
        mock_org_vehicle.odometer_last_recorded = None

        with patch(
            "app.modules.customers.service.create_customer",
            new_callable=AsyncMock,
            return_value=customer_dict,
        ), patch(
            "app.modules.kiosk.service._ensure_vehicle_linked",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.vehicles.service.promote_vehicle",
            new_callable=AsyncMock,
            return_value=mock_org_vehicle,
        ):
            await kiosk_check_in_v2(
                db,
                org_id=org_id,
                user_id=user_id,
                data=request,
            )

        # Only 2 OdometerReading objects should be added (vehicles 1 and 3)
        assert db.add.call_count == 2

        odometer_1 = db.add.call_args_list[0][0][0]
        assert isinstance(odometer_1, OdometerReading)
        assert odometer_1.global_vehicle_id == vehicle_id_1
        assert odometer_1.reading_km == 50000
        assert odometer_1.source == "kiosk"

        odometer_2 = db.add.call_args_list[1][0][0]
        assert isinstance(odometer_2, OdometerReading)
        assert odometer_2.global_vehicle_id == vehicle_id_3
        assert odometer_2.reading_km == 120000
        assert odometer_2.source == "kiosk"


# ---------------------------------------------------------------------------
# Integration Tests: Idempotent Linking
# ---------------------------------------------------------------------------


class TestCheckInV2IdempotentLinking:
    """Idempotent linking: duplicate vehicle entries don't create duplicate records.

    Requirements: 6.4
    """

    @pytest.mark.asyncio
    async def test_duplicate_vehicle_entries_calls_ensure_linked_for_each(self):
        """When the same vehicle appears twice, _ensure_vehicle_linked is called for each entry."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        vehicle_id = uuid.uuid4()

        request = _make_checkin_request(
            vehicles=[
                KioskVehicleEntry(global_vehicle_id=str(vehicle_id)),
                KioskVehicleEntry(global_vehicle_id=str(vehicle_id)),
            ],
        )

        customer_dict = {
            "id": str(uuid.uuid4()),
            "first_name": "John",
            "last_name": "Smith",
            "phone": "0211234567",
        }

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(None))
        db.flush = AsyncMock()
        db.add = MagicMock()

        with patch(
            "app.modules.customers.service.create_customer",
            new_callable=AsyncMock,
            return_value=customer_dict,
        ), patch(
            "app.modules.kiosk.service._ensure_vehicle_linked",
            new_callable=AsyncMock,
        ) as mock_ensure_linked:
            result = await kiosk_check_in_v2(
                db,
                org_id=org_id,
                user_id=user_id,
                data=request,
            )

        # _ensure_vehicle_linked is called for each entry (it handles idempotency internally)
        assert mock_ensure_linked.call_count == 2
        # Both calls use the same vehicle_id
        call_vehicle_ids = [
            call.kwargs["vehicle_id"] for call in mock_ensure_linked.call_args_list
        ]
        assert call_vehicle_ids == [vehicle_id, vehicle_id]
        # vehicles_linked count reflects total entries processed
        assert result.vehicles_linked == 2

    @pytest.mark.asyncio
    async def test_ensure_vehicle_linked_skips_existing_link(self):
        """_ensure_vehicle_linked skips link creation when link already exists in DB."""
        import sys
        from types import ModuleType

        from app.modules.kiosk.service import _ensure_vehicle_linked

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        vehicle_id = uuid.uuid4()

        # Simulate existing link found in DB
        existing_link = MagicMock()

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(existing_link))

        # Mock the vehicles.service module to make it importable
        mock_vehicles_service = ModuleType("app.modules.vehicles.service")
        mock_link_fn = AsyncMock()
        mock_vehicles_service.link_vehicle_to_customer = mock_link_fn
        with patch.dict(sys.modules, {"app.modules.vehicles.service": mock_vehicles_service}):
            await _ensure_vehicle_linked(
                db,
                vehicle_id=vehicle_id,
                customer_id=customer_id,
                org_id=org_id,
                user_id=user_id,
            )

        # link_vehicle_to_customer should NOT be called (link already exists)
        mock_link_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_vehicle_linked_creates_link_when_not_exists(self):
        """_ensure_vehicle_linked creates a link when no existing link is found."""
        import sys
        from types import ModuleType

        from app.modules.kiosk.service import _ensure_vehicle_linked

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        vehicle_id = uuid.uuid4()

        # Simulate no existing link
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(None))

        # Mock the vehicles.service module to make it importable
        mock_vehicles_service = ModuleType("app.modules.vehicles.service")
        mock_link_fn = AsyncMock()
        mock_vehicles_service.link_vehicle_to_customer = mock_link_fn
        with patch.dict(sys.modules, {"app.modules.vehicles.service": mock_vehicles_service}):
            await _ensure_vehicle_linked(
                db,
                vehicle_id=vehicle_id,
                customer_id=customer_id,
                org_id=org_id,
                user_id=user_id,
                ip_address="10.0.0.1",
            )

        # link_vehicle_to_customer should be called once
        mock_link_fn.assert_called_once_with(
            db,
            vehicle_id=vehicle_id,
            customer_id=customer_id,
            org_id=org_id,
            user_id=user_id,
            ip_address="10.0.0.1",
        )


# ---------------------------------------------------------------------------
# Integration Tests: Router Handler Flow
# ---------------------------------------------------------------------------


class TestCheckInV2RouterHandler:
    """Test the full router handler function (check_in) end-to-end.

    Requirements: 7.2, 7.3
    """

    @pytest.mark.asyncio
    async def test_router_handler_returns_result(self):
        """The check_in router handler returns the check-in result correctly."""
        from app.modules.kiosk.router import check_in

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        request_mock = MagicMock()
        request_mock.state.user_id = str(user_id)
        request_mock.state.org_id = str(org_id)
        request_mock.state.client_ip = "10.0.0.1"

        payload = _make_checkin_request(
            first_name="Test",
            last_name="User",
            phone="0211234567",
            vehicles=[],
        )

        customer_dict = {
            "id": str(uuid.uuid4()),
            "first_name": "Test",
            "last_name": "User",
            "phone": "0211234567",
        }

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(None))
        db.flush = AsyncMock()
        db.add = MagicMock()

        with patch(
            "app.modules.customers.service.create_customer",
            new_callable=AsyncMock,
            return_value=customer_dict,
        ):
            result = await check_in(
                payload=payload,
                request=request_mock,
                db=db,
            )

        assert result.customer_first_name == "Test"
        assert result.is_new_customer is True
        assert result.vehicles_linked == 0

    @pytest.mark.asyncio
    async def test_router_handler_returns_403_without_org_context(self):
        """The check_in handler returns 403 when org context is missing."""
        from app.modules.kiosk.router import check_in

        request_mock = MagicMock()
        request_mock.state.user_id = str(uuid.uuid4())
        request_mock.state.org_id = None
        request_mock.state.client_ip = "10.0.0.1"

        payload = _make_checkin_request()
        db = AsyncMock()

        result = await check_in(
            payload=payload,
            request=request_mock,
            db=db,
        )

        # Should return a JSONResponse with 403
        assert result.status_code == 403
