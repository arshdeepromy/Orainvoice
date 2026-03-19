"""Redis sliding-window rate limiter middleware.

Enforces three tiers of rate limiting using Redis sorted sets:
  * Per-user:  100 req/min  (configurable via settings)
  * Per-org:   1000 req/min (configurable via settings)
  * Per-IP on auth endpoints: 10 req/min (configurable via settings)

When a limit is exceeded the middleware returns HTTP 429 with a
``Retry-After`` header.

When Redis is unavailable the middleware fails closed — returning
HTTP 503 (Service Unavailable) to prevent unlimited unthrottled access.

Implemented as pure ASGI middleware to avoid request body stream corruption.
"""

import logging
import time

from redis.asyncio import Redis
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings
from app.middleware.auth import is_auth_endpoint

logger = logging.getLogger(__name__)

# Window size in seconds.
_WINDOW = 60

# Password reset paths get stricter rate limiting.
_PASSWORD_RESET_PATHS: set[str] = {
    "/api/v1/auth/password/reset-request",
    "/api/v1/auth/password/reset",
    "/api/v2/auth/password/reset-request",
    "/api/v2/auth/password/reset",
}

# Public read-only auth endpoints that should not be rate limited strictly
_PUBLIC_READ_ONLY_PATHS: set[str] = {
    "/api/v1/auth/plans",
    "/api/v1/auth/captcha",
    "/api/v1/auth/verify-captcha",
    "/api/v1/auth/stripe-publishable-key",
    "/api/v2/auth/plans",
    "/api/v2/auth/captcha",
    "/api/v2/auth/verify-captcha",
    "/api/v2/auth/stripe-publishable-key",
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
    
    If limit is 0, rate limiting is disabled and always returns allowed=True.
    """
    # If limit is 0, rate limiting is disabled
    if limit <= 0:
        return True, 0
    
    window_start = now - _WINDOW

    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, window_start)
    pipe.zcard(key)
    results = await pipe.execute()
    count: int = results[1]

    if count >= limit:
        oldest = await redis.zrange(key, 0, 0, withscores=True)
        if oldest:
            retry_after = int(oldest[0][1] + _WINDOW - now) + 1
        else:
            retry_after = 1
        return False, max(retry_after, 1)

    pipe2 = redis.pipeline()
    pipe2.zadd(key, {f"{now}": now})
    pipe2.expire(key, _WINDOW + 5)
    await pipe2.execute()

    return True, 0


class RateLimitMiddleware:
    """Sliding-window rate limiter backed by Redis.

    Pure ASGI implementation — does not wrap the receive channel.
    """

    def __init__(self, app: ASGIApp, redis: Redis | None = None) -> None:
        self.app = app
        self._redis = redis

    async def _get_redis(self) -> Redis | None:
        """Return the shared Redis pool; no per-request connection creation."""
        if self._redis is not None:
            return self._redis

        try:
            from app.core.redis import redis_pool
            self._redis = redis_pool
            await self._redis.ping()
        except Exception:
            logger.warning("Redis unavailable — rate limiter will fail open for this request")
            self._redis = None
        return self._redis

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        redis = await self._get_redis()

        if not redis:
            # Fail open — allow the request through when Redis is unavailable.
            # Logging the event so operators can investigate.
            logger.warning("Rate limiter Redis unavailable — allowing request through")
            await self.app(scope, receive, send)
            return

        try:
            await self._apply_rate_limits(scope, receive, send, request, redis)
        except Exception:
            # Redis went away mid-request — fail open.
            logger.warning("Rate limiter Redis error during check — allowing request through")
            self._redis = None  # Reset so next request retries connection
            await self.app(scope, receive, send)

    async def _apply_rate_limits(
        self, scope: Scope, receive: Receive, send: Send, request: Request, redis: Redis,
    ) -> None:
        """Apply all rate limit checks. Raises on Redis errors so caller can fail open."""

        now = time.time()
        path = request.url.path

        # --- Password reset per-IP limit (strictest: 5/min) ---
        if path in _PASSWORD_RESET_PATHS:
            client_ip = request.client.host if request.client else "unknown"
            key = f"rl:pwreset:ip:{client_ip}"
            allowed, retry_after = await _check_rate_limit(redis, key, _PASSWORD_RESET_LIMIT, now)
            if not allowed:
                response = JSONResponse(
                    status_code=429,
                    content={"detail": "Too many password reset requests — try again later"},
                    headers={"Retry-After": str(retry_after)},
                )
                await response(scope, receive, send)
                return

        # --- Auth-endpoint per-IP limit (skip public read-only endpoints) ---
        if is_auth_endpoint(path) and path not in _PUBLIC_READ_ONLY_PATHS:
            client_ip = request.client.host if request.client else "unknown"
            key = f"rl:auth:ip:{client_ip}"
            allowed, retry_after = await _check_rate_limit(
                redis, key, settings.rate_limit_auth_per_ip_per_minute, now,
            )
            if not allowed:
                response = JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests — try again later"},
                    headers={"Retry-After": str(retry_after)},
                )
                await response(scope, receive, send)
                return

        # --- Per-user limit ---
        user_id: str | None = getattr(request.state, "user_id", None)
        if user_id:
            key = f"rl:user:{user_id}"
            allowed, retry_after = await _check_rate_limit(
                redis, key, settings.rate_limit_per_user_per_minute, now,
            )
            if not allowed:
                response = JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests — try again later"},
                    headers={"Retry-After": str(retry_after)},
                )
                await response(scope, receive, send)
                return

        # --- Per-org limit ---
        org_id: str | None = getattr(request.state, "org_id", None)
        if org_id:
            key = f"rl:org:{org_id}"
            allowed, retry_after = await _check_rate_limit(
                redis, key, settings.rate_limit_per_org_per_minute, now,
            )
            if not allowed:
                response = JSONResponse(
                    status_code=429,
                    content={"detail": "Organisation rate limit exceeded — try again later"},
                    headers={"Retry-After": str(retry_after)},
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)
