# Requirements Document

## Introduction

High Availability (HA) Replication enables the OraInvoice platform to run on two Raspberry Pi nodes at different physical locations, with one node designated as primary (serving traffic) and the other as standby (ready to take over). The system uses PostgreSQL logical replication to keep the standby database in sync with the primary, a heartbeat service for health monitoring, and an admin GUI for visibility and manual failover control. DNS/NPM-level routing is managed externally by the administrator — the app handles replication, health monitoring, and role management only. This enables zero-downtime rolling updates: promote standby, update the idle node, test, swap back, update the other.

## Glossary

- **Primary_Node**: The node currently accepting read/write traffic and serving customers. Its PostgreSQL instance is the replication source.
- **Standby_Node**: The node running an identical copy of the application stack, receiving replicated data from the Primary_Node. It can be promoted to Primary_Node during failover.
- **Heartbeat**: A periodic HTTP health check between the two nodes to detect availability. Each node pings the other's heartbeat endpoint.
- **Replication_Lag**: The time delay between a write on the Primary_Node and that write being applied on the Standby_Node, measured in seconds.
- **Failover**: The process of promoting the Standby_Node to Primary_Node, either manually by the admin or automatically when the Primary_Node is unreachable.
- **Promotion**: The act of changing a node's role from standby to primary, making it accept writes and serve traffic.
- **Demotion**: The act of changing a node's role from primary to standby, making it stop accepting writes and begin receiving replication data.
- **Node_Registry**: A configuration record stored in each node's database identifying itself and its peer, including roles, endpoints, and health status.
- **Sync_Status**: The current state of replication between nodes — syncing, healthy, lagging, disconnected, or error.
- **Global_Admin**: A user with the `global_admin` role who has access to platform-wide settings including HA management.
- **Rolling_Update**: A deployment strategy where one node is updated at a time while the other continues serving traffic, achieving zero-downtime updates.

## Requirements

### Requirement 1: Node Identity and Registration

**User Story:** As a Global_Admin, I want each node to know its own identity and its peer's address, so that the two nodes can communicate and replicate data.

#### Acceptance Criteria

