# HA Replication Review 3 — GUI-Only Config & Completeness Audit

**Date:** 2026-04-27  
**Scope:** (1) Eliminate all env-var dependencies from HA replication — everything via GUI; (2) Confirm frontend config page completeness; (3) Identify any remaining code bugs or workflow gaps.

---

## 1. Env Var Dependency Audit

Four HA-related env vars still exist. Status is different for each one.

### 1.1 `HA_HEARTBEAT_SECRET` — DB-preferred, env fallback still active

| | Detail |
|---|---|
| DB column | `ha_config.heartbeat_secret` (LargeBinary, AES-256-GCM encrypted) |
| GUI field | Heartbeat Secret input in Node Configuration ✓ |
| Startup path | `_get_heartbeat_secret_from_config(cfg_orm)` — DB preferred ✓ |
| Fallback path | `service.py:72` → `os.environ.get("HA_HEARTBEAT_SECRET", "")` |
| Heartbeat endpoint | `router.py:165` → env fallback if DB decryption fails |

**Problem — env files have actual values:**

| File | Value |
|---|---|
| `.env` | `HA_HEARTBEAT_SECRET=dev-ha-secret-for-testing` |
| `.env.pi` | `HA_HEARTBEAT_SECRET=dev-ha-secret-for-testing` |
| `.env.ha-standby` | `HA_HEARTBEAT_SECRET=dev-ha-secret-for-testing` |
| `.env.standby-prod` | `HA_HEARTBEAT_SECRET=dev-ha-secret-for-testing` |
| `.env.pi-standby` | `HA_HEARTBEAT_SECRET=` (blank) |

**Risk:** If a node has a blank `heartbeat_secret` in the DB but `HA_HEARTBEAT_SECRET` set in the env file, the app silently uses the weak env secret. The GUI shows "secret not configured" but heartbeats actually "work" on the env secret. A node that was configured via GUI and one that relies on the env var will have mismatched secrets → HMAC failures. User has no visible indication of which secret is active.

**Dead code:** `_get_heartbeat_secret()` at `service.py:46–59` reads env only, never from DB. It is no longer called anywhere after the BUG-HA-04 fix. It should be removed to avoid confusion.

**Fix required:**
- Remove `_get_heartbeat_secret()` function (dead code)
- Remove the env fallback from `_get_heartbeat_secret_from_config()` and the heartbeat endpoint — if DB decrypt fails, raise an error, don't silently fall back
- Clear `HA_HEARTBEAT_SECRET` values from all `.env*` files (set to empty or remove the line entirely)

---

### 1.2 `HA_PEER_DB_URL` — DB-preferred, env fallback still active

| | Detail |
|---|---|
| DB columns | `peer_db_host`, `peer_db_port`, `peer_db_name`, `peer_db_user`, `peer_db_password` (encrypted) |
| GUI section | Peer Database Settings ✓ |
| Fallback path | `service.py:142` → `os.environ.get("HA_PEER_DB_URL") or None` |
| Error messages | `router.py:449,521` — still mention env var as an option |

**Critical — leaked password still in env file:**

```
.env.standby-prod:51  HA_PEER_DB_URL=postgresql://replicator:NoorHarleen1@192.168.1.90:5432/workshoppro
```

BUG-HA-03 fixed the scripts, but the `.env.standby-prod` file still has the same password `NoorHarleen1` hardcoded. This env var is the active fallback — if the DB peer config is empty (or decryption fails), the app uses this connection string silently.

**Fix required:**
- Clear `HA_PEER_DB_URL` from `.env.standby-prod` and all other env files immediately
- Remove the `os.environ.get("HA_PEER_DB_URL")` fallback from `get_peer_db_url()` (or log a strong deprecation warning)
- Update error messages at `router.py:449,521` to say: `"Peer database connection is not configured. Set peer DB settings in HA configuration."` — remove the env var mention

---

### 1.3 `HA_LOCAL_LAN_IP` — **No DB alternative, no GUI field**

**Purpose:** Used only to display the correct connection string in the "View Connection Info" modal after creating a replication user. Does NOT affect actual replication.

**Auto-detection logic (`_detect_host_lan_ip()`):**
1. Env var override (always wins)
2. `host.docker.internal` (Docker Desktop only)
3. UDP socket trick — `socket.connect("8.8.8.8", 80)` → returns local IP
4. Fallback: `127.0.0.1`

