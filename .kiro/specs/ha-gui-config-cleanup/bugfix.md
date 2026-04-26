# Bugfix Requirements Document — HA GUI Config Cleanup (Round 3)

## Introduction

This specification covers the 9 remaining unfixed issues from the third HA replication audit (`docs/HA_REPLICATION_REVIEW_3.md`). The audit focused on eliminating all environment-variable dependencies from the HA system (everything should be GUI-configurable) and closing remaining code/UI gaps. Round 1 fixed 15 bugs, Round 2 fixed 6 bugs (CRIT-1/2/3, SIG-1/2, MIN-1). This round addresses: 1 critical leaked credential, 3 moderate env-fallback/message issues, 2 moderate UI gaps (peer role display, stop-replication confirm gate), 1 moderate missing GUI fields feature (local_lan_ip/local_pg_port), and 2 minor cleanup items (dead code, stale guide text, auto-promote flag never cleared).

**Builds on:** `.kiro/specs/ha-replication-bugfixes/` (round 1) and `.kiro/specs/ha-replication-bugfixes-2/` (round 2).

**Review document:** `docs/HA_REPLICATION_REVIEW_3.md`

---

## Bug Analysis

### Current Behavior (Defect)

#### CRIT — Leaked password in `.env.standby-prod` and active env fallback for peer DB URL

1.1 WHEN `.env.standby-prod` is read by the application THEN the system exposes a hardcoded production password (`NoorHarleen1`) in the `HA_PEER_DB_URL` line, and `get_peer_db_url()` at `service.py:142` falls back to `os.environ.get("HA_PEER_DB_URL")` when DB-stored peer config is empty or decryption fails, silently using the leaked credential.

1.2 WHEN `get_peer_db_url()` is called and the DB-stored peer config fields are not populated THEN the system falls back to the `HA_PEER_DB_URL` environment variable instead of returning `None`, bypassing the GUI-only configuration model and using potentially stale or insecure credentials from env files.

#### MOD-1 — HA_HEARTBEAT_SECRET env fallback still active

1.3 WHEN `_get_heartbeat_secret_from_config()` at `service.py:72` is called and the DB-stored `heartbeat_secret` is empty or decryption fails THEN the system falls back to `os.environ.get("HA_HEARTBEAT_SECRET", "")` instead of returning an empty string or raising an error, silently using a weak dev secret from env files.

1.4 WHEN the heartbeat endpoint at `router.py:165` refreshes its cache and the DB-stored secret is empty or decryption fails THEN the system falls back to `os.environ.get("HA_HEARTBEAT_SECRET", "")`, allowing heartbeat HMAC verification to silently use the env-based dev secret.

1.5 WHEN the `.env`, `.env.pi`, `.env.ha-standby`, and `.env.standby-prod` files are loaded THEN the system has `HA_HEARTBEAT_SECRET=dev-ha-secret-for-testing` set as a non-empty value, which the env fallback paths actively use when DB config is absent.

#### MOD-2 — Error messages still mention HA_PEER_DB_URL env var

1.6 WHEN the `POST /ha/replication/init` endpoint at `router.py:449` detects no peer DB URL on a standby node THEN the error message says "Set peer DB settings in HA configuration or set HA_PEER_DB_URL environment variable", directing users to use an env var that should no longer be the configuration path.

1.7 WHEN the `POST /ha/replication/resync` endpoint at `router.py:521` detects no peer DB URL THEN the error message says "Set peer DB settings in HA configuration or set HA_PEER_DB_URL environment variable", same stale guidance.

#### MOD-3 — No GUI fields for `local_lan_ip` / `local_pg_port`

1.8 WHEN the "View Connection Info" modal is displayed after creating a replication user THEN the system auto-detects the host LAN IP using a UDP socket trick that returns the Docker container's internal IP (e.g., `172.17.0.2`) on Linux production instead of the host's LAN IP (e.g., `192.168.1.90`), and falls back to `HA_LOCAL_LAN_IP` env var which has no GUI equivalent.

1.9 WHEN the "View Connection Info" modal displays the PostgreSQL port THEN the system reads `HA_LOCAL_PG_PORT` from the environment (defaulting to `5432`) because the container cannot detect the host's Docker port mapping, and there is no GUI field to configure this — the `HAConfig` model has no `local_lan_ip` or `local_pg_port` columns.

#### MOD-4 — Peer role shown as hardcoded inference instead of actual heartbeat data

1.10 WHEN the Cluster Status peer card is rendered at `HAReplication.tsx:1308` THEN the system displays `config.role === 'primary' ? 'Standby' : 'Primary'` as the peer role — a hardcoded logical opposite — instead of the actual peer role reported by the heartbeat service, which is already stored in `_heartbeat_service.peer_role` and exposed through `get_cluster_status()`.

