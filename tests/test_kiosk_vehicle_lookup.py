"""Unit tests for kiosk vehicle lookup (cascading) — Task 2.1.

Tests cover:
  - Org vehicle hit: returns data from org_vehicles without further lookups
  - Global vehicle hit: returns data from global_vehicles without CarJam call
  - CarJam success: calls CarJam, stores result in global_vehicles, returns data
  - CarJam not found: raises HTTP 404
  - CarJam rate limit: raises HTTP 429
  - CarJam generic error: raises HTTP 502
  - Rego normalisation (uppercase, trimmed)
  - Source field correctness for each lookup tier

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

# Import models to resolve SQLAlchemy relationships
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401

from app.integrations.carjam import (
    CarjamError,
    CarjamNotFoundError,
    CarjamRateLimitError,
    CarjamVehicleData,
)
from app.modules.kiosk.service import lookup_vehicle_for_kiosk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_org_vehicle(**overrides):
    """Build a mock OrgVehicle ORM object."""
    ov = MagicMock()
    ov.id = overrides.get("id", uuid.uuid4())
    ov.org_id = overrides.get("org_id", uuid.uuid4())
    ov.rego = overrides.get("rego", "ABC123")
    ov.make = overrides.get("make", "Toyota")
    ov.model = overrides.get("model", "Corolla")
    ov.body_type = overrides.get("body_type", "Sedan")
    ov.year = overrides.get("year", 2020)
    ov.colour = overrides.get("colour", "White")
    ov.wof_expiry = overrides.get("wof_expiry", date(2025, 6, 1))
    ov.registration_expiry = overrides.get("registration_expiry", date(2025, 12, 1))
    ov.odometer_last_recorded = overrides.get("odometer_last_recorded", 45000)
    return ov


def _make_global_vehicle(**overrides):
    """Build a mock GlobalVehicle ORM object."""
    gv = MagicMock()
    gv.id = overrides.get("id", uuid.uuid4())
    gv.rego = overrides.get("rego", "ABC123")
    gv.make = overrides.get("make", "Honda")
    gv.model = overrides.get("model", "Civic")
    gv.body_type = overrides.get("body_type", "Hatchback")
    gv.year = overrides.get("year", 2019)
    gv.colour = overrides.get("colour", "Blue")
    gv.wof_expiry = overrides.get("wof_expiry", date(2025, 8, 15))
    gv.registration_expiry = overrides.get("registration_expiry", date(2026, 1, 10))
    gv.odometer_last_recorded = overrides.get("odometer_last_recorded", 62000)
    return gv


def _make_scalar_result(value):
    """Create a mock DB execute result that returns value from scalar_one_or_none."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _make_carjam_data(**overrides):
    """Build a CarjamVehicleData instance."""
    defaults = {
        "rego": "XYZ789",
        "make": "Mazda",
        "model": "3",
        "year": 2021,
        "colour": "Red",
        "body_type": "Sedan",
        "fuel_type": "Petrol",
        "engine_size": "2.0L",
        "seats": 5,
        "wof_expiry": "2025-09-01",
        "rego_expiry": "2026-03-15",
        "odometer": 30000,
        "lookup_type": "basic",
        "vin": None,
        "chassis": None,
        "engine_no": None,
        "transmission": None,
        "country_of_origin": None,
        "number_of_owners": None,
        "vehicle_type": None,
        "reported_stolen": None,
        "power_kw": None,
        "tare_weight": None,
        "gross_vehicle_mass": None,
        "date_first_registered_nz": None,
        "plate_type": None,
        "submodel": None,
        "second_colour": None,
    }
    defaults.update(overrides)
    return CarjamVehicleData(**defaults)


# ---------------------------------------------------------------------------
# Tests: Org vehicle hit (Req 3.1)
# ---------------------------------------------------------------------------


class TestOrgVehicleHit:
    """When a vehicle is found in org_vehicles, return it with source='manual'."""

    @pytest.mark.asyncio
    async def test_returns_org_vehicle_data(self):
        """Org vehicle hit returns correct fields and source='manual'."""
        org_id = uuid.uuid4()
        org_vehicle = _make_org_vehicle(rego="ABC123", org_id=org_id)

        db = AsyncMock()
        redis = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(org_vehicle))

        result = await lookup_vehicle_for_kiosk(db, redis, rego="ABC123", org_id=org_id)

        assert result["id"] == str(org_vehicle.id)
        assert result["rego"] == "ABC123"
        assert result["make"] == "Toyota"
        assert result["model"] == "Corolla"
        assert result["body_type"] == "Sedan"
        assert result["year"] == 2020
        assert result["colour"] == "White"
        assert result["source"] == "manual"
        assert result["odometer"] == 45000

    @pytest.mark.asyncio
    async def test_does_not_query_global_or_carjam(self):
        """Org vehicle hit should only execute one DB query (org_vehicles)."""
        org_id = uuid.uuid4()
        org_vehicle = _make_org_vehicle(rego="ABC123", org_id=org_id)

        db = AsyncMock()
        redis = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(org_vehicle))

        await lookup_vehicle_for_kiosk(db, redis, rego="ABC123", org_id=org_id)

        # Only one DB query should have been made (org_vehicles)
        assert db.execute.call_count == 1


