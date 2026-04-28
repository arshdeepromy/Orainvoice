"""Lightweight helper for writing events to the ``ha_event_log`` table.

All writes are non-blocking — failures are caught and logged to stderr
so that the heartbeat loop, role transitions, and other HA operations
are never disrupted by event-log issues.

The function uses its own short-lived session via ``async_session_factory()``
(not the request session) so it can safely be called from background tasks
without transaction conflicts.

Requirements: 34.10
"""

from __future__ import annotations

import logging
import socket
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def log_ha_event(
    event_type: str,
    severity: str,  # 'info' | 'warning' | 'error' | 'critical'
    message: str,
    details: dict | None = None,
    node_name: str | None = None,
) -> None:
    """Write an event to ``ha_event_log``.  Non-blocking — never raises.

    Parameters
    ----------
    event_type:
        Short classification string, e.g. ``'heartbeat_failure'``,
        ``'role_change'``, ``'replication_error'``, ``'split_brain'``,
        ``'auto_promote'``, ``'volume_sync_error'``, ``'config_change'``,
        ``'recovery'``.
    severity:
        One of ``'info'``, ``'warning'``, ``'error'``, ``'critical'``.
    message:
        Human-readable description of the event.
    details:
        Optional structured payload (stack traces, peer response, lag
        values, etc.).  Stored as JSONB.
    node_name:
        Which node logged the event.  When ``None``, the function reads
        the node name from ``ha_config``; if that is unavailable it falls
        back to the machine hostname.
    """
    try:
        from app.core.database import async_session_factory
        from app.modules.ha.models import HAEventLog, HAConfig
        from sqlalchemy import select

        resolved_node_name = node_name

        async with async_session_factory() as session:
            async with session.begin():
                # Resolve node_name if not provided
                if resolved_node_name is None:
                    try:
                        result = await session.execute(
                            select(HAConfig.node_name).limit(1)
                        )
                        resolved_node_name = result.scalar_one_or_none()
                    except Exception:
                        pass  # DB lookup failed — fall through to hostname

                if not resolved_node_name:
                    resolved_node_name = socket.gethostname()

                event = HAEventLog(
                    id=uuid.uuid4(),
                    timestamp=datetime.now(timezone.utc),
                    event_type=event_type,
                    severity=severity,
                    message=message,
                    details=details,
                    node_name=resolved_node_name,
                )
                session.add(event)
    except Exception as exc:
        logger.error("Failed to write HA event: %s", exc)
