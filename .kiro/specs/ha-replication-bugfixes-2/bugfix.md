# Bugfix Requirements Document — HA Replication Post-Fix Review (Round 2)

## Introduction

This specification covers 6 confirmed bugs found during the post-bugfix review of the HA replication system (`docs/HA_REPLICATION_REVIEW_2.md`), conducted after all 15 original bugs from `HA_REPLICATION_GAPS.md` were patched. The bugs range from 3 critical defects (resync always fails on second call, split-brain detection broken after manual role changes, replication slot endpoint crashes on every call) to 2 significant issues (heartbeat restart loses Redis lock isolation, demote creates duplicate-key violations and leaves orphaned publication) and 1 minor gap (dev standby compose missing explicit WAL settings).

**Builds on:** `.kiro/specs/ha-replication-bugfixes/` — the original 15-bug fix specification.

**Review document:** `docs/HA_REPLICATION_REVIEW_2.md`

**Issue tracking:** Each bug shall be logged in `docs/ISSUE_TRACKER.md` per the issue-tracking workflow before implementation begins.

---

## Bug Analysis

### Current Behavior (Defect)

#### CRIT-1: `trigger_resync` orphaned slot → resync always fails on second call

1.1 WHEN `trigger_resync` is called after a subscription has previously existed THEN the system calls `drop_subscription()` which executes `ALTER SUBSCRIPTION ... SET (slot_name = NONE)` leaving an orphaned replication slot named `orainvoice_ha_sub` on the primary, and then immediately executes `CREATE SUBSCRIPTION ... WITH (copy_data = true)` which fails with "replication slot 'orainvoice_ha_sub' already exists" because `_cleanup_orphaned_slot_on_peer` is never called between the drop and create steps.

1.2 WHEN the `CREATE SUBSCRIPTION` fails in `trigger_resync` THEN the standby is left with all tables truncated (step 1 succeeded) and no subscription (step 3 failed), making the standby fully broken with no data and no replication — requiring manual `psql` intervention to recover.

#### CRIT-2: `promote()`/`demote()`/`demote_and_sync()` don't update `_heartbeat_service.local_role`

1.3 WHEN `promote()` is called manually (standby → primary) THEN the system calls `set_node_role("primary", ...)` to update the middleware but never updates `_heartbeat_service.local_role`, which stays as `"standby"`, causing `detect_split_brain("standby", peer_role)` to never return `True` even when both nodes are simultaneously primary — split-brain goes undetected.

1.4 WHEN `demote()` is called manually (primary → standby) THEN the system calls `set_node_role("standby", ...)` but `_heartbeat_service.local_role` stays as `"primary"`, causing `detect_split_brain("primary", "primary")` to return `True` on the next heartbeat — a spurious split-brain detection that persists until container restart, blocking all requests with misleading "split-brain detected" errors.

1.5 WHEN `demote_and_sync()` is called (role reversal recovery) THEN the system calls `set_node_role("standby", ...)` but `_heartbeat_service.local_role` stays as `"primary"`, causing the same spurious split-brain detection as `demote()`.

#### CRIT-3: `drop_replication_slot` router passes `None` as db → 500 on every call

1.6 WHEN the `DELETE /api/v1/ha/replication/slots/{slot_name}` endpoint is called THEN the router function `drop_replication_slot(slot_name: str)` has no `db: AsyncSession = Depends(get_db_session)` parameter and passes `None` to `ReplicationManager.drop_replication_slot(None, slot_name)`, which calls `db.execute()` on `None` → `AttributeError: 'NoneType' object has no attribute 'execute'` → 500 Internal Server Error on every call.

#### SIG-1: `save_config` restarts heartbeat without Redis lock info

1.7 WHEN `save_config` restarts the heartbeat service (due to peer endpoint change, secret change, etc.) THEN the new `HeartbeatService` instance is created without setting `_redis_lock_key`, `_lock_ttl`, or `_redis_client`, so the new service never renews the `ha:heartbeat_lock` Redis TTL, causing the lock to expire within 30 seconds and allowing a second gunicorn worker to start a duplicate heartbeat service — reintroducing the BUG-HA-06 multi-worker race condition.

#### SIG-2: `demote()` uses `copy_data=true` on full dataset and doesn't drop publication

1.8 WHEN `demote()` calls `resume_subscription()` and the fallback path (re-create subscription) executes THEN the `CREATE SUBSCRIPTION` SQL has no `WITH (copy_data = false)` clause, defaulting to `copy_data=true`, which causes PostgreSQL to attempt a full initial table sync on a node that already has all the data → duplicate primary-key violations on every table.

1.9 WHEN `demote()` transitions a primary to standby THEN it never calls `drop_publication()`, leaving the former primary with an active publication (`orainvoice_ha_pub`) that retains WAL unnecessarily and is conceptually incorrect for a standby node.

#### MIN-1: Dev standby compose missing `max_wal_senders` and `max_replication_slots`

1.10 WHEN `docker-compose.ha-standby.yml` starts the standby postgres THEN it does not include `-c max_wal_senders=10` or `-c max_replication_slots=10` in the postgres command, relying on PostgreSQL 16 defaults which happen to be correct by coincidence but are not explicitly declared like all other compose files.

---

### Expected Behavior (Correct)

#### CRIT-1 Expected: Orphaned slot cleanup in `trigger_resync`

