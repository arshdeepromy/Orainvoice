"""Celery application factory and shared task infrastructure.

Creates the Celery app instance used by all background tasks (notifications,
PDF generation, reports, scheduled jobs, integrations).

The broker and result backend are configured from ``app.config.settings``.

Queue architecture (5 named queues):
- **notifications** — email/SMS dispatch with retry
- **pdf_generation** — on-demand PDF rendering via WeasyPrint
- **reports** — async report generation for large datasets
- **integrations** — Xero/MYOB sync, Carjam overage billing
- **scheduled_jobs** — periodic tasks driven by Celery Beat

Requirements: 82.3
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue

from app.config import settings

# ---------------------------------------------------------------------------
# Celery application
# ---------------------------------------------------------------------------

celery_app = Celery(
    "workshoppro",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

# ---------------------------------------------------------------------------
# Queue definitions
# ---------------------------------------------------------------------------

default_exchange = Exchange("default", type="direct")

TASK_QUEUES = (
    Queue("default", default_exchange, routing_key="default"),
    Queue("notifications", Exchange("notifications", type="direct"), routing_key="notifications"),
    Queue("pdf_generation", Exchange("pdf_generation", type="direct"), routing_key="pdf_generation"),
    Queue("reports", Exchange("reports", type="direct"), routing_key="reports"),
    Queue("integrations", Exchange("integrations", type="direct"), routing_key="integrations"),
    Queue("scheduled_jobs", Exchange("scheduled_jobs", type="direct"), routing_key="scheduled_jobs"),
)

QUEUE_NAMES = frozenset(q.name for q in TASK_QUEUES)

# ---------------------------------------------------------------------------
# Task routing — maps task module paths to queues
# ---------------------------------------------------------------------------

TASK_ROUTES = {
    "app.tasks.notifications.*": {"queue": "notifications"},
    "app.tasks.pdf_generation.*": {"queue": "pdf_generation"},
    "app.tasks.reports.*": {"queue": "reports"},
    "app.tasks.integrations.*": {"queue": "integrations"},
    "app.tasks.scheduled.*": {"queue": "scheduled_jobs"},
    "app.tasks.subscriptions.*": {"queue": "scheduled_jobs"},
}

# ---------------------------------------------------------------------------
# Celery Beat schedule — periodic tasks
# ---------------------------------------------------------------------------

BEAT_SCHEDULE = {
    # -- Overdue invoice status update (every minute, acts at midnight) --
    "check-overdue-invoices": {
        "task": "app.tasks.scheduled.check_overdue_invoices_task",
        "schedule": 60.0,
    },
    # -- Overdue payment reminders (every 5 minutes) --
    "process-overdue-reminders": {
        "task": "app.tasks.notifications.process_overdue_reminders_task",
        "schedule": 300.0,
    },
    # -- WOF/rego expiry reminders (daily at 2am NZST) --
    "process-wof-rego-reminders": {
        "task": "app.tasks.notifications.process_wof_rego_reminders_task",
        "schedule": crontab(hour=2, minute=0),
    },
    # -- Retry failed notifications (every minute) --
    "retry-failed-notifications": {
        "task": "app.tasks.scheduled.retry_failed_notifications_task",
        "schedule": 60.0,
    },
    # -- Archive old error logs (daily at 3am NZST) --
    "archive-error-logs": {
        "task": "app.tasks.scheduled.archive_error_logs_task",
        "schedule": crontab(hour=3, minute=0),
    },
    # -- Trial expiry check (every hour) --
    "check-trial-expiry": {
        "task": "app.tasks.subscriptions.check_trial_expiry_task",
        "schedule": 3600.0,
    },
    # -- Grace period check (every hour) --
    "check-grace-period": {
        "task": "app.tasks.subscriptions.check_grace_period_task",
        "schedule": 3600.0,
    },
    # -- Suspension retention check (daily at 3am NZST) --
    "check-suspension-retention": {
        "task": "app.tasks.subscriptions.check_suspension_retention_task",
        "schedule": crontab(hour=3, minute=30),
    },
    # -- Carjam overage billing (daily at 4am NZST) --
    "report-carjam-overage": {
        "task": "app.tasks.subscriptions.report_carjam_overage_task",
        "schedule": crontab(hour=4, minute=0),
    },
    # -- SMS overage billing (daily at 4:15am NZST) --
    "report-sms-overage": {
        "task": "app.tasks.subscriptions.report_sms_overage_task",
        "schedule": crontab(hour=4, minute=15),
    },
    # -- Monthly SMS counter reset (1st of each month at 00:05 NZST) --
    "reset-sms-counters": {
        "task": "app.tasks.scheduled.reset_sms_counters_task",
        "schedule": crontab(day_of_month=1, hour=0, minute=5),
    },
    # -- Recurring invoice generation (daily at 6am NZST) --
    "generate-recurring-invoices": {
        "task": "app.tasks.scheduled.generate_recurring_invoices_task",
        "schedule": crontab(hour=6, minute=0),
    },
    # -- Staff schedule reminders (every 5 minutes) --
    "send-schedule-reminders": {
        "task": "app.tasks.scheduled.send_schedule_reminders_task",
        "schedule": 300.0,
    },
}

# ---------------------------------------------------------------------------
# Apply configuration
# ---------------------------------------------------------------------------

celery_app.conf.update(
    # Serialisation
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # Timezone
    timezone="Pacific/Auckland",
    enable_utc=True,
    # Task tracking
    task_track_started=True,
    # Queues
    task_queues=TASK_QUEUES,
    task_default_queue="default",
    task_default_exchange="default",
    task_default_routing_key="default",
    task_routes=TASK_ROUTES,
    # Beat schedule
    beat_schedule=BEAT_SCHEDULE,
    # Worker settings
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)

# ---------------------------------------------------------------------------
# Auto-discover task modules
# ---------------------------------------------------------------------------

celery_app.autodiscover_tasks(
    [
        "app.tasks.notifications",
        "app.tasks.pdf_generation",
        "app.tasks.reports",
        "app.tasks.integrations",
        "app.tasks.scheduled",
        "app.tasks.subscriptions",
        "app.tasks.webhooks",
    ]
)
