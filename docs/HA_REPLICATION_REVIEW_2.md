# HA Replication — Post-Bugfix Review

Audit date: 2026-04-27
Scope: All files under `app/modules/ha/`, `app/main.py`, all docker-compose files, `scripts/` related to replication.
Context: Follow-up review after all 15 bugs from `HA_REPLICATION_GAPS.md` were patched.

---

## Original 15 Bugs — Verification Status

All 15 bugs from the original gap analysis are confirmed fixed:

| # | Bug | Status |
|---|-----|--------|
| 1 | Sequences not replicated — `ADD ALL SEQUENCES` missing | ✅ Fixed |
| 2 | `trigger_resync` didn't truncate before re-copy | ✅ Fixed |
| 3 | Hardcoded credentials in scripts | ✅ Fixed |
| 4 | Startup ignored DB-stored heartbeat secret | ✅ Fixed |
| 5 | No `max_slot_wal_keep_size` — unbounded WAL growth | ✅ Fixed |
| 6 | Multi-worker gunicorn duplicated heartbeat service | ✅ Fixed |
| 7 | Split-brain undetectable under full network partition | ✅ Documented |
| 8 | Primary base compose missing `max_wal_senders`/`max_replication_slots` | ✅ Fixed |
| 9 | Standby dev compose missing session timeouts | ✅ Fixed |
| 10 | Lag metric used send-time only, not GREATEST(send, receipt) | ✅ Fixed |
| 11 | `pg_hba.conf` unmanaged — no IP restriction script | ✅ Fixed |
| 12 | Cache invalidation single-worker only | ✅ Fixed (Redis dirty-flag) |
| 13 | WebSocket bypassed standby write-protection middleware | ✅ Fixed |
| 14 | `dead_letter` table replicated — risk of re-processing | ✅ Fixed |
| 15 | Peer role always inferred as opposite of local role | ✅ Fixed |

---

## New Findings — Post-Fix Review

The implementation introduced or exposed **3 Critical bugs**, **2 Significant bugs**, and **2 Minor gaps** that would cause replication workflows to fail.

---

## CRITICAL

### CRIT-1: `trigger_resync` always fails on the second call — orphaned slot never cleaned up

