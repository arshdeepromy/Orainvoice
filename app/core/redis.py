"""Redis connection pool.

Provides a shared ``redis.asyncio.Redis`` instance backed by a connection
pool.  All application code (rate limiting, caching, Celery broker helpers)
should import ``get_redis`` or ``redis_pool`` from this module.
"""

from __future__ import annotations

import redis.asyncio as aioredis

from app.config import settings

# ---------------------------------------------------------------------------
# Connection pool & client
# ---------------------------------------------------------------------------

redis_pool: aioredis.Redis = aioredis.from_url(
    settings.redis_url,
    decode_responses=True,
    max_connections=50,
)


async def get_redis() -> aioredis.Redis:
    """FastAPI dependency returning the shared Redis client.

    Usage::

        @router.get("/cached")
        async def cached(r: aioredis.Redis = Depends(get_redis)):
            await r.get("key")
    """
    return redis_pool


async def close_redis() -> None:
    """Gracefully close the Redis connection pool (call on app shutdown)."""
    await redis_pool.aclose()