# ---------------------------------------------------------------------------
# Tests: Global vehicle hit (Req 3.2)
# ---------------------------------------------------------------------------


class TestGlobalVehicleHit:
    """When not in org_vehicles but found in global_vehicles, return with source='cache'."""

    @pytest.mark.asyncio
    async def test_returns_global_vehicle_data(self):
        """Global vehicle hit returns correct fields and source='cache'."""
        org_id = uuid.uuid4()
        global_vehicle = _make_global_vehicle(rego="DEF456")

        db = AsyncMock()
        redis = AsyncMock()
        # First call: org_vehicles miss, second call: global_vehicles hit
        db.execute = AsyncMock(side_effect=[
            _make_scalar_result(None),  # org_vehicles miss
            _make_scalar_result(global_vehicle),  # global_vehicles hit
        ])

        result = await lookup_vehicle_for_kiosk(db, redis, rego="DEF456", org_id=org_id)

        assert result["id"] == str(global_vehicle.id)
        assert result["rego"] == "DEF456"
        assert result["make"] == "Honda"
        assert result["model"] == "Civic"
        assert result["source"] == "cache"

    @pytest.mark.asyncio
    async def test_does_not_call_carjam(self):
        """Global vehicle hit should not call CarJam API."""
        org_id = uuid.uuid4()
        global_vehicle = _make_global_vehicle(rego="DEF456")

        db = AsyncMock()
        redis = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _make_scalar_result(None),
            _make_scalar_result(global_vehicle),
        ])

        with patch("app.modules.vehicles.service._load_carjam_client") as mock_client:
            await lookup_vehicle_for_kiosk(db, redis, rego="DEF456", org_id=org_id)
            mock_client.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: CarJam API success (Req 3.3, 3.4)
# ---------------------------------------------------------------------------


class TestCarjamSuccess:
    """When not in org or global, CarJam is called and result is cached."""

    @pytest.mark.asyncio
    async def test_returns_carjam_data_with_source_carjam(self):
        """CarJam success returns data with source='carjam'."""
        org_id = uuid.uuid4()
        carjam_data = _make_carjam_data(rego="XYZ789")

        # Mock the new GlobalVehicle that gets created
        new_gv = _make_global_vehicle(
            rego="XYZ789", make="Mazda", model="3", year=2021,
            colour="Red", body_type="Sedan",
            wof_expiry=date(2025, 9, 1),
            registration_expiry=date(2026, 3, 15),
            odometer_last_recorded=30000,
        )

        db = AsyncMock()
        redis = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _make_scalar_result(None),  # org_vehicles miss
            _make_scalar_result(None),  # global_vehicles miss
        ])
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()

        mock_client = AsyncMock()
        mock_client.lookup_vehicle = AsyncMock(return_value=carjam_data)

        with patch(
            "app.modules.vehicles.service._load_carjam_client",
            return_value=mock_client,
        ), patch(
            "app.modules.vehicles.service._carjam_data_to_global_vehicle",
            return_value=new_gv,
        ):
            result = await lookup_vehicle_for_kiosk(db, redis, rego="XYZ789", org_id=org_id)

        assert result["source"] == "carjam"
        assert result["rego"] == "XYZ789"
        assert result["make"] == "Mazda"
        assert result["model"] == "3"

    @pytest.mark.asyncio
    async def test_stores_result_in_global_vehicles(self):
        """CarJam success stores the vehicle in global_vehicles (cache)."""
        org_id = uuid.uuid4()
        carjam_data = _make_carjam_data(rego="XYZ789")
        new_gv = _make_global_vehicle(rego="XYZ789")

        db = AsyncMock()
        redis = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _make_scalar_result(None),
            _make_scalar_result(None),
        ])
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()

        mock_client = AsyncMock()
        mock_client.lookup_vehicle = AsyncMock(return_value=carjam_data)

        with patch(
            "app.modules.vehicles.service._load_carjam_client",
            return_value=mock_client,
        ), patch(
            "app.modules.vehicles.service._carjam_data_to_global_vehicle",
            return_value=new_gv,
        ):
            await lookup_vehicle_for_kiosk(db, redis, rego="XYZ789", org_id=org_id)

        # Verify the vehicle was added to the session and flushed
        db.add.assert_called_once_with(new_gv)
        db.flush.assert_awaited_once()
        db.refresh.assert_awaited_once_with(new_gv)


# ---------------------------------------------------------------------------
# Tests: CarJam not found (Req 3.5)
# ---------------------------------------------------------------------------


