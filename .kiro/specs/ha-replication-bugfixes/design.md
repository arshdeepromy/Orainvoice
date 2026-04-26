# HA Replication Bugfixes — Design Document

## Overview

This design covers fixes for 15 confirmed bugs and gaps in the OraInvoice HA (High Availability) replication system, identified by a deep audit of `app/modules/ha/`, all `docker-compose` files, `app/main.py`, and operational scripts.

**Severity breakdown:**
- **2 Critical** — Post-promotion duplicate key violations from unreplicated sequences; broken full-resync flow
- **4 Significant** — Unbounded WAL disk growth; multi-worker heartbeat race conditions; startup ignoring DB-stored secrets; hardcoded credentials in scripts
- **4 Moderate** — Inaccurate lag metric; missing compose settings; unmanaged pg_hba.conf; undocumented split-brain limitation
- **5 Minor** — Single-worker cache invalidation; WebSocket middleware bypass; dead_letter replication; incorrect peer role inference; issue tracker logging

**Existing HA specs this builds on:**
- `.kiro/specs/ha-replication/` — original HA requirements and design
- `.kiro/specs/ha-replication-improvements/` — auto-promote, split-brain, demote-and-sync improvements

---

## Architecture

The HA system uses **PostgreSQL 16 logical replication** between a primary node and a standby node, with a heartbeat service for health monitoring and automatic failover.

**Data flow:**
```
Primary (Pi prod)                          Standby (local dev or standby-prod)
┌──────────────┐    logical replication    ┌──────────────┐
│ PostgreSQL   │ ──────────────────────►   │ PostgreSQL   │
│ (publisher)  │    publication/subscription│ (subscriber) │
└──────────────┘                           └──────────────┘
       │                                          │
┌──────────────┐    heartbeat pings        ┌──────────────┐
│ FastAPI app  │ ◄────────────────────►    │ FastAPI app  │
│ (primary)    │    HMAC-signed JSON       │ (standby)    │
└──────────────┘                           └──────────────┘
```

**Key components touched by these fixes:**

| Component | Files | Fixes |
|-----------|-------|-------|
| Replication manager | `app/modules/ha/replication.py` | BUG-HA-01, 02, 10, 13, 14 |
| App startup | `app/main.py` | BUG-HA-04, 06 |
| Heartbeat service | `app/modules/ha/heartbeat.py` | BUG-HA-06, 15 |
| HA service | `app/modules/ha/service.py` | BUG-HA-06, 15 |
| Standby middleware | `app/modules/ha/middleware.py` | BUG-HA-13 |
| HA router | `app/modules/ha/router.py` | BUG-HA-06, 12 |
| Docker Compose files | `docker-compose.yml`, `docker-compose.pi.yml`, `docker-compose.ha-standby.yml`, `docker-compose.standby-prod.yml` | BUG-HA-05, 08, 09 |
| Operational scripts | `scripts/check_repl_status.sh`, `scripts/check_sync_status.sh`, `scripts/fix_replication.sh` | BUG-HA-03 |
| Documentation | `docs/HA_REPLICATION_GUIDE.md` | BUG-HA-07, 11 |
| New script | `scripts/configure_pg_hba.sh` | BUG-HA-11 |
| Issue tracker | `docs/ISSUE_TRACKER.md` | All |

---

## Components and Interfaces

### Fix BUG-HA-01: Sequence Replication (Critical)

**File:** `app/modules/ha/replication.py`

**Approach:** Two-phase fix. (1) Include sequences in the publication for ongoing sync using PostgreSQL 16 native sequence replication. (2) Add a post-promotion sequence fast-forward as a safety net for any gap.

**Phase 1 — Publication includes sequences:**

In `ReplicationManager.init_primary`, after creating the table publication, add all sequences:

```python
# After creating the FOR TABLE publication:
await conn.execute(
    f"ALTER PUBLICATION {ReplicationManager.PUBLICATION_NAME} ADD ALL SEQUENCES"
)
```

**Phase 2 — Post-promotion sequence fast-forward (safety net):**

Add a new static method `ReplicationManager.sync_sequences_post_promotion(db)` that runs on the node immediately after promotion:

