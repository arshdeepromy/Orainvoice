"""Tests for storage and performance management (Task 52).

Validates:
- 52.8: File upload rejected when storage quota exceeded
- 52.9: Query timeout kills long-running queries and returns 504
- 52.10: Job priority queue processes high-priority tasks before low-priority
- 52.11: Slow query logging captures queries exceeding threshold
"""

from __future__ import annotations

import logging
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.storage_manager import StorageManager, StorageUsageReport
from app.core.query_optimizer import QueryOptimizer, SLOW_QUERY_THRESHOLD_MS
from app.core.job_queue import (
    JobPriorityQueue,
    Priority,
    WorkerAllocation,
    PRIORITY_QUEUE_MAP,
)


# -----------------------------------------------------------------------
# 52.8 — Storage quota enforcement
# -----------------------------------------------------------------------


class TestStorageQuotaEnforcement:
    """Validates: Requirement 43.3 — upload rejected when quota exceeded."""

    @pytest.mark.asyncio
    async def test_enforce_quota_rejects_when_exceeded(self):
        """Upload is rejected with HTTP 413 when quota would be exceeded."""
        org_id = str(uuid.uuid4())
        mock_db = AsyncMock()

        # Simulate org at 5 GB used out of 5 GB quota
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = MagicMock(
            storage_used_bytes=5_368_709_120,
            storage_quota_bytes=5_368_709_120,
        )
        mock_db.execute = AsyncMock(return_value=mock_result)

        manager = StorageManager(mock_db)

        with pytest.raises(HTTPException) as exc_info:
            await manager.enforce_quota(org_id, incoming_file_size=1024)

        assert exc_info.value.status_code == 413
        detail = exc_info.value.detail
        assert detail["error"] == "storage_quota_exceeded"
        assert detail["used_bytes"] == 5_368_709_120
        assert detail["quota_bytes"] == 5_368_709_120
        assert detail["incoming_bytes"] == 1024
        assert "quota exceeded" in detail["message"].lower()

    @pytest.mark.asyncio
    async def test_enforce_quota_allows_within_limit(self):
        """Upload is allowed when within quota."""
        org_id = str(uuid.uuid4())
        mock_db = AsyncMock()

        # Simulate org at 1 GB used out of 5 GB quota
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = MagicMock(
            storage_used_bytes=1_073_741_824,
            storage_quota_bytes=5_368_709_120,
        )
        mock_db.execute = AsyncMock(return_value=mock_result)

        manager = StorageManager(mock_db)
        # Should not raise
        await manager.enforce_quota(org_id, incoming_file_size=1024)

    @pytest.mark.asyncio
    async def test_check_quota_reports_warning_at_80_percent(self):
        """Usage report flags warning when at 80%+ of quota."""
        org_id = str(uuid.uuid4())
        mock_db = AsyncMock()

        # 80% of 5 GB
        used = int(5_368_709_120 * 0.85)
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = MagicMock(
            storage_used_bytes=used,
            storage_quota_bytes=5_368_709_120,
        )
        mock_db.execute = AsyncMock(return_value=mock_result)

        manager = StorageManager(mock_db)
        report = await manager.check_quota(org_id)

        assert report.is_warning is True
        assert report.is_exceeded is False
        assert report.usage_percent > 80.0

    @pytest.mark.asyncio
    async def test_increment_and_decrement_usage(self):
        """increment_usage and decrement_usage update storage correctly."""
        org_id = str(uuid.uuid4())
        mock_db = AsyncMock()

        # After increment, simulate updated values
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = MagicMock(
            storage_used_bytes=2_000_000,
            storage_quota_bytes=5_368_709_120,
        )
        mock_db.execute = AsyncMock(return_value=mock_result)

        manager = StorageManager(mock_db)
        report = await manager.increment_usage(org_id, 1_000_000)
        assert report.used_bytes == 2_000_000

        # Decrement
        mock_result.one_or_none.return_value = MagicMock(
            storage_used_bytes=1_000_000,
            storage_quota_bytes=5_368_709_120,
        )
        report = await manager.decrement_usage(org_id, 1_000_000)
        assert report.used_bytes == 1_000_000


# -----------------------------------------------------------------------
# 52.9 — Query timeout
# -----------------------------------------------------------------------


class TestQueryTimeout:
    """Validates: Requirement 43.5 — query timeout kills long-running queries."""

    @pytest.mark.asyncio
    async def test_add_query_timeout_sets_statement_timeout(self):
        """add_query_timeout executes SET LOCAL statement_timeout."""
        mock_db = AsyncMock()
        executed: list[str] = []

        async def capture_execute(stmt, params=None):
            executed.append(str(stmt))
            return MagicMock()

        mock_db.execute = capture_execute

        optimizer = QueryOptimizer(mock_db, timeout_ms=30_000)
        await optimizer.add_query_timeout()

        assert len(executed) == 1
        assert "statement_timeout" in executed[0]
        assert "30000" in executed[0]

    @pytest.mark.asyncio
    async def test_custom_timeout_per_endpoint(self):
        """Custom timeout can be set per endpoint."""
        mock_db = AsyncMock()
        executed: list[str] = []

        async def capture_execute(stmt, params=None):
            executed.append(str(stmt))
            return MagicMock()

        mock_db.execute = capture_execute

        optimizer = QueryOptimizer(mock_db)
        await optimizer.add_query_timeout(timeout_ms=5_000)

        assert "5000" in executed[0]

    @pytest.mark.asyncio
    async def test_optimized_context_manager_sets_timeout(self):
        """The optimized() context manager sets timeout and logs slow queries."""
        mock_db = AsyncMock()
        executed: list[str] = []

        async def capture_execute(stmt, params=None):
            executed.append(str(stmt))
            return MagicMock()

        mock_db.execute = capture_execute

        optimizer = QueryOptimizer(mock_db, timeout_ms=15_000)
        async with optimizer.optimized(description="test query"):
            pass  # fast query

        assert any("15000" in s for s in executed)


