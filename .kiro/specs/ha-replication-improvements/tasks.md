# Implementation Tasks

## Task 1: Database Migration and Model Changes
- [x] 1.1 Create Alembic migration to add `promoted_at` column to `ha_config` table (TIMESTAMPTZ, nullable, default null, idempotent with IF NOT EXISTS guard)
- [x] 1.2 Add `promoted_at` field to `HAConfig` model in `app/modules/ha/models.py`
- [x] 1.3 Add `FailoverStatusResponse` and `DemoteAndSyncRequest` schemas to `app/modules/ha/schemas.py`
- [x] 1.4 Add `promoted_at` field to `HAConfigResponse` schema in `app/modules/ha/schemas.py`
- [x] 1.5 Run migration against dev database and verify column exists

## Task 2: Auto-Truncate on Standby Initialization
- [x] 2.1 Add `truncate_all_tables()` static method to `ReplicationManager` in `app/modules/ha/replication.py` — queries pg_tables for all public tables except ha_config, executes TRUNCATE ... CASCADE in a single statement via raw asyncpg connection
- [x] 2.2 Modify `init_standby()` in `ReplicationManager` to accept `truncate_first: bool = False` parameter and call `truncate_all_tables()` before creating the subscription when true
- [x] 2.3 Modify `replication_init` endpoint in `app/modules/ha/router.py` to pass `truncate_first=True` when role is standby
- [x] 2.4 Write property-based test: truncation table set correctness (ha_config always excluded from any set of public table names) `[PBT]`

## Task 3: Promotion Timestamp Tracking
- [x] 3.1 Modify `HAService.promote()` in `app/modules/ha/service.py` to set `cfg.promoted_at = datetime.now(timezone.utc)` after role change
- [x] 3.2 Modify `HAService.demote()` in `app/modules/ha/service.py` to set `cfg.promoted_at = None` after role change
- [x] 3.3 Modify heartbeat endpoint in `app/modules/ha/router.py` to include `promoted_at` in the payload dict (ISO 8601 string or null) before HMAC signing

## Task 4: HeartbeatService — Failover State Tracking
- [x] 4.1 Add `_peer_unreachable_since`, `_auto_promote_attempted`, `_auto_promote_failed_permanently`, and `_peer_promoted_at` instance variables to `HeartbeatService.__init__()` in `app/modules/ha/heartbeat.py`
- [x] 4.2 Modify `_ping_loop()` to track peer unreachable transitions: record `_peer_unreachable_since` when peer becomes unreachable, reset to None when peer becomes reachable
- [x] 4.3 Parse `promoted_at` from peer heartbeat response in `_ping_peer()` and store as `_peer_promoted_at`
- [x] 4.4 Add `get_peer_unreachable_seconds()` method returning seconds since peer became unreachable (or None)
- [x] 4.5 Add `get_seconds_until_auto_promote(failover_timeout: int)` method returning countdown (or None)
- [x] 4.6 Add `is_stale_primary(local_promoted_at: datetime | None)` method comparing local vs peer promoted_at timestamps
- [x] 4.7 Write property-based test: failover countdown arithmetic (remaining = max(0, timeout - elapsed), elapsed + remaining >= timeout) `[PBT]`

## Task 5: Auto-Promote Execution
- [x] 5.1 Add `_execute_auto_promote()` async method to `HeartbeatService` — uses `async_session_factory()` for dedicated DB session, stops subscription, updates role to primary, sets promoted_at, updates middleware cache, writes audit log with system UUID
- [x] 5.2 Add auto-promote trigger logic to `_ping_loop()` — when peer unreachable > failover_timeout and auto_promote_enabled and not already attempted, call `_execute_auto_promote()` with retry-once-on-failure logic
- [x] 5.3 Add `determine_stale_primary()` pure function to `app/modules/ha/utils.py` — compares two promoted_at timestamps, returns which is stale
- [x] 5.4 Write property-based test: should_auto_promote decision consistency (True iff enabled=True AND seconds > timeout) `[PBT]`
- [x] 5.5 Write property-based test: stale primary determination (antisymmetric, null is stale when peer has timestamp) `[PBT]`

## Task 6: Split-Brain Write Protection
- [x] 6.1 Add `_split_brain_blocked` module-level flag and `set_split_brain_blocked()` function to `app/modules/ha/middleware.py`
- [x] 6.2 Modify `StandbyWriteProtectionMiddleware.__call__()` to also block writes when `_split_brain_blocked` is True (same exemptions as standby mode: read-only methods, HA endpoints, auth endpoints)
- [x] 6.3 Add logic to HeartbeatService `_ping_loop()` to call `set_split_brain_blocked(True)` when split-brain detected and local node is stale primary, and `set_split_brain_blocked(False)` when split-brain resolves
- [x] 6.4 Write property-based test: split-brain write blocking consistency (GET/HEAD/OPTIONS never blocked, HA/auth paths never blocked, writes to non-exempt paths blocked when flag is active) `[PBT]`

