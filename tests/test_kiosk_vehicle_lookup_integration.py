"""Integration tests for POST /kiosk/vehicle-lookup endpoint.

Tests cover the full request/response cycle through the router:
  - Full cascade: org_vehicles hit returns source="manual"
  - Full cascade: global_vehicles hit returns source="cache"
  - Full cascade: CarJam hit returns source="carjam" (mocked)
  - 404 when vehicle not found anywhere
  - Rate limiting: 31st request within 60s returns 429
  - Role enforcement: non-kiosk role gets 403

Requirements: 3.1, 3.2, 3.3, 3.5, 7.1, 7.4
"""

from __future__ import annotations

import time
import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from redis.asyncio import Redis

# Ensure SQLAlchemy relationship models are loaded
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401

from app.integrations.carjam import (
    CarjamError,
    CarjamNotFoundError,
    CarjamRateLimitError,
    CarjamVehicleData,
)
from app.modules.kiosk.router import (
    _check_kiosk_rate_limit,
    _KIOSK_RATE_LIMIT,
    vehicle_lookup,
)
from app.modules.kiosk.schemas import KioskVehicleLookupRequest
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
    gv.rego = overrides.get("rego", "DEF456")
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


def _make_mock_request(*, user_id: str, org_id: str, role: str = "kiosk"):
    """Create a mock FastAPI Request with state attributes for auth context."""
    request = MagicMock()
    request.state.user_id = user_id
    request.state.org_id = org_id
    request.state.role = role
    request.state.client_ip = "10.0.0.1"
    return request


def _make_mock_redis_under_limit() -> AsyncMock:
    """Create a mock Redis that simulates being under the rate limit."""
    redis = AsyncMock(spec=Redis)

    pipe1 = AsyncMock()
    pipe1.zremrangebyscore = MagicMock(return_value=pipe1)
    pipe1.zcard = MagicMock(return_value=pipe1)
    pipe1.execute = AsyncMock(return_value=[0, 5])  # 5 requests in window

    pipe2 = AsyncMock()
    pipe2.zadd = MagicMock(return_value=pipe2)
    pipe2.expire = MagicMock(return_value=pipe2)
    pipe2.execute = AsyncMock(return_value=[1, True])

    redis.pipeline = MagicMock(side_effect=[pipe1, pipe2])
    return redis


def _make_mock_redis_at_limit() -> AsyncMock:
    """Create a mock Redis that simulates being at the rate limit (30 requests)."""
    redis = AsyncMock(spec=Redis)

    pipe1 = AsyncMock()
    pipe1.zremrangebyscore = MagicMock(return_value=pipe1)
    pipe1.zcard = MagicMock(return_value=pipe1)
    pipe1.execute = AsyncMock(return_value=[0, _KIOSK_RATE_LIMIT])  # 30 in window

    redis.pipeline = MagicMock(return_value=pipe1)

    now = time.time()
    redis.zrange = AsyncMock(return_value=[(b"oldest", now - 50)])

    return redis


# ---------------------------------------------------------------------------
# Integration Tests: Full Cascade
# ---------------------------------------------------------------------------


