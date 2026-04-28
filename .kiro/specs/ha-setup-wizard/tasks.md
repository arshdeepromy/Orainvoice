# Implementation Plan: HA Setup Wizard

## Overview

Transform OraInvoice's HA setup from a manual, multi-step process into a guided point-and-click wizard. Implementation spans infrastructure (Dockerfile, entrypoint, Docker Compose), database (migration, model, event log), backend API (wizard endpoints), frontend (5-step wizard UI), verification tests, and a full two-stack integration test. Each phase builds incrementally on the previous, with checkpoints to verify correctness before proceeding.

## Tasks

- [x] 1. Infrastructure — Dockerfile, Entrypoint, Docker Compose
  - [x] 1.1 Install `openssh-server` and `rsync` in Dockerfile
    - Add `openssh-server` and `rsync` to the existing `apt-get install` step in `Dockerfile`
    - Add `mkdir -p /run/sshd` after the install step (required by OpenSSH daemon)
    - Do NOT add an `EXPOSE 2222` — port exposure is handled per-environment in Docker Compose
    - _Requirements: 31.1, 31.2, 31.3, 31.4_

  - [x] 1.2 Fix entrypoint role detection with Python+asyncpg
    - Replace the `psql`-based `ROLE=...` command in `scripts/docker-entrypoint.sh` with a Python+asyncpg inline script
    - The Python script connects to the DATABASE_URL, queries `SELECT role FROM ha_config LIMIT 1`, prints the role or `standalone` on failure
    - Must handle: table doesn't exist, no rows, DB unreachable — all fall back to `standalone`
    - Must complete within 5 seconds (use `timeout=5` on `asyncpg.connect`)
    - _Requirements: 32.1, 32.2, 32.3, 32.4, 32.5_

  - [x] 1.3 Add SSH keygen, LAN IP detection, and sshd startup to entrypoint
    - After the role detection block and before migrations, add three new blocks to `scripts/docker-entrypoint.sh`:
    - **SSH keygen**: If `/ha_keys/id_ed25519` does not exist, generate an Ed25519 keypair with `ssh-keygen -t ed25519 -f /ha_keys/id_ed25519 -N "" -q`. Set permissions: private key 600, public key 644. Create `/ha_keys/authorized_keys` (mode 600) if missing.
    - **LAN IP detection**: If `HA_LOCAL_LAN_IP` env var is set, use it. Otherwise detect via `ip route | awk '/default/ {print $3}'`, falling back to `127.0.0.1`. Write result to `/tmp/host_lan_ip`.
    - **sshd startup**: Write `/etc/ssh/sshd_config.d/ha.conf` with Port 2222, AuthorizedKeysFile `/ha_keys/authorized_keys`, PasswordAuthentication no, PubkeyAuthentication yes, PermitRootLogin no. Start sshd with `/usr/sbin/sshd`. If sshd fails, log warning and continue (non-fatal).
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4_

  - [x] 1.4 Add `ha_keys` volume and port 2222 to all compose files
    - **`docker-compose.yml`**: Add `ha_keys:/ha_keys` volume mount to `app` service. Add `"2222:2222"` port mapping to `app` service. Add `ha_keys:` to top-level volumes.
    - **`docker-compose.pi.yml`**: Add `ha_keys:/ha_keys` volume mount to `app` service. Add `"2222:2222"` port mapping to `app` service.
    - **`docker-compose.standby-prod.yml`**: Add `ha_keys:/ha_keys` volume mount to `app` service. Add `"2222:2222"` port mapping to `app` service. Add `ha_keys:` to top-level volumes.
    - **`docker-compose.ha-standby.yml`**: Add `ha_keys:/ha_keys` volume mount to `app` service (use `standby_ha_keys` as volume name to avoid conflict with primary). Add `standby_ha_keys:` to top-level volumes.
    - Preserve bridge networking mode for all services.
    - _Requirements: 3.5, 3.6, 13.1, 13.2, 13.3_

  - [x] 1.5 Add port 2223 mapping for standby compose
    - In `docker-compose.ha-standby.yml`, add `"2223:2222"` port mapping to the `app` service (host port 2223 → container port 2222 to avoid conflict with primary's 2222:2222)
    - _Requirements: 35.2_

- [x] 2. Checkpoint — Rebuild both stacks, verify startup logs
  - Rebuild primary: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build --force-recreate`
  - Rebuild standby: `docker compose -p invoicing-standby -f docker-compose.ha-standby.yml up -d --build --force-recreate`
  - Check primary logs: `docker logs invoicing-app-1 --tail 30` — verify SSH keypair generated/reused, host LAN IP detected, sshd started, migrations run
  - Check standby logs: `docker logs invoicing-standby-app-1 --tail 30` — verify same startup sequence
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 35.3, 35.4, 35.5_

- [x] 3. Database — Migration, Model, Event Log
  - [x] 3.1 Create Alembic migration for `ha_event_log` table
    - Create a new Alembic migration that creates the `ha_event_log` table with columns: `id` (UUID PK, default uuid4), `timestamp` (DateTime with timezone, server_default now()), `event_type` (String(50), not null), `severity` (String(20), not null), `message` (Text, not null), `details` (JSONB, nullable), `node_name` (String(100), not null)
    - Add indexes: `ix_ha_event_log_timestamp` on `timestamp DESC`, `ix_ha_event_log_event_type` on `event_type`, `ix_ha_event_log_severity` on `severity`
    - _Requirements: 34.1, 34.8_

  - [x] 3.2 Run migration on dev database
    - Execute: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head`
    - Verify the migration succeeds and the `ha_event_log` table exists
    - _Requirements: 34.1 (database-migration-checklist steering)_

  - [x] 3.3 Add `HAEventLog` model to `app/modules/ha/models.py`
    - Add the `HAEventLog` SQLAlchemy model class matching the migration schema
    - Use `Mapped` type annotations consistent with the existing `HAConfig` model style
    - _Requirements: 34.1_

  - [x] 3.4 Add `ha_event_log` to replication publication exclusion list
    - In `ReplicationManager.init_primary()` in `app/modules/ha/replication.py`, add `ha_event_log` to the `NOT IN` clause alongside `ha_config` and `dead_letter_queue`
    - Update the log message to mention all three excluded tables
    - _Requirements: 34.2_

  - [x] 3.5 Create event log helper module `app/modules/ha/event_log.py`
    - Create `log_ha_event(event_type, severity, message, details, node_name)` async function
    - Uses its own short-lived session via `async_session_factory()` (not the request session) so it can be called from background tasks
    - All writes wrapped in try/except — never raises, logs to stderr on failure
    - _Requirements: 34.10_

  - [x] 3.6 Add connection string escaping helper to `ReplicationManager`
    - Add static method `_escape_conn_str(conn_str: str) -> str` that doubles single quotes (`'` → `''`)
    - Apply in `init_standby`, `trigger_resync`, and `resume_subscription` wherever `CONNECTION '{primary_conn_str}'` is used
    - _Requirements: 33.1, 33.2, 33.3_

- [x] 4. Checkpoint — Verify migration applied, event log writes work
  - Verify `ha_event_log` table exists in the dev database
  - Write a quick test event using the helper module (via `docker exec`)
  - Verify the connection string escaping works with a test string containing single quotes
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 34.1, 33.1_

- [x] 5. Backend API — Wizard Pydantic Schemas
  - [x] 5.1 Add wizard Pydantic schemas to `app/modules/ha/schemas.py`
    - Add all wizard request/response schemas: `WizardCheckReachabilityRequest`, `WizardCheckReachabilityResponse`, `WizardAuthenticateRequest`, `WizardAuthenticateResponse`, `WizardHandshakeRequest`, `WizardHandshakeResponse`, `WizardReceiveHandshakeRequest`, `WizardReceiveHandshakeResponse`, `WizardSetupRequest`, `WizardSetupStepResult`, `WizardSetupResponse`, `HAEventResponse`, `HAEventListResponse`
    - Follow existing schema patterns in the file
    - _Requirements: 4.1, 5.1, 6.1, 7.1, 8.1, 10.1, 34.6_

- [x] 6. Backend API — Wizard Endpoints
  - [x] 6.1 Add `POST /ha/wizard/check-reachability` endpoint
    - Accepts `WizardCheckReachabilityRequest` with `address` field
    - Sends HTTP GET to `{address}/api/v1/ha/heartbeat` with 10s timeout using `httpx`
    - Returns `WizardCheckReachabilityResponse` with reachable status, node_name, role, is_orainvoice flag
    - Include version comparison: read local `GIT_SHA` env var, compare with peer's heartbeat response, include version mismatch warning if different
    - Requires Global_Admin auth
    - _Requirements: 4.1, 4.2, 5.1, 5.2, 5.3, 5.4, 37.1, 37.2, 37.3_

  - [x] 6.2 Add `POST /ha/wizard/authenticate` endpoint
    - Accepts `WizardAuthenticateRequest` with address, email, password
    - Proxies login to `{address}/api/v1/auth/login` using `httpx`
    - Verifies the returned token has `global_admin` role by decoding JWT claims
    - Returns `WizardAuthenticateResponse` with authenticated status, is_global_admin flag, token
    - Requires Global_Admin auth on the calling node
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 6.3 Add `POST /ha/wizard/handshake` endpoint (primary-side, called by browser)
    - Accepts `WizardHandshakeRequest` with address, standby_token
    - Reads local SSH public key from `/ha_keys/id_ed25519.pub`
    - Reads `local_lan_ip` and `local_pg_port` from DB > env > auto-detect (reuse existing `local-db-info` logic)
    - Generates 32-byte HMAC secret via `secrets.token_hex(32)`
    - POSTs to `{address}/api/v1/ha/wizard/receive-handshake` with Bearer standby_token: ssh_pub_key, lan_ip, pg_port, hmac_secret
    - Receives standby's SSH public key, LAN IP, PG port in response
    - Appends standby's SSH public key to local `/ha_keys/authorized_keys` (idempotent — no duplicates)
    - Stores HMAC secret in local `ha_config` (encrypted via `envelope_encrypt`)
    - Logs event to `ha_event_log`
    - Returns `WizardHandshakeResponse` with both IPs, both PG ports, hmac_secret_set flag
    - Requires Global_Admin auth
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 14.1, 14.2, 15.2, 16.1, 16.2, 16.4, 30.1_

  - [x] 6.4 Add `POST /ha/wizard/receive-handshake` endpoint (standby-side, called by peer)
    - Accepts `WizardReceiveHandshakeRequest` with ssh_pub_key, lan_ip, pg_port, hmac_secret
    - Appends received SSH public key to `/ha_keys/authorized_keys` (idempotent)
    - Stores HMAC secret in local `ha_config` (encrypted)
    - Reads local SSH public key from `/ha_keys/id_ed25519.pub`
    - Reads local LAN IP and PG port (DB > env > auto-detect)
    - Returns `WizardReceiveHandshakeResponse` with own ssh_pub_key, lan_ip, pg_port
    - Requires Global_Admin auth
    - _Requirements: 10.1, 10.2, 10.3, 10.6, 30.2_

  - [x] 6.5 Add `POST /ha/wizard/setup` endpoint
    - Accepts `WizardSetupRequest` with address, standby_token
    - Executes the full automated setup sequence, building a step log:
      1. Configure standby node — PUT `{address}/api/v1/ha/configure` with role=standby, peer_endpoint, peer DB credentials for primary's database
      2. Configure primary node — Call `HAService.save_config()` locally with role=primary, peer_endpoint, peer DB credentials for standby's database
      3. Create publication — Call `ReplicationManager.init_primary()`
      4. Create subscription on standby — POST `{address}/api/v1/ha/replication/init`
      5. Configure volume sync — PUT volume sync config on both nodes with SSH key paths, IPs, ports from handshake
    - Each step returns status (completed/failed) and error message if failed
    - If a step fails, subsequent steps are skipped
    - Logs events to `ha_event_log` for each step
    - Requires Global_Admin auth
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 10.4, 10.5, 14.1, 14.2, 14.3_

  - [x] 6.6 Add `GET /ha/events` endpoint
    - Query params: `limit` (default 50), `severity` (optional filter), `event_type` (optional filter)
    - Returns `HAEventListResponse` with events from `ha_event_log` ordered by timestamp DESC
    - Requires Global_Admin auth
    - _Requirements: 34.6, 34.7_

  - [x] 6.7 Add version tracking to heartbeat response
    - Add `app_version` field to the heartbeat response payload (read from `GIT_SHA` env var or `BUILD_DATE`)
    - Update `HeartbeatResponse` schema to include `app_version: str | None = None`
    - _Requirements: 37.1, 37.4_

  - [x] 6.8 Wire event logging into heartbeat, service, and volume sync
    - **HeartbeatService** (`heartbeat.py`): Call `log_ha_event()` on heartbeat ping failure, peer health state transitions (healthy→degraded→unreachable), auto-promote attempt/failure, split-brain detection
    - **HAService** (`service.py`): Call `log_ha_event()` on role changes (promote, demote, demote_and_sync), replication init/stop, resync trigger, config changes
    - **VolumeSyncService** (`volume_sync_service.py`): Call `log_ha_event()` on sync failure
    - All calls wrapped in try/except — never crash the calling operation
    - _Requirements: 34.3, 34.4, 34.5, 34.10_

  - [x] 6.9 Add 30-day event pruning to heartbeat loop
    - In the heartbeat `_ping_loop`, add a periodic cleanup (every ~24 hours, tracked by monotonic timestamp) that deletes `ha_event_log` rows where `timestamp < now() - interval '30 days'`
    - Use a short-lived session via `async_session_factory()`
    - Wrapped in try/except — non-critical
    - _Requirements: 34.9_

- [x] 7. Checkpoint — Test wizard endpoints via curl/httpx
  - Test `check-reachability` against the standby stack
  - Test `authenticate` with valid and invalid credentials
  - Test `receive-handshake` directly
  - Verify event log entries are created for each operation
  - Verify version info appears in heartbeat response
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 5.1, 6.1, 10.1, 34.6, 37.1_

- [x] 8. Frontend — Wizard UI
  - [x] 8.1 Add wizard step interfaces and state to `HAReplication.tsx`
    - Define `WizardStep` interface with id, title, status (pending/active/completed/failed)
    - Define `WIZARD_STEPS` array for the 5 steps: Enter Standby Address, Verify Reachability, Authenticate, Trust Handshake, Setup Replication
    - Add wizard state variables: `wizardActive`, `currentStep`, `stepStatuses`, `standbyAddress`, `standbyToken`, `handshakeResult`, `setupLog`
    - Add `HAEvent` interface for the event log table
    - _Requirements: 9.1, 17.4_

  - [x] 8.2 Add Step 1: Enter Standby Address
    - Text input for standby node IP/URL with validation (non-empty, valid address format)
    - "Check Reachability" button that calls `POST /ha/wizard/check-reachability`
    - Display version mismatch warning if versions differ
    - On success, auto-advance to Step 2 (reachability verified)
    - On failure, display human-readable error with retry option
    - Use safe-api-consumption patterns (`res.data?.field ?? fallback`)
    - _Requirements: 4.1, 4.2, 4.3, 5.1, 5.2, 5.3, 5.4, 37.2, 37.3_

  - [x] 8.3 Add Step 2: Verify Reachability (auto-completed by Step 1)
    - Display success indicator with standby node name and role from reachability check
    - This step is completed automatically when check-reachability succeeds in Step 1
    - Show "Edit Address" button to go back to Step 1
    - _Requirements: 5.2_

  - [x] 8.4 Add Step 3: Authenticate
    - Login form with email and password fields for standby node Global_Admin credentials
    - "Authenticate" button that calls `POST /ha/wizard/authenticate`
    - On success, store token in component state (memory only, not localStorage), advance to Step 4
    - On failure, display error (invalid credentials, not Global_Admin) with retry
    - Use safe-api-consumption patterns
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 16.3_

  - [x] 8.5 Add Step 4: Trust Handshake
    - "Start Handshake" button that calls `POST /ha/wizard/handshake`
    - Display progress spinner during handshake
    - On success, display exchanged details: both IPs, both PG ports, HMAC secret set confirmation
    - On failure, display which step failed with retry option
    - Use safe-api-consumption patterns
    - _Requirements: 7.1, 7.8, 7.9, 16.1_

  - [x] 8.6 Add Step 5: Automated Setup with progress log
    - "Start Setup" button that calls `POST /ha/wizard/setup`
    - Display Setup_Log with each step's status: pending, in-progress, completed, or failed
    - Each step shows: checkmark icon (completed), spinner (in-progress), error icon (failed), dimmed (pending)
    - On success, display success message and transition to normal HA monitoring view
    - On failure, display error in setup log, stop further steps, allow retry from failed step
    - Use safe-api-consumption patterns
    - _Requirements: 8.1, 8.6, 8.7, 8.8, 9.1, 9.2, 9.3, 9.4_

  - [x] 8.7 Add recovery options (Resume, Fresh Setup)
    - When replication is broken (subscription not active or peer unreachable), display warning banner with description
    - Display two recovery buttons: "Resume" and "Fresh Setup"
    - "Resume" calls the existing resume subscription endpoint
    - "Fresh Setup" requires typing "CONFIRM", then drops all replication objects and re-runs wizard from Trust Handshake
    - Display progress messages during recovery
    - _Requirements: 11.1, 11.2, 12.1, 12.2, 12.3, 12.4, 12.5_

  - [x] 8.8 Add HA Event Log table section
    - New section below the existing monitoring UI showing recent HA events
    - Fetch events from `GET /ha/events` with default limit 50
    - Display table with columns: Time, Severity (color-coded badge), Event Type, Message
    - Severity badges: green=info, yellow=warning, red=error, purple=critical
    - Filter dropdowns for severity and event_type
    - "Load More" pagination
    - Use safe-api-consumption patterns (`res.data?.events ?? []`, `res.data?.total ?? 0`)
    - _Requirements: 34.6, 34.7_

  - [x] 8.9 Integrate wizard with existing HA page conditional rendering
    - When no HA config exists → show wizard as primary content
    - When HA config exists but broken → show warning banner + recovery options
    - When HA fully configured and healthy → show existing monitoring UI + event log
    - Wizard uses same Tailwind CSS and Headless UI styling as rest of page
    - Step indicator shows current step and total steps
    - _Requirements: 15.1, 17.1, 17.2, 17.3, 17.4_

  - [x] 8.10 Rebuild frontend
    - Execute: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend npx vite build`
    - Verify build succeeds with no TypeScript errors
    - _Requirements: (database-migration-checklist steering — mandatory frontend rebuild)_

- [x] 9. Checkpoint — Verify wizard renders correctly
  - Navigate to `http://localhost/admin/ha-replication` on the primary
  - Verify wizard UI renders when no HA config exists
  - Verify step indicator shows all 5 steps
  - Verify event log table section renders (may be empty)
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 17.1, 17.4_

- [x] 10. Verification Tests — Property Tests and Bug Fix Confirmations
  - [x] 10.1 Write property test: Address validation (Property 1)
    - **Property 1: Address validation accepts valid addresses and rejects invalid ones**
    - Use Hypothesis to generate random strings, valid IPs, valid hostnames, empty strings, whitespace
    - Verify the wizard address validator returns correct boolean for each
    - File: `tests/properties/test_ha_wizard_properties.py`
    - **Validates: Requirements 4.2**

  - [x] 10.2 Write property test: HMAC secret generation (Property 2)
    - **Property 2: HMAC secret generation produces cryptographically strong secrets**
    - Verify generated secrets are at least 64 hex characters (32 bytes)
    - Verify two independent invocations produce distinct secrets
    - File: `tests/properties/test_ha_wizard_properties.py`
    - **Validates: Requirements 7.6, 16.2**

  - [x] 10.3 Write property test: Wizard endpoints require auth (Property 3)
    - **Property 3: All wizard endpoints reject unauthenticated requests**
    - For each wizard endpoint path, call without auth token, verify HTTP 401 or 403
    - File: `tests/properties/test_ha_wizard_properties.py`
    - **Validates: Requirements 10.6, 16.1**

  - [x] 10.4 Write property test: Handshake idempotency for authorized_keys (Property 4)
    - **Property 4: Trust handshake is idempotent for authorized_keys**
    - Generate random SSH public keys, run handshake append logic multiple times, verify no duplicates in authorized_keys
    - File: `tests/properties/test_ha_wizard_properties.py`
    - **Validates: Requirements 15.2**

  - [x] 10.5 Write property test: Role transitions update heartbeat local_role (Property 5)
    - **Property 5: Role transitions update heartbeat service local_role**
    - For each valid role transition, verify HeartbeatService.local_role equals the new role after transition
    - File: `tests/properties/test_ha_wizard_properties.py`
    - **Validates: Requirements 19.1, 19.2, 19.3**

  - [x] 10.6 Write property test: Auto-promote flag reset on recovery (Property 6)
    - **Property 6: Auto-promote flag resets when peer recovers**
    - Generate random sequences of unreachable/reachable transitions, verify `_auto_promote_attempted` resets on recovery while `_auto_promote_failed_permanently` remains unchanged
    - File: `tests/properties/test_ha_wizard_properties.py`
    - **Validates: Requirements 23.1, 23.2, 23.3**

  - [x] 10.7 Write property test: No env fallback for secrets (Property 7)
    - **Property 7: HA secret functions have no environment variable fallback**
    - Set `HA_HEARTBEAT_SECRET` and `HA_PEER_DB_URL` env vars to random values, call `_get_heartbeat_secret_from_config(None)` and `get_peer_db_url()`, verify they return empty string / None regardless
    - File: `tests/properties/test_ha_wizard_properties.py`
    - **Validates: Requirements 26.1, 26.2**

  - [x] 10.8 Write property test: Connection string escaping (Property 8)
    - **Property 8: Connection string escaping produces valid SQL**
    - Generate random strings with single quotes, backslashes, special chars
    - Verify `_escape_conn_str()` doubles all single quotes and the result is valid for SQL interpolation
    - File: `tests/properties/test_ha_wizard_properties.py`
    - **Validates: Requirements 33.1, 33.2, 33.3**

  - [x] 10.9 Write property test: Publication excludes ha_event_log (Property 9)
    - **Property 9: ha_event_log is excluded from replication publication**
    - Verify the exclusion list in `init_primary()` includes `ha_event_log`, `ha_config`, and `dead_letter_queue`
    - File: `tests/properties/test_ha_wizard_properties.py`
    - **Validates: Requirements 34.2**

  - [x] 10.10 Write property test: Event pruning (Property 10)
    - **Property 10: Event pruning removes only events older than 30 days**
    - Generate random event timestamps spanning 0-60 days ago, run pruning, verify only events older than 30 days are removed
    - File: `tests/properties/test_ha_wizard_properties.py`
    - **Validates: Requirements 34.9**

  - [x] 10.11 Write verification tests for already-fixed bugs (Requirements 18-29)
    - Create `tests/unit/test_ha_bugfix_verification.py` with tests confirming each fix remains correct:
    - **Req 18**: Verify `_cleanup_orphaned_slot_on_peer` is called in `trigger_resync` (mock test)
    - **Req 19**: Verify `_heartbeat_service.local_role` updated after promote/demote/demote_and_sync
    - **Req 20**: Verify `drop_replication_slot` endpoint has `Depends(get_db_session)`
    - **Req 21**: Verify new HeartbeatService in `save_config` has Redis lock fields wired
    - **Req 22**: Verify `resume_subscription` fallback uses `copy_data = false`; verify `demote()` drops publication
    - **Req 23**: Verify `_auto_promote_attempted` reset on peer recovery
    - **Req 24**: Parse `docker-compose.ha-standby.yml`, verify `max_wal_senders=10` and `max_replication_slots=10`
    - **Req 25**: Read `.env*` files, verify empty `HA_HEARTBEAT_SECRET` and `HA_PEER_DB_URL` values
    - **Req 26**: Call `_get_heartbeat_secret_from_config(None)` with env set, verify no fallback
    - **Req 27**: Verify `FailoverStatusResponse` schema has `peer_role` field
    - **Req 28**: Verify `stop-replication` is in `needsConfirmText` list in `HAReplication.tsx`
    - **Req 29**: Verify no `.env` references for HA config in setup guide text
    - _Requirements: 18.1-18.4, 19.1-19.4, 20.1-20.5, 21.1-21.3, 22.1-22.4, 23.1-23.3, 24.1-24.2, 25.1-25.6, 26.1-26.4, 27.1-27.3, 28.1-28.3, 29.1-29.3_

  - [x] 10.12 Write E2E test script `scripts/test_ha_wizard_e2e.py`
    - Follow the feature-testing-workflow steering doc pattern
    - Login as Global_Admin on primary
    - Call check-reachability against standby
    - Call authenticate against standby
    - Call handshake
    - Call setup
    - Verify ha_config on primary node
    - Verify ha_event_log has entries
    - Verify event log API returns events
    - Test auth rejection (no token → 401/403)
    - Clean up test data
    - _Requirements: 5.1, 6.1, 7.1, 8.1, 34.6_

- [x] 11. Integration Test — Full Two-Stack Wizard Flow
  - [x] 11.1 Rebuild both Docker stacks from scratch
    - Primary: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build --force-recreate`
    - Standby: `docker compose -p invoicing-standby -f docker-compose.ha-standby.yml up -d --build --force-recreate`
    - Run migration on standby: `docker compose -p invoicing-standby -f docker-compose.ha-standby.yml exec app alembic upgrade head`
    - Verify both stacks are healthy (check logs for SSH keygen, LAN IP, sshd, migrations)
    - _Requirements: 35.1, 35.2, 35.3, 35.4, 35.5_

  - [x] 11.2 Test full wizard flow through the browser
    - Navigate to `http://localhost/admin/ha-replication` on the primary
    - Complete all 5 wizard steps using the standby's address (`http://{host_lan_ip}:8081`)
    - Verify each step completes successfully with correct UI feedback
    - Verify the wizard transitions to the normal HA monitoring view after setup
    - _Requirements: 35.6, 8.7, 9.1, 9.2, 9.3, 9.4_

  - [x] 11.3 Verify replication with actual data
    - Create a test customer on the primary via the API or UI
    - Query the standby's database to verify the customer replicated within 10 seconds
    - Verify heartbeat history shows successful pings on both nodes
    - Verify `ha_event_log` has wizard setup events on both nodes
    - Verify volume sync configuration is set on both nodes
    - _Requirements: 35.7, 35.8, 35.9, 35.10_

  - [x] 11.4 Fix any bugs found, update steering docs
    - For each error encountered during integration testing:
      1. Fix the root cause (not just the symptom)
      2. Re-run the full wizard flow from the beginning to verify no regressions
      3. Add a rule to the appropriate steering doc in `.kiro/steering/`:
         - Docker/container issues → `deployment-environments.md` or new `ha-infrastructure.md`
         - Frontend API mismatches → `frontend-backend-contract-alignment.md`
         - Database/migration issues → `database-migration-checklist.md`
         - Security issues → `security-hardening-checklist.md`
    - _Requirements: 36.1, 36.2, 36.3_

  - [x] 11.5 Re-test until zero errors
    - The integration test is NOT complete until the full wizard flow succeeds end-to-end with zero errors on a clean rebuild of both stacks
    - Final test run must include: creating test data on primary, verifying replication to standby, verifying HA event log records events
    - _Requirements: 36.4, 36.5_

- [ ] 12. Final checkpoint — Ensure all tests pass
  - Verify both Docker stacks are running with HA fully configured
  - Verify replication is active (data written on primary appears on standby)
  - Verify heartbeat is healthy on both nodes
  - Verify event log has complete history of wizard setup
  - Verify recovery options (Resume, Fresh Setup) are visible when replication is broken
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 35.7, 35.8, 35.9, 35.10, 11.1, 12.1_

- [ ] 13. Git push all changes to GitHub
  - [ ] 13.1 Stage and commit all changes
    - Stage all modified and new files with `git add -A`
    - Check for any files containing secrets (`.env`, `.key`, `.pem`) — do NOT commit actual secrets
    - Commit with a descriptive message covering all changes: infrastructure, backend, frontend, tests, steering docs
  - [ ] 13.2 Push to a feature branch
    - Create branch `feature/ha-setup-wizard` if not already on it
    - Push with `-u` flag to set upstream tracking: `git push -u origin feature/ha-setup-wizard`
  - [ ] 13.3 Merge to main and push
    - Switch to main: `git checkout main`
    - Merge the feature branch: `git merge feature/ha-setup-wizard`
    - Push main to GitHub: `git push origin main`
    - Verify the working tree is clean: `git status --short` should show no output

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation after each phase
- Property tests validate universal correctness properties from the design document
- After creating migrations, they MUST be run immediately (database-migration-checklist steering)
- After modifying frontend code, it MUST be rebuilt (database-migration-checklist steering)
- All frontend code must use safe-api-consumption patterns (`?.`, `?? []`, `?? 0`)
- The integration test (Phase 6, tasks 11-12) is the most critical phase — it validates everything works together
- Bug fixes found during integration testing must be documented in steering docs (Requirement 36)