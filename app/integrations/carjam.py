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
    lookup_type: str = "basic"  # "basic" or "abcd"
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
    # Extended fields
    vin: str | None = None
    chassis: str | None = None
    engine_no: str | None = None
    transmission: str | None = None
    country_of_origin: str | None = None
    number_of_owners: int | None = None
    vehicle_type: str | None = None
    reported_stolen: str | None = None
    power_kw: int | None = None
    tare_weight: int | None = None
    gross_vehicle_mass: int | None = None
    date_first_registered_nz: str | None = None
    plate_type: str | None = None
    submodel: str | None = None
    second_colour: str | None = None


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


def _parse_vehicle_response(rego: str, data: dict[str, Any], lookup_type: str = "basic") -> CarjamVehicleData:
    """Extract vehicle fields from a Carjam regular API response dict.
    
    Regular API returns data in message.idh.vehicle format.
    """

    def _safe_int(val: Any) -> int | None:
        if val is None or val == "":
            return None
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    def _safe_str(val: Any) -> str | None:
        """Convert value to string, handling None and empty values."""
        if val is None or val == "":
            return None
        return str(val)

    def _timestamp_to_date(val: Any) -> str | None:
        """Convert UNIX timestamp to ISO date string."""
        if val is None or val == "":
            return None
        try:
            import datetime
            ts = int(val)
            dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
            return dt.date().isoformat()
        except (ValueError, TypeError):
            return None

    return CarjamVehicleData(
        rego=rego.upper().strip(),
        lookup_type=lookup_type,
        make=data.get("make"),
        model=data.get("model"),
        year=_safe_int(data.get("year_of_manufacture")),
        colour=data.get("main_colour"),
        body_type=data.get("body_style"),
        fuel_type=_safe_str(data.get("fuel_type")),
        engine_size=_safe_str(data.get("cc_rating")),
        seats=_safe_int(data.get("no_of_seats")),
        wof_expiry=_timestamp_to_date(data.get("expiry_date_of_last_successful_wof")),
        rego_expiry=_timestamp_to_date(data.get("licence_expiry_date")),
        odometer=_safe_int(data.get("latest_odometer_reading")),
        # Extended fields
        vin=_safe_str(data.get("vin")),
        chassis=_safe_str(data.get("chassis")),
        engine_no=_safe_str(data.get("engine_no")),
        transmission=_safe_str(data.get("transmission_type")),
        country_of_origin=_safe_str(data.get("country_of_origin")),
        number_of_owners=_safe_int(data.get("number_of_owners")),
        vehicle_type=_safe_str(data.get("vehicle_type")),
        reported_stolen=_safe_str(data.get("reported_stolen_nzta") or data.get("reported_stolen")),
        power_kw=_safe_int(data.get("power")),
        tare_weight=_safe_int(data.get("tare_weight")),
        gross_vehicle_mass=_safe_int(data.get("gross_vehicle_mass")),
        date_first_registered_nz=_timestamp_to_date(data.get("date_of_first_registration_in_nz")),
        plate_type=_safe_str(data.get("plate_type")),
        submodel=_safe_str(data.get("submodel")),
        second_colour=_safe_str(data.get("second_colour")),
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
        # Carjam regular API endpoint: /api/car/
        url = f"{self._base_url}/api/car/"
        params = {
            "key": self._api_key,
            "plate": rego,
            "basic": "1",
            "f": "json",  # Request JSON format instead of XML
        }

        logger.info(f"Carjam API call: URL={url}, params={params}")

        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as http:
                response = await http.get(url, params=params)
                logger.info(f"Carjam API response: status={response.status_code}, url={response.url}")
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

        # Check for error response (has "error" key)
        if "error" in body:
            error_data = body["error"]
            error_code = error_data.get("code", "unknown")
            error_msg = error_data.get("message", "Unknown Carjam error")
            logger.error("Carjam API error for rego=%s: [%s] %s", rego, error_code, error_msg)
            
            # Check if it's a "not found" type error
            if "not found" in error_msg.lower():
                raise CarjamNotFoundError(rego)
            
            raise CarjamError(f"Carjam API error: {error_msg}")

        # JSON format returns {'idh': {...}} directly (no 'message' wrapper)
        if "idh" not in body:
            raise CarjamNotFoundError(rego)
        
        idh_data = body["idh"]
        
        if "vehicle" not in idh_data:
            raise CarjamNotFoundError(rego)

        vehicle_data = idh_data["vehicle"]
        
        # Check if vehicle has basic data
        if not vehicle_data.get("make"):
            raise CarjamNotFoundError(rego)

        return _parse_vehicle_response(rego, vehicle_data, lookup_type="basic")

    async def lookup_vehicle_abcd(self, rego: str, use_mvr: bool = True) -> CarjamVehicleData:
        """Look up a vehicle using ABCD (Absolute Basic Car Details) API.
        
        This is a lower-cost API option that provides basic vehicle information.
        
        Parameters
        ----------
        rego:
            Vehicle registration plate, VIN, or chassis number
        use_mvr:
            If True (default), allows fetching from Motor Vehicle Register if CarJam
            doesn't have data internally. If False, only uses CarJam's internal data.
            Note: MVR access adds 17c NZD to the API call cost.
        
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
        # Carjam ABCD API endpoint: /a/vehicle:abcd
        url = f"{self._base_url}/a/vehicle:abcd"
        params = {
            "key": self._api_key,
            "plate": rego,
            "mvr": "1" if use_mvr else "0",
        }

        logger.info(f"Carjam ABCD API call: URL={url}, plate={rego}, mvr={use_mvr}")

        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as http:
                response = await http.get(url, params=params)
                logger.info(f"Carjam ABCD API response: status={response.status_code}")
                
                # Check for Refresh header (data is being fetched)
                refresh_header = response.headers.get("Refresh")
                if refresh_header:
                    logger.info(f"Carjam ABCD: Data being fetched, refresh in {refresh_header}s")
                    raise CarjamError(f"Carjam is fetching data, retry in {refresh_header} seconds")
                    
        except httpx.TimeoutException:
            logger.error("Carjam ABCD API timeout for rego=%s", rego)
            raise CarjamError(f"Carjam ABCD API timed out for rego '{rego}'")
        except httpx.HTTPError as exc:
            logger.error("Carjam ABCD HTTP error for rego=%s: %s", rego, exc)
            raise CarjamError(f"Carjam ABCD HTTP error: {exc}") from exc

        # --- Handle response status ---
        if response.status_code == 404:
            raise CarjamNotFoundError(rego)

        if response.status_code == 429:
            retry_hdr = response.headers.get("Retry-After", "60")
            try:
                retry_secs = int(retry_hdr)
            except ValueError:
                retry_secs = 60
            logger.warning(
                "Carjam ABCD API returned 429 for rego=%s — retry after %ds",
                rego,
                retry_secs,
            )
            raise CarjamRateLimitError(retry_after=retry_secs)

        if response.status_code != 200:
            logger.error(
                "Carjam ABCD API unexpected status %d for rego=%s: %s",
                response.status_code,
                rego,
                response.text[:500],
            )
            raise CarjamError(
                f"Carjam ABCD API returned status {response.status_code}"
            )

        # --- Parse response ---
        try:
            body = response.json()
        except Exception as exc:
            raise CarjamError("Failed to parse Carjam ABCD response JSON") from exc

        # Check for error response
        if "code" in body and "message" in body:
            error_code = body.get("code")
            error_msg = body.get("message", "Unknown Carjam error")
            logger.error("Carjam ABCD API error for rego=%s: [%s] %s", rego, error_code, error_msg)
            raise CarjamError(f"Carjam ABCD API error: {error_msg}")

        # Check for null response (data not ready yet)
        if body is None or (isinstance(body, dict) and not body):
            logger.info(f"Carjam ABCD: Null response for {rego}, data not ready")
            # Return a special response indicating data is being fetched
            raise CarjamError("ABCD_FETCHING")

        # Check if we have basic required fields
        if not body.get("make"):
            raise CarjamNotFoundError(rego)

        return _parse_vehicle_response(rego, body, lookup_type="abcd")
