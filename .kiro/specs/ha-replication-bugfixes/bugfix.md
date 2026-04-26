# HA Replication — Bug Fix Specification

## Introduction

This specification covers 15 verified bugs and gaps in the OraInvoice HA (High Availability) replication system identified by a deep audit of `app/modules/ha/`, all `docker-compose` files, `app/main.py`, and operational scripts. The bugs range from two critical defects that make real-world failover impossible (post-promotion duplicate key violations from unreplicated sequences, and a broken full-resync flow), to significant operational hazards (unbounded WAL disk growth, multi-worker heartbeat race conditions, startup ignoring DB-stored secrets), to moderate and minor issues affecting accuracy, consistency, and security hygiene.

The fixes are ordered by severity and grouped into logical areas: replication data integrity, process isolation, startup bootstrapping, PostgreSQL configuration, script security, and correctness of ancillary components.

**Existing HA specs this builds on:**
- `.kiro/specs/ha-replication/` — original HA requirements and design
- `.kiro/specs/ha-replication-improvements/` — auto-promote, split-brain, demote-and-sync improvements

**Issue tracking:** each bug shall be logged in `docs/ISSUE_TRACKER.md` per the issue-tracking workflow before implementation begins.

---

## Bug Analysis

### BUG-HA-01 (Critical): Sequences not replicated — post-promotion duplicate key violations
**File:** `app/modules/ha/replication.py:183`

**Current behavior (defect):**

1.1 WHEN `init_primary` creates the PostgreSQL publication THEN the SQL is `CREATE PUBLICATION orainvoice_ha_pub FOR TABLE table1, table2, ...` which replicates row data only and NOT sequences, so all auto-increment sequences on the standby remain at their initial values (typically `1`) regardless of how far the primary's sequences have advanced.

1.2 WHEN a write arrives on the standby via logical replication (e.g. `INSERT id=12345`) THEN PostgreSQL applies the row directly without calling `nextval()`, so the local sequence never advances on the standby.

1.3 WHEN the standby is promoted to primary and the application tries to `INSERT` its first new row THEN the ORM calls `nextval('some_id_seq')` which returns `1`, but `id=1` already exists in the replicated data → **duplicate key violation on every table with an auto-increment primary key**.

1.4 WHEN `get_replication_lag` queries `pg_stat_subscription.last_msg_send_time` THEN it reports the time of the last keepalive message (sent every few seconds regardless of data changes), which substantially understates the true replication lag during periods of low write activity, making the promote lag-safety guard (`lag > 5.0 → require force`) ineffective.

### BUG-HA-02 (Critical): `trigger_resync` does not truncate the standby before re-copying
**File:** `app/modules/ha/replication.py:400`

**Current behavior (defect):**

2.1 WHEN `trigger_resync` is called THEN it calls `drop_subscription(db)` followed by `CREATE SUBSCRIPTION ... WITH (copy_data = true)` without first calling `truncate_all_tables()`.

2.2 WHEN PostgreSQL logical replication performs the initial copy with `copy_data = true` THEN it does NOT automatically truncate the target tables; it inserts rows directly into existing tables.

2.3 WHEN `trigger_resync` is called on a standby that already has replicated rows THEN the `copy_data = true` initial sync attempts to re-insert all rows from the primary → **duplicate primary key errors on every table**, making the re-sync fail entirely.

2.4 WHEN `init_standby` is called from `router.py:448` THEN it correctly passes `truncate_first=True`, which truncates before subscribing. WHEN `trigger_resync` is called THEN it bypasses this safeguard, making resync less safe than the initial sync.

### BUG-HA-03 (Significant): Hardcoded credentials committed to the repository
**Files:** `scripts/check_repl_status.sh`, `scripts/check_sync_status.sh`, `scripts/fix_replication.sh`

**Current behavior (defect):**

3.1 WHEN `scripts/check_repl_status.sh` or `scripts/check_sync_status.sh` or `scripts/fix_replication.sh` are executed THEN they use `echo W4h3guru1# | sudo -S` with the production server's sudo password hardcoded in plaintext.

