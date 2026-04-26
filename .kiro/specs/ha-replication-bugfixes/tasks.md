# HA Replication Bugfixes — Implementation Tasks

## Overview

15 implementation tasks covering all confirmed HA replication bugs, ordered by severity (critical → significant → moderate → minor). Each parent task maps to one bug. Sub-tasks break down the specific code changes with file paths and requirements references. Checkpoint tasks are included after critical and significant fix groups.

---

## Tasks

### Critical Fixes

- [x] 1. Fix sequence replication (Critical, BUG-HA-01)
  - [x] 1.1 Add `ALTER PUBLICATION ... ADD ALL SEQUENCES` after `CREATE PUBLICATION` in `init_primary` in `app/modules/ha/replication.py`
  - [x] 1.2 Add `sync_sequences_post_promotion()` static method to `ReplicationManager` in `app/modules/ha/replication.py`
  - [x] 1.3 Call sequence sync in `HAService.promote()` after `set_node_role` in `app/modules/ha/service.py`
  - [x] 1.4 Call sequence sync in `HeartbeatService._execute_auto_promote()` after `set_node_role` in `app/modules/ha/heartbeat.py`
  - [x] 1.5 Fix lag query to use `GREATEST(last_msg_send_time, last_msg_receipt_time)` in `get_replication_lag` and `get_replication_status` in `app/modules/ha/replication.py`

- [x] 2. Fix trigger_resync truncation (Critical, BUG-HA-02)
  - [x] 2.1 Add `await ReplicationManager.truncate_all_tables()` as first step in `trigger_resync` before `drop_subscription` in `app/modules/ha/replication.py`
  - [x] 2.2 Add log statement: "Triggered re-sync: truncating standby tables first" in `app/modules/ha/replication.py`

- [x] 3. Checkpoint: verify critical fixes
  - [x] 3.1 Verify sequence replication: after init_standby + promote, `SELECT nextval('organisations_id_seq')` returns value > MAX(id); first INSERT succeeds
  - [x] 3.2 Verify resync: `POST /api/v1/ha/replication/resync` on standby with existing data produces no duplicate key errors; subscription transitions to `active`

### Significant Fixes

- [x] 4. Remove hardcoded credentials from scripts (Significant, BUG-HA-03)
  - [x] 4.1 Remove all `echo W4h3guru1# | sudo -S` prefixes from `scripts/check_repl_status.sh` — replace with bare `sudo`
  - [x] 4.2 Remove all `echo W4h3guru1# | sudo -S` prefixes from `scripts/check_sync_status.sh` — replace with bare `sudo`
  - [x] 4.3 Remove hardcoded `password=NoorHarleen1` from `scripts/fix_replication.sh` — replace connection string with `${HA_PEER_DB_URL}` variable reference
  - [x] 4.4 Add prerequisite header comments to all three scripts documenting SSH key auth, NOPASSWD sudoers, and env var requirements
  - [x] 4.5 Rotate leaked credentials on production server (`ALTER USER replicator WITH PASSWORD`; change sudo password)

- [x] 5. Fix startup heartbeat uses DB-stored secret (Significant, BUG-HA-04)
  - [x] 5.1 In `_start_ha_heartbeat()` in `app/main.py`: load ORM `HAConfig` object directly via `select(HAConfig).limit(1)`
  - [x] 5.2 Pass ORM object to `_get_heartbeat_secret_from_config(cfg_orm)` instead of `os.environ.get("HA_HEARTBEAT_SECRET", "")`
  - [x] 5.3 Pass `local_role=cfg_orm.role` to `HeartbeatService(...)` constructor (currently omitted at startup)

- [x] 6. Add WAL disk guard to compose files (Significant, BUG-HA-05)
  - [x] 6.1 In `docker-compose.pi.yml`: add `-c max_slot_wal_keep_size=2048` to postgres command
  - [x] 6.2 In `docker-compose.pi.yml`: change `max_replication_slots=150` to `max_replication_slots=10`
  - [x] 6.3 In `docker-compose.yml`: add explicit `-c max_wal_senders=10` and `-c max_replication_slots=10` to postgres command
  - [x] 6.4 In `docker-compose.standby-prod.yml`: add `-c max_slot_wal_keep_size=2048` to postgres command

- [x] 7. Add Redis distributed lock for multi-worker heartbeat (Significant, BUG-HA-06)
  - [x] 7.1 Add Redis lock acquisition (`SET NX EX`) in `_start_ha_heartbeat()` in `app/main.py` — skip heartbeat start if lock not acquired
  - [x] 7.2 Add lock TTL renewal in `HeartbeatService._ping_loop` in `app/modules/ha/heartbeat.py` after each successful ping cycle
  - [x] 7.3 Add separate Redis promotion lock in `_execute_auto_promote()` in `app/modules/ha/heartbeat.py`
  - [x] 7.4 Add Redis dirty-flag write (`ha:hb_cache_dirty`) in `save_config` in `app/modules/ha/service.py` for cross-worker cache invalidation
  - [x] 7.5 Add Redis dirty-flag check in heartbeat endpoint handler in `app/modules/ha/router.py` — force cache miss if dirty flag present

- [x] 8. Checkpoint: verify significant fixes
  - [x] 8.1 Verify credentials: `git log -p scripts/` shows no password strings; scripts run with SSH key auth
  - [x] 8.2 Verify startup secret: set heartbeat secret via UI, restart container, confirm no "Invalid HMAC signature" in logs
  - [x] 8.3 Verify WAL guard: `SHOW max_slot_wal_keep_size` returns `2048MB` on pi compose
  - [x] 8.4 Verify multi-worker: start with `--workers 2`, confirm Redis key `ha:heartbeat_lock` exists with one PID; only one set of pings per interval