2.1 WHEN `trigger_resync` is called THEN the system SHALL call `_cleanup_orphaned_slot_on_peer(primary_conn_str)` between `drop_subscription()` and `CREATE SUBSCRIPTION` to remove any orphaned replication slot left on the primary by the `SET (slot_name = NONE)` step.

2.2 WHEN `trigger_resync` completes the orphaned slot cleanup THEN the subsequent `CREATE SUBSCRIPTION` SHALL succeed because the slot name is available on the primary.

#### CRIT-2 Expected: `local_role` updated in all manual role transitions

2.3 WHEN `promote()` completes the role change to primary THEN the system SHALL set `_heartbeat_service.local_role = "primary"` (if `_heartbeat_service is not None`) after calling `set_node_role("primary", ...)`, so that split-brain detection uses the correct local role.

2.4 WHEN `demote()` completes the role change to standby THEN the system SHALL set `_heartbeat_service.local_role = "standby"` (if `_heartbeat_service is not None`) after calling `set_node_role("standby", ...)`, so that split-brain detection does not fire spuriously.

2.5 WHEN `demote_and_sync()` completes the role change to standby THEN the system SHALL set `_heartbeat_service.local_role = "standby"` (if `_heartbeat_service is not None`) after calling `set_node_role("standby", ...)`.

#### CRIT-3 Expected: `drop_replication_slot` endpoint has db dependency

2.6 WHEN the `DELETE /api/v1/ha/replication/slots/{slot_name}` endpoint is called THEN the router function SHALL have `db: AsyncSession = Depends(get_db_session)` as a parameter and SHALL pass `db` to `ReplicationManager.drop_replication_slot(db, slot_name)`, matching the pattern used by the adjacent `list_replication_slots` endpoint.

#### SIG-1 Expected: `save_config` passes Redis lock info to new HeartbeatService

2.7 WHEN `save_config` creates a new `HeartbeatService` instance THEN it SHALL set `_redis_lock_key`, `_lock_ttl`, and `_redis_client` on the new instance using the same pattern as `_start_ha_heartbeat` in `main.py`, so the new service can renew the Redis heartbeat lock TTL and prevent duplicate heartbeat services across workers.

#### SIG-2 Expected: `demote()` uses `copy_data=false` and drops publication

2.8 WHEN `resume_subscription()` re-creates a subscription in the fallback path THEN the `CREATE SUBSCRIPTION` SQL SHALL include `WITH (copy_data = false)` to prevent duplicate-key violations on a node that already has all the data.

2.9 WHEN `demote()` transitions a primary to standby THEN it SHALL call `drop_publication(db)` before resuming the subscription, so the former primary no longer holds an active publication.

#### MIN-1 Expected: Dev standby compose has explicit WAL settings

2.10 WHEN `docker-compose.ha-standby.yml` starts the standby postgres THEN the command SHALL include `-c max_wal_senders=10` and `-c max_replication_slots=10` to match all other compose files and make replication capability explicit rather than relying on defaults.

---

### Unchanged Behavior (Regression Prevention)

3.1 WHEN `init_standby` is called with `truncate_first=True` THEN the system SHALL CONTINUE TO truncate all public tables except `ha_config` before creating the subscription, and SHALL CONTINUE TO handle orphaned slots via `_cleanup_orphaned_slot_on_peer` with auto-retry, exactly as today.

3.2 WHEN `drop_subscription` is called THEN it SHALL CONTINUE TO execute `ALTER SUBSCRIPTION ... DISABLE`, `ALTER SUBSCRIPTION ... SET (slot_name = NONE)`, and `DROP SUBSCRIPTION IF EXISTS` in sequence, exactly as today.

3.3 WHEN `HeartbeatService._execute_auto_promote` runs (auto-promote path) THEN it SHALL CONTINUE TO set `self.local_role = "primary"` directly on the heartbeat service instance, exactly as today.

3.4 WHEN `list_replication_slots` is called THEN it SHALL CONTINUE TO use `db: AsyncSession = Depends(get_db_session)` and pass `db` to `ReplicationManager.list_replication_slots(db)`, exactly as today.

3.5 WHEN `_start_ha_heartbeat` in `main.py` creates the initial `HeartbeatService` THEN it SHALL CONTINUE TO set `_redis_lock_key`, `_lock_ttl`, and `_redis_client` on the instance, exactly as today.

3.6 WHEN `resume_subscription` successfully re-enables an existing subscription via `ALTER SUBSCRIPTION ... ENABLE` THEN it SHALL CONTINUE TO use the enable path without re-creating the subscription, exactly as today.

3.7 WHEN `promote()` is called THEN it SHALL CONTINUE TO check replication lag, stop the subscription, update the role, run post-promotion sequence sync, update the middleware cache, and write the audit log, exactly as today.

3.8 WHEN `demote_and_sync()` is called THEN it SHALL CONTINUE TO truncate all tables, create subscription via `init_standby`, update middleware, clear split-brain flags, and write audit log, exactly as today.

3.9 WHEN the dev standby postgres starts THEN it SHALL CONTINUE TO have `wal_level=logical`, `idle_in_transaction_session_timeout=30000`, `statement_timeout=30000`, and SSL configuration, exactly as today.

3.10 WHEN `trigger_resync` truncation fails THEN the error SHALL CONTINUE TO propagate and the subscription SHALL CONTINUE TO be left untouched, exactly as today.
