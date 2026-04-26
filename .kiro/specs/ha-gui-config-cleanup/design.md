# HA GUI Config Cleanup (Round 3) — Bugfix Design

## Overview

This design addresses 9 unfixed issues from the third HA replication audit (`docs/HA_REPLICATION_REVIEW_3.md`). The overarching goal is to eliminate all environment-variable dependencies from the HA system so that everything is GUI-configurable, and to close remaining code/UI gaps. The bugs span: a critical leaked credential in `.env.standby-prod`, active env fallbacks for `HA_PEER_DB_URL` and `HA_HEARTBEAT_SECRET`, error messages referencing env vars, missing GUI fields for `local_lan_ip`/`local_pg_port`, a hardcoded peer role display, a missing CONFIRM gate on `stop-replication`, a never-cleared `_auto_promote_attempted` flag, dead code, and stale setup guide text.

The fix strategy is: remove all env-var fallback paths from Python code, clear env-var values from `.env*` files, add DB columns + GUI fields for `local_lan_ip`/`local_pg_port`, expose `peer_role` through the failover-status API, add `stop-replication` to the CONFIRM gate list, reset `_auto_promote_attempted` on peer recovery, delete dead code, and update the setup guide text.

## Glossary

- **Bug_Condition (C)**: The set of conditions under which the HA system silently uses env-var values, displays incorrect information, or behaves incorrectly — covering env fallbacks, stale UI text, hardcoded peer role, missing confirm gates, and unreset flags.
- **Property (P)**: The desired behavior after the fix — all HA configuration sourced exclusively from the GUI/DB, correct peer role display, CONFIRM gate on destructive actions, auto-promote flag properly reset, and no dead code or stale references.
- **Preservation**: Existing behavior that must remain unchanged — DB-stored config retrieval, encrypted secret handling, heartbeat HMAC signing, `_build_peer_db_url()`, auto-detect fallback chain for LAN IP, and all existing CONFIRM gates.
- **`get_peer_db_url()`**: Function in `service.py:139` that returns the peer DB connection string; currently falls back to `HA_PEER_DB_URL` env var.
- **`_get_heartbeat_secret_from_config()`**: Function in `service.py:65` that returns the HMAC secret; currently falls back to `HA_HEARTBEAT_SECRET` env var.
- **`_get_heartbeat_secret()`**: Dead function in `service.py:46-59` that reads only from env var; never called after BUG-HA-04 fix.
- **`_detect_host_lan_ip()`**: Function in `router.py:63` that auto-detects the host LAN IP; priority: env var > Docker Desktop > UDP socket > 127.0.0.1.
- **`_auto_promote_attempted`**: Boolean flag in `HeartbeatService` that tracks whether auto-promote has been attempted; never reset on peer recovery.

## Bug Details

### Bug Condition

The bugs manifest across multiple code paths where the HA system either (a) silently falls back to environment variables instead of requiring GUI/DB configuration, (b) displays incorrect or stale information in the UI, or (c) has missing safety gates or unreset state flags.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type HASystemInteraction
  OUTPUT: boolean

  // CRIT + MOD-1: Env fallback paths are active
  IF input.action == "get_peer_db_url" AND db_peer_config_empty(input)
    RETURN True  // Falls back to HA_PEER_DB_URL env var

  IF input.action == "get_heartbeat_secret" AND db_secret_empty_or_decrypt_fails(input)
    RETURN True  // Falls back to HA_HEARTBEAT_SECRET env var

  IF input.action == "heartbeat_endpoint_cache_refresh" AND db_secret_empty_or_decrypt_fails(input)
    RETURN True  // Falls back to HA_HEARTBEAT_SECRET env var

  // CRIT: Leaked password in env file
  IF input.action == "read_env_file" AND input.file == ".env.standby-prod"
     AND env_contains_nonempty("HA_PEER_DB_URL", input.file)
    RETURN True

  // MOD-2: Error messages mention env var
  IF input.action IN ["replication_init", "replication_resync"]
     AND input.error_message CONTAINS "HA_PEER_DB_URL"
    RETURN True

  // MOD-3: No GUI fields for local_lan_ip / local_pg_port
  IF input.action == "local_db_info" AND NOT db_has_local_lan_ip_column()
    RETURN True

  // MOD-4: Peer role hardcoded
  IF input.action == "render_peer_card" AND peer_role_is_hardcoded_opposite(input)
    RETURN True

  // MOD-5: stop-replication has no CONFIRM gate
  IF input.action == "stop_replication_modal" AND NOT requires_confirm_text(input)
    RETURN True

  // MIN-1: _auto_promote_attempted never cleared
  IF input.action == "peer_recovery" AND auto_promote_attempted_not_reset(input)
    RETURN True

  // MIN-2: Dead code exists
  IF input.action == "inspect_codebase" AND function_exists("_get_heartbeat_secret")
    RETURN True

  // MIN-3: Setup guide mentions .env
  IF input.action == "render_setup_guide" AND guide_text_mentions_env_files(input)
    RETURN True

  RETURN False
