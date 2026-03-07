"""Query optimisation utilities for tenant-safe database access.

Provides QueryOptimizer with configurable row limits, statement timeouts,
and slow-query logging.

Requirements: 43.4, 43.5
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Defaults
DEFAULT_MAX_ROWS: int = 10_000
DEFAULT_QUERY_TIMEOUT_MS: int = 30_000  # 30 seconds
REPORT_QUERY_TIMEOUT_MS: int = 120_000  # 120 seconds for reports
SLOW_QUERY_THRESHOLD_MS: float = 1_000.0  # 1 second


class QueryOptimizer:
    """Applies row limits, statement timeouts, and slow-query logging.

    Usage::

        optimizer = QueryOptimizer(session)
        async with optimizer.optimized(timeout_ms=30000):
            result = await session.execute(stmt.limit(optimizer.row_limit))
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        max_rows: int = DEFAULT_MAX_ROWS,
        timeout_ms: int = DEFAULT_QUERY_TIMEOUT_MS,
        slow_threshold_ms: float = SLOW_QUERY_THRESHOLD_MS,
    ) -> None:
        self._session = session
        self.row_limit = max_rows
        self._timeout_ms = timeout_ms
        self._slow_threshold_ms = slow_threshold_ms

    def add_row_limit(self, max_rows: int | None = None) -> int:
        """Return the effective row limit (configurable, default 10 000).

        Use with ``stmt.limit(optimizer.add_row_limit())``.
        """
        if max_rows is not None:
            self.row_limit = max_rows
        return self.row_limit

    async def add_query_timeout(self, timeout_ms: int | None = None) -> None:
        """Set a PostgreSQL statement_timeout for the current transaction.

        Args:
            timeout_ms: Timeout in milliseconds. Defaults to the instance
                        default (30 000 ms). Use 0 to disable.
        """
        ms = timeout_ms if timeout_ms is not None else self._timeout_ms
        await self._session.execute(
            text(f"SET LOCAL statement_timeout = {int(ms)}")
        )

    def log_slow_queries(
        self,
        query_description: str,
        elapsed_ms: float,
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Log a warning if the query exceeded the slow-query threshold."""
        if elapsed_ms >= self._slow_threshold_ms:
            logger.warning(
                "Slow query detected: %s took %.1f ms (threshold: %.1f ms)%s",
                query_description,
                elapsed_ms,
                self._slow_threshold_ms,
                f" | {extra}" if extra else "",
            )

    @asynccontextmanager
    async def optimized(
        self,
        *,
        timeout_ms: int | None = None,
        description: str = "query",
    ):
        """Context manager that sets timeout and logs slow queries.

        Usage::

            async with optimizer.optimized(description="list invoices"):
                result = await session.execute(stmt)
        """
        await self.add_query_timeout(timeout_ms)
        start = time.monotonic()
        try:
            yield self
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000
            self.log_slow_queries(description, elapsed_ms)

    @asynccontextmanager
    async def report_optimized(self, *, description: str = "report query"):
        """Context manager with extended timeout for report queries (120s)."""
        async with self.optimized(
            timeout_ms=REPORT_QUERY_TIMEOUT_MS,
            description=description,
        ):
            yield self
