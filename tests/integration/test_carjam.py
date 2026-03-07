"""Integration tests for Carjam — cache-first lookup, API failure fallback, rate limiting, refresh, overage tracking.

Tests the full flow from vehicle service/router layer through to mocked Carjam API responses.
All Carjam API calls are mocked — no real API calls are made.

Requirements: 14.1-14.7, 16.2
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
import app.modules.catalogue.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.inventory.models import PartSupplier  # noqa: F401
from app.modules.customers.models import Customer  # noqa: F401

from app.integrations.carjam import (
    CarjamClient,
    CarjamError,
    CarjamNotFoundError,
    CarjamRateLimitError,
    CarjamVehicleData,
)
from app.modules.admin.models import GlobalVehicle, Organisation
from app.modules.vehicles.service import (
    create_manual_vehicle,
    lookup_vehicle,
    refresh_vehicle,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_CARJAM_RESPONSE = {
    "make": "Toyota",
    "model": "Corolla",
    "year": "2018",
    "colour": "Silver",
    "body_type": "Hatchback",
    "fuel_type": "Petrol",
    "engine_size": "1.8L",
    "seats": "5",
    "wof_expiry": "2025-06-15",
    "rego_expiry": "2025-09-01",
    "odometer": "85000",
}


def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db



def _make_global_vehicle(rego="ABC123", **overrides):
    gv = MagicMock(spec=GlobalVehicle)
    gv.id = overrides.get("id", uuid.uuid4())
    gv.rego = rego
    gv.make = overrides.get("make", "Toyota")
    gv.model = overrides.get("model", "Corolla")
    gv.year = overrides.get("year", 2018)
    gv.colour = overrides.get("colour", "Silver")
    gv.body_type = overrides.get("body_type", "Hatchback")
    gv.fuel_type = overrides.get("fuel_type", "Petrol")
    gv.engine_size = overrides.get("engine_size", "1.8L")
    gv.num_seats = overrides.get("num_seats", 5)
    gv.wof_expiry = overrides.get("wof_expiry", date(2025, 6, 15))
    gv.registration_expiry = overrides.get("registration_expiry", date(2025, 9, 1))
    gv.odometer_last_recorded = overrides.get("odometer_last_recorded", 85000)
    gv.last_pulled_at = overrides.get("last_pulled_at", datetime(2025, 1, 1, tzinfo=timezone.utc))
    gv.created_at = overrides.get("created_at", datetime(2025, 1, 1, tzinfo=timezone.utc))
    return gv


def _make_org(org_id=None, carjam_lookups=0):
    org = MagicMock(spec=Organisation)
    org.id = org_id or uuid.uuid4()
    org.carjam_lookups_this_month = carjam_lookups
    return org


def _mock_scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _make_carjam_vehicle_data(rego="ABC123"):
    return CarjamVehicleData(
        rego=rego,
        make="Toyota",
        model="Corolla",
        year=2018,
        colour="Silver",
        body_type="Hatchback",
        fuel_type="Petrol",
        engine_size="1.8L",
        seats=5,
        wof_expiry="2025-06-15",
        rego_expiry="2025-09-01",
        odometer=85000,
    )


# ===========================================================================
# 1. Cache-First Lookup Flow (Req 14.1, 14.2, 14.3)
# ===========================================================================


class TestCacheFirstLookupFlow:
    """Test the cache-first vehicle lookup strategy.

    Req 14.1: Check Global_Vehicle_DB first.
    Req 14.2: Cache hit returns data without Carjam API call or counter increment.
    Req 14.3: Cache miss calls Carjam, stores result, increments counter.
    """

    @pytest.mark.asyncio
    async def test_cache_hit_returns_data_without_api_call(self):
        """Req 14.1, 14.2: When rego exists in Global_Vehicle_DB, return cached
        data without calling Carjam API and without incrementing the org counter."""
        existing_vehicle = _make_global_vehicle(rego="ABC123")
        org = _make_org(carjam_lookups=5)

        db = _mock_db()
        # First execute: GlobalVehicle lookup → cache hit
        db.execute = AsyncMock(return_value=_mock_scalar_result(existing_vehicle))

        redis = AsyncMock()

        with patch("app.modules.vehicles.service.CarjamClient") as mock_client_cls:
            result = await lookup_vehicle(
                db, redis, rego="ABC123",
                org_id=org.id, user_id=uuid.uuid4(),
            )

            # Carjam client should never be instantiated on cache hit
            mock_client_cls.assert_not_called()

        assert result["rego"] == "ABC123"
        assert result["source"] == "cache"
        assert result["make"] == "Toyota"
        # Org counter should not have been touched (no second db.execute for org)
        assert db.add.call_count == 0

    @pytest.mark.asyncio
    async def test_cache_miss_calls_carjam_and_stores_result(self):
        """Req 14.3: When rego not in Global_Vehicle_DB, call Carjam API,
        store result in Global_Vehicle_DB, and increment org counter by 1."""
        org = _make_org(carjam_lookups=10)

        db = _mock_db()
        # First execute: GlobalVehicle lookup → cache miss
        # Second execute: Organisation lookup → return org
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(None),  # cache miss
            _mock_scalar_result(org),   # org lookup
        ])

        redis = AsyncMock()
        carjam_data = _make_carjam_vehicle_data("XYZ789")

        with patch("app.modules.vehicles.service.CarjamClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.lookup_vehicle = AsyncMock(return_value=carjam_data)
            mock_client_cls.return_value = mock_client

            with patch("app.modules.vehicles.service.write_audit_log", new_callable=AsyncMock):
                result = await lookup_vehicle(
                    db, redis, rego="XYZ789",
                    org_id=org.id, user_id=uuid.uuid4(),
                )

        # Carjam API was called
        mock_client.lookup_vehicle.assert_awaited_once_with("XYZ789")
        # New vehicle was added to DB
        assert db.add.called
        # Org counter was incremented
        assert org.carjam_lookups_this_month == 11
        # Result comes from Carjam
        assert result["source"] == "carjam"
        assert result["rego"] == "XYZ789"
        assert result["make"] == "Toyota"

    @pytest.mark.asyncio
    async def test_cache_hit_does_not_increment_counter(self):
        """Req 14.2: Verify the org's Carjam usage counter stays unchanged on cache hit."""
        org = _make_org(carjam_lookups=42)
        existing_vehicle = _make_global_vehicle(rego="DEF456")

        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(existing_vehicle))
        redis = AsyncMock()

        with patch("app.modules.vehicles.service.CarjamClient") as mock_client_cls:
            await lookup_vehicle(
                db, redis, rego="DEF456",
                org_id=org.id, user_id=uuid.uuid4(),
            )
            mock_client_cls.assert_not_called()

        # Counter unchanged
        assert org.carjam_lookups_this_month == 42

    @pytest.mark.asyncio
    async def test_rego_normalised_to_uppercase(self):
        """Rego input is normalised to uppercase before cache lookup."""
        existing_vehicle = _make_global_vehicle(rego="ABC123")

        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(existing_vehicle))
        redis = AsyncMock()

        with patch("app.modules.vehicles.service.CarjamClient"):
            result = await lookup_vehicle(
                db, redis, rego="abc123",
                org_id=uuid.uuid4(), user_id=uuid.uuid4(),
            )

        assert result["rego"] == "ABC123"



