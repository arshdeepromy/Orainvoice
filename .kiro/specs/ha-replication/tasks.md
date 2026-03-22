# Implementation Plan: HA Replication

## Overview

Implement active-standby high availability for OraInvoice across two Raspberry Pi nodes. The backend is built with FastAPI + SQLAlchemy async + PostgreSQL logical replication, and the frontend with React + TypeScript. Tasks are ordered so each step builds on the previous: data models first, then core services, then API layer, then frontend, then integration wiring.

## Tasks

- [x] 1. Create HAConfig model and Alembic migration
  - [x] 1.1 Create `HAConfig` SQLAlchemy ORM model in `app/modules/ha/models.py`
    - Define the `HAConfig(Base)` model with all columns: id, node_id, node_name, role, peer_endpoint, auto_promote_enabled, heartbeat_interval_seconds, failover_timeout_seconds, maintenance_mode, last_peer_health, last_peer_heartbeat, sync_status, created_at, updated_at
    - Add check constraints on role (standalone, primary, standby) and sync_status (not_configured, initializing, healthy, lagging, disconnected, resyncing, error)
    - _Requirements: 10.1_

  - [x] 1.2 Create Alembic migration for `ha_config` table
    - Generate a new Alembic revision that creates the `ha_config` table with all columns, constraints, and indexes
    - _Requirements: 10.1_

- [x] 2. Create HA schemas and utility functions
  - [x] 2.1 Create Pydantic request/response schemas in `app/modules/ha/schemas.py`
    - Implement all schemas: `HAConfigRequest`, `HAConfigResponse`, `HeartbeatResponse`, `PublicStatusResponse`, `PromoteRequest`, `DemoteRequest`, `ReplicationStatusResponse`, `ResyncProgressResponse`, `HeartbeatHistoryEntry`, `HANodeStatusForDashboard`
    - _Requirements: 1.1, 1.5, 2.1, 4.1, 4.3, 7.1, 8.4_

  - [x] 2.2 Implement HMAC signing and verification utilities in `app/modules/ha/hmac_utils.py`
    - `compute_hmac(payload: dict, secret: str) -> str` — HMAC-SHA256 of JSON-serialized payload
    - `verify_hmac(payload: dict, signature: str, secret: str) -> bool`
    - _Requirements: 11.4, 11.5_

  - [x] 2.3 Write property test for HMAC sign/verify round-trip (P2)
    - Generate random payloads and secrets; verify compute then verify returns true; different secret returns false
    - **Validates: Requirements 11.4**

  - [x] 2.4 Write property test for peer health classification (P3)
    - Generate random timestamp deltas; verify healthy < 30s, degraded 30–60s, unreachable > 60s
    - **Validates: Requirements 2.3**

  - [x] 2.5 Write property test for confirmation text validation (P4)
    - Generate random strings; verify only exact "CONFIRM" is accepted
    - **Validates: Requirements 7.6**

  - [x] 2.6 Write property test for role state machine validity (P8)
    - Generate all role pairs; verify only valid transitions are allowed
    - **Validates: Requirements 4.1, 4.3**

  - [x] 2.7 Write property test for public status response field safety (P7)
    - Generate status responses; verify only node_name, role, peer_status, sync_status are present
    - **Validates: Requirements 8.4, 11.3**

- [x] 3. Checkpoint — Ensure all schema and utility tests pass

- [x] 4. Implement Heartbeat Service
  - [x] 4.1 Create `HeartbeatService` class in `app/modules/ha/heartbeat.py`
    - Implement `__init__(peer_endpoint, interval, secret)` with `deque(maxlen=100)` for history
    - Implement `start()` / `stop()` to manage the background asyncio task
    - Implement `_ping_loop()` — every `interval` seconds, call `_ping_peer()` and update peer health
    - Implement `_ping_peer()` — HTTP GET to peer's heartbeat endpoint with 5s timeout, verify HMAC, return `HeartbeatHistoryEntry`
    - Implement `get_peer_health()` — classify based on last heartbeat timestamp (healthy/degraded/unreachable)
    - Implement `get_history()` — return list from deque
    - Handle peer health transitions: log warning on healthy→unreachable, log info on unreachable→healthy
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [x] 4.2 Write property test for heartbeat history bounded size (P10)
    - Generate sequences of 100+ heartbeat entries; verify deque never exceeds 100
    - **Validates: Requirements 2.4**

  - [x] 4.3 Write property test for auto-promote gating (P11)
    - Generate states with auto_promote_enabled=false; verify no auto-promotion regardless of timeout
    - **Validates: Requirements 5.3**

