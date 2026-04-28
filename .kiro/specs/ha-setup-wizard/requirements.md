# Requirements Document

## Introduction

The HA Setup Wizard eliminates all manual configuration for setting up High Availability replication between two OraInvoice nodes. Currently, HA setup requires manual SSH configuration, SQL commands, editing config files, and understanding PostgreSQL replication internals. This feature replaces that with a guided, point-and-click wizard on the HA Replication page that handles trust establishment, SSH key exchange, replication configuration, and volume sync setup — all from a single flow.

Requirements 1–17 cover the wizard flow itself. Requirements 18–30 address bugs and gaps identified during the HA replication audit (documented in `docs/HA_REPLICATION_REVIEW_2.md` and `docs/HA_REPLICATION_REVIEW_3.md`). Requirements 31–33 address infrastructure gaps found during the final line-by-line code audit.

### Audit Verification Status (Final Code Review — 2026-04-29)

A line-by-line code audit confirmed that **most bugs from previous reviews have already been fixed** in the current codebase. The following requirements (18–29) are included as **verification criteria** — the design and tasks phases should confirm they remain correct and add tests where missing, but no new code changes are expected for these items:

| Requirement | Status | Evidence |
|---|---|---|
| 18: `trigger_resync` orphaned slot | ✅ Already fixed | `replication.py:479` — `_cleanup_orphaned_slot_on_peer` called between drop and create |
| 19: `promote()`/`demote()` local_role | ✅ Already fixed | `service.py:363,443,537` — all three methods update `_heartbeat_service.local_role` |
| 20: `drop_replication_slot` db param | ✅ Already fixed | `router.py:1053` — `db: AsyncSession = Depends(get_db_session)` present |
| 21: `save_config` Redis lock wiring | ✅ Already fixed | `service.py:268-273` — Redis lock fields wired after creating new HeartbeatService |
| 22: `demote()` copy_data + publication | ✅ Already fixed | `replication.py:451` uses `copy_data = false`; `service.py:425` drops publication |
| 23: `_auto_promote_attempted` reset | ✅ Already fixed | `heartbeat.py:137` — reset to False when peer recovers |
| 24: Dev standby compose settings | ✅ Already fixed | `docker-compose.ha-standby.yml:54-56` — explicit `max_wal_senders=10`, `max_replication_slots=10` |
| 25: Leaked credentials in env files | ✅ Already fixed | All `.env*` files have empty `HA_HEARTBEAT_SECRET` and `HA_PEER_DB_URL` values |
| 26: Env var fallbacks removed | ✅ Already fixed | `service.py` — no `os.environ.get("HA_")` calls; dead code removed |
| 27: Peer role from heartbeat | ✅ Already fixed | `schemas.py:229` — `peer_role` field; `HAReplication.tsx:1470` — reads `failoverStatus?.peer_role` |
| 28: stop-replication confirm gate | ✅ Already fixed | `HAReplication.tsx:492,784` — `stop-replication` in `needsConfirmText` list |
| 29: Setup guide .env references | ✅ Already fixed | No `.env` references found in `HAReplication.tsx` |
| 30: DB-stored local_lan_ip/pg_port | ⚠️ Partially done | DB fields and GUI exist; wizard trust handshake needs to use them |

**Requirements 31–33 are NEW issues** found during the final audit that require actual code changes.

## Glossary

- **Wizard**: The guided multi-step UI flow on the HA Replication page that walks the admin through pairing and configuring two OraInvoice nodes for HA replication
- **Primary_Node**: The OraInvoice node that accepts all read/write traffic and publishes data via PostgreSQL logical replication
- **Standby_Node**: The OraInvoice node that receives replicated data from the Primary_Node and serves as a disaster recovery target
- **Trust_Handshake**: The authenticated API-based exchange between two nodes that establishes mutual trust by exchanging SSH public keys, LAN IPs, PG ports, and a shared HMAC secret
- **Pairing**: The process of authenticating against the remote node and completing the Trust_Handshake, after which both nodes recognize each other as HA peers
- **SSH_Keypair**: An RSA or Ed25519 key pair auto-generated at container startup, stored in the `ha_keys` Docker volume, used for rsync-based volume replication between nodes
- **SSHD**: The OpenSSH server daemon running inside the app container on port 2222, enabling rsync connections from the peer node without depending on host SSH
- **Host_LAN_IP**: The IP address of the Docker host machine on the local network, auto-detected at container startup via the default gateway route
- **HMAC_Secret**: A shared secret generated during the Trust_Handshake, stored on both nodes, used to sign and verify heartbeat messages
- **Replication_Publication**: A PostgreSQL logical replication publication created on the Primary_Node that defines which tables are replicated
- **Replication_Subscription**: A PostgreSQL logical replication subscription created on the Standby_Node that connects to the Primary_Node's publication and streams changes
- **Volume_Sync**: The rsync-based file replication of `/app/uploads/` and `/app/compliance_files/` from the Primary_Node to the Standby_Node over SSH
- **Setup_Log**: The human-readable, step-by-step progress log displayed in the Wizard UI during automated configuration
- **Global_Admin**: The highest-privilege user role in OraInvoice, required to access and operate the HA Setup Wizard
- **Entrypoint_Script**: The `docker-entrypoint.sh` shell script that runs before the application starts, responsible for auto-generating SSH keys, detecting the Host_LAN_IP, and starting SSHD
- **ReplicationManager**: The Python class in `app/modules/ha/replication.py` that manages PostgreSQL logical replication lifecycle (publication, subscription, resync, slot management)
- **HAService**: The Python class in `app/modules/ha/service.py` that provides HA configuration CRUD, role transitions (promote/demote), and cluster status aggregation
- **HeartbeatService**: The background asyncio service in `app/modules/ha/heartbeat.py` that pings the peer node's heartbeat endpoint at a configurable interval and tracks health history
- **Replication_Slot**: A PostgreSQL server-side object that tracks the position of a logical replication subscriber in the WAL stream; orphaned slots retain WAL indefinitely

## Requirements

### Requirement 1: SSH Keypair Auto-Generation at Container Startup