END FUNCTION
```

### Examples

- **CRIT — Leaked password**: `.env.standby-prod` contains `HA_PEER_DB_URL=postgresql://replicator:NoorHarleen1@192.168.1.90:5432/workshoppro`. When `get_peer_db_url()` is called and DB peer config is empty, this leaked credential is silently used.
- **MOD-1 — Heartbeat secret fallback**: `.env`, `.env.pi`, `.env.ha-standby`, `.env.standby-prod` all contain `HA_HEARTBEAT_SECRET=dev-ha-secret-for-testing`. When DB secret is empty, the weak dev secret is silently used for HMAC signing.
- **MOD-2 — Stale error message**: `POST /ha/replication/init` on a standby with no peer DB URL returns "Set peer DB settings in HA configuration or set HA_PEER_DB_URL environment variable" — directing users to use an env var.
- **MOD-3 — Wrong IP in modal**: On Linux Docker, `_detect_host_lan_ip()` returns `172.17.0.2` (container IP) instead of `192.168.1.90` (host LAN IP). No GUI field exists to override this.
- **MOD-4 — Hardcoded peer role**: `HAReplication.tsx:1308` displays `config.role === 'primary' ? 'Standby' : 'Primary'` — after a promotion, both nodes may show incorrect peer roles.
- **MOD-5 — No CONFIRM gate**: Clicking "Stop Replication" on a primary drops the publication (halting all data flow) without requiring the user to type CONFIRM.
- **MIN-1 — Stuck auto-promote**: After a failed auto-promote attempt, `_auto_promote_attempted = True` permanently. Even if the peer recovers and goes down again, auto-promote never triggers.
- **MIN-2 — Dead code**: `_get_heartbeat_secret()` at `service.py:46-59` is never called but still exists, causing confusion about which function is authoritative.
- **MIN-3 — Stale guide text**: Setup guide says "protect your `.env` files too" — contradicts the GUI-only configuration model.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- `_build_peer_db_url()` must continue to build valid PostgreSQL connection strings from DB-stored peer config fields (Req 3.1)
- `_get_heartbeat_secret_from_config()` must continue to decrypt and return the DB-stored secret when it exists and is valid (Req 3.2)
- The heartbeat endpoint must continue to use the decrypted DB secret for HMAC signing when available (Req 3.3)
- `save_config` must continue to encrypt and store `heartbeat_secret` and `peer_db_password` (Req 3.4, 3.5)
- `_detect_host_lan_ip()` must continue its auto-detect chain (Docker Desktop → UDP socket → fallback) when no DB or env override exists (Req 3.6)
- `_heartbeat_service.peer_role` must continue to be populated from heartbeat responses (Req 3.7)
- `get_cluster_status()` must continue to use `_heartbeat_service.peer_role` (Req 3.8)
- All existing CONFIRM gates (promote, demote, resync, demote-and-sync, standby init-replication) must continue to work (Req 3.9)
- `_auto_promote_failed_permanently` must continue to permanently disable auto-promote after two failures (Req 3.10)
- `.env.pi-standby` already has blank `HA_HEARTBEAT_SECRET=` and `HA_PEER_DB_URL=` — must remain unchanged (Req 3.11)
- All existing `HAConfigRequest` peer DB fields must continue to be processed and stored (Req 3.12)

