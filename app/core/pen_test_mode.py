"""Penetration-test diagnostic mode.

When the ``PEN_TEST_MODE`` environment variable is set to a truthy value
(``"1"``, ``"true"``, ``"yes"``), this middleware injects diagnostic headers
into every HTTP response:

  • ``X-Debug-SQL-Queries``   — number of SQL queries executed
  • ``X-Debug-Cache-Hits``    — Redis cache hit count
  • ``X-Debug-Cache-Misses``  — Redis cache miss count
  • ``X-Debug-Timing-Ms``     — total request processing time in ms

These headers help penetration testers identify N+1 queries, cache
inefficiencies, and slow endpoints without access to server logs.

**This middleware MUST NOT be enabled in production.**  The ``is_enabled()``
check rejects ``environment == "production"`` even if the env var is set.
"""

from __future__ import annotations

import os
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

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


class PenTestMiddleware(BaseHTTPMiddleware):
    """Inject diagnostic headers when ``PEN_TEST_MODE`` is enabled."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if not is_enabled():
            return await call_next(request)

        # Initialise metrics and start timer.
        request.state._pen_test_metrics = _RequestMetrics()
        start = time.perf_counter()

        response: Response = await call_next(request)

        elapsed_ms = (time.perf_counter() - start) * 1000
        metrics = get_metrics(request)

        response.headers["X-Debug-SQL-Queries"] = str(metrics.sql_query_count)
        response.headers["X-Debug-Cache-Hits"] = str(metrics.cache_hits)
        response.headers["X-Debug-Cache-Misses"] = str(metrics.cache_misses)
        response.headers["X-Debug-Timing-Ms"] = f"{elapsed_ms:.1f}"

        return response
