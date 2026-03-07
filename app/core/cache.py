"""Redis caching utilities for WorkshopPro NZ.

Provides cache get/set/invalidate with configurable TTLs, key generation
helpers, and a decorator for caching service function results.

Cache TTL strategy (Requirement 81.4):
- Vehicle lookups: 24 hours (data changes infrequently, Carjam calls are expensive)
- Service catalogues: 1 hour (org admins may update pricing)
- Session data: 30 minutes (aligned with access token lifecycle)
"""

from __future__ import annotations

import functools
import hashlib
import json
from enum import IntEnum
from typing import Any, Callable

import redis.asyncio as aioredis

from app.core.redis import redis_pool

# ---------------------------------------------------------------------------
# TTL constants (seconds) — Requirement 81.4
# ---------------------------------------------------------------------------


class CacheTTL(IntEnum):
    """Standard TTL values for different data categories."""

    VEHICLE_LOOKUP = 86_400    # 24 hours
    SERVICE_CATALOGUE = 3_600  # 1 hour
    SESSION_DATA = 1_800       # 30 minutes
    DEFAULT = 300              # 5 minutes fallback


# ---------------------------------------------------------------------------
# Key generation helpers
# ---------------------------------------------------------------------------

_KEY_PREFIX = "workshoppro"


def cache_key(namespace: str, *parts: str) -> str:
    """Build a namespaced cache key.

    Example::

        cache_key("vehicle", "ABC123")
        # → "workshoppro:vehicle:ABC123"
    """
    segments = [_KEY_PREFIX, namespace, *parts]
    return ":".join(segments)


def cache_key_hash(namespace: str, *parts: str) -> str:
    """Build a cache key with a hashed suffix for long/complex identifiers.

    Useful when parts may contain special characters or be very long.
    """
    raw = ":".join(parts)
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"{_KEY_PREFIX}:{namespace}:{digest}"


# ---------------------------------------------------------------------------
# Core cache operations
# ---------------------------------------------------------------------------


async def cache_get(key: str) -> Any | None:
    """Retrieve a JSON-deserialised value from Redis, or ``None`` on miss."""
    raw = await redis_pool.get(key)
    if raw is None:
        return None
    return json.loads(raw)


async def cache_set(key: str, value: Any, ttl: int = CacheTTL.DEFAULT) -> None:
    """Store a JSON-serialised value in Redis with the given TTL (seconds)."""
    await redis_pool.set(key, json.dumps(value, default=str), ex=ttl)


async def cache_invalidate(key: str) -> None:
    """Delete a single cache key."""
    await redis_pool.delete(key)


async def cache_invalidate_pattern(pattern: str) -> None:
    """Delete all keys matching a glob *pattern*.

    Example::

        await cache_invalidate_pattern("workshoppro:catalogue:org-123:*")
    """
    cursor: int | str = 0
    while True:
        cursor, keys = await redis_pool.scan(cursor=int(cursor), match=pattern, count=200)
        if keys:
            await redis_pool.delete(*keys)
        if cursor == 0:
            break


# ---------------------------------------------------------------------------
# Convenience helpers for specific data types
# ---------------------------------------------------------------------------


async def get_cached_vehicle(rego: str) -> dict | None:
    """Return cached vehicle data for *rego*, or ``None``."""
    return await cache_get(cache_key("vehicle", rego.upper()))


async def set_cached_vehicle(rego: str, data: dict) -> None:
    """Cache vehicle data with the vehicle-lookup TTL."""
    await cache_set(
        cache_key("vehicle", rego.upper()),
        data,
        ttl=CacheTTL.VEHICLE_LOOKUP,
    )


async def get_cached_catalogue(org_id: str) -> list | None:
    """Return cached service catalogue for an org, or ``None``."""
    return await cache_get(cache_key("catalogue", org_id))


async def set_cached_catalogue(org_id: str, data: list) -> None:
    """Cache service catalogue with the catalogue TTL."""
    await cache_set(
        cache_key("catalogue", org_id),
        data,
        ttl=CacheTTL.SERVICE_CATALOGUE,
    )


async def get_cached_session(session_id: str) -> dict | None:
    """Return cached session data, or ``None``."""
    return await cache_get(cache_key("session", session_id))


async def set_cached_session(session_id: str, data: dict) -> None:
    """Cache session data with the session TTL."""
    await cache_set(
        cache_key("session", session_id),
        data,
        ttl=CacheTTL.SESSION_DATA,
    )


# ---------------------------------------------------------------------------
# Caching decorator
# ---------------------------------------------------------------------------


def cached(
    namespace: str,
    ttl: int = CacheTTL.DEFAULT,
    key_builder: Callable[..., str] | None = None,
):
    """Decorator that caches the return value of an async function.

    Parameters
    ----------
    namespace:
        Cache key namespace (e.g. ``"vehicle"``, ``"catalogue"``).
    ttl:
        Time-to-live in seconds.
    key_builder:
        Optional callable ``(*args, **kwargs) -> str`` that produces the
        variable part of the cache key.  When omitted the positional args
        are joined with ``:``.

    Usage::

        @cached("vehicle", ttl=CacheTTL.VEHICLE_LOOKUP)
        async def lookup_vehicle(rego: str) -> dict:
            ...
    """

    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            if key_builder is not None:
                parts = key_builder(*args, **kwargs)
            else:
                parts = ":".join(str(a) for a in args)
            key = cache_key(namespace, parts)

            hit = await cache_get(key)
            if hit is not None:
                return hit

            result = await fn(*args, **kwargs)
            if result is not None:
                await cache_set(key, result, ttl=ttl)
            return result

        return wrapper

    return decorator