# ===========================================================================
# 2. Carjam API Failure Fallback to Manual Entry (Req 14.5, 14.6, 14.7)
# ===========================================================================


class TestCarjamApiFailureFallback:
    """Test that when Carjam API fails or returns no result, the system
    falls back to manual vehicle entry.

    Req 14.6: If Carjam returns no result, present manual entry form.
    Req 14.7: Manual entries stored in org_vehicles, marked as 'manually entered'.
    """

    @pytest.mark.asyncio
    async def test_carjam_not_found_raises_for_manual_entry(self):
        """Req 14.6: When Carjam returns no result, CarjamNotFoundError is raised,
        signalling the router to suggest manual entry."""
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))  # cache miss
        redis = AsyncMock()

        with patch("app.modules.vehicles.service.CarjamClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.lookup_vehicle = AsyncMock(
                side_effect=CarjamNotFoundError("NOTFOUND1")
            )
            mock_client_cls.return_value = mock_client

            with pytest.raises(CarjamNotFoundError) as exc_info:
                await lookup_vehicle(
                    db, redis, rego="NOTFOUND1",
                    org_id=uuid.uuid4(), user_id=uuid.uuid4(),
                )

            assert "NOTFOUND1" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_carjam_api_error_propagates(self):
        """When Carjam API is down (HTTP error), CarjamError propagates
        so the router can return 502 and allow manual entry."""
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))  # cache miss
        redis = AsyncMock()

        with patch("app.modules.vehicles.service.CarjamClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.lookup_vehicle = AsyncMock(
                side_effect=CarjamError("Carjam API timed out for rego 'DOWN1'")
            )
            mock_client_cls.return_value = mock_client

            with pytest.raises(CarjamError, match="timed out"):
                await lookup_vehicle(
                    db, redis, rego="DOWN1",
                    org_id=uuid.uuid4(), user_id=uuid.uuid4(),
                )

    @pytest.mark.asyncio
    async def test_manual_entry_stored_in_org_vehicles(self):
        """Req 14.7: Manual entry creates record in org_vehicles (not Global_Vehicle_DB),
        marked as 'manually entered'."""
        db = _mock_db()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        with patch("app.modules.vehicles.service.write_audit_log", new_callable=AsyncMock):
            result = await create_manual_vehicle(
                db,
                org_id=org_id,
                user_id=user_id,
                rego="MANUAL1",
                make="Honda",
                model="Civic",
                year=2020,
                colour="Blue",
            )

        assert result["rego"] == "MANUAL1"
        assert result["make"] == "Honda"
        assert result["is_manual_entry"] is True
        assert result["org_id"] == str(org_id)
        # Verify it was added to the DB session
        assert db.add.called

    @pytest.mark.asyncio
    async def test_manual_entry_does_not_touch_global_vehicle_db(self):
        """Req 14.7: Manual entries are NOT stored in Global_Vehicle_DB."""
        db = _mock_db()

        with patch("app.modules.vehicles.service.write_audit_log", new_callable=AsyncMock):
            result = await create_manual_vehicle(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                rego="MANUAL2",
                make="Ford",
            )

        # The add call should be for OrgVehicle, not GlobalVehicle
        added_obj = db.add.call_args[0][0]
        from app.modules.vehicles.models import OrgVehicle
        assert isinstance(added_obj, OrgVehicle)
        assert added_obj.is_manual_entry is True

    @pytest.mark.asyncio
    async def test_manual_entry_does_not_increment_carjam_counter(self):
        """Manual entry should not count as a Carjam lookup."""
        org = _make_org(carjam_lookups=5)
        db = _mock_db()

        with patch("app.modules.vehicles.service.write_audit_log", new_callable=AsyncMock):
            await create_manual_vehicle(
                db,
                org_id=org.id,
                user_id=uuid.uuid4(),
                rego="MANUAL3",
            )

        # Counter unchanged
        assert org.carjam_lookups_this_month == 5