**Scope:**
All inputs that do NOT involve the 9 bug conditions should be completely unaffected by this fix. This includes:
- Normal DB-stored config retrieval and usage
- Mouse clicks and other UI interactions unrelated to the 9 issues
- Heartbeat ping/response cycle when DB secret is valid
- Replication init/resync when peer DB URL is configured in DB

## Hypothesized Root Cause

Based on the bug analysis and code inspection, the root causes are:

1. **Incomplete env-var removal (CRIT, MOD-1)**: The BUG-HA-03 and BUG-HA-04 fixes added DB-preferred paths but left `os.environ.get()` fallbacks as safety nets. These fallbacks are now actively harmful because the `.env*` files still contain real values (including a leaked production password). The fallback lines at `service.py:72`, `service.py:142`, and `router.py:165` need to be removed entirely.

2. **Stale error messages (MOD-2)**: When the env fallback was the primary configuration path, error messages correctly directed users to set the env var. After the GUI migration, the messages at `router.py:449` and `router.py:521` were not updated.

3. **Missing DB columns and GUI fields (MOD-3)**: `local_lan_ip` and `local_pg_port` were never part of the original HA design — they were added as env-var overrides for Docker-specific issues. The `HAConfig` model, schemas, service, and frontend were never extended to support them.

4. **Frontend not consuming available data (MOD-4)**: The BUG-HA-15 fix stored `peer_role` in `_heartbeat_service.peer_role` and exposed it through `get_cluster_status()`, but the `/ha/failover-status` endpoint (which the frontend polls) was never updated to include `peer_role`. The frontend falls back to a hardcoded logical opposite.

5. **Incomplete action list (MOD-5)**: The `needsConfirmText` check at `HAReplication.tsx:638` was written before `stop-replication` was considered a destructive action. The action was omitted from the list.

6. **Missing state reset (MIN-1)**: In `heartbeat.py`'s `_ping_loop`, the peer recovery branch resets `_peer_unreachable_since = None` but does not reset `_auto_promote_attempted`. This was an oversight — the single-attempt flag should reset when the peer recovers so auto-promote can trigger again on a future outage.

7. **Dead code not cleaned up (MIN-2)**: `_get_heartbeat_secret()` was the original env-only function. After BUG-HA-04 introduced `_get_heartbeat_secret_from_config()`, the old function was left in place.

8. **Stale documentation (MIN-3)**: The setup guide text at `HAReplication.tsx:167` was written before the GUI-only migration and was never updated.

## Correctness Properties

Property 1: Bug Condition — Env Fallbacks Removed

_For any_ call to `get_peer_db_url()` where the DB-stored peer config fields are not populated, the fixed function SHALL return `None` without reading `HA_PEER_DB_URL` from the environment. Similarly, _for any_ call to `_get_heartbeat_secret_from_config()` where the DB-stored secret is empty or decryption fails, the fixed function SHALL return `""` without reading `HA_HEARTBEAT_SECRET` from the environment. The heartbeat endpoint cache refresh SHALL also not fall back to the env var.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**

Property 2: Preservation — DB-Stored Config Retrieval Unchanged

_For any_ call to `get_peer_db_url()` where the DB-stored peer config fields ARE populated, the fixed function SHALL produce the same result as the original function (via `_build_peer_db_url()`). _For any_ call to `_get_heartbeat_secret_from_config()` where the DB-stored secret IS valid, the fixed function SHALL produce the same decrypted secret as the original function. All existing CONFIRM gates, auto-detect fallback chains, and encrypted storage paths SHALL remain unchanged.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12**

Property 3: Bug Condition — UI Correctness

_For any_ rendering of the peer card in Cluster Status, the fixed frontend SHALL display the `peer_role` value from the `/ha/failover-status` response instead of a hardcoded logical opposite. _For any_ `stop-replication` action modal, the fixed frontend SHALL require typing CONFIRM. _For any_ rendering of the setup guide, the fixed text SHALL not mention `.env` files for HA configuration.

**Validates: Requirements 2.12, 2.13, 2.14, 2.17**

Property 4: Bug Condition — Local LAN IP/Port GUI Fields