- [x] 5. Implement Replication Manager
  - [x] 5.1 Create `ReplicationManager` class in `app/modules/ha/replication.py`
    - Implement `init_primary(db)` — execute `CREATE PUBLICATION orainvoice_ha_pub FOR ALL TABLES`
    - Implement `init_standby(db, primary_conn_str)` — execute `CREATE SUBSCRIPTION orainvoice_ha_sub CONNECTION '...' PUBLICATION orainvoice_ha_pub`
    - Implement `get_replication_status(db)` — query `pg_stat_subscription` and `pg_replication_slots`
    - Implement `get_replication_lag(db)` — query subscription lag from `pg_stat_subscription`
    - Implement `stop_subscription(db)` — `ALTER SUBSCRIPTION orainvoice_ha_sub DISABLE`
    - Implement `resume_subscription(db, primary_conn_str)` — `ALTER SUBSCRIPTION orainvoice_ha_sub ENABLE` or re-create if slot invalidated
    - Implement `trigger_resync(db, primary_conn_str)` — drop and re-create subscription with `copy_data=true`
    - Implement `drop_publication(db)` and `drop_subscription(db)` for cleanup
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 6.1, 6.2_

- [x] 6. Implement Standby Write Protection Middleware
  - [x] 6.1 Create `StandbyWriteProtectionMiddleware` in `app/modules/ha/middleware.py`
    - Check node role from cached HA config (Redis or in-memory)
    - If role is "standby" and method is not GET/HEAD/OPTIONS and path does not start with `/api/v1/ha/`, return 503 with standby message including peer_endpoint
    - Allow all requests when role is "primary" or "standalone"
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [x] 6.2 Write property test for standby write protection (P6)
    - Generate combinations of (method, path, role); verify 503 only for non-GET on standby for non-HA paths
    - **Validates: Requirements 9.1, 9.3, 9.4**

- [x] 7. Checkpoint — Ensure all service tests pass

- [x] 8. Implement HA Service
  - [x] 8.1 Create `HAService` in `app/modules/ha/service.py`
    - Implement `get_config(db)` — load HAConfig from database, return None if not configured
    - Implement `save_config(db, config, user_id)` — upsert HAConfig, log audit event, hot-reload heartbeat service
    - Implement `get_identity(db)` — return full node identity and config
    - Implement `promote(db, user_id, reason, force)` — validate current role is standby, check replication lag (< 5s or force=true), stop subscription, update role to primary, log audit
    - Implement `demote(db, user_id, reason)` — validate current role is primary, update role to standby, create/resume subscription, log audit
    - Implement `get_cluster_status(db)` — return local node status + peer status from heartbeat service
    - Implement `enter_maintenance_mode(db, user_id)` / `exit_maintenance_mode(db, user_id)`
    - _Requirements: 1.1, 1.2, 1.5, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 5.1, 5.2, 5.3, 5.4, 5.5, 10.1, 10.2, 10.3, 10.4, 10.5, 12.2, 12.3, 12.4_

  - [x] 8.2 Write property test for RBAC enforcement (P1)
    - Generate random roles; verify only global_admin passes, all others get 403
    - **Validates: Requirements 1.2, 11.1**

  - [x] 8.3 Write property test for promotion lag threshold (P5)
    - Generate lag values and force flags; verify promotion blocked when lag > 5s and force=false
    - **Validates: Requirements 4.5**

  - [x] 8.4 Write property test for HA config persistence round-trip (P9)
    - Generate valid configs; verify save then load returns identical values
    - **Validates: Requirements 10.1**

  - [x] 8.5 Write property test for split-brain detection (P12)
    - Generate states where both nodes report primary; verify alert is raised
    - **Validates: Requirements 5.5**

- [x] 9. Implement HA Router and wire to app
  - [x] 9.1 Create `ha_router` in `app/modules/ha/router.py`
    - Define all endpoints per the design: heartbeat (public), status (public), identity (admin), configure (admin), promote (admin), demote (admin), replication/init (admin), replication/status (admin), replication/resync (admin), maintenance-mode (admin), ready (admin), history (admin)
    - _Requirements: 1.2, 1.5, 2.1, 4.1, 4.3, 7.1, 8.4, 11.1_

  - [x] 9.2 Mount HA router on the main app and register the standby middleware
    - Include `ha_router` with prefix `/api/v1/ha` in `app/main.py` or the appropriate app setup
    - Add `StandbyWriteProtectionMiddleware` to the FastAPI app
    - Initialize heartbeat service on startup if HA config exists
    - _Requirements: 9.2, 10.2_

  - [x] 9.3 Add `HA_HEARTBEAT_SECRET` and `HA_PEER_DB_URL` to `.env.example` and `.env.pi`
    - Document the new environment variables
    - _Requirements: 11.5_

  - [x] 9.4 Write backend unit tests in `tests/test_ha_replication.py`
    - Test config CRUD (create, read, update)
    - Test promote happy path (standby → primary)
    - Test promote blocked when already primary
    - Test promote blocked when lag > 5s without force
    - Test demote happy path (primary → standby)
    - Test demote blocked when already standby
    - Test heartbeat endpoint returns correct structure
    - Test public status endpoint returns only safe fields
    - Test standby middleware blocks writes
    - Test standby middleware allows GET and HA paths
    - Test HMAC verification success and failure
    - _Requirements: 1.2, 2.1, 4.1, 4.3, 4.5, 8.4, 9.1, 11.1, 11.4_

