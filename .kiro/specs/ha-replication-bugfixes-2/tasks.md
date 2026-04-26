# HA Replication Bugfixes (Round 2) — Implementation Tasks

## Overview

6 implementation tasks covering all confirmed bugs from the post-bugfix review (`docs/HA_REPLICATION_REVIEW_2.md`), ordered by severity (critical → significant → minor). Each parent task maps to one bug with sub-tasks for specific code changes. Includes exploration tests (bug condition), preservation tests, and checkpoints per the bugfix methodology.

**Builds on:** `.kiro/specs/ha-replication-bugfixes/` (original 15-bug fix specification)

---

## Tasks

### Exploration & Preservation Tests

- [x] 1. Write bug condition exploration tests (BEFORE implementing fixes)
  - **Property 1: Bug Condition** - HA Replication Round 2 Bugs
  - **IMPORTANT**: Write these tests BEFORE implementing any fixes
  - **GOAL**: Surface counterexamples that demonstrate all 6 bugs exist in the unfixed code
  - **Scoped PBT Approach**: Each test targets a specific bug condition from the design
  - Test CRIT-1: Mock `drop_subscription` and `_exec_autocommit`, call `trigger_resync` — verify `_cleanup_orphaned_slot_on_peer` is NOT called between drop and create (confirms orphaned slot bug)
  - Test CRIT-2 (promote): Create mock `_heartbeat_service` with `local_role="standby"`, call `promote()` — verify `_heartbeat_service.local_role` is still `"standby"` after promote (confirms local_role not updated)
  - Test CRIT-2 (demote): Create mock `_heartbeat_service` with `local_role="primary"`, call `demote()` — verify `_heartbeat_service.local_role` is still `"primary"` after demote (confirms spurious split-brain)
  - Test CRIT-2 (demote_and_sync): Create mock `_heartbeat_service` with `local_role="primary"`, call `demote_and_sync()` — verify `_heartbeat_service.local_role` is still `"primary"` (confirms same bug)
  - Test CRIT-3: Inspect `drop_replication_slot` function signature — verify it has no `db` parameter and passes `None` to `ReplicationManager.drop_replication_slot` (confirms 500 on every call)
  - Test SIG-1: Mock config change that triggers heartbeat restart in `save_config` — verify new `HeartbeatService` instance has `_redis_lock_key is None` (confirms Redis lock lost)
  - Test SIG-2a: Mock `_exec_autocommit` to capture SQL, trigger `resume_subscription` fallback path — verify SQL does NOT contain `copy_data = false` (confirms duplicate PK violations)
  - Test SIG-2b: Mock `demote()` call — verify `drop_publication` is NOT called (confirms orphaned publication)
  - Test MIN-1: Parse `docker-compose.ha-standby.yml` — verify `max_wal_senders` and `max_replication_slots` are NOT in postgres command (confirms missing settings)
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: All tests FAIL (this confirms the bugs exist)
  - Document counterexamples found for each bug
  - Mark task complete when tests are written, run, and failures documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10_