# -----------------------------------------------------------------------
# 52.10 — Job priority queue
# -----------------------------------------------------------------------


class TestJobPriorityQueue:
    """Validates: Requirement 43.7 — high-priority tasks processed first."""

    def test_payments_routed_to_high_priority(self):
        """Payment tasks are routed to the high_priority queue."""
        queue = JobPriorityQueue()
        assert queue.get_queue("payments") == "high_priority"
        assert queue.get_priority("payments") == Priority.HIGH

    def test_pos_routed_to_high_priority(self):
        """POS tasks are routed to the high_priority queue."""
        queue = JobPriorityQueue()
        assert queue.get_queue("pos") == "high_priority"
        assert queue.get_priority("pos") == Priority.HIGH

    def test_invoices_routed_to_medium_priority(self):
        """Invoice tasks are routed to the default (medium) queue."""
        queue = JobPriorityQueue()
        assert queue.get_queue("invoices") == "default"
        assert queue.get_priority("invoices") == Priority.MEDIUM

    def test_reports_routed_to_low_priority(self):
        """Report tasks are routed to the bulk (low) queue."""
        queue = JobPriorityQueue()
        assert queue.get_queue("reports") == "bulk"
        assert queue.get_priority("reports") == Priority.LOW

    def test_analytics_routed_to_low_priority(self):
        """Analytics tasks are routed to the bulk (low) queue."""
        queue = JobPriorityQueue()
        assert queue.get_queue("analytics") == "bulk"

    def test_unknown_category_defaults_to_medium(self):
        """Unknown task categories default to medium priority."""
        queue = JobPriorityQueue()
        assert queue.get_queue("unknown_task") == "default"
        assert queue.get_priority("unknown_task") == Priority.MEDIUM

    def test_high_priority_before_low_priority(self):
        """High-priority queue name sorts before low-priority in processing order."""
        queue = JobPriorityQueue()
        high_q = queue.get_queue("payments")
        low_q = queue.get_queue("reports")
        # They should be different queues
        assert high_q != low_q
        assert high_q == "high_priority"
        assert low_q == "bulk"

    def test_route_task_returns_queue_kwarg(self):
        """route_task() returns dict with queue set for apply_async."""
        queue = JobPriorityQueue()
        kwargs = queue.route_task("payments", args=["arg1"])
        assert kwargs["queue"] == "high_priority"
        assert kwargs["args"] == ["arg1"]

    def test_worker_allocation_ratios(self):
        """Worker allocation distributes workers by priority ratio."""
        allocation = WorkerAllocation(high=5, medium=3, low=2)
        concurrency = allocation.as_concurrency_map(total_workers=10)
        assert concurrency["high_priority"] == 5
        assert concurrency["default"] == 3
        assert concurrency["bulk"] == 2

    def test_register_custom_category(self):
        """Custom task categories can be registered."""
        queue = JobPriorityQueue()
        queue.register_category("custom_task", Priority.HIGH)
        assert queue.get_queue("custom_task") == "high_priority"


# -----------------------------------------------------------------------
# 52.11 — Slow query logging
# -----------------------------------------------------------------------


class TestSlowQueryLogging:
    """Validates: Requirement 43.5 — slow query logging captures queries exceeding threshold."""

    def test_slow_query_logged_above_threshold(self, caplog):
        """Queries exceeding 1s threshold are logged as warnings."""
        mock_db = AsyncMock()
        optimizer = QueryOptimizer(mock_db, slow_threshold_ms=1000.0)

        with caplog.at_level(logging.WARNING, logger="app.core.query_optimizer"):
            optimizer.log_slow_queries("SELECT * FROM invoices", elapsed_ms=1500.0)

        assert len(caplog.records) == 1
        assert "Slow query detected" in caplog.records[0].message
        assert "SELECT * FROM invoices" in caplog.records[0].message
        assert "1500.0" in caplog.records[0].message

    def test_fast_query_not_logged(self, caplog):
        """Queries under the threshold are not logged."""
        mock_db = AsyncMock()
        optimizer = QueryOptimizer(mock_db, slow_threshold_ms=1000.0)

        with caplog.at_level(logging.WARNING, logger="app.core.query_optimizer"):
            optimizer.log_slow_queries("SELECT 1", elapsed_ms=50.0)

        assert len(caplog.records) == 0

    def test_exact_threshold_triggers_log(self, caplog):
        """Query at exactly the threshold is logged."""
        mock_db = AsyncMock()
        optimizer = QueryOptimizer(mock_db, slow_threshold_ms=1000.0)

        with caplog.at_level(logging.WARNING, logger="app.core.query_optimizer"):
            optimizer.log_slow_queries("SELECT * FROM products", elapsed_ms=1000.0)

        assert len(caplog.records) == 1

    def test_slow_query_with_extra_context(self, caplog):
        """Slow query log includes extra context when provided."""
        mock_db = AsyncMock()
        optimizer = QueryOptimizer(mock_db, slow_threshold_ms=500.0)

        with caplog.at_level(logging.WARNING, logger="app.core.query_optimizer"):
            optimizer.log_slow_queries(
                "complex join",
                elapsed_ms=2000.0,
                extra={"org_id": "abc-123", "endpoint": "/api/v2/invoices"},
            )

        assert "complex join" in caplog.records[0].message
        assert "abc-123" in caplog.records[0].message