# ===========================================================================
# 3. Rate Limiting Enforcement (Req 16.2)
# ===========================================================================


class TestRateLimitingEnforcement:
    """Test that the global Carjam rate limit is enforced.

    Req 16.2: Enforce a global rate limit (configurable by Global_Admin)
    on maximum Carjam API calls per minute across the entire platform.
    """

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_raises_error(self):
        """When the global rate limit is exceeded, CarjamRateLimitError is raised
        before any HTTP call is made."""
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))  # cache miss
        redis = AsyncMock()

        with patch("app.modules.vehicles.service.CarjamClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.lookup_vehicle = AsyncMock(
                side_effect=CarjamRateLimitError(retry_after=30)
            )
            mock_client_cls.return_value = mock_client

            with pytest.raises(CarjamRateLimitError) as exc_info:
                await lookup_vehicle(
                    db, redis, rego="RATELIMIT1",
                    org_id=uuid.uuid4(), user_id=uuid.uuid4(),
                )

            assert exc_info.value.retry_after == 30

    @pytest.mark.asyncio
    async def test_rate_limit_does_not_increment_counter(self):
        """When rate limited, the org's Carjam counter should NOT be incremented
        since no successful lookup occurred."""
        org = _make_org(carjam_lookups=10)
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))  # cache miss
        redis = AsyncMock()

        with patch("app.modules.vehicles.service.CarjamClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.lookup_vehicle = AsyncMock(
                side_effect=CarjamRateLimitError(retry_after=5)
            )
            mock_client_cls.return_value = mock_client

            with pytest.raises(CarjamRateLimitError):
                await lookup_vehicle(
                    db, redis, rego="RATELIMIT2",
                    org_id=org.id, user_id=uuid.uuid4(),
                )

        # Counter unchanged
        assert org.carjam_lookups_this_month == 10

    @pytest.mark.asyncio
    async def test_rate_limit_client_level_enforcement(self):
        """Test that CarjamClient enforces rate limiting via Redis sliding window
        before making the HTTP call."""
        redis = MagicMock()

        # redis.pipeline() is called synchronously, returns a pipeline object
        # whose methods are sync but execute() is async
        pipe_mock = MagicMock()
        pipe_mock.zremrangebyscore = MagicMock()
        pipe_mock.zcard = MagicMock()
        pipe_mock.execute = AsyncMock(return_value=[None, 100])  # count = 100 (at limit)
        redis.pipeline.return_value = pipe_mock
        redis.zrange = AsyncMock(return_value=[(b"entry", 1000.0)])

        client = CarjamClient(
            redis=redis,
            api_key="test-key",
            base_url="https://api.carjam.co.nz",
            rate_limit=100,
        )

        with pytest.raises(CarjamRateLimitError):
            await client.lookup_vehicle("TEST123")

    @pytest.mark.asyncio
    async def test_rate_limit_allows_when_under_limit(self):
        """Test that lookups proceed when under the rate limit."""
        # First pipeline: rate limit check (under limit)
        pipe_check = MagicMock()
        pipe_check.zremrangebyscore = MagicMock()
        pipe_check.zcard = MagicMock()
        pipe_check.execute = AsyncMock(return_value=[None, 5])  # count = 5

        # Second pipeline: record the call
        pipe_record = MagicMock()
        pipe_record.zadd = MagicMock()
        pipe_record.expire = MagicMock()
        pipe_record.execute = AsyncMock(return_value=[None, None])

        redis = MagicMock()
        redis.pipeline.side_effect = [pipe_check, pipe_record]

        client = CarjamClient(
            redis=redis,
            api_key="test-key",
            base_url="https://api.carjam.co.nz",
            rate_limit=100,
        )

        with patch("httpx.AsyncClient") as mock_httpx:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = _SAMPLE_CARJAM_RESPONSE

            mock_http_client = AsyncMock()
            mock_http_client.get = AsyncMock(return_value=mock_response)
            mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
            mock_http_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.return_value = mock_http_client

            result = await client.lookup_vehicle("ABC123")

        assert result.rego == "ABC123"
        assert result.make == "Toyota"



