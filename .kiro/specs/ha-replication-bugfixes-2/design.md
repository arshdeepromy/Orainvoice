# HA Replication Bugfixes (Round 2) — Bugfix Design

## Overview

This design addresses 6 bugs discovered during the post-bugfix review of the HA replication system (`docs/HA_REPLICATION_REVIEW_2.md`), conducted after all 15 original bugs from `HA_REPLICATION_GAPS.md` were patched. The bugs span 3 critical defects (resync always fails on second call, split-brain detection broken after manual role changes, replication slot endpoint crashes), 2 significant issues (heartbeat restart loses Redis lock isolation, demote creates duplicate-key violations and leaves orphaned publication), and 1 minor gap (dev standby compose missing explicit WAL settings).

**Fix approach:** Each bug has a targeted, minimal fix that addresses the root cause without altering surrounding logic. All fixes follow patterns already established in the codebase (e.g., `_cleanup_orphaned_slot_on_peer` already exists and is used by `init_standby`; Redis lock wiring already exists in `_start_ha_heartbeat`).

## Glossary

- **Bug_Condition (C)**: The specific input/state combination that triggers each bug — e.g., calling `trigger_resync` when an orphaned slot exists on the primary
- **Property (P)**: The desired correct behavior when the bug condition holds — e.g., orphaned slot is cleaned up before CREATE SUBSCRIPTION
- **Preservation**: Existing behavior that must remain unchanged by the fix — e.g., `init_standby` orphaned slot handling, `drop_subscription` sequence, auto-promote `local_role` update
- **`trigger_resync`**: Method in `replication.py` that truncates standby data and re-creates the subscription with `copy_data=true` for a full re-sync
- **`_cleanup_orphaned_slot_on_peer`**: Method in `replication.py` that connects to the primary and drops an inactive orphaned replication slot
- **`_heartbeat_service`**: Module-level singleton in `service.py` — the `HeartbeatService` instance that pings the peer and runs split-brain detection
- **`local_role`**: Attribute on `HeartbeatService` used by `detect_split_brain()` to compare local vs peer roles
- **`_redis_lock_key` / `_lock_ttl` / `_redis_client`**: Redis distributed lock attributes on `HeartbeatService` that prevent duplicate heartbeat services across gunicorn workers (BUG-HA-06 fix)
- **`resume_subscription`**: Method in `replication.py` that re-enables an existing subscription or re-creates it if the slot is invalidated
- **`drop_publication`**: Method in `replication.py` that drops the publication on a node

## Bug Details

### Bug Condition

The bugs manifest across six distinct conditions in the HA replication system. Each condition represents a specific code path where the implementation is incomplete or incorrect.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type HAOperation (trigger_resync | promote | demote | demote_and_sync | drop_slot_endpoint | save_config_restart | demote_resume_sub | compose_start)
  OUTPUT: boolean

  -- CRIT-1: trigger_resync with prior subscription
  IF input.operation == "trigger_resync"
     AND input.prior_subscription_existed == true
  THEN RETURN true

  -- CRIT-2: manual role transition with active heartbeat service
  IF input.operation IN ["promote", "demote", "demote_and_sync"]
     AND input.heartbeat_service_running == true
  THEN RETURN true

  -- CRIT-3: drop_replication_slot endpoint called
  IF input.operation == "drop_slot_endpoint"
  THEN RETURN true

  -- SIG-1: save_config triggers heartbeat restart
  IF input.operation == "save_config"
     AND input.triggers_heartbeat_restart == true
  THEN RETURN true

  -- SIG-2a: demote() fallback creates subscription on node with existing data
  IF input.operation == "demote"
     AND input.resume_subscription_fallback == true
  THEN RETURN true

  -- SIG-2b: demote() doesn't drop publication
  IF input.operation == "demote"
  THEN RETURN true

  -- MIN-1: standby compose starts postgres
  IF input.operation == "compose_start"
     AND input.compose_file == "docker-compose.ha-standby.yml"
  THEN RETURN true

  RETURN false