**Problem — UDP socket trick returns wrong IP in Docker:**  
Inside a Docker container on Linux (production Pi), the UDP socket trick returns the container's internal IP (e.g., `172.17.0.2`), NOT the host's LAN IP (e.g., `192.168.1.90`). The displayed connection string shows the wrong IP. The admin copies it to the standby, enters the wrong host, and wonders why the connection test fails.

This is NOT cosmetic — it directly blocks new standby setup if the admin relies on "View Connection Info."

**Fix required:**  
Add `local_lan_ip` (optional `String(255)`) to `ha_config` table and expose it in the GUI as an optional field: *"Local LAN IP (optional — used to display connection info for peer setup; auto-detected if blank)"*. Priority: DB field > env var > auto-detect.

---

### 1.4 `HA_LOCAL_PG_PORT` — **No DB alternative, no GUI field**

**Purpose:** Used only for the "View Connection Info" modal to show the correct host port mapping. Does NOT affect actual replication.

**Problem — container cannot see Docker host port mappings:**  
The PostgreSQL container always sees its internal port as 5432. If the host `docker-compose.yml` maps `5435:5432`, the container has no way to know the external port is 5435. Without `HA_LOCAL_PG_PORT=5435`, the displayed connection string shows port 5432, which the peer cannot reach. **This is not auto-detectable.**

`.env.standby-prod` correctly sets `HA_LOCAL_PG_PORT=5435` — but this relies on env config, not GUI.

**Fix required:**  
Add `local_pg_port` (optional `Integer`, default `null`) to `ha_config` table. Expose it in the GUI: *"Local PostgreSQL Port (optional — the HOST port mapped to PostgreSQL; auto-defaults to 5432 if blank)"*. Priority: DB field > env var > 5432.

---

## 2. Code Bugs — Still Unfixed From Previous Review

The following bugs were identified in the second review (`HA_REPLICATION_REVIEW_2.md`) but have NOT been fixed.

### BUG-CRIT-1: `trigger_resync` — Orphaned Slot Causes `CREATE SUBSCRIPTION` to Fail

**File:** `app/modules/ha/replication.py:461–486`  
**Status:** UNFIXED

`drop_subscription()` uses `ALTER SUBSCRIPTION ... SET (slot_name = NONE)` before `DROP SUBSCRIPTION`. This disconnects the subscription from the slot without dropping it (intentional — works when primary is unreachable). The slot remains on the primary as an orphan.

`trigger_resync` then calls `CREATE SUBSCRIPTION`, which tries to create a new slot with the same name. PostgreSQL returns: `ERROR: replication slot already exists`. Resync fails every time except the very first.

```python
# CURRENT — broken:
await ReplicationManager.drop_subscription(db)
# orphan slot still exists on primary
sql = f"CREATE SUBSCRIPTION {SUBSCRIPTION_NAME} ..."  # fails: slot already exists

# FIX:
await ReplicationManager.drop_subscription(db)
await ReplicationManager._cleanup_orphaned_slot_on_peer(primary_conn_str)  # ADD THIS
sql = f"CREATE SUBSCRIPTION {SUBSCRIPTION_NAME} ..."  # now works
```

`_cleanup_orphaned_slot_on_peer()` already exists at `replication.py:689` and is called from `init_standby`. It just needs to be called from `trigger_resync` too.

---

### BUG-CRIT-2: `promote()` and `demote()` Don't Update `_heartbeat_service.local_role`

**Files:** `app/modules/ha/service.py:307–382`, `384–443`  
**Status:** UNFIXED

`set_node_role()` updates the middleware module's `_node_role` variable. The heartbeat service has a separate `self.local_role` instance variable. They are two separate caches.

- `promote()` — calls `set_node_role("primary", ...)` but not `_heartbeat_service.local_role = "primary"`  
  → After manual promote, `detect_split_brain(self.local_role="standby", peer_role="primary")` = False → split-brain never fires even if both nodes are primary.

- `demote()` — calls `set_node_role("standby", ...)` but not `_heartbeat_service.local_role = "standby"`  
  → After manual demote, `detect_split_brain(self.local_role="primary", peer_role="primary")` = True → **spurious split-brain fires** → writes blocked on a legitimate standby.

**Fix:**
```python
# In promote(), after set_node_role("primary", ...):
hb = get_heartbeat_service()
if hb is not None:
    hb.local_role = "primary"

# In demote(), after set_node_role("standby", ...):
hb = get_heartbeat_service()
if hb is not None:
    hb.local_role = "standby"
```

Same fix needed in `demote_and_sync()`.

---

### BUG-CRIT-3: `drop_replication_slot` Router — `None` Passed as DB Session

**File:** `app/modules/ha/router.py:1039–1053`  
**Status:** UNFIXED

