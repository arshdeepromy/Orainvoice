# Scheduled Tasks & Background Jobs

Developer reference for all recurring background tasks in the platform.

## Architecture

The app uses a **lightweight in-process async scheduler** — no Celery, no Redis queues, no external cron daemon. All tasks are plain `async` functions managed by a single `asyncio.Task` that runs inside the FastAPI process.

**Key files:**

- `app/tasks/scheduled.py` — task definitions + scheduler loop
- `app/tasks/notifications.py` — async email/SMS dispatch helpers (called by tasks, not scheduled directly)
- `app/integrations/connexus_sms.py` — Connexus token refresher (separate background loop)
- `app/main.py` — startup/shutdown hooks

## How the Scheduler Works

```
app startup (FastAPI lifespan)
  └─► start_scheduler()
        └─► asyncio.create_task(_scheduler_loop())
              └─► every 30s: check each task's last_run vs interval
                    └─► if elapsed >= interval: fire-and-forget via asyncio.create_task()
```

- On first boot, all `last_run` timestamps are `0.0`, so every task runs immediately on startup.
- Each task runs independently — a slow or failing task doesn't block others.
- All tasks are wrapped in `_run_task_safe()` which catches and logs exceptions.
- On shutdown, `stop_scheduler()` sets a stop event and waits up to 10s for the loop to exit.

## Task Registry

Tasks are registered in the `_DAILY_TASKS` list at the bottom of `app/tasks/scheduled.py`:

```python
_DAILY_TASKS = [
    (task_function, interval_seconds, "name"),
    ...
]
```

### Adding a New Task

1. Write an `async def your_task() -> dict:` function in `scheduled.py`
2. Use `async_session_factory()` for DB access (tasks run outside request context)
3. Return a dict with results/stats for logging
4. Append to `_DAILY_TASKS`:
   ```python
   (your_task, 3600, "your_task_name"),
   ```
5. No restart config needed — the scheduler picks it up on next deploy.

## All Registered Tasks

| Task | Interval | Frequency | What it does |
|------|----------|-----------|-------------|
| `check_overdue_invoices_task` | 3600s | Hourly | Marks invoices past due date as `overdue` |
| `retry_failed_notifications_task` | 300s | 5 min | Retries queued notifications with exponential backoff (60s → 300s → 900s, max 3 retries) |
| `archive_error_logs_task` | 86400s | Daily | Deletes `error_log` rows older than 12 months |
| `generate_recurring_invoices_task` | 3600s | Hourly | Finds due recurring schedules, generates invoices, advances next date |
| `check_quote_expiry_task` | 3600s | Hourly | Marks quotes past expiry date as `expired` |
| `send_schedule_reminders_task` | 300s | 5 min | Sends email reminders for staff schedule entries starting within 60 min |
| `check_compliance_expiry_task` | 86400s | Daily | Logs reminders for compliance docs expiring in 7 or 30 days |
| `publish_scheduled_notifications` | 60s | 1 min | Publishes platform notifications that have reached their scheduled time |
| `reset_sms_counters_task` | 86400s | Daily | Resets `sms_sent_this_month` counter on all orgs (with month-guard) |
| `process_customer_reminders_scheduled` | 86400s | Daily | Phase 1: scans customers with reminder_config, enqueues pending reminders |
| `process_reminder_queue_scheduled` | 60s | 1 min | Phase 2: processes pending reminder queue items in batches with rate limiting |
| `sync_public_holidays_task` | 15552000s | ~6 months | Syncs NZ and AU public holidays from Nager.Date API for the current year |

## Task Details

### SMS Counter Reset (`reset_sms_counters_task`)

Resets the legacy `Organisation.sms_sent_this_month` counter. Has a **month guard**: checks `sms_sent_reset_at` on the most recently reset org — if it's already been reset in the current calendar month, the task skips. This prevents container restarts from zeroing counters mid-month.

Note: the actual SMS usage source of truth is now a combined query against `sms_messages` + `notification_log` tables (see `_count_org_sms_this_month` in `admin/service.py`). The counter is legacy but still reset for backward compatibility.

### Reminder Queue (Two-Phase System)

The reminder system uses a two-phase approach:

- **Phase 1** (`process_customer_reminders_scheduled`, daily): Scans all customers with `reminder_config` in `custom_fields`, checks vehicle expiry dates, and inserts rows into `reminder_queue` with `INSERT ... ON CONFLICT DO NOTHING` for dedup.
- **Phase 2** (`process_reminder_queue_scheduled`, every 60s): Picks up pending items using `SELECT ... FOR UPDATE SKIP LOCKED`, sends via email/SMS with concurrency limit (5), marks sent/failed, retries with exponential backoff.

Config constants in `app/modules/notifications/reminder_queue_service.py`:
```python
DEFAULT_BATCH_SIZE = 50
BATCH_DELAY_SECONDS = 2.0
SEND_CONCURRENCY = 5
LOCK_TIMEOUT_MINUTES = 10
MAX_RETRIES = 3
```

### Notification Retry (`retry_failed_notifications_task`)

Retries notifications stuck in `queued` status with `retry_count > 0`. Uses exponential backoff:
- Retry 1: 60s delay
- Retry 2: 300s delay
- Retry 3: 900s delay
- After 3 retries: marked `failed`, logged to Global Admin error log

### Recurring Invoices (`generate_recurring_invoices_task`)

Sets RLS context per-org before generating each invoice. Processes each schedule in its own DB transaction so one failure doesn't roll back others.

## Connexus Token Refresher (Separate Background Loop)

The Connexus SMS token refresher is **not** part of the main scheduler. It's a standalone `asyncio.Task` managed by the `_TokenRefresher` singleton in `app/integrations/connexus_sms.py`.

- Starts when the first `ConnexusSmsClient` is instantiated
- On startup, restores cached token from DB (`sms_verification_providers.config` JSONB)
- If token has > 5 min remaining: sleeps until `remaining - 300s`
- If token is within 5 min of expiry, expired, or missing: refreshes immediately
- After each successful refresh: persists token to DB
- All refresh events are logged to an in-memory ring buffer (viewable via dashboard "Refresh Reasons" button)

## Startup Behavior

On container start/restart:
1. FastAPI `startup` event fires
2. `start_scheduler()` creates the scheduler loop task
3. All `last_run` timestamps are `0.0` → every task runs immediately
4. The SMS counter reset task checks the month guard before resetting
5. The Connexus token refresher restores its token from DB before first refresh attempt

## Gotchas

- **No distributed locking**: If you run multiple app instances (horizontal scaling), every instance runs its own scheduler. Tasks like `reset_sms_counters_task` are idempotent, but others (like `generate_recurring_invoices_task`) could produce duplicates. Add a distributed lock (Redis/pg advisory lock) before scaling horizontally.
- **Intervals are wall-clock, not cron expressions**: A task with `86400s` interval runs ~24h after its last run, not at a specific time of day. After a restart, it runs immediately.
- **Fire-and-forget**: Tasks are dispatched via `asyncio.create_task()` without awaiting. If the app shuts down while a task is running, it may be interrupted.
- **No persistent state**: The `last_run` dict lives in memory. On restart, all tasks re-run. Design tasks to be idempotent.
