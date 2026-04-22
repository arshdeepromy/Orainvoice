# Requirements Document

## Introduction

This specification covers five improvements to the existing OraInvoice HA (High Availability) replication system. The current system uses PostgreSQL 16 logical replication between a primary node (Raspberry Pi) and a standby node (local Windows machine), with heartbeat monitoring, manual promote/demote, and replication slot management already implemented.

The improvements address gaps identified during real-world setup and operation:
1. Auto-truncate on standby initialization (users get locked out because truncation deletes local users)
2. Auto-promote failover (the `auto_promote_enabled` flag exists but has no backend logic)
3. Role reversal after recovery (no guided flow when old primary comes back online)
4. Split-brain write protection (detection exists but no write-blocking or resolution flow)
5. New standby setup wizard (no guided flow for replacing a dead primary's standby)

## Glossary

- **HA_System**: The High Availability replication module in OraInvoice, comprising the heartbeat service, replication manager, HA service, middleware, and admin UI
- **Primary_Node**: The HA node currently accepting writes and publishing data via PostgreSQL logical replication
- **Standby_Node**: The HA node receiving replicated data from the primary via a PostgreSQL subscription; rejects write requests
- **HeartbeatService**: The background asyncio task that pings the peer node's heartbeat endpoint at a configurable interval and tracks health history
- **ReplicationManager**: The component that manages PostgreSQL publication/subscription lifecycle and replication status monitoring
- **HAService**: The core business logic service for HA node management including configuration, promote/demote, and maintenance mode
- **StandbyWriteProtectionMiddleware**: The ASGI middleware that blocks non-read requests when the node role is standby or when split-brain write protection is active
- **Failover_Timeout**: The configurable duration (default 90 seconds) a standby waits after detecting the primary is unreachable before auto-promoting; stored as `failover_timeout_seconds` in HAConfig
- **Auto_Promote**: The automatic promotion of a standby node to primary when the primary has been unreachable for longer than the Failover_Timeout and `auto_promote_enabled` is true
- **Split_Brain**: A condition where both nodes in the HA cluster claim the role of primary simultaneously, risking data divergence
- **Promotion_Timestamp**: The UTC datetime recorded when a node is promoted to primary, used to determine recency during split-brain resolution; stored as `promoted_at` in HAConfig
- **Stale_Primary**: During a split-brain condition, the node whose Promotion_Timestamp is older (or null), indicating it was promoted less recently
- **ha_config**: The PostgreSQL table storing per-node HA configuration; excluded from replication so each node maintains independent state
- **Truncation**: The SQL TRUNCATE operation that removes all rows from tables, used to clear standby data before initial replication sync
- **Orphaned_Slot**: A PostgreSQL replication slot that exists on the primary but has no active subscriber, typically left over from a failed initialization attempt

## Requirements

### Requirement 1: Standby Initialization Warning Modal

**User Story:** As an admin, I want to see a clear warning before initializing replication on a standby node, so that I understand all local data will be replaced by data from the primary.

#### Acceptance Criteria

1. WHEN the admin clicks "Initialize Replication" on a Standby_Node, THE HA_System SHALL display a warning modal with the message: "This will replace ALL local data with data from the primary. Local users, organisations, and all business data will be overwritten. You will not be able to log in with local credentials after this."
2. THE warning modal SHALL require the admin to type "CONFIRM" before the initialization proceeds
3. IF the admin cancels the warning modal, THEN THE HA_System SHALL take no action and leave the standby data unchanged
4. WHEN the admin confirms the warning modal, THE HA_System SHALL proceed with the auto-truncate and subscription creation defined in Requirement 2

### Requirement 2: Auto-Truncate on Standby Initialization

**User Story:** As an admin, I want the standby initialization to automatically truncate all replicated tables before creating the subscription, so that the initial data sync from the primary does not fail due to duplicate key conflicts.

#### Acceptance Criteria

1. WHEN the admin confirms standby initialization, THE ReplicationManager SHALL truncate all tables in the public schema except ha_config before creating the PostgreSQL subscription
2. THE ReplicationManager SHALL execute the truncation using CASCADE to handle foreign key dependencies
3. THE ReplicationManager SHALL execute the truncation within a single transaction so that either all tables are truncated or none are
4. IF the truncation fails, THEN THE ReplicationManager SHALL return a descriptive error message and not proceed with subscription creation
5. WHEN truncation succeeds, THE ReplicationManager SHALL create the subscription with `copy_data=true` to trigger a full data sync from the primary
6. THE ReplicationManager SHALL clean up orphaned replication slots on the primary automatically before creating the subscription
7. THE HA_System SHALL log the truncation event in the application log with the count of truncated tables

### Requirement 3: Auto-Promote Failover Detection

**User Story:** As an admin, I want the standby node to automatically detect when the primary is unreachable and count down to auto-promotion, so that the system can recover without manual intervention.

#### Acceptance Criteria

1. WHILE the Standby_Node has `auto_promote_enabled` set to true, THE HeartbeatService SHALL track the continuous duration that the Primary_Node has been unreachable
2. WHEN the Primary_Node transitions from reachable to unreachable, THE HeartbeatService SHALL record the timestamp of the transition
3. WHILE the Primary_Node is unreachable, THE HeartbeatService SHALL expose the elapsed unreachable duration and the remaining seconds until auto-promotion via a status query
4. THE HeartbeatService SHALL calculate the remaining seconds as `failover_timeout_seconds` minus the elapsed unreachable duration
5. IF the Primary_Node becomes reachable again before the Failover_Timeout expires, THEN THE HeartbeatService SHALL reset the unreachable duration counter to zero

### Requirement 4: Auto-Promote Execution

**User Story:** As an admin, I want the standby to automatically promote itself to primary after the failover timeout expires, so that the system resumes accepting writes without manual intervention.

#### Acceptance Criteria

1. WHEN the unreachable duration exceeds the Failover_Timeout AND `auto_promote_enabled` is true, THE HA_System SHALL automatically promote the Standby_Node to Primary_Node
2. THE HA_System SHALL stop the replication subscription before changing the role to primary
3. THE HA_System SHALL record the Promotion_Timestamp in the ha_config table when auto-promotion occurs
4. THE HA_System SHALL log the auto-promotion event in the audit log with action "ha.auto_promoted", including the unreachable duration and the failover timeout value, using a system-generated UUID as the user_id since no user session is active during auto-promotion
5. IF the auto-promotion fails, THEN THE HA_System SHALL log the error and retry once after 10 seconds
6. IF the retry also fails, THEN THE HA_System SHALL log a critical error and not attempt further auto-promotions until the HeartbeatService is restarted
7. THE HA_System SHALL update the middleware role cache to "primary" immediately after successful auto-promotion so the node begins accepting writes
8. THE auto-promotion logic SHALL use a dedicated short-lived database session (via `async_session_factory`) to avoid transaction timeout issues with the heartbeat service's long-running context

### Requirement 5: Auto-Promote UI Status

**User Story:** As an admin, I want to see the auto-promote countdown status in the HA dashboard, so that I can monitor the failover process and intervene if needed.

#### Acceptance Criteria

1. WHILE the Primary_Node is unreachable AND `auto_promote_enabled` is true, THE HA_System SHALL display a status banner: "Primary unreachable for X seconds, auto-promote in Y seconds"
2. THE status banner SHALL update on each polling cycle (default 10 seconds) to reflect the current countdown
3. WHEN `auto_promote_enabled` is false AND the Primary_Node is unreachable, THE HA_System SHALL display: "Primary unreachable for X seconds. Auto-promote is disabled."
4. WHEN auto-promotion completes successfully, THE HA_System SHALL display a success banner: "This node has been automatically promoted to primary"
5. THE HA_System SHALL expose the auto-promote countdown state via the GET `/api/v1/ha/failover-status` endpoint so the frontend can poll for updates

### Requirement 6: Role Reversal Detection

**User Story:** As an admin, I want the system to detect when a recovered node conflicts with the current primary, so that split-brain conditions are identified immediately.

#### Acceptance Criteria

1. WHEN the HeartbeatService detects that both the local node and the peer node claim the role "primary", THE HA_System SHALL set a `split_brain_detected` flag to true
2. WHEN split-brain is detected on a node whose Promotion_Timestamp is older than the peer's Promotion_Timestamp, THE HA_System SHALL mark that node as the "stale primary"
3. WHEN split-brain is detected on a node whose Promotion_Timestamp is null (never explicitly promoted, e.g. originally configured as primary), THE HA_System SHALL treat that node as the stale primary
4. THE HA_System SHALL expose the split-brain status and stale-primary determination via the heartbeat status API and the failover-status endpoint
5. WHEN the peer's heartbeat response includes a `promoted_at` timestamp, THE HeartbeatService SHALL compare it with the local Promotion_Timestamp to determine which node was promoted more recently

### Requirement 7: Role Reversal Guided Flow

**User Story:** As an admin, I want a guided flow to demote the recovered old primary and configure it as a standby of the new primary, so that the cluster returns to a healthy state without manual SQL commands.

#### Acceptance Criteria

1. WHEN split-brain is detected AND the local node is the stale primary, THE HA_System SHALL display a guided recovery modal: "This node was previously primary but another node has been promoted. Would you like to demote this node to standby and sync from the new primary?"
2. THE guided recovery modal SHALL present two options: "Demote and Sync" and "Dismiss (manual resolution)"
3. WHEN the admin selects "Demote and Sync", THE HA_System SHALL display a data loss acknowledgment: "Any data written to this node after the failover will be lost. The new primary's data will replace all local data."
4. THE admin SHALL type "CONFIRM" to proceed with the demote-and-sync operation
5. WHEN the admin confirms, THE HA_System SHALL demote the local node to standby, truncate all replicated tables (except ha_config), and create a subscription pointing to the new primary
6. THE HA_System SHALL log the role reversal event in the audit log with action "ha.role_reversal_completed"
7. IF the demote-and-sync operation fails, THEN THE HA_System SHALL display the error and allow the admin to retry or choose manual resolution

### Requirement 8: Split-Brain Write Protection

**User Story:** As an admin, I want writes to be blocked on the stale primary during a split-brain condition, so that data divergence is minimized.

#### Acceptance Criteria

1. WHEN split-brain is detected AND the local node is determined to be the stale primary, THE StandbyWriteProtectionMiddleware SHALL block all write requests on the stale primary
2. THE HA_System SHALL display a critical alert banner in the UI: "SPLIT-BRAIN DETECTED: This node's data may be stale. Writes are blocked until the conflict is resolved."
3. THE write protection SHALL allow read requests (GET, HEAD, OPTIONS) to continue
4. THE write protection SHALL allow HA management endpoints (`/api/v1/ha/*`) and authentication endpoints (`/api/v1/auth/*`) to continue functioning so the admin can resolve the conflict
5. IF the admin resolves the split-brain (via demote, the guided flow, or manual role change), THEN THE StandbyWriteProtectionMiddleware SHALL lift the write protection according to the new role
6. THE HA_System SHALL require manual intervention to resolve split-brain conditions; automatic resolution SHALL NOT be attempted

### Requirement 9: New Standby Setup Wizard — Entry Point

**User Story:** As an admin, I want a guided wizard to set up a new standby node when the old primary is permanently dead, so that I can restore HA capability with a replacement server.

#### Acceptance Criteria

1. WHEN the HA_System is configured as primary AND no peer heartbeat has been received for more than 5 minutes, THE HA_System SHALL display a suggestion banner: "Peer node appears permanently unreachable. Would you like to set up a new standby?"
2. WHEN the admin clicks "Set Up New Standby", THE HA_System SHALL launch a step-by-step wizard
3. THE wizard SHALL consist of four steps: (a) Configure peer database connection, (b) Test peer database connectivity, (c) Create replication user on the new primary, (d) Summary with instructions for the new standby
4. THE wizard SHALL reuse the existing peer database settings form, test connection functionality, and replication user creation functionality from the current HA page

### Requirement 10: New Standby Setup Wizard — Execution

**User Story:** As an admin, I want the setup wizard to validate each step before proceeding, so that I can be confident the new standby will connect successfully.

#### Acceptance Criteria

1. WHEN the admin completes the peer database connection form in the wizard, THE HA_System SHALL save the peer database settings to the ha_config table
2. WHEN the admin clicks "Test Connection" in the wizard, THE HA_System SHALL verify connectivity to the peer database and confirm `wal_level=logical`
3. IF the connection test fails, THEN THE HA_System SHALL display the error and prevent the admin from proceeding to the next step
4. WHEN the admin creates the replication user in the wizard, THE HA_System SHALL create the user with REPLICATION and SELECT privileges on the local database
5. WHEN all wizard steps are complete, THE HA_System SHALL display a summary with instructions: "Go to the new standby node's HA page, configure it as Standby with this node as the peer, and click Initialize Replication."
6. THE HA_System SHALL log the new standby setup initiation in the audit log with action "ha.new_standby_setup"

### Requirement 11: Promotion Timestamp Tracking

**User Story:** As an admin, I want each promotion event to be timestamped, so that the system can determine which node was promoted more recently during split-brain resolution.

#### Acceptance Criteria

1. WHEN a node is promoted to primary (manually or via auto-promote), THE HAService SHALL record the current UTC timestamp in a `promoted_at` column in the ha_config table
2. THE `promoted_at` column SHALL be added via an Alembic migration that is idempotent (uses IF NOT EXISTS or equivalent guard)
3. THE HeartbeatService SHALL include the `promoted_at` timestamp in the heartbeat response payload
4. THE HeartbeatService SHALL include the `promoted_at` timestamp in the HMAC-signed portion of the heartbeat payload
5. WHEN a node is demoted to standby, THE HAService SHALL clear the `promoted_at` timestamp by setting it to null

### Requirement 12: Failover Status API

**User Story:** As a frontend developer, I want a REST API endpoint that returns the current auto-promote countdown state, so that the UI can display real-time failover status.

#### Acceptance Criteria

1. THE HA_System SHALL expose a GET `/api/v1/ha/failover-status` endpoint that returns the current failover state
2. THE endpoint response SHALL be defined as a Pydantic response schema (`FailoverStatusResponse`) with typed fields: `auto_promote_enabled` (bool), `peer_unreachable_seconds` (float or null), `failover_timeout_seconds` (int), `seconds_until_auto_promote` (float or null), `split_brain_detected` (bool), `is_stale_primary` (bool), and `promoted_at` (ISO 8601 string or null)
3. THE endpoint SHALL require the `global_admin` role
4. WHEN the peer is reachable, THE endpoint SHALL return `peer_unreachable_seconds` as null and `seconds_until_auto_promote` as null

### Requirement 13: Background Task Guard on Standby

**User Story:** As a system operator, I want background tasks (billing, trial expiry, grace period checks, suspension retention) to be skipped on standby nodes, so that they don't fail with write errors and don't miss billing cycles that the primary is handling.

#### Acceptance Criteria

1. THE task scheduler SHALL check the current node role before executing each scheduled task
2. WHEN the node role is "standby", THE task scheduler SHALL skip all tasks that write to the database (billing, trial expiry, grace period, suspension retention, SMS quota reset, Carjam quota reset)
3. THE task scheduler SHALL log a debug message when skipping a task due to standby role
4. WHEN the node is promoted to primary (manually or via auto-promote), THE task scheduler SHALL resume executing all tasks on the next scheduled cycle
5. THE role check SHALL read from the middleware role cache (not the database) to avoid adding DB queries to every task cycle

### Requirement 14: Standby-Safe Container Startup

**User Story:** As a system operator, I want the container entrypoint to detect standby mode and skip migrations and seeding, so that standby containers don't crash-loop on startup.

#### Acceptance Criteria

1. THE docker entrypoint SHALL check if the node is a standby before running `alembic upgrade head`
2. WHEN the node is a standby (determined by checking the `ha_config` table role column via a direct psql query), THE entrypoint SHALL skip migrations and log "Standby node — skipping migrations (data comes from replication)"
3. WHEN the node is a standby in development mode, THE entrypoint SHALL skip the dev seed script
4. WHEN the node is a primary or standalone (or ha_config doesn't exist), THE entrypoint SHALL run migrations and seeding normally
5. THE startup-time demo org sync (`sync_demo_org_modules`) SHALL also check the node role and skip writes on standby

### Requirement 15: Heartbeat Service Crash Recovery

**User Story:** As a system operator, I want the heartbeat service to recover from unexpected errors without dying, so that auto-promote and peer monitoring continue working.

#### Acceptance Criteria

1. THE HeartbeatService `_ping_loop()` SHALL wrap each ping cycle in a try/except that catches all exceptions (except CancelledError)
2. WHEN an unexpected exception occurs in the ping loop, THE HeartbeatService SHALL log the error and continue to the next cycle after the normal interval
3. THE HeartbeatService SHALL track consecutive failures and log a warning after 5 consecutive failures
4. THE HeartbeatService SHALL NOT crash or stop the background task due to transient errors (network issues, DNS failures, JSON parse errors)

### Requirement 16: Sync Status Column Updates

**User Story:** As an admin, I want the HA dashboard to show the actual replication sync status, so that I can see at a glance whether replication is healthy, lagging, or disconnected.

#### Acceptance Criteria

1. THE HeartbeatService SHALL update the `sync_status` column in ha_config based on the replication state after each heartbeat cycle
2. THE sync_status SHALL be set to "healthy" when the subscription is active and lag is < 60 seconds
3. THE sync_status SHALL be set to "lagging" when the subscription is active but lag is >= 60 seconds
4. THE sync_status SHALL be set to "disconnected" when the subscription exists but is disabled or the peer is unreachable
5. THE sync_status SHALL be set to "not_configured" when no subscription or publication exists
6. THE sync_status update SHALL use a dedicated short-lived DB session to avoid interfering with the heartbeat service's main loop
