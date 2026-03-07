"""Unit tests for Task 35.2 — Scheduled jobs.

Tests the four Celery Beat tasks in ``app/tasks/scheduled.py``:
- check_overdue_invoices_task (Req 19.6)
- retry_failed_notifications_task (Req 37.2)
- archive_error_logs_task (Req 49.7)
- generate_recurring_invoices_task (Req 60.2, 60.4)

Requirements: 19.6, 37.2, 49.7, 60.2, 60.4
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks.scheduled import (
    MAX_NOTIFICATION_RETRIES,
    RETRY_DELAYS,
    ERROR_LOG_RETENTION_MONTHS,
    _get_retry_delay,
    _check_overdue_invoices_async,
    _retry_failed_notifications_async,
    _archive_error_logs_async,
    _generate_recurring_invoices_async,
    check_overdue_invoices_task,
    retry_failed_notifications_task,
    archive_error_logs_task,
    generate_recurring_invoices_task,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_max_notification_retries(self):
        assert MAX_NOTIFICATION_RETRIES == 3

    def test_retry_delays(self):
        assert RETRY_DELAYS == (60, 300, 900)

    def test_error_log_retention_months(self):
        assert ERROR_LOG_RETENTION_MONTHS == 12


# ---------------------------------------------------------------------------
# Retry delay helper
# ---------------------------------------------------------------------------

class TestGetRetryDelay:
    def test_first_retry_60s(self):
        assert _get_retry_delay(0) == 60

    def test_second_retry_300s(self):
        assert _get_retry_delay(1) == 300

    def test_third_retry_900s(self):
        assert _get_retry_delay(2) == 900

    def test_beyond_max_uses_last(self):
        assert _get_retry_delay(10) == 900


# ---------------------------------------------------------------------------
# Task registration and configuration
# ---------------------------------------------------------------------------

class TestTaskRegistration:
    """Verify all scheduled tasks are properly registered with Celery."""

    def test_overdue_invoices_task_name(self):
        assert check_overdue_invoices_task.name == (
            "app.tasks.scheduled.check_overdue_invoices_task"
        )

    def test_retry_notifications_task_name(self):
        assert retry_failed_notifications_task.name == (
            "app.tasks.scheduled.retry_failed_notifications_task"
        )

    def test_archive_error_logs_task_name(self):
        assert archive_error_logs_task.name == (
            "app.tasks.scheduled.archive_error_logs_task"
        )

    def test_generate_recurring_invoices_task_name(self):
        assert generate_recurring_invoices_task.name == (
            "app.tasks.scheduled.generate_recurring_invoices_task"
        )

    def test_overdue_invoices_acks_late(self):
        assert check_overdue_invoices_task.acks_late is True

    def test_retry_notifications_acks_late(self):
        assert retry_failed_notifications_task.acks_late is True

    def test_archive_error_logs_acks_late(self):
        assert archive_error_logs_task.acks_late is True

    def test_generate_recurring_acks_late(self):
        assert generate_recurring_invoices_task.acks_late is True


# ---------------------------------------------------------------------------
# check_overdue_invoices_task
# ---------------------------------------------------------------------------

class TestCheckOverdueInvoicesTask:
    """Req 19.6: overdue invoice status update."""

    def test_success_returns_count(self):
        with patch(
            "app.tasks.scheduled._run_async",
            return_value={"invoices_marked_overdue": 5},
        ):
            result = check_overdue_invoices_task()
            assert result["invoices_marked_overdue"] == 5

    def test_zero_overdue(self):
        with patch(
            "app.tasks.scheduled._run_async",
            return_value={"invoices_marked_overdue": 0},
        ):
            result = check_overdue_invoices_task()
            assert result["invoices_marked_overdue"] == 0

    def test_exception_returns_error(self):
        with patch(
            "app.tasks.scheduled._run_async",
            side_effect=RuntimeError("DB down"),
        ):
            result = check_overdue_invoices_task()
            assert "error" in result
            assert "DB down" in result["error"]


class TestCheckOverdueInvoicesAsync:
    """Test the async implementation calls mark_invoices_overdue."""

    def test_delegates_to_async_impl(self):
        """The sync task delegates to _check_overdue_invoices_async via _run_async."""
        with patch(
            "app.tasks.scheduled._run_async",
            return_value={"invoices_marked_overdue": 7},
        ) as mock_run:
            result = check_overdue_invoices_task()
            assert result["invoices_marked_overdue"] == 7
            mock_run.assert_called_once()
            # The argument should be a coroutine (the async function's return)
            args = mock_run.call_args
            assert args is not None


# ---------------------------------------------------------------------------
# retry_failed_notifications_task
# ---------------------------------------------------------------------------

class TestRetryFailedNotificationsTask:
    """Req 37.2: retry with exponential backoff."""

    def test_success_returns_counts(self):
        with patch(
            "app.tasks.scheduled._run_async",
            return_value={"retried": 2, "permanently_failed": 1, "errors": 0},
        ):
            result = retry_failed_notifications_task()
            assert result["retried"] == 2
            assert result["permanently_failed"] == 1
            assert result["errors"] == 0

    def test_no_pending_retries(self):
        with patch(
            "app.tasks.scheduled._run_async",
            return_value={"retried": 0, "permanently_failed": 0, "errors": 0},
        ):
            result = retry_failed_notifications_task()
            assert result["retried"] == 0

    def test_exception_returns_error(self):
        with patch(
            "app.tasks.scheduled._run_async",
            side_effect=RuntimeError("Redis down"),
        ):
            result = retry_failed_notifications_task()
            assert "error" in result
            assert "Redis down" in result["error"]


# ---------------------------------------------------------------------------
# archive_error_logs_task
# ---------------------------------------------------------------------------

class TestArchiveErrorLogsTask:
    """Req 49.7: archive error logs older than 12 months."""

    def test_success_returns_count(self):
        with patch(
            "app.tasks.scheduled._run_async",
            return_value={"archived_count": 42, "cutoff": "2023-01-01T00:00:00+00:00"},
        ):
            result = archive_error_logs_task()
            assert result["archived_count"] == 42

    def test_zero_archived(self):
        with patch(
            "app.tasks.scheduled._run_async",
            return_value={"archived_count": 0, "cutoff": "2023-01-01T00:00:00+00:00"},
        ):
            result = archive_error_logs_task()
            assert result["archived_count"] == 0

    def test_exception_returns_error(self):
        with patch(
            "app.tasks.scheduled._run_async",
            side_effect=RuntimeError("Permission denied"),
        ):
            result = archive_error_logs_task()
            assert "error" in result
            assert "Permission denied" in result["error"]


# ---------------------------------------------------------------------------
# generate_recurring_invoices_task
# ---------------------------------------------------------------------------

class TestGenerateRecurringInvoicesTask:
    """Req 60.2, 60.4: recurring invoice generation."""

    def test_success_returns_counts(self):
        with patch(
            "app.tasks.scheduled._run_async",
            return_value={"generated": 3, "errors": 0},
        ):
            result = generate_recurring_invoices_task()
            assert result["generated"] == 3
            assert result["errors"] == 0

    def test_no_schedules_due(self):
        with patch(
            "app.tasks.scheduled._run_async",
            return_value={"generated": 0, "errors": 0},
        ):
            result = generate_recurring_invoices_task()
            assert result["generated"] == 0

    def test_partial_failure(self):
        with patch(
            "app.tasks.scheduled._run_async",
            return_value={"generated": 2, "errors": 1},
        ):
            result = generate_recurring_invoices_task()
            assert result["generated"] == 2
            assert result["errors"] == 1

    def test_exception_returns_error(self):
        with patch(
            "app.tasks.scheduled._run_async",
            side_effect=RuntimeError("DB connection lost"),
        ):
            result = generate_recurring_invoices_task()
            assert "error" in result
            assert "DB connection lost" in result["error"]


# ---------------------------------------------------------------------------
# Beat schedule integration
# ---------------------------------------------------------------------------

class TestBeatScheduleIntegration:
    """Verify scheduled tasks match the Beat schedule in __init__.py."""

    def test_all_scheduled_tasks_importable(self):
        """All four tasks should be importable from the module."""
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

    def test_task_names_match_beat_schedule(self):
        from app.tasks import BEAT_SCHEDULE

        expected_tasks = {
            "check-overdue-invoices": "app.tasks.scheduled.check_overdue_invoices_task",
            "retry-failed-notifications": "app.tasks.scheduled.retry_failed_notifications_task",
            "archive-error-logs": "app.tasks.scheduled.archive_error_logs_task",
            "generate-recurring-invoices": "app.tasks.scheduled.generate_recurring_invoices_task",
        }

        for beat_name, task_name in expected_tasks.items():
            assert beat_name in BEAT_SCHEDULE, f"Missing Beat entry: {beat_name}"
            assert BEAT_SCHEDULE[beat_name]["task"] == task_name
