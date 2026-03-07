"""Unit tests for Task 35.1 — Celery configuration and task queues.

Validates:
- 5 named queues are defined: notifications, pdf_generation, reports,
  integrations, scheduled_jobs
- Task routing maps task modules to the correct queues
- Celery Beat schedule contains all required periodic tasks
- Broker and backend are configured from settings
- Serialisation, timezone, and worker settings are correct

Requirements: 82.3
"""

from __future__ import annotations

from celery.schedules import crontab

from app.config import settings
from app.tasks import (
    BEAT_SCHEDULE,
    QUEUE_NAMES,
    TASK_QUEUES,
    TASK_ROUTES,
    celery_app,
)


class TestQueueDefinitions:
    """Verify the 5 named queues plus default are defined."""

    EXPECTED_QUEUES = {
        "default",
        "notifications",
        "pdf_generation",
        "reports",
        "integrations",
        "scheduled_jobs",
    }

    def test_all_queues_present(self):
        actual = {q.name for q in TASK_QUEUES}
        assert actual == self.EXPECTED_QUEUES

    def test_queue_names_frozenset(self):
        assert QUEUE_NAMES == self.EXPECTED_QUEUES

    def test_queue_count(self):
        # 5 named + 1 default
        assert len(TASK_QUEUES) == 6

    def test_each_queue_has_exchange(self):
        for q in TASK_QUEUES:
            assert q.exchange is not None
            assert q.exchange.name != ""


class TestTaskRouting:
    """Verify task modules are routed to the correct queues."""

    def test_notifications_route(self):
        assert TASK_ROUTES["app.tasks.notifications.*"]["queue"] == "notifications"

    def test_pdf_generation_route(self):
        assert TASK_ROUTES["app.tasks.pdf_generation.*"]["queue"] == "pdf_generation"

    def test_reports_route(self):
        assert TASK_ROUTES["app.tasks.reports.*"]["queue"] == "reports"

    def test_integrations_route(self):
        assert TASK_ROUTES["app.tasks.integrations.*"]["queue"] == "integrations"

    def test_scheduled_route(self):
        assert TASK_ROUTES["app.tasks.scheduled.*"]["queue"] == "scheduled_jobs"

    def test_subscriptions_route(self):
        assert TASK_ROUTES["app.tasks.subscriptions.*"]["queue"] == "scheduled_jobs"

    def test_all_routes_target_valid_queues(self):
        for pattern, route in TASK_ROUTES.items():
            assert route["queue"] in QUEUE_NAMES, (
                f"Route {pattern} targets unknown queue {route['queue']}"
            )


class TestBeatSchedule:
    """Verify Celery Beat periodic task schedule."""

    def test_overdue_invoices_every_minute(self):
        entry = BEAT_SCHEDULE["check-overdue-invoices"]
        assert entry["task"] == "app.tasks.scheduled.check_overdue_invoices_task"
        assert entry["schedule"] == 60.0

    def test_overdue_reminders_every_5_minutes(self):
        entry = BEAT_SCHEDULE["process-overdue-reminders"]
        assert entry["task"] == "app.tasks.notifications.process_overdue_reminders_task"
        assert entry["schedule"] == 300.0

    def test_wof_rego_reminders_daily_2am(self):
        entry = BEAT_SCHEDULE["process-wof-rego-reminders"]
        assert entry["task"] == "app.tasks.notifications.process_wof_rego_reminders_task"
        sched = entry["schedule"]
        assert isinstance(sched, crontab)

    def test_retry_failed_notifications_every_minute(self):
        entry = BEAT_SCHEDULE["retry-failed-notifications"]
        assert entry["task"] == "app.tasks.scheduled.retry_failed_notifications_task"
        assert entry["schedule"] == 60.0

    def test_archive_error_logs_daily_3am(self):
        entry = BEAT_SCHEDULE["archive-error-logs"]
        assert entry["task"] == "app.tasks.scheduled.archive_error_logs_task"
        sched = entry["schedule"]
        assert isinstance(sched, crontab)

    def test_trial_expiry_hourly(self):
        entry = BEAT_SCHEDULE["check-trial-expiry"]
        assert entry["task"] == "app.tasks.subscriptions.check_trial_expiry_task"
        assert entry["schedule"] == 3600.0

    def test_recurring_invoices_daily(self):
        entry = BEAT_SCHEDULE["generate-recurring-invoices"]
        assert entry["task"] == "app.tasks.scheduled.generate_recurring_invoices_task"
        sched = entry["schedule"]
        assert isinstance(sched, crontab)

    def test_all_beat_entries_have_task_and_schedule(self):
        for name, entry in BEAT_SCHEDULE.items():
            assert "task" in entry, f"Beat entry '{name}' missing 'task'"
            assert "schedule" in entry, f"Beat entry '{name}' missing 'schedule'"


class TestCeleryAppConfig:
    """Verify core Celery app configuration."""

    def test_broker_url_from_settings(self):
        assert celery_app.conf.broker_url == settings.celery_broker_url

    def test_result_backend_from_settings(self):
        assert celery_app.conf.result_backend == settings.celery_result_backend

    def test_serializer_json(self):
        assert celery_app.conf.task_serializer == "json"

    def test_accept_content_json(self):
        assert "json" in celery_app.conf.accept_content

    def test_timezone_nz(self):
        assert celery_app.conf.timezone == "Pacific/Auckland"

    def test_utc_enabled(self):
        assert celery_app.conf.enable_utc is True

    def test_track_started(self):
        assert celery_app.conf.task_track_started is True

    def test_default_queue(self):
        assert celery_app.conf.task_default_queue == "default"

    def test_acks_late(self):
        assert celery_app.conf.task_acks_late is True

    def test_reject_on_worker_lost(self):
        assert celery_app.conf.task_reject_on_worker_lost is True

    def test_prefetch_multiplier(self):
        assert celery_app.conf.worker_prefetch_multiplier == 1

    def test_app_name(self):
        assert celery_app.main == "workshoppro"