**User Story:** As a system administrator, I want SSH keys to be auto-generated when the container starts, so that no manual SSH configuration is needed before HA setup.

#### Acceptance Criteria

1. WHEN the Entrypoint_Script runs and no SSH_Keypair exists in the `ha_keys` volume, THE Entrypoint_Script SHALL generate an Ed25519 SSH_Keypair and store it in the `ha_keys` volume at `/ha_keys/id_ed25519` and `/ha_keys/id_ed25519.pub`
2. WHEN the Entrypoint_Script runs and an SSH_Keypair already exists in the `ha_keys` volume, THE Entrypoint_Script SHALL skip key generation and reuse the existing SSH_Keypair
3. THE Entrypoint_Script SHALL set file permissions on the private key to `600` and the public key to `644`
4. THE Entrypoint_Script SHALL create an empty `authorized_keys` file at `/ha_keys/authorized_keys` with permissions `600` if the file does not already exist

### Requirement 2: Host LAN IP Auto-Detection at Container Startup

**User Story:** As a system administrator, I want the host LAN IP to be auto-detected at container startup, so that nodes can exchange correct network addresses during the Trust_Handshake without manual IP entry.

#### Acceptance Criteria

1. WHEN the Entrypoint_Script runs inside a bridge-networked container, THE Entrypoint_Script SHALL detect the Host_LAN_IP by querying the default gateway route
2. WHEN the environment variable `HA_LOCAL_LAN_IP` is set, THE Entrypoint_Script SHALL use the value of `HA_LOCAL_LAN_IP` as the Host_LAN_IP instead of auto-detecting
3. THE Entrypoint_Script SHALL store the detected Host_LAN_IP in a file at `/tmp/host_lan_ip` for the application to read at runtime
4. WHEN the Host_LAN_IP cannot be detected and `HA_LOCAL_LAN_IP` is not set, THE Entrypoint_Script SHALL fall back to `127.0.0.1` and log a warning message

### Requirement 3: SSHD Server Running Inside the App Container

**User Story:** As a system administrator, I want an SSH server running inside the app container, so that rsync-based volume replication can operate without depending on the host machine's SSH.

#### Acceptance Criteria

1. THE Entrypoint_Script SHALL start SSHD on port 2222 inside the app container before the application process starts
2. THE SSHD SHALL accept only key-based authentication using keys from `/ha_keys/authorized_keys`
3. THE SSHD SHALL reject password-based authentication
4. WHEN SSHD fails to start, THE Entrypoint_Script SHALL log an error message and continue starting the application without SSHD
5. THE Docker Compose configuration SHALL expose port 2222 on the host for all HA-capable deployment environments (pi.yml, standby-prod, ha-standby)
6. THE Docker Compose configuration SHALL mount the `ha_keys` volume at `/ha_keys` in the app container for all HA-capable deployment environments

### Requirement 4: Wizard Step 1 — Enter Standby Address

**User Story:** As a Global_Admin, I want to enter the standby node's address in the Wizard, so that the system knows which remote node to pair with.

#### Acceptance Criteria

1. WHEN the Global_Admin opens the HA Replication page and no HA Pairing exists, THE Wizard SHALL display a text input for the Standby_Node's IP address or URL
2. THE Wizard SHALL validate that the entered address is a non-empty string containing a valid IP address or hostname
3. WHEN the Global_Admin submits the address, THE Wizard SHALL proceed to the reachability verification step

### Requirement 5: Wizard Step 2 — Verify Standby Reachability

**User Story:** As a Global_Admin, I want the system to verify that the standby node is reachable and running OraInvoice, so that I know the address is correct before proceeding.

#### Acceptance Criteria

1. WHEN the Global_Admin submits the standby address, THE Primary_Node SHALL send an HTTP request to the Standby_Node's health or heartbeat endpoint to verify reachability
2. WHEN the Standby_Node responds with a valid OraInvoice heartbeat response, THE Wizard SHALL display a success indicator and proceed to the authentication step
3. IF the Standby_Node is unreachable or does not respond within 10 seconds, THEN THE Wizard SHALL display a human-readable error message indicating the node is unreachable and allow the admin to retry or edit the address
4. IF the Standby_Node responds but is not running OraInvoice, THEN THE Wizard SHALL display a human-readable error message indicating the remote host is not an OraInvoice node

### Requirement 6: Wizard Step 3 — Authenticate Against Standby

**User Story:** As a Global_Admin, I want to authenticate against the standby node using my Global_Admin credentials, so that the system can prove I own both nodes before establishing trust.

#### Acceptance Criteria

1. WHEN the Standby_Node is verified as reachable, THE Wizard SHALL display a login form requesting Global_Admin credentials (email and password) for the Standby_Node
2. WHEN the Global_Admin submits credentials, THE Primary_Node SHALL authenticate against the Standby_Node's login API endpoint using the provided credentials
3. WHEN authentication succeeds and the authenticated user has the Global_Admin role on the Standby_Node, THE Wizard SHALL store the resulting authentication token temporarily in memory and proceed to the Trust_Handshake step
4. IF authentication fails, THEN THE Wizard SHALL display a human-readable error message indicating invalid credentials and allow the admin to retry
5. IF the authenticated user does not have the Global_Admin role on the Standby_Node, THEN THE Wizard SHALL display a human-readable error message indicating that Global_Admin privileges are required on both nodes

### Requirement 7: Wizard Step 4 — Trust Handshake

**User Story:** As a Global_Admin, I want the system to automatically exchange SSH keys, network details, and a shared HMAC secret between both nodes, so that no manual key or config file management is needed.

#### Acceptance Criteria