1.11 WHEN the `/ha/failover-status` endpoint returns its response THEN the `FailoverStatusResponse` schema does not include a `peer_role` field, so the frontend has no way to display the actual peer role from heartbeat data.

#### MOD-5 — `stop-replication` on primary has no CONFIRM gate

1.12 WHEN the `stop-replication` action modal is triggered THEN the `needsConfirmText` check at `HAReplication.tsx:638` does not include `'stop-replication'` in its list, so the user can stop replication (which drops the publication on a primary, halting all data flow to the standby) without typing CONFIRM.

#### MIN-1 — `_auto_promote_attempted` never cleared on peer recovery

1.13 WHEN the peer transitions from unreachable to healthy in `heartbeat.py`'s `_ping_loop` THEN the system resets `_peer_unreachable_since = None` but does NOT reset `_auto_promote_attempted`, so after a failed auto-promote attempt, auto-promote is permanently disabled until the container is restarted — even if the peer recovers and later goes down again.

#### MIN-2 — `_get_heartbeat_secret()` dead code

1.14 WHEN the codebase is inspected THEN the function `_get_heartbeat_secret()` at `service.py:46-59` still exists but is never called anywhere — it was the old env-only path replaced by `_get_heartbeat_secret_from_config()` during the BUG-HA-04 fix, and its presence causes confusion about which function is authoritative.

#### MIN-3 — Setup guide still mentions `.env` files

1.15 WHEN the Setup Guide security notes are displayed at `HAReplication.tsx:167` THEN the text says "protect your `.env` files too", which contradicts the GUI-only configuration goal and misleads users into thinking env files are required for HA configuration.

---

### Expected Behavior (Correct)

#### CRIT Expected: Remove leaked password and env fallback for peer DB URL

2.1 WHEN `.env.standby-prod` is read THEN the `HA_PEER_DB_URL` line SHALL be cleared (set to empty: `HA_PEER_DB_URL=`) so no production password is stored in plaintext in env files. The same SHALL apply to `HA_PEER_DB_URL` in `.env`, `.env.ha-standby`, `.env.pi`, and `.env.pi-standby`.

2.2 WHEN `get_peer_db_url()` is called and the DB-stored peer config fields are not populated THEN the system SHALL return `None` without falling back to the `HA_PEER_DB_URL` environment variable — the `os.environ.get("HA_PEER_DB_URL")` fallback line SHALL be removed.

#### MOD-1 Expected: Remove heartbeat secret env fallbacks and clear env values

2.3 WHEN `_get_heartbeat_secret_from_config()` is called and the DB-stored `heartbeat_secret` is empty or decryption fails THEN the system SHALL return an empty string `""` without falling back to `os.environ.get("HA_HEARTBEAT_SECRET", "")` — the env fallback SHALL be removed.

2.4 WHEN the heartbeat endpoint refreshes its cache and the DB-stored secret is empty or decryption fails THEN the system SHALL use an empty string `""` without falling back to the `HA_HEARTBEAT_SECRET` environment variable — the env fallback SHALL be removed.

2.5 WHEN the `.env`, `.env.pi`, `.env.ha-standby`, and `.env.standby-prod` files are loaded THEN the `HA_HEARTBEAT_SECRET` line SHALL be cleared (set to empty: `HA_HEARTBEAT_SECRET=`) so no dev secret value is present.

#### MOD-2 Expected: Error messages reference GUI configuration only

2.6 WHEN the `POST /ha/replication/init` endpoint detects no peer DB URL on a standby node THEN the error message SHALL say "Peer database connection is not configured. Set peer DB settings in HA configuration." without mentioning the `HA_PEER_DB_URL` environment variable.

2.7 WHEN the `POST /ha/replication/resync` endpoint detects no peer DB URL THEN the error message SHALL say "Peer database connection is not configured. Set peer DB settings in HA configuration." without mentioning the `HA_PEER_DB_URL` environment variable.

#### MOD-3 Expected: GUI fields for `local_lan_ip` and `local_pg_port`

2.8 WHEN the `HAConfig` model is inspected THEN it SHALL have `local_lan_ip` (optional `String(255)`, nullable, default `None`) and `local_pg_port` (optional `Integer`, nullable, default `None`) columns, added via an Alembic migration.

2.9 WHEN the HA configuration form is displayed in the frontend THEN it SHALL include optional input fields for "Local LAN IP" (with helper text: "Used for View Connection Info. Auto-detected if blank.") and "Local PostgreSQL Port" (with helper text: "The host port mapped to PostgreSQL. Defaults to 5432 if blank.") in the Node Configuration section.