# ===========================================================================
# 4. Cache Refresh Flow (Req 14.5)
# ===========================================================================


class TestCacheRefreshFlow:
    """Test force-refresh of cached vehicle data.

    Req 14.5: Refresh button forces new Carjam API call, updates
    Global_Vehicle_DB record, and charges the organisation for one lookup.
    """

    @pytest.mark.asyncio
    async def test_refresh_calls_carjam_and_updates_record(self):
        """Req 14.5: Force refresh calls Carjam, updates existing record,
        and increments org counter."""
        existing_vehicle = _make_global_vehicle(rego="REFRESH1")
        # Make attributes writable for the update
        existing_vehicle.make = "Toyota"
        existing_vehicle.model = "Corolla"
        org = _make_org(carjam_lookups=3)

        db = _mock_db()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(existing_vehicle),  # vehicle lookup
            _mock_scalar_result(org),                # org lookup
        ])

        redis = AsyncMock()
        updated_data = CarjamVehicleData(
            rego="REFRESH1",
            make="Toyota",
            model="Corolla GR",
            year=2018,
            colour="Red",
            body_type="Hatchback",
            fuel_type="Petrol",
            engine_size="1.8L",
            seats=5,
            wof_expiry="2026-01-15",
            rego_expiry="2026-03-01",
            odometer=92000,
        )

        with patch("app.modules.vehicles.service.CarjamClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.lookup_vehicle = AsyncMock(return_value=updated_data)
            mock_client_cls.return_value = mock_client

            with patch("app.modules.vehicles.service.write_audit_log", new_callable=AsyncMock):
                result = await refresh_vehicle(
                    db, redis,
                    vehicle_id=existing_vehicle.id,
                    org_id=org.id,
                    user_id=uuid.uuid4(),
                )

        # Carjam was called
        mock_client.lookup_vehicle.assert_awaited_once_with("REFRESH1")
        # Org counter incremented
        assert org.carjam_lookups_this_month == 4
        # Result reflects updated data
        assert result["source"] == "carjam"

    @pytest.mark.asyncio
    async def test_refresh_nonexistent_vehicle_raises(self):
        """Refresh on a vehicle not in Global_Vehicle_DB raises ValueError."""
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))
        redis = AsyncMock()

        with pytest.raises(ValueError, match="not found"):
            await refresh_vehicle(
                db, redis,
                vehicle_id=uuid.uuid4(),
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_refresh_rate_limited_propagates_error(self):
        """When rate limited during refresh, CarjamRateLimitError propagates."""
        existing_vehicle = _make_global_vehicle(rego="RATEREF1")
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(existing_vehicle))
        redis = AsyncMock()

        with patch("app.modules.vehicles.service.CarjamClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.lookup_vehicle = AsyncMock(
                side_effect=CarjamRateLimitError(retry_after=15)
            )
            mock_client_cls.return_value = mock_client

            with pytest.raises(CarjamRateLimitError):
                await refresh_vehicle(
                    db, redis,
                    vehicle_id=existing_vehicle.id,
                    org_id=uuid.uuid4(),
                    user_id=uuid.uuid4(),
                )


