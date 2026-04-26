# HA Replication — Gap Analysis

Audit date: 2026-04-26  
Scope: all files under `app/modules/ha/`, all docker-compose files, `app/main.py`, and `scripts/` related to replication.

---

## CRITICAL

### 1. Sequences not replicated — post-promotion duplicate key violations
**File:** [`app/modules/ha/replication.py:183`](../app/modules/ha/replication.py#L183)

The publication is created as `FOR TABLE table1, table2, ...` — this replicates row data only, not sequences. On the standby, all sequences remain at their initial values (typically `1`) because `INSERT` operations arriving via logical replication do not advance sequences. After promotion, the first `INSERT` on the new primary calls `nextval()` → returns `1` → primary key already exists in replicated data → **duplicate key violation on every table**.

PostgreSQL 16 supports `FOR ALL SEQUENCES` in a publication, and subscriptions can enable sequence replication. The current code never does this. A promotion without sequence synchronization is broken in production.

**Fix direction:** Change the publication to `CREATE PUBLICATION ... FOR ALL TABLES, ALL SEQUENCES` (PG 16+), or add a post-promotion step that runs `SELECT setval(seq, MAX(id)) FROM table` for all auto-increment columns.

---

### 2. `trigger_resync` doesn't truncate the standby first
**File:** [`app/modules/ha/replication.py:400`](../app/modules/ha/replication.py#L400)

`trigger_resync` drops and recreates the subscription with `copy_data=true`, but does **not** call `truncate_all_tables()` first. PostgreSQL logical replication initial copy does not truncate the target tables before copying. If the standby already has rows (which it will after a previous subscription), the re-sync fails with duplicate primary key errors on every table.

Compare `init_standby` which correctly passes `truncate_first=True` from [`app/modules/ha/router.py:448`](../app/modules/ha/router.py#L448) — `trigger_resync` is missing this step entirely.

**Fix direction:** Add `await ReplicationManager.truncate_all_tables()` at the start of `trigger_resync`, before dropping the subscription.

---

## SIGNIFICANT

### 3. Hardcoded credentials in committed scripts
**Files:** [`scripts/check_repl_status.sh:20`](../scripts/check_repl_status.sh#L20), [`scripts/check_sync_status.sh:5`](../scripts/check_sync_status.sh#L5), [`scripts/fix_replication.sh:8`](../scripts/fix_replication.sh#L8)

The following are committed to the repository in plaintext:
- `W4h3guru1#` — sudo password (in `check_repl_status.sh`, `check_sync_status.sh`, `fix_replication.sh`)
- `password=NoorHarleen1` — live replication user password (in `fix_replication.sh:45`)

These are in git history and must be rotated. The scripts should use `sudo -S` with a prompt or `ssh -i` with keys rather than embedding passwords.

---

### 4. Startup heartbeat ignores DB-stored heartbeat secret
**File:** [`app/main.py:657`](../app/main.py#L657)

In `_start_ha_heartbeat`, the heartbeat service is initialized with:
```python
secret = os.environ.get("HA_HEARTBEAT_SECRET", "")
```
It does **not** call `_get_heartbeat_secret_from_config(cfg)`, which reads and decrypts the DB-stored secret. The per-save path in `HAService.save_config` correctly uses `_get_heartbeat_secret_from_config`, but after every container restart the heartbeat service falls back to the env var only — silently ignoring any secret configured through the admin UI.

If the admin sets the heartbeat secret via the UI without also setting `HA_HEARTBEAT_SECRET` in the environment, HMAC verification fails on every heartbeat ping after a restart.

**Fix direction:** Replace `os.environ.get("HA_HEARTBEAT_SECRET", "")` in `_start_ha_heartbeat` with a call to `_get_heartbeat_secret_from_config(config_orm_row)`.

---

### 5. No WAL disk space guard (`max_slot_wal_keep_size` unset)
**Files:** all docker-compose files

None of the compose files set `max_slot_wal_keep_size`. If the standby goes offline for an extended period, the replication slot on the primary retains all WAL from the slot's `restart_lsn` forward with no limit. On a busy system this can fill the primary's disk and crash it.

Additionally, `max_replication_slots=150` in `docker-compose.pi.yml` is excessively high — 150 idle slots each accumulating retained WAL is a disk-exhaustion risk on a Raspberry Pi.

**Fix direction:** Add `-c max_slot_wal_keep_size=2048` (2 GB) to the primary postgres command in `docker-compose.pi.yml`. Reduce `max_replication_slots` to a sane value (e.g., `10`).

---

### 6. Multi-worker gunicorn runs multiple independent heartbeat services
**Files:** [`app/main.py:641`](../app/main.py#L641), [`app/modules/ha/service.py:38`](../app/modules/ha/service.py#L38)

`_heartbeat_service` is a module-level singleton, but gunicorn spawns `--workers 2`, each with its own Python interpreter and its own copy of the module. Each worker independently calls `_start_ha_heartbeat` on startup and starts its own `HeartbeatService`. Consequences:

- The standby receives **2× the configured heartbeat pings** per interval.
- Auto-promote logic runs independently in each worker. Both can detect the same unreachable condition and both call `_execute_auto_promote` concurrently, creating a race on `cfg.role` and writing two audit log entries.
- `_auto_promote_attempted` and `_auto_promote_failed_permanently` are per-worker flags — a failure in worker A doesn't prevent worker B from retrying.

**Fix direction:** Either use a single-worker setup for the HA service (e.g., a dedicated sidecar process), or use a distributed lock (Redis `SET NX EX`) in `_execute_auto_promote` to ensure only one worker can execute the promotion.

---

## MODERATE

### 7. Split-brain is undetectable during a full network partition
**File:** [`app/modules/ha/heartbeat.py:277`](../app/modules/ha/heartbeat.py#L277)

`detect_split_brain` runs only on a **successful** heartbeat ping. During a full network partition where neither node can reach the other, `split_brain_detected` stays `False` on both sides. After the standby auto-promotes, both nodes accept writes independently with no awareness of the conflict. There is no STONITH/fencing safeguard.

This is inherent to a 2-node design without a quorum mechanism, but the failover documentation does not make this limitation explicit and users may believe split-brain is always detected.

---

### 8. Primary base compose file missing `max_wal_senders` and `max_replication_slots`
**File:** [`docker-compose.yml`](../docker-compose.yml)

The primary's base `docker-compose.yml` only sets `wal_level=logical`. `max_wal_senders` and `max_replication_slots` are only added in the `docker-compose.pi.yml` override. If someone deploys the primary without the pi overlay, PostgreSQL defaults apply (`max_wal_senders=10`, `max_replication_slots=10`) and replication silently relies on those defaults without any explicit intent.

---

### 9. Standby dev compose missing statement/idle timeouts
**File:** [`docker-compose.ha-standby.yml`](../docker-compose.ha-standby.yml)

The standby dev postgres has no `idle_in_transaction_session_timeout` or `statement_timeout`, while `docker-compose.standby-prod.yml` and `docker-compose.pi.yml` both configure `30000ms`. This means the dev standby behaves differently from production under idle or slow connections, masking potential timeout-related bugs.

---

### 10. Replication lag metric uses `last_msg_send_time` — not LSN difference
**File:** [`app/modules/ha/replication.py:482`](../app/modules/ha/replication.py#L482)

```sql
EXTRACT(EPOCH FROM (now() - last_msg_send_time)) AS lag_seconds
```

`last_msg_send_time` is updated on every keepalive message, not just data messages. Under low write volume, this reports near-zero lag even when there are uncommitted WAL records queued. A more accurate measure is `pg_stat_replication.write_lag` / `flush_lag` / `replay_lag` (viewed from the primary), or comparing `received_lsn` vs `latest_end_lsn` in `pg_stat_subscription`.

The promote guard at [`app/modules/ha/service.py:325`](../app/modules/ha/service.py#L325) uses this value (`lag > 5.0`). If the metric understates actual lag, the safety guard is ineffective.

---

### 11. `pg_hba.conf` is unmanaged — replication connections not IP-restricted
**Scope:** infrastructure / deployment

The docs recommend restricting replication to the peer's specific IP via `pg_hba.conf`, but there is no mechanism to configure or deploy a custom `pg_hba.conf`. The Docker image uses default rules, meaning any host that can reach the exposed postgres port and holds valid credentials can establish a replication connection.

---

## MINOR

### 12. Heartbeat cache invalidation is per-worker only
**File:** [`app/modules/ha/router.py:272`](../app/modules/ha/router.py#L272)

`save_config` invalidates `_hb_cache` in the worker handling the request (`_ha_router._hb_cache["ts"] = 0`) but the other gunicorn worker keeps serving the old cached config (role, secret, maintenance flag) for up to 10 seconds. In multi-worker mode this causes transient inconsistencies in heartbeat responses.

---

### 13. WebSocket connections bypass standby write-protection middleware
**File:** [`app/modules/ha/middleware.py:88`](../app/modules/ha/middleware.py#L88)

```python
if scope["type"] != "http":
    await self.app(scope, receive, send)
    return
```

WebSocket connections (`scope["type"] == "websocket"`) are passed through unconditionally. The kitchen display WebSocket is currently read-only (Redis pub/sub, no DB writes), so there is no actual risk today. However, any future WebSocket handler that writes to the database would bypass standby protection silently.

---

### 14. `dead_letter` table is replicated and may trigger re-processing
**File:** [`app/modules/ha/replication.py:176`](../app/modules/ha/replication.py#L176)

`dead_letter` entries (failed background jobs from the old primary) are in the public schema and are included in the publication. After failover, the new primary inherits these entries. If any background task processor re-attempts entries from `dead_letter`, jobs that already partially executed on the old primary could be re-run, causing double side-effects (duplicate emails, double payments, etc.).

---

### 15. Peer role is always inferred as the opposite of local role
**File:** [`app/modules/ha/service.py:567`](../app/modules/ha/service.py#L567)

```python
peer_role = "standby" if cfg.role == "primary" else "primary"
```

In standalone mode, or in any configuration where the peer is also standalone, the cluster status dashboard will show an incorrect peer role. The actual peer role is available in the heartbeat response payload (`data.get("role")`) but is not used here.

---

## Summary Table

| # | Gap | Severity | File |
|---|-----|----------|------|
| 1 | Sequences not replicated → post-promotion duplicate PKs | **Critical** | `replication.py:183` |
| 2 | `trigger_resync` doesn't truncate before re-copy | **Critical** | `replication.py:400` |
| 3 | Plaintext passwords in committed scripts | **Significant** | `scripts/fix_replication.sh`, `check_repl_status.sh`, `check_sync_status.sh` |
| 4 | Startup ignores DB-stored heartbeat secret | **Significant** | `main.py:657` |
| 5 | No `max_slot_wal_keep_size` — unbounded WAL growth | **Significant** | all compose files |
| 6 | Multi-worker gunicorn duplicates heartbeat service | **Significant** | `main.py:641`, `service.py:38` |
| 7 | Split-brain undetectable under full network partition | **Moderate** | `heartbeat.py:277` |
| 8 | Primary base compose missing `max_wal_senders`/`max_replication_slots` | **Moderate** | `docker-compose.yml` |
| 9 | Standby dev compose missing statement timeouts | **Moderate** | `docker-compose.ha-standby.yml` |
| 10 | Lag metric uses send-time, not LSN diff | **Moderate** | `replication.py:482` |
| 11 | `pg_hba.conf` unmanaged, no IP restriction | **Moderate** | infrastructure |
| 12 | Cache invalidation single-worker only | **Minor** | `router.py:272` |
| 13 | WebSocket bypasses standby middleware | **Minor** | `middleware.py:88` |
| 14 | `dead_letter` table replicated, may re-process | **Minor** | `replication.py:176` |
| 15 | Peer role inferred incorrectly in standalone mode | **Minor** | `service.py:567` |