3.2 WHEN `scripts/fix_replication.sh` creates a subscription THEN it embeds `password=NoorHarleen1` (the live replication user's password) in plaintext in the SQL heredoc.

3.3 WHEN any developer, CI pipeline, or code-scanning tool reads these files from git history THEN the credentials are exposed, violating the security hardening rule: "Never store masked credential values back to the database" and the credential hygiene principle from `steering/security-hardening-checklist.md`.

### BUG-HA-04 (Significant): Startup heartbeat service ignores DB-stored heartbeat secret
**File:** `app/main.py:657`

**Current behavior (defect):**

4.1 WHEN `_start_ha_heartbeat()` runs at container startup THEN it retrieves the secret with `secret = os.environ.get("HA_HEARTBEAT_SECRET", "")` exclusively from the environment variable, ignoring any secret stored in `ha_config.heartbeat_secret` (encrypted at rest).

4.2 WHEN an admin configures the heartbeat secret via the HA admin UI (which stores it encrypted in the DB via `envelope_encrypt`) THEN the secret is correctly used by `HAService.save_config` via `_get_heartbeat_secret_from_config(cfg)` during runtime.

4.3 WHEN the app container restarts (after deploy, crash, or power cycle) THEN the heartbeat service starts with the env var value only, not the DB-stored value → HMAC verification fails on every heartbeat ping if the admin set the secret through the UI without also updating the env var.

4.4 WHEN `HA_HEARTBEAT_SECRET` is absent from the environment THEN the startup heartbeat service runs with an empty secret, making HMAC verification trivially forgeable — but the warning log is only emitted by `_get_heartbeat_secret`, not by the startup code path.

### BUG-HA-05 (Significant): No WAL disk space guard — unbounded WAL retention on primary
**Files:** all `docker-compose` files

**Current behavior (defect):**

5.1 WHEN `docker-compose.pi.yml` configures the primary postgres THEN `max_slot_wal_keep_size` is not set, so PostgreSQL retains all WAL from the replication slot's `restart_lsn` indefinitely.

5.2 WHEN the standby goes offline (network outage, hardware failure, planned maintenance) THEN the primary's replication slot continues accumulating WAL with no upper bound.

5.3 WHEN the accumulated WAL fills the primary's disk THEN the primary crashes with `FATAL: could not write to file "pg_wal/..."`, taking down the entire service.

5.4 WHEN `docker-compose.pi.yml` sets `max_replication_slots=150` THEN up to 150 idle orphaned slots could each accumulate WAL independently, multiplying the disk risk on the Raspberry Pi which has limited storage.

5.5 WHEN `docker-compose.yml` (base, used by primary dev) does not set `max_wal_senders` or `max_replication_slots` THEN replication silently depends on PostgreSQL defaults (`max_wal_senders=10`, `max_replication_slots=10`) with no explicit intent documented in the compose file.

### BUG-HA-06 (Significant): Multi-worker gunicorn spawns independent heartbeat service per worker
**Files:** `app/main.py:641`, `app/modules/ha/service.py:38`

**Current behavior (defect):**

6.1 WHEN gunicorn starts with `--workers 2` THEN each worker process independently executes `_start_ha_heartbeat()`, creating two separate `HeartbeatService` instances with two separate `asyncio.Task` background loops.

6.2 WHEN both workers run the heartbeat loop THEN the standby receives two heartbeat pings per configured interval (20 pings/minute at the default 10s interval), doubling the expected load.

6.3 WHEN the `_peer_unreachable_since` timer and `_auto_promote_attempted` flag are module-level state inside each worker THEN two independent auto-promote executions can race: both workers detect the timeout, both set `_auto_promote_attempted = True`, and both call `_execute_auto_promote()`, creating a race condition on `cfg.role` update and writing two audit log entries.

6.4 WHEN `HAService._heartbeat_service` (module-level singleton) is updated in one worker THEN other workers retain their own separate singleton, so `get_heartbeat_service()` returns stale or inconsistent data across workers.

6.5 WHEN the heartbeat response cache `_hb_cache` in `router.py` is invalidated after `save_config` by setting `_ha_router._hb_cache["ts"] = 0` in one worker THEN the other worker's cache TTL is unaffected and continues serving stale heartbeat config for up to 10 seconds.

### BUG-HA-07 (Moderate): Split-brain is undetectable and undocumented during full network partition
**File:** `app/modules/ha/heartbeat.py:277`

**Current behavior (defect):**

7.1 WHEN both nodes are fully isolated from each other (network partition) THEN `detect_split_brain(self.local_role, peer_role)` never executes because `_ping_peer()` never returns a successful heartbeat response with a `role` field.

7.2 WHEN the standby auto-promotes after the failover timeout during a network partition THEN both nodes accept writes independently and `split_brain_detected` remains `False` on both sides indefinitely.

7.3 WHEN the HA documentation (`docs/HA_REPLICATION_GUIDE.md`) describes failover scenarios THEN the full-partition split-brain limitation is not explicitly documented, leaving admins with a false expectation that split-brain is always detected.

### BUG-HA-08 (Moderate): Primary dev compose file missing explicit WAL sender/slot settings
**File:** `docker-compose.yml`

**Current behavior (defect):**

8.1 WHEN the primary is started with only `docker-compose.yml` (without the `docker-compose.pi.yml` overlay) THEN the postgres command only has `wal_level=logical` but no `max_wal_senders` or `max_replication_slots`, silently depending on PostgreSQL defaults.

8.2 WHEN a developer sets up a local dev HA environment without the pi overlay THEN replication may work by accident (defaults are sufficient for 1 standby) or fail unexpectedly if slots fill.

### BUG-HA-09 (Moderate): Standby dev compose missing statement and idle-transaction timeouts
**File:** `docker-compose.ha-standby.yml`

**Current behavior (defect):**

9.1 WHEN `docker-compose.ha-standby.yml` starts the standby postgres THEN there is no `idle_in_transaction_session_timeout` or `statement_timeout` configured, unlike `docker-compose.standby-prod.yml` (30000ms each) and `docker-compose.pi.yml` (30000ms each).

9.2 WHEN a session on the dev standby hangs inside a transaction (bug, deadlock, forgotten commit) THEN it is never killed, masking timeout-related bugs that would surface in production.

### BUG-HA-10 (Moderate): Replication lag metric uses `last_msg_send_time` — understates true lag
**File:** `app/modules/ha/replication.py:482`

**Current behavior (defect):**

10.1 WHEN `get_replication_status` and `get_replication_lag` compute lag THEN they use `EXTRACT(EPOCH FROM (now() - last_msg_send_time))` from `pg_stat_subscription`, where `last_msg_send_time` is updated by keepalive messages (sent every few seconds regardless of data changes).

10.2 WHEN there are no write transactions on the primary THEN `last_msg_send_time` is refreshed by keepalive pings and reports near-zero lag even if the subscription is lagging in LSN terms.

10.3 WHEN the lag metric is used by the promote safety guard (`lag > 5.0 → require force`) THEN a true lag of 30 seconds could be reported as 0.5 seconds because a keepalive arrived recently → **the guard allows promotion without a `force` flag despite significant data loss risk**.

### BUG-HA-11 (Moderate): `pg_hba.conf` is unmanaged — replication connections not IP-restricted
**Scope:** deployment/infrastructure

**Current behavior (defect):**

11.1 WHEN the PostgreSQL Docker image starts THEN `pg_hba.conf` uses the default Docker-provided rules which allow all authenticated connections from any host, not just the peer's IP.

11.2 WHEN any host on the VPN/network knows the replication user credentials THEN it can establish a replication connection to the primary's PostgreSQL, even if it is not the designated standby.

11.3 WHEN `docs/HA_REPLICATION_GUIDE.md` documents IP-based `pg_hba.conf` restrictions THEN there is no script, entrypoint, or compose mechanism to actually deploy these rules, making the recommended configuration impossible to follow without manual steps.

### BUG-HA-12 (Minor): Heartbeat cache invalidation is single-worker in a multi-worker gunicorn setup
**File:** `app/modules/ha/router.py:272`

**Current behavior (defect):**

12.1 WHEN `HAService.save_config` completes and tries to invalidate the heartbeat response cache THEN it does so by accessing `_ha_router._hb_cache["ts"] = 0` within the worker that handled the request.

12.2 WHEN the response is served by a different worker (which gunicorn may route to arbitrarily) THEN that worker's `_hb_cache` is untouched and continues serving stale role, secret, and maintenance-mode values for up to 10 seconds.

### BUG-HA-13 (Minor): WebSocket connections bypass standby write-protection middleware
**File:** `app/modules/ha/middleware.py:88`

**Current behavior (defect):**

13.1 WHEN `StandbyWriteProtectionMiddleware.__call__` receives a WebSocket upgrade request THEN it checks `if scope["type"] != "http"` and passes the request through unconditionally, skipping all write-protection logic.

13.2 WHEN a future WebSocket handler writes to the database (kitchen display's `publish_kitchen_event` currently does not, but any new handler might) THEN those writes are silently allowed on a standby node, bypassing the protection the middleware was designed to enforce.

### BUG-HA-14 (Minor): `dead_letter` table is replicated and may cause double-processing on new primary
**File:** `app/modules/ha/replication.py:176`

**Current behavior (defect):**

14.1 WHEN `init_primary` builds the publication table list THEN it includes all public schema tables except `ha_config`, which includes `dead_letter` (failed background jobs).

14.2 WHEN a failover occurs THEN the new primary (former standby) inherits all `dead_letter` entries that the old primary accumulated, representing partially-executed operations from the old node.

14.3 WHEN the background task processor re-attempts `dead_letter` entries on the new primary THEN jobs that already partially ran on the old primary could be re-executed, causing double side-effects (duplicate emails, duplicate payment attempts, duplicate webhook deliveries).

### BUG-HA-15 (Minor): Peer role inferred as opposite of local in `get_cluster_status` — incorrect in standalone mode
**File:** `app/modules/ha/service.py:567`

**Current behavior (defect):**

15.1 WHEN `get_cluster_status` builds the peer entry for the cluster status dashboard THEN it sets `peer_role = "standby" if cfg.role == "primary" else "primary"`, which always produces the opposite of the local role.

15.2 WHEN the local node is in `standalone` mode THEN the peer entry is shown with role `"primary"`, which is incorrect.

15.3 WHEN the heartbeat response payload already contains the peer's actual role (`data.get("role")`) from the last successful ping THEN this data is available in `HeartbeatService._ping_peer` return values but is not stored for use by `get_cluster_status`.

---

## Expected Behavior (Correct)

### BUG-HA-01 Expected (Sequence Replication)

1.1 WHEN `init_primary` creates the PostgreSQL publication THEN the publication SHALL include all public tables (excluding `ha_config`) AND all sequences via `CREATE PUBLICATION orainvoice_ha_pub FOR TABLE tbl1, tbl2, ... WITH (publish = 'insert,update,delete,truncate')` followed by `ALTER PUBLICATION orainvoice_ha_pub ADD ALL SEQUENCES` (PostgreSQL 16 syntax).

1.2 WHEN a sequence value is advanced on the primary THEN the new value SHALL be replicated to the standby so that after promotion the standby's sequences are current.

1.3 WHEN the standby is promoted to primary and the application inserts its first new row THEN the ORM call to `nextval()` SHALL return a value that does not conflict with any existing row.

1.4 AS A fallback for environments where sequence replication is not supported THEN `promote()` in `HAService` SHALL execute a post-promotion sequence synchronisation step that runs `SELECT setval(seq, COALESCE(MAX(id), 1)) FROM table` for all tables with auto-increment primary keys before the middleware role cache is updated to "primary".

1.5 WHEN `get_replication_lag` measures lag THEN it SHALL use `EXTRACT(EPOCH FROM (now() - latest_end_lsn_time))` or compare `pg_current_wal_lsn()` on the primary vs `received_lsn` on the standby (via `pg_stat_subscription.received_lsn`), providing a lag measure that is non-zero even during keepalive-only periods.

### BUG-HA-02 Expected (Resync Truncation)

2.1 WHEN `trigger_resync` is called THEN it SHALL call `truncate_all_tables()` before dropping and recreating the subscription, so the standby tables are empty before the initial copy begins.

2.2 WHEN `trigger_resync` completes the truncation THEN it SHALL log the count of truncated tables at INFO level.

2.3 WHEN truncation fails for any reason THEN `trigger_resync` SHALL raise an exception and not proceed to drop or recreate the subscription.

2.4 WHEN the re-sync subscription is created THEN it SHALL use `WITH (copy_data = true)` and the standby tables SHALL be empty so the copy succeeds without primary key conflicts.

### BUG-HA-03 Expected (Hardcoded Credentials)

3.1 WHEN `scripts/check_repl_status.sh`, `scripts/check_sync_status.sh`, and `scripts/fix_replication.sh` are read THEN they SHALL contain NO hardcoded passwords, sudo secrets, or database credentials.

3.2 WHEN these scripts need to run privileged commands THEN they SHALL use `sudo` without embedding a password (rely on SSH key auth and `NOPASSWD` sudoers rules, or prompt interactively).

3.3 WHEN `fix_replication.sh` creates a replication subscription THEN the connection string SHALL reference the `HA_PEER_DB_URL` environment variable instead of a hardcoded password.

3.4 WHEN the credentials are removed from scripts THEN a note SHALL be added explaining how to supply them at runtime (environment variable or SSH key setup).

### BUG-HA-04 Expected (Startup Heartbeat Secret)

4.1 WHEN `_start_ha_heartbeat()` initialises the `HeartbeatService` THEN it SHALL call `_get_heartbeat_secret_from_config(config_orm_obj)` (which reads the encrypted DB-stored secret and falls back to the env var) instead of `os.environ.get("HA_HEARTBEAT_SECRET", "")` directly.

4.2 WHEN the app starts and an encrypted secret is present in `ha_config.heartbeat_secret` THEN the heartbeat service SHALL use that decrypted value for HMAC signing.

4.3 WHEN the app starts and no DB-stored secret exists THEN the startup code SHALL fall back to `HA_HEARTBEAT_SECRET` env var, matching existing runtime behaviour.

4.4 WHEN the startup heartbeat service is initialised with an empty secret THEN it SHALL log a warning (matching the existing warning in `_get_heartbeat_secret`) so the operator is alerted.

### BUG-HA-05 Expected (WAL Disk Guard)

5.1 WHEN `docker-compose.pi.yml` configures the primary postgres THEN it SHALL include `-c max_slot_wal_keep_size=2048` (2 GB ceiling), causing PostgreSQL to invalidate the replication slot rather than filling the disk when WAL accumulates beyond that limit.

5.2 WHEN `docker-compose.pi.yml` configures `max_replication_slots` THEN the value SHALL be reduced to `10` (sufficient for 1 standby plus headroom), removing the excessive 150-slot allocation.

5.3 WHEN `docker-compose.yml` (base/primary dev) configures postgres THEN it SHALL explicitly include `max_wal_senders=10` and `max_replication_slots=10` so replication parameters are visible and intentional, not silently defaulted.

5.4 WHEN a replication slot is invalidated due to `max_slot_wal_keep_size` THEN the HA admin page SHALL display this as a `disconnected` sync status and the admin SHALL use "Trigger Re-sync" to recover.

### BUG-HA-06 Expected (Multi-Worker Isolation)

6.1 WHEN gunicorn starts with multiple workers THEN only ONE worker SHALL run the heartbeat service background task. The selection SHALL use a Redis distributed lock (`SET NX EX`) so only the lock-holder starts the heartbeat loop.

6.2 WHEN a worker that holds the heartbeat lock exits or crashes THEN another worker SHALL acquire the lock within one heartbeat interval and start the heartbeat service.

6.3 WHEN `_execute_auto_promote` runs THEN it SHALL use a Redis distributed lock (distinct from the heartbeat lock) to ensure only one promotion attempt runs across all workers, preventing the race condition on `cfg.role`.

6.4 WHEN the heartbeat cache `_hb_cache` needs invalidation THEN the invalidation SHALL write a flag to Redis (e.g., `ha:hb_cache_dirty = 1` with a short TTL) so all workers pick it up on their next request.

### BUG-HA-07 Expected (Network Partition Documentation)

7.1 WHEN a full network partition occurs and the standby auto-promotes THEN the system SHALL behave as documented: both nodes accept writes independently. This is an inherent limitation of a 2-node active-standby design without a quorum mechanism and SHALL NOT be changed in scope.

7.2 WHEN `docs/HA_REPLICATION_GUIDE.md` describes the "Unplanned Failover" section THEN it SHALL include an explicit warning: "During a full network partition where neither node can reach the other, split-brain is NOT detectable until connectivity is restored. If auto-promote is enabled, both nodes may accept writes independently. Resolve by identifying which node served customer traffic and using 'Demote and Sync' on the stale primary once connectivity is restored."

7.3 WHEN the HA admin page displays the failover status THEN the auto-promote description text SHALL include: "Note: If the primary is also unreachable by the standby (full partition), split-brain detection will be inactive until connectivity is restored."

### BUG-HA-08 Expected (Base Compose WAL Settings)

8.1 WHEN `docker-compose.yml` configures the primary dev postgres THEN it SHALL explicitly set `max_wal_senders=10` and `max_replication_slots=10` in the postgres command list, making replication capability intentional and auditable.

### BUG-HA-09 Expected (Standby Dev Timeouts)

9.1 WHEN `docker-compose.ha-standby.yml` configures the standby dev postgres THEN it SHALL include `-c idle_in_transaction_session_timeout=30000` and `-c statement_timeout=30000` matching the production standby configuration in `docker-compose.standby-prod.yml`.

### BUG-HA-10 Expected (Accurate Lag Metric)

10.1 WHEN `get_replication_lag` queries replication lag THEN it SHALL use `last_msg_receipt_time` (time the standby last received a message from the primary, which includes data messages) instead of or in addition to `last_msg_send_time`:
```sql
SELECT EXTRACT(EPOCH FROM (now() - GREATEST(last_msg_send_time, last_msg_receipt_time)))
FROM pg_stat_subscription WHERE subname = :name
```

10.2 WHEN the primary is accessible THEN `get_replication_status` SHALL also attempt to read `write_lag` from `pg_stat_replication` (via a direct peer DB connection if available) as a secondary, more accurate lag source.

10.3 WHEN the lag metric is used in the promote safety guard THEN the guard SHALL use the highest of all available lag measures (subscription-side and replication-side) to be conservative.

### BUG-HA-11 Expected (pg_hba.conf Restriction)

11.1 WHEN `scripts/generate_pg_certs.sh` or a new `scripts/configure_pg_hba.sh` runs THEN it SHALL append the correct `hostssl replication replicator <peer_ip>/32 scram-sha-256` rule to the postgres container's `pg_hba.conf` using `docker exec`.

11.2 WHEN `docs/HA_REPLICATION_GUIDE.md` describes the replication user setup THEN it SHALL include a concrete command to add the `pg_hba.conf` rule and reload PostgreSQL.

11.3 AS a minimum viable fix: the guide SHALL document a `docker exec ... psql -c "SELECT pg_reload_conf()"` command after manual `pg_hba.conf` edits, since `pg_hba.conf` inside a Docker container is editable via `docker exec`.

### BUG-HA-12 Expected (Multi-Worker Cache Invalidation)

12.1 WHEN `save_config` completes and needs to invalidate the heartbeat response cache THEN it SHALL write a Redis key `ha:hb_cache_dirty` with a 1-second TTL.

12.2 WHEN the heartbeat endpoint checks the cache THEN it SHALL first check for `ha:hb_cache_dirty` in Redis; if present, it SHALL skip the in-memory cache and re-query the DB.

12.3 WHEN Redis is unavailable THEN the cache invalidation SHALL fail silently and the existing 10-second TTL-based expiry SHALL take over as before.

### BUG-HA-13 Expected (WebSocket Write Protection)

13.1 WHEN `StandbyWriteProtectionMiddleware.__call__` receives a WebSocket connection THEN it SHALL apply the same path-allowlist check as HTTP requests: if the WebSocket path is not in `_STANDBY_ALLOWED_PREFIXES`, it SHALL close the connection with a 503 close code and message.

13.2 WHEN a WebSocket path starts with `/api/v1/ha/` THEN it SHALL be allowed through on standby nodes.

13.3 WHEN the kitchen display WebSocket (`/ws/kitchen/...`) is accessed on a standby node THEN it SHALL be allowed through because it is read-only (Redis pub/sub subscriber only, no DB writes). The allowlist SHALL include `/ws/kitchen/` explicitly.

### BUG-HA-14 Expected (Dead Letter Replication)

14.1 WHEN `init_primary` builds the publication table list THEN `dead_letter` SHALL be excluded from the publication alongside `ha_config`, so dead letter queue entries are not replicated to the standby.

14.2 WHEN the standby is promoted THEN it starts with an empty `dead_letter` table, ensuring no orphaned failed jobs from the old primary are re-processed.

14.3 WHEN `filter_tables_for_truncation` is called THEN `dead_letter` SHALL remain in the truncation list (since it is not published, truncating it on the standby is a no-op but harmless).

14.4 WHEN `truncate_all_tables` is called THEN `idempotency_keys` SHALL remain replicated (current behaviour is correct — idempotency keys from the primary should carry over to prevent double-processing of replayed requests).

### BUG-HA-15 Expected (Cluster Status Peer Role)

15.1 WHEN `HeartbeatService._ping_peer` parses a successful heartbeat response THEN it SHALL store `peer_role = data.get("role", "unknown")` as an instance attribute.

15.2 WHEN `get_cluster_status` builds the peer entry THEN it SHALL use `_heartbeat_service.peer_role` (the actual role from the last heartbeat) instead of inferring it as the opposite of the local role.

15.3 WHEN no heartbeat has been received yet (service just started) THEN `peer_role` SHALL default to `"unknown"` rather than inferring primary/standby.

15.4 WHEN the local node is in `standalone` mode THEN the peer entry SHALL show role `"unknown"` rather than the incorrectly inferred `"primary"`.

---

## Unchanged Behavior (Regression Prevention)

16.1 WHEN `init_standby` is called with `truncate_first=True` (existing path from `router.py`) THEN it SHALL CONTINUE TO truncate all public tables except `ha_config` before creating the subscription, exactly as today.

16.2 WHEN `init_primary` creates a new publication THEN it SHALL CONTINUE TO exclude `ha_config` from the publication, as today.

16.3 WHEN `filter_tables_for_truncation` is called THEN it SHALL CONTINUE TO always exclude `ha_config` from the truncation set.

16.4 WHEN the standby write-protection middleware blocks a write request THEN it SHALL CONTINUE TO return a 503 response with `{"detail": "...", "node_role": "...", "primary_endpoint": "..."}` exactly as today.

16.5 WHEN the heartbeat endpoint is called THEN it SHALL CONTINUE TO return an HMAC-signed JSON payload with all existing fields, and the response SHALL CONTINUE TO be served from the in-memory cache (10s TTL) to avoid DB queries on every ping.

16.6 WHEN `HAService.promote` is called THEN it SHALL CONTINUE TO check replication lag, stop the subscription, update the role, update the middleware cache, and write the audit log — with the sequence sync step added AFTER the existing steps, before returning.

16.7 WHEN `HAService.demote` is called THEN it SHALL CONTINUE TO update the role to standby, clear `promoted_at`, resume the subscription, update the middleware cache, and write the audit log, exactly as today.

16.8 WHEN auto-promote fires in `HeartbeatService._execute_auto_promote` THEN it SHALL CONTINUE TO use a dedicated `async_session_factory()` session (not the heartbeat loop's main context), as today.

16.9 WHEN `drop_replication_slot` validates a slot name THEN it SHALL CONTINUE TO use the regex `^[a-zA-Z0-9_]+$` to prevent SQL injection.

16.10 WHEN the standby dev postgres runs THEN it SHALL CONTINUE TO have `wal_level=logical` (unchanged), so it can act as a primary after promotion.

16.11 WHEN `create_replication_user` validates a username THEN it SHALL CONTINUE TO use the regex `^[a-zA-Z_][a-zA-Z0-9_]*$` and SHALL CONTINUE TO use `quote_ident` and `quote_literal` for the actual DDL.

16.12 WHEN background tasks run on a standby node THEN they SHALL CONTINUE TO be skipped per the `WRITE_TASKS` guard implemented in `app/tasks/scheduled.py` (from the ha-replication-improvements spec).

---

## Design

### Fix BUG-HA-01: Sequence Replication (Two-Phase Approach)

PostgreSQL 16 supports sequence replication natively. The fix uses a two-phase approach: (1) include sequences in the publication for ongoing sync, and (2) add a post-promotion sequence fast-forward as a safety net for any gap.

**Phase 1 — Publication includes sequences:**

In `ReplicationManager.init_primary`, after creating the table publication, add all sequences:

```python
# After creating the FOR TABLE publication:
await conn.execute(
    f"ALTER PUBLICATION {ReplicationManager.PUBLICATION_NAME} ADD ALL SEQUENCES"
)
```

This is a PostgreSQL 16 feature (`FOR ALL SEQUENCES` in publications). The subscription receives sequence changes automatically.

**Phase 2 — Post-promotion sequence fast-forward (safety net):**

Add a new static method `ReplicationManager.sync_sequences_post_promotion(db)` that runs on the node immediately after promotion:

```python
@staticmethod
async def sync_sequences_post_promotion(db: AsyncSession) -> dict:
    """Advance all sequences to be at least max(existing_id) + 1.
    
    Called after promotion to prevent duplicate key violations from
    any sequences that may not have been replicated (e.g. logical
    replication sequence support is PG16 only and may be disabled).
    """
    conn = await ReplicationManager._get_raw_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT s.relname AS seq_name, 
                   t.relname AS table_name,
                   a.attname AS col_name
            FROM pg_class s
            JOIN pg_depend d ON d.objid = s.oid
            JOIN pg_class t ON t.oid = d.refobjid
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
            WHERE s.relkind = 'S' AND d.deptype = 'a'
            AND t.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
            """
        )
        synced = 0
        for row in rows:
            try:
                max_val = await conn.fetchval(
                    f"SELECT COALESCE(MAX({row['col_name']}), 0) FROM {row['table_name']}"
                )
                await conn.execute(
                    f"SELECT setval('{row['seq_name']}', GREATEST($1 + 1, 1), false)",
                    max_val,
                )
                synced += 1
            except Exception as exc:
                logger.warning("Could not sync sequence %s: %s", row['seq_name'], exc)
        logger.info("Post-promotion sequence sync: %d sequences advanced", synced)
        return {"status": "ok", "sequences_synced": synced}
    finally:
        await conn.close()
```

Call `sync_sequences_post_promotion` in `HAService.promote()` after `set_node_role("primary", ...)`, and in `HeartbeatService._execute_auto_promote()` after the middleware update, before committing.

**Accurate lag fix:**

Replace `get_replication_lag` SQL with:
```sql
SELECT EXTRACT(EPOCH FROM (now() - GREATEST(last_msg_send_time, last_msg_receipt_time)))
FROM pg_stat_subscription WHERE subname = :name
```

---

### Fix BUG-HA-02: Resync Truncation

In `ReplicationManager.trigger_resync`, add truncation as the first step:

```python
@staticmethod
async def trigger_resync(db: AsyncSession, primary_conn_str: str) -> None:
    logger.info("Triggering full re-sync — truncating standby data first")
    # Step 1: truncate (raises RuntimeError on failure, aborts early)
    await ReplicationManager.truncate_all_tables()
    # Step 2: drop existing subscription
    await ReplicationManager.drop_subscription(db)
    # Step 3: recreate with copy_data=true
    sql = (
        f"CREATE SUBSCRIPTION {ReplicationManager.SUBSCRIPTION_NAME} "
        f"CONNECTION '{primary_conn_str}' "
        f"PUBLICATION {ReplicationManager.PUBLICATION_NAME} "
        f"WITH (copy_data = true)"
    )
    await ReplicationManager._exec_autocommit(db, sql)
    logger.info(
        "Subscription '%s' re-created with copy_data=true — full re-sync in progress",
        ReplicationManager.SUBSCRIPTION_NAME,
    )
```

---

### Fix BUG-HA-03: Hardcoded Credentials in Scripts

**`scripts/check_repl_status.sh`:** Replace `echo W4h3guru1# | sudo -S` with `sudo` (will prompt interactively, or rely on NOPASSWD in the Pi's sudoers). Remove the SSH heredoc blocks that embed the password; use `ssh nerdy@192.168.10.87` with SSH key auth (which is already configured per the steering deployment doc).

**`scripts/check_sync_status.sh`:** Same pattern — remove `echo W4h3guru1# | sudo -S` prefix from all commands.

**`scripts/fix_replication.sh`:** Remove the hardcoded `password=NoorHarleen1` from the SQL heredoc. Replace the connection string with a reference to an environment variable:
```bash
PEER_DB_URL="${HA_PEER_DB_URL:-postgresql://replicator:<password>@192.168.1.90:5432/workshoppro}"
```
Add a comment instructing the operator to set `HA_PEER_DB_URL` before running the script.

After removing credentials, document in the script header:
```bash
# Prerequisites:
# - SSH key auth configured to the standby (nerdy@192.168.10.87)
# - Sudoers configured with NOPASSWD for docker commands on the standby
# - HA_PEER_DB_URL environment variable set with the replication connection string
```

---

### Fix BUG-HA-04: Startup Heartbeat Uses Correct Secret

In `app/main.py` inside `_start_ha_heartbeat()`, change the secret retrieval to use the DB-stored secret:

```python
# BEFORE (broken):
secret = os.environ.get("HA_HEARTBEAT_SECRET", "")

# AFTER (correct):
from app.modules.ha.service import _get_heartbeat_secret_from_config
secret = _get_heartbeat_secret_from_config(config._raw_orm_obj_or_none)
```

Since `HAService.get_config` returns a schema object (not the ORM object), the startup code must load the ORM object directly to pass it to `_get_heartbeat_secret_from_config`. Refactor `_start_ha_heartbeat` to load `HAConfig` via ORM directly (the pattern is already used elsewhere in the file):

```python
async with async_session_factory() as session:
    async with session.begin():
        from app.modules.ha.models import HAConfig
        from sqlalchemy import select
        result = await session.execute(select(HAConfig).limit(1))
        cfg_orm = result.scalars().first()
        if cfg_orm is not None:
            set_node_role(cfg_orm.role, cfg_orm.peer_endpoint)
            if cfg_orm.peer_endpoint:
                from app.modules.ha.service import _get_heartbeat_secret_from_config
                secret = _get_heartbeat_secret_from_config(cfg_orm)
                hb = HeartbeatService(
                    peer_endpoint=cfg_orm.peer_endpoint,
                    interval=cfg_orm.heartbeat_interval_seconds,
                    secret=secret,
                    local_role=cfg_orm.role,
                )
                ha_svc_module._heartbeat_service = hb
                await hb.start()
```

Note: the current startup code also does not pass `local_role=cfg_orm.role` to `HeartbeatService`, which means split-brain detection (`detect_split_brain(self.local_role, peer_role)`) would always compare `"standalone"` against the peer's role. This shall be fixed in the same change.

---

### Fix BUG-HA-05: WAL Disk Space Guard in Compose Files

**`docker-compose.pi.yml`** (primary prod) — add to postgres command:
```yaml
- "-c"
- "max_slot_wal_keep_size=2048"  # 2GB ceiling; invalidates slot before disk fills
```
Change `max_replication_slots=150` to `max_replication_slots=10`.

**`docker-compose.yml`** (base/primary dev) — add to postgres command (if present) or add a new section for replication:
```yaml
- "-c"
- "max_wal_senders=10"
- "-c"
- "max_replication_slots=10"
- "-c"
- "wal_level=logical"
```
(Note: `wal_level=logical` is already present; consolidate.)

**`docker-compose.standby-prod.yml`** — add the same `max_slot_wal_keep_size=2048` for the standby postgres (in case the standby is ever promoted to primary, it should already have the guard configured).

---

### Fix BUG-HA-06: Multi-Worker Heartbeat Isolation

The core fix uses a Redis distributed lock to ensure only one worker runs the heartbeat service at a time.

**In `app/main.py` `_start_ha_heartbeat()`:**

```python
async def _start_ha_heartbeat() -> None:
    import asyncio, os, logging
    logger = logging.getLogger(__name__)
    
    # Use Redis distributed lock so only one gunicorn worker runs heartbeat.
    # Lock TTL = 3× heartbeat interval (default 30s) so another worker can
    # take over if this one dies.
    LOCK_KEY = "ha:heartbeat_lock"
    LOCK_TTL = 30  # seconds
    
    try:
        from app.core.redis import get_redis_client
        redis = await get_redis_client()
        worker_id = os.getpid()
        acquired = await redis.set(LOCK_KEY, worker_id, nx=True, ex=LOCK_TTL)
        if not acquired:
            logger.info(
                "Heartbeat lock already held by another worker — skipping heartbeat start in PID %d",
                worker_id,
            )
            return
        logger.info("Heartbeat lock acquired by PID %d", worker_id)
    except Exception as exc:
        logger.warning("Could not acquire Redis heartbeat lock: %s — starting anyway", exc)
    
    # ... existing startup logic (load config, create HeartbeatService) ...
    
    # Extend lock periodically inside the heartbeat loop (add to HeartbeatService._ping_loop):
    # await redis.expire(LOCK_KEY, LOCK_TTL)
```

**In `HeartbeatService._ping_loop`** — extend the lock TTL on each successful cycle:
```python
# At top of _ping_loop, store lock context
# After each successful ping cycle:
try:
    if self._redis_lock_key and self._redis_client:
        await self._redis_client.expire(self._redis_lock_key, self._lock_ttl)
except Exception:
    pass  # Non-critical; another worker will take over when lock expires
```

**For `_execute_auto_promote`** — add a separate promotion lock:
```python
PROMOTE_LOCK_KEY = "ha:auto_promote_lock"
acquired = await redis.set(PROMOTE_LOCK_KEY, worker_id, nx=True, ex=60)
if not acquired:
    logger.info("Auto-promote lock held by another worker — skipping")
    return
```

**For `_hb_cache` invalidation across workers** — in `save_config`:
```python
# After existing cache invalidation:
try:
    from app.core.redis import get_redis_client
    redis = await get_redis_client()
    await redis.set("ha:hb_cache_dirty", "1", ex=15)
except Exception:
    pass  # Non-critical — cache expires naturally
```

In the `heartbeat` endpoint handler — check dirty flag:
```python
try:
    from app.core.redis import get_redis_client as _get_redis
    _redis = await _get_redis()
    if await _redis.get("ha:hb_cache_dirty"):
        _hb_cache["ts"] = 0  # force cache miss
        await _redis.delete("ha:hb_cache_dirty")
except Exception:
    pass  # Redis unavailable — fall back to TTL-based expiry
```

---

### Fix BUG-HA-07: Document Network Partition Limitation

No code changes. Add to `docs/HA_REPLICATION_GUIDE.md` under **Failover and Recovery Procedures → Unplanned Failover**:

```markdown
> **Warning — Network Partition (Full Isolation):** During a network partition where 
> neither node can reach the other, split-brain detection is inactive because it relies 
> on successful heartbeat communication. If auto-promote is enabled, the standby will 
> promote after the failover timeout, resulting in two independent primaries with diverging 
> data. This is an inherent limitation of a 2-node design without a quorum mechanism.
> 
> To recover: identify which node served customer traffic after the split, use 
> "Demote and Sync" on the stale primary once connectivity is restored. Any data written 
> to the stale primary since the split will be lost.
```

Also update the HA admin frontend to add a tooltip on the auto-promote toggle explaining this limitation.

---

### Fix BUG-HA-08: Base Compose Explicit WAL Settings

In `docker-compose.yml` postgres `command:` section, add after the existing `wal_level=logical` entry:
```yaml
- "-c"
- "max_wal_senders=10"
- "-c"
- "max_replication_slots=10"
```

---

### Fix BUG-HA-09: Standby Dev Compose Timeouts

In `docker-compose.ha-standby.yml` postgres `command:` section, add before the closing line:
```yaml
- "-c"
- "idle_in_transaction_session_timeout=30000"
- "-c"
- "statement_timeout=30000"
```

---

### Fix BUG-HA-10: Accurate Lag Metric

In `ReplicationManager.get_replication_lag`, change the SQL to use the more accurate receipt time:

```python
result = await db.execute(
    text(
        "SELECT EXTRACT(EPOCH FROM "
        "  (now() - GREATEST(last_msg_send_time, last_msg_receipt_time))) "
        "FROM pg_stat_subscription "
        "WHERE subname = :name"
    ),
    {"name": ReplicationManager.SUBSCRIPTION_NAME},
)
```

In `get_replication_status`, apply the same change to the lag computation there. Add a comment explaining why `GREATEST(send, receipt)` is used: receipt time is only updated when data arrives, making it a more accurate lag indicator during active replication.

---

### Fix BUG-HA-11: Document and Script pg_hba.conf

Create `scripts/configure_pg_hba.sh`:

```bash
#!/bin/bash
# Adds IP-restricted replication rule to pg_hba.conf inside the Docker container.
# Run on EACH node after initial setup, replacing <PEER_IP> with the peer's LAN IP.
# Usage: bash scripts/configure_pg_hba.sh <container_name> <peer_ip>
set -e
CONTAINER="${1:?Usage: $0 <container_name> <peer_ip>}"
PEER_IP="${2:?Usage: $0 <container_name> <peer_ip>}"

docker exec "$CONTAINER" bash -c "
  echo 'hostssl replication replicator ${PEER_IP}/32 scram-sha-256' >> /var/lib/postgresql/data/pg_hba.conf
  echo 'hostssl all replicator ${PEER_IP}/32 scram-sha-256' >> /var/lib/postgresql/data/pg_hba.conf
"
docker exec "$CONTAINER" psql -U postgres -c "SELECT pg_reload_conf()"
echo "pg_hba.conf updated and reloaded for peer IP: ${PEER_IP}"
```

Add a reference to this script in `docs/HA_REPLICATION_GUIDE.md` under **Database Password and Security Considerations → Restrict pg_hba.conf Access**.

---

### Fix BUG-HA-12: Multi-Worker Cache Invalidation

Covered by the Redis dirty-flag mechanism described in Fix BUG-HA-06.

---

### Fix BUG-HA-13: WebSocket Write Protection

In `StandbyWriteProtectionMiddleware.__call__`:

```python
async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
    scope_type = scope["type"]
    
    if scope_type == "http":
        request = Request(scope)
        if should_block_request(request.method, request.url.path, _node_role, _split_brain_blocked):
            # ... existing 503 response ...
            return
        await self.app(scope, receive, send)
        return
    
    if scope_type == "websocket":
        path = scope.get("path", "")
        # Allow read-only WebSocket paths explicitly
        _WS_ALLOWED_PREFIXES = ("/ws/kitchen/", "/api/v1/ha/")
        if _node_role == "standby" or _split_brain_blocked:
            if not any(path.startswith(p) for p in _WS_ALLOWED_PREFIXES):
                # Close WebSocket with 503
                await send({
                    "type": "websocket.close",
                    "code": 1013,  # 1013 = Try Again Later
                    "reason": "This node is in standby mode. Writes not accepted.",
                })
                return
    
    await self.app(scope, receive, send)
```

---

### Fix BUG-HA-14: Exclude `dead_letter` from Publication

In `ReplicationManager.init_primary`, change the table exclusion query:

```python
# BEFORE:
"WHERE schemaname = 'public' AND tablename != 'ha_config'"

# AFTER:
"WHERE schemaname = 'public' AND tablename NOT IN ('ha_config', 'dead_letter_queue')"
```

Check the actual table name used by `app/models/dead_letter.py` and use that exact name.

Also update `filter_tables_for_truncation` to document (in a comment) why `ha_config` is excluded but `dead_letter_queue` is NOT excluded from truncation (truncating it on standby init is safe since it's not replicated, and restoring it from primary would bring stale failed jobs anyway).

---

### Fix BUG-HA-15: Accurate Peer Role in Cluster Status

In `HeartbeatService`, add instance state for peer role:

```python
# In __init__:
self.peer_role: str = "unknown"

# In _ping_peer(), after parsing the response:
self.peer_role = data.get("role", "unknown")
```

In `HAService.get_cluster_status`, use the actual peer role:

```python
# BEFORE:
peer_role = "standby" if cfg.role == "primary" else "primary"

# AFTER:
peer_role = _heartbeat_service.peer_role if _heartbeat_service is not None else "unknown"
```

---

## Implementation Tasks

Tasks are ordered by severity. Each task maps to a specific file change and can be implemented independently.

### Task 1 — Fix sequence replication (Critical, BUG-HA-01)
- **File:** `app/modules/ha/replication.py`
- Add `FOR ALL SEQUENCES` to publication via `ALTER PUBLICATION ... ADD ALL SEQUENCES` after `CREATE PUBLICATION` in `init_primary`.
- Add new `sync_sequences_post_promotion(db)` static method.
- Call `sync_sequences_post_promotion` in `HAService.promote()` after `set_node_role`.
- Call `sync_sequences_post_promotion` in `HeartbeatService._execute_auto_promote()` after `set_node_role`.
- Fix lag query in `get_replication_lag` and `get_replication_status` to use `GREATEST(last_msg_send_time, last_msg_receipt_time)`.

### Task 2 — Fix trigger_resync truncation (Critical, BUG-HA-02)
- **File:** `app/modules/ha/replication.py`
- In `trigger_resync`: call `await ReplicationManager.truncate_all_tables()` as the first step before `drop_subscription`.
- Add log statement: "Triggered re-sync: truncating standby tables first."

### Task 3 — Remove hardcoded credentials from scripts (Significant, BUG-HA-03)
- **Files:** `scripts/check_repl_status.sh`, `scripts/check_sync_status.sh`, `scripts/fix_replication.sh`
- Remove all `echo W4h3guru1# | sudo -S` prefixes. Replace with bare `sudo` (requires NOPASSWD or interactive prompt).
- Remove `password=NoorHarleen1` from `fix_replication.sh`. Replace connection string with `${HA_PEER_DB_URL}` variable reference.
- Add header comment to each script documenting prerequisites.
- Rotate the leaked credentials on the production server (`ALTER USER replicator WITH PASSWORD '<new_password>'`; change sudo password for `nerdy`).

### Task 4 — Fix startup heartbeat uses DB-stored secret (Significant, BUG-HA-04)
- **File:** `app/main.py`
- In `_start_ha_heartbeat()`: load ORM `HAConfig` object directly and pass it to `_get_heartbeat_secret_from_config(cfg_orm)`.
- Also pass `local_role=cfg_orm.role` to `HeartbeatService(...)` constructor (currently omitted at startup).

### Task 5 — Add WAL disk guard to compose files (Significant, BUG-HA-05)
- **File:** `docker-compose.pi.yml`: add `max_slot_wal_keep_size=2048`, reduce `max_replication_slots` from 150 to 10.
- **File:** `docker-compose.yml`: add explicit `max_wal_senders=10`, `max_replication_slots=10` (consolidate existing `wal_level=logical`).
- **File:** `docker-compose.standby-prod.yml`: add `max_slot_wal_keep_size=2048`.

### Task 6 — Add Redis distributed lock for multi-worker heartbeat (Significant, BUG-HA-06)
- **Files:** `app/main.py`, `app/modules/ha/heartbeat.py`, `app/modules/ha/router.py`, `app/modules/ha/service.py`
- Add Redis lock acquisition in `_start_ha_heartbeat()`.
- Extend lock TTL each heartbeat cycle in `HeartbeatService._ping_loop`.
- Add Redis lock in `_execute_auto_promote()`.
- Add Redis dirty-flag for cache invalidation in `save_config` and read it in the heartbeat endpoint.

### Task 7 — Document network partition split-brain limitation (Moderate, BUG-HA-07)
- **File:** `docs/HA_REPLICATION_GUIDE.md`
- Add warning block to the Unplanned Failover section.
- **File:** `frontend/src/pages/admin/HAReplication.tsx` (or relevant frontend component)
- Add tooltip text on the auto-promote toggle.

### Task 8 — Add explicit WAL settings to base compose (Moderate, BUG-HA-08)
- **File:** `docker-compose.yml`
- Add `max_wal_senders=10` and `max_replication_slots=10` to postgres command.

### Task 9 — Add timeouts to standby dev compose (Moderate, BUG-HA-09)
- **File:** `docker-compose.ha-standby.yml`
- Add `idle_in_transaction_session_timeout=30000` and `statement_timeout=30000` to postgres command.

### Task 10 — Fix replication lag accuracy (Moderate, BUG-HA-10)
- **File:** `app/modules/ha/replication.py`
- Update `get_replication_lag` and `get_replication_status` SQL to use `GREATEST(last_msg_send_time, last_msg_receipt_time)`.

### Task 11 — Add pg_hba.conf restriction script (Moderate, BUG-HA-11)
- **File (new):** `scripts/configure_pg_hba.sh`
- Create script that appends IP-specific replication rules to the postgres container's `pg_hba.conf` and reloads it.
- **File:** `docs/HA_REPLICATION_GUIDE.md`
- Add reference to the new script in the Security section.

### Task 12 — Fix WebSocket write protection (Minor, BUG-HA-13)
- **File:** `app/modules/ha/middleware.py`
- Extend `__call__` to handle `scope["type"] == "websocket"` with path allowlist check.

### Task 13 — Exclude `dead_letter` from publication (Minor, BUG-HA-14)
- **File:** `app/modules/ha/replication.py`
- In `init_primary`: change exclusion from `!= 'ha_config'` to `NOT IN ('ha_config', '<dead_letter_table_name>')`.
- Verify actual table name from `app/models/dead_letter.py`.

### Task 14 — Fix peer role in cluster status (Minor, BUG-HA-15)
- **File:** `app/modules/ha/heartbeat.py`
- Add `self.peer_role: str = "unknown"` to `__init__`.
- Set `self.peer_role = data.get("role", "unknown")` in `_ping_peer()` on successful response.
- **File:** `app/modules/ha/service.py`
- In `get_cluster_status`: use `_heartbeat_service.peer_role` instead of the inferred opposite role.

### Task 15 — Log issues in ISSUE_TRACKER.md
- **File:** `docs/ISSUE_TRACKER.md`
- Add ISSUE entries for each bug (ISSUE-107 through ISSUE-121 or as appropriate following the current sequence).
- Each entry must include: date, severity, status, symptoms, root cause, fix applied, files changed, as per `steering/issue-tracking-workflow.md`.

---

## Testing Checklist

After implementing each task, verify the following before marking resolved:

- [ ] **Task 1 (Sequences):** After init_standby + promote, run `SELECT nextval('organisations_id_seq')` — it must return a value higher than the current MAX(id). Verify the first INSERT after promotion succeeds without duplicate key error.
- [ ] **Task 2 (Resync):** Call `POST /api/v1/ha/replication/resync` on a standby with existing data. Verify no duplicate key error in logs and subscription status transitions to `active`.
- [ ] **Task 3 (Credentials):** Run `git log -p scripts/` — verify no password strings are present in any commit. Confirm the scripts run correctly with SSH key auth.
- [ ] **Task 4 (Startup secret):** Set heartbeat secret via UI, restart app container, verify heartbeat HMAC succeeds (no "Invalid HMAC signature" in logs).
- [ ] **Task 5 (WAL guard):** Set `max_slot_wal_keep_size=512MB` temporarily, let the standby fall behind, verify the slot is invalidated (not disk-fill). Restore to 2048.
- [ ] **Task 6 (Multi-worker):** Start with `--workers 2`, verify Redis key `ha:heartbeat_lock` exists with one PID, and only one set of heartbeat pings reaches the standby every 10s.
- [ ] **Task 7 (Docs):** Review the updated `HA_REPLICATION_GUIDE.md` partition warning section for accuracy and completeness.
- [ ] **Task 8 (Base compose):** `docker compose exec postgres psql -U postgres -c "SHOW max_wal_senders"` returns `10`.
- [ ] **Task 9 (Standby timeouts):** `docker compose -f docker-compose.ha-standby.yml exec postgres psql -U postgres -c "SHOW statement_timeout"` returns `30000`.
- [ ] **Task 10 (Lag metric):** Under zero write activity on primary, `GET /api/v1/ha/replication/status` should NOT report near-zero lag; it should reflect actual WAL position difference.
- [ ] **Task 11 (pg_hba):** Run `scripts/configure_pg_hba.sh` against a test container. Verify `pg_hba.conf` contains the new rule and `pg_reload_conf()` returns true.
- [ ] **Task 12 (WebSocket):** Connect to `ws://localhost:8081/ws/kitchen/test-org/all` on a standby node — verify the connection is allowed. Try a hypothetical write WebSocket path not in the allowlist — verify close code 1013.
- [ ] **Task 13 (dead_letter):** After `init_primary`, query `SELECT tablename FROM pg_publication_tables WHERE pubname = 'orainvoice_ha_pub' AND tablename = 'dead_letter_queue'` — must return 0 rows.
- [ ] **Task 14 (Peer role):** In standalone mode, `GET /api/v1/ha/cluster-status` peer entry should show `role: "unknown"`, not `role: "primary"`.
- [ ] **Task 15 (Issue tracker):** All 15 issues are logged with correct severity and status `resolved`.

---

## Risk Assessment

| Task | Risk of Regression | Mitigation |
|------|--------------------|------------|
| 1 — Sequence replication | Medium — alters publication DDL; PG16 required | Verify PG16 version before altering; sequence sync is additive |
| 2 — Resync truncation | Low — adds truncation as first step; same logic used in init_standby | Existing test coverage on truncation function |
| 3 — Script credentials | Zero for app code; rotate credentials separately | Rotate before removing from scripts |
| 4 — Startup secret | Low — changes secret source, same interface | Verify HMAC succeeds after restart |
| 5 — WAL guard | Low — additive postgres config | Test slot invalidation behaviour before production |
| 6 — Multi-worker lock | Medium — new Redis dependency in startup | Fallback: if Redis unavailable, log warning and proceed without lock |
| 7 — Docs | Zero | Review only |
| 8/9 — Compose timeouts | Low — additive config | Existing compose tests |
| 10 — Lag metric | Low — SQL change only; same return type | Verify no NULL when no messages received |
| 11 — pg_hba script | Low — script only, no app code | Test against a dev container |
| 12 — WebSocket middleware | Low — new branch for websocket type | Kitchen display WS must still work on primary |
| 13 — Dead letter exclusion | Low — narrows publication set | Verify dead_letter not in publication after re-init |
| 14 — Peer role | Low — read-only display fix | No data path affected |
| 15 — Issue tracker | Zero | Documentation only |
