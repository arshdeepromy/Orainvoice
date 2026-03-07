"""Carjam API client with Redis sliding-window rate limiting.

Provides async vehicle lookup by NZ registration plate via the Carjam API.
Rate limiting is enforced globally across the platform using a Redis
sliding-window counter, with the limit configurable by Global_Admin via
the ``integration_configs`` table (falls back to ``settings``).

Usage::

    from app.integrations.carjam import CarjamClient

    client = CarjamClient(redis=redis_pool)
    vehicle = await client.lookup_vehicle("ABC123")

Errors::

    CarjamError          — base error for all Carjam failures
    CarjamRateLimitError — platform-wide rate limit exceeded
    CarjamNotFoundError  — Carjam returned no result for the rego
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
from redis.asyncio import Redis

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CarjamError(Exception):
    """Base exception for Carjam integration failures."""


class CarjamRateLimitError(CarjamError):
    """Raised when the platform-wide Carjam rate limit is exceeded."""

    def __init__(self, retry_after: int = 1) -> None:
        self.retry_after = retry_after
        super().__init__(
            f"Carjam rate limit exceeded — retry after {retry_after}s"
        )


class CarjamNotFoundError(CarjamError):
    """Raised when Carjam returns no data for the given registration."""

    def __init__(self, rego: str) -> None:
        self.rego = rego
        super().__init__(f"No Carjam result for rego '{rego}'")


# ---------------------------------------------------------------------------
# Vehicle data container
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CarjamVehicleData:
    """Typed container for vehicle data returned by the Carjam API."""

    rego: str
    make: str | None = None
    model: str | None = None
    year: int | None = None
    colour: str | None = None
    body_type: str | None = None
    fuel_type: str | None = None
    engine_size: str | None = None
    seats: int | None = None
    wof_expiry: str | None = None
    rego_expiry: str | None = None
    odometer: int | None = None


# ---------------------------------------------------------------------------
# Rate limiter (sliding window via Redis sorted set)
# ---------------------------------------------------------------------------

_RATE_LIMIT_KEY = "carjam:global_rate_limit"
_RATE_LIMIT_WINDOW = 60  # seconds


async def _check_carjam_rate_limit(
    redis: Redis,
    limit: int,
) -> tuple[bool, int]:
    """Check the global Carjam rate limit using a sliding-window sorted set.

    Returns ``(allowed, retry_after_seconds)``.
    """
    now = time.time()
    window_start = now - _RATE_LIMIT_WINDOW

    pipe = redis.pipeline()
    pipe.zremrangebyscore(_RATE_LIMIT_KEY, 0, window_start)
    pipe.zcard(_RATE_LIMIT_KEY)
    results = await pipe.execute()
    count: int = results[1]

    if count >= limit:
        oldest = await redis.zrange(
            _RATE_LIMIT_KEY, 0, 0, withscores=True,
        )
        if oldest:
            retry_after = int(oldest[0][1] + _RATE_LIMIT_WINDOW - now) + 1
        else:
            retry_after = 1
        return False, max(retry_after, 1)

    # Record this call.
    pipe2 = redis.pipeline()
    pipe2.zadd(_RATE_LIMIT_KEY, {f"{now}": now})
    pipe2.expire(_RATE_LIMIT_KEY, _RATE_LIMIT_WINDOW + 5)
    await pipe2.execute()

    return True, 0


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_vehicle_response(rego: str, data: dict[str, Any]) -> CarjamVehicleData:
    """Extract vehicle fields from a Carjam API response dict."""

    def _safe_int(val: Any) -> int | None:
        if val is None:
            return None
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    return CarjamVehicleData(
        rego=rego.upper().strip(),
        make=data.get("make"),
        model=data.get("model"),
        year=_safe_int(data.get("year")),
        colour=data.get("colour"),
        body_type=data.get("body_type"),
        fuel_type=data.get("fuel_type"),
        engine_size=data.get("engine_size"),
        seats=_safe_int(data.get("seats")),
        wof_expiry=data.get("wof_expiry"),
        rego_expiry=data.get("rego_expiry"),
        odometer=_safe_int(data.get("odometer")),
    )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT = 10.0  # seconds


class CarjamClient:
    """Async Carjam API client with Redis-backed global rate limiting.

    Parameters
    ----------
    redis:
        An ``redis.asyncio.Redis`` instance for rate limiting.
    api_key:
        Carjam API key.  Falls back to ``settings.carjam_api_key``.
    base_url:
        Carjam base URL.  Falls back to ``settings.carjam_base_url``.
    rate_limit:
        Maximum Carjam API calls per minute (platform-wide).
        Falls back to ``settings.carjam_global_rate_limit_per_minute``.
    timeout:
        HTTP request timeout in seconds.
    """

    def __init__(
        self,
        redis: Redis,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        rate_limit: int | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._redis = redis
        self._api_key = api_key or settings.carjam_api_key
        self._base_url = (base_url or settings.carjam_base_url).rstrip("/")
        self._rate_limit = rate_limit or settings.carjam_global_rate_limit_per_minute
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def lookup_vehicle(self, rego: str) -> CarjamVehicleData:
        """Look up a vehicle by NZ registration plate.

        Enforces the global rate limit before making the HTTP call.

        Raises
        ------
        CarjamRateLimitError
            If the platform-wide rate limit has been exceeded.
        CarjamNotFoundError
            If Carjam returns no data for the registration.
        CarjamError
            On any other HTTP or parsing failure.
        """
        rego = rego.upper().strip()
        if not rego:
            raise CarjamError("Registration plate cannot be empty")

        # --- Rate limit check ---
        allowed, retry_after = await _check_carjam_rate_limit(
            self._redis, self._rate_limit,
        )
        if not allowed:
            logger.warning(
                "Carjam global rate limit hit (%d/min) — retry after %ds",
                self._rate_limit,
                retry_after,
            )
            raise CarjamRateLimitError(retry_after=retry_after)

        # --- HTTP call ---
        url = f"{self._base_url}/car/{rego}"
        headers = {"Authorization": f"Bearer {self._api_key}"}

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as http:
                response = await http.get(url, headers=headers)
        except httpx.TimeoutException:
            logger.error("Carjam API timeout for rego=%s", rego)
            raise CarjamError(f"Carjam API timed out for rego '{rego}'")
        except httpx.HTTPError as exc:
            logger.error("Carjam HTTP error for rego=%s: %s", rego, exc)
            raise CarjamError(f"Carjam HTTP error: {exc}") from exc

        # --- Handle response status ---
        if response.status_code == 404:
            raise CarjamNotFoundError(rego)

        if response.status_code == 429:
            # Carjam's own rate limit (distinct from our platform limit).
            retry_hdr = response.headers.get("Retry-After", "60")
            try:
                retry_secs = int(retry_hdr)
            except ValueError:
                retry_secs = 60
            logger.warning(
                "Carjam API returned 429 for rego=%s — retry after %ds",
                rego,
                retry_secs,
            )
            raise CarjamRateLimitError(retry_after=retry_secs)

        if response.status_code != 200:
            logger.error(
                "Carjam API unexpected status %d for rego=%s: %s",
                response.status_code,
                rego,
                response.text[:500],
            )
            raise CarjamError(
                f"Carjam API returned status {response.status_code}"
            )

        # --- Parse response ---
        try:
            body = response.json()
        except Exception as exc:
            raise CarjamError("Failed to parse Carjam response JSON") from exc

        if not body:
            raise CarjamNotFoundError(rego)

        return _parse_vehicle_response(rego, body)