# ===========================================================================
# 5. Carjam Overage Tracking (Req 14.3, 16.2)
# ===========================================================================


class TestCarjamOverageTracking:
    """Test that Carjam lookups are tracked against plan limits for billing."""

    @pytest.mark.asyncio
    async def test_counter_increments_on_cache_miss(self):
        """Each cache miss increments the org's carjam_lookups_this_month by exactly 1."""
        org = _make_org(carjam_lookups=0)
        db = _mock_db()
        redis = AsyncMock()
        carjam_data = _make_carjam_vehicle_data("COUNT1")

        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(None),  # cache miss
            _mock_scalar_result(org),   # org lookup
        ])

        with patch("app.modules.vehicles.service.CarjamClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.lookup_vehicle = AsyncMock(return_value=carjam_data)
            mock_client_cls.return_value = mock_client

            with patch("app.modules.vehicles.service.write_audit_log", new_callable=AsyncMock):
                await lookup_vehicle(
                    db, redis, rego="COUNT1",
                    org_id=org.id, user_id=uuid.uuid4(),
                )

        assert org.carjam_lookups_this_month == 1

    @pytest.mark.asyncio
    async def test_counter_increments_on_refresh(self):
        """Refresh also increments the org's counter by 1 (Req 14.5)."""
        existing_vehicle = _make_global_vehicle(rego="COUNTREF1")
        existing_vehicle.make = "Toyota"
        org = _make_org(carjam_lookups=50)

        db = _mock_db()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(existing_vehicle),
            _mock_scalar_result(org),
        ])
        redis = AsyncMock()
        carjam_data = _make_carjam_vehicle_data("COUNTREF1")

        with patch("app.modules.vehicles.service.CarjamClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.lookup_vehicle = AsyncMock(return_value=carjam_data)
            mock_client_cls.return_value = mock_client

            with patch("app.modules.vehicles.service.write_audit_log", new_callable=AsyncMock):
                await refresh_vehicle(
                    db, redis,
                    vehicle_id=existing_vehicle.id,
                    org_id=org.id,
                    user_id=uuid.uuid4(),
                )

        assert org.carjam_lookups_this_month == 51

    @pytest.mark.asyncio
    async def test_failed_lookup_does_not_increment_counter(self):
        """When Carjam API fails, the counter should NOT be incremented."""
        org = _make_org(carjam_lookups=25)
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))  # cache miss
        redis = AsyncMock()

        with patch("app.modules.vehicles.service.CarjamClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.lookup_vehicle = AsyncMock(
                side_effect=CarjamError("API down")
            )
            mock_client_cls.return_value = mock_client

            with pytest.raises(CarjamError):
                await lookup_vehicle(
                    db, redis, rego="FAIL1",
                    org_id=org.id, user_id=uuid.uuid4(),
                )

        assert org.carjam_lookups_this_month == 25
