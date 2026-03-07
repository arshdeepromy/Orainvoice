"""Performance configuration and monitoring utilities.

Centralises performance-related constants, connection pool settings, and
response-time tracking helpers referenced by Requirement 81.

Performance targets:
- Page render: < 2 seconds (Req 81.1)
- API response (standard CRUD): < 200 ms (Req 81.2)
- Concurrent users: ≥ 500 (Req 81.3)
"""

from __future__ import annotations

import time
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Performance targets (Requirement 81.1, 81.2, 81.3)
# ---------------------------------------------------------------------------

PAGE_RENDER_TARGET_MS: int = 2_000
"""Maximum acceptable page render time in milliseconds (Req 81.1)."""

API_RESPONSE_TARGET_MS: int = 200
"""Maximum acceptable API response time for standard CRUD in ms (Req 81.2)."""

CONCURRENT_USERS_TARGET: int = 500
"""Minimum concurrent users the platform must support (Req 81.3)."""

# ---------------------------------------------------------------------------
# Database connection pool configuration (Requirement 81.5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DBPoolConfig:
    """Database connection pool settings.

    These values are tuned for ≥ 500 concurrent users across multiple
    Uvicorn workers.  Each worker gets its own pool, so the effective
    total connections = pool_size × worker_count + max_overflow × worker_count.
    """

    pool_size: int = 20
    """Steady-state connections per worker."""

    max_overflow: int = 10
    """Extra connections allowed above pool_size under burst load."""

    pool_pre_ping: bool = True
    """Verify connections are alive before checkout (avoids stale conns)."""

    pool_recycle_seconds: int = 1_800
    """Recycle connections after 30 minutes to avoid server-side timeouts."""

    pool_timeout_seconds: int = 30
    """Seconds to wait for a connection from the pool before raising."""


DB_POOL_CONFIG = DBPoolConfig()

# ---------------------------------------------------------------------------
# Redis connection pool configuration (Requirement 81.4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RedisPoolConfig:
    """Redis connection pool settings."""

    max_connections: int = 50
    """Max connections in the shared Redis pool."""

    socket_timeout_seconds: float = 5.0
    """Timeout for individual Redis commands."""

    socket_connect_timeout_seconds: float = 2.0
    """Timeout for establishing a new Redis connection."""


REDIS_POOL_CONFIG = RedisPoolConfig()

# ---------------------------------------------------------------------------
# Concurrency / worker configuration (Requirement 81.3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConcurrencyConfig:
    """Uvicorn / Gunicorn worker configuration for 500+ concurrent users.

    Recommended deployment: Gunicorn with Uvicorn workers behind a load
    balancer.  ``worker_count`` should be tuned to the number of CPU cores.
    """

    worker_count: int = 4
    """Number of Uvicorn worker processes (rule of thumb: 2 × CPU cores)."""

    worker_connections: int = 1_000
    """Max simultaneous connections per worker (async, so this is high)."""

    keepalive_seconds: int = 5
    """HTTP keep-alive timeout between requests."""

    graceful_timeout_seconds: int = 30
    """Seconds to wait for in-flight requests during shutdown."""

    max_requests_per_worker: int = 10_000
    """Restart worker after N requests to prevent memory leaks."""

    max_requests_jitter: int = 1_000
    """Random jitter added to max_requests to stagger restarts."""


CONCURRENCY_CONFIG = ConcurrencyConfig()

# ---------------------------------------------------------------------------
# Response time tracking utility
# ---------------------------------------------------------------------------


class ResponseTimer:
    """Simple context-manager for measuring elapsed time.

    Usage::

        timer = ResponseTimer()
        with timer:
            await do_work()
        print(timer.elapsed_ms)
    """

    def __init__(self) -> None:
        self._start: float = 0.0
        self._end: float = 0.0

    def __enter__(self) -> "ResponseTimer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc) -> None:
        self._end = time.perf_counter()

    @property
    def elapsed_ms(self) -> float:
        """Elapsed time in milliseconds."""
        return (self._end - self._start) * 1_000

    def within_target(self, target_ms: int | None = None) -> bool:
        """Return ``True`` if elapsed time is within the given target."""
        target = target_ms if target_ms is not None else API_RESPONSE_TARGET_MS
        return self.elapsed_ms <= target
