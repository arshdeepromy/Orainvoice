"""Redis pub/sub helpers for kitchen display real-time updates.

Provides ``publish_kitchen_event`` to broadcast order changes to
connected WebSocket clients.

**Validates: Requirement — Kitchen Display Module — Task 32.5**
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

_redis_client: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Return a shared async Redis client (lazy-initialised)."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=False,
        )
    return _redis_client


def _channel_name(org_id: str, station: str) -> str:
    return f"kitchen:{org_id}:{station}"


async def publish_kitchen_event(
    org_id: str,
    station: str,
    event_type: str,
    data: dict[str, Any],
) -> None:
    """Publish a kitchen event to the station-specific channel.

    Also publishes to the ``all`` channel so displays monitoring
    all stations receive the update.
    """
    redis = await get_redis()
    payload = json.dumps({"event": event_type, "station": station, **data})
    channel = _channel_name(org_id, station)
    all_channel = _channel_name(org_id, "all")
    await redis.publish(channel, payload)
    if station != "all":
        await redis.publish(all_channel, payload)
