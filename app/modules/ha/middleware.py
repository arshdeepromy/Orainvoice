"""Standby write-protection middleware for HA.

Rejects non-GET/HEAD/OPTIONS requests when the local node is in standby
role, except for HA management endpoints (``/api/v1/ha/*``).

The current node role and peer endpoint are stored as module-level
variables and updated by the HA service via :func:`set_node_role`.

Requirements: 9.1, 9.2, 9.3, 9.4
"""

from __future__ import annotations

import logging

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.modules.ha.utils import should_block_request

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level cache — updated by the HA service at runtime.
# ---------------------------------------------------------------------------

_node_role: str = "standalone"
_peer_endpoint: str | None = None


def set_node_role(role: str, peer_endpoint: str | None = None) -> None:
    """Update the cached node role and peer endpoint.

    Called by the HA service whenever the role changes (configure,
    promote, demote, or startup load from DB).
    """
    global _node_role, _peer_endpoint
    _node_role = role
    _peer_endpoint = peer_endpoint
    logger.info("Node role updated to '%s' (peer: %s)", role, peer_endpoint)


def get_node_role() -> str:
    """Return the current cached node role."""
    return _node_role


def get_peer_endpoint() -> str | None:
    """Return the current cached peer endpoint."""
    return _peer_endpoint


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class StandbyWriteProtectionMiddleware:
    """Reject non-read requests when the node is in standby role.

    Allows:
    - All GET / HEAD / OPTIONS requests (reads)
    - All requests to ``/api/v1/ha/*`` (HA management)
    - All requests when node role is ``'primary'`` or ``'standalone'``
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)

        if should_block_request(request.method, request.url.path, _node_role):
            response = JSONResponse(
                status_code=503,
                content={
                    "detail": (
                        "This node is in standby mode. "
                        "Writes are only accepted on the primary node."
                    ),
                    "node_role": "standby",
                    "primary_endpoint": _peer_endpoint or "",
                },
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