- [x] 2. Write preservation property tests (BEFORE implementing fixes)
  - **Property 2: Preservation** - Existing HA Behavior Unchanged
  - **IMPORTANT**: Follow observation-first methodology — observe behavior on UNFIXED code first
  - Observe: `init_standby` with `truncate_first=True` truncates tables, handles orphaned slots via `_cleanup_orphaned_slot_on_peer`, creates subscription — unchanged by CRIT-1 fix
  - Observe: `drop_subscription` executes DISABLE → SET slot_name=NONE → DROP SUBSCRIPTION sequence — unchanged
  - Observe: `_execute_auto_promote` sets `self.local_role = "primary"` directly — unchanged by CRIT-2 fix
  - Observe: `list_replication_slots` endpoint uses `db: AsyncSession = Depends(get_db_session)` — unchanged by CRIT-3 fix
  - Observe: `_start_ha_heartbeat` in `main.py` wires `_redis_lock_key`, `_lock_ttl`, `_redis_client` — unchanged by SIG-1 fix
  - Observe: `resume_subscription` enable path (ALTER SUBSCRIPTION ENABLE) works without re-creating — unchanged by SIG-2 fix
  - Observe: `promote()` checks lag, stops subscription, updates role, syncs sequences, writes audit log — unchanged by CRIT-2 fix
  - Observe: `demote_and_sync()` truncates tables, creates subscription via `init_standby`, clears split-brain — unchanged by CRIT-2 fix
  - Observe: `docker-compose.ha-standby.yml` has `wal_level=logical`, timeouts, SSL config — unchanged by MIN-1 fix
  - Observe: `trigger_resync` truncation failure propagates and subscription is left untouched — unchanged by CRIT-1 fix
  - Write property-based tests capturing all observed behaviors
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: All tests PASS (confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10_

### Critical Fixes

- [x] 3. Fix CRIT-1: Add orphaned slot cleanup to `trigger_resync` (Critical)

  - [x] 3.1 Add `_cleanup_orphaned_slot_on_peer` call in `trigger_resync` in `app/modules/ha/replication.py`
    - Insert `await ReplicationManager._cleanup_orphaned_slot_on_peer(primary_conn_str)` between `drop_subscription(db)` and the `CREATE SUBSCRIPTION` SQL
    - This follows the exact pattern already used by `init_standby` for orphaned slot handling
    - Add comment: `# Step 3: clean up orphaned slot left on primary by SET (slot_name = NONE)`
    - _Bug_Condition: isBugCondition(input) where input.operation == "trigger_resync" AND input.prior_subscription_existed == true_
    - _Expected_Behavior: `_cleanup_orphaned_slot_on_peer` called between drop_subscription and CREATE SUBSCRIPTION_
    - _Preservation: `init_standby` orphaned slot handling unchanged (Req 3.1); `drop_subscription` sequence unchanged (Req 3.2); truncation failure propagation unchanged (Req 3.10)_
    - _Requirements: 2.1, 2.2_

  - [x] 3.2 Verify bug condition exploration test now passes for CRIT-1
    - **Property 1: Expected Behavior** - Orphaned Slot Cleanup in trigger_resync
    - **IMPORTANT**: Re-run the SAME CRIT-1 test from task 1 — do NOT write a new test
    - The test from task 1 now verifies `_cleanup_orphaned_slot_on_peer` IS called between drop and create
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.1, 2.2_

- [x] 4. Fix CRIT-2: Update `_heartbeat_service.local_role` in manual role transitions (Critical)

  - [x] 4.1 Add `local_role` update in `promote()` in `app/modules/ha/service.py`
    - After `set_node_role("primary", cfg.peer_endpoint)`, add:
    - `if _heartbeat_service is not None: _heartbeat_service.local_role = "primary"`
    - _Bug_Condition: isBugCondition(input) where input.operation == "promote" AND input.heartbeat_service_running == true_
    - _Expected_Behavior: `_heartbeat_service.local_role == "primary"` after promote_
    - _Preservation: `promote()` full flow unchanged (Req 3.7); auto-promote `local_role` update unchanged (Req 3.3)_
    - _Requirements: 2.3_

  - [x] 4.2 Add `local_role` update in `demote()` in `app/modules/ha/service.py`
    - After `set_node_role("standby", cfg.peer_endpoint)`, add:
    - `if _heartbeat_service is not None: _heartbeat_service.local_role = "standby"`
    - _Bug_Condition: isBugCondition(input) where input.operation == "demote" AND input.heartbeat_service_running == true_
    - _Expected_Behavior: `_heartbeat_service.local_role == "standby"` after demote_
    - _Preservation: `demote()` existing flow unchanged_
    - _Requirements: 2.4_

  - [x] 4.3 Add `local_role` update in `demote_and_sync()` in `app/modules/ha/service.py`
    - After `set_node_role("standby", cfg.peer_endpoint)`, add:
    - `if _heartbeat_service is not None: _heartbeat_service.local_role = "standby"`
    - _Bug_Condition: isBugCondition(input) where input.operation == "demote_and_sync" AND input.heartbeat_service_running == true_
    - _Expected_Behavior: `_heartbeat_service.local_role == "standby"` after demote_and_sync_
    - _Preservation: `demote_and_sync()` full flow unchanged (Req 3.8)_
    - _Requirements: 2.5_

  - [x] 4.4 Verify bug condition exploration test now passes for CRIT-2
    - **Property 1: Expected Behavior** - local_role Updated on Manual Role Transitions
    - **IMPORTANT**: Re-run the SAME CRIT-2 tests from task 1 — do NOT write new tests
    - Tests now verify `_heartbeat_service.local_role` IS updated after promote/demote/demote_and_sync
    - **EXPECTED OUTCOME**: Tests PASS (confirms bug is fixed)
    - _Requirements: 2.3, 2.4, 2.5_

- [x] 5. Fix CRIT-3: Add `db` dependency to `drop_replication_slot` endpoint (Critical)

  - [x] 5.1 Add `db: AsyncSession = Depends(get_db_session)` parameter to `drop_replication_slot` in `app/modules/ha/router.py`
    - Change signature from `async def drop_replication_slot(slot_name: str)` to `async def drop_replication_slot(slot_name: str, db: AsyncSession = Depends(get_db_session))`
    - Change `ReplicationManager.drop_replication_slot(None, slot_name)` to `ReplicationManager.drop_replication_slot(db, slot_name)`
    - Matches the pattern used by the adjacent `list_replication_slots` endpoint
    - _Bug_Condition: isBugCondition(input) where input.operation == "drop_slot_endpoint"_
    - _Expected_Behavior: `db` (not `None`) passed to `ReplicationManager.drop_replication_slot`_
    - _Preservation: `list_replication_slots` endpoint unchanged (Req 3.4)_
    - _Requirements: 2.6_

  - [x] 5.2 Verify bug condition exploration test now passes for CRIT-3
    - **Property 1: Expected Behavior** - drop_replication_slot Has DB Session
    - **IMPORTANT**: Re-run the SAME CRIT-3 test from task 1 — do NOT write a new test
    - Test now verifies the endpoint has `db` parameter and passes it correctly
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.6_

- [x] 6. Checkpoint: verify critical fixes
  - Run all exploration tests from task 1 for CRIT-1, CRIT-2, CRIT-3 — all should PASS
  - Run all preservation tests from task 2 — all should still PASS (no regressions)
  - Verify `trigger_resync` call sequence: truncate → drop_subscription → cleanup_orphaned_slot → CREATE SUBSCRIPTION
  - Verify `promote()`/`demote()`/`demote_and_sync()` update `_heartbeat_service.local_role` when service exists and handle `None` gracefully
  - Verify `drop_replication_slot` endpoint function signature includes `db` parameter
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

### Significant Fixes

- [x] 7. Fix SIG-1: Wire Redis lock info in `save_config` heartbeat restart (Significant)

  - [x] 7.1 Add Redis lock wiring after creating new `HeartbeatService` in `save_config` in `app/modules/ha/service.py`
    - After `_heartbeat_service = HeartbeatService(...)` and before `await _heartbeat_service.start()`, add:
    - ```python
      try:
          from app.core.redis import redis_pool
          _heartbeat_service._redis_lock_key = "ha:heartbeat_lock"
          _heartbeat_service._lock_ttl = 30
          _heartbeat_service._redis_client = redis_pool
      except Exception:
          pass  # Redis unavailable — lock renewal won't work but service still runs
      ```
    - This replicates the exact pattern from `_start_ha_heartbeat` in `main.py`
    - _Bug_Condition: isBugCondition(input) where input.operation == "save_config" AND input.triggers_heartbeat_restart == true_
    - _Expected_Behavior: new HeartbeatService has `_redis_lock_key`, `_lock_ttl`, `_redis_client` set_
    - _Preservation: `_start_ha_heartbeat` in `main.py` Redis lock wiring unchanged (Req 3.5)_
    - _Requirements: 2.7_

  - [x] 7.2 Verify bug condition exploration test now passes for SIG-1
    - **Property 1: Expected Behavior** - Heartbeat Restart Preserves Redis Lock
    - **IMPORTANT**: Re-run the SAME SIG-1 test from task 1 — do NOT write a new test
    - Test now verifies new `HeartbeatService` has Redis lock attributes set
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.7_

- [x] 8. Fix SIG-2: Demote uses `copy_data=false` and drops publication (Significant)

  - [x] 8.1 Add `copy_data = false` to `resume_subscription` fallback path in `app/modules/ha/replication.py`
    - In the fallback `CREATE SUBSCRIPTION` SQL (after `drop_subscription` in `resume_subscription`), change:
    - `f"PUBLICATION {ReplicationManager.PUBLICATION_NAME}"` to `f"PUBLICATION {ReplicationManager.PUBLICATION_NAME} WITH (copy_data = false)"`
    - This prevents duplicate PK violations when the node already has all the data
    - _Bug_Condition: isBugCondition(input) where input.operation == "demote" AND input.resume_subscription_fallback == true_
    - _Expected_Behavior: fallback CREATE SUBSCRIPTION SQL includes `copy_data = false`_
    - _Preservation: `resume_subscription` enable path (ALTER SUBSCRIPTION ENABLE) unchanged (Req 3.6)_
    - _Requirements: 2.8_

  - [x] 8.2 Add `drop_publication` call in `demote()` before `resume_subscription` in `app/modules/ha/service.py`
    - Before the `resume_subscription` call in `demote()`, add:
    - ```python
      try:
          await ReplicationManager.drop_publication(db)
      except Exception as exc:
          logger.warning("Could not drop publication during demote: %s", exc)
      ```
    - This removes the publication from the former primary (now standby)
    - _Bug_Condition: isBugCondition(input) where input.operation == "demote"_
    - _Expected_Behavior: `drop_publication(db)` called before `resume_subscription`_
    - _Preservation: `demote()` existing flow unchanged except for new publication drop step_
    - _Requirements: 2.9_

  - [x] 8.3 Verify bug condition exploration tests now pass for SIG-2
    - **Property 1: Expected Behavior** - Demote Uses copy_data=false and Drops Publication
    - **IMPORTANT**: Re-run the SAME SIG-2 tests from task 1 — do NOT write new tests
    - Tests now verify: (a) fallback SQL contains `copy_data = false`, (b) `drop_publication` IS called during demote
    - **EXPECTED OUTCOME**: Tests PASS (confirms bugs are fixed)
    - _Requirements: 2.8, 2.9_

### Minor Fix

- [x] 9. Fix MIN-1: Add explicit WAL settings to dev standby compose (Minor)

  - [x] 9.1 Add `max_wal_senders=10` and `max_replication_slots=10` to postgres command in `docker-compose.ha-standby.yml`
    - Append to the postgres command list:
    - `- "-c"` / `- "max_wal_senders=10"` and `- "-c"` / `- "max_replication_slots=10"`
    - This matches all other compose files (docker-compose.yml, docker-compose.pi.yml, docker-compose.standby-prod.yml)
    - _Bug_Condition: isBugCondition(input) where input.operation == "compose_start" AND input.compose_file == "docker-compose.ha-standby.yml"_
    - _Expected_Behavior: postgres command includes `max_wal_senders=10` and `max_replication_slots=10`_
    - _Preservation: existing `wal_level=logical`, timeouts, SSL config unchanged (Req 3.9)_
    - _Requirements: 2.10_

  - [x] 9.2 Verify bug condition exploration test now passes for MIN-1
    - **Property 1: Expected Behavior** - Dev Standby Compose Has Explicit WAL Settings
    - **IMPORTANT**: Re-run the SAME MIN-1 test from task 1 — do NOT write a new test
    - Test now verifies `max_wal_senders` and `max_replication_slots` ARE in postgres command
    - **EXPECTED OUTCOME**: Test PASSES (confirms fix applied)
    - _Requirements: 2.10_

### Verification & Preservation

- [x] 10. Verify all preservation tests still pass after all fixes
  - **Property 2: Preservation** - Existing HA Behavior Unchanged
  - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
  - Run all preservation property tests from task 2
  - **EXPECTED OUTCOME**: All tests PASS (confirms no regressions across all 6 fixes)
  - Confirm: `init_standby` orphaned slot handling unchanged (Req 3.1)
  - Confirm: `drop_subscription` DISABLE → SET → DROP sequence unchanged (Req 3.2)
  - Confirm: `_execute_auto_promote` `local_role` update unchanged (Req 3.3)
  - Confirm: `list_replication_slots` `db` dependency unchanged (Req 3.4)
  - Confirm: `_start_ha_heartbeat` Redis lock wiring unchanged (Req 3.5)
  - Confirm: `resume_subscription` enable path unchanged (Req 3.6)
  - Confirm: `promote()` full flow unchanged (Req 3.7)
  - Confirm: `demote_and_sync()` full flow unchanged (Req 3.8)
  - Confirm: Compose existing settings unchanged (Req 3.9)
  - Confirm: `trigger_resync` truncation failure propagation unchanged (Req 3.10)
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10_

### Issue Tracking & Final Checkpoint

- [x] 11. Log all 6 bugs in `docs/ISSUE_TRACKER.md`
  - Add ISSUE-129: CRIT-1 — `trigger_resync` orphaned slot → resync always fails on second call
  - Add ISSUE-130: CRIT-2 — `promote()`/`demote()`/`demote_and_sync()` don't update `_heartbeat_service.local_role`
  - Add ISSUE-131: CRIT-3 — `drop_replication_slot` router passes `None` as db → 500 on every call
  - Add ISSUE-132: SIG-1 — `save_config` restarts heartbeat without Redis lock info
  - Add ISSUE-133: SIG-2 — `demote()` uses `copy_data=true` on full dataset and doesn't drop publication
  - Add ISSUE-134: MIN-1 — Dev standby compose missing `max_wal_senders` and `max_replication_slots`
  - Each entry includes: date, severity, status (fixed), symptoms, root cause, fix applied, files changed
  - Follow format from `steering/issue-tracking-workflow.md`
  - Reference spec: `.kiro/specs/ha-replication-bugfixes-2/`
  - _Requirements: 1.1–1.10, 2.1–2.10_

- [x] 12. Checkpoint — Ensure all tests pass
  - Run full test suite: all exploration tests (task 1) should PASS on fixed code
  - Run full test suite: all preservation tests (task 2) should PASS on fixed code
  - Verify no regressions in existing HA test suite
  - Ensure all tests pass, ask the user if questions arise.

---

## Notes

### Severity and Risk Summary

| Bug | Task | Risk Level | Key Mitigation |
|-----|------|------------|----------------|
| CRIT-1 | 3 | Low | Adds one existing function call between existing steps; `_cleanup_orphaned_slot_on_peer` is battle-tested in `init_standby` |
| CRIT-2 | 4 | Low | Adds 3 one-liner attribute assignments; follows exact pattern from `_execute_auto_promote` |
| CRIT-3 | 5 | Low | Adds standard FastAPI dependency injection; matches adjacent `list_replication_slots` endpoint |
| SIG-1 | 7 | Low | Copies 4 lines from `_start_ha_heartbeat`; wrapped in try/except for safety |
| SIG-2 | 8 | Medium | `copy_data=false` affects `resume_subscription` globally; `drop_publication` adds new step to demote. Both correct but should be tested with real postgres |
| MIN-1 | 9 | Low | Adds explicit config matching existing defaults; no behavioral change |

### Implementation Order

1. **Exploration tests** (Task 1) — confirm all 6 bugs exist on unfixed code
2. **Preservation tests** (Task 2) — capture baseline behavior on unfixed code
3. **Critical fixes** (Tasks 3–5) — CRIT-1, CRIT-2, CRIT-3
4. **Critical checkpoint** (Task 6) — verify critical fixes and no regressions
5. **Significant fixes** (Tasks 7–8) — SIG-1, SIG-2
6. **Minor fix** (Task 9) — MIN-1
7. **Preservation verification** (Task 10) — confirm no regressions across all fixes
8. **Issue tracking** (Task 11) — log ISSUE-129 through ISSUE-134
9. **Final checkpoint** (Task 12) — full test suite green

### Files Changed Summary

| File | Bug(s) | Changes |
|------|--------|---------|
| `app/modules/ha/replication.py` | CRIT-1, SIG-2 | Add `_cleanup_orphaned_slot_on_peer` in `trigger_resync`; add `WITH (copy_data = false)` in `resume_subscription` fallback |
| `app/modules/ha/service.py` | CRIT-2, SIG-1, SIG-2 | Update `_heartbeat_service.local_role` in promote/demote/demote_and_sync; wire Redis lock in `save_config`; add `drop_publication` in demote |
| `app/modules/ha/router.py` | CRIT-3 | Add `db: AsyncSession = Depends(get_db_session)` to `drop_replication_slot` |
| `docker-compose.ha-standby.yml` | MIN-1 | Add `max_wal_senders=10` and `max_replication_slots=10` to postgres command |
| `docs/ISSUE_TRACKER.md` | All | Add ISSUE-129 through ISSUE-134 |
