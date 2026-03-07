"""WebSocket endpoint for real-time kitchen display updates via Redis pub/sub.

Channel pattern: ``kitchen:{org_id}:{station}``
A special ``all`` station subscribes to all stations for an org.

**Validates: Requirement — Kitchen Display Module — Task 32.5**
"""

from __future__ import annotations

import asyncio
import json
import logging
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.modules.kitchen_display.redis_pubsub import (
    get_redis,
    publish_kitchen_event,
)

logger = logging.getLogger(__name__)

ws_router = APIRouter()


def _channel_name(org_id: str, station: str) -> str:
    return f"kitchen:{org_id}:{station}"


@ws_router.websocket("/ws/kitchen/{org_id}/{station}")
async def kitchen_ws(websocket: WebSocket, org_id: str, station: str):
    """WebSocket endpoint for kitchen display real-time updates.

    Subscribes to Redis pub/sub channel ``kitchen:{org_id}:{station}``.
    Also subscribes to ``kitchen:{org_id}:all`` for broadcast messages.
    """
    await websocket.accept()

    redis = await get_redis()
    pubsub = redis.pubsub()

    channels = [_channel_name(org_id, station)]
    if station != "all":
        channels.append(_channel_name(org_id, "all"))

    await pubsub.subscribe(*channels)

    try:
        while True:
            # Listen for Redis messages with a short timeout so we can
            # also detect client disconnects.
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=0.5,
            )
            if message and message["type"] == "message":
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                await websocket.send_text(data)

            # Small sleep to avoid busy-loop
            await asyncio.sleep(0.05)
    except WebSocketDisconnect:
        logger.info("Kitchen WS client disconnected: org=%s station=%s", org_id, station)
    except Exception:
        logger.exception("Kitchen WS error: org=%s station=%s", org_id, station)
    finally:
        await pubsub.unsubscribe(*channels)
        await pubsub.close()
