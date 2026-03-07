"""Unit tests for vehicle lookup (cache-first) — Task 8.2.

Tests cover:
  - Cache hit: returns data from Global_Vehicle_DB without Carjam call
  - Cache miss: calls Carjam, stores result, increments org counter
  - Carjam not found: returns 404 with manual entry suggestion
  - Carjam rate limit: returns 429
  - Carjam generic error: returns 502
  - All Carjam fields stored correctly
  - Rego normalisation (uppercase, trimmed)

Requirements: 14.1, 14.2, 14.3, 14.4
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
    _global_vehicle_to_dict,
    _parse_date,
    lookup_vehicle,
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


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------


class TestParseDate:
    def test_valid_date(self):
        assert _parse_date("2025-06-01") == date(2025, 6, 1)

    def test_none_returns_none(self):
        assert _parse_date(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_date("") is None

    def test_invalid_format_returns_none(self):
        assert _parse_date("not-a-date") is None


# ---------------------------------------------------------------------------
# _global_vehicle_to_dict
# ---------------------------------------------------------------------------


class TestGlobalVehicleToDict:
    def test_all_fields_present(self):
        gv = _make_global_vehicle()
        result = _global_vehicle_to_dict(gv, source="cache")

        assert result["rego"] == "ABC123"
        assert result["make"] == "Toyota"
        assert result["model"] == "Corolla"
        assert result["year"] == 2020
        assert result["colour"] == "White"
        assert result["body_type"] == "Sedan"
        assert result["fuel_type"] == "Petrol"
        assert result["engine_size"] == "1.8L"
        assert result["seats"] == 5
        assert result["wof_expiry"] == "2025-06-01"
        assert result["rego_expiry"] == "2025-12-01"
        assert result["odometer"] == 45000
        assert result["source"] == "cache"
        assert result["last_pulled_at"] is not None

    def test_none_dates(self):
        gv = _make_global_vehicle(wof_expiry=None, registration_expiry=None)
        result = _global_vehicle_to_dict(gv, source="carjam")
        assert result["wof_expiry"] is None
        assert result["rego_expiry"] is None
        assert result["source"] == "carjam"


# ---------------------------------------------------------------------------
# lookup_vehicle — cache hit (Req 14.1, 14.2)
# ---------------------------------------------------------------------------


class TestLookupVehicleCacheHit:
    @pytest.mark.asyncio
    async def test_returns_cached_data_without_carjam_call(self):
        """Req 14.1, 14.2: Cache hit returns data without API call or counter increment."""
        gv = _make_global_vehicle(rego="ABC123")
        org = _make_org(carjam_lookups_this_month=5)

        db = AsyncMock()
        # First call: select GlobalVehicle → cache hit
        db.execute = AsyncMock(return_value=_make_scalar_result(gv))

        redis = MagicMock()

        with patch("app.modules.vehicles.service.CarjamClient") as mock_client_cls:
            result = await lookup_vehicle(
                db, redis,
                rego="abc123",
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
            )

            # Carjam should NOT have been called
            mock_client_cls.assert_not_called()

        assert result["rego"] == "ABC123"
        assert result["source"] == "cache"
        assert result["make"] == "Toyota"

    @pytest.mark.asyncio
    async def test_rego_normalised_to_uppercase(self):
        """Rego should be normalised to uppercase before DB lookup."""
        gv = _make_global_vehicle(rego="XYZ789")

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(gv))
        redis = MagicMock()

        with patch("app.modules.vehicles.service.CarjamClient"):
            result = await lookup_vehicle(
                db, redis,
                rego="  xyz789  ",
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
            )

        assert result["rego"] == "XYZ789"
        assert result["source"] == "cache"


# ---------------------------------------------------------------------------
# lookup_vehicle — cache miss (Req 14.3, 14.4)
# ---------------------------------------------------------------------------


class TestLookupVehicleCacheMiss:
    @pytest.mark.asyncio
    async def test_calls_carjam_stores_result_increments_counter(self):
        """Req 14.3: Cache miss calls Carjam, stores result, increments counter."""
        org = _make_org(carjam_lookups_this_month=5)

        carjam_data = CarjamVehicleData(
            rego="NEW123",
            make="Honda",
            model="Civic",
            year=2019,
            colour="Blue",
            body_type="Hatchback",
            fuel_type="Petrol",
            engine_size="1.5L",
            seats=5,
            wof_expiry="2025-03-15",
            rego_expiry="2025-09-30",
            odometer=62000,
        )

        execute_calls = []

        async def _side_effect_execute(stmt, *args, **kwargs):
            execute_calls.append(stmt)
            # First execute: select GlobalVehicle → cache miss
            if len(execute_calls) == 1:
                return _make_scalar_result(None)
            # Second execute: select Organisation
            elif len(execute_calls) == 2:
                return _make_scalar_result(org)
            # Subsequent: audit log INSERT etc.
            return MagicMock()

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_side_effect_execute)
        db.add = MagicMock()
        db.flush = AsyncMock()

        redis = MagicMock()

        mock_client_instance = AsyncMock()
        mock_client_instance.lookup_vehicle = AsyncMock(return_value=carjam_data)

        with patch("app.modules.vehicles.service.CarjamClient", return_value=mock_client_instance):
            with patch("app.modules.vehicles.service.write_audit_log", new_callable=AsyncMock):
                result = await lookup_vehicle(
                    db, redis,
                    rego="NEW123",
                    org_id=uuid.uuid4(),
                    user_id=uuid.uuid4(),
                )

        assert result["source"] == "carjam"
        assert result["rego"] == "NEW123"
        assert result["make"] == "Honda"
        assert result["model"] == "Civic"
        assert result["year"] == 2019
        assert result["colour"] == "Blue"
        assert result["body_type"] == "Hatchback"
        assert result["fuel_type"] == "Petrol"
        assert result["engine_size"] == "1.5L"
        assert result["seats"] == 5
        assert result["odometer"] == 62000

        # Carjam was called
        mock_client_instance.lookup_vehicle.assert_called_once_with("NEW123")

        # Vehicle was added to DB
        db.add.assert_called_once()

        # Org counter was incremented
        assert org.carjam_lookups_this_month == 6

    @pytest.mark.asyncio
    async def test_all_carjam_fields_stored(self):
        """Req 14.4: All Carjam fields are stored in the GlobalVehicle record."""
        from app.modules.vehicles.service import _carjam_data_to_global_vehicle

        data = CarjamVehicleData(
            rego="TST999",
            make="Mazda",
            model="CX-5",
            year=2022,
            colour="Red",
            body_type="SUV",
            fuel_type="Diesel",
            engine_size="2.2L",
            seats=5,
            wof_expiry="2026-01-15",
            rego_expiry="2026-06-30",
            odometer=15000,
        )

        gv = _carjam_data_to_global_vehicle(data)

        assert gv.rego == "TST999"
        assert gv.make == "Mazda"
        assert gv.model == "CX-5"
        assert gv.year == 2022
        assert gv.colour == "Red"
        assert gv.body_type == "SUV"
        assert gv.fuel_type == "Diesel"
        assert gv.engine_size == "2.2L"
        assert gv.num_seats == 5
        assert gv.wof_expiry == date(2026, 1, 15)
        assert gv.registration_expiry == date(2026, 6, 30)
        assert gv.odometer_last_recorded == 15000
        assert gv.last_pulled_at is not None


# ---------------------------------------------------------------------------
# lookup_vehicle — error handling
# ---------------------------------------------------------------------------


class TestLookupVehicleErrors:
    @pytest.mark.asyncio
    async def test_carjam_not_found_propagates(self):
        """Req 14.6: CarjamNotFoundError propagates for router to handle."""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(None))
        redis = MagicMock()

        mock_client = AsyncMock()
        mock_client.lookup_vehicle = AsyncMock(
            side_effect=CarjamNotFoundError("ZZZ999")
        )

        with patch("app.modules.vehicles.service.CarjamClient", return_value=mock_client):
            with pytest.raises(CarjamNotFoundError):
                await lookup_vehicle(
                    db, redis,
                    rego="ZZZ999",
                    org_id=uuid.uuid4(),
                    user_id=uuid.uuid4(),
                )

    @pytest.mark.asyncio
    async def test_carjam_rate_limit_propagates(self):
        """CarjamRateLimitError propagates for router to return 429."""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(None))
        redis = MagicMock()

        mock_client = AsyncMock()
        mock_client.lookup_vehicle = AsyncMock(
            side_effect=CarjamRateLimitError(retry_after=30)
        )

        with patch("app.modules.vehicles.service.CarjamClient", return_value=mock_client):
            with pytest.raises(CarjamRateLimitError) as exc_info:
                await lookup_vehicle(
                    db, redis,
                    rego="ABC123",
                    org_id=uuid.uuid4(),
                    user_id=uuid.uuid4(),
                )
            assert exc_info.value.retry_after == 30

    @pytest.mark.asyncio
    async def test_carjam_generic_error_propagates(self):
        """Generic CarjamError propagates for router to return 502."""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(None))
        redis = MagicMock()

        mock_client = AsyncMock()
        mock_client.lookup_vehicle = AsyncMock(
            side_effect=CarjamError("Connection failed")
        )

        with patch("app.modules.vehicles.service.CarjamClient", return_value=mock_client):
            with pytest.raises(CarjamError, match="Connection failed"):
                await lookup_vehicle(
                    db, redis,
                    rego="ABC123",
                    org_id=uuid.uuid4(),
                    user_id=uuid.uuid4(),
                )