_For any_ HA configuration form display, the fixed frontend SHALL include optional input fields for Local LAN IP and Local PostgreSQL Port. _For any_ call to the `local-db-info` endpoint, the fixed code SHALL prioritize DB-stored values over env vars over auto-detect.

**Validates: Requirements 2.8, 2.9, 2.10, 2.11**

Property 5: Bug Condition — Auto-Promote Flag Reset

_For any_ peer recovery transition (unreachable → healthy) in `_ping_loop`, the fixed code SHALL reset `_auto_promote_attempted = False` alongside the existing `_peer_unreachable_since = None` reset.

**Validates: Requirements 2.15**

Property 6: Bug Condition — Dead Code and Error Messages

_For any_ inspection of the codebase, the function `_get_heartbeat_secret()` SHALL no longer exist. _For any_ error response from `replication/init` or `replication/resync` about missing peer DB URL, the message SHALL reference GUI configuration only, not the `HA_PEER_DB_URL` environment variable.

**Validates: Requirements 2.6, 2.7, 2.16**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `app/modules/ha/service.py`

**Function**: `_get_heartbeat_secret()` (lines 46-59)

**Specific Changes**:
1. **Delete dead code**: Remove the entire `_get_heartbeat_secret()` function (lines 46-59). It is never called.

**Function**: `_get_heartbeat_secret_from_config()` (lines 65-72)

**Specific Changes**:
2. **Remove env fallback**: Change the fallback from `return os.environ.get("HA_HEARTBEAT_SECRET", "")` to `return ""`. When DB decrypt fails, return empty string — do not silently use env var.

**Function**: `get_peer_db_url()` (lines 139-145)

**Specific Changes**:
3. **Remove env fallback**: Change `return os.environ.get("HA_PEER_DB_URL") or None` to `return None`. When DB peer config is empty, return `None` — do not silently use env var.

**Function**: `save_config()`

**Specific Changes**:
4. **Persist new fields**: Add handling for `local_lan_ip` and `local_pg_port` in both the insert and update branches, storing them on the `HAConfig` ORM object.

---

**File**: `app/modules/ha/router.py`

**Function**: `heartbeat()` (line ~165)

**Specific Changes**:
5. **Remove env fallback in heartbeat cache**: Change the fallback from `secret = os.environ.get("HA_HEARTBEAT_SECRET", "")` to `secret = ""` in the cache miss branch.

**Function**: `replication_init()` (line ~449)

**Specific Changes**:
6. **Update error message**: Change `"Set peer DB settings in HA configuration or set HA_PEER_DB_URL environment variable."` to `"Peer database connection is not configured. Set peer DB settings in HA configuration."`.

**Function**: `replication_resync()` (line ~521)

**Specific Changes**:
7. **Update error message**: Same change as above.

**Function**: `local_db_info()`

**Specific Changes**:
8. **Add DB-stored field priority**: Load `HAConfig` from DB. If `cfg.local_lan_ip` is set, use it instead of calling `_detect_host_lan_ip()`. If `cfg.local_pg_port` is set, use it instead of reading `HA_LOCAL_PG_PORT` env var. Fallback chain: DB field > env var > auto-detect/default.

**Function**: `create_replication_user()`

**Specific Changes**:
9. **Add DB-stored field priority**: Same as `local_db_info()` — use DB-stored `local_lan_ip` and `local_pg_port` when building the connection info response.

**Function**: `failover_status()`

**Specific Changes**:
10. **Add peer_role to response**: Read `hb_service.peer_role` and include it in the `FailoverStatusResponse`.

---

**File**: `app/modules/ha/models.py`

**Specific Changes**:
11. **Add columns**: Add `local_lan_ip: Mapped[str | None] = mapped_column(String(255), nullable=True)` and `local_pg_port: Mapped[int | None] = mapped_column(Integer, nullable=True)` to the `HAConfig` model.

---

**File**: `app/modules/ha/schemas.py`

**Specific Changes**:
12. **Add fields to HAConfigRequest**: Add `local_lan_ip: str | None = Field(default=None)` and `local_pg_port: int | None = Field(default=None)`.
13. **Add fields to HAConfigResponse**: Add `local_lan_ip: str | None = None` and `local_pg_port: int | None = None`.
14. **Add peer_role to FailoverStatusResponse**: Add `peer_role: str = Field(default="unknown")`.

