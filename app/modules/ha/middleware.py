"""Standby write-protection middleware for HA.

Rejects non-GET/HEAD/OPTIONS requests when the local node is in standby
role, except for HA management endpoints (``/api/v1/ha/*``).

WebSocket connections on non-allowlisted paths are closed with code 1013
(Try Again Later) when the node is in standby or split-brain-blocked mode.

The current node role and peer endpoint are stored as module-level
variables and updated by the HA service via :func:`set_node_role`.

Requirements: 9.1, 9.2, 9.3, 9.4, 13.1, 13.2, 13.3
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
_split_brain_blocked: bool = False


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


def set_split_brain_blocked(blocked: bool) -> None:
    """Update the split-brain write-blocking flag.

    Called by the HeartbeatService when split-brain is detected and the
    local node is the stale primary, or when split-brain resolves.

    Requirements: 8.1, 8.5
    """
    global _split_brain_blocked
    _split_brain_blocked = blocked
    if blocked:
        logger.warning("Split-brain write protection ACTIVATED — writes blocked")
    else:
        logger.info("Split-brain write protection deactivated")


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class StandbyWriteProtectionMiddleware:
    """Reject non-read requests when the node is in standby role.

    Allows:
    - All GET / HEAD / OPTIONS requests (reads)
    - All requests to ``/api/v1/ha/*`` (HA management)
    - All requests when node role is ``'primary'`` or ``'standalone'``

    WebSocket connections are also checked: non-allowlisted paths are
    closed with code 1013 (Try Again Later) on standby/split-brain nodes.
    The kitchen display WebSocket (``/ws/kitchen/``) is explicitly allowed
    because it is read-only (Redis pub/sub subscriber only).
    """

    # WebSocket paths allowed on standby nodes (read-only or HA management).
    _WS_ALLOWED_PREFIXES: tuple[str, ...] = ("/ws/kitchen/", "/api/v1/ha/")

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope_type = scope["type"]

        # --- WebSocket write protection ---
        if scope_type == "websocket":
            if _node_role == "standby" or _split_brain_blocked:
                path = scope.get("path", "")
                if not any(path.startswith(p) for p in self._WS_ALLOWED_PREFIXES):
                    await send({
                        "type": "websocket.close",
                        "code": 1013,  # Try Again Later
                        "reason": "This node is in standby mode. Writes not accepted.",
                    })
                    return
            await self.app(scope, receive, send)
            return

        if scope_type != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)

        if should_block_request(
            request.method,
            request.url.path,
            _node_role,
            is_split_brain_blocked=_split_brain_blocked,
        ):
            # Determine the appropriate error message
            if _split_brain_blocked:
                detail = (
                    "Split-brain detected: this node may be a stale primary. "
                    "Writes are blocked until the conflict is resolved."
                )
                node_role_label = "split-brain-blocked"
            else:
                detail = (
                    "This node is in standby mode. "
                    "Writes are only accepted on the primary node."
                )
                node_role_label = "standby"

            response = JSONResponse(
                status_code=503,
                content={
                    "detail": detail,
                    "node_role": node_role_label,
                    "primary_endpoint": _peer_endpoint or "",
                },
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
