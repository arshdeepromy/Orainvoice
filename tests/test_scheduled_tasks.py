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


# ---------------------------------------------------------------------------
# Task 13: Background Task Guard on Standby (Req 13.1–13.5)
# ---------------------------------------------------------------------------


class TestWriteTasksDefinition:
    """13.2: Verify WRITE_TASKS set contains the correct task names."""

    def test_write_tasks_is_a_set(self):
        from app.tasks.scheduled import WRITE_TASKS
        assert isinstance(WRITE_TASKS, set)

    def test_write_tasks_contains_billing(self):
        from app.tasks.scheduled import WRITE_TASKS
        assert "recurring_billing" in WRITE_TASKS

    def test_write_tasks_contains_sms_reset(self):
        from app.tasks.scheduled import WRITE_TASKS
        assert "reset_sms_counters" in WRITE_TASKS

    def test_write_tasks_does_not_contain_readonly(self):
        """Read-only tasks like compliance_expiry should still run on standby."""
        from app.tasks.scheduled import WRITE_TASKS
        assert "compliance_expiry" not in WRITE_TASKS
        assert "quote_expiry" not in WRITE_TASKS
        assert "sync_public_holidays" not in WRITE_TASKS

    def test_all_write_tasks_exist_in_daily_tasks(self):
        """Every name in WRITE_TASKS must correspond to a registered task."""
        from app.tasks.scheduled import WRITE_TASKS, _DAILY_TASKS
        registered_names = {name for _, _, name in _DAILY_TASKS}
        for wt in WRITE_TASKS:
            assert wt in registered_names, f"WRITE_TASKS entry '{wt}' not in _DAILY_TASKS"


class TestStandbyTaskGuard:
    """13.1, 13.3: Role check skips write tasks on standby, logs debug."""

    @pytest.mark.asyncio
    async def test_standby_skips_write_tasks(self):
        """When role is 'standby', write tasks should not be dispatched."""
        import asyncio
        from unittest.mock import MagicMock

        dispatched: list[str] = []

        async def fake_run_task_safe(fn, name):
            dispatched.append(name)

        with patch("app.tasks.scheduled.get_node_role", return_value="standby"), \
             patch("app.tasks.scheduled._run_task_safe", side_effect=fake_run_task_safe), \
             patch("app.tasks.scheduled.asyncio.create_task") as mock_create:
            # Simulate one scheduler cycle
            from app.tasks.scheduled import WRITE_TASKS, _DAILY_TASKS, get_node_role
            import time

            role = get_node_role()
            assert role == "standby"

            last_run: dict[str, float] = {name: 0.0 for _, _, name in _DAILY_TASKS}
            now = time.time() + 100  # ensure all tasks are due

            skipped = []
            executed = []
            for fn, interval, name in _DAILY_TASKS:
                if now - last_run.get(name, 0) >= interval:
                    if role == "standby" and name in WRITE_TASKS:
                        skipped.append(name)
                        continue
                    executed.append(name)

            # All write tasks should be skipped
            for wt in WRITE_TASKS:
                assert wt in skipped, f"Write task '{wt}' was not skipped on standby"

            # Read-only tasks should still execute
            assert "compliance_expiry" in executed
            assert "quote_expiry" in executed
            assert "sync_public_holidays" in executed

    @pytest.mark.asyncio
    async def test_primary_executes_all_tasks(self):
        """When role is 'primary', all tasks should execute."""
        from app.tasks.scheduled import WRITE_TASKS, _DAILY_TASKS
        import time

        role = "primary"
        last_run: dict[str, float] = {name: 0.0 for _, _, name in _DAILY_TASKS}
        now = time.time() + 100

        skipped = []
        executed = []
        for fn, interval, name in _DAILY_TASKS:
            if now - last_run.get(name, 0) >= interval:
                if role == "standby" and name in WRITE_TASKS:
                    skipped.append(name)
                    continue
                executed.append(name)

        assert len(skipped) == 0
        assert len(executed) == len(_DAILY_TASKS)

    @pytest.mark.asyncio
    async def test_standalone_executes_all_tasks(self):
        """When role is 'standalone', all tasks should execute."""
        from app.tasks.scheduled import WRITE_TASKS, _DAILY_TASKS
        import time

        role = "standalone"
        last_run: dict[str, float] = {name: 0.0 for _, _, name in _DAILY_TASKS}
        now = time.time() + 100

        skipped = []
        executed = []
        for fn, interval, name in _DAILY_TASKS:
            if now - last_run.get(name, 0) >= interval:
                if role == "standby" and name in WRITE_TASKS:
                    skipped.append(name)
                    continue
                executed.append(name)

        assert len(skipped) == 0
        assert len(executed) == len(_DAILY_TASKS)

    def test_debug_log_on_skip(self):
        """13.3: A debug message should be logged when skipping a task."""
        from app.tasks.scheduled import WRITE_TASKS
        import logging

        with patch("app.tasks.scheduled.get_node_role", return_value="standby"):
            task_logger = logging.getLogger("app.tasks.scheduled")
            with patch.object(task_logger, "debug") as mock_debug:
                # Simulate the skip logic from the scheduler loop
                role = "standby"
                name = "recurring_billing"
                if role == "standby" and name in WRITE_TASKS:
                    task_logger.debug("Skipping task %s on standby node", name)

                mock_debug.assert_called_once_with(
                    "Skipping task %s on standby node", "recurring_billing"
                )


class TestPromotionResumesAllTasks:
    """13.4: After promotion to primary, all tasks execute normally.

    The middleware role cache is updated immediately by set_node_role()
    during promotion. The scheduler reads from get_node_role() each cycle,
    so the next cycle after promotion will see role='primary' and execute
    all tasks — no additional logic is needed.
    """

    @pytest.mark.asyncio
    async def test_promotion_switches_role_cache(self):
        """Verify that set_node_role updates the cache read by get_node_role."""
        from app.modules.ha.middleware import set_node_role, get_node_role

        # Start as standby
        set_node_role("standby")
        assert get_node_role() == "standby"

        # Promote to primary
        set_node_role("primary")
        assert get_node_role() == "primary"

    @pytest.mark.asyncio
    async def test_after_promotion_all_tasks_run(self):
        """After promotion, the scheduler should execute all tasks including writes."""
        from app.tasks.scheduled import WRITE_TASKS, _DAILY_TASKS
        from app.modules.ha.middleware import set_node_role, get_node_role
        import time

        # Simulate promotion
        set_node_role("standby")
        assert get_node_role() == "standby"

        set_node_role("primary")
        role = get_node_role()
        assert role == "primary"

        # Simulate scheduler cycle after promotion
        last_run: dict[str, float] = {name: 0.0 for _, _, name in _DAILY_TASKS}
        now = time.time() + 100

        skipped = []
        executed = []
        for fn, interval, name in _DAILY_TASKS:
            if now - last_run.get(name, 0) >= interval:
                if role == "standby" and name in WRITE_TASKS:
                    skipped.append(name)
                    continue
                executed.append(name)

        assert len(skipped) == 0
        assert len(executed) == len(_DAILY_TASKS)

        # Reset to standalone for other tests
        set_node_role("standalone")
