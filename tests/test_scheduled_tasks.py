"""Unit tests for scheduled tasks.

Tests the async tasks in ``app/tasks/scheduled.py``:
- check_overdue_invoices_task (Req 19.6)
- retry_failed_notifications_task (Req 37.2)
- archive_error_logs_task (Req 49.7)
- generate_recurring_invoices_task (Req 60.2, 60.4)

Requirements: 19.6, 37.2, 49.7, 60.2, 60.4
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.tasks.scheduled import (
    MAX_NOTIFICATION_RETRIES,
    RETRY_DELAYS,
    ERROR_LOG_RETENTION_MONTHS,
    _get_retry_delay,
    check_overdue_invoices_task,
    retry_failed_notifications_task,
    archive_error_logs_task,
    generate_recurring_invoices_task,
)


class TestConstants:
    def test_max_notification_retries(self):
        assert MAX_NOTIFICATION_RETRIES == 3

    def test_retry_delays(self):
        assert RETRY_DELAYS == (60, 300, 900)

    def test_error_log_retention_months(self):
        assert ERROR_LOG_RETENTION_MONTHS == 12


class TestGetRetryDelay:
    def test_first_retry_60s(self):
        assert _get_retry_delay(0) == 60

    def test_second_retry_300s(self):
        assert _get_retry_delay(1) == 300

    def test_third_retry_900s(self):
        assert _get_retry_delay(2) == 900

    def test_beyond_max_uses_last(self):
        assert _get_retry_delay(10) == 900


class TestCheckOverdueInvoicesTask:
    """Req 19.6: overdue invoice status update."""

    @pytest.mark.asyncio
    async def test_success_returns_count(self):
        with patch("app.tasks.scheduled.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.begin.return_value.__aenter__ = AsyncMock()
            mock_session.begin.return_value.__aexit__ = AsyncMock()
            with patch("app.modules.invoices.service.mark_invoices_overdue", new_callable=AsyncMock, return_value=5):
                result = await check_overdue_invoices_task()
                assert result["invoices_marked_overdue"] == 5

    @pytest.mark.asyncio
    async def test_zero_overdue(self):
        with patch("app.tasks.scheduled.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.begin.return_value.__aenter__ = AsyncMock()
            mock_session.begin.return_value.__aexit__ = AsyncMock()
            with patch("app.modules.invoices.service.mark_invoices_overdue", new_callable=AsyncMock, return_value=0):
                result = await check_overdue_invoices_task()
                assert result["invoices_marked_overdue"] == 0

    @pytest.mark.asyncio
    async def test_exception_returns_error(self):
        with patch("app.tasks.scheduled.async_session_factory", side_effect=RuntimeError("DB down")):
            result = await check_overdue_invoices_task()
            assert "error" in result
            assert "DB down" in result["error"]


class TestRetryFailedNotificationsTask:
    """Req 37.2: retry with exponential backoff."""

    @pytest.mark.asyncio
    async def test_no_pending_returns_zeros(self):
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all.return_value = []
        with patch("app.tasks.scheduled.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.begin.return_value.__aenter__ = AsyncMock()
            mock_session.begin.return_value.__aexit__ = AsyncMock()
            mock_session.execute = AsyncMock(return_value=mock_result)
            result = await retry_failed_notifications_task()
            assert result["retried"] == 0
            assert result["permanently_failed"] == 0
            assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_exception_returns_error(self):
        with patch("app.tasks.scheduled.async_session_factory", side_effect=RuntimeError("Redis down")):
            result = await retry_failed_notifications_task()
            assert "error" in result
            assert "Redis down" in result["error"]


class TestArchiveErrorLogsTask:
    """Req 49.7: archive error logs older than 12 months."""

    @pytest.mark.asyncio
    async def test_success_returns_count(self):
        mock_exec_result = AsyncMock()
        mock_exec_result.rowcount = 42
        with patch("app.tasks.scheduled.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.begin.return_value.__aenter__ = AsyncMock()
            mock_session.begin.return_value.__aexit__ = AsyncMock()
            mock_session.execute = AsyncMock(return_value=mock_exec_result)
            result = await archive_error_logs_task()
            assert result["archived_count"] == 42

    @pytest.mark.asyncio
    async def test_zero_archived(self):
        mock_exec_result = AsyncMock()
        mock_exec_result.rowcount = 0
        with patch("app.tasks.scheduled.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.begin.return_value.__aenter__ = AsyncMock()
            mock_session.begin.return_value.__aexit__ = AsyncMock()
            mock_session.execute = AsyncMock(return_value=mock_exec_result)
            result = await archive_error_logs_task()
            assert result["archived_count"] == 0

    @pytest.mark.asyncio
    async def test_exception_returns_error(self):
        with patch("app.tasks.scheduled.async_session_factory", side_effect=RuntimeError("Permission denied")):
            result = await archive_error_logs_task()
            assert "error" in result
            assert "Permission denied" in result["error"]


class TestGenerateRecurringInvoicesTask:
    """Req 60.2, 60.4: recurring invoice generation."""

    @pytest.mark.asyncio
    async def test_no_schedules_due(self):
        with patch("app.tasks.scheduled.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.begin.return_value.__aenter__ = AsyncMock()
            mock_session.begin.return_value.__aexit__ = AsyncMock()
            mock_svc = AsyncMock()
            mock_svc.find_due_schedules = AsyncMock(return_value=[])
            with patch("app.tasks.scheduled.RecurringService", return_value=mock_svc):
                result = await generate_recurring_invoices_task()
                assert result["generated"] == 0
                assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_exception_returns_error(self):
        with patch("app.tasks.scheduled.async_session_factory", side_effect=RuntimeError("DB connection lost")):
            result = await generate_recurring_invoices_task()
            assert "error" in result
            assert "DB connection lost" in result["error"]


class TestBeatScheduleIntegration:
    """Verify scheduled tasks are importable and callable."""

    def test_all_scheduled_tasks_importable(self):
        from app.tasks.scheduled import (
            check_overdue_invoices_task,
            retry_failed_notifications_task,
            archive_error_logs_task,
            generate_recurring_invoices_task,
        )
        assert callable(check_overdue_invoices_task)
        assert callable(retry_failed_notifications_task)
        assert callable(archive_error_logs_task)
        assert callable(generate_recurring_invoices_task)