END FUNCTION
```

### Examples

- **CRIT-1**: Admin clicks "Resync" button after replication was previously initialized → `trigger_resync` truncates tables, drops subscription (orphaning slot), then `CREATE SUBSCRIPTION` fails with "replication slot already exists" → standby is bricked (empty tables, no subscription)
- **CRIT-2 (promote)**: Admin manually promotes standby → `_heartbeat_service.local_role` stays "standby" → `detect_split_brain("standby", "primary")` returns False → true split-brain goes undetected
- **CRIT-2 (demote)**: Admin manually demotes primary → `_heartbeat_service.local_role` stays "primary" → `detect_split_brain("primary", "primary")` returns True → spurious split-brain blocks all requests until container restart
- **CRIT-3**: Admin clicks "Drop Slot" in replication slots UI → `drop_replication_slot(None, slot_name)` → `None.execute()` → `AttributeError` → 500 error
- **SIG-1**: Admin changes peer endpoint in HA config → `save_config` creates new `HeartbeatService` without Redis lock info → lock expires in 30s → second worker starts duplicate heartbeat
- **SIG-2**: Admin demotes primary after new primary has publication → `resume_subscription` fallback creates subscription with `copy_data=true` → duplicate PK violations on every table; old publication never dropped

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- `init_standby` must continue to truncate tables (when `truncate_first=True`), handle orphaned slots via `_cleanup_orphaned_slot_on_peer` with auto-retry, exactly as today (Req 3.1)
- `drop_subscription` must continue to execute DISABLE → SET slot_name=NONE → DROP SUBSCRIPTION in sequence, exactly as today (Req 3.2)
- `_execute_auto_promote` must continue to set `self.local_role = "primary"` directly on the heartbeat service instance, exactly as today (Req 3.3)
- `list_replication_slots` endpoint must continue to use `db: AsyncSession = Depends(get_db_session)`, exactly as today (Req 3.4)
- `_start_ha_heartbeat` in `main.py` must continue to set `_redis_lock_key`, `_lock_ttl`, and `_redis_client` on the initial HeartbeatService, exactly as today (Req 3.5)
- `resume_subscription` enable path (ALTER SUBSCRIPTION ENABLE) must continue to work without re-creating the subscription, exactly as today (Req 3.6)
- `promote()` must continue to check replication lag, stop subscription, update role, run sequence sync, update middleware, and write audit log, exactly as today (Req 3.7)
- `demote_and_sync()` must continue to truncate tables, create subscription via `init_standby`, update middleware, clear split-brain flags, and write audit log, exactly as today (Req 3.8)
- Dev standby postgres must continue to have `wal_level=logical`, `idle_in_transaction_session_timeout=30000`, `statement_timeout=30000`, and SSL configuration, exactly as today (Req 3.9)
- `trigger_resync` truncation failure must continue to propagate and leave the subscription untouched, exactly as today (Req 3.10)

**Scope:**
All inputs that do NOT match the bug conditions above should be completely unaffected by these fixes. This includes:
- `init_standby` (already has orphaned slot cleanup)
- Auto-promote path (already updates `local_role`)
- `list_replication_slots` endpoint (already has `db` dependency)
- Initial heartbeat startup in `main.py` (already has Redis lock wiring)
- `resume_subscription` enable path (not the fallback re-create path)
- All other compose files (already have explicit WAL settings)

## Hypothesized Root Cause

Based on the code review in `docs/HA_REPLICATION_REVIEW_2.md`, the root causes are confirmed (not hypothesized — the review document includes line-level analysis):

1. **CRIT-1 — Missing cleanup step**: `trigger_resync` calls `drop_subscription` → `CREATE SUBSCRIPTION` directly. `drop_subscription` uses `SET (slot_name = NONE)` which orphans the slot on the primary. `init_standby` handles this via `_cleanup_orphaned_slot_on_peer`, but `trigger_resync` was written separately and skips this step. The fix pattern already exists — it just needs to be called.

2. **CRIT-2 — Incomplete state update**: `_execute_auto_promote` (auto path) correctly sets `self.local_role = "primary"`. The manual paths `promote()`, `demote()`, `demote_and_sync()` only call `set_node_role()` (middleware) but never update `_heartbeat_service.local_role`. This is a simple omission — the auto-promote code shows the correct pattern.

3. **CRIT-3 — Missing FastAPI dependency**: `drop_replication_slot` endpoint was added without the `db: AsyncSession = Depends(get_db_session)` parameter. The adjacent `list_replication_slots` endpoint has it correctly. Copy-paste omission.

4. **SIG-1 — Incomplete heartbeat restart**: `_start_ha_heartbeat` in `main.py` sets Redis lock attributes after creating `HeartbeatService`. `save_config` in `service.py` creates a new `HeartbeatService` on config change but doesn't replicate the Redis lock wiring. The pattern exists in `main.py` — it just needs to be duplicated.

5. **SIG-2 — Wrong copy_data default + missing publication drop**: `resume_subscription` fallback path creates subscription without `WITH (copy_data = false)`. During `demote()`, the former primary already has all data, so `copy_data=true` (default) causes duplicate PK violations. Additionally, `demote()` never drops the publication, leaving the former primary with an active publication that retains WAL unnecessarily.

6. **MIN-1 — Missing explicit config**: `docker-compose.ha-standby.yml` relies on PostgreSQL 16 defaults for `max_wal_senders` and `max_replication_slots` instead of declaring them explicitly like all other compose files.

## Correctness Properties

Property 1: Bug Condition — Orphaned Slot Cleanup in trigger_resync (CRIT-1)

_For any_ call to `trigger_resync` where a prior subscription existed (and `drop_subscription` has orphaned the slot on the primary), the fixed `trigger_resync` SHALL call `_cleanup_orphaned_slot_on_peer(primary_conn_str)` between `drop_subscription` and `CREATE SUBSCRIPTION`, ensuring the slot is available for the new subscription.

**Validates: Requirements 2.1, 2.2**

Property 2: Bug Condition — local_role Updated on Manual Role Transitions (CRIT-2)

_For any_ manual role transition (`promote`, `demote`, `demote_and_sync`) where `_heartbeat_service is not None`, the fixed function SHALL set `_heartbeat_service.local_role` to the new role value ("primary" for promote, "standby" for demote/demote_and_sync) after calling `set_node_role()`, ensuring `detect_split_brain()` uses the correct local role.

**Validates: Requirements 2.3, 2.4, 2.5**

Property 3: Bug Condition — drop_replication_slot Endpoint Has DB Session (CRIT-3)

_For any_ call to `DELETE /api/v1/ha/replication/slots/{slot_name}`, the fixed endpoint SHALL inject `db: AsyncSession` via `Depends(get_db_session)` and pass it to `ReplicationManager.drop_replication_slot(db, slot_name)`, preventing the `AttributeError` on `None.execute()`.

**Validates: Requirements 2.6**

Property 4: Bug Condition — Heartbeat Restart Preserves Redis Lock (SIG-1)

_For any_ `save_config` call that triggers a heartbeat service restart, the new `HeartbeatService` instance SHALL have `_redis_lock_key`, `_lock_ttl`, and `_redis_client` set using the same values as `_start_ha_heartbeat` in `main.py`, ensuring the Redis heartbeat lock TTL continues to be renewed.

**Validates: Requirements 2.7**

Property 5: Bug Condition — Demote Uses copy_data=false and Drops Publication (SIG-2)

_For any_ `demote()` call, the fixed function SHALL (a) call `drop_publication(db)` before resuming the subscription, and (b) when `resume_subscription` falls back to re-creating the subscription, the SQL SHALL include `WITH (copy_data = false)` to prevent duplicate-key violations on a node that already has all the data.

**Validates: Requirements 2.8, 2.9**

Property 6: Bug Condition — Dev Standby Compose Has Explicit WAL Settings (MIN-1)

_For any_ start of the dev standby postgres via `docker-compose.ha-standby.yml`, the postgres command SHALL include `-c max_wal_senders=10` and `-c max_replication_slots=10` to match all other compose files.

**Validates: Requirements 2.10**

Property 7: Preservation — Existing Behavior Unchanged

_For any_ input where the bug condition does NOT hold (non-buggy code paths), the fixed code SHALL produce exactly the same behavior as the original code, preserving all existing functionality including: `init_standby` orphaned slot handling, `drop_subscription` sequence, auto-promote `local_role` update, `list_replication_slots` db dependency, startup Redis lock wiring, `resume_subscription` enable path, `promote()` full flow, `demote_and_sync()` full flow, existing compose settings, and `trigger_resync` truncation failure propagation.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10**

## Fix Implementation

### Changes Required

All root causes are confirmed by the review document. Each fix follows an existing pattern in the codebase.

### CRIT-1: Add orphaned slot cleanup to `trigger_resync`

**File**: `app/modules/ha/replication.py`
**Function**: `trigger_resync`

**Specific Changes**:
1. **Add `_cleanup_orphaned_slot_on_peer` call**: Insert `await ReplicationManager._cleanup_orphaned_slot_on_peer(primary_conn_str)` between `drop_subscription(db)` and the `CREATE SUBSCRIPTION` SQL execution.

**Fixed code:**
```python
@staticmethod
async def trigger_resync(db: AsyncSession, primary_conn_str: str) -> None:
    logger.info("Triggering full re-sync — truncating standby data first")
    # Step 1: truncate all tables (raises RuntimeError on failure, aborts early)
    await ReplicationManager.truncate_all_tables()
    # Step 2: drop existing subscription
    await ReplicationManager.drop_subscription(db)
    # Step 3: clean up orphaned slot left on primary by SET (slot_name = NONE)
    await ReplicationManager._cleanup_orphaned_slot_on_peer(primary_conn_str)
    # Step 4: re-create subscription with full data copy
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