1. WHEN authentication against the Standby_Node succeeds, THE Primary_Node SHALL read its local SSH public key from the `ha_keys` volume
2. THE Primary_Node SHALL send its SSH public key, Host_LAN_IP, and local PostgreSQL host port to the Standby_Node via an authenticated API endpoint
3. THE Standby_Node SHALL store the received SSH public key in its `/ha_keys/authorized_keys` file
4. THE Standby_Node SHALL respond with its own SSH public key, Host_LAN_IP, and local PostgreSQL host port
5. THE Primary_Node SHALL store the received SSH public key from the Standby_Node in its `/ha_keys/authorized_keys` file
6. THE Primary_Node SHALL generate a cryptographically random HMAC_Secret (minimum 32 bytes) and send it to the Standby_Node via the authenticated API endpoint
7. BOTH nodes SHALL store the HMAC_Secret in their respective `ha_config` database records
8. WHEN the Trust_Handshake completes successfully, THE Wizard SHALL display a "Ready to configure HA replication" confirmation message with the exchanged details (both IPs, both PG ports)
9. IF any step of the Trust_Handshake fails, THEN THE Wizard SHALL display a human-readable error message identifying which step failed and allow the admin to retry

### Requirement 8: Wizard Step 5 — Automated Replication Setup

**User Story:** As a Global_Admin, I want to click a single "Start" button to configure all replication automatically, so that I do not need to run SQL commands or edit config files.

#### Acceptance Criteria