```python
@staticmethod
async def sync_sequences_post_promotion(db: AsyncSession) -> dict:
    """Advance all sequences to be at least max(existing_id) + 1."""
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

Call sites:
- `HAService.promote()` — after `set_node_role("primary", ...)`
- `HeartbeatService._execute_auto_promote()` — after the middleware update, before committing

**Accurate lag fix:**

Replace `get_replication_lag` SQL with:
```sql
SELECT EXTRACT(EPOCH FROM (now() - GREATEST(last_msg_send_time, last_msg_receipt_time)))
FROM pg_stat_subscription WHERE subname = :name
```

---

### Fix BUG-HA-02: Resync Truncation (Critical)

**File:** `app/modules/ha/replication.py`

**Approach:** Add `truncate_all_tables()` as the first step in `trigger_resync`, before dropping and recreating the subscription. This matches the existing pattern in `init_standby` which correctly passes `truncate_first=True`.

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

### Fix BUG-HA-03: Hardcoded Credentials in Scripts (Significant)

**Files:** `scripts/check_repl_status.sh`, `scripts/check_sync_status.sh`, `scripts/fix_replication.sh`

**Approach:**
- Remove all `echo W4h3guru1# | sudo -S` prefixes — replace with bare `sudo` (relies on NOPASSWD sudoers or interactive prompt)
- Remove `password=NoorHarleen1` from `fix_replication.sh` — replace connection string with `${HA_PEER_DB_URL}` variable reference
- Add header comment to each script documenting prerequisites:

```bash
# Prerequisites:
# - SSH key auth configured to the standby (nerdy@192.168.10.87)
# - Sudoers configured with NOPASSWD for docker commands on the standby
# - HA_PEER_DB_URL environment variable set with the replication connection string
```

- Rotate the leaked credentials on the production server

---

### Fix BUG-HA-04: Startup Heartbeat Uses DB-Stored Secret (Significant)

**File:** `app/main.py`

**Approach:** In `_start_ha_heartbeat()`, load the ORM `HAConfig` object directly and pass it to `_get_heartbeat_secret_from_config(cfg_orm)` instead of reading from `os.environ.get("HA_HEARTBEAT_SECRET", "")`.

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
                    local_role=cfg_orm.role,  # Also fixes missing local_role
                )
                ha_svc_module._heartbeat_service = hb
                await hb.start()
```

Also fixes the missing `local_role=cfg_orm.role` parameter to `HeartbeatService`, which was causing split-brain detection to always compare `"standalone"` against the peer's role.

---

### Fix BUG-HA-05: WAL Disk Space Guard in Compose Files (Significant)

**Files:** `docker-compose.pi.yml`, `docker-compose.yml`, `docker-compose.standby-prod.yml`

**Approach:** Add `max_slot_wal_keep_size=2048` (2 GB ceiling) to prevent unbounded WAL retention. Reduce excessive slot allocation.

- **`docker-compose.pi.yml`** (primary prod): Add `max_slot_wal_keep_size=2048`. Change `max_replication_slots=150` to `max_replication_slots=10`.
- **`docker-compose.yml`** (base/primary dev): Add explicit `max_wal_senders=10`, `max_replication_slots=10` alongside existing `wal_level=logical`.
- **`docker-compose.standby-prod.yml`**: Add `max_slot_wal_keep_size=2048` (in case standby is promoted to primary).

---

### Fix BUG-HA-06: Multi-Worker Heartbeat Isolation (Significant)

**Files:** `app/main.py`, `app/modules/ha/heartbeat.py`, `app/modules/ha/router.py`, `app/modules/ha/service.py`

**Approach:** Use Redis distributed locks to ensure only one gunicorn worker runs the heartbeat service.

**Heartbeat lock in `_start_ha_heartbeat()`:**
```python
LOCK_KEY = "ha:heartbeat_lock"
LOCK_TTL = 30  # seconds

from app.core.redis import get_redis_client
redis = await get_redis_client()
worker_id = os.getpid()
acquired = await redis.set(LOCK_KEY, worker_id, nx=True, ex=LOCK_TTL)
if not acquired:
    logger.info("Heartbeat lock already held — skipping in PID %d", worker_id)
    return
