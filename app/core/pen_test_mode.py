"""Penetration-test diagnostic mode.

When ``PEN_TEST_MODE`` is set, injects diagnostic headers into responses.
**Must NOT be enabled in production.**

Implemented as pure ASGI middleware to avoid request body stream corruption.
"""

from __future__ import annotations

import os
import time

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings

_TRUTHY = {"1", "true", "yes"}


def is_enabled() -> bool:
    """Return True if pen-test mode is active and safe to use."""
    if settings.environment == "production":
        return False
    return os.environ.get("PEN_TEST_MODE", "").lower() in _TRUTHY


class _RequestMetrics:
    """Mutable counters attached to ``request.state`` for the current request."""

    __slots__ = ("sql_query_count", "cache_hits", "cache_misses")

    def __init__(self) -> None:
        self.sql_query_count: int = 0
        self.cache_hits: int = 0
        self.cache_misses: int = 0


def get_metrics(request: Request) -> _RequestMetrics:
    """Return the metrics object for the current request (creates if absent)."""
    metrics: _RequestMetrics | None = getattr(request.state, "_pen_test_metrics", None)
    if metrics is None:
        metrics = _RequestMetrics()
        request.state._pen_test_metrics = metrics
    return metrics


def record_sql_query(request: Request) -> None:
    """Increment the SQL query counter for the current request."""
    if is_enabled():
        get_metrics(request).sql_query_count += 1


def record_cache_hit(request: Request) -> None:
    """Increment the cache-hit counter for the current request."""
    if is_enabled():
        get_metrics(request).cache_hits += 1


def record_cache_miss(request: Request) -> None:
    """Increment the cache-miss counter for the current request."""
    if is_enabled():
        get_metrics(request).cache_misses += 1


class PenTestMiddleware:
    """Inject diagnostic headers when ``PEN_TEST_MODE`` is enabled.

    Pure ASGI implementation — does not wrap the receive channel.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if not is_enabled():
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        request.state._pen_test_metrics = _RequestMetrics()
        start = time.perf_counter()

        async def inject_debug_headers(message):
            if message["type"] == "http.response.start":
                elapsed_ms = (time.perf_counter() - start) * 1000
                metrics = get_metrics(request)
                headers = list(message.get("headers", []))
                headers.append((b"x-debug-sql-queries", str(metrics.sql_query_count).encode()))
                headers.append((b"x-debug-cache-hits", str(metrics.cache_hits).encode()))
                headers.append((b"x-debug-cache-misses", str(metrics.cache_misses).encode()))
                headers.append((b"x-debug-timing-ms", f"{elapsed_ms:.1f}".encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, inject_debug_headers)
