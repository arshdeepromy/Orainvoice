# HA GUI Config Cleanup (Round 3) — Implementation Tasks

## Overview

14 implementation tasks covering all 9 issues from the third HA replication audit (`docs/HA_REPLICATION_REVIEW_3.md`), ordered by severity (critical → moderate → minor). Includes exploration tests (bug condition), preservation tests, and checkpoints per the bugfix methodology. 23 changes across 8 files + 5 env files + 1 Alembic migration.

**Builds on:** `.kiro/specs/ha-replication-bugfixes/` (round 1) and `.kiro/specs/ha-replication-bugfixes-2/` (round 2).

**Review document:** `docs/HA_REPLICATION_REVIEW_3.md`

---

## Tasks

### Exploration & Preservation Tests

- [x] 1. Write bug condition exploration tests (BEFORE implementing fixes)
  - **Property 1: Bug Condition** - HA GUI Config Cleanup Round 3 Bugs
  - **IMPORTANT**: Write these tests BEFORE implementing any fixes
  - **GOAL**: Surface counterexamples that demonstrate all 9 bugs exist in the unfixed code
  - **Scoped PBT Approach**: Each test targets a specific bug condition from the design
  - **Test file**: `tests/test_ha_gui_config_cleanup_exploration.py`
  - Test CRIT (peer DB env fallback): Mock empty DB peer config, set `HA_PEER_DB_URL` env var to a test value, call `get_peer_db_url()` — verify it returns the env value instead of `None` (confirms env fallback is active)
  - Test MOD-1a (heartbeat secret env fallback): Call `_get_heartbeat_secret_from_config(None)` with `HA_HEARTBEAT_SECRET` env var set to `"dev-ha-secret-for-testing"` — verify it returns the env value instead of `""` (confirms env fallback is active)
  - Test MOD-1b (heartbeat endpoint env fallback): Inspect the heartbeat cache-miss code path in `router.py` — verify it reads `os.environ.get("HA_HEARTBEAT_SECRET", "")` when DB secret is empty (confirms env fallback in heartbeat endpoint)
  - Test MOD-2 (stale error messages): Inspect the error message strings at `router.py` replication_init and replication_resync — verify they contain `"HA_PEER_DB_URL"` (confirms stale env var reference)
  - Test MOD-3 (missing DB columns): Inspect `HAConfig` model — verify it does NOT have `local_lan_ip` or `local_pg_port` columns (confirms missing GUI fields)
  - Test MOD-4 (peer role not in failover-status): Inspect `FailoverStatusResponse` schema — verify it does NOT have a `peer_role` field (confirms hardcoded peer role)
  - Test MOD-5 (stop-replication no CONFIRM): Inspect the `needsConfirmText` logic in `HAReplication.tsx` — verify `'stop-replication'` is NOT in the list (confirms missing CONFIRM gate)
  - Test MIN-1 (auto-promote flag not reset): Create a `HeartbeatService` instance, set `_auto_promote_attempted = True`, simulate peer recovery (unreachable → healthy transition) — verify `_auto_promote_attempted` is still `True` (confirms flag never cleared)
  - Test MIN-2 (dead code): Verify function `_get_heartbeat_secret` exists in `service.py` (confirms dead code present)
  - Test MIN-3 (stale guide text): Inspect `HAReplication.tsx` setup guide — verify it contains `".env"` text (confirms stale reference)
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: All tests FAIL (this confirms the bugs exist)
  - Document counterexamples found for each bug
  - Mark task complete when tests are written, run, and failures documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 1.12, 1.13, 1.14, 1.15_