1. THE system SHALL store a node configuration containing: node_id (UUID), node_name (human-readable), role (primary or standby), peer_endpoint (URL of the other node's API), and last_updated timestamp.
2. THE system SHALL provide an admin API endpoint to configure the peer node endpoint and assign the local node's role.
3. WHEN a node starts up with HA configuration present, THE system SHALL validate connectivity to the peer endpoint within 15 seconds.
4. IF the peer is unreachable at startup, THE system SHALL log a warning and continue operating in its current role, retrying peer connectivity every 30 seconds.
5. THE system SHALL expose a `GET /api/v1/ha/identity` endpoint (global_admin only) returning the local node's identity, role, and peer configuration.

### Requirement 2: Heartbeat Health Monitoring

**User Story:** As a Global_Admin, I want each node to continuously monitor the other's health, so that I can see when a node goes down and the system can detect failures.

#### Acceptance Criteria

1. THE system SHALL expose a `GET /api/v1/ha/heartbeat` endpoint that returns the node's health status, current role, database status, replication lag (if standby), and uptime — accessible without authentication for peer-to-peer monitoring.
2. EACH node SHALL ping its peer's heartbeat endpoint every 10 seconds.
3. THE system SHALL track the peer's health status as: healthy (last heartbeat < 30s ago), degraded (last heartbeat 30–60s ago), or unreachable (last heartbeat > 60s ago or connection refused).
4. THE system SHALL store the last 100 heartbeat results in memory for the admin dashboard to display recent health history.
5. WHEN the peer transitions from healthy to unreachable, THE system SHALL log a warning event and update the node registry.
6. WHEN the peer transitions from unreachable to healthy, THE system SHALL log an info event and update the node registry.

### Requirement 3: PostgreSQL Replication Setup

**User Story:** As a Global_Admin, I want the primary node's database changes to be automatically replicated to the standby node, so that the standby always has current data.

#### Acceptance Criteria

1. THE system SHALL use PostgreSQL logical replication to stream changes from the Primary_Node to the Standby_Node.
2. THE system SHALL provide an admin API endpoint to initialize replication: create a publication on the primary and a subscription on the standby.
3. WHEN replication is initialized, THE system SHALL perform an initial full data sync from primary to standby before streaming incremental changes.
4. THE system SHALL monitor replication lag and expose it via the heartbeat endpoint and admin API.
5. IF replication lag exceeds 60 seconds, THE system SHALL mark the Sync_Status as "lagging" and log a warning.
6. IF replication is disconnected, THE system SHALL attempt to reconnect every 30 seconds for up to 10 minutes before marking Sync_Status as "error".
7. THE system SHALL provide an admin API endpoint to check replication health: publication status, subscription status, lag, and last replicated transaction timestamp.
8. THE system SHALL provide an admin API endpoint to perform a full re-sync if replication becomes inconsistent.

### Requirement 4: Manual Failover (Promote/Demote)

**User Story:** As a Global_Admin, I want to manually promote the standby to primary and demote the primary to standby, so that I can perform rolling updates and handle planned maintenance.

#### Acceptance Criteria

1. THE system SHALL provide a `POST /api/v1/ha/promote` endpoint (global_admin only) that promotes the current standby node to primary.
2. WHEN promotion is triggered, THE system SHALL: stop the replication subscription, set the local node role to primary, and begin accepting writes.
3. THE system SHALL provide a `POST /api/v1/ha/demote` endpoint (global_admin only) that demotes the current primary node to standby.
4. WHEN demotion is triggered, THE system SHALL: set the local node role to standby, create/resume the replication subscription from the new primary, and stop accepting direct writes (read-only mode for the app).
5. BEFORE promotion, THE system SHALL verify that replication lag is under 5 seconds to prevent data loss. If lag exceeds 5 seconds, promotion SHALL require a `force: true` flag with an acknowledgment of potential data loss.
6. THE system SHALL log all promote/demote actions in the audit log with the acting user, timestamp, and reason.
7. WHEN a node is in standby role, THE system SHALL reject all write API requests with a 503 response indicating the node is in standby mode, EXCEPT for HA management endpoints and heartbeat.

### Requirement 5: Automatic Failover Detection

**User Story:** As a Global_Admin, I want the standby to automatically detect when the primary is down and alert me, so that I can decide whether to promote the standby.

#### Acceptance Criteria

1. WHEN the standby node detects the primary as unreachable for more than 90 seconds (configurable), THE system SHALL mark the primary as "presumed down".
2. WHEN the primary is presumed down, THE system SHALL NOT automatically promote the standby — it SHALL send a notification (log entry + optional webhook/email) alerting the Global_Admin.
3. THE system SHALL provide a configurable option `auto_promote_enabled` (default: false) that, when enabled, automatically promotes the standby after the primary has been unreachable for the configured timeout.
4. IF auto-promotion occurs, THE system SHALL log the event as a critical audit entry and send a notification to the Global_Admin.
5. WHEN the previously-down primary comes back online, THE system SHALL detect the peer is now a primary and NOT attempt to also run as primary — it SHALL remain in its current role and alert the admin of a split-brain condition if both nodes claim primary.

### Requirement 6: Post-Failover Re-sync

**User Story:** As a Global_Admin, I want the old primary to catch up with the new primary's data after it comes back online, so that both nodes are in sync again.

#### Acceptance Criteria

1. WHEN a demoted node (former primary) starts receiving replication from the new primary, THE system SHALL perform a differential sync to catch up on changes made while it was down.
2. IF the replication slot has been invalidated (too much WAL accumulated), THE system SHALL provide an admin endpoint to trigger a full re-sync from the current primary.
3. THE system SHALL track re-sync progress and expose it via the admin API: tables synced, rows copied, estimated time remaining.
4. DURING re-sync, THE standby node SHALL continue responding to heartbeat requests but SHALL return a Sync_Status of "resyncing".

### Requirement 7: Admin Dashboard — HA Status Panel

**User Story:** As a Global_Admin, I want to see the HA status of both nodes on the admin dashboard, so that I have full visibility into the cluster health.

#### Acceptance Criteria

1. THE Global Admin Dashboard SHALL display an "HA Cluster Status" section showing both nodes with their: name, role (primary/standby), health status (healthy/degraded/unreachable), replication sync status, replication lag, and last heartbeat timestamp.
2. THE HA Status Panel SHALL auto-refresh every 10 seconds.
3. THE HA Status Panel SHALL display a visual indicator (green/amber/red) for each node's health.
4. THE HA Status Panel SHALL show a "Promote to Primary" button next to the standby node (only when the local node is the standby).
5. THE HA Status Panel SHALL show a "Demote to Standby" button next to the primary node (only when the local node is the primary).
6. WHEN the admin clicks Promote or Demote, THE system SHALL show a confirmation dialog requiring the admin to type "CONFIRM" before proceeding.
7. THE HA Status Panel SHALL display a banner when replication is lagging (> 30s) or disconnected.
8. THE HA Status Panel SHALL display the current node's role prominently so the admin always knows which node they are connected to.

### Requirement 8: Login Page — Node Awareness

**User Story:** As a user logging in, I want to see which node I'm connected to and whether both nodes are healthy, so that I have confidence the system is available.

#### Acceptance Criteria

1. THE login page SHALL display a small, non-intrusive indicator showing the current node name and role (e.g., "Node: Pi-Main (Primary)").
2. IF the peer node is unreachable, THE login page SHALL display a subtle warning: "Backup node offline — running on single node".
3. IF the current node is a standby that has been promoted due to primary failure, THE login page SHALL display: "Running on backup node — primary node offline".
4. THE node status information SHALL be fetched from a lightweight public endpoint `GET /api/v1/ha/status` that returns only: node_name, role, peer_status (healthy/unreachable), and sync_status — no sensitive information.

### Requirement 9: Write Protection on Standby

**User Story:** As a system operator, I want the standby node to reject write operations, so that data integrity is maintained and writes only go to the primary.

#### Acceptance Criteria

1. WHEN a node's role is standby, THE system SHALL intercept all non-GET API requests (except HA endpoints and heartbeat) and return a 503 response with body `{"detail": "This node is in standby mode. Writes are only accepted on the primary node.", "node_role": "standby", "primary_endpoint": "<peer_url>"}`.
2. THE standby write protection SHALL be implemented as FastAPI middleware that checks the node role before routing to endpoint handlers.
3. THE middleware SHALL allow all requests to paths matching `/api/v1/ha/*` regardless of node role.
4. THE middleware SHALL allow all GET requests regardless of node role (standby can serve reads).

### Requirement 10: HA Configuration Persistence

**User Story:** As a Global_Admin, I want HA configuration to persist across restarts, so that I don't have to reconfigure the cluster every time a node reboots.

#### Acceptance Criteria

1. THE system SHALL store HA configuration (node_id, node_name, role, peer_endpoint, auto_promote_enabled, heartbeat_interval, failover_timeout) in the database in an `ha_config` table.
2. WHEN the application starts, THE system SHALL load HA configuration from the database and initialize the heartbeat service and replication monitoring.
3. IF no HA configuration exists at startup, THE system SHALL operate in standalone mode (no heartbeat, no replication, no write protection).
4. THE system SHALL provide admin API endpoints to create, update, and view HA configuration.
5. WHEN HA configuration is updated, THE system SHALL apply changes immediately without requiring a restart (hot-reload heartbeat interval, peer endpoint, etc.).

### Requirement 11: Security

**User Story:** As a Global_Admin, I want HA management to be secure, so that only authorized administrators can modify the cluster configuration.

#### Acceptance Criteria

1. ALL HA management endpoints (configure, promote, demote, re-sync) SHALL require the `global_admin` role.
2. THE heartbeat endpoint SHALL be accessible without authentication but SHALL NOT expose sensitive information (no database credentials, no user data, no internal IPs beyond what's necessary).
3. THE public status endpoint SHALL only expose: node_name, role, peer_status, and sync_status.
4. THE system SHALL use HMAC-signed heartbeat payloads using a shared secret configured in both nodes' environment variables, to prevent spoofed heartbeats.
5. THE shared HMAC secret SHALL be configured via the `HA_HEARTBEAT_SECRET` environment variable.

### Requirement 12: Rolling Update Support

**User Story:** As a Global_Admin, I want to perform zero-downtime updates by updating one node at a time, so that the application is always available during deployments.

#### Acceptance Criteria

1. THE admin dashboard SHALL display a "Rolling Update Guide" section in the HA panel that shows the recommended update procedure as a checklist.
2. THE system SHALL expose a `POST /api/v1/ha/maintenance-mode` endpoint that puts the current node into maintenance mode — it continues serving existing requests but returns a header `X-Node-Maintenance: true` so the admin knows to switch DNS.
3. WHEN a node is in maintenance mode, THE heartbeat response SHALL include `maintenance: true` so the peer knows.
4. THE system SHALL provide a `POST /api/v1/ha/ready` endpoint to signal that the node has been updated and is ready to resume normal operation.