### CRIT-2: Update `_heartbeat_service.local_role` in manual role transitions

**File**: `app/modules/ha/service.py`
**Functions**: `promote()`, `demote()`, `demote_and_sync()`

**Specific Changes**:
1. **In `promote()`**: After `set_node_role("primary", cfg.peer_endpoint)`, add:
   ```python
   if _heartbeat_service is not None:
       _heartbeat_service.local_role = "primary"
   ```

2. **In `demote()`**: After `set_node_role("standby", cfg.peer_endpoint)`, add:
   ```python
   if _heartbeat_service is not None:
       _heartbeat_service.local_role = "standby"
   ```

3. **In `demote_and_sync()`**: After `set_node_role("standby", cfg.peer_endpoint)`, add:
   ```python
   if _heartbeat_service is not None:
       _heartbeat_service.local_role = "standby"
   ```

---

### CRIT-3: Add `db` dependency to `drop_replication_slot` endpoint

**File**: `app/modules/ha/router.py`
**Function**: `drop_replication_slot`

**Specific Changes**:
1. **Add `db` parameter**: Change function signature from `async def drop_replication_slot(slot_name: str)` to `async def drop_replication_slot(slot_name: str, db: AsyncSession = Depends(get_db_session))`
2. **Pass `db` to manager**: Change `ReplicationManager.drop_replication_slot(None, slot_name)` to `ReplicationManager.drop_replication_slot(db, slot_name)`