- [x] 2. Write preservation property tests (BEFORE implementing fixes)
  - **Property 2: Preservation** - Existing HA Config Behavior Unchanged
  - **IMPORTANT**: Follow observation-first methodology — observe behavior on UNFIXED code first
  - **Test file**: `tests/test_ha_gui_config_cleanup_preservation.py`
  - Observe: `_build_peer_db_url()` with fully populated DB peer config fields builds valid PostgreSQL URL — unchanged by CRIT fix (Req 3.1)
  - Observe: `_get_heartbeat_secret_from_config(cfg)` with valid encrypted DB secret returns decrypted value — unchanged by MOD-1 fix (Req 3.2)
  - Observe: heartbeat endpoint uses decrypted DB secret for HMAC signing when available — unchanged (Req 3.3)
  - Observe: `save_config` encrypts and stores `heartbeat_secret` when provided — unchanged (Req 3.4)
  - Observe: `save_config` encrypts and stores `peer_db_password` and persists all peer DB fields — unchanged (Req 3.5)
  - Observe: `_detect_host_lan_ip()` auto-detect chain (Docker Desktop → UDP socket → fallback) works when no override exists — unchanged by MOD-3 fix (Req 3.6)
  - Observe: `_heartbeat_service.peer_role` populated from heartbeat responses — unchanged (Req 3.7)
  - Observe: `get_cluster_status()` uses `_heartbeat_service.peer_role` for peer entry — unchanged (Req 3.8)
  - Observe: all existing CONFIRM gates (promote, demote, resync, demote-and-sync, standby init-replication) require CONFIRM — unchanged by MOD-5 fix (Req 3.9)
  - Observe: `_auto_promote_failed_permanently` is NOT reset on peer recovery — only `_auto_promote_attempted` is reset — unchanged by MIN-1 fix (Req 3.10)
  - Observe: `.env.pi-standby` already has blank `HA_HEARTBEAT_SECRET=` and `HA_PEER_DB_URL=` — unchanged (Req 3.11)
  - Observe: `HAConfigRequest` peer DB fields continue to be processed and stored — unchanged (Req 3.12)
  - Write property-based tests capturing all observed behaviors
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: All tests PASS (confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12_

### Critical Fix

- [ ] 3. Fix CRIT: Clear leaked password + remove env fallback for peer DB URL (Critical)

  - [x] 3.1 Clear `HA_PEER_DB_URL` from `.env.standby-prod`
    - Change `HA_PEER_DB_URL=postgresql://replicator:NoorHarleen1@192.168.1.90:5432/workshoppro` to `HA_PEER_DB_URL=`
    - This removes the leaked production password from the env file
    - _Bug_Condition: isBugCondition(input) where input.action == "read_env_file" AND input.file == ".env.standby-prod" AND env_contains_nonempty("HA_PEER_DB_URL")_
    - _Requirements: 2.1_

  - [x] 3.2 Clear `HA_PEER_DB_URL` from `.env` and `.env.ha-standby`
    - Change `.env` line `HA_PEER_DB_URL=postgresql://postgres:postgres@host.docker.internal:5433/workshoppro` to `HA_PEER_DB_URL=`
    - Change `.env.ha-standby` line `HA_PEER_DB_URL=postgresql://postgres:postgres@host.docker.internal:5434/workshoppro` to `HA_PEER_DB_URL=`
    - `.env.pi` and `.env.pi-standby` already have `HA_PEER_DB_URL=` blank — no change needed (Req 3.11)
    - _Requirements: 2.1_

  - [x] 3.3 Remove env fallback from `get_peer_db_url()` in `app/modules/ha/service.py`
    - Change `return os.environ.get("HA_PEER_DB_URL") or None` to `return None`
    - When DB peer config is empty, return `None` — do not silently use env var
    - _Bug_Condition: isBugCondition(input) where input.action == "get_peer_db_url" AND db_peer_config_empty(input)_
    - _Expected_Behavior: returns None without reading HA_PEER_DB_URL from environment_
    - _Preservation: `_build_peer_db_url()` unchanged (Req 3.1); peer DB fields processing unchanged (Req 3.12)_
    - _Requirements: 2.2_

  - [x] 3.4 Verify bug condition exploration test now passes for CRIT
    - **Property 1: Expected Behavior** - Peer DB URL Env Fallback Removed
    - **IMPORTANT**: Re-run the SAME CRIT test from task 1 — do NOT write a new test
    - The test from task 1 now verifies `get_peer_db_url()` returns `None` when DB config is empty (not env value)
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.1, 2.2_

### Moderate Fixes

- [ ] 4. Fix MOD-1: Remove heartbeat secret env fallbacks + clear env values (Moderate)

  - [x] 4.1 Remove env fallback from `_get_heartbeat_secret_from_config()` in `app/modules/ha/service.py`
    - Change `return os.environ.get("HA_HEARTBEAT_SECRET", "")` to `return ""`
    - When DB secret is empty or decryption fails, return empty string — do not silently use env var
    - _Bug_Condition: isBugCondition(input) where input.action == "get_heartbeat_secret" AND db_secret_empty_or_decrypt_fails(input)_
    - _Expected_Behavior: returns "" without reading HA_HEARTBEAT_SECRET from environment_
    - _Preservation: DB-stored secret decryption unchanged (Req 3.2)_
    - _Requirements: 2.3_

  - [x] 4.2 Remove env fallback from heartbeat endpoint cache-miss in `app/modules/ha/router.py`
    - In the `heartbeat()` function cache-miss branch, change `secret = os.environ.get("HA_HEARTBEAT_SECRET", "")` to `secret = ""`
    - When DB secret is empty or decryption fails, use empty string — do not fall back to env var
    - _Bug_Condition: isBugCondition(input) where input.action == "heartbeat_endpoint_cache_refresh" AND db_secret_empty_or_decrypt_fails(input)_
    - _Expected_Behavior: secret = "" without reading HA_HEARTBEAT_SECRET from environment_
    - _Preservation: heartbeat HMAC signing with valid DB secret unchanged (Req 3.3)_
    - _Requirements: 2.4_

  - [x] 4.3 Clear `HA_HEARTBEAT_SECRET` values from all `.env*` files
    - Change `.env` line `HA_HEARTBEAT_SECRET=dev-ha-secret-for-testing` to `HA_HEARTBEAT_SECRET=`
    - Change `.env.pi` line `HA_HEARTBEAT_SECRET=dev-ha-secret-for-testing` to `HA_HEARTBEAT_SECRET=`
    - Change `.env.ha-standby` line `HA_HEARTBEAT_SECRET=dev-ha-secret-for-testing` to `HA_HEARTBEAT_SECRET=`
    - Change `.env.standby-prod` line `HA_HEARTBEAT_SECRET=dev-ha-secret-for-testing` to `HA_HEARTBEAT_SECRET=`
    - `.env.pi-standby` already has `HA_HEARTBEAT_SECRET=` blank — no change needed (Req 3.11)
    - _Requirements: 2.5_

  - [x] 4.4 Verify bug condition exploration tests now pass for MOD-1
    - **Property 1: Expected Behavior** - Heartbeat Secret Env Fallbacks Removed
    - **IMPORTANT**: Re-run the SAME MOD-1 tests from task 1 — do NOT write new tests
    - Tests now verify `_get_heartbeat_secret_from_config(None)` returns `""` and heartbeat endpoint uses `""` when DB secret is empty
    - **EXPECTED OUTCOME**: Tests PASS (confirms bugs are fixed)
    - _Requirements: 2.3, 2.4, 2.5_

- [ ] 5. Fix MOD-2: Update error messages to remove env var references (Moderate)

  - [x] 5.1 Update error message in `replication_init()` in `app/modules/ha/router.py`
    - Change `"Peer database connection is not configured. Set peer DB settings in HA configuration or set HA_PEER_DB_URL environment variable."` to `"Peer database connection is not configured. Set peer DB settings in HA configuration."`
    - _Bug_Condition: isBugCondition(input) where input.action == "replication_init" AND input.error_message CONTAINS "HA_PEER_DB_URL"_
    - _Expected_Behavior: error message references GUI configuration only, not env var_
    - _Requirements: 2.6_

  - [x] 5.2 Update error message in `replication_resync()` in `app/modules/ha/router.py`
    - Change `"Peer database connection is not configured. Set peer DB settings in HA configuration or set HA_PEER_DB_URL environment variable."` to `"Peer database connection is not configured. Set peer DB settings in HA configuration."`
    - _Bug_Condition: isBugCondition(input) where input.action == "replication_resync" AND input.error_message CONTAINS "HA_PEER_DB_URL"_
    - _Expected_Behavior: error message references GUI configuration only, not env var_
    - _Requirements: 2.7_

  - [x] 5.3 Verify bug condition exploration test now passes for MOD-2
    - **Property 1: Expected Behavior** - Error Messages Reference GUI Only
    - **IMPORTANT**: Re-run the SAME MOD-2 test from task 1 — do NOT write a new test
    - Test now verifies error messages do NOT contain `"HA_PEER_DB_URL"`
    - **EXPECTED OUTCOME**: Test PASSES (confirms fix applied)
    - _Requirements: 2.6, 2.7_


- [ ] 6. Fix MOD-3: Add `local_lan_ip`/`local_pg_port` to DB model, schema, service, router, and frontend (Moderate)

  - [x] 6.1 Add columns to `HAConfig` model in `app/modules/ha/models.py`
    - Add `local_lan_ip: Mapped[str | None] = mapped_column(String(255), nullable=True)` after the `peer_db_sslmode` column
    - Add `local_pg_port: Mapped[int | None] = mapped_column(Integer, nullable=True)` after `local_lan_ip`
    - _Bug_Condition: isBugCondition(input) where input.action == "local_db_info" AND NOT db_has_local_lan_ip_column()_
    - _Expected_Behavior: HAConfig model has local_lan_ip and local_pg_port columns_
    - _Requirements: 2.8_

  - [x] 6.2 Create Alembic migration for new columns
    - Create migration file in `alembic/versions/` that adds `local_lan_ip VARCHAR(255)` and `local_pg_port INTEGER` columns to `ha_config` table, both nullable with no default
    - Use `op.add_column` with `sa.Column` — idempotent where possible
    - _Requirements: 2.8_

  - [x] 6.3 Add fields to `HAConfigRequest` and `HAConfigResponse` schemas in `app/modules/ha/schemas.py`
    - Add to `HAConfigRequest`: `local_lan_ip: str | None = Field(default=None, description="Local LAN IP override for View Connection Info (auto-detected if blank)")` and `local_pg_port: int | None = Field(default=None, description="Local PostgreSQL host port override (defaults to 5432 if blank)")`
    - Add to `HAConfigResponse`: `local_lan_ip: str | None = None` and `local_pg_port: int | None = None`
    - _Requirements: 2.11_

  - [x] 6.4 Add field handling in `save_config()` and `_config_to_response()` in `app/modules/ha/service.py`
    - In `save_config()` insert branch: add `cfg.local_lan_ip = config.local_lan_ip` and `cfg.local_pg_port = config.local_pg_port`
    - In `save_config()` update branch: add `if config.local_lan_ip is not None: cfg.local_lan_ip = config.local_lan_ip` and same for `local_pg_port`
    - In `_config_to_response()`: add `local_lan_ip=cfg.local_lan_ip` and `local_pg_port=cfg.local_pg_port`
    - _Preservation: existing save_config peer DB field handling unchanged (Req 3.5, 3.12)_
    - _Requirements: 2.11_

  - [x] 6.5 Update `local_db_info()` endpoint in `app/modules/ha/router.py` to prioritize DB fields
    - Load `HAConfig` from DB at the start of the endpoint
    - For LAN IP: if `cfg.local_lan_ip` is set, use it; else fall back to `_detect_host_lan_ip()` (which already checks env var then auto-detect)
    - For PG port: if `cfg.local_pg_port` is set, use it; else fall back to `int(os.environ.get("HA_LOCAL_PG_PORT", "5432"))`
    - _Preservation: `_detect_host_lan_ip()` auto-detect chain unchanged (Req 3.6)_
    - _Requirements: 2.10_

  - [x] 6.6 Update `create_replication_user()` endpoint in `app/modules/ha/router.py` to use DB fields
    - Same priority as `local_db_info()`: DB field > env var > auto-detect for LAN IP and PG port
    - Load `HAConfig` from the existing `db` session and use `cfg.local_lan_ip` / `cfg.local_pg_port` when set
    - _Requirements: 2.10_

  - [x] 6.7 Add form fields to `frontend/src/pages/admin/HAReplication.tsx`
    - Add form state: `formLocalLanIp` (string, default `''`) and `formLocalPgPort` (string, default `''`)
    - Add optional input fields in the Node Configuration section after the Heartbeat Secret field:
      - "Local LAN IP" with helper text: "Used for View Connection Info. Auto-detected if blank."
      - "Local PostgreSQL Port" with helper text: "The host port mapped to PostgreSQL. Defaults to 5432 if blank."
    - Include `local_lan_ip` and `local_pg_port` in the save payload (both in `handleSaveConfig` and `handleWizardSaveConfig`)
    - Populate from config on initial load: `setFormLocalLanIp(cfg.local_lan_ip || '')` and `setFormLocalPgPort(cfg.local_pg_port ? String(cfg.local_pg_port) : '')`
    - Follow safe-api-consumption patterns: use `cfg.local_lan_ip ?? ''` and `cfg.local_pg_port ?? null`
    - _Requirements: 2.9_

  - [x] 6.8 Verify bug condition exploration test now passes for MOD-3
    - **Property 1: Expected Behavior** - Local LAN IP/Port GUI Fields Added
    - **IMPORTANT**: Re-run the SAME MOD-3 test from task 1 — do NOT write a new test
    - Test now verifies `HAConfig` model HAS `local_lan_ip` and `local_pg_port` columns
    - **EXPECTED OUTCOME**: Test PASSES (confirms fix applied)
    - _Requirements: 2.8, 2.9, 2.10, 2.11_

- [ ] 7. Fix MOD-4: Add `peer_role` to failover-status response + fix frontend display (Moderate)

  - [x] 7.1 Add `peer_role` field to `FailoverStatusResponse` in `app/modules/ha/schemas.py`
    - Add `peer_role: str = Field(default="unknown", description="Actual peer role from heartbeat responses")`
    - _Bug_Condition: isBugCondition(input) where input.action == "render_peer_card" AND peer_role_is_hardcoded_opposite(input)_
    - _Expected_Behavior: FailoverStatusResponse includes peer_role field_
    - _Requirements: 2.12_

  - [x] 7.2 Populate `peer_role` in `failover_status()` endpoint in `app/modules/ha/router.py`
    - After the existing `hb_service` checks, add: `peer_role = hb_service.peer_role if hb_service is not None else "unknown"`
    - Add `peer_role=peer_role` to the `FailoverStatusResponse(...)` constructor
    - _Preservation: `_heartbeat_service.peer_role` population unchanged (Req 3.7); `get_cluster_status()` usage unchanged (Req 3.8)_
    - _Requirements: 2.12_

  - [x] 7.3 Add `peer_role` to `FailoverStatus` TypeScript interface in `frontend/src/pages/admin/HAReplication.tsx`
    - Add `peer_role?: string` to the `FailoverStatus` interface
    - _Requirements: 2.12_

  - [x] 7.4 Fix peer role display in Cluster Status peer card in `frontend/src/pages/admin/HAReplication.tsx`
    - Change the peer card Badge from hardcoded `config.role === 'primary' ? 'Standby' : 'Primary'` to use `failoverStatus?.peer_role ?? (config.role === 'primary' ? 'standby' : 'primary')`
    - Update the `roleVariant()` call to use the same dynamic peer role value
    - Follow safe-api-consumption patterns: use `?.` and `??` for fallback
    - _Expected_Behavior: peer card displays actual peer role from heartbeat data_
    - _Requirements: 2.13_

  - [x] 7.5 Verify bug condition exploration test now passes for MOD-4
    - **Property 1: Expected Behavior** - Peer Role From Heartbeat Data
    - **IMPORTANT**: Re-run the SAME MOD-4 test from task 1 — do NOT write a new test
    - Test now verifies `FailoverStatusResponse` HAS a `peer_role` field
    - **EXPECTED OUTCOME**: Test PASSES (confirms fix applied)
    - _Requirements: 2.12, 2.13_

- [ ] 8. Fix MOD-5: Add `stop-replication` to CONFIRM gate in frontend (Moderate)

  - [x] 8.1 Add `'stop-replication'` to `needsConfirmText` list in `frontend/src/pages/admin/HAReplication.tsx`
    - Change `['promote', 'demote', 'resync', 'demote-and-sync']` to `['promote', 'demote', 'resync', 'stop-replication', 'demote-and-sync']`
    - Also add `'stop-replication'` to the `isStandbyInit` condition check so it requires CONFIRM on both primary and standby
    - _Bug_Condition: isBugCondition(input) where input.action == "stop_replication_modal" AND NOT requires_confirm_text(input)_
    - _Expected_Behavior: stop-replication modal requires typing CONFIRM_
    - _Preservation: all existing CONFIRM gates unchanged (Req 3.9)_
    - _Requirements: 2.14_

  - [x] 8.2 Verify bug condition exploration test now passes for MOD-5
    - **Property 1: Expected Behavior** - Stop Replication Requires CONFIRM
    - **IMPORTANT**: Re-run the SAME MOD-5 test from task 1 — do NOT write a new test
    - Test now verifies `'stop-replication'` IS in the `needsConfirmText` list
    - **EXPECTED OUTCOME**: Test PASSES (confirms fix applied)
    - _Requirements: 2.14_

### Minor Fixes

- [ ] 9. Fix MIN-1: Reset `_auto_promote_attempted` on peer recovery (Minor)

  - [x] 9.1 Add flag reset in `_ping_loop()` peer recovery branch in `app/modules/ha/heartbeat.py`
    - In the branch where `previous_health == "unreachable" and self.peer_health != "unreachable"`, add `self._auto_promote_attempted = False` after the existing `self._peer_unreachable_since = None`
    - Do NOT reset `self._auto_promote_failed_permanently` — that flag is intentionally permanent (Req 3.10)
    - _Bug_Condition: isBugCondition(input) where input.action == "peer_recovery" AND auto_promote_attempted_not_reset(input)_
    - _Expected_Behavior: `_auto_promote_attempted` reset to False on peer recovery_
    - _Preservation: `_auto_promote_failed_permanently` NOT reset (Req 3.10)_
    - _Requirements: 2.15_

  - [x] 9.2 Verify bug condition exploration test now passes for MIN-1
    - **Property 1: Expected Behavior** - Auto-Promote Flag Reset on Recovery
    - **IMPORTANT**: Re-run the SAME MIN-1 test from task 1 — do NOT write a new test
    - Test now verifies `_auto_promote_attempted` IS reset to `False` on peer recovery
    - **EXPECTED OUTCOME**: Test PASSES (confirms fix applied)
    - _Requirements: 2.15_

- [ ] 10. Fix MIN-2: Delete dead code `_get_heartbeat_secret()` (Minor)

  - [x] 10.1 Delete `_get_heartbeat_secret()` function from `app/modules/ha/service.py`
    - Remove the entire function at lines 46-59 (the `def _get_heartbeat_secret()` function and its docstring)
    - This function reads only from env var, is never called after BUG-HA-04 fix, and causes confusion about which function is authoritative
    - _Bug_Condition: isBugCondition(input) where input.action == "inspect_codebase" AND function_exists("_get_heartbeat_secret")_
    - _Expected_Behavior: function `_get_heartbeat_secret()` no longer exists_
    - _Requirements: 2.16_

  - [x] 10.2 Verify bug condition exploration test now passes for MIN-2
    - **Property 1: Expected Behavior** - Dead Code Removed
    - **IMPORTANT**: Re-run the SAME MIN-2 test from task 1 — do NOT write a new test
    - Test now verifies `_get_heartbeat_secret` function does NOT exist in `service.py`
    - **EXPECTED OUTCOME**: Test PASSES (confirms dead code removed)
    - _Requirements: 2.16_

- [ ] 11. Fix MIN-3: Update setup guide text in frontend (Minor)

  - [x] 11.1 Update setup guide security note in `frontend/src/pages/admin/HAReplication.tsx`
    - Change the text `"protect your .env files too"` (in the Security Notes section of the SetupGuide component) to `"The heartbeat secret and peer DB credentials are stored encrypted in the database — no .env file entries are required for HA configuration"`
    - _Bug_Condition: isBugCondition(input) where input.action == "render_setup_guide" AND guide_text_mentions_env_files(input)_
    - _Expected_Behavior: setup guide references GUI-only configuration, not .env files_
    - _Requirements: 2.17_

  - [x] 11.2 Verify bug condition exploration test now passes for MIN-3
    - **Property 1: Expected Behavior** - Setup Guide References GUI-Only Config
    - **IMPORTANT**: Re-run the SAME MIN-3 test from task 1 — do NOT write a new test
    - Test now verifies setup guide text does NOT mention `.env` files for HA configuration
    - **EXPECTED OUTCOME**: Test PASSES (confirms fix applied)
    - _Requirements: 2.17_

### Verification & Preservation

- [x] 12. Verify all preservation tests still pass after all fixes
  - **Property 2: Preservation** - Existing HA Config Behavior Unchanged
  - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
  - Run all preservation property tests from task 2
  - **EXPECTED OUTCOME**: All tests PASS (confirms no regressions across all 9 fixes)
  - Confirm: `_build_peer_db_url()` unchanged (Req 3.1)
  - Confirm: DB-stored secret decryption unchanged (Req 3.2)
  - Confirm: heartbeat HMAC signing with valid DB secret unchanged (Req 3.3)
  - Confirm: `save_config` heartbeat secret encryption unchanged (Req 3.4)
  - Confirm: `save_config` peer DB field handling unchanged (Req 3.5)
  - Confirm: `_detect_host_lan_ip()` auto-detect chain unchanged (Req 3.6)
  - Confirm: `_heartbeat_service.peer_role` population unchanged (Req 3.7)
  - Confirm: `get_cluster_status()` peer role usage unchanged (Req 3.8)
  - Confirm: all existing CONFIRM gates unchanged (Req 3.9)
  - Confirm: `_auto_promote_failed_permanently` NOT reset on recovery (Req 3.10)
  - Confirm: `.env.pi-standby` blank values unchanged (Req 3.11)
  - Confirm: `HAConfigRequest` peer DB fields processing unchanged (Req 3.12)
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12_

### Issue Tracking & Final Checkpoint

- [x] 13. Log all 9 issues in `docs/ISSUE_TRACKER.md`
  - Add ISSUE-135: CRIT — Leaked password in `.env.standby-prod` + active `HA_PEER_DB_URL` env fallback in `get_peer_db_url()`
  - Add ISSUE-136: MOD-1 — `HA_HEARTBEAT_SECRET` env fallback still active in `_get_heartbeat_secret_from_config()` and heartbeat endpoint; dev secret in all `.env*` files
  - Add ISSUE-137: MOD-2 — Error messages at `replication/init` and `replication/resync` still reference `HA_PEER_DB_URL` env var
  - Add ISSUE-138: MOD-3 — No GUI fields for `local_lan_ip`/`local_pg_port`; auto-detect returns wrong IP in Docker on Linux
  - Add ISSUE-139: MOD-4 — Peer role hardcoded as logical opposite in frontend; `FailoverStatusResponse` missing `peer_role` field
  - Add ISSUE-140: MOD-5 — `stop-replication` on primary has no CONFIRM gate; can accidentally drop publication
  - Add ISSUE-141: MIN-1 — `_auto_promote_attempted` never cleared on peer recovery; auto-promote permanently disabled after one attempt
  - Add ISSUE-142: MIN-2 — Dead code `_get_heartbeat_secret()` still present in `service.py`
  - Add ISSUE-143: MIN-3 — Setup guide security notes still mention `.env` files for HA configuration
  - Each entry includes: date, severity, status (fixed), symptoms, root cause, fix applied, files changed
  - Reference spec: `.kiro/specs/ha-gui-config-cleanup/`
  - _Requirements: 1.1–1.15, 2.1–2.17_

- [x] 14. Checkpoint — Ensure all tests pass
  - Run full test suite: all exploration tests (task 1) should PASS on fixed code
  - Run full test suite: all preservation tests (task 2) should PASS on fixed code
  - Verify no regressions in existing HA test suite
  - Ensure all tests pass, ask the user if questions arise.

---

## Notes

### Severity and Risk Summary

| Bug | Task | Risk Level | Key Mitigation |
|-----|------|------------|----------------|
| CRIT | 3 | Low | Removes one `os.environ.get` line + clears env values; DB-stored config path unchanged |
| MOD-1 | 4 | Low | Removes two `os.environ.get` lines + clears env values; DB-stored secret path unchanged |
| MOD-2 | 5 | Low | String-only change in error messages; no logic change |
| MOD-3 | 6 | Medium | Adds 2 DB columns, schema fields, service handling, router logic, and frontend fields; touches 5 files + migration |
| MOD-4 | 7 | Low | Adds 1 field to schema + response; frontend uses `??` fallback for backward compatibility |
| MOD-5 | 8 | Low | Adds 1 string to an array in frontend; no backend change |
| MIN-1 | 9 | Low | Adds 1 line in peer recovery branch; `_auto_promote_failed_permanently` intentionally NOT reset |
| MIN-2 | 10 | Low | Deletes unused function; no callers exist |
| MIN-3 | 11 | Low | String-only change in frontend JSX; no logic change |

### Implementation Order

1. **Exploration tests** (Task 1) — confirm all 9 bugs exist on unfixed code
2. **Preservation tests** (Task 2) — capture baseline behavior on unfixed code
3. **CRIT fix** (Task 3) — clear leaked password + remove peer DB URL env fallback
4. **MOD-1 fix** (Task 4) — remove heartbeat secret env fallbacks + clear env values
5. **MOD-2 fix** (Task 5) — update error messages
6. **MOD-3 fix** (Task 6) — add `local_lan_ip`/`local_pg_port` (migration, model, schema, service, router, frontend)
7. **MOD-4 fix** (Task 7) — add `peer_role` to failover-status + fix frontend display
8. **MOD-5 fix** (Task 8) — add `stop-replication` to CONFIRM gate
9. **MIN-1 fix** (Task 9) — reset `_auto_promote_attempted` on peer recovery
10. **MIN-2 fix** (Task 10) — delete dead code `_get_heartbeat_secret()`
11. **MIN-3 fix** (Task 11) — update setup guide text
12. **Preservation verification** (Task 12) — confirm no regressions across all fixes
13. **Issue tracking** (Task 13) — log ISSUE-135 through ISSUE-143
14. **Final checkpoint** (Task 14) — full test suite green

### Files Changed Summary

| File | Bug(s) | Changes |
|------|--------|---------|
| `app/modules/ha/service.py` | CRIT, MOD-1, MOD-3, MIN-2 | Remove `get_peer_db_url()` env fallback; remove `_get_heartbeat_secret_from_config()` env fallback; add `local_lan_ip`/`local_pg_port` to `save_config` + `_config_to_response`; delete `_get_heartbeat_secret()` |
| `app/modules/ha/router.py` | MOD-1, MOD-2, MOD-3 | Remove heartbeat endpoint env fallback; update 2 error messages; update `local_db_info()` + `create_replication_user()` to prioritize DB fields; add `peer_role` to `failover_status()` |
| `app/modules/ha/models.py` | MOD-3 | Add `local_lan_ip` and `local_pg_port` columns |
| `app/modules/ha/schemas.py` | MOD-3, MOD-4 | Add `local_lan_ip`/`local_pg_port` to request+response; add `peer_role` to `FailoverStatusResponse` |
| `app/modules/ha/heartbeat.py` | MIN-1 | Reset `_auto_promote_attempted` on peer recovery |
| `frontend/src/pages/admin/HAReplication.tsx` | MOD-3, MOD-4, MOD-5, MIN-3 | Add `local_lan_ip`/`local_pg_port` form fields; fix peer role display; add `stop-replication` to CONFIRM gate; update setup guide text |
| `alembic/versions/` | MOD-3 | New migration adding `local_lan_ip` and `local_pg_port` columns |
| `.env`, `.env.pi`, `.env.ha-standby`, `.env.standby-prod` | CRIT, MOD-1 | Clear `HA_PEER_DB_URL` and `HA_HEARTBEAT_SECRET` values |
| `docs/ISSUE_TRACKER.md` | All | Add ISSUE-135 through ISSUE-143 |