class TestVehicleLookupCascadeOrgVehicle:
    """Full cascade: org_vehicles hit returns source='manual'.

    Requirements: 3.1, 7.1
    """

    @pytest.mark.asyncio
    async def test_org_vehicle_hit_returns_manual_source(self):
        """When vehicle is found in org_vehicles, returns source='manual' with full details."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        org_vehicle = _make_org_vehicle(rego="ABC123", org_id=org_id)

        db = AsyncMock()
        redis = _make_mock_redis_under_limit()
        db.execute = AsyncMock(return_value=_make_scalar_result(org_vehicle))

        request = _make_mock_request(user_id=str(user_id), org_id=str(org_id))

        # Call the service function directly (simulating the router handler)
        result = await lookup_vehicle_for_kiosk(
            db, redis, rego="ABC123", org_id=org_id
        )

        assert result["source"] == "manual"
        assert result["id"] == str(org_vehicle.id)
        assert result["rego"] == "ABC123"
        assert result["make"] == "Toyota"
        assert result["model"] == "Corolla"
        assert result["body_type"] == "Sedan"
        assert result["year"] == 2020
        assert result["colour"] == "White"
        assert result["wof_expiry"] == "2025-06-01"
        assert result["rego_expiry"] == "2025-12-01"
        assert result["odometer"] == 45000

    @pytest.mark.asyncio
    async def test_org_vehicle_hit_does_not_query_global_or_carjam(self):
        """Org vehicle hit should only execute one DB query — no global or CarJam."""
        org_id = uuid.uuid4()
        org_vehicle = _make_org_vehicle(rego="ABC123", org_id=org_id)

        db = AsyncMock()
        redis = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(org_vehicle))

        await lookup_vehicle_for_kiosk(db, redis, rego="ABC123", org_id=org_id)

        # Only one DB query (org_vehicles)
        assert db.execute.call_count == 1


class TestVehicleLookupCascadeGlobalVehicle:
    """Full cascade: global_vehicles hit returns source='cache'.

    Requirements: 3.2, 7.1
    """

    @pytest.mark.asyncio
    async def test_global_vehicle_hit_returns_cache_source(self):
        """When vehicle is found in global_vehicles, returns source='cache' with full details."""
        org_id = uuid.uuid4()
        global_vehicle = _make_global_vehicle(rego="DEF456")

        db = AsyncMock()
        redis = AsyncMock()
        # First call: org_vehicles miss, second call: global_vehicles hit
        db.execute = AsyncMock(side_effect=[
            _make_scalar_result(None),
            _make_scalar_result(global_vehicle),
        ])

        result = await lookup_vehicle_for_kiosk(
            db, redis, rego="DEF456", org_id=org_id
        )

        assert result["source"] == "cache"
        assert result["id"] == str(global_vehicle.id)
        assert result["rego"] == "DEF456"
        assert result["make"] == "Honda"
        assert result["model"] == "Civic"
        assert result["body_type"] == "Hatchback"
        assert result["year"] == 2019
        assert result["colour"] == "Blue"
        assert result["wof_expiry"] == "2025-08-15"
        assert result["rego_expiry"] == "2026-01-10"
        assert result["odometer"] == 62000

    @pytest.mark.asyncio
    async def test_global_vehicle_hit_does_not_call_carjam(self):
        """Global vehicle hit should not call CarJam API."""
        org_id = uuid.uuid4()
        global_vehicle = _make_global_vehicle(rego="DEF456")

        db = AsyncMock()
        redis = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _make_scalar_result(None),
            _make_scalar_result(global_vehicle),
        ])

        with patch(
            "app.modules.vehicles.service._load_carjam_client"
        ) as mock_client:
            await lookup_vehicle_for_kiosk(db, redis, rego="DEF456", org_id=org_id)
            mock_client.assert_not_called()


class TestVehicleLookupCascadeCarjam:
    """Full cascade: CarJam hit returns source='carjam' (mocked).

    Requirements: 3.3, 3.5, 7.1
    """

    @pytest.mark.asyncio
    async def test_carjam_hit_returns_carjam_source(self):
        """When vehicle is found via CarJam, returns source='carjam' and caches result."""
        org_id = uuid.uuid4()
        carjam_data = _make_carjam_data(rego="XYZ789")

        # Mock the new GlobalVehicle that gets created from CarJam data
        new_gv = _make_global_vehicle(
            rego="XYZ789",
            make="Mazda",
            model="3",
            year=2021,
            colour="Red",
            body_type="Sedan",
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
            result = await lookup_vehicle_for_kiosk(
                db, redis, rego="XYZ789", org_id=org_id
            )

        assert result["source"] == "carjam"
        assert result["rego"] == "XYZ789"
        assert result["make"] == "Mazda"
        assert result["model"] == "3"
        assert result["year"] == 2021
        assert result["colour"] == "Red"

        # Verify the vehicle was cached in global_vehicles
        db.add.assert_called_once_with(new_gv)
        db.flush.assert_awaited_once()
        db.refresh.assert_awaited_once_with(new_gv)

    @pytest.mark.asyncio
    async def test_carjam_hit_stores_in_global_vehicles(self):
        """CarJam success stores the result in global_vehicles for future cache hits."""
        org_id = uuid.uuid4()
        carjam_data = _make_carjam_data(rego="GHI321")
        new_gv = _make_global_vehicle(rego="GHI321")

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
            await lookup_vehicle_for_kiosk(db, redis, rego="GHI321", org_id=org_id)

        # Verify caching
        db.add.assert_called_once_with(new_gv)
        db.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# Integration Tests: 404 Not Found
# ---------------------------------------------------------------------------


class TestVehicleLookupNotFound:
    """404 when vehicle not found anywhere in the cascade.

    Requirements: 3.5, 7.1
    """

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        """When vehicle is not in org, global, or CarJam, raises HTTP 404."""
        org_id = uuid.uuid4()

        db = AsyncMock()
        redis = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _make_scalar_result(None),  # org_vehicles miss
            _make_scalar_result(None),  # global_vehicles miss
        ])

        mock_client = AsyncMock()
        mock_client.lookup_vehicle = AsyncMock(
            side_effect=CarjamNotFoundError("NOTFOUND1")
        )

        with patch(
            "app.modules.vehicles.service._load_carjam_client",
            return_value=mock_client,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await lookup_vehicle_for_kiosk(
                    db, redis, rego="NOTFOUND1", org_id=org_id
                )

        assert exc_info.value.status_code == 404
        assert "NOTFOUND1" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_not_found_detail_includes_rego(self):
        """404 error detail includes the registration number that was searched."""
        org_id = uuid.uuid4()

        db = AsyncMock()
        redis = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _make_scalar_result(None),
            _make_scalar_result(None),
        ])

        mock_client = AsyncMock()
        mock_client.lookup_vehicle = AsyncMock(
            side_effect=CarjamNotFoundError("ZZZ999")
        )

        with patch(
            "app.modules.vehicles.service._load_carjam_client",
            return_value=mock_client,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await lookup_vehicle_for_kiosk(
                    db, redis, rego="ZZZ999", org_id=org_id
                )

        assert "ZZZ999" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Integration Tests: Rate Limiting
# ---------------------------------------------------------------------------


class TestVehicleLookupRateLimiting:
    """Rate limiting: 31st request within 60s returns 429.

    Requirements: 7.4
    """

    @pytest.mark.asyncio
    async def test_31st_request_returns_429(self):
        """The 31st request within 60 seconds is rejected with HTTP 429."""
        user_id = str(uuid.uuid4())
        request = _make_mock_request(user_id=user_id, org_id=str(uuid.uuid4()))
        redis = _make_mock_redis_at_limit()

        with pytest.raises(HTTPException) as exc_info:
            await _check_kiosk_rate_limit(request, redis=redis)

        assert exc_info.value.status_code == 429
        assert "rate limit" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_429_includes_retry_after_header(self):
        """Rate limit response includes a Retry-After header."""
        user_id = str(uuid.uuid4())
        request = _make_mock_request(user_id=user_id, org_id=str(uuid.uuid4()))
        redis = _make_mock_redis_at_limit()

        with pytest.raises(HTTPException) as exc_info:
            await _check_kiosk_rate_limit(request, redis=redis)

        assert "Retry-After" in exc_info.value.headers
        retry_after = int(exc_info.value.headers["Retry-After"])
        assert retry_after >= 1

    @pytest.mark.asyncio
    async def test_under_limit_request_allowed(self):
        """Requests under the rate limit (< 30) are allowed through."""
        user_id = str(uuid.uuid4())
        request = _make_mock_request(user_id=user_id, org_id=str(uuid.uuid4()))
        redis = _make_mock_redis_under_limit()

        # Should not raise — request is under the limit
        await _check_kiosk_rate_limit(request, redis=redis)

    @pytest.mark.asyncio
    async def test_exactly_at_limit_blocked(self):
        """When exactly 30 requests are in the window, the next one is blocked."""
        user_id = str(uuid.uuid4())
        request = _make_mock_request(user_id=user_id, org_id=str(uuid.uuid4()))

        # Simulate exactly 30 requests in the window
        redis = AsyncMock(spec=Redis)
        pipe1 = AsyncMock()
        pipe1.zremrangebyscore = MagicMock(return_value=pipe1)
        pipe1.zcard = MagicMock(return_value=pipe1)
        pipe1.execute = AsyncMock(return_value=[0, 30])

        redis.pipeline = MagicMock(return_value=pipe1)

        now = time.time()
        redis.zrange = AsyncMock(return_value=[(b"oldest", now - 55)])

        with pytest.raises(HTTPException) as exc_info:
            await _check_kiosk_rate_limit(request, redis=redis)

        assert exc_info.value.status_code == 429


# ---------------------------------------------------------------------------
# Integration Tests: Role Enforcement
# ---------------------------------------------------------------------------


class TestVehicleLookupRoleEnforcement:
    """Role enforcement: non-kiosk role gets 403.

    Requirements: 7.1, 7.4
    """

    @pytest.mark.asyncio
    async def test_non_kiosk_role_rejected(self):
        """A user with 'salesperson' role is rejected with 403 by require_role('kiosk')."""
        from app.modules.auth.rbac import require_role

        # Get the inner check function from the Depends wrapper
        depends_obj = require_role("kiosk")
        check_fn = depends_obj.dependency

        request = _make_mock_request(
            user_id=str(uuid.uuid4()),
            org_id=str(uuid.uuid4()),
            role="salesperson",
        )

        with pytest.raises(HTTPException) as exc_info:
            await check_fn(request)

        assert exc_info.value.status_code == 403
        assert "kiosk" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_org_admin_role_rejected(self):
        """A user with 'org_admin' role is rejected for kiosk-only endpoints."""
        from app.modules.auth.rbac import require_role

        depends_obj = require_role("kiosk")
        check_fn = depends_obj.dependency

        request = _make_mock_request(
            user_id=str(uuid.uuid4()),
            org_id=str(uuid.uuid4()),
            role="org_admin",
        )

        with pytest.raises(HTTPException) as exc_info:
            await check_fn(request)

        assert exc_info.value.status_code == 403
        assert "kiosk" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_kiosk_role_allowed(self):
        """A user with 'kiosk' role is allowed access to the vehicle-lookup endpoint."""
        from app.modules.auth.rbac import require_role

        depends_obj = require_role("kiosk")
        check_fn = depends_obj.dependency

        request = _make_mock_request(
            user_id=str(uuid.uuid4()),
            org_id=str(uuid.uuid4()),
            role="kiosk",
        )

        # Should not raise — kiosk role is allowed
        await check_fn(request)

    @pytest.mark.asyncio
    async def test_unauthenticated_request_rejected(self):
        """A request without user_id/role is rejected with 401."""
        from app.modules.auth.rbac import require_role

        # Get the inner check function from the Depends wrapper
        depends_obj = require_role("kiosk")
        check_fn = depends_obj.dependency

        # Create a request with no auth context
        request = MagicMock()
        request.state.user_id = None
        request.state.org_id = None
        request.state.role = None

        with pytest.raises(HTTPException) as exc_info:
            await check_fn(request)

        assert exc_info.value.status_code == 401
        assert "Authentication required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_wrong_role_gets_403_with_detail(self):
        """A request with wrong role gets 403 with descriptive detail message."""
        from app.modules.auth.rbac import require_role

        depends_obj = require_role("kiosk")
        check_fn = depends_obj.dependency

        request = _make_mock_request(
            user_id=str(uuid.uuid4()),
            org_id=str(uuid.uuid4()),
            role="staff_member",
        )

        with pytest.raises(HTTPException) as exc_info:
            await check_fn(request)

        assert exc_info.value.status_code == 403
        assert "kiosk" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# Integration Tests: Full Router Handler Flow
# ---------------------------------------------------------------------------


class TestVehicleLookupRouterHandler:
    """Test the full router handler function (vehicle_lookup) end-to-end.

    Requirements: 3.1, 3.2, 7.1
    """

    @pytest.mark.asyncio
    async def test_router_handler_returns_result_for_org_vehicle(self):
        """The vehicle_lookup router handler returns the lookup result correctly."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        org_vehicle = _make_org_vehicle(rego="RTR123", org_id=org_id)

        db = AsyncMock()
        redis = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(org_vehicle))

        request = _make_mock_request(user_id=str(user_id), org_id=str(org_id))
        payload = KioskVehicleLookupRequest(rego="rtr123")

        result = await vehicle_lookup(
            payload=payload,
            request=request,
            db=db,
            redis=redis,
        )

        assert result["source"] == "manual"
        assert result["rego"] == "RTR123"

    @pytest.mark.asyncio
    async def test_router_handler_returns_403_without_org_context(self):
        """The vehicle_lookup handler returns 403 when org context is missing."""
        db = AsyncMock()
        redis = AsyncMock()

        # Request without org_id
        request = MagicMock()
        request.state.user_id = str(uuid.uuid4())
        request.state.org_id = None
        request.state.role = "kiosk"
        request.state.client_ip = "10.0.0.1"

        payload = KioskVehicleLookupRequest(rego="ABC123")

        result = await vehicle_lookup(
            payload=payload,
            request=request,
            db=db,
            redis=redis,
        )

        # Should return a JSONResponse with 403
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_router_handler_normalises_rego_input(self):
        """The router handler normalises rego (strip + uppercase) via schema validator."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        org_vehicle = _make_org_vehicle(rego="LOW123", org_id=org_id)

        db = AsyncMock()
        redis = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(org_vehicle))

        request = _make_mock_request(user_id=str(user_id), org_id=str(org_id))

        # Input with lowercase and whitespace — schema validator should clean it
        payload = KioskVehicleLookupRequest(rego="  low123  ")

        # Verify the schema cleaned the rego
        assert payload.rego == "LOW123"

        result = await vehicle_lookup(
            payload=payload,
            request=request,
            db=db,
            redis=redis,
        )

        assert result["rego"] == "LOW123"