**Fixed code:**
```python
async def drop_replication_slot(
    slot_name: str,
    db: AsyncSession = Depends(get_db_session),
):
    try:
        result = await ReplicationManager.drop_replication_slot(db, slot_name)
        ...
```

---

### SIG-1: Wire Redis lock info in `save_config` heartbeat restart

**File**: `app/modules/ha/service.py`
**Function**: `save_config`

**Specific Changes**:
1. **Add Redis lock wiring**: After creating the new `HeartbeatService` and before calling `start()`, add the same Redis lock wiring pattern used in `_start_ha_heartbeat` in `main.py`:
   ```python
   # Wire Redis lock info so the new service renews the lock TTL (BUG-HA-06)
   try:
       from app.core.redis import redis_pool
       _heartbeat_service._redis_lock_key = "ha:heartbeat_lock"
       _heartbeat_service._lock_ttl = 30
       _heartbeat_service._redis_client = redis_pool
   except Exception:
       pass  # Redis unavailable — lock renewal won't work but service still runs
   ```

---

### SIG-2: Fix `demote()` to drop publication and use `copy_data=false`

**File**: `app/modules/ha/service.py`
**Function**: `demote()`

**Specific Changes**:
1. **Drop publication before resuming subscription**: Add `drop_publication(db)` call before the `resume_subscription` call:
   ```python
   # Drop this node's publication (it is no longer a primary)
   try:
       await ReplicationManager.drop_publication(db)
   except Exception as exc:
       logger.warning("Could not drop publication during demote: %s", exc)
   ```

**File**: `app/modules/ha/replication.py`
**Function**: `resume_subscription`

2. **Add `copy_data=false` to fallback CREATE SUBSCRIPTION**: Change the fallback SQL from:
   ```python
   sql = (
       f"CREATE SUBSCRIPTION {ReplicationManager.SUBSCRIPTION_NAME} "
       f"CONNECTION '{primary_conn_str}' "
       f"PUBLICATION {ReplicationManager.PUBLICATION_NAME}"
   )
   ```
   to:
   ```python
   sql = (
       f"CREATE SUBSCRIPTION {ReplicationManager.SUBSCRIPTION_NAME} "
       f"CONNECTION '{primary_conn_str}' "
       f"PUBLICATION {ReplicationManager.PUBLICATION_NAME} "
       f"WITH (copy_data = false)"
   )
   ```

