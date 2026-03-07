"""Integration tests for the dead letter queue service.

**Validates: Requirement 10.4**

Tests:
- 10.7: Dead letter queue retries failed tasks up to 3 times with
  exponential backoff (1 min → 5 min → 25 min), then marks as failed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.dead_letter import DeadLetterService, _BACKOFF_MINUTES, _next_retry_at
from app.models.dead_letter import DeadLetterTask


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(
    retry_count: int = 0,
    max_retries: int = 3,
    status: str = "pending",
    task_name: str = "send_notification",
    task_args: dict | None = None,
    created_minutes_ago: int = 0,
) -> DeadLetterTask:
    """Build a DeadLetterTask instance for testing."""
    now = datetime.now(timezone.utc)
    task = DeadLetterTask()
    task.id = uuid.uuid4()
    task.task_name = task_name
    task.task_args = task_args or {"email": "test@example.com"}
    task.error_message = "Connection refused"
    task.retry_count = retry_count
    task.max_retries = max_retries
    task.status = status
    task.next_retry_at = _next_retry_at(retry_count)
    task.created_at = now - timedelta(minutes=created_minutes_ago)
    task.updated_at = now
    return task


# ===========================================================================
# 10.7: Dead letter queue retries with exponential backoff
# ===========================================================================


class TestDeadLetterQueueRetries:
    """Verify retry behaviour and exponential backoff schedule."""

    def test_backoff_schedule_is_1_5_25_minutes(self) -> None:
        """The backoff schedule should be 1, 5, 25 minutes."""
        assert _BACKOFF_MINUTES == [1, 5, 25]

    def test_next_retry_at_first_attempt(self) -> None:
        """First retry (count=0) should be ~1 minute from now."""
        before = datetime.now(timezone.utc)
        result = _next_retry_at(0)
        after = datetime.now(timezone.utc)

        expected_min = before + timedelta(minutes=1)
        expected_max = after + timedelta(minutes=1)
        assert expected_min <= result <= expected_max

    def test_next_retry_at_second_attempt(self) -> None:
        """Second retry (count=1) should be ~5 minutes from now."""
        before = datetime.now(timezone.utc)
        result = _next_retry_at(1)
        after = datetime.now(timezone.utc)

        expected_min = before + timedelta(minutes=5)
        expected_max = after + timedelta(minutes=5)
        assert expected_min <= result <= expected_max

    def test_next_retry_at_third_attempt(self) -> None:
        """Third retry (count=2) should be ~25 minutes from now."""
        before = datetime.now(timezone.utc)
        result = _next_retry_at(2)
        after = datetime.now(timezone.utc)

        expected_min = before + timedelta(minutes=25)
        expected_max = after + timedelta(minutes=25)
        assert expected_min <= result <= expected_max

    def test_next_retry_at_beyond_schedule_uses_last(self) -> None:
        """Retry count beyond schedule length uses the last backoff value."""
        before = datetime.now(timezone.utc)
        result = _next_retry_at(10)
        after = datetime.now(timezone.utc)

        expected_min = before + timedelta(minutes=25)
        expected_max = after + timedelta(minutes=25)
        assert expected_min <= result <= expected_max

    @pytest.mark.asyncio
    async def test_retry_increments_count_on_failure(self) -> None:
        """Each failed retry increments retry_count."""
        task = _make_task(retry_count=0, max_retries=3)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.flush = AsyncMock()

        failing_executor = AsyncMock(side_effect=RuntimeError("still broken"))

        svc = DeadLetterService(session=mock_session)
        result = await svc.retry_task(task.id, executor=failing_executor)

        assert result is not None
        assert result.retry_count == 1
        assert result.status == "pending"  # Still retryable
        assert result.next_retry_at is not None

    @pytest.mark.asyncio
    async def test_retry_marks_failed_after_max_retries(self) -> None:
        """After max_retries, the task is marked as 'failed'."""
        task = _make_task(retry_count=2, max_retries=3)  # Next retry will be #3

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.flush = AsyncMock()

        failing_executor = AsyncMock(side_effect=RuntimeError("still broken"))

        svc = DeadLetterService(session=mock_session)
        result = await svc.retry_task(task.id, executor=failing_executor)

        assert result is not None
        assert result.retry_count == 3
        assert result.status == "failed"
        assert result.next_retry_at is None

    @pytest.mark.asyncio
    async def test_retry_marks_completed_on_success(self) -> None:
        """A successful retry marks the task as 'completed'."""
        task = _make_task(retry_count=1, max_retries=3)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.flush = AsyncMock()

        success_executor = AsyncMock(return_value=None)

        svc = DeadLetterService(session=mock_session)
        result = await svc.retry_task(task.id, executor=success_executor)

        assert result is not None
        assert result.status == "completed"
        assert result.error_message is None

    @pytest.mark.asyncio
    async def test_three_retries_then_failed(self) -> None:
        """Simulate 3 consecutive failed retries → task ends up 'failed'."""
        task = _make_task(retry_count=0, max_retries=3)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.flush = AsyncMock()

        failing_executor = AsyncMock(side_effect=RuntimeError("nope"))

        svc = DeadLetterService(session=mock_session)

        # Retry 1
        result = await svc.retry_task(task.id, executor=failing_executor)
        assert result.retry_count == 1
        assert result.status == "pending"

        # Retry 2
        result = await svc.retry_task(task.id, executor=failing_executor)
        assert result.retry_count == 2
        assert result.status == "pending"

        # Retry 3 — should be marked failed
        result = await svc.retry_task(task.id, executor=failing_executor)
        assert result.retry_count == 3
        assert result.status == "failed"
        assert result.next_retry_at is None

    @pytest.mark.asyncio
    async def test_retry_nonexistent_task_returns_none(self) -> None:
        """Retrying a non-existent task returns None."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        svc = DeadLetterService(session=mock_session)
        result = await svc.retry_task(uuid.uuid4())

        assert result is None