**File:** [`app/modules/ha/replication.py:461–486`](../app/modules/ha/replication.py#L461-L486)

**Root cause:**

`drop_subscription` intentionally calls `ALTER SUBSCRIPTION ... SET (slot_name = NONE)` before `DROP SUBSCRIPTION IF EXISTS`. This prevents the drop from failing when the primary is unreachable. The side-effect is that the replication slot `orainvoice_ha_sub` is left as an **inactive orphan on the primary**.

`trigger_resync` then immediately executes:
```sql
CREATE SUBSCRIPTION orainvoice_ha_sub CONNECTION '...' PUBLICATION ... WITH (copy_data = true)
```
PostgreSQL tries to create a slot named `orainvoice_ha_sub` on the primary — but it still exists as an orphan → **"replication slot 'orainvoice_ha_sub' already exists"** → `RuntimeError` is propagated → 400 response.

`init_standby` handles exactly this case via `_cleanup_orphaned_slot_on_peer`. `trigger_resync` skips this step entirely because it calls `_exec_autocommit` directly.

**Failure sequence:**
1. `truncate_all_tables()` — standby tables are now empty
2. `drop_subscription()` — orphan slot left on primary
3. `CREATE SUBSCRIPTION ...` → **FAILS** — slot already exists
4. Standby is empty with no subscription — **fully broken, manual intervention required**

**Impact:** The Resync button in the admin UI always fails after the first successful subscription has ever been set up. Any attempt to recover from replication inconsistency leaves the standby bricked.

**Fix:**
In [`replication.py:475`](../app/modules/ha/replication.py#L475), between `drop_subscription` and the `CREATE SUBSCRIPTION` call, add:
```python
# Clean up orphaned slot left by drop_subscription's SET (slot_name = NONE)
await ReplicationManager._cleanup_orphaned_slot_on_peer(primary_conn_str)
```

Full fixed `trigger_resync`:
```python
async def trigger_resync(db: AsyncSession, primary_conn_str: str) -> None:
    logger.info("Triggering full re-sync — truncating standby data first")
    await ReplicationManager.truncate_all_tables()
    await ReplicationManager.drop_subscription(db)
    # Clean up orphaned slot left on primary by SET (slot_name = NONE)
    await ReplicationManager._cleanup_orphaned_slot_on_peer(primary_conn_str)
    sql = (
        f"CREATE SUBSCRIPTION {ReplicationManager.SUBSCRIPTION_NAME} "
        f"CONNECTION '{primary_conn_str}' "
        f"PUBLICATION {ReplicationManager.PUBLICATION_NAME} "
        f"WITH (copy_data = true)"
    )
    await ReplicationManager._exec_autocommit(db, sql)
```

---

### CRIT-2: `promote()` and `demote()` don't update `_heartbeat_service.local_role` — split-brain detection is wrong after any manual role change

**Files:** [`app/modules/ha/service.py:351`](../app/modules/ha/service.py#L351), [`service.py:421`](../app/modules/ha/service.py#L421), [`service.py:509`](../app/modules/ha/service.py#L509)

**Root cause:**

`_execute_auto_promote` (auto-promote path) correctly sets `self.local_role = "primary"` at [`heartbeat.py:492`](../app/modules/ha/heartbeat.py#L492). The manual paths `promote()`, `demote()`, and `demote_and_sync()` only call `set_node_role()` which updates the middleware module variable — they never update `_heartbeat_service.local_role`.

**After manual `promote()` (standby → primary):**
- `_heartbeat_service.local_role` stays `"standby"`
- `detect_split_brain("standby", "primary")` = **False** — split-brain is never detected even when both nodes are simultaneously primary
- If the old primary is still running and accepting writes, the newly promoted node will not block writes on its side — full split-brain with no detection

**After manual `demote()` (primary → standby):**
- `_heartbeat_service.local_role` stays `"primary"`
- `detect_split_brain("primary", "primary")` = **True** — **SPURIOUS split-brain** fires on the next heartbeat
- `set_split_brain_blocked(True)` activates — every blocked request reports "split-brain detected" instead of "standby mode"
- The `is_stale_primary()` check evaluates `local_promoted_at = None` (demote cleared it) vs `_peer_promoted_at != None` → returns True → `set_split_brain_blocked(True)` confirmed
- This state **persists until container restart** — the peer will always claim "primary" (it IS primary), so `detect_split_brain` never clears

**Impact:**
- Post-promote: true split-brain scenarios go undetected, both nodes accept writes
- Post-demote: administrators see misleading "split-brain detected" errors on the newly demoted node; log noise obscures real split-brain events

**Fix:**
In [`service.py`](../app/modules/ha/service.py), update `_heartbeat_service.local_role` in all three transition methods:

```python
# In promote() — after set_node_role("primary", cfg.peer_endpoint):
if _heartbeat_service is not None:
    _heartbeat_service.local_role = "primary"

# In demote() — after set_node_role("standby", cfg.peer_endpoint):
if _heartbeat_service is not None:
    _heartbeat_service.local_role = "standby"

# In demote_and_sync() — after set_node_role("standby", cfg.peer_endpoint):
if _heartbeat_service is not None:
    _heartbeat_service.local_role = "standby"
```

---

### CRIT-3: `drop_replication_slot` router endpoint passes `None` as `db` → `AttributeError` on every call

**File:** [`app/modules/ha/router.py:1039–1046`](../app/modules/ha/router.py#L1039-L1046)

**Root cause:**

```python
# router.py:1039 — BROKEN
async def drop_replication_slot(slot_name: str):          # ← no db dependency
    try:
        result = await ReplicationManager.drop_replication_slot(None, slot_name)
```

`ReplicationManager.drop_replication_slot` at [`replication.py:668`](../app/modules/ha/replication.py#L668) immediately executes:
```python
result = await db.execute(text("SELECT active FROM pg_replication_slots WHERE slot_name = :name"), ...)
```
`None.execute(...)` → `AttributeError: 'NoneType' object has no attribute 'execute'` → **500 Internal Server Error** on every call to `DELETE /api/v1/ha/replication/slots/{slot_name}`.

Compare with `list_replication_slots` at [`router.py:1018`](../app/modules/ha/router.py#L1018) which correctly has `db: AsyncSession = Depends(get_db_session)`.

**Impact:** The entire replication slot management UI is non-functional. Orphaned slots cannot be dropped via the UI, forcing manual `psql` intervention.

**Fix:**
```python
# router.py:1039 — FIXED
async def drop_replication_slot(
    slot_name: str,
    db: AsyncSession = Depends(get_db_session),     # ← add this
):
    try:
        result = await ReplicationManager.drop_replication_slot(db, slot_name)  # ← pass db
```

---

## SIGNIFICANT

### SIG-1: `save_config` restarts heartbeat without Redis lock info — multi-worker problem silently returns

**File:** [`app/modules/ha/service.py:259–267`](../app/modules/ha/service.py#L259-L267)

**Root cause:**

When `save_config` restarts the heartbeat service (on peer endpoint change, secret change, etc.), it creates a new `HeartbeatService` without setting `_redis_lock_key`, `_lock_ttl`, or `_redis_client`:

```python
# _start_ha_heartbeat in main.py — CORRECT: passes Redis lock info
hb._redis_lock_key = LOCK_KEY
hb._lock_ttl = LOCK_TTL
hb._redis_client = redis_client

# save_config in service.py — MISSING these three lines
_heartbeat_service = HeartbeatService(peer_endpoint=..., interval=..., secret=..., local_role=...)
await _heartbeat_service.start()
```

Without Redis lock info, the new service **never renews** the `ha:heartbeat_lock` TTL. The lock expires within 30 seconds. The other gunicorn worker then acquires the lock and starts its own heartbeat service. Both workers ping the peer and can each independently trigger auto-promote — exactly the BUG-HA-06 race condition that was fixed.

**Trigger:** Any admin action that modifies HA config via the UI (`PUT /api/v1/ha/configure`) causes this regression.

**Fix:**
After creating the new `HeartbeatService` in `save_config`, add Redis lock wiring (same pattern as `_start_ha_heartbeat`):
```python
_heartbeat_service = HeartbeatService(
    peer_endpoint=cfg.peer_endpoint,
    interval=cfg.heartbeat_interval_seconds,
    secret=secret,
    local_role=cfg.role,
)
# Pass Redis lock info so the new service can renew the lock TTL
try:
    from app.core.redis import redis_pool
    _heartbeat_service._redis_lock_key = "ha:heartbeat_lock"
    _heartbeat_service._lock_ttl = 30
    _heartbeat_service._redis_client = redis_pool
except Exception:
    pass
await _heartbeat_service.start()
```

---

### SIG-2: `demote()` uses default `copy_data=true` on a node with existing data, and never drops its publication

**Files:** [`app/modules/ha/service.py:413–418`](../app/modules/ha/service.py#L413-L418), [`replication.py:449–457`](../app/modules/ha/replication.py#L449-L457)

**Root cause — `copy_data=true` on full dataset:**

When a primary demotes to standby, `demote()` calls `resume_subscription()`. In the fallback path (old primary never had a subscription), `resume_subscription` creates:
```python
sql = (f"CREATE SUBSCRIPTION {SUBSCRIPTION_NAME} "
       f"CONNECTION '{primary_conn_str}' "
       f"PUBLICATION {PUBLICATION_NAME}")   # ← no WITH (copy_data = false)
```
The default is `copy_data=true`. A former primary already holds the complete authoritative dataset. PostgreSQL's initial table-sync workers will immediately fail with **duplicate primary-key violations on every table**.

**Root cause — publication never dropped:**

`demote()` never calls `drop_publication()`. After demotion the former primary still holds `orainvoice_ha_pub`:
- Retains WAL unnecessarily (no subscriber is connected)
- Is conceptually wrong — a standby node should not publish
- Creates confusion for administrators managing the HA panel

**Current real-world behaviour:**

In practice today, the subscription creation fails silently because the newly promoted node has no publication immediately after `promote()` (which correctly stops the subscription but doesn't create a publication). `demote()` catches the exception and returns `200 OK` with `{"status": "ok", "role": "standby"}` — replication is non-functional but the admin sees no error.

Once an admin runs `/replication/init` on the new primary to create its publication, any subsequent `demote()` call on the old primary will then successfully create a subscription — but with `copy_data=true` → duplicate PKs on every table.

**Fix:**

1. Add `drop_publication` at the start of `demote()`:
```python
# Drop this node's publication (it is no longer a primary)
try:
    await ReplicationManager.drop_publication(db)
except Exception as exc:
    logger.warning("Could not drop publication during demote: %s", exc)
```

2. In `resume_subscription`, add `copy_data=false` for the planned-demote case (data is already in sync):
```python
sql = (
    f"CREATE SUBSCRIPTION {ReplicationManager.SUBSCRIPTION_NAME} "
    f"CONNECTION '{primary_conn_str}' "
    f"PUBLICATION {ReplicationManager.PUBLICATION_NAME} "
    f"WITH (copy_data = false)"   # ← add this
)
```

3. Update the rolling-update procedure in `docs/HA_REPLICATION_GUIDE.md` — document that `/replication/init` on the NEW primary must complete **before** calling `/demote` on the old primary.

---

## MINOR

### MIN-1: Dev standby compose missing `max_wal_senders` and `max_replication_slots`

**File:** [`docker-compose.ha-standby.yml:31–52`](../docker-compose.ha-standby.yml#L31-L52)

All other compose files have explicit `-c max_wal_senders=10` and `-c max_replication_slots=10`. The dev standby (`docker-compose.ha-standby.yml`) does not. PostgreSQL 16 defaults happen to be `max_wal_senders=10` and `max_replication_slots=10` — currently correct by coincidence. If the dev standby is promoted during HA testing, it relies on implicit defaults rather than declared configuration.

**Fix:**
```yaml
# docker-compose.ha-standby.yml — add to postgres command:
- "-c"
- "max_wal_senders=10"
- "-c"
- "max_replication_slots=10"
```

---

### MIN-2: `_auto_promote_attempted` is never cleared on peer recovery — permanent auto-promote lockout after any transient failure

**File:** [`app/modules/ha/heartbeat.py:127–134`](../app/modules/ha/heartbeat.py#L127-L134)

When the peer recovers, `_peer_unreachable_since` is reset to `None`. But `_auto_promote_attempted` and `_auto_promote_failed_permanently` are never cleared. If auto-promote fails for a transient reason (Redis unavailable, DB connection timeout during promotion), the node will **never attempt auto-promote again** — even if the peer goes unreachable for hours afterward — until the container restarts. There is no log warning that this lockout state persists after recovery.

**Fix:**
When the peer transitions from "unreachable" back to reachable, reset `_auto_promote_attempted`:
```python
elif previous_health == "unreachable" and self.peer_health != "unreachable":
    logger.info("Peer %s is reachable again (now %s)", self.peer_endpoint, self.peer_health)
    self._peer_unreachable_since = None
    self._auto_promote_attempted = False     # ← add: allow future auto-promote if peer goes down again
    # Note: _auto_promote_failed_permanently is intentionally NOT reset here —
    # permanent failure (2 consecutive failures) requires a container restart
```

---

## Summary Table

| # | Gap | Severity | File | One-line Fix |
|---|-----|----------|------|-------------|
| CRIT-1 | `trigger_resync` orphan slot → resync always fails | **Critical** | `replication.py:475` | Add `_cleanup_orphaned_slot_on_peer` before CREATE SUBSCRIPTION |
| CRIT-2 | `promote`/`demote` don't update `local_role` → split-brain blind/spurious | **Critical** | `service.py:351,421,509` | Set `_heartbeat_service.local_role` in all three methods |
| CRIT-3 | `drop_replication_slot` router passes `None` as db → 500 crash | **Critical** | `router.py:1039` | Add `db: AsyncSession = Depends(get_db_session)` to endpoint |
| SIG-1 | `save_config` restarts heartbeat without Redis lock → multi-worker returns | **Significant** | `service.py:261` | Pass Redis lock info to new HeartbeatService in save_config |
| SIG-2 | `demote()` uses `copy_data=true` on full dataset; keeps publication | **Significant** | `service.py:413`, `replication.py:451` | Use `copy_data=false`; drop publication in demote |
| MIN-1 | Dev standby missing `max_wal_senders`/`max_replication_slots` | **Minor** | `docker-compose.ha-standby.yml` | Add explicit settings |
| MIN-2 | `_auto_promote_attempted` never cleared → permanent lockout after transient failure | **Minor** | `heartbeat.py:134` | Reset flag when peer recovers |

---

## Confirmed Working — No Issues

All critical paths verified correct after the original 15 fixes:

- Sequence replication via `ADD ALL SEQUENCES` + `sync_sequences_post_promotion()` called from both promote paths ✓
- `trigger_resync` truncates before dropping subscription ✓ (slot cleanup still missing — CRIT-1)
- Credentials removed from all three scripts ✓
- Startup reads DB-stored heartbeat secret via `_get_heartbeat_secret_from_config` ✓
- `max_slot_wal_keep_size=2048` in `docker-compose.pi.yml` and `docker-compose.standby-prod.yml` ✓
- `max_replication_slots` reduced from 150 to 10 in pi.yml ✓
- Redis distributed lock acquired at startup, renewed each heartbeat cycle ✓ (breaks in `save_config` — SIG-1)
- WebSocket write-protection with allowlist (`/ws/kitchen/`, `/api/v1/ha/`) ✓
- `dead_letter_queue` excluded from publication ✓
- `GREATEST(last_msg_send_time, last_msg_receipt_time)` lag metric ✓
- Actual peer role stored from heartbeat response (`peer_role`) ✓
- Redis dirty-flag for cross-worker heartbeat cache invalidation ✓
- Base `docker-compose.yml` has explicit `max_wal_senders=10`, `max_replication_slots=10` ✓
- Dev standby `docker-compose.ha-standby.yml` has `idle_in_transaction_session_timeout` and `statement_timeout` ✓
- HMAC signing and verification cycle is correct (canonical JSON → sign → pop → re-canonicalize → verify) ✓
- `demote_and_sync` truncates then creates subscription with `truncate_first=False` (correct) ✓
- `drop_publication` and `drop_subscription` both use `_exec_autocommit` (DDL-safe) ✓
- `init_standby` handles orphaned slot via `_cleanup_orphaned_slot_on_peer` with auto-retry ✓
- `sync_sequences_post_promotion` uses `setval(seq, GREATEST(max_id+1, 1), false)` correctly ✓
- `filter_tables_for_truncation` excludes `ha_config` but includes `dead_letter_queue` (correct) ✓
- `ReplicationManager._get_raw_conn` disables `statement_timeout` and `idle_in_transaction_session_timeout` ✓
- Slot name validated with `[a-zA-Z0-9_]+` regex before use in SQL ✓
- `create_replication_user` uses `quote_literal`/`quote_ident` for safe password escaping ✓