---

### MIN-1: Add explicit WAL settings to dev standby compose

**File**: `docker-compose.ha-standby.yml`
**Section**: `services.postgres.command`

**Specific Changes**:
1. **Add `max_wal_senders=10`**: Append `- "-c"` and `- "max_wal_senders=10"` to the postgres command list
2. **Add `max_replication_slots=10`**: Append `- "-c"` and `- "max_replication_slots=10"` to the postgres command list

---

### Files Changed Summary

| File | Bug(s) | Change Description |
|------|--------|--------------------|
| `app/modules/ha/replication.py` | CRIT-1, SIG-2 | Add `_cleanup_orphaned_slot_on_peer` call in `trigger_resync`; add `WITH (copy_data = false)` in `resume_subscription` fallback |
| `app/modules/ha/service.py` | CRIT-2, SIG-1, SIG-2 | Update `_heartbeat_service.local_role` in `promote`/`demote`/`demote_and_sync`; wire Redis lock in `save_config`; add `drop_publication` in `demote` |
| `app/modules/ha/router.py` | CRIT-3 | Add `db: AsyncSession = Depends(get_db_session)` to `drop_replication_slot` endpoint |
| `docker-compose.ha-standby.yml` | MIN-1 | Add `max_wal_senders=10` and `max_replication_slots=10` to postgres command |

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bugs on unfixed code, then verify the fixes work correctly and preserve existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bugs BEFORE implementing the fix. Confirm the root cause analysis from `docs/HA_REPLICATION_REVIEW_2.md`.

**Test Plan**: Write unit tests that mock the database and replication manager methods, then verify the buggy behavior exists in the unfixed code.

**Test Cases**:
1. **CRIT-1 — Resync orphaned slot**: Mock `drop_subscription` and `_exec_autocommit`, call `trigger_resync` — verify `_cleanup_orphaned_slot_on_peer` is NOT called (will fail on unfixed code, confirming the bug)
2. **CRIT-2 — Promote local_role**: Create a mock `_heartbeat_service` with `local_role="standby"`, call `promote()` — verify `local_role` is still "standby" after promote (confirms the bug)
3. **CRIT-2 — Demote local_role**: Create a mock `_heartbeat_service` with `local_role="primary"`, call `demote()` — verify `local_role` is still "primary" after demote (confirms the bug)
4. **CRIT-3 — Drop slot endpoint**: Call `drop_replication_slot` endpoint via test client — verify it returns 500 (confirms the bug)
5. **SIG-1 — Save config Redis lock**: Mock config change that triggers heartbeat restart, verify new `HeartbeatService` has `_redis_lock_key is None` (confirms the bug)
6. **SIG-2 — Resume subscription SQL**: Mock `_exec_autocommit` to capture SQL, trigger `resume_subscription` fallback — verify SQL does NOT contain "copy_data = false" (confirms the bug)

**Expected Counterexamples**:
- CRIT-1: `_cleanup_orphaned_slot_on_peer` never called → CREATE SUBSCRIPTION fails with "already exists"
- CRIT-2: `_heartbeat_service.local_role` unchanged after promote/demote → split-brain detection wrong
- CRIT-3: `None.execute()` → `AttributeError` → 500 response
- SIG-1: `_redis_lock_key is None` → lock never renewed → duplicate heartbeat after 30s

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := fixedFunction(input)
  ASSERT expectedBehavior(result)
