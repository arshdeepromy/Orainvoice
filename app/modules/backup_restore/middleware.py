"""Restore-maintenance gate middleware.

While ``backup_config.restore_maintenance_active`` is set, the full-restore flow
needs to quiesce normal application traffic before its destructive
``pg_restore --clean`` apply. This net-new ASGI middleware — registered alongside
:class:`StandbyWriteProtectionMiddleware` — reads that DB-backed flag and:

- returns **HTTP 503** with a maintenance body for every request *except*
  Global-Admin requests (so the admin can keep monitoring / cancelling the
  restore) and health/liveness requests (so orchestration probes keep working);
- maintains a per-process **active-request counter** of in-flight non-exempt
  requests so the full-restore ``MaintenanceController`` can **drain** them (wait
  for the counter to reach zero, up to a bounded grace) before the destructive
  apply begins.

The 10-second "maintenance could not be enabled" abort deadline itself is
enforced by the full-restore ``MaintenanceController`` (see
``restore/full_restore.py``); this middleware provides the request gate and the
drain counter it relies on.

The flag is read from the DB rather than an in-process variable because the
Docker-Compose topology runs multiple workers and a DB-backed flag is read
consistently by every worker (design "Maintenance mode enforcement"). To keep
per-request latency low the read is cached for a short TTL; an explicit
:func:`prime_maintenance_active` lets the worker performing the restore flip its
own cache immediately for instant local gating.

Requirements: 12.1, 12.2
"""

from __future__ import annotations

import logging
import time

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

#: How long a DB read of ``restore_maintenance_active`` is cached before being
#: re-read. Trades a few seconds of per-worker staleness for avoiding a DB hit
#: on every request. A restore holds maintenance for far longer than this, so
#: the gate still engages promptly.
FLAG_CACHE_TTL_SECONDS: float = 2.0

#: Paths that must keep responding during maintenance (orchestration / probes).
_HEALTH_PATHS: frozenset[str] = frozenset({"/health"})

#: The role that is allowed through the gate so the admin can monitor / cancel.
_GLOBAL_ADMIN_ROLE = "global_admin"

# ---------------------------------------------------------------------------
# Module-level state (per worker process)
# ---------------------------------------------------------------------------

# Short-TTL cache of the DB-backed flag.
_flag_value: bool = False
_flag_read_at: float = 0.0

# Count of in-flight non-exempt requests currently being served. The event loop
# is single-threaded so plain int read-modify-write between awaits is safe.
_active_requests: int = 0


def prime_maintenance_active(active: bool) -> None:
    """Set this worker's cached maintenance flag immediately.

    Lets the worker that is performing the restore gate traffic without waiting
    for the cache TTL to expire. Other workers pick the change up from the DB on
    their next refresh. Also used by tests to drive the gate deterministically.
    """
    global _flag_value, _flag_read_at
    _flag_value = active
    _flag_read_at = time.monotonic()


def reset_flag_cache() -> None:
    """Forget the cached flag so the next check re-reads the DB (test helper)."""
    global _flag_read_at
    _flag_read_at = 0.0


def get_active_request_count() -> int:
    """Return the number of in-flight non-exempt requests on this worker."""
    return _active_requests


async def is_maintenance_active() -> bool:
    """Return whether restore maintenance is active, using a short-TTL cache.

    Reads ``backup_config.restore_maintenance_active`` from the DB. On any read
    error it **fails open** (returns ``False``) so a transient DB hiccup can
    never take the whole platform offline — the restore controller cannot make
    progress without the DB anyway, so there is nothing to gate for.
    """
    global _flag_value, _flag_read_at
    now = time.monotonic()
    if now - _flag_read_at < FLAG_CACHE_TTL_SECONDS:
        return _flag_value

    try:
        from sqlalchemy import select

        from app.core.database import async_session_factory
        from app.modules.backup_restore.models import BackupConfig

        async with async_session_factory() as session:
            result = await session.execute(
                select(BackupConfig.restore_maintenance_active).limit(1)
            )
            value = result.scalars().first()
        _flag_value = bool(value)
    except Exception:  # noqa: BLE001 - fail open on read failure (see docstring)
        logger.warning(
            "Could not read restore_maintenance_active; assuming maintenance "
            "is inactive so traffic is not blocked",
            exc_info=True,
        )
        _flag_value = False
    _flag_read_at = now
    return _flag_value


def _is_exempt(request: Request) -> bool:
    """Requests that pass the gate even while maintenance is active.

    Global-Admin requests (so the admin can monitor / cancel the running
    restore) and health/liveness probes.
    """
    if request.url.path in _HEALTH_PATHS:
        return True
    role = getattr(request.state, "role", None)
    return role == _GLOBAL_ADMIN_ROLE


class RestoreMaintenanceMiddleware:
    """Gate + drain counter for full-restore maintenance mode.

    Registered alongside :class:`StandbyWriteProtectionMiddleware`. While
    ``backup_config.restore_maintenance_active`` is set:

    - non-exempt requests receive HTTP 503 (Req 12.1);
    - exempt requests (Global-Admin, health) pass through.

    Independently of the flag, the middleware counts in-flight non-exempt
    requests so the restore controller can drain them before the destructive
    apply.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        exempt = _is_exempt(request)

        if not exempt and await is_maintenance_active():
            response = JSONResponse(
                status_code=503,
                content={
                    "detail": (
                        "The platform is temporarily unavailable while a system "
                        "restore is in progress. Please try again shortly."
                    ),
                    "maintenance": True,
                    "reason": "restore_in_progress",
                },
                headers={"Retry-After": "60"},
            )
            await response(scope, receive, send)
            return

        # Exempt requests are not counted: the admin's monitoring / cancel calls
        # must not hold the drain open indefinitely.
        if exempt:
            await self.app(scope, receive, send)
            return

        global _active_requests
        _active_requests += 1
        try:
            await self.app(scope, receive, send)
        finally:
            _active_requests -= 1


async def wait_for_drain(
    grace_seconds: float,
    poll_interval: float = 0.1,
) -> bool:
    """Wait for in-flight non-exempt requests to finish, up to *grace_seconds*.

    Returns ``True`` if the active-request counter reached zero within the grace
    period, ``False`` if the grace expired with requests still in flight. The
    full-restore ``MaintenanceController`` calls this after enabling maintenance
    and before the destructive ``--clean`` apply (Req 12.1).
    """
    import asyncio

    deadline = time.monotonic() + max(0.0, grace_seconds)
    while _active_requests > 0:
        if time.monotonic() >= deadline:
            logger.warning(
                "Restore-maintenance drain grace (%.1fs) expired with %d "
                "request(s) still in flight",
                grace_seconds,
                _active_requests,
            )
            return False
        await asyncio.sleep(poll_interval)
    return True