```python
# Line 1039 — MISSING db parameter:
async def drop_replication_slot(slot_name: str):
    result = await ReplicationManager.drop_replication_slot(None, slot_name)
```

`ReplicationManager.drop_replication_slot(db, slot_name)` calls `await db.execute(...)` at line 668. When `db=None`, this is `None.execute(...)` → `AttributeError` → 500 on every call to `DELETE /api/v1/ha/replication/slots/{slot_name}`.

The Drop button in the Replication Slots UI is completely broken.

**Fix:**
```python
async def drop_replication_slot(
    slot_name: str,
    db: AsyncSession = Depends(get_db_session),   # ADD THIS
):
    result = await ReplicationManager.drop_replication_slot(db, slot_name)  # pass db
```

---

### BUG-SIG-1: `save_config` Restarts Heartbeat Without Redis Lock

**File:** `app/modules/ha/service.py:261`  
**Status:** UNFIXED

When `save_config` restarts the heartbeat service, it creates a new `HeartbeatService` but does NOT wire the Redis lock fields (`_redis_lock_key`, `_lock_ttl`, `_redis_client`). The old lock expires in ~30s, another worker acquires it, and two workers run heartbeat — re-introducing BUG-HA-06.

**Fix:** Mirror the wiring from `_start_ha_heartbeat` in `main.py` into the `save_config` restart path.

---

### BUG-SIG-2: `demote()` Uses `copy_data=true` Default

**File:** `app/modules/ha/service.py:413–418` → `replication.py:resume_subscription`  
**Status:** UNFIXED

`demote()` calls `resume_subscription()` which falls through to `CREATE SUBSCRIPTION ... WITH (copy_data = true)`. For a graceful rolling-update demote where data is already in sync, `copy_data=true` causes duplicate PK errors on all tables.

**Fix:** `resume_subscription()` should use `copy_data = false` in its CREATE fallback path.

---

## 3. Frontend GUI — Configuration Completeness

### 3.1 What Is Fully Configurable via GUI ✓

| Setting | GUI Field | DB Stored | Encrypted |
|---|---|---|---|
| Node name | ✓ Node Name | ✓ | — |
| Role | ✓ Role dropdown | ✓ | — |
| Peer endpoint (HTTP URL) | ✓ Peer Endpoint | ✓ | — |
| Heartbeat HMAC secret | ✓ Heartbeat Secret | ✓ | AES-256-GCM |
| Auto-promote toggle | ✓ checkbox | ✓ | — |
| Heartbeat interval | ✓ number input | ✓ | — |
| Failover timeout | ✓ number input | ✓ | — |
| Peer DB host | ✓ Host field | ✓ | — |
| Peer DB port | ✓ Port field | ✓ | — |
| Peer DB name | ✓ Database Name | ✓ | — |
| Peer DB user | ✓ User field | ✓ | — |
| Peer DB password | ✓ Password field | ✓ | AES-256-GCM |
| Peer DB SSL mode | ✓ SSL dropdown | ✓ | — |

### 3.2 What Is Missing from GUI ✗

| Setting | Current Source | Impact |
|---|---|---|
| Local LAN IP | `HA_LOCAL_LAN_IP` env or auto-detect | Wrong IP in "View Connection Info" on Linux Docker |
| Local PG port | `HA_LOCAL_PG_PORT` env or hardcoded 5432 | Wrong port in "View Connection Info" always |

### 3.3 Status Indicators — What Is Shown

- `✓ Credentials stored` badge in Peer Database Settings when `peer_db_configured` is true ✓
- `✓ Secret stored` helper text under Heartbeat Secret when `heartbeat_secret_configured` is true ✓  
- Cluster Status panel (peer health dot, lag, sync status) ✓
- Auto-promote countdown banner ✓
- Split-brain critical alert banner ✓
- "Automatically promoted" banner ✓
- Replication slots table with Drop button ✓
- Heartbeat history table ✓

### 3.4 UI Gaps

**Gap 1 — Peer role hardcoded, not from actual heartbeat**  
`HAReplication.tsx:1308`: `config.role === 'primary' ? 'Standby' : 'Primary'` — the peer card always shows the logical opposite role. After a promotion, both nodes may report as primary from this logic.

BUG-HA-15 fix stored `peer_role` in `_heartbeat_service.peer_role` and exposed it through `get_cluster_status()`. But the frontend never calls `/ha/cluster-status`. The `FailoverStatus` interface does not include `peer_role`. Add `peer_role` to the `/ha/failover-status` response and display it in the peer card.