### Moderate Fixes

- [x] 9. Document network partition split-brain limitation (Moderate, BUG-HA-07)
  - [x] 9.1 Add network partition warning block to `docs/HA_REPLICATION_GUIDE.md` under Unplanned Failover section
  - [x] 9.2 Add tooltip text on auto-promote toggle in HA admin frontend component

- [x] 10. Add explicit WAL settings to base compose (Moderate, BUG-HA-08)
  - [x] 10.1 Add `-c max_wal_senders=10` and `-c max_replication_slots=10` to postgres command in `docker-compose.yml`

- [x] 11. Add timeouts to standby dev compose (Moderate, BUG-HA-09)
  - [x] 11.1 Add `-c idle_in_transaction_session_timeout=30000` and `-c statement_timeout=30000` to postgres command in `docker-compose.ha-standby.yml`

- [x] 12. Fix replication lag accuracy (Moderate, BUG-HA-10)
  - [x] 12.1 Update `get_replication_lag` SQL to use `GREATEST(last_msg_send_time, last_msg_receipt_time)` in `app/modules/ha/replication.py`
  - [x] 12.2 Update `get_replication_status` SQL to use the same `GREATEST` lag computation in `app/modules/ha/replication.py`
  - [x] 12.3 Add comment explaining why `GREATEST(send, receipt)` is used

- [x] 13. Add pg_hba.conf restriction script (Moderate, BUG-HA-11)
  - [x] 13.1 Create `scripts/configure_pg_hba.sh` — appends IP-specific replication rules to postgres container's `pg_hba.conf` and reloads
  - [x] 13.2 Add reference to the new script in `docs/HA_REPLICATION_GUIDE.md` under the Security section

### Minor Fixes

- [x] 14. Fix WebSocket write protection (Minor, BUG-HA-13)
  - [x] 14.1 Extend `StandbyWriteProtectionMiddleware.__call__` in `app/modules/ha/middleware.py` to handle `scope["type"] == "websocket"`
  - [x] 14.2 Add WebSocket path allowlist (`/ws/kitchen/`, `/api/v1/ha/`) — block non-allowlisted paths with close code 1013 on standby

- [x] 15. Exclude `dead_letter` from publication (Minor, BUG-HA-14)
  - [x] 15.1 In `init_primary` in `app/modules/ha/replication.py`: change exclusion from `!= 'ha_config'` to `NOT IN ('ha_config', '<dead_letter_table_name>')`
  - [x] 15.2 Verify actual table name from `app/models/dead_letter.py` and use exact name
  - [x] 15.3 Add comment in `filter_tables_for_truncation` explaining why `dead_letter` is excluded from publication but not from truncation

- [x] 16. Fix peer role in cluster status (Minor, BUG-HA-15)
  - [x] 16.1 Add `self.peer_role: str = "unknown"` to `HeartbeatService.__init__` in `app/modules/ha/heartbeat.py`
  - [x] 16.2 Set `self.peer_role = data.get("role", "unknown")` in `_ping_peer()` on successful response in `app/modules/ha/heartbeat.py`
  - [x] 16.3 In `get_cluster_status` in `app/modules/ha/service.py`: use `_heartbeat_service.peer_role` instead of inferred opposite role

- [x] 17. Log all issues in ISSUE_TRACKER.md (Minor, all bugs)
  - [x] 17.1 Add ISSUE entries (ISSUE-107 through ISSUE-121 or next available) to `docs/ISSUE_TRACKER.md` for all 15 bugs
  - [x] 17.2 Each entry includes: date, severity, status, symptoms, root cause, fix applied, files changed (per `steering/issue-tracking-workflow.md`)

---

## Notes

### Severity and Risk Summary

| Priority | Tasks | Risk Level | Key Mitigation |
|----------|-------|------------|----------------|
| Critical | 1–2 | Medium | Verify PG16 before altering publication; truncation uses existing tested function |
| Significant | 4–7 | Low–Medium | Redis lock has fallback (proceed without lock); credential rotation is separate step |
| Moderate | 9–13 | Low | All additive config or documentation changes; no existing behavior removed |
| Minor | 14–17 | Low–Zero | Narrow scope changes; display-only fixes; documentation |

### Implementation Order

1. **Critical fixes first** (Tasks 1–2) — these block real-world failover
2. **Checkpoint** (Task 3) — verify critical fixes before proceeding
3. **Significant fixes** (Tasks 4–7) — operational hazards and security
4. **Checkpoint** (Task 8) — verify significant fixes
5. **Moderate fixes** (Tasks 9–13) — accuracy, consistency, documentation
6. **Minor fixes** (Tasks 14–17) — defensive improvements and logging

### Testing References

All testing procedures are documented in the Testing Strategy section of `design.md`. Each task's verification maps to a specific test in that checklist. Manual testing against a local HA standby setup is required for Tasks 1, 2, 4, 5, 6, and 12.

### Dependencies

- Task 7 (multi-worker lock) depends on Redis being available — includes fallback for Redis-unavailable scenarios
- Task 12 (lag accuracy fix) overlaps with Task 1.5 — implement together to avoid double-editing the same SQL
- Task 6.3 (base compose WAL settings) overlaps with Task 10.1 — can be combined into a single compose edit
- BUG-HA-12 (cache invalidation) is fully covered by Task 7 (multi-worker isolation) — no separate task needed