```

**Lock renewal in `HeartbeatService._ping_loop`:**
```python
# After each successful ping cycle:
try:
    if self._redis_lock_key and self._redis_client:
        await self._redis_client.expire(self._redis_lock_key, self._lock_ttl)
except Exception:
    pass  # Non-critical; another worker takes over when lock expires
```

**Promotion lock in `_execute_auto_promote()`:**
```python
PROMOTE_LOCK_KEY = "ha:auto_promote_lock"
acquired = await redis.set(PROMOTE_LOCK_KEY, worker_id, nx=True, ex=60)
if not acquired:
    logger.info("Auto-promote lock held by another worker — skipping")
    return
```

**Cross-worker cache invalidation (also fixes BUG-HA-12):**

In `save_config`:
```python
try:
    redis = await get_redis_client()
    await redis.set("ha:hb_cache_dirty", "1", ex=15)
except Exception:
    pass  # Non-critical — cache expires naturally via 10s TTL
```

In the heartbeat endpoint handler:
```python
try:
    _redis = await get_redis_client()
    if await _redis.get("ha:hb_cache_dirty"):
        _hb_cache["ts"] = 0  # force cache miss
        await _redis.delete("ha:hb_cache_dirty")
except Exception:
    pass  # Redis unavailable — fall back to TTL-based expiry
```

---

### Fix BUG-HA-07: Document Network Partition Limitation (Moderate)

**Files:** `docs/HA_REPLICATION_GUIDE.md`, HA admin frontend component

**Approach:** No code changes. Add explicit documentation about the inherent 2-node split-brain limitation.

Add to `docs/HA_REPLICATION_GUIDE.md` under **Failover and Recovery Procedures → Unplanned Failover**:

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

Also add a tooltip on the auto-promote toggle in the HA admin frontend.

---

### Fix BUG-HA-08: Base Compose Explicit WAL Settings (Moderate)

**File:** `docker-compose.yml`

**Approach:** Add `max_wal_senders=10` and `max_replication_slots=10` to the postgres command section, making replication capability intentional and auditable rather than silently relying on PostgreSQL defaults.

---

### Fix BUG-HA-09: Standby Dev Compose Timeouts (Moderate)

**File:** `docker-compose.ha-standby.yml`

**Approach:** Add `idle_in_transaction_session_timeout=30000` and `statement_timeout=30000` to match the production standby configuration in `docker-compose.standby-prod.yml`.

---

### Fix BUG-HA-10: Accurate Lag Metric (Moderate)

**File:** `app/modules/ha/replication.py`

**Approach:** Change the lag SQL in both `get_replication_lag` and `get_replication_status` to use the more accurate receipt time:

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

`last_msg_receipt_time` is only updated when data arrives, making it a more accurate lag indicator during active replication. Using `GREATEST` of both ensures the metric reflects the most recent meaningful activity.

---

### Fix BUG-HA-11: pg_hba.conf Restriction Script (Moderate)

**Files:** New `scripts/configure_pg_hba.sh`, `docs/HA_REPLICATION_GUIDE.md`

**Approach:** Create a script that appends IP-specific replication rules to the postgres container's `pg_hba.conf` and reloads the configuration.

```bash
#!/bin/bash
# Adds IP-restricted replication rule to pg_hba.conf inside the Docker container.
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

Add a reference to this script in `docs/HA_REPLICATION_GUIDE.md` under the Security section.

---

### Fix BUG-HA-12: Multi-Worker Cache Invalidation (Minor)

Covered by the Redis dirty-flag mechanism in Fix BUG-HA-06. When `save_config` completes, it writes `ha:hb_cache_dirty` to Redis. All workers check this flag before serving cached heartbeat responses.

---

### Fix BUG-HA-13: WebSocket Write Protection (Minor)

**File:** `app/modules/ha/middleware.py`

**Approach:** Extend `StandbyWriteProtectionMiddleware.__call__` to handle WebSocket connections with a path allowlist:

```python
if scope_type == "websocket":
    path = scope.get("path", "")
    _WS_ALLOWED_PREFIXES = ("/ws/kitchen/", "/api/v1/ha/")
    if _node_role == "standby" or _split_brain_blocked:
        if not any(path.startswith(p) for p in _WS_ALLOWED_PREFIXES):
            await send({
                "type": "websocket.close",
                "code": 1013,  # Try Again Later
                "reason": "This node is in standby mode. Writes not accepted.",
            })
            return
```

Kitchen display WebSocket (`/ws/kitchen/`) is explicitly allowed as it is read-only (Redis pub/sub subscriber only).

---

### Fix BUG-HA-14: Exclude `dead_letter` from Publication (Minor)

**File:** `app/modules/ha/replication.py`

**Approach:** In `init_primary`, change the table exclusion filter:

```python
# BEFORE:
"WHERE schemaname = 'public' AND tablename != 'ha_config'"

# AFTER:
"WHERE schemaname = 'public' AND tablename NOT IN ('ha_config', 'dead_letter_queue')"
```

The actual table name must be verified from `app/models/dead_letter.py`. After failover, the new primary starts with an empty dead_letter table, preventing re-processing of partially-executed jobs from the old primary.

---

### Fix BUG-HA-15: Accurate Peer Role in Cluster Status (Minor)

**Files:** `app/modules/ha/heartbeat.py`, `app/modules/ha/service.py`

**Approach:** Store the actual peer role from heartbeat responses instead of inferring it as the opposite of the local role.

In `HeartbeatService`:
```python
# In __init__:
self.peer_role: str = "unknown"

# In _ping_peer(), after parsing the response:
self.peer_role = data.get("role", "unknown")
```

In `HAService.get_cluster_status`:
```python
# BEFORE:
peer_role = "standby" if cfg.role == "primary" else "primary"

# AFTER:
peer_role = _heartbeat_service.peer_role if _heartbeat_service is not None else "unknown"
```

---

## Files Changed / Created

### Modified Files

| File | Bugs Fixed |
|------|-----------|
| `app/modules/ha/replication.py` | BUG-HA-01, 02, 10, 14 |
| `app/main.py` | BUG-HA-04, 06 |
| `app/modules/ha/heartbeat.py` | BUG-HA-06, 15 |
| `app/modules/ha/service.py` | BUG-HA-06, 15 |
| `app/modules/ha/middleware.py` | BUG-HA-13 |
| `app/modules/ha/router.py` | BUG-HA-06, 12 |
| `docker-compose.yml` | BUG-HA-05, 08 |
| `docker-compose.pi.yml` | BUG-HA-05 |
| `docker-compose.ha-standby.yml` | BUG-HA-09 |
| `docker-compose.standby-prod.yml` | BUG-HA-05 |
| `scripts/check_repl_status.sh` | BUG-HA-03 |
| `scripts/check_sync_status.sh` | BUG-HA-03 |
| `scripts/fix_replication.sh` | BUG-HA-03 |
| `docs/HA_REPLICATION_GUIDE.md` | BUG-HA-07, 11 |
| `docs/ISSUE_TRACKER.md` | All (logging) |

### New Files

| File | Purpose |
|------|---------|
| `scripts/configure_pg_hba.sh` | BUG-HA-11 — IP-restricted pg_hba.conf configuration |

---

## Testing Strategy

After implementing each fix, verify the following:

- [ ] **BUG-HA-01 (Sequences):** After init_standby + promote, run `SELECT nextval('organisations_id_seq')` — must return a value higher than MAX(id). First INSERT after promotion succeeds without duplicate key error.
- [ ] **BUG-HA-02 (Resync):** Call `POST /api/v1/ha/replication/resync` on a standby with existing data. No duplicate key error in logs; subscription status transitions to `active`.
- [ ] **BUG-HA-03 (Credentials):** Run `git log -p scripts/` — no password strings present. Scripts run correctly with SSH key auth.
- [ ] **BUG-HA-04 (Startup secret):** Set heartbeat secret via UI, restart app container, verify heartbeat HMAC succeeds (no "Invalid HMAC signature" in logs).
- [ ] **BUG-HA-05 (WAL guard):** Set `max_slot_wal_keep_size=512MB` temporarily, let standby fall behind, verify slot is invalidated (not disk-fill). Restore to 2048.
- [ ] **BUG-HA-06 (Multi-worker):** Start with `--workers 2`, verify Redis key `ha:heartbeat_lock` exists with one PID, and only one set of heartbeat pings reaches the standby every 10s.
- [ ] **BUG-HA-07 (Docs):** Review updated `HA_REPLICATION_GUIDE.md` partition warning for accuracy and completeness.
- [ ] **BUG-HA-08 (Base compose):** `docker compose exec postgres psql -U postgres -c "SHOW max_wal_senders"` returns `10`.
- [ ] **BUG-HA-09 (Standby timeouts):** `docker compose -f docker-compose.ha-standby.yml exec postgres psql -U postgres -c "SHOW statement_timeout"` returns `30000`.
- [ ] **BUG-HA-10 (Lag metric):** Under zero write activity on primary, `GET /api/v1/ha/replication/status` should NOT report near-zero lag.
- [ ] **BUG-HA-11 (pg_hba):** Run `scripts/configure_pg_hba.sh` against a test container. Verify `pg_hba.conf` contains the new rule and `pg_reload_conf()` returns true.
- [ ] **BUG-HA-12 (Cache):** After `save_config` in one worker, verify the other worker's heartbeat endpoint reflects the new config within one request.
- [ ] **BUG-HA-13 (WebSocket):** Connect to `ws://localhost:8081/ws/kitchen/test-org/all` on standby — connection allowed. Non-allowlisted WebSocket path — close code 1013.
- [ ] **BUG-HA-14 (dead_letter):** After `init_primary`, query `SELECT tablename FROM pg_publication_tables WHERE pubname = 'orainvoice_ha_pub' AND tablename = 'dead_letter_queue'` — must return 0 rows.
- [ ] **BUG-HA-15 (Peer role):** In standalone mode, `GET /api/v1/ha/cluster-status` peer entry shows `role: "unknown"`, not `role: "primary"`.

---

## Risk Assessment

| Task | Bug | Risk of Regression | Mitigation |
|------|-----|--------------------|------------|
| 1 | BUG-HA-01 — Sequence replication | Medium — alters publication DDL; PG16 required | Verify PG16 version before altering; sequence sync is additive |
| 2 | BUG-HA-02 — Resync truncation | Low — adds truncation as first step; same logic used in init_standby | Existing test coverage on truncation function |
| 3 | BUG-HA-03 — Script credentials | Zero for app code; rotate credentials separately | Rotate before removing from scripts |
| 4 | BUG-HA-04 — Startup secret | Low — changes secret source, same interface | Verify HMAC succeeds after restart |
| 5 | BUG-HA-05 — WAL guard | Low — additive postgres config | Test slot invalidation behaviour before production |
| 6 | BUG-HA-06 — Multi-worker lock | Medium — new Redis dependency in startup | Fallback: if Redis unavailable, log warning and proceed without lock |
| 7 | BUG-HA-07 — Docs | Zero | Review only |
| 8 | BUG-HA-08 — Base compose WAL | Low — additive config | Existing compose tests |
| 9 | BUG-HA-09 — Standby timeouts | Low — additive config | Existing compose tests |
| 10 | BUG-HA-10 — Lag metric | Low — SQL change only; same return type | Verify no NULL when no messages received |
| 11 | BUG-HA-11 — pg_hba script | Low — script only, no app code | Test against a dev container |
| 12 | BUG-HA-12 — Cache invalidation | Low — covered by BUG-HA-06 Redis mechanism | Redis fallback to TTL-based expiry |
| 13 | BUG-HA-13 — WebSocket middleware | Low — new branch for websocket type | Kitchen display WS must still work on primary |
| 14 | BUG-HA-14 — Dead letter exclusion | Low — narrows publication set | Verify dead_letter not in publication after re-init |
| 15 | BUG-HA-15 — Peer role | Low — read-only display fix | No data path affected |
