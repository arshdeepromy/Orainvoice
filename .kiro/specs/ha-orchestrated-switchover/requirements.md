# Requirements Document

## Introduction

OraInvoice runs in a two-node High-Availability (HA) cluster using PostgreSQL **logical** replication. One node holds the `primary` role (accepts writes), the other holds the `standby` role (read-only, subscribes to the primary's publication). A Global-Admin "HA Replication" page exposes a **Promote to Primary** button.

Today, "Promote to Primary" mutates ONLY the local node: it validates the local role, checks replication lag, stops the local subscription, sets the local role to `primary`, and stamps `promoted_at`. It never contacts the peer. Demoting the old primary and re-pointing replication are separate manual steps performed on the other node. Between those steps both nodes consider themselves `primary` — a split-brain window with a real risk of divergent writes and data loss.

This feature adds a **single-click orchestrated switchover**. When the admin clicks "Promote to Primary" on the standby and the current primary is reachable, the system performs a coordinated, no-data-loss role swap across both nodes as one operation: quiesce the old primary, drain replication to zero lag, demote the old primary remotely, promote the local node, and automatically re-point the old primary's subscription at the new primary so replication resumes in the reversed direction. If the current primary is not reachable, the system falls back to the existing standalone promote behaviour (lag/force guard plus split-brain detection).

The orchestrated path is **additive**. The existing manual promote, demote, and demote-and-sync actions remain available as fallbacks. The orchestrated path is exposed through a new endpoint (e.g. `POST /api/v1/ha/switchover`) and a new progress UI on the existing HA Replication page.

## Glossary

- **Switchover_Orchestrator**: The backend component that drives the multi-phase orchestrated role swap. Runs on the standby node that initiated the switchover; it becomes the new primary.
- **Local_Node**: The node on which the admin clicked "Promote to Primary". It is currently `standby` and intends to become `primary`. The Switchover_Orchestrator runs here.
- **Old_Primary**: The peer node that is currently `primary` and is the target of the remote demote.
- **Peer_RPC_Client**: The authenticated cross-node HTTP client (the existing wizard pattern: authenticate to the peer to obtain a JWT, then call peer HA endpoints over httpx).
- **Heartbeat_Service**: The existing background service that pings the peer's `/api/v1/ha/heartbeat` endpoint and exposes peer reachability, `peer_role`, and replication lag.
- **Replication_Lag**: Seconds the standby is behind the primary, measured from PostgreSQL replication state.
- **Drain**: Waiting until Replication_Lag reaches zero (standby fully caught up) before any role change, guaranteeing no committed write on the Old_Primary is lost.
- **Quiesce**: Putting the Old_Primary into a state where it rejects writes (existing maintenance-mode toggle + write-blocking middleware) so no new writes occur during the switchover.
- **HA_Config**: The single-row configuration table storing each node's role, `peer_endpoint`, peer DB connection info, `promoted_at`, and HMAC secret.
- **Switchover_Phase**: A named, ordered step in the orchestration (e.g. `verify_primary`, `quiesce`, `drain`, `demote_remote`, `promote_local`, `repoint_subscription`, `verify_cluster`).
- **Switchover_Progress**: The ordered list of Switchover_Phase results (status + message + timestamp) reported to the admin UI. Held in a **process-shared Progress_Store** so it is observable regardless of which worker runs or serves it.
- **Switchover_Id**: An identifier minted when a switchover is accepted, used by the admin UI to poll the live Switchover_Progress and the final outcome.
- **Progress_Store**: The shared, cross-process store (Redis, mirroring the existing HA lock channel) that holds the current Switchover_Progress and final outcome keyed by Switchover_Id. It is the authoritative source of switchover state, not the initiating HTTP response.
- **Rollback**: Restoring the cluster to a consistent single-primary state after a mid-orchestration failure, preferably by re-promoting the Old_Primary.
- **Split_Brain**: A condition where both nodes hold the `primary` role simultaneously.
- **Zero_Primary**: A condition where neither node holds the `primary` role.
- **Drain_Timeout**: The configurable maximum number of seconds the Switchover_Orchestrator waits for Replication_Lag to reach zero before aborting the switchover.
- **Confirmation_Text**: The exact string `CONFIRM` the admin must type to authorise the switchover.
- **Global_Admin**: The platform-level role required for all HA management operations.

## Requirements

### Requirement 1: Initiate orchestrated switchover from the standby

**User Story:** As a Global Admin, I want a single "Promote to Primary" action on the standby to perform a full coordinated role swap when the current primary is reachable, so that I do not have to run separate manual steps on each node and risk split-brain.

#### Acceptance Criteria

1. WHEN a Global_Admin submits a switchover request on the Local_Node, THE Switchover_Orchestrator SHALL verify that the Local_Node role is `standby` before performing any other phase.
2. IF the Local_Node role is not `standby`, THEN THE Switchover_Orchestrator SHALL reject the request with an error identifying the current role and SHALL make no role change.
3. WHEN a switchover request is submitted, THE Switchover_Orchestrator SHALL require the Confirmation_Text to equal `CONFIRM` before performing any phase.
4. IF the Confirmation_Text does not equal `CONFIRM`, THEN THE Switchover_Orchestrator SHALL reject the request and SHALL make no role change.
5. WHEN a switchover request is submitted, THE Switchover_Orchestrator SHALL require a non-empty reason string and SHALL record the reason in the audit log.
6. WHILE HA is not configured on the Local_Node, THE Switchover_Orchestrator SHALL reject the switchover request with an error stating that HA is not configured.

### Requirement 2: Verify the current primary before switching

**User Story:** As a Global Admin, I want the system to confirm the peer is genuinely the reachable primary before swapping roles, so that the orchestrated path only runs when it is safe to coordinate both nodes.

#### Acceptance Criteria

1. WHEN the switchover begins, THE Switchover_Orchestrator SHALL determine peer reachability using the Heartbeat_Service and a direct authenticated probe of the Old_Primary.
2. WHEN the Old_Primary is reachable, THE Switchover_Orchestrator SHALL confirm that the Old_Primary reports its role as `primary` before proceeding.
3. IF the Old_Primary is reachable but reports a role other than `primary`, THEN THE Switchover_Orchestrator SHALL abort the orchestrated path, SHALL make no role change, and SHALL return an error describing the unexpected peer role.
4. WHEN the Old_Primary is reachable over the management API but its database is not reachable from the Local_Node, THE Switchover_Orchestrator SHALL abort before the quiesce phase and SHALL return an error stating that the peer database is unreachable.
5. WHEN the Switchover_Orchestrator authenticates to the Old_Primary, THE Switchover_Orchestrator SHALL use the existing authenticated Peer_RPC_Client pattern with Global_Admin credentials.

### Requirement 3: Unreachable-primary fallback

**User Story:** As a Global Admin, I want the standby to fall back to standalone promotion when the primary is unreachable, so that I can still recover the cluster during a real primary outage.

#### Acceptance Criteria

1. IF the Old_Primary is unreachable when the switchover begins, THEN THE Switchover_Orchestrator SHALL fall back to the existing standalone promote behaviour on the Local_Node.
2. WHEN the standalone fallback runs, THE Switchover_Orchestrator SHALL apply the existing lag guard, allowing promotion only when Replication_Lag is at or below 5 seconds or when the force flag is set.
3. IF the standalone fallback is requested with Replication_Lag above 5 seconds and the force flag is not set, THEN THE Switchover_Orchestrator SHALL reject the promotion and SHALL report the measured lag.
4. WHEN the standalone fallback completes promotion, THE Switchover_Orchestrator SHALL set the Local_Node role to `primary` and SHALL stamp `promoted_at`.
5. WHEN the standalone fallback completes, THE Switchover_Orchestrator SHALL report to the admin that the peer was unreachable and that the old primary must be demoted and re-pointed manually once it returns.

### Requirement 4: Quiesce the old primary

**User Story:** As a Global Admin, I want the old primary to stop accepting writes before the role swap, so that no new writes are lost or create divergence during the switchover.

#### Acceptance Criteria

1. WHEN verification of the Old_Primary succeeds, THE Switchover_Orchestrator SHALL instruct the Old_Primary to enter maintenance mode so it rejects write requests.
2. WHEN the Old_Primary has entered maintenance mode, THE Switchover_Orchestrator SHALL confirm the quiesced state before starting the drain phase.
3. IF the Old_Primary cannot be quiesced, THEN THE Switchover_Orchestrator SHALL abort the switchover and SHALL leave the Old_Primary as `primary` without any further role change.
4. WHILE the Old_Primary is quiesced, THE Old_Primary SHALL continue to serve read requests and HA management endpoints.

### Requirement 5: Drain replication to zero lag (no data loss)

**User Story:** As a Global Admin, I want the standby to fully catch up to the old primary before any role change, so that the switchover loses no committed data.

#### Acceptance Criteria

1. WHEN the Old_Primary is quiesced, THE Switchover_Orchestrator SHALL wait until Replication_Lag on the Local_Node reaches zero before demoting the Old_Primary.
2. THE Switchover_Orchestrator SHALL enforce a configurable Drain_Timeout for the drain phase.
3. IF Replication_Lag does not reach zero within the Drain_Timeout, THEN THE Switchover_Orchestrator SHALL abort the switchover and SHALL roll back the quiesce so the Old_Primary resumes accepting writes as `primary`.
4. WHILE draining, THE Switchover_Orchestrator SHALL report the current Replication_Lag value to the admin progress view.
5. WHEN Replication_Lag reaches zero within the Drain_Timeout, THE Switchover_Orchestrator SHALL proceed to demote the Old_Primary.
6. THE Switchover_Orchestrator SHALL treat the drain phase as the data-safety gate, performing no remote demotion before the drain confirms zero lag.

### Requirement 6: Demote the old primary remotely

**User Story:** As a Global Admin, I want the old primary demoted automatically as part of the switchover, so that the cluster never has two primaries.

#### Acceptance Criteria

1. WHEN the drain phase confirms zero Replication_Lag, THE Switchover_Orchestrator SHALL instruct the Old_Primary to demote itself to `standby`.
2. WHEN the Old_Primary demotes, THE Old_Primary SHALL drop its publication as part of the demotion.
3. WHEN the remote demotion completes, THE Switchover_Orchestrator SHALL confirm that the Old_Primary reports its role as `standby` before promoting the Local_Node.
4. IF the remote demotion fails, THEN THE Switchover_Orchestrator SHALL abort before promoting the Local_Node and SHALL roll back the quiesce so the Old_Primary remains the single `primary`.
5. IF the Switchover_Orchestrator cannot confirm the Old_Primary reached `standby` after the demote call, THEN THE Switchover_Orchestrator SHALL abort the promotion of the Local_Node and SHALL enter the Rollback procedure.

### Requirement 7: Promote the local node

**User Story:** As a Global Admin, I want the local node promoted to primary only after the old primary is confirmed demoted, so that exactly one primary exists at all times.

#### Acceptance Criteria

1. WHEN the Old_Primary is confirmed `standby`, THE Switchover_Orchestrator SHALL promote the Local_Node to `primary`.
2. WHEN the Local_Node is promoted, THE Switchover_Orchestrator SHALL stop the Local_Node subscription, set the Local_Node role to `primary`, and stamp `promoted_at`.
3. WHEN the Local_Node is promoted, THE Switchover_Orchestrator SHALL create the publication on the Local_Node so the demoted Old_Primary can subscribe to it.
4. WHEN the Local_Node is promoted, THE Switchover_Orchestrator SHALL synchronise sequence values on the Local_Node so new inserts do not collide with replicated rows.
5. IF promotion of the Local_Node fails after the Old_Primary has been demoted, THEN THE Switchover_Orchestrator SHALL enter the Rollback procedure to restore a single-primary cluster.

### Requirement 8: Re-point the old primary's subscription automatically

**User Story:** As a Global Admin, I want the old primary to start replicating from the new primary automatically, so that I do not have to manually re-initialise replication after a switchover.

#### Acceptance Criteria

1. WHEN the Local_Node has become `primary`, THE Switchover_Orchestrator SHALL instruct the Old_Primary to create a subscription pointing at the Local_Node as the new publisher.
2. WHEN re-pointing the Old_Primary subscription, THE Switchover_Orchestrator SHALL use the peer database connection information already stored in HA_Config without requiring the admin to enter connection details.
3. WHEN the re-point completes, THE Switchover_Orchestrator SHALL confirm that the Old_Primary subscription is active and replicating from the Local_Node.
4. IF the re-point fails, THEN THE Switchover_Orchestrator SHALL report the switchover as completed-with-warning, identifying that the new primary is active but the old primary is not yet subscribed, and SHALL provide the manual remediation step.
5. WHEN re-point succeeds, THE Switchover_Orchestrator SHALL take the Old_Primary out of maintenance mode so it operates as a healthy read-only standby.
6. WHEN re-pointing the Old_Primary, THE Switchover_Orchestrator SHALL create the reversed subscription **without copying initial table data and without truncating the Old_Primary's tables**, because the Drain phase already guaranteed the two nodes hold identical committed data; a full truncate-and-resync SHALL NOT be used on the orchestrated path.

### Requirement 9: Final cluster verification

**User Story:** As a Global Admin, I want the switchover to confirm a healthy reversed cluster at the end, so that I know the operation truly succeeded.

#### Acceptance Criteria

1. WHEN all preceding phases complete, THE Switchover_Orchestrator SHALL verify that exactly one node holds the `primary` role.
2. WHEN final verification runs, THE Switchover_Orchestrator SHALL verify that the Local_Node is `primary` and the Old_Primary is `standby`.
3. IF final verification detects two primaries, THEN THE Switchover_Orchestrator SHALL report a critical split-brain outcome and SHALL surface the existing split-brain resolution guidance.
4. IF final verification detects zero primaries, THEN THE Switchover_Orchestrator SHALL report a critical zero-primary outcome and SHALL enter the Rollback procedure to restore a single `primary`.
5. WHEN final verification confirms one `primary` and one `standby`, THE Switchover_Orchestrator SHALL report the switchover as succeeded.

### Requirement 10: Single-primary safety invariant

**User Story:** As a Global Admin, I want a hard guarantee that the cluster never ends a switchover with zero primaries or two primaries, so that production never enters an unrecoverable or divergent state.

#### Acceptance Criteria

1. WHEN any switchover terminates with a success outcome, THE Switchover_Orchestrator SHALL leave exactly one node as `primary`.
2. WHEN any switchover terminates with a rolled-back outcome, THE Switchover_Orchestrator SHALL leave exactly one node as `primary`.
3. THE Switchover_Orchestrator SHALL never report success WHILE both nodes hold the `primary` role.
4. THE Switchover_Orchestrator SHALL never report success WHILE neither node holds the `primary` role.
5. IF the Switchover_Orchestrator cannot restore a single-primary state during Rollback, THEN THE Switchover_Orchestrator SHALL report a critical manual-intervention-required outcome that names which node currently holds each role.

### Requirement 11: Rollback on mid-orchestration failure

**User Story:** As a Global Admin, I want any failure after the old primary is quiesced or demoted to roll back to a consistent state, so that a partial switchover does not break the cluster.

#### Acceptance Criteria

1. IF a phase fails after the Old_Primary is quiesced but before it is demoted, THEN THE Switchover_Orchestrator SHALL take the Old_Primary out of maintenance mode so it resumes as the single `primary`.
2. IF a phase fails after the Old_Primary is demoted but before the Local_Node is promoted, THEN THE Switchover_Orchestrator SHALL re-promote the Old_Primary to `primary` and SHALL leave the Local_Node as `standby`.
3. WHEN Rollback re-promotes the Old_Primary, THE Switchover_Orchestrator SHALL confirm the Old_Primary reports the `primary` role before reporting the Rollback as complete.
4. WHEN Rollback completes, THE Switchover_Orchestrator SHALL report a failed-but-rolled-back outcome that identifies the phase that failed.
5. IF Rollback itself fails to contact the Old_Primary, THEN THE Switchover_Orchestrator SHALL report a critical manual-intervention-required outcome describing the last known role of each node.

### Requirement 12: Idempotency and concurrency control

**User Story:** As a Global Admin, I want double-clicks and concurrent switchover requests to be rejected safely, so that overlapping operations cannot corrupt cluster state.

#### Acceptance Criteria

1. WHILE a switchover is in progress on the Local_Node, THE Switchover_Orchestrator SHALL reject any new switchover request with a conflict response indicating an operation is already running.
2. WHEN two switchover requests are submitted concurrently, THE Switchover_Orchestrator SHALL allow at most one to proceed and SHALL reject the other.
3. IF a switchover request arrives while the Local_Node is already `primary`, THEN THE Switchover_Orchestrator SHALL reject the request as a no-op and SHALL report that the node is already primary.
4. WHEN a switchover finishes, THE Switchover_Orchestrator SHALL release the in-progress lock so a future switchover can run.
5. WHERE a distributed lock service is available, THE Switchover_Orchestrator SHALL acquire a cluster-scoped lock before starting and SHALL release it when the switchover terminates.

### Requirement 13: Network-partition and peer-state edge cases

**User Story:** As a Global Admin, I want partial-connectivity scenarios handled explicitly, so that ambiguous network states do not trigger a divergent role swap.

#### Acceptance Criteria

1. IF the Old_Primary management API is reachable but the peer database is unreachable, THEN THE Switchover_Orchestrator SHALL abort before quiescing and SHALL report the database as the blocking dependency.
2. IF connectivity to the Old_Primary is lost after quiesce but before demote, THEN THE Switchover_Orchestrator SHALL abort and SHALL attempt to un-quiesce the Old_Primary, reporting whether the un-quiesce succeeded.
3. IF connectivity to the Old_Primary is lost after demote but before re-point, THEN THE Switchover_Orchestrator SHALL complete the Local_Node promotion and SHALL report the switchover as completed-with-warning, instructing the admin to re-point the old primary manually when it returns.
4. WHEN the Heartbeat_Service reports the peer as `degraded` rather than `unreachable` at switchover start, THE Switchover_Orchestrator SHALL perform the direct authenticated probe before choosing the orchestrated or fallback path.
5. IF the direct authenticated probe to the Old_Primary fails while the Heartbeat_Service still reports the peer reachable, THEN THE Switchover_Orchestrator SHALL treat the Old_Primary as unreachable and SHALL use the unreachable-primary fallback path.

### Requirement 14: Progress visibility and outcome reporting

**User Story:** As a Global Admin, I want to see each switchover phase progress and a clear final outcome, so that I understand exactly what happened during a production failover.

#### Acceptance Criteria

1. WHEN a switchover runs, THE Switchover_Orchestrator SHALL expose ordered Switchover_Progress entries, each with a phase name, status, and message.
2. WHILE a switchover is in progress, THE HA Replication page SHALL display the current phase and its status to the Global_Admin.
3. WHEN a switchover terminates, THE HA Replication page SHALL display a final outcome of succeeded, failed-but-rolled-back, completed-with-warning, or manual-intervention-required.
4. WHEN a phase fails, THE Switchover_Progress SHALL include the phase that failed and a human-readable error message.
5. BEFORE a switchover starts, THE HA Replication page SHALL require the Global_Admin to type the Confirmation_Text `CONFIRM`.
6. WHEN the orchestrated path is unavailable because the peer is unreachable, THE HA Replication page SHALL inform the Global_Admin that the standalone fallback will be used before the operation proceeds.
7. THE Switchover_Progress and the final outcome SHALL be retrievable from the Local_Node independently of which application worker process executed the switchover, so that progress polling returns the live state even when the node serves requests across multiple workers.
8. THE Switchover_Progress and the final outcome SHALL remain retrievable after the request that initiated the switchover has returned or its connection has been dropped, so that a long-running switchover is never lost to a client or proxy timeout.

### Requirement 15: Audit and HA event logging

**User Story:** As a Global Admin, I want every switchover phase and outcome recorded in the audit and HA event logs, so that I can review failover history and diagnose incidents.

#### Acceptance Criteria

1. WHEN a switchover starts, THE Switchover_Orchestrator SHALL write an audit log entry recording the initiating Global_Admin, the reason, and the start time.
2. WHEN each Switchover_Phase completes or fails, THE Switchover_Orchestrator SHALL write an HA event log entry recording the phase name, severity, and message.
3. WHEN a switchover terminates, THE Switchover_Orchestrator SHALL write an audit log entry recording the final outcome.
4. WHEN Rollback runs, THE Switchover_Orchestrator SHALL record an HA event log entry describing the Rollback actions and their result.
5. WHERE a switchover ends in a split-brain or zero-primary outcome, THE Switchover_Orchestrator SHALL record the event at critical severity.

### Requirement 16: Authorisation

**User Story:** As a platform operator, I want only Global Admins to trigger switchovers, so that this production-critical operation is restricted to authorised users.

#### Acceptance Criteria

1. THE switchover endpoint SHALL require the Global_Admin role.
2. IF a request to the switchover endpoint is made by a user without the Global_Admin role, THEN THE switchover endpoint SHALL reject the request with a forbidden response and SHALL make no role change.
3. WHEN the Switchover_Orchestrator authenticates to the Old_Primary, THE Switchover_Orchestrator SHALL present Global_Admin credentials that the Old_Primary independently authorises.

### Requirement 17: Preserve existing manual actions

**User Story:** As a Global Admin, I want the existing manual promote, demote, and demote-and-sync actions to keep working, so that I retain manual control and recovery options.

#### Acceptance Criteria

1. THE feature SHALL add the orchestrated switchover as a new operation without removing the existing manual promote action.
2. THE feature SHALL retain the existing manual demote and demote-and-sync actions.
3. WHEN the orchestrated switchover is unavailable, THE HA Replication page SHALL still allow the Global_Admin to run the existing manual actions.
4. THE feature SHALL retain the existing split-brain detection and resolution guidance for use when a switchover ends in a split-brain outcome.