---

**File**: `app/modules/ha/heartbeat.py`

**Function**: `_ping_loop()` — peer recovery branch

**Specific Changes**:
15. **Reset auto-promote flag**: In the branch where `previous_health == "unreachable" and self.peer_health != "unreachable"`, add `self._auto_promote_attempted = False` after the existing `self._peer_unreachable_since = None`.

---

**File**: `frontend/src/pages/admin/HAReplication.tsx`

**Specific Changes**:
16. **Add peer_role to FailoverStatus interface**: Add `peer_role?: string` to the `FailoverStatus` TypeScript interface.
17. **Fix peer role display**: Change `config.role === 'primary' ? 'Standby' : 'Primary'` at line 1308-1309 to use `failoverStatus?.peer_role ?? (config.role === 'primary' ? 'standby' : 'primary')`.
18. **Add stop-replication to CONFIRM gate**: Change `needsConfirmText` at line 638 to include `'stop-replication'` in the list: `['promote', 'demote', 'resync', 'stop-replication', 'demote-and-sync']`.
19. **Update setup guide text**: Change line 167 from `"protect your .env files too"` to `"The heartbeat secret and peer DB credentials are stored encrypted in the database — no .env file entries are required for HA configuration"`.
20. **Add local_lan_ip and local_pg_port form fields**: Add optional input fields in the Node Configuration section with helper text. Add form state variables and include them in the save payload.
21. **Send confirmation_text for stop-replication**: Update the `handleAction` switch case for `stop-replication` to send `{ confirmation_text: 'CONFIRM' }` in the POST body (the backend `replication_stop` endpoint doesn't currently require it, but the frontend CONFIRM gate prevents accidental clicks).

---

**File**: `alembic/versions/` — New migration

**Specific Changes**:
22. **Add columns**: Create an Alembic migration that adds `local_lan_ip VARCHAR(255)` and `local_pg_port INTEGER` columns to the `ha_config` table, both nullable with no default.

---

**Files**: `.env`, `.env.pi`, `.env.ha-standby`, `.env.standby-prod`, `.env.pi-standby`

**Specific Changes**:
23. **Clear env values**: Set `HA_HEARTBEAT_SECRET=` (empty) in `.env`, `.env.pi`, `.env.ha-standby`, `.env.standby-prod`. Set `HA_PEER_DB_URL=` (empty) in `.env`, `.env.ha-standby`, `.env.standby-prod`. (`.env.pi` and `.env.pi-standby` already have `HA_PEER_DB_URL=` blank.)

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bugs on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bugs BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that exercise the env-fallback paths, error messages, peer role display logic, CONFIRM gate logic, and auto-promote flag behavior. Run these tests on the UNFIXED code to observe failures and understand the root cause.

**Test Cases**:
1. **Env Fallback — Peer DB URL**: Call `get_peer_db_url()` with empty DB peer config and `HA_PEER_DB_URL` set in env → observe it returns the env value (will fail on unfixed code by returning env value instead of None)
2. **Env Fallback — Heartbeat Secret**: Call `_get_heartbeat_secret_from_config(None)` with `HA_HEARTBEAT_SECRET` set in env → observe it returns the env value (will fail on unfixed code by returning env value instead of "")
3. **Error Message — Init**: Call `POST /ha/replication/init` as standby with no peer DB URL → observe error message mentions env var (will fail on unfixed code)
4. **Peer Role — Hardcoded**: Render peer card when `config.role === 'primary'` → observe it shows "Standby" regardless of actual peer role (will fail on unfixed code)
5. **CONFIRM Gate — Stop Replication**: Open stop-replication modal → observe no CONFIRM text input is shown (will fail on unfixed code)
6. **Auto-Promote Flag**: Simulate peer recovery after failed auto-promote → observe `_auto_promote_attempted` remains True (will fail on unfixed code)

**Expected Counterexamples**:
- `get_peer_db_url()` returns `"postgresql://replicator:NoorHarleen1@..."` from env instead of `None`
- `_get_heartbeat_secret_from_config(None)` returns `"dev-ha-secret-for-testing"` from env instead of `""`
- Error messages contain the string `"HA_PEER_DB_URL"`
- Peer card always shows logical opposite role regardless of actual heartbeat data

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := fixedFunction(input)
  ASSERT expectedBehavior(result)
END FOR
```

Specifically:
- `get_peer_db_url()` with empty DB config → returns `None`
- `_get_heartbeat_secret_from_config(None)` → returns `""`
- Heartbeat cache miss with empty DB secret → `secret = ""`
- Error messages do not contain `"HA_PEER_DB_URL"`
- `local_db_info` with DB-stored `local_lan_ip` → returns DB value
- `FailoverStatusResponse` includes `peer_role` field
- `needsConfirmText` includes `'stop-replication'`
- Peer recovery resets `_auto_promote_attempted = False`
- `_get_heartbeat_secret()` function does not exist
- Setup guide text does not mention `.env` files

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

**Test Plan**: Observe behavior on UNFIXED code first for DB-stored config retrieval, then write property-based tests capturing that behavior.

**Test Cases**:
1. **Peer DB URL Preservation**: Verify `get_peer_db_url()` with fully populated DB peer config continues to return the same URL built by `_build_peer_db_url()`
2. **Heartbeat Secret Preservation**: Verify `_get_heartbeat_secret_from_config()` with valid encrypted DB secret continues to return the decrypted value
3. **Save Config Preservation**: Verify `save_config()` continues to encrypt and store `heartbeat_secret` and `peer_db_password` correctly
4. **CONFIRM Gate Preservation**: Verify all existing CONFIRM gates (promote, demote, resync, demote-and-sync, standby init-replication) continue to require CONFIRM
5. **Auto-Detect Preservation**: Verify `_detect_host_lan_ip()` continues its fallback chain when no DB override exists
6. **Auto-Promote Permanent Failure Preservation**: Verify `_auto_promote_failed_permanently` is NOT reset on peer recovery (only `_auto_promote_attempted` is reset)

### Unit Tests

- Test `get_peer_db_url()` returns `None` when DB config is empty (no env fallback)
- Test `get_peer_db_url()` returns valid URL when DB config is populated
- Test `_get_heartbeat_secret_from_config(None)` returns `""` (no env fallback)
- Test `_get_heartbeat_secret_from_config(cfg)` returns decrypted secret when DB has valid encrypted secret
- Test `local_db_info` endpoint returns DB-stored `local_lan_ip` when set, falls back to auto-detect when not
- Test `local_db_info` endpoint returns DB-stored `local_pg_port` when set, falls back to env/5432 when not
- Test `FailoverStatusResponse` includes `peer_role` field from heartbeat service
- Test `save_config` persists `local_lan_ip` and `local_pg_port` to DB
- Test `_auto_promote_attempted` is reset to `False` on peer recovery
- Test `_auto_promote_failed_permanently` is NOT reset on peer recovery
- Test error messages at `replication/init` and `replication/resync` do not mention `HA_PEER_DB_URL`

### Property-Based Tests

- Generate random `HAConfig` states (with/without peer DB fields, with/without heartbeat secret) and verify `get_peer_db_url()` never reads from env vars
- Generate random `HAConfig` states and verify `_get_heartbeat_secret_from_config()` never reads from env vars
- Generate random peer health transition sequences and verify `_auto_promote_attempted` is correctly reset on recovery but `_auto_promote_failed_permanently` is never reset
- Generate random `local_lan_ip`/`local_pg_port` DB values and verify `local_db_info` prioritizes DB > env > auto-detect

### Integration Tests

- Full flow: save config with `local_lan_ip` and `local_pg_port` → call `local-db-info` → verify returned values match DB
- Full flow: save config with peer DB fields → call `get_peer_db_url()` → verify URL is built from DB fields, not env
- Full flow: poll `/ha/failover-status` → verify `peer_role` field is present and reflects heartbeat data
- Full flow: open stop-replication modal → verify CONFIRM text input is required
- Full flow: verify `.env*` files have empty `HA_HEARTBEAT_SECRET` and `HA_PEER_DB_URL` values