## Task 7: Failover Status API and Demote-and-Sync Endpoint
- [x] 7.1 Add `GET /api/v1/ha/failover-status` endpoint to `app/modules/ha/router.py` — reads from HAConfig and HeartbeatService, returns `FailoverStatusResponse`
- [x] 7.2 Add `HAService.demote_and_sync()` method to `app/modules/ha/service.py` — demotes to standby, clears promoted_at, truncates tables, creates subscription, clears split-brain flags, writes audit log
- [x] 7.3 Add `POST /api/v1/ha/demote-and-sync` endpoint to `app/modules/ha/router.py` — validates confirmation text, calls `HAService.demote_and_sync()`

## Task 8: Frontend — Standby Init Warning Modal
- [x] 8.1 Modify the `init-replication` modal in `HAReplication.tsx` to show enhanced warning text when role is standby, require "CONFIRM" text input and reason field before proceeding
- [x] 8.2 Update `handleAction` for `init-replication` to pass `truncate_first=true` in the API call when role is standby

## Task 9: Frontend — Failover Status and Auto-Promote Countdown
- [x] 9.1 Add `FailoverStatus` TypeScript interface and `failoverStatus` state to `HAReplication.tsx`
- [x] 9.2 Add failover-status polling to `fetchData()` using `safeFetch` with `?? null` fallback
- [x] 9.3 Add auto-promote countdown banner component — amber banner with "Primary unreachable for X seconds, auto-promote in Y seconds" when applicable, gray banner when auto-promote disabled, green success banner after promotion

## Task 10: Frontend — Split-Brain Alert and Guided Recovery
- [x] 10.1 Add split-brain critical alert banner (red) when `failoverStatus?.split_brain_detected` is true, with "Demote and Sync" button when `is_stale_primary` is true
- [x] 10.2 Add guided recovery modal with data loss acknowledgment, "CONFIRM" input, reason field, and "Demote and Sync" / "Dismiss" buttons — calls `POST /api/v1/ha/demote-and-sync`
- [x] 10.3 Add `demote-and-sync` to the `ModalAction` type and wire up the modal action handler

## Task 11: Frontend — New Standby Setup Wizard
- [x] 11.1 Add wizard state management (current step, step completion tracking) and suggestion banner that appears when role is primary and peer unreachable > 5 minutes
- [x] 11.2 Build 4-step wizard UI: (a) peer DB connection form (reuse existing fields), (b) test connection with validation gate, (c) create replication user, (d) summary with instructions for new standby
- [x] 11.3 Wire wizard steps to existing API calls (save config, test-db-connection, create-replication-user) with step-by-step validation

## Task 12: Integration Testing
- [x] 12.1 Create `scripts/test_ha_improvements_e2e.py` — tests truncate-all-tables API, failover-status endpoint response shape, demote-and-sync endpoint, and promotion timestamp tracking


## Task 13: Background Task Guard on Standby
- [x] 13.1 Add role check to the task scheduler loop in `app/tasks/scheduled.py` — before each task execution, read the cached node role from `app/modules/ha/middleware.py` and skip write tasks when role is "standby"
- [x] 13.2 Define a list of standby-safe tasks (read-only) vs write tasks (billing, trial expiry, grace period, suspension, SMS reset, Carjam reset) — only skip write tasks
- [x] 13.3 Log a debug message when skipping a task due to standby role
- [x] 13.4 Verify that after promotion to primary, the next task cycle executes all tasks normally

## Task 14: Standby-Safe Container Startup
- [x] 14.1 Modify `scripts/docker-entrypoint.sh` to check the node role before running migrations — use `psql` to query `SELECT role FROM ha_config LIMIT 1` and skip `alembic upgrade head` if role is "standby"
- [x] 14.2 Skip the dev seed script on standby nodes in the entrypoint
- [x] 14.3 Add role check to `sync_demo_org_modules()` in `app/main.py` startup handler — skip writes when role is standby
- [x] 14.4 Handle the case where `ha_config` table doesn't exist yet (first deployment) — treat as standalone and run migrations normally

## Task 15: Heartbeat Service Crash Recovery
- [x] 15.1 Wrap the main `_ping_loop()` body in a try/except that catches all exceptions except `asyncio.CancelledError`
- [x] 15.2 Log the exception and continue to the next cycle after the normal interval
- [x] 15.3 Add a `_consecutive_failures` counter that increments on each failure and resets on success — log a warning after 5 consecutive failures
- [x] 15.4 Ensure the auto-promote logic (Task 5) is also wrapped in error handling so a failed promotion doesn't crash the heartbeat loop

## Task 16: Sync Status Column Updates
- [x] 16.1 Add logic to HeartbeatService to update `ha_config.sync_status` after each heartbeat cycle using a dedicated short-lived DB session via `async_session_factory()`
- [x] 16.2 Determine sync_status based on: subscription active + lag < 60s = "healthy", subscription active + lag >= 60s = "lagging", subscription disabled or peer unreachable = "disconnected", no subscription/publication = "not_configured"
- [x] 16.3 Also update `ha_config.last_peer_heartbeat` and `ha_config.last_peer_health` columns with the latest heartbeat data
- [x] 16.4 Throttle the DB update to once per 30 seconds (not every 10-second heartbeat) to reduce write load
