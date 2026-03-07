"""Unit tests for the Carjam API client (Task 8.1).

Tests cover:
  - CarjamVehicleData construction
  - Response parsing (_parse_vehicle_response)
  - Rate limiting logic (_check_carjam_rate_limit)
  - CarjamClient.lookup_vehicle — success, 404, 429, timeout, empty rego
  - Error hierarchy
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.integrations.carjam import (
    CarjamClient,
    CarjamError,
    CarjamNotFoundError,
    CarjamRateLimitError,
    CarjamVehicleData,
    _check_carjam_rate_limit,
    _parse_vehicle_response,
)


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------


class TestCarjamVehicleData:
    def test_construction_with_all_fields(self):
        v = CarjamVehicleData(
            rego="ABC123",
            make="Toyota",
            model="Corolla",
            year=2020,
            colour="White",
            body_type="Sedan",
            fuel_type="Petrol",
            engine_size="1.8L",
            seats=5,
            wof_expiry="2025-06-01",
            rego_expiry="2025-12-01",
            odometer=45000,
        )
        assert v.rego == "ABC123"
        assert v.make == "Toyota"
        assert v.year == 2020
        assert v.seats == 5

    def test_construction_minimal(self):
        v = CarjamVehicleData(rego="XYZ789")
        assert v.rego == "XYZ789"
        assert v.make is None
        assert v.year is None

    def test_frozen(self):
        v = CarjamVehicleData(rego="ABC123")
        with pytest.raises(AttributeError):
            v.rego = "CHANGED"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


class TestParseVehicleResponse:
    def test_full_response(self):
        data = {
            "make": "Honda",
            "model": "Civic",
            "year": "2019",
            "colour": "Blue",
            "body_type": "Hatchback",
            "fuel_type": "Petrol",
            "engine_size": "1.5L",
            "seats": "5",
            "wof_expiry": "2025-03-15",
            "rego_expiry": "2025-09-30",
            "odometer": "62000",
        }
        v = _parse_vehicle_response("abc123", data)
        assert v.rego == "ABC123"
        assert v.make == "Honda"
        assert v.year == 2019
        assert v.seats == 5
        assert v.odometer == 62000

    def test_missing_fields_default_to_none(self):
        v = _parse_vehicle_response("DEF456", {})
        assert v.rego == "DEF456"
        assert v.make is None
        assert v.year is None

    def test_non_numeric_year_returns_none(self):
        v = _parse_vehicle_response("GHI789", {"year": "unknown"})
        assert v.year is None

    def test_rego_normalised_to_uppercase(self):
        v = _parse_vehicle_response("  abc123  ", {"make": "Ford"})
        assert v.rego == "ABC123"


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


class TestExceptions:
    def test_carjam_error_is_base(self):
        assert issubclass(CarjamRateLimitError, CarjamError)
        assert issubclass(CarjamNotFoundError, CarjamError)

    def test_rate_limit_error_has_retry_after(self):
        err = CarjamRateLimitError(retry_after=30)
        assert err.retry_after == 30
        assert "30" in str(err)

    def test_not_found_error_has_rego(self):
        err = CarjamNotFoundError("XYZ999")
        assert err.rego == "XYZ999"
        assert "XYZ999" in str(err)


# ---------------------------------------------------------------------------
# Rate limiting (with mock Redis)
# ---------------------------------------------------------------------------


def _make_mock_redis(count: int = 0, oldest_score: float | None = None):
    """Build a mock Redis that simulates sorted-set rate limit state.

    ``redis.asyncio.Redis.pipeline()`` is synchronous (returns a Pipeline
    object directly), but ``Pipeline.execute()`` is async.
    """
    from unittest.mock import MagicMock

    redis = MagicMock()

    # Pipeline for zremrangebyscore + zcard
    pipe1 = MagicMock()
    pipe1.execute = AsyncMock(return_value=[0, count])

    # Pipeline for zadd + expire
    pipe2 = MagicMock()
    pipe2.execute = AsyncMock(return_value=[1, True])

    # pipeline() is synchronous — returns pipe1 first, pipe2 second
    redis.pipeline = MagicMock(side_effect=[pipe1, pipe2])

    # zrange is async
    if oldest_score is not None:
        redis.zrange = AsyncMock(return_value=[("ts", oldest_score)])
    else:
        redis.zrange = AsyncMock(return_value=[])

    return redis


class TestCheckCarjamRateLimit:
    @pytest.mark.asyncio
    async def test_allowed_when_under_limit(self):
        redis = _make_mock_redis(count=5)
        allowed, retry_after = await _check_carjam_rate_limit(redis, limit=60)
        assert allowed is True
        assert retry_after == 0

    @pytest.mark.asyncio
    async def test_denied_when_at_limit(self):
        import time

        redis = _make_mock_redis(count=60, oldest_score=time.time() - 30)
        allowed, retry_after = await _check_carjam_rate_limit(redis, limit=60)
        assert allowed is False
        assert retry_after > 0

    @pytest.mark.asyncio
    async def test_denied_with_no_oldest_entry(self):
        redis = _make_mock_redis(count=60, oldest_score=None)
        redis.zrange = AsyncMock(return_value=[])
        allowed, retry_after = await _check_carjam_rate_limit(redis, limit=60)
        assert allowed is False
        assert retry_after >= 1


# ---------------------------------------------------------------------------
# CarjamClient.lookup_vehicle
# ---------------------------------------------------------------------------


def _make_client(redis=None, rate_limit=100):
    """Build a CarjamClient with test defaults."""
    return CarjamClient(
        redis=redis or _make_mock_redis(count=0),
        api_key="test-key",
        base_url="https://api.carjam.co.nz",
        rate_limit=rate_limit,
    )


class TestCarjamClientLookup:
    @pytest.mark.asyncio
    async def test_successful_lookup(self):
        mock_response = httpx.Response(
            200,
            json={
                "make": "Toyota",
                "model": "Hilux",
                "year": "2021",
                "colour": "Silver",
            },
            request=httpx.Request("GET", "https://api.carjam.co.nz/car/ABC123"),
        )

        client = _make_client()
        with patch("app.integrations.carjam.httpx.AsyncClient") as mock_http:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_http.return_value = mock_instance

            result = await client.lookup_vehicle("abc123")

        assert result.rego == "ABC123"
        assert result.make == "Toyota"
        assert result.model == "Hilux"
        assert result.year == 2021

    @pytest.mark.asyncio
    async def test_404_raises_not_found(self):
        mock_response = httpx.Response(
            404,
            text="Not found",
            request=httpx.Request("GET", "https://api.carjam.co.nz/car/ZZZ999"),
        )

        client = _make_client()
        with patch("app.integrations.carjam.httpx.AsyncClient") as mock_http:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_http.return_value = mock_instance

            with pytest.raises(CarjamNotFoundError) as exc_info:
                await client.lookup_vehicle("ZZZ999")
            assert exc_info.value.rego == "ZZZ999"

    @pytest.mark.asyncio
    async def test_429_raises_rate_limit_error(self):
        mock_response = httpx.Response(
            429,
            text="Too many requests",
            headers={"Retry-After": "45"},
            request=httpx.Request("GET", "https://api.carjam.co.nz/car/ABC123"),
        )

        client = _make_client()
        with patch("app.integrations.carjam.httpx.AsyncClient") as mock_http:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_http.return_value = mock_instance

            with pytest.raises(CarjamRateLimitError) as exc_info:
                await client.lookup_vehicle("ABC123")
            assert exc_info.value.retry_after == 45

    @pytest.mark.asyncio
    async def test_timeout_raises_carjam_error(self):
        client = _make_client()
        with patch("app.integrations.carjam.httpx.AsyncClient") as mock_http:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_http.return_value = mock_instance

            with pytest.raises(CarjamError, match="timed out"):
                await client.lookup_vehicle("ABC123")

    @pytest.mark.asyncio
    async def test_empty_rego_raises_error(self):
        client = _make_client()
        with pytest.raises(CarjamError, match="empty"):
            await client.lookup_vehicle("")

    @pytest.mark.asyncio
    async def test_whitespace_rego_raises_error(self):
        client = _make_client()
        with pytest.raises(CarjamError, match="empty"):
            await client.lookup_vehicle("   ")

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_before_http_call(self):
        """When the platform rate limit is hit, no HTTP call should be made."""
        redis = _make_mock_redis(count=5)
        client = _make_client(redis=redis, rate_limit=5)

        with patch("app.integrations.carjam.httpx.AsyncClient") as mock_http:
            with pytest.raises(CarjamRateLimitError):
                await client.lookup_vehicle("ABC123")
            # httpx.AsyncClient should never have been instantiated
            mock_http.assert_not_called()

    @pytest.mark.asyncio
    async def test_server_error_raises_carjam_error(self):
        mock_response = httpx.Response(
            500,
            text="Internal Server Error",
            request=httpx.Request("GET", "https://api.carjam.co.nz/car/ABC123"),
        )

        client = _make_client()
        with patch("app.integrations.carjam.httpx.AsyncClient") as mock_http:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_http.return_value = mock_instance

            with pytest.raises(CarjamError, match="500"):
                await client.lookup_vehicle("ABC123")

    @pytest.mark.asyncio
    async def test_empty_json_body_raises_not_found(self):
        mock_response = httpx.Response(
            200,
            json={},
            request=httpx.Request("GET", "https://api.carjam.co.nz/car/ABC123"),
        )

        client = _make_client()
        with patch("app.integrations.carjam.httpx.AsyncClient") as mock_http:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_http.return_value = mock_instance

            with pytest.raises(CarjamNotFoundError):
                await client.lookup_vehicle("ABC123")