1. WHEN the Global_Admin clicks "Start" after a successful Trust_Handshake, THE Primary_Node SHALL configure the Standby_Node's HA settings (role=standby, peer endpoint, peer DB connection details) via the Standby_Node's authenticated API
2. THE Primary_Node SHALL configure its own HA settings (role=primary, peer endpoint pointing to the Standby_Node, peer DB connection details for the Standby_Node's database)
3. THE Primary_Node SHALL create a PostgreSQL Replication_Publication on its local database
4. THE Primary_Node SHALL instruct the Standby_Node to create a PostgreSQL Replication_Subscription via the Standby_Node's authenticated API
5. THE Primary_Node SHALL configure Volume_Sync on both nodes using the SSH keys and network details exchanged during the Trust_Handshake
6. THE Wizard SHALL display a Setup_Log with human-readable progress messages for each step as it executes (e.g., "Configuring standby node...", "Creating publication...", "Creating subscription...", "Configuring volume sync...")
7. WHEN all setup steps complete successfully, THE Wizard SHALL display a success message and transition to the normal HA monitoring view
8. IF any setup step fails, THEN THE Wizard SHALL display a human-readable error message in the Setup_Log identifying which step failed, stop further steps, and allow the admin to retry from the failed step

### Requirement 9: Setup Progress Feedback

**User Story:** As a Global_Admin, I want to see real-time, human-readable progress messages during the automated setup, so that I understand what the system is doing and can identify where failures occur.

#### Acceptance Criteria

1. WHILE the automated replication setup is in progress, THE Wizard SHALL display each step's status as one of: pending, in-progress, completed, or failed
2. THE Wizard SHALL update the Setup_Log in real-time as each step transitions between statuses
3. WHEN a step completes successfully, THE Wizard SHALL display a checkmark icon and a brief success description for that step
4. WHEN a step fails, THE Wizard SHALL display an error icon, the step name, and a human-readable error description

### Requirement 10: Standby-Side API Endpoints for Remote Configuration

**User Story:** As a system component, I want the Standby_Node to expose authenticated API endpoints for receiving trust handshake data and replication commands, so that the Primary_Node can configure the Standby_Node remotely during the Wizard flow.

#### Acceptance Criteria

1. THE Standby_Node SHALL expose an API endpoint that accepts and stores an SSH public key in its `authorized_keys` file, accessible only with a valid Global_Admin authentication token
2. THE Standby_Node SHALL expose an API endpoint that returns its own SSH public key, Host_LAN_IP, and local PostgreSQL host port, accessible only with a valid Global_Admin authentication token
3. THE Standby_Node SHALL expose an API endpoint that accepts and stores an HMAC_Secret, accessible only with a valid Global_Admin authentication token
4. THE Standby_Node SHALL expose an API endpoint that accepts HA configuration (role, peer endpoint, peer DB connection details) and applies it, accessible only with a valid Global_Admin authentication token
5. THE Standby_Node SHALL expose an API endpoint that triggers Replication_Subscription creation, accessible only with a valid Global_Admin authentication token
6. IF any endpoint is called without a valid Global_Admin authentication token, THEN THE Standby_Node SHALL return HTTP 401 or 403

### Requirement 11: Recovery — Broken Replication State Display

**User Story:** As a Global_Admin, I want to see a clear indication when replication is broken, so that I can take action to restore HA.

#### Acceptance Criteria

1. WHEN the Replication_Subscription status is not "active" or the peer heartbeat is unreachable for longer than the configured heartbeat interval, THE HA Replication page SHALL display a prominent warning banner indicating the broken state
2. THE warning banner SHALL include a human-readable description of the detected problem (e.g., "Subscription disconnected", "Standby unreachable since [timestamp]")

### Requirement 12: Recovery — Resume and Fresh Setup Options

**User Story:** As a Global_Admin, I want recovery options when replication breaks, so that I can restore HA without starting from scratch if possible.

#### Acceptance Criteria

1. WHEN replication is in a broken state, THE HA Replication page SHALL display two recovery action buttons: "Resume" and "Fresh Setup"
2. WHEN the Global_Admin clicks "Resume", THE Primary_Node SHALL attempt to re-establish the existing Replication_Subscription without dropping data
3. WHEN the Global_Admin clicks "Fresh Setup", THE Primary_Node SHALL drop all existing replication objects (publication, subscription, replication slots) on both nodes and re-run the full automated setup from the Trust_Handshake step
4. THE "Fresh Setup" action SHALL require the Global_Admin to type "CONFIRM" before proceeding
5. WHILE a recovery action is in progress, THE HA Replication page SHALL display human-readable progress messages in the Setup_Log

### Requirement 13: Docker Compose Volume and Port Configuration

**User Story:** As a system administrator, I want the Docker Compose files to include the `ha_keys` volume and SSHD port mapping, so that HA setup works out of the box without manual Docker configuration.

#### Acceptance Criteria

1. THE Docker Compose configuration for all HA-capable environments SHALL define a named volume `ha_keys` and mount it at `/ha_keys` in the app service
2. THE Docker Compose configuration for all HA-capable environments SHALL map container port 2222 to host port 2222 in the app service
3. THE Docker Compose configuration SHALL preserve bridge networking mode for all services

### Requirement 14: Container Networking Compatibility

**User Story:** As a system administrator, I want the HA setup to work with Docker bridge networking, so that Docker DNS resolution and port isolation are preserved.

#### Acceptance Criteria

1. THE Wizard SHALL use the auto-detected Host_LAN_IP (not container-internal IPs) for all peer endpoint and database connection configurations
2. THE Wizard SHALL use host-mapped ports (not container-internal ports) for PostgreSQL and SSHD connections between nodes
3. WHEN configuring peer database connections, THE Wizard SHALL use the Host_LAN_IP and the host-mapped PostgreSQL port of the peer node

### Requirement 15: Wizard Idempotency and Re-Entry

**User Story:** As a Global_Admin, I want to be able to re-run the Wizard without causing errors, so that I can recover from partial setups or reconfigure HA after changes.

#### Acceptance Criteria

1. WHEN the Wizard is run on nodes that already have HA configured, THE Wizard SHALL detect the existing configuration and offer to reconfigure (Fresh Setup) or skip to monitoring
2. THE Trust_Handshake SHALL be idempotent — running it multiple times SHALL update the stored keys and secrets without creating duplicates or errors
3. THE automated replication setup SHALL handle pre-existing publications and subscriptions by dropping and recreating them

### Requirement 16: Security of Trust Handshake Data

**User Story:** As a system administrator, I want the trust handshake to be secure, so that SSH keys and HMAC secrets are not exposed to unauthorized parties.

#### Acceptance Criteria

1. THE Trust_Handshake API endpoints SHALL require Global_Admin authentication on both nodes
2. THE HMAC_Secret SHALL be generated using a cryptographically secure random number generator
3. THE Standby_Node's Global_Admin credentials used during the Wizard SHALL be held only in browser memory and discarded after the Trust_Handshake completes
4. THE SSH private keys SHALL remain on their respective nodes and SHALL NOT be transmitted during the Trust_Handshake — only public keys are exchanged

### Requirement 17: Wizard UI Integration with Existing HA Page

**User Story:** As a Global_Admin, I want the Setup Wizard to be part of the existing HA Replication page, so that all HA management is in one place.

#### Acceptance Criteria

1. WHEN no HA Pairing exists, THE HA Replication page SHALL display the Wizard as the primary content area
2. WHEN HA is fully configured and healthy, THE HA Replication page SHALL display the existing monitoring and management UI
3. THE Wizard SHALL use the same visual styling (Tailwind CSS, Headless UI components) as the rest of the HA Replication page
4. THE Wizard SHALL display a step indicator showing the current step and total steps in the flow

---

## Bug Fixes — Critical

### Requirement 18: Fix `trigger_resync` Orphaned Replication Slot

**User Story:** As a Global_Admin, I want the Resync operation to clean up orphaned replication slots before recreating the subscription, so that resync does not fail with "replication slot already exists" errors.

**Context:** `trigger_resync` in `app/modules/ha/replication.py` calls `drop_subscription()` which uses `ALTER SUBSCRIPTION ... SET (slot_name = NONE)` before dropping. This intentionally leaves the replication slot as an orphan on the Primary_Node (necessary when the primary is unreachable). The subsequent `CREATE SUBSCRIPTION` then fails because the slot already exists. The `_cleanup_orphaned_slot_on_peer()` helper already exists and is called from `init_standby`, but `trigger_resync` skips this step.

#### Acceptance Criteria

1. WHEN `trigger_resync` is called, THE ReplicationManager SHALL call `_cleanup_orphaned_slot_on_peer(primary_conn_str)` after `drop_subscription` and before `CREATE SUBSCRIPTION`
2. WHEN the orphaned slot cleanup succeeds, THE ReplicationManager SHALL proceed to create the new subscription
3. IF the orphaned slot cleanup fails, THEN THE ReplicationManager SHALL propagate the error with a human-readable message indicating the slot could not be cleaned up
4. THE `trigger_resync` operation SHALL succeed on repeated calls without manual intervention on the Primary_Node

**File:** `app/modules/ha/replication.py`

### Requirement 19: Fix `promote()`/`demote()` Not Updating Heartbeat `local_role`

**User Story:** As a system administrator, I want manual promote and demote operations to update the heartbeat service's local role, so that split-brain detection works correctly after role changes.

**Context:** `promote()`, `demote()`, and `demote_and_sync()` in `app/modules/ha/service.py` call `set_node_role()` which updates the middleware module variable, but do not update `_heartbeat_service.local_role`. After a manual promote, `detect_split_brain(local_role="standby", peer_role="primary")` returns False — split-brain goes undetected. After a manual demote, `detect_split_brain(local_role="primary", peer_role="primary")` returns True — spurious split-brain fires and blocks writes on a legitimate Standby_Node.

#### Acceptance Criteria

1. WHEN `promote()` completes the role change to primary, THE HAService SHALL update `_heartbeat_service.local_role` to `"primary"`
2. WHEN `demote()` completes the role change to standby, THE HAService SHALL update `_heartbeat_service.local_role` to `"standby"`
3. WHEN `demote_and_sync()` completes the role change to standby, THE HAService SHALL update `_heartbeat_service.local_role` to `"standby"`
4. IF `_heartbeat_service` is None (heartbeat not running), THEN THE HAService SHALL skip the local_role update without raising an error

**File:** `app/modules/ha/service.py`

### Requirement 20: Fix `drop_replication_slot` Router Missing DB Session

**User Story:** As a Global_Admin, I want the Drop Replication Slot button in the UI to work, so that I can clean up orphaned or inactive replication slots without manual SQL commands.

**Context:** The `drop_replication_slot` endpoint in `app/modules/ha/router.py` passes `None` as the `db` parameter to `ReplicationManager.drop_replication_slot()`. The method calls `await db.execute(...)` which becomes `None.execute(...)` and raises `AttributeError`, returning HTTP 500 on every call. The Drop button in the Replication Slots UI is completely non-functional.

#### Acceptance Criteria

1. THE `drop_replication_slot` endpoint SHALL accept a database session via `db: AsyncSession = Depends(get_db_session)`
2. THE `drop_replication_slot` endpoint SHALL pass the database session to `ReplicationManager.drop_replication_slot(db, slot_name)`
3. WHEN the slot exists and is inactive, THE endpoint SHALL drop the slot and return a success response
4. WHEN the slot does not exist, THE endpoint SHALL return a not-found response
5. WHEN the slot is active, THE endpoint SHALL return an error response indicating the slot cannot be dropped while in use

**File:** `app/modules/ha/router.py`

---

## Bug Fixes — Significant

### Requirement 21: Fix `save_config` Heartbeat Restart Without Redis Lock Wiring

**User Story:** As a system administrator, I want the heartbeat service to maintain its Redis distributed lock after a configuration change, so that multi-worker race conditions do not cause duplicate heartbeat services.

**Context:** When `save_config` in `app/modules/ha/service.py` restarts the heartbeat service, it creates a new `HeartbeatService` instance. The Redis lock fields (`_redis_lock_key`, `_lock_ttl`, `_redis_client`) must be wired to the new instance so it can renew the distributed lock. Without this wiring, the old lock expires in ~30 seconds, another gunicorn worker acquires it, and two workers run heartbeat concurrently — reintroducing the multi-worker race condition.

#### Acceptance Criteria

1. WHEN `save_config` creates a new HeartbeatService instance, THE HAService SHALL set `_redis_lock_key`, `_lock_ttl`, and `_redis_client` on the new instance using the same values as the startup path in `main.py`
2. IF Redis is unavailable during the wiring, THEN THE HAService SHALL log a warning and continue starting the heartbeat service without lock renewal
3. THE new HeartbeatService instance SHALL renew the Redis lock TTL on each heartbeat cycle after the restart

**File:** `app/modules/ha/service.py`

### Requirement 22: Fix `demote()` Using `copy_data=true` and Not Dropping Publication

**User Story:** As a system administrator, I want the demote operation to correctly transition a Primary_Node to Standby_Node without duplicate key errors or leftover publications, so that graceful role reversals work reliably.

**Context:** `demote()` calls `resume_subscription()` which, in its fallback CREATE path, uses the default `copy_data=true`. A former Primary_Node already holds the complete dataset, so the initial table-sync causes duplicate primary key violations on every table. Additionally, `demote()` does not drop the publication, leaving the former Primary_Node with an unnecessary publication that retains WAL.

#### Acceptance Criteria

1. WHEN `demote()` transitions a Primary_Node to standby, THE HAService SHALL drop the existing Replication_Publication before creating the subscription
2. IF the publication drop fails, THEN THE HAService SHALL log a warning and continue with the demote operation
3. WHEN `resume_subscription()` falls through to the CREATE SUBSCRIPTION path, THE ReplicationManager SHALL use `copy_data = false` to prevent duplicate key violations on a node that already has all data
4. THE `demote()` operation SHALL complete successfully on a Primary_Node that has a full dataset without raising duplicate key errors

**Files:** `app/modules/ha/service.py`, `app/modules/ha/replication.py`

---

## Bug Fixes — Moderate

### Requirement 23: Fix `_auto_promote_attempted` Never Cleared After Peer Recovery

**User Story:** As a system administrator, I want auto-promote to be available again after a peer recovers from a transient outage, so that the system can handle future failover scenarios without requiring a container restart.

**Context:** In `app/modules/ha/heartbeat.py`, if auto-promote is attempted but fails for a transient reason (e.g., Redis lock held by another process, DB connection timeout), `_auto_promote_attempted` is set to `True` permanently. When the peer recovers and transitions from unreachable to reachable, `_peer_unreachable_since` is reset but `_auto_promote_attempted` is not. Auto-promote is permanently disabled until the container restarts.

#### Acceptance Criteria

1. WHEN the peer transitions from unreachable to reachable in the heartbeat ping loop, THE HeartbeatService SHALL reset `_auto_promote_attempted` to `False`
2. THE HeartbeatService SHALL NOT reset `_auto_promote_failed_permanently` when the peer recovers — permanent failure (two consecutive failures) requires a container restart
3. WHEN `_auto_promote_attempted` is reset, THE HeartbeatService SHALL be able to trigger auto-promote on a subsequent peer outage

**File:** `app/modules/ha/heartbeat.py`

### Requirement 24: Fix Dev Standby Compose Missing Replication Settings

**User Story:** As a developer, I want the dev standby Docker Compose file to have explicit replication settings, so that HA testing in the dev environment uses declared configuration rather than relying on implicit PostgreSQL defaults.

**Context:** `docker-compose.ha-standby.yml` is missing explicit `max_wal_senders=10` and `max_replication_slots=10` settings. All other compose files (`docker-compose.yml`, `docker-compose.pi.yml`, `docker-compose.standby-prod.yml`) have these settings. The dev standby relies on PostgreSQL 16 defaults which happen to be correct (10/10), but this is coincidental and not declared.

#### Acceptance Criteria

1. THE `docker-compose.ha-standby.yml` PostgreSQL service SHALL include explicit `-c max_wal_senders=10` in its command arguments
2. THE `docker-compose.ha-standby.yml` PostgreSQL service SHALL include explicit `-c max_replication_slots=10` in its command arguments

**File:** `docker-compose.ha-standby.yml`

---

## Security Fixes

### Requirement 25: Remove Leaked Credentials from Environment Files

**User Story:** As a system administrator, I want all committed environment files to be free of real passwords and secrets, so that credentials are not exposed in the git repository.

**Context:** `.env.standby-prod` contains `HA_PEER_DB_URL=postgresql://replicator:NoorHarleen1@192.168.1.90:5432/workshoppro` — a live password in a committed file. All `.env*` files contain `HA_HEARTBEAT_SECRET=dev-ha-secret-for-testing` which, if the DB secret is empty, silently becomes the active HMAC secret via the env-var fallback.

#### Acceptance Criteria

1. THE `.env.standby-prod` file SHALL have the `HA_PEER_DB_URL` value cleared (set to empty string)
2. THE `.env` file SHALL have the `HA_HEARTBEAT_SECRET` value cleared (set to empty string)
3. THE `.env.pi` file SHALL have the `HA_HEARTBEAT_SECRET` value cleared (set to empty string)
4. THE `.env.ha-standby` file SHALL have the `HA_HEARTBEAT_SECRET` value cleared (set to empty string)
5. THE `.env.standby-prod` file SHALL have the `HA_HEARTBEAT_SECRET` value cleared (set to empty string)
6. THE `.env.pi-standby` file SHALL retain its existing empty `HA_HEARTBEAT_SECRET` value

**Files:** `.env`, `.env.pi`, `.env.ha-standby`, `.env.standby-prod`, `.env.pi-standby`

### Requirement 26: Remove Environment Variable Fallbacks for HA Secrets

**User Story:** As a system administrator, I want HA secrets to be sourced exclusively from the database (configured via GUI), so that there is no silent fallback to potentially weak or stale environment variable values.

**Context:** `_get_heartbeat_secret_from_config()` in `app/modules/ha/service.py` falls back to `os.environ.get("HA_HEARTBEAT_SECRET")` if DB decryption fails. `get_peer_db_url()` falls back to `os.environ.get("HA_PEER_DB_URL")`. Error messages in `app/modules/ha/router.py` still tell users to set environment variables. Dead code: `_get_heartbeat_secret()` at `service.py:46-59` reads env only and is never called.

#### Acceptance Criteria

1. THE `_get_heartbeat_secret_from_config()` function SHALL return an empty string when DB decryption fails, without falling back to the `HA_HEARTBEAT_SECRET` environment variable
2. THE `get_peer_db_url()` function SHALL return None when DB peer config is empty, without falling back to the `HA_PEER_DB_URL` environment variable
3. THE dead `_get_heartbeat_secret()` function SHALL be removed from `app/modules/ha/service.py`
4. THE error messages in `app/modules/ha/router.py` that reference environment variables SHALL be updated to reference GUI-only configuration (e.g., "Set peer DB settings in HA configuration")

**Files:** `app/modules/ha/service.py`, `app/modules/ha/router.py`

---

## Frontend Fixes

### Requirement 27: Fix Peer Role Display Using Actual Heartbeat Data

**User Story:** As a Global_Admin, I want the peer node card to display the actual peer role from heartbeat data, so that the displayed role is accurate after promotions and failovers.

**Context:** The `FailoverStatusResponse` schema already includes a `peer_role` field populated from `_heartbeat_service.peer_role`, and the frontend already reads `failoverStatus?.peer_role` with a fallback to the inferred opposite role. The current implementation is correct. This requirement ensures the pattern is maintained and the fallback is only used when heartbeat data is unavailable (e.g., peer unreachable).

#### Acceptance Criteria

1. THE HA Replication page SHALL display the peer role from `failoverStatus.peer_role` when available
2. WHEN `failoverStatus.peer_role` is not available, THE HA Replication page SHALL fall back to displaying the logical opposite of the local role
3. THE `FailoverStatusResponse` schema SHALL include the `peer_role` field with a default value of `"unknown"`

**Files:** `app/modules/ha/schemas.py`, `frontend/src/pages/admin/HAReplication.tsx`

### Requirement 28: Add Confirmation Gate for `stop-replication` on Primary

**User Story:** As a Global_Admin, I want the stop-replication action to require typing "CONFIRM" before executing, so that I cannot accidentally stop all data flow to the Standby_Node.

**Context:** Stopping replication on a Primary_Node drops the publication, which halts all data flow to the Standby_Node. The `stop-replication` action is already included in the `needsConfirmText` list in `HAReplication.tsx`. This requirement ensures the confirmation gate remains in place.

#### Acceptance Criteria

1. WHEN the Global_Admin clicks "Stop Replication" on a Primary_Node, THE HA Replication page SHALL display a confirmation modal requiring the admin to type "CONFIRM"
2. THE confirmation modal SHALL display a description explaining that stopping replication drops the publication and halts data flow to the Standby_Node
3. THE "Stop Replication" action SHALL NOT execute until the admin types "CONFIRM" and provides a reason

**File:** `frontend/src/pages/admin/HAReplication.tsx`

### Requirement 29: Update Setup Guide Text to Remove `.env` References

**User Story:** As a Global_Admin, I want the setup guide to accurately reflect that HA configuration is GUI-only, so that I am not misled into editing environment files.

**Context:** The Security Notes section in the HA Setup Guide within `HAReplication.tsx` should state that HA secrets and credentials are stored encrypted in the database and configured via the GUI. Any remaining references to `.env` files for HA configuration should be removed or clarified.

#### Acceptance Criteria

1. THE Security Notes section in the HA Setup Guide SHALL state that the heartbeat secret and peer DB credentials are stored encrypted in the database
2. THE Security Notes section SHALL state that no `.env` file entries are required for HA configuration
3. THE Setup Guide SHALL NOT instruct users to edit `.env` files for HA-related settings

**File:** `frontend/src/pages/admin/HAReplication.tsx`

---

## Docker Infrastructure

### Requirement 30: Ensure Wizard Uses DB-Stored `local_lan_ip` and `local_pg_port`

**User Story:** As a system administrator, I want the setup wizard's trust handshake to use DB-stored LAN IP and PG port values when available, so that the correct network details are exchanged even when auto-detection returns incorrect values (e.g., container-internal IPs on Linux Docker).

**Context:** The `local_lan_ip` and `local_pg_port` columns already exist in the `ha_config` model and are exposed in the GUI from a previous spec (ha-gui-config-cleanup). The `local-db-info` endpoint already uses the priority chain: DB field > env var > auto-detect. This requirement ensures the wizard's trust handshake reads these DB-stored values during the exchange, and that the entrypoint auto-detection populates them in the DB if not already set.

#### Acceptance Criteria

1. WHEN the Trust_Handshake exchanges network details, THE Primary_Node SHALL read `local_lan_ip` and `local_pg_port` from the `ha_config` database record if set, falling back to environment variable and then auto-detection
2. WHEN the Trust_Handshake exchanges network details, THE Standby_Node SHALL read `local_lan_ip` and `local_pg_port` from the `ha_config` database record if set, falling back to environment variable and then auto-detection
3. WHEN the Entrypoint_Script detects the Host_LAN_IP and no `local_lan_ip` value is stored in the database, THE application startup path SHALL store the auto-detected value in the `ha_config.local_lan_ip` column for future use
4. THE "View Connection Info" modal SHALL display a note indicating that IP and port are auto-detected and can be overridden in Node Configuration if incorrect

**Files:** `app/modules/ha/router.py`, `app/modules/ha/service.py`, `frontend/src/pages/admin/HAReplication.tsx`


---

## Infrastructure Fixes (Final Audit Findings)

### Requirement 31: Install `openssh-server` and `rsync` in Dockerfile

**User Story:** As a system administrator, I want the app container to include SSH server and rsync binaries, so that the wizard's sshd service and volume sync features work without manual package installation.

**Context:** The current `Dockerfile` only installs WeasyPrint dependencies (`libpango`, `libcairo`, etc.). The wizard requires `openssh-server` (for sshd on port 2222) and `rsync` (for volume sync). The `python:3.11-slim` base image does not include either package. Without these, the entrypoint cannot start sshd, and the volume sync service's `rsync` subprocess calls will fail with "command not found".

#### Acceptance Criteria

1. THE Dockerfile SHALL install `openssh-server` and `rsync` packages in the `apt-get install` step alongside the existing WeasyPrint dependencies
2. THE Dockerfile SHALL create the `/run/sshd` directory required by the OpenSSH server daemon
3. THE installed packages SHALL NOT significantly increase the image size (openssh-server ~3 MB, rsync ~0.5 MB on slim)
4. THE Dockerfile SHALL NOT expose port 2222 directly — port exposure is handled by Docker Compose configuration per environment

**File:** `Dockerfile`

### Requirement 32: Fix Standby Role Detection in Container Entrypoint

**User Story:** As a system administrator, I want the container entrypoint to correctly detect when the node is a standby, so that database migrations are skipped on standby nodes (where data comes from replication).

**Context:** The current `docker-entrypoint.sh` uses `psql` to query `ha_config.role`, but `psql` is NOT installed in the container image (`python:3.11-slim` does not include PostgreSQL client tools). The command fails silently due to `2>/dev/null || echo "standalone"`, causing the entrypoint to always return "standalone" and run migrations on every startup — including on standby nodes where migrations should be skipped because data arrives via replication.

Running migrations on a standby node can cause:
- Schema conflicts with replicated data
- Alembic version table conflicts (the primary's alembic_version is replicated)
- Duplicate table/column creation errors if the migration has already been applied via replication

#### Acceptance Criteria

1. THE Entrypoint_Script SHALL use Python with `asyncpg` (already installed in the image) instead of `psql` to query the `ha_config` table for the node role
2. WHEN the `ha_config` table exists and contains a row with `role = 'standby'`, THE Entrypoint_Script SHALL skip database migrations
3. WHEN the `ha_config` table does not exist or contains no rows, THE Entrypoint_Script SHALL treat the node as standalone and run migrations normally
4. WHEN the database is unreachable during the role check, THE Entrypoint_Script SHALL fall back to running migrations (safe default for first deployment)
5. THE role detection SHALL complete within 5 seconds to avoid delaying container startup

**File:** `scripts/docker-entrypoint.sh`

### Requirement 33: Escape Connection String in Replication SQL Statements

**User Story:** As a system administrator, I want PostgreSQL connection strings used in replication SQL to be properly escaped, so that passwords containing special characters (single quotes, backslashes) do not break the SQL syntax.

**Context:** `init_standby`, `trigger_resync`, and `resume_subscription` in `app/modules/ha/replication.py` interpolate `primary_conn_str` directly into SQL strings using f-strings: `f"CONNECTION '{primary_conn_str}'"`. While the connection string is constructed from controlled input via `_build_peer_db_url()` (which uses `urllib.parse.quote_plus` for user and password), a password containing a literal single quote (`'`) would break the SQL syntax because `quote_plus` encodes for URLs, not for SQL string literals.

Example: password `O'Brien` → URL-encoded as `O%27Brien` → works in URL but PostgreSQL's `CONNECTION` clause expects a libpq connection string, not a URL. The actual risk is low because `_build_peer_db_url` produces `postgresql://` URLs which libpq accepts, but the single-quote escaping for the SQL wrapper is still needed.

#### Acceptance Criteria

1. WHEN constructing SQL statements that include a `CONNECTION` clause, THE ReplicationManager SHALL escape single quotes in the connection string by doubling them (`'` → `''`) before interpolation
2. THE escaping SHALL be applied in a single helper method used by `init_standby`, `trigger_resync`, and `resume_subscription`
3. THE escaping SHALL handle connection strings containing single quotes, backslashes, and other SQL-special characters without breaking the SQL syntax

**File:** `app/modules/ha/replication.py`


### Requirement 34: Persistent HA Event Log

**User Story:** As a Global_Admin, I want HA events (heartbeat failures, role changes, replication errors, auto-promote attempts, split-brain detections) persisted to the database and visible on the HA Replication page, so that I can diagnose issues without digging through container logs that are lost on restart.

**Context:** Currently, heartbeat history is stored in an in-memory `deque(maxlen=100)` inside `HeartbeatService`. This data is lost on every container restart. Errors from heartbeat failures, auto-promote attempts, split-brain detections, and replication issues are only visible in `docker logs` output, which rotates and is not accessible from the admin UI. When troubleshooting HA issues, the admin has no persistent record of what happened — they see the current state but not the history of events that led to it.

The HA event log should capture:
- Heartbeat failures (peer unreachable, HMAC mismatch, timeout)
- Role transitions (promote, demote, auto-promote)
- Replication events (subscription created, dropped, resync triggered, slot cleanup)
- Split-brain detections and resolutions
- Volume sync failures
- Configuration changes
- Recovery actions (resume, fresh setup)

#### Acceptance Criteria

1. THE system SHALL create an `ha_event_log` database table with columns: `id` (UUID PK), `timestamp` (DateTime with timezone), `event_type` (String — e.g., 'heartbeat_failure', 'role_change', 'replication_error', 'split_brain', 'auto_promote', 'volume_sync_error', 'config_change', 'recovery'), `severity` (String — 'info', 'warning', 'error', 'critical'), `message` (Text — human-readable description), `details` (JSONB, nullable — structured error data like stack traces, peer response, lag values), `node_name` (String — which node logged the event)
2. THE `ha_event_log` table SHALL be excluded from the replication publication (it is per-node, like `ha_config`)
3. THE HeartbeatService SHALL write an event to `ha_event_log` when a heartbeat ping fails (with the error reason), when the peer transitions between health states (healthy → degraded → unreachable), and when auto-promote is attempted or fails
4. THE HAService SHALL write an event to `ha_event_log` when a role change occurs (promote, demote, demote-and-sync), when replication is initialized or stopped, and when a resync is triggered
5. THE VolumeSyncService SHALL write an event to `ha_event_log` when a volume sync fails (with the rsync error output)
6. THE HA Replication page SHALL display the most recent HA events (default: last 50) in a filterable table with columns: Time, Severity (color-coded badge), Event Type, Message
7. THE event log table on the frontend SHALL support filtering by severity (info/warning/error/critical) and event type
8. THE `ha_event_log` table SHALL have an index on `timestamp DESC` for efficient querying
9. THE system SHALL automatically prune events older than 30 days to prevent unbounded table growth (via a periodic cleanup in the heartbeat loop or a startup hook)
10. EVENT writes SHALL be non-blocking — failures to write to the event log SHALL NOT affect the heartbeat loop, role transitions, or any other HA operations (wrap in try/except, log to stderr as fallback)

**Files:** New migration, new model in `app/modules/ha/`, `app/modules/ha/heartbeat.py`, `app/modules/ha/service.py`, `app/modules/ha/volume_sync_service.py`, `app/modules/ha/router.py`, `frontend/src/pages/admin/HAReplication.tsx`


---

## Integration Testing & Validation

### Requirement 35: Local Dev Two-Stack Integration Test

**User Story:** As a developer, I want to test the full HA wizard flow locally using two Docker Compose stacks on the same machine, so that I can verify the entire setup works end-to-end before deploying to production.

**Context:** The existing dev stack runs on ports 80 (nginx), 5434 (postgres), 6379 (redis). The HA standby dev stack runs on ports 8081 (nginx), 5433 (postgres), 6380 (redis). Both stacks must run simultaneously on the same Windows/Linux host without port conflicts. The wizard must be tested by navigating to the primary's HA page, entering the standby's address, and completing the full wizard flow — exactly as a production user would.

#### Acceptance Criteria

1. THE dev primary stack SHALL run with its existing port mappings (80, 5434, 6379) plus the new SSHD port 2222
2. THE dev standby stack SHALL run with its existing port mappings (8081, 5433, 6380) plus SSHD on port 2223 (to avoid conflict with primary's 2222)
3. BOTH stacks SHALL be rebuilt from scratch (`--build --force-recreate`) after all code changes to verify the Dockerfile, entrypoint, and compose changes work correctly
4. THE primary stack's app container logs SHALL show: SSH keypair generated (or reused), host LAN IP detected, sshd started on port 2222, migrations run successfully
5. THE standby stack's app container logs SHALL show the same startup sequence with sshd on port 2222 (mapped to host 2223)
6. THE wizard flow SHALL be tested by navigating to `http://localhost/admin/ha-replication` on the primary and completing all 5 steps using the standby's address (`http://{host_lan_ip}:8081`)
7. AFTER the wizard completes, PostgreSQL logical replication SHALL be active — data written on the primary SHALL appear on the standby within 10 seconds
8. AFTER the wizard completes, the heartbeat service SHALL be running on both nodes with successful pings visible in the heartbeat history
9. AFTER the wizard completes, the volume sync configuration SHALL be set on both nodes with the correct SSH key paths and remote addresses
10. THE `ha_event_log` table on both nodes SHALL contain events from the wizard setup process

### Requirement 36: Iterative Bug Fix and Steering Doc Update Loop

**User Story:** As a developer, I want all bugs encountered during integration testing to be fixed immediately and documented in steering docs, so that the same mistakes are never repeated in future implementations.

**Context:** Previous implementations have consistently hit errors during testing that required multiple rounds of troubleshooting. This requirement mandates that every error encountered during the integration test is: (1) fixed in the code, (2) verified by re-running the test, and (3) documented as a lesson learned in the appropriate steering doc.

#### Acceptance Criteria

1. WHEN an error is encountered during integration testing, THE developer SHALL fix the root cause (not just the symptom) before proceeding to the next test step
2. WHEN a fix is applied, THE developer SHALL re-run the full wizard flow from the beginning to verify no regressions were introduced
3. WHEN a new class of bug is discovered (not already documented), THE developer SHALL add a rule to the appropriate steering doc in `.kiro/steering/`:
   - Docker/container issues → `deployment-environments.md` or new `ha-infrastructure.md`
   - Frontend API mismatches → `frontend-backend-contract-alignment.md`
   - Database/migration issues → `database-migration-checklist.md`
   - Security issues → `security-hardening-checklist.md`
   - Performance issues → `performance-and-resilience.md`
4. THE integration test SHALL NOT be considered complete until the full wizard flow succeeds end-to-end with zero errors on a clean rebuild of both stacks
5. THE final test run SHALL include: creating test data on the primary (e.g., a test customer), verifying it replicates to the standby, and verifying the HA event log records the replication events

### Requirement 37: Version Tracking

**User Story:** As a developer, I want the HA wizard feature to include a version identifier, so that both nodes can verify they are running compatible versions during the trust handshake.

#### Acceptance Criteria

1. THE application SHALL expose a version identifier in the heartbeat response (e.g., `"app_version": "1.3.0"` or a build SHA)
2. DURING the wizard's reachability check (Step 2), THE Primary_Node SHALL compare its version with the Standby_Node's version from the heartbeat response
3. IF the versions differ, THE Wizard SHALL display a warning message indicating the version mismatch but SHALL NOT block the setup (version differences may be intentional during rolling updates)
4. THE version identifier SHALL be set from the `GIT_SHA` build argument in the Dockerfile or from a `VERSION` file in the repository root