2.10 WHEN the `local-db-info` endpoint resolves the LAN IP and PG port THEN it SHALL prioritize: DB-stored `local_lan_ip` field > `HA_LOCAL_LAN_IP` env var > auto-detect for IP, and DB-stored `local_pg_port` field > `HA_LOCAL_PG_PORT` env var > `5432` for port.

2.11 WHEN the `HAConfigRequest` and `HAConfigResponse` schemas are inspected THEN they SHALL include `local_lan_ip` (optional string) and `local_pg_port` (optional int) fields, and `save_config` SHALL persist these fields to the database.

#### MOD-4 Expected: Peer role from heartbeat data displayed in UI

2.12 WHEN the `/ha/failover-status` endpoint returns its response THEN the `FailoverStatusResponse` schema SHALL include a `peer_role` field (string, default `"unknown"`) populated from `_heartbeat_service.peer_role`.

2.13 WHEN the Cluster Status peer card is rendered THEN it SHALL display the `peer_role` value from the `/ha/failover-status` response instead of the hardcoded logical opposite of the local role.

#### MOD-5 Expected: `stop-replication` requires CONFIRM

2.14 WHEN the `stop-replication` action modal is triggered THEN the `needsConfirmText` check SHALL include `'stop-replication'` in its list, requiring the user to type CONFIRM before the action executes.

#### MIN-1 Expected: `_auto_promote_attempted` cleared on peer recovery

2.15 WHEN the peer transitions from unreachable to healthy in `_ping_loop` THEN the system SHALL reset `self._auto_promote_attempted = False` alongside the existing `self._peer_unreachable_since = None` reset, so that auto-promote can trigger again if the peer goes down in the future.

#### MIN-2 Expected: Dead code removed

2.16 WHEN the codebase is inspected THEN the function `_get_heartbeat_secret()` at `service.py:46-59` SHALL no longer exist — it SHALL be deleted as dead code.

#### MIN-3 Expected: Setup guide references GUI-only configuration

2.17 WHEN the Setup Guide security notes are displayed THEN the text SHALL say "The heartbeat secret and peer DB credentials are stored encrypted in the database — no env file entries are required for HA configuration." instead of "protect your `.env` files too".

---

### Unchanged Behavior (Regression Prevention)

3.1 WHEN `_build_peer_db_url()` is called with fully populated DB-stored peer config fields THEN the system SHALL CONTINUE TO build and return a valid PostgreSQL connection string from those fields, exactly as today.

3.2 WHEN `_get_heartbeat_secret_from_config()` is called with a valid encrypted `heartbeat_secret` in the DB THEN the system SHALL CONTINUE TO decrypt and return the secret from the DB, exactly as today.

3.3 WHEN the heartbeat endpoint has a valid DB-stored secret THEN it SHALL CONTINUE TO use the decrypted DB secret for HMAC signing, exactly as today.

3.4 WHEN `save_config` is called with a `heartbeat_secret` value THEN it SHALL CONTINUE TO encrypt and store the secret in the `heartbeat_secret` column, exactly as today.

3.5 WHEN `save_config` is called with peer DB fields THEN it SHALL CONTINUE TO encrypt and store the peer DB password and persist all peer DB fields, exactly as today.

3.6 WHEN the `local-db-info` endpoint is called and no DB-stored or env-var override exists for LAN IP THEN it SHALL CONTINUE TO auto-detect the IP using the existing `_detect_host_lan_ip()` logic (Docker Desktop → UDP socket → fallback), exactly as today.

3.7 WHEN the heartbeat service records a successful heartbeat response THEN it SHALL CONTINUE TO store the peer role in `self.peer_role` from the response data, exactly as today (BUG-HA-15 fix).

3.8 WHEN `get_cluster_status()` builds the peer entry THEN it SHALL CONTINUE TO use `_heartbeat_service.peer_role` for the peer role, exactly as today.

3.9 WHEN the `promote`, `demote`, `resync`, `demote-and-sync`, or standby `init-replication` action modals are triggered THEN they SHALL CONTINUE TO require typing CONFIRM, exactly as today.

3.10 WHEN `_auto_promote_failed_permanently` is set to `True` after two failed auto-promote attempts THEN it SHALL CONTINUE TO permanently disable auto-promote until container restart, exactly as today — only `_auto_promote_attempted` (the single-attempt flag) is reset on peer recovery.

3.11 WHEN `.env.pi-standby` is loaded THEN its `HA_HEARTBEAT_SECRET=` (already blank) and `HA_PEER_DB_URL=` (already blank) lines SHALL CONTINUE TO be empty, exactly as today.

3.12 WHEN the `HAConfigRequest` schema receives `peer_db_host`, `peer_db_port`, `peer_db_name`, `peer_db_user`, `peer_db_password`, and `peer_db_sslmode` fields THEN they SHALL CONTINUE TO be processed and stored exactly as today.
