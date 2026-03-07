"""Unit tests for vehicle refresh and manual entry — Task 8.3.

Tests cover:
  - Refresh: force Carjam re-fetch, update GlobalVehicle, increment org counter
  - Refresh: vehicle not found returns error
  - Refresh: Carjam errors propagate correctly
  - Manual entry: creates OrgVehicle record marked as "manually entered"
  - Manual entry: stored in org_vehicles, NOT Global_Vehicle_DB
  - Manual entry: rego normalised to uppercase

Requirements: 14.5, 14.6, 14.7
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models to resolve SQLAlchemy relationships
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401

from app.integrations.carjam import (
    CarjamError,
    CarjamNotFoundError,
    CarjamRateLimitError,
    CarjamVehicleData,
)
from app.modules.vehicles.service import (
    _org_vehicle_to_dict,
    create_manual_vehicle,
    refresh_vehicle,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_global_vehicle(**overrides):
    """Build a mock GlobalVehicle ORM object."""
    gv = MagicMock()
    gv.id = overrides.get("id", uuid.uuid4())
    gv.rego = overrides.get("rego", "ABC123")
    gv.make = overrides.get("make", "Toyota")
    gv.model = overrides.get("model", "Corolla")
    gv.year = overrides.get("year", 2020)
    gv.colour = overrides.get("colour", "White")
    gv.body_type = overrides.get("body_type", "Sedan")
    gv.fuel_type = overrides.get("fuel_type", "Petrol")
    gv.engine_size = overrides.get("engine_size", "1.8L")
    gv.num_seats = overrides.get("num_seats", 5)
    gv.wof_expiry = overrides.get("wof_expiry", date(2025, 6, 1))
    gv.registration_expiry = overrides.get("registration_expiry", date(2025, 12, 1))
    gv.odometer_last_recorded = overrides.get("odometer_last_recorded", 45000)
    gv.last_pulled_at = overrides.get("last_pulled_at", datetime(2025, 1, 15, tzinfo=timezone.utc))
    return gv


def _make_org(**overrides):
    """Build a mock Organisation ORM object."""
    org = MagicMock()
    org.id = overrides.get("id", uuid.uuid4())
    org.carjam_lookups_this_month = overrides.get("carjam_lookups_this_month", 5)
    return org


def _make_scalar_result(value):
    """Create a mock DB execute result that returns value from scalar_one_or_none."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _make_org_vehicle(**overrides):
    """Build a mock OrgVehicle object for testing _org_vehicle_to_dict."""
    ov = MagicMock()
    ov.id = overrides.get("id", uuid.uuid4())
    ov.org_id = overrides.get("org_id", uuid.uuid4())
    ov.rego = overrides.get("rego", "MAN001")
    ov.make = overrides.get("make", "Ford")
    ov.model = overrides.get("model", "Ranger")
    ov.year = overrides.get("year", 2018)
    ov.colour = overrides.get("colour", "Silver")
    ov.body_type = overrides.get("body_type", "Ute")
    ov.fuel_type = overrides.get("fuel_type", "Diesel")
    ov.engine_size = overrides.get("engine_size", "3.2L")
    ov.num_seats = overrides.get("num_seats", 5)
    ov.is_manual_entry = overrides.get("is_manual_entry", True)
    ov.created_at = overrides.get("created_at", datetime(2025, 3, 1, tzinfo=timezone.utc))
    return ov


# ---------------------------------------------------------------------------
# _org_vehicle_to_dict
# ---------------------------------------------------------------------------


class TestOrgVehicleToDict:
    def test_all_fields_present(self):
        ov = _make_org_vehicle()
        result = _org_vehicle_to_dict(ov)

        assert result["rego"] == "MAN001"
        assert result["make"] == "Ford"
        assert result["model"] == "Ranger"
        assert result["year"] == 2018
        assert result["colour"] == "Silver"
        assert result["body_type"] == "Ute"
        assert result["fuel_type"] == "Diesel"
        assert result["engine_size"] == "3.2L"
        assert result["num_seats"] == 5
        assert result["is_manual_entry"] is True
        assert result["created_at"] is not None
        assert result["id"] is not None
        assert result["org_id"] is not None


# ---------------------------------------------------------------------------
# refresh_vehicle — success (Req 14.5)
# ---------------------------------------------------------------------------


class TestRefreshVehicle:
    @pytest.mark.asyncio
    async def test_updates_global_vehicle_and_increments_counter(self):
        """Req 14.5: Refresh forces Carjam re-fetch, updates record, charges org."""
        vehicle_id = uuid.uuid4()
        org_id = uuid.uuid4()
        gv = _make_global_vehicle(id=vehicle_id, rego="REF123")
        org = _make_org(carjam_lookups_this_month=10)

        carjam_data = CarjamVehicleData(
            rego="REF123",
            make="Nissan",
            model="Leaf",
            year=2023,
            colour="Green",
            body_type="Hatchback",
            fuel_type="Electric",
            engine_size="N/A",
            seats=5,
            wof_expiry="2026-06-01",
            rego_expiry="2026-12-01",
            odometer=8000,
        )

        execute_calls = []

        async def _side_effect_execute(stmt, *args, **kwargs):
            execute_calls.append(stmt)
            if len(execute_calls) == 1:
                return _make_scalar_result(gv)
            elif len(execute_calls) == 2:
                return _make_scalar_result(org)
            return MagicMock()

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_side_effect_execute)
        db.flush = AsyncMock()
        redis = MagicMock()

        mock_client = AsyncMock()
        mock_client.lookup_vehicle = AsyncMock(return_value=carjam_data)

        with patch("app.modules.vehicles.service.CarjamClient", return_value=mock_client):
            with patch("app.modules.vehicles.service.write_audit_log", new_callable=AsyncMock):
                result = await refresh_vehicle(
                    db, redis,
                    vehicle_id=vehicle_id,
                    org_id=org_id,
                    user_id=uuid.uuid4(),
                )

        # Carjam was called
        mock_client.lookup_vehicle.assert_called_once_with("REF123")

        # GlobalVehicle fields updated
        assert gv.make == "Nissan"
        assert gv.model == "Leaf"
        assert gv.year == 2023
        assert gv.colour == "Green"
        assert gv.fuel_type == "Electric"
        assert gv.odometer_last_recorded == 8000

        # Org counter incremented
        assert org.carjam_lookups_this_month == 11

        # Response has correct data
        assert result["source"] == "carjam"
        assert result["rego"] == "REF123"
        assert result["make"] == "Nissan"

    @pytest.mark.asyncio
    async def test_vehicle_not_found_raises_value_error(self):
        """Refresh on non-existent vehicle raises ValueError."""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(None))
        redis = MagicMock()

        with pytest.raises(ValueError, match="not found"):
            await refresh_vehicle(
                db, redis,
                vehicle_id=uuid.uuid4(),
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_carjam_not_found_propagates(self):
        """If Carjam returns no result on refresh, CarjamNotFoundError propagates."""
        gv = _make_global_vehicle(rego="GONE999")

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(gv))
        redis = MagicMock()

        mock_client = AsyncMock()
        mock_client.lookup_vehicle = AsyncMock(
            side_effect=CarjamNotFoundError("GONE999")
        )

        with patch("app.modules.vehicles.service.CarjamClient", return_value=mock_client):
            with pytest.raises(CarjamNotFoundError):
                await refresh_vehicle(
                    db, redis,
                    vehicle_id=uuid.uuid4(),
                    org_id=uuid.uuid4(),
                    user_id=uuid.uuid4(),
                )

    @pytest.mark.asyncio
    async def test_carjam_rate_limit_propagates(self):
        """CarjamRateLimitError propagates on refresh."""
        gv = _make_global_vehicle(rego="LIM123")

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(gv))
        redis = MagicMock()

        mock_client = AsyncMock()
        mock_client.lookup_vehicle = AsyncMock(
            side_effect=CarjamRateLimitError(retry_after=60)
        )

        with patch("app.modules.vehicles.service.CarjamClient", return_value=mock_client):
            with pytest.raises(CarjamRateLimitError) as exc_info:
                await refresh_vehicle(
                    db, redis,
                    vehicle_id=uuid.uuid4(),
                    org_id=uuid.uuid4(),
                    user_id=uuid.uuid4(),
                )
            assert exc_info.value.retry_after == 60


# ---------------------------------------------------------------------------
# create_manual_vehicle (Req 14.6, 14.7)
# ---------------------------------------------------------------------------


