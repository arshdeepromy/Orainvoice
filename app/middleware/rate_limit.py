"""Redis sliding-window rate limiter middleware.

Enforces three tiers of rate limiting using Redis sorted sets:
  • Per-user:  100 req/min  (configurable via settings)
  • Per-org:   1000 req/min (configurable via settings)
  • Per-IP on auth endpoints: 10 req/min (configurable via settings)

When a limit is exceeded the middleware returns HTTP 429 with a
``Retry-After`` header.
"""

import time

from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings
from app.middleware.auth import is_auth_endpoint

# Window size in seconds.
_WINDOW = 60

# Password reset paths get stricter rate limiting.
_PASSWORD_RESET_PATHS: set[str] = {
    "/api/v1/auth/password/reset-request",
    "/api/v1/auth/password/reset",
    "/api/v2/auth/password/reset-request",
    "/api/v2/auth/password/reset",
}

# Default password reset limit per IP per minute.
_PASSWORD_RESET_LIMIT = 5


async def _check_rate_limit(
    redis: Redis,
    key: str,
    limit: int,
    now: float,
) -> tuple[bool, int]:
    """Return (allowed, retry_after_seconds) using a sorted-set sliding window.

    Members are timestamps (score = timestamp). On each call we:
      1. Remove entries older than ``now - WINDOW``.
      2. Count remaining entries.
      3. If under the limit, add the current timestamp.
    """
    window_start = now - _WINDOW

    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, window_start)
    pipe.zcard(key)
    results = await pipe.execute()
    count: int = results[1]

    if count >= limit:
        # Find the oldest entry still in the window to compute retry-after.
        oldest = await redis.zrange(key, 0, 0, withscores=True)
        if oldest:
            retry_after = int(oldest[0][1] + _WINDOW - now) + 1
        else:
            retry_after = 1
        return False, max(retry_after, 1)

    # Record this request.
    pipe2 = redis.pipeline()
    pipe2.zadd(key, {f"{now}": now})
    pipe2.expire(key, _WINDOW + 5)  # TTL slightly beyond window
    await pipe2.execute()

    return True, 0


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter backed by Redis."""

    def __init__(self, app, redis: Redis | None = None):
        super().__init__(app)
        self._redis = redis
        self._connected = False

    async def _get_redis(self) -> Redis | None:
        """Lazily connect to Redis; return None if unavailable."""
        if self._redis is not None:
            return self._redis
        if self._connected:
            return self._redis
        try:
            self._redis = Redis.from_url(
                settings.redis_url,
                decode_responses=True,
            )
            await self._redis.ping()
            self._connected = True
        except Exception:
            # If Redis is down, allow requests through (fail-open).
            self._redis = None
            self._connected = True
        return self._redis

    async def dispatch(self, request: Request, call_next):
        redis = await self._get_redis()
        if redis is None:
            # Fail-open: no rate limiting when Redis is unavailable.
            return await call_next(request)

        now = time.time()
        path = request.url.path

        # --- Password reset per-IP limit (strictest: 5/min) ---
        if path in _PASSWORD_RESET_PATHS:
            client_ip = request.client.host if request.client else "unknown"
            key = f"rl:pwreset:ip:{client_ip}"
            allowed, retry_after = await _check_rate_limit(
                redis, key, _PASSWORD_RESET_LIMIT, now,
            )
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many password reset requests — try again later"},
                    headers={"Retry-After": str(retry_after)},
                )

        # --- Auth-endpoint per-IP limit ---
        if is_auth_endpoint(path):
            client_ip = request.client.host if request.client else "unknown"
            key = f"rl:auth:ip:{client_ip}"
            allowed, retry_after = await _check_rate_limit(
                redis, key, settings.rate_limit_auth_per_ip_per_minute, now,
            )
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests — try again later"},
                    headers={"Retry-After": str(retry_after)},
                )

        # --- Per-user limit ---
        user_id: str | None = getattr(request.state, "user_id", None)
        if user_id:
            key = f"rl:user:{user_id}"
            allowed, retry_after = await _check_rate_limit(
                redis, key, settings.rate_limit_per_user_per_minute, now,
            )
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests — try again later"},
                    headers={"Retry-After": str(retry_after)},
                )

        # --- Per-org limit ---
        org_id: str | None = getattr(request.state, "org_id", None)
        if org_id:
            key = f"rl:org:{org_id}"
            allowed, retry_after = await _check_rate_limit(
                redis, key, settings.rate_limit_per_org_per_minute, now,
            )
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Organisation rate limit exceeded — try again later"},
                    headers={"Retry-After": str(retry_after)},
                )

        return await call_next(request)