class TestCarjamNotFound:
    """When CarJam returns not found, raise HTTP 404."""

    @pytest.mark.asyncio
    async def test_raises_404(self):
        """CarJam not found raises HTTPException with status 404."""
        org_id = uuid.uuid4()

        db = AsyncMock()
        redis = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _make_scalar_result(None),
            _make_scalar_result(None),
        ])

        mock_client = AsyncMock()
        mock_client.lookup_vehicle = AsyncMock(
            side_effect=CarjamNotFoundError("GHI321")
        )

        with patch(
            "app.modules.vehicles.service._load_carjam_client",
            return_value=mock_client,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await lookup_vehicle_for_kiosk(db, redis, rego="GHI321", org_id=org_id)

        assert exc_info.value.status_code == 404
        assert "GHI321" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Tests: CarJam rate limit (error handling)
# ---------------------------------------------------------------------------


class TestCarjamRateLimit:
    """When CarJam rate limit is exceeded, raise HTTP 429."""

    @pytest.mark.asyncio
    async def test_raises_429_with_retry_after(self):
        """CarJam rate limit raises HTTPException with status 429."""
        org_id = uuid.uuid4()

        db = AsyncMock()
        redis = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _make_scalar_result(None),
            _make_scalar_result(None),
        ])

        mock_client = AsyncMock()
        mock_client.lookup_vehicle = AsyncMock(
            side_effect=CarjamRateLimitError(retry_after=30)
        )

        with patch(
            "app.modules.vehicles.service._load_carjam_client",
            return_value=mock_client,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await lookup_vehicle_for_kiosk(db, redis, rego="JKL654", org_id=org_id)

        assert exc_info.value.status_code == 429
        assert exc_info.value.headers["Retry-After"] == "30"


# ---------------------------------------------------------------------------
# Tests: CarJam generic error
# ---------------------------------------------------------------------------


class TestCarjamGenericError:
    """When CarJam returns a generic error, raise HTTP 502."""

    @pytest.mark.asyncio
    async def test_raises_502(self):
        """CarJam generic error raises HTTPException with status 502."""
        org_id = uuid.uuid4()

        db = AsyncMock()
        redis = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _make_scalar_result(None),
            _make_scalar_result(None),
        ])

        mock_client = AsyncMock()
        mock_client.lookup_vehicle = AsyncMock(
            side_effect=CarjamError("Connection timeout")
        )

        with patch(
            "app.modules.vehicles.service._load_carjam_client",
            return_value=mock_client,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await lookup_vehicle_for_kiosk(db, redis, rego="MNO987", org_id=org_id)

        assert exc_info.value.status_code == 502
        assert "service error" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# Tests: Rego normalisation
# ---------------------------------------------------------------------------


class TestRegoNormalisation:
    """Rego input is normalised (uppercase, stripped) before lookup."""

    @pytest.mark.asyncio
    async def test_lowercase_rego_is_uppercased(self):
        """Lowercase rego is converted to uppercase for lookup."""
        org_id = uuid.uuid4()
        org_vehicle = _make_org_vehicle(rego="ABC123")

        db = AsyncMock()
        redis = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(org_vehicle))

        result = await lookup_vehicle_for_kiosk(db, redis, rego="abc123", org_id=org_id)

        assert result["rego"] == "ABC123"

    @pytest.mark.asyncio
    async def test_whitespace_is_stripped(self):
        """Leading/trailing whitespace is stripped from rego."""
        org_id = uuid.uuid4()
        org_vehicle = _make_org_vehicle(rego="ABC123")

        db = AsyncMock()
        redis = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(org_vehicle))

        result = await lookup_vehicle_for_kiosk(db, redis, rego="  abc123  ", org_id=org_id)

        assert result["rego"] == "ABC123"


# ---------------------------------------------------------------------------
# Tests: Date serialisation
# ---------------------------------------------------------------------------


class TestDateSerialisation:
    """Date fields are serialised as ISO strings or None."""

    @pytest.mark.asyncio
    async def test_dates_serialised_as_iso(self):
        """WOF and rego expiry dates are returned as ISO strings."""
        org_id = uuid.uuid4()
        org_vehicle = _make_org_vehicle(
            rego="ABC123",
            wof_expiry=date(2025, 6, 1),
            registration_expiry=date(2025, 12, 1),
        )

        db = AsyncMock()
        redis = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(org_vehicle))

        result = await lookup_vehicle_for_kiosk(db, redis, rego="ABC123", org_id=org_id)

        assert result["wof_expiry"] == "2025-06-01"
        assert result["rego_expiry"] == "2025-12-01"

    @pytest.mark.asyncio
    async def test_null_dates_returned_as_none(self):
        """Null date fields are returned as None."""
        org_id = uuid.uuid4()
        org_vehicle = _make_org_vehicle(
            rego="ABC123",
            wof_expiry=None,
            registration_expiry=None,
        )

        db = AsyncMock()
        redis = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(org_vehicle))

        result = await lookup_vehicle_for_kiosk(db, redis, rego="ABC123", org_id=org_id)

        assert result["wof_expiry"] is None
        assert result["rego_expiry"] is None