class TestCreateManualVehicle:
    @pytest.mark.asyncio
    async def test_creates_org_vehicle_marked_as_manual(self):
        """Req 14.7: Manual entry stored in org_vehicles, marked as manually entered."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch("app.modules.vehicles.service.write_audit_log", new_callable=AsyncMock):
            with patch("app.modules.vehicles.models.OrgVehicle") as MockOrgVehicle:
                mock_instance = MagicMock()
                mock_instance.id = uuid.uuid4()
                mock_instance.org_id = org_id
                mock_instance.rego = "MAN456"
                mock_instance.make = "Subaru"
                mock_instance.model = "Outback"
                mock_instance.year = 2017
                mock_instance.colour = "Blue"
                mock_instance.body_type = "Wagon"
                mock_instance.fuel_type = "Petrol"
                mock_instance.engine_size = "2.5L"
                mock_instance.num_seats = 5
                mock_instance.is_manual_entry = True
                mock_instance.created_at = datetime(2025, 3, 1, tzinfo=timezone.utc)
                MockOrgVehicle.return_value = mock_instance

                result = await create_manual_vehicle(
                    db,
                    org_id=org_id,
                    user_id=user_id,
                    rego="man456",
                    make="Subaru",
                    model="Outback",
                    year=2017,
                    colour="Blue",
                    body_type="Wagon",
                    fuel_type="Petrol",
                    engine_size="2.5L",
                    num_seats=5,
                )

        # OrgVehicle was constructed with correct args
        MockOrgVehicle.assert_called_once()
        call_kwargs = MockOrgVehicle.call_args[1]
        assert call_kwargs["org_id"] == org_id
        assert call_kwargs["rego"] == "MAN456"  # normalised uppercase
        assert call_kwargs["is_manual_entry"] is True

        # Added to DB
        db.add.assert_called_once_with(mock_instance)

        # Response
        assert result["rego"] == "MAN456"
        assert result["make"] == "Subaru"
        assert result["is_manual_entry"] is True

    @pytest.mark.asyncio
    async def test_rego_normalised_to_uppercase(self):
        """Rego should be normalised to uppercase and trimmed."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch("app.modules.vehicles.service.write_audit_log", new_callable=AsyncMock):
            with patch("app.modules.vehicles.models.OrgVehicle") as MockOrgVehicle:
                mock_instance = MagicMock()
                mock_instance.id = uuid.uuid4()
                mock_instance.org_id = uuid.uuid4()
                mock_instance.rego = "LOW123"
                mock_instance.make = None
                mock_instance.model = None
                mock_instance.year = None
                mock_instance.colour = None
                mock_instance.body_type = None
                mock_instance.fuel_type = None
                mock_instance.engine_size = None
                mock_instance.num_seats = None
                mock_instance.is_manual_entry = True
                mock_instance.created_at = datetime(2025, 3, 1, tzinfo=timezone.utc)
                MockOrgVehicle.return_value = mock_instance

                await create_manual_vehicle(
                    db,
                    org_id=uuid.uuid4(),
                    user_id=uuid.uuid4(),
                    rego="  low123  ",
                )

        call_kwargs = MockOrgVehicle.call_args[1]
        assert call_kwargs["rego"] == "LOW123"

    @pytest.mark.asyncio
    async def test_audit_log_written(self):
        """Manual entry should write an audit log entry."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch("app.modules.vehicles.service.write_audit_log", new_callable=AsyncMock) as mock_audit:
            with patch("app.modules.vehicles.models.OrgVehicle") as MockOrgVehicle:
                mock_instance = MagicMock()
                mock_instance.id = uuid.uuid4()
                mock_instance.org_id = uuid.uuid4()
                mock_instance.rego = "AUD001"
                mock_instance.make = None
                mock_instance.model = None
                mock_instance.year = None
                mock_instance.colour = None
                mock_instance.body_type = None
                mock_instance.fuel_type = None
                mock_instance.engine_size = None
                mock_instance.num_seats = None
                mock_instance.is_manual_entry = True
                mock_instance.created_at = datetime(2025, 3, 1, tzinfo=timezone.utc)
                MockOrgVehicle.return_value = mock_instance

                await create_manual_vehicle(
                    db,
                    org_id=uuid.uuid4(),
                    user_id=uuid.uuid4(),
                    rego="AUD001",
                )

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args[1]
        assert call_kwargs["action"] == "vehicle.manual_entry"
        assert call_kwargs["entity_type"] == "org_vehicle"