- [x] 10. Checkpoint — Ensure all backend tests pass

- [x] 11. Implement frontend HA Status Panel
  - [x] 11.1 Create `HAStatusPanel` component in `frontend/src/components/ha/HAStatusPanel.tsx`
    - Fetch cluster status from `GET /api/v1/ha/identity` and peer info from heartbeat history
    - Display both nodes: name, role badge (Primary/Standby), health indicator (green/amber/red), sync status, replication lag, last heartbeat
    - Auto-refresh every 10 seconds
    - Show "Promote to Primary" button when local node is standby
    - Show "Demote to Standby" button when local node is primary
    - Confirmation dialog requiring "CONFIRM" text for promote/demote
    - Banner when replication is lagging (> 30s) or disconnected
    - Display current node role prominently
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8_

  - [x] 11.2 Create `NodeStatusIndicator` component in `frontend/src/components/ha/NodeStatusIndicator.tsx`
    - Fetch from `GET /api/v1/ha/status` (public endpoint)
    - Display small indicator: node name and role
    - Show warning if peer is unreachable
    - Show notice if running on backup node
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [x] 11.3 Add `HAStatusPanel` to the Global Admin Dashboard
    - Import and render `HAStatusPanel` in `GlobalAdminDashboard.tsx` as a new section
    - Only show when HA is configured (check via API, gracefully hide if 404)
    - _Requirements: 7.1_

  - [x] 11.4 Add `NodeStatusIndicator` to the login page
    - Import and render `NodeStatusIndicator` in the login page component
    - Position as a small, non-intrusive indicator
    - _Requirements: 8.1_

- [x] 12. Checkpoint — Ensure frontend builds without errors

- [x] 13. Write frontend tests
  - [x] 13.1 Write frontend unit tests in `frontend/src/components/ha/__tests__/ha-status.test.tsx`
    - Test HAStatusPanel renders both nodes
    - Test promote button visible only when local node is standby
    - Test demote button visible only when local node is primary
    - Test confirmation dialog requires "CONFIRM" text
    - Test health indicator colors (green/amber/red)
    - Test replication lag warning banner
    - Test auto-refresh polling
    - _Requirements: 7.1, 7.4, 7.5, 7.6, 7.7_

  - [x] 13.2 Write frontend unit tests for NodeStatusIndicator
    - Test displays node name and role
    - Test shows warning when peer unreachable
    - Test shows backup node notice
    - Test gracefully handles HA not configured (no indicator shown)
    - _Requirements: 8.1, 8.2, 8.3_

  - [x] 13.3 Write frontend property tests in `frontend/src/components/ha/__tests__/ha-status.properties.test.ts`
    - Promote/demote button visibility based on role
    - Health indicator color based on status string
    - Replication lag warning visibility based on lag value
    - **Validates: Requirements 7.3, 7.4, 7.5, 7.7**

- [x] 14. Update deployment steering and documentation
  - [x] 14.1 Update `.kiro/steering/deployment-environments.md` to include HA setup instructions
    - Document the two-node architecture
    - Document environment variables (HA_HEARTBEAT_SECRET, HA_PEER_DB_URL)
    - Document the rolling update procedure using promote/demote
    - Document initial setup steps: configure primary, configure standby, init replication
    - _Requirements: 12.1_

  - [x] 14.2 Create `docker-compose.pi-standby.yml` override for the standby node
    - Same as `docker-compose.pi.yml` but with PostgreSQL configured for logical replication subscriber
    - Add `wal_level=logical` to PostgreSQL command args on both primary and standby compose files
    - _Requirements: 3.1_

- [x] 15. Final checkpoint — Ensure all tests pass

## Notes

- DNS/NPM routing is managed manually by the admin — the app does NOT handle traffic routing
- The remote Pi already has rclone and other containers — this feature is fully isolated in its own Docker containers and does not touch existing services
- PostgreSQL logical replication requires `wal_level=logical` on the primary — this needs to be added to `docker-compose.pi.yml`
- The `ha_config` table is local to each node (not replicated) so each node maintains its own identity
- Property tests validate universal correctness properties from the design document (P1–P12)
- Each task references specific requirements for traceability