END FOR
```

**Test Cases**:
1. **CRIT-1**: After fix, `trigger_resync` calls `_cleanup_orphaned_slot_on_peer` between `drop_subscription` and `CREATE SUBSCRIPTION`
2. **CRIT-2**: After fix, `promote()` sets `_heartbeat_service.local_role = "primary"`; `demote()` and `demote_and_sync()` set it to `"standby"`
3. **CRIT-3**: After fix, `drop_replication_slot` endpoint passes `db` (not `None`) to `ReplicationManager.drop_replication_slot`
4. **SIG-1**: After fix, `save_config` heartbeat restart sets `_redis_lock_key`, `_lock_ttl`, `_redis_client` on new service
5. **SIG-2**: After fix, `resume_subscription` fallback SQL includes `copy_data = false`; `demote()` calls `drop_publication`
6. **MIN-1**: After fix, `docker-compose.ha-standby.yml` postgres command includes `max_wal_senders=10` and `max_replication_slots=10`

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT originalFunction(input) = fixedFunction(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain
- It catches edge cases that manual unit tests might miss
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs

**Test Plan**: Observe behavior on UNFIXED code first for non-bug-condition inputs, then write property-based tests capturing that behavior.

**Test Cases**:
1. **init_standby preservation**: Verify `init_standby` still truncates tables, handles orphaned slots, and creates subscription — unchanged by CRIT-1 fix
2. **drop_subscription preservation**: Verify DISABLE → SET slot_name=NONE → DROP sequence unchanged
3. **Auto-promote local_role preservation**: Verify `_execute_auto_promote` still sets `self.local_role = "primary"` — unchanged by CRIT-2 fix
4. **list_replication_slots preservation**: Verify endpoint still uses `db` dependency — unchanged by CRIT-3 fix
5. **Startup Redis lock preservation**: Verify `_start_ha_heartbeat` still wires Redis lock — unchanged by SIG-1 fix
6. **resume_subscription enable path preservation**: Verify ALTER SUBSCRIPTION ENABLE path still works without re-creating — unchanged by SIG-2 fix
7. **promote() full flow preservation**: Verify promote still checks lag, stops subscription, updates role, syncs sequences, writes audit log
8. **demote_and_sync() full flow preservation**: Verify demote_and_sync still truncates, creates subscription, clears split-brain
9. **Compose existing settings preservation**: Verify `wal_level=logical`, timeouts, SSL still present in standby compose
10. **trigger_resync truncation failure preservation**: Verify truncation failure still propagates and subscription is untouched

### Unit Tests

- Test `trigger_resync` call sequence (mock all replication methods, verify order: truncate → drop_subscription → cleanup_orphaned_slot → CREATE SUBSCRIPTION)
- Test `promote()` / `demote()` / `demote_and_sync()` update `_heartbeat_service.local_role` when service exists
- Test `promote()` / `demote()` / `demote_and_sync()` handle `_heartbeat_service is None` gracefully
- Test `drop_replication_slot` endpoint function signature includes `db` parameter
- Test `save_config` heartbeat restart sets Redis lock attributes
- Test `resume_subscription` fallback SQL contains `copy_data = false`
- Test `demote()` calls `drop_publication` before `resume_subscription`
- Test `docker-compose.ha-standby.yml` postgres command includes `max_wal_senders` and `max_replication_slots`

### Property-Based Tests

- Generate random role transition sequences (promote/demote/demote_and_sync in various orders) and verify `_heartbeat_service.local_role` always matches the DB role after each transition
- Generate random `save_config` inputs that trigger heartbeat restart and verify Redis lock attributes are always set on the new service
- Generate random `trigger_resync` scenarios (with/without prior subscription) and verify `_cleanup_orphaned_slot_on_peer` is always called after `drop_subscription`

### Integration Tests

- Test full resync flow: init_standby → trigger_resync → verify subscription re-created successfully (requires two postgres instances)
- Test promote → demote cycle: verify split-brain detection works correctly throughout
- Test save_config → heartbeat restart → verify Redis lock is maintained
- Test drop_replication_slot endpoint via FastAPI test client → verify 200 response (not 500)

### Risk Assessment

| Bug | Risk Level | Rollback Impact | Notes |
|-----|-----------|-----------------|-------|
| CRIT-1 | Low | None | Adds one function call between existing steps; `_cleanup_orphaned_slot_on_peer` is already battle-tested in `init_standby` |
| CRIT-2 | Low | None | Adds 3 one-liner attribute assignments; follows exact pattern from `_execute_auto_promote` |
| CRIT-3 | Low | None | Adds standard FastAPI dependency injection; matches adjacent endpoint pattern |
| SIG-1 | Low | None | Copies 4 lines from `_start_ha_heartbeat`; wrapped in try/except for safety |
| SIG-2 | Medium | Requires coordination | `copy_data=false` change affects `resume_subscription` globally (not just demote); `drop_publication` adds a new step to demote flow. Both are correct but should be tested with real postgres |
| MIN-1 | Low | None | Adds explicit config that matches existing defaults; no behavioral change |