**Gap 2 — `stop-replication` has no confirmation gate on primary**  
`HAReplication.tsx:638`: `needsConfirmText` list excludes `'stop-replication'`. On a primary, stopping replication drops the publication — all data flow to the standby stops. This should require typing CONFIRM.

Similarly `init-replication` on a primary (creates the publication) can be clicked accidentally with no gate. Low risk but deserves a reason field at minimum.

**Gap 3 — Setup Guide still mentions `.env` files**  
`HAReplication.tsx:167`: *"protect your `.env` files too"* — contradicts the GUI-only goal. Should say: *"The heartbeat secret and peer DB credentials are stored encrypted in the database — no env file entries are required for HA configuration."*

**Gap 4 — `HA_LOCAL_LAN_IP`/`HA_LOCAL_PG_PORT` not surfaced in UI**  
When the "View Connection Info" shows a wrong IP or wrong port, there is no indication to the user that the values came from auto-detection and may be incorrect. Add a small note: *"IP and port are auto-detected from the server. If incorrect, they can be overridden in Node Configuration."*

---

## 4. Workflow Completeness — Remaining Gaps

### 4.1 `_auto_promote_attempted` Never Cleared After Recovery

**File:** `app/modules/ha/heartbeat.py`

If auto-promote is attempted but fails (e.g., Redis lock acquired by another process, promote throws), `_auto_promote_attempted = True` permanently. When the peer recovers, `_peer_unreachable_since` is reset but `_auto_promote_attempted` is not. Auto-promote is permanently disabled until container restart.

**Fix:** In `_ping_loop`, when peer recovers (transitions from unreachable → healthy), also reset `self._auto_promote_attempted = False`.

### 4.2 `_get_heartbeat_secret()` is Dead Code

`service.py:46–59` — This function was the old env-only path. After the BUG-HA-04 fix, all callers use `_get_heartbeat_secret_from_config()`. The old function is never called. Remove it.

---

## 5. Summary — Action Table

| # | Severity | Issue | File | Fix Size |
|---|---|---|---|---|
| 1 | **Critical** | `trigger_resync` orphan slot → CREATE SUBSCRIPTION fails | `replication.py:475` | 1 line |
| 2 | **Critical** | `promote()`/`demote()` don't update `hb.local_role` → split-brain wrong | `service.py:351,421` | 6 lines |
| 3 | **Critical** | `drop_replication_slot` router `db=None` → AttributeError 500 | `router.py:1039` | 2 lines |
| 4 | **Significant** | `HA_PEER_DB_URL` with leaked password still in `.env.standby-prod` | `.env.standby-prod` | 1 line delete |
| 5 | **Significant** | `save_config` restarts heartbeat without Redis lock wiring | `service.py:261` | 6 lines |
| 6 | **Significant** | `demote()` → `copy_data=true` causes duplicate PK errors | `replication.py:resume` | 1 word change |
| 7 | **Significant** | No GUI fields for `local_lan_ip` / `local_pg_port` | model + migration + GUI | medium |
| 8 | **Moderate** | Error messages still tell user to set `HA_PEER_DB_URL` env var | `router.py:449,521` | 2 lines |
| 9 | **Moderate** | `HA_HEARTBEAT_SECRET` env fallback still active; dev secret in all `.env` files | service + env files | 4 lines + env cleanup |
| 10 | **Moderate** | Peer role shown as hardcoded inference, not real heartbeat role | `HAReplication.tsx:1308` | small |
| 11 | **Moderate** | `stop-replication` on primary has no CONFIRM gate | `HAReplication.tsx:638` | 1 word add |
| 12 | **Minor** | `_auto_promote_attempted` never cleared on peer recovery | `heartbeat.py` | 1 line |
| 13 | **Minor** | `_get_heartbeat_secret()` dead code still present | `service.py:46` | delete |
| 14 | **Minor** | Setup Guide still mentions `.env` files for HA config | `HAReplication.tsx:167` | 2 lines |

---

## 6. Confirmed Working

- Peer DB credentials stored encrypted in DB, buildable into connection URL via `_build_peer_db_url()` ✓
- Heartbeat secret stored encrypted, decrypted at startup from DB ✓
- GUI shows `✓ Credentials stored` / `✓ Secret stored` status correctly ✓
- Connection test flow (host/name/user/password → test → save with main config) ✓
- Replication user creation + connection info modal ✓
- All 15 original bugs verified fixed from Review 1 ✓
- Sequence sync on promote ✓
- Resync truncation ✓
- Redis heartbeat lock (at startup) ✓
- WAL disk guard ✓
- WebSocket write protection ✓
