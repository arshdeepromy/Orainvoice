# Implementation Plan: HA Orchestrated Switchover

## Overview

This plan implements the single-click orchestrated switchover as a **purely additive** layer on `app/modules/ha/`. The existing `promote`, `demote`, and `demote-and-sync` endpoints and their `HAService` methods are reused and preserved unchanged.

Implementation language is **Python 3.11 / FastAPI** for the backend and **TypeScript / React (frontend-v2)** for the UI, matching the design.

Sequencing is deliberate: the schema/migration, the **pure decision functions** in `switchover_logic.py`, and their Hypothesis property tests come first so the safety-critical decisions are validated before any async orchestration exists. Then `PeerHAClient`, then the orchestrator phases, then the router endpoints + concurrency lock, then the frontend, and finally integration/rehearsal tasks (marked optional where they need real hardware).

Conventions:
- Backend tests run via `docker compose exec -T app python -m pytest <path>`.
- Frontend checks run from `frontend-v2/` via `npx vitest --run` and `npx tsc --noEmit`.
- Property-based tests use Hypothesis, ≥100 examples each, tagged `Feature: ha-orchestrated-switchover, Property N`.
- Tasks marked with `*` are optional (tests / live-hardware) and may be skipped for a faster path; core implementation tasks are never optional.

## Tasks

- [ ] 1. Additive HAConfig credential columns, schema flags, and idempotent migration
  - [ ] 1.1 Add `peer_admin_email` and `peer_admin_password` columns to the HAConfig model
    - Add two nullable **`LargeBinary`** columns to the `HAConfig` ORM model in `app/modules/ha/models.py` — NOT `text`. `envelope_encrypt` returns **bytes**, and the columns this mirrors (`peer_db_password` `models.py:71`, `heartbeat_secret` `models.py:81`) are `LargeBinary`. Encrypt both values with `envelope_encrypt` and decrypt with `envelope_decrypt_str` exactly like `peer_db_password`
    - Do NOT alter or remove any existing column
    - _Requirements: 2.5, 16.3_

  - [ ] 1.2 Wire credential storage and the `peer_admin_configured` flag into schemas and save_config
    - In `app/modules/ha/schemas.py`, accept optional `peer_admin_email` / `peer_admin_password` on the config-save input and add `peer_admin_configured: bool` to `HAConfigResponse` (mirroring `peer_db_configured`); never return the plaintext credential
    - In `app/modules/ha/service.py`, extend `HAService.save_config` to envelope-encrypt and persist the new credentials when provided, and derive `peer_admin_configured`
    - Preserve all existing `save_config` behaviour and fields
    - _Requirements: 2.5, 16.3_

  - [ ] 1.3 Create an idempotent Alembic migration chaining from head 0217
    - New revision `0218` with `down_revision = "0217"` in `alembic/versions/` (0217 is the confirmed current head: `alembic heads` → `0217`)
    - Use `ADD COLUMN IF NOT EXISTS … bytea` for both columns (matching the `LargeBinary` ORM type); `downgrade` drops them with `IF EXISTS`
    - _Requirements: 2.5_

  - [ ]* 1.4 Write unit tests for credential storage and config response
    - Assert credentials are stored encrypted, never returned in plaintext, and `peer_admin_configured` is true only when both are set
    - Assert existing `HAConfigResponse` fields are unchanged
    - _Requirements: 2.5, 16.3_

- [ ] 2. Pure decision functions in switchover_logic.py (the testable heart)
  - [ ] 2.1 Define phase order, data models, and `choose_path`
    - Create `app/modules/ha/switchover_logic.py` with `PHASE_ORDER`, frozen `ClusterObservation`, and `choose_path(obs) -> 'orchestrated' | 'fallback' | 'abort:<reason>'` per the decision table (bad_local_role, fallback on API-unreachable or failed-probe, peer_db_unreachable, peer_not_primary, else orchestrated)
    - No I/O in this module
    - _Requirements: 1.1, 1.2, 2.1, 2.2, 2.3, 2.4, 3.1, 13.1, 13.4, 13.5_

  - [ ]* 2.2 Write property test for path selection
    - **Property 1: Path selection is correct for any cluster observation**
    - **Validates: Requirements 1.1, 1.2, 2.1, 2.2, 2.3, 2.4, 3.1, 13.1, 13.4, 13.5**
    - Hypothesis strategy over roles, reachability booleans, and heartbeat health; ≥100 examples; tag `Feature: ha-orchestrated-switchover, Property 1`

  - [ ] 2.3 Implement the drain gate and phase progression helpers
    - Add `is_drain_complete(lag_seconds) -> bool` (True only when `lag == 0.0`, False for `None`) and `next_phase(completed) -> str | None`
    - _Requirements: 4.2, 5.1, 5.5, 5.6, 6.3, 7.1, 14.1_

  - [ ]* 2.4 Write property test for the drain gate / phase ordering
    - **Property 2: The drain gate is the data-safety boundary**
    - **Validates: Requirements 4.2, 5.1, 5.5, 5.6, 6.3, 7.1, 14.1**
    - Simulate executions as prefixes of `PHASE_ORDER`; assert `demote_remote` and later phases only follow a zero-lag drain; ≥100 examples; tag `Feature: ha-orchestrated-switchover, Property 2`

  - [ ] 2.5 Implement rollback-action mapping
    - Add `rollback_action(failed_phase) -> str` mapping per the rollback state machine (quiesce/drain/demote_remote → `unquiesce_peer`; promote_local & zero_primary → `repromote_peer`; post-demote connectivity loss → `complete_with_warning`)
    - _Requirements: 4.3, 5.3, 6.4, 6.5, 7.5, 11.1, 11.2, 13.2_

  - [ ]* 2.6 Write property test for rollback decisions
    - **Property 3: Rollback decisions restore a single primary per phase**
    - **Validates: Requirements 4.3, 5.3, 6.4, 6.5, 7.5, 11.1, 11.2, 13.2**
    - ≥100 examples over all phases; tag `Feature: ha-orchestrated-switchover, Property 3`

  - [ ] 2.7 Implement single-primary verification and outcome classification
    - Add `verify_single_primary(local_role, peer_role) -> 'ok' | 'split_brain' | 'zero_primary'` and `classify_outcome(phases) -> outcome enum` as pure reducers
    - _Requirements: 8.4, 9.1, 9.2, 9.3, 9.4, 9.5, 10.1, 10.2, 10.3, 10.4, 10.5, 11.4, 11.5, 13.3, 14.4_

  - [ ]* 2.8 Write property test for the single-primary invariant
    - **Property 4: Single-primary invariant on every terminal state**
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 10.1, 10.2, 10.3, 10.4**
    - Assert `succeeded ⇒ verify_single_primary == ok`; never `succeeded` with two/zero primaries; ≥100 examples; tag `Feature: ha-orchestrated-switchover, Property 4`

  - [ ]* 2.9 Write property test for outcome classification
    - **Property 5: Outcome classification is correct and retains the failing phase**
    - **Validates: Requirements 8.4, 9.5, 10.5, 11.4, 11.5, 13.3, 14.4**
    - Phase-result lists with an optional injected failure at a random index; assert correct outcome and that the failed phase is recorded; ≥100 examples; tag `Feature: ha-orchestrated-switchover, Property 5`

  - [ ] 2.10 Implement severity classification for outcomes
    - Add `severity_for_outcome(outcome) -> str` returning `critical` for split-brain, zero-primary, and `manual_intervention_required`, non-critical otherwise
    - _Requirements: 15.5_

  - [ ]* 2.11 Write property test for outcome severity
    - **Property 6: Unsafe outcomes are recorded at critical severity**
    - **Validates: Requirements 15.5**
    - ≥100 examples over the outcome enum; tag `Feature: ha-orchestrated-switchover, Property 6`

  - [ ]* 2.12 Write property test for the fallback lag guard
    - **Property 8: Fallback lag guard admits promotion only when safe**
    - **Validates: Requirements 3.2, 3.3**
    - Exercise the existing pure `can_promote` helper over lag (`None`/0/positive) × `force`; ≥100 examples; tag `Feature: ha-orchestrated-switchover, Property 8`

- [ ] 3. Checkpoint - pure logic validated
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. PeerHAClient — authenticated cross-node RPC
  - [ ] 4.1 Implement PeerHAClient and PeerRPCError taxonomy
    - Create `app/modules/ha/peer_client.py` with `PeerHAClient` and a `PeerIdentity` dataclass, generalising the existing wizard authenticate-then-call pattern (do not modify the wizard endpoints)
    - Implement `authenticate()` (POST `/auth/login`, decode JWT base64, assert `role == global_admin`, cache token), `get_identity()` (parses role/node_name/promoted_at out of the FULL `HAConfigResponse` the `/identity` endpoint returns), `probe_alive()` (GET `/ha/heartbeat` on the public router; verify HMAC if signed else treat 200+role as alive), `enter_maintenance()`, `exit_maintenance()`, `demote(reason)`, `promote(reason, force)`, `repoint_subscription()` (targets the NEW `POST /ha/replication/resume` — non-destructive, NOT `/replication/init`), `get_replication_status()`
    - Define `PeerRPCError` subclasses distinguishing connect-timeout vs HTTP-error vs auth-failure
    - Read peer Global_Admin credentials from the envelope-encrypted HAConfig fields added in task 1
    - _Requirements: 2.1, 2.5, 4.1, 6.1, 8.1, 8.2, 8.5, 13.4, 16.3_

  - [ ] 4.3 Add the non-destructive re-point peer endpoint `POST /api/v1/ha/replication/resume`
    - Add to `admin_router` in `app/modules/ha/router.py` (additive): when the node is `standby`, call `ReplicationManager.resume_subscription(db, get_peer_db_url(db))` — `CREATE SUBSCRIPTION … WITH (copy_data = false)` (`replication.py:556`), so the demoted old primary subscribes to the new primary with **no truncate and no full resync** (Req 8.6)
    - Do NOT reuse `/replication/init` (truncates) or `/replication/resync` (full resync). Return the resulting subscription status
    - _Requirements: 8.1, 8.2, 8.6_

  - [ ]* 4.2 Write unit tests for PeerHAClient with a mocked httpx transport
    - Assert token caching, `role != global_admin` rejection, and that each RPC method targets the correct peer endpoint
    - Assert the correct `PeerRPCError` subclass is raised for timeout vs HTTP error vs auth failure
    - _Requirements: 2.5, 16.3_

- [ ] 5. SwitchoverOrchestrator — async driver and phases
  - [ ] 5.1 Scaffold the orchestrator, Redis-backed progress store, and request/response schemas
    - Add `SwitchoverRequest`, `SwitchoverPhaseResult`, `SwitchoverOutcome`, `SwitchoverResponse`, **`SwitchoverAcceptedResponse`** (202 body: `switchover_id`, `accepted`, `path`, `message`), and `SwitchoverStatusResponse` (with `result: SwitchoverResponse | None`) to `app/modules/ha/schemas.py` (additive only)
    - Create `app/modules/ha/progress_store.py`: a **Redis-backed** single-row store (`redis_pool`, key `ha:switchover_progress`, JSON doc `{switchover_id, in_progress, current_phase, phases[], result}`, TTL ~900s) so progress is visible across the 2–4 gunicorn workers; include an in-memory fallback when Redis is unavailable (Req 14.7, 14.8)
    - Create `app/modules/ha/switchover.py` with the `SwitchoverOrchestrator` skeleton; it writes the store on every phase transition and on terminal outcome; use short-lived `async_session_factory()` sessions with explicit commit (not request-scoped `get_db_session`)
    - _Requirements: 14.1, 14.3, 14.4, 14.7, 14.8_

  - [ ] 5.2 Implement the verify_primary phase
    - Read local `HAConfig`; use `HeartbeatService.get_peer_health()` plus `PeerHAClient.get_identity()` / `probe_alive()`; probe peer DB via short `asyncpg` connect to `get_peer_db_url`; feed observations into `choose_path`
    - Branch to abort / fallback / orchestrated accordingly, recording a `PhaseResult`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 13.1, 13.4, 13.5_

  - [ ] 5.3 Implement the unreachable-primary fallback path
    - When `choose_path` returns `fallback`, call existing `HAService.promote(db, user_id, reason, force)` verbatim (preserving the 5s lag guard, force behaviour, `promoted_at` stamp, role=primary)
    - Build a `path="fallback"` response with a single synthetic `promote_local` phase and the manual-remediation message
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [ ] 5.4 Implement the quiesce phase
    - Call `PeerHAClient.enter_maintenance()`; confirm quiesced before drain; on failure abort leaving the peer as primary (no further role change)
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [ ] 5.5 Implement the drain phase with configurable timeout
    - Poll `ReplicationManager.get_replication_lag()` until `is_drain_complete` is true or `drain_timeout_seconds` elapses; emit a lag-bearing `PhaseResult` per tick; on timeout, roll back via `exit_maintenance`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [ ] 5.6 Implement the demote_remote phase
    - Call `PeerHAClient.demote(reason)`; confirm peer reports `standby` via `get_identity()` before promoting local; on failure or unconfirmed role, roll back via `exit_maintenance`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [ ] 5.7 Implement the promote_local phase
    - Call `HAService.promote()` (stop subscription, role=primary, stamp `promoted_at` — and note it **already calls `sync_sequences_post_promotion()` internally**, `service.py:~361`), then `ReplicationManager.init_primary()` to create the publication (promote does NOT create it). **Do NOT call `sync_sequences_post_promotion()` a second time** — it is redundant. On failure enter rollback `repromote_peer`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [ ] 5.8 Implement the repoint_subscription phase and post-repoint un-quiesce
    - Call `PeerHAClient.repoint_subscription()` → the new `POST /ha/replication/resume` (task 4.3), so the peer subscribes to the new primary using its own stored peer-DB config via `resume_subscription` (`copy_data=false`, **non-destructive** — no truncate/resync, Req 8.6); confirm active via `get_replication_status()`, then `exit_maintenance()` on the peer
    - On repoint failure, classify `completed_with_warning` with remediation text
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [ ] 5.9 Implement the verify_cluster phase
    - Read local role and peer role; call `verify_single_primary`; map `ok`→succeeded, `split_brain`→critical outcome surfacing existing split-brain guidance, `zero_primary`→rollback then re-verify
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [ ] 5.10 Implement the rollback procedure and single-primary invariant enforcement
    - Use `rollback_action` to choose the compensating action; wrap the compensating RPC so a peer-unreachable failure yields `manual_intervention_required` naming last-known roles; release guards in `finally`
    - Ensure every terminal state leaves exactly one primary or reports manual-intervention
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 11.1, 11.2, 11.3, 11.4, 11.5, 13.2, 13.3_

  - [ ] 5.11 Wire audit and HA event logging across phases
    - Call `write_audit_log` at start (`ha.switchover_started`) and end (`ha.switchover_completed`); `log_ha_event` per phase and per rollback action; use `severity_for_outcome` for critical outcomes; make all logging best-effort (never aborts the operation)
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5_

  - [ ]* 5.12 Write unit tests for orchestrator wiring with mocked PeerHAClient and services
    - Cover fallback wiring (path/phase/remediation), drain loop timeout + per-tick lag, rollback paths (un-quiesce, re-promote, manual-intervention), and audit/event call sequence
    - _Requirements: 3.4, 3.5, 5.2, 5.4, 11.1, 11.2, 11.5, 15.1, 15.2, 15.3, 15.4_

- [ ] 6. Checkpoint - orchestrator complete
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Endpoints, concurrency control, and pre-flight validation
  - [ ] 7.1 Add the switchover endpoints to the existing admin_router
    - Add `POST /api/v1/ha/switchover` and `GET /api/v1/ha/switchover/status` to `app/modules/ha/router.py` on the existing `admin_router` (already `require_role("global_admin")`); leave existing `/promote`, `/demote`, `/demote-and-sync` endpoints untouched
    - `POST` runs **pre-flight only**: validate `confirmation_text == "CONFIRM"` (reuse `validate_confirmation_text`) and non-empty `reason`; 404 when HA not configured; 400 for non-`standby`; 409 for already-primary / already-running / peer-creds-not-configured; acquire the lock, seed the progress store, **launch the orchestration as a background task (`asyncio.create_task`)**, and return **`202` with `SwitchoverAcceptedResponse { switchover_id, path }`**. Do NOT run the multi-phase operation inside the request (nginx `proxy_read_timeout 120s` / gunicorn `--timeout 120` vs `drain_timeout` up to 600s)
    - `GET /switchover/status` reads the Redis-backed progress store and is the source of truth (returns live phases + terminal `result`); works across workers and after the POST connection closes (Req 14.7, 14.8)
    - _Requirements: 1.3, 1.4, 1.5, 1.6, 14.1, 14.2, 14.3, 14.7, 14.8, 16.1, 16.2, 17.1, 17.2, 17.3_

  - [ ] 7.2 Implement the cluster-scoped Redis lock and in-process guard
    - Acquire `redis_pool.set("ha:switchover_lock", worker_id, nx=True, ex=600)` (mirroring `ha:auto_promote_lock`) plus a module-level `asyncio.Lock` + `in_progress` flag; reject overlapping requests with 409; already-primary returns 409 no-op without acquiring; release in `finally`; degrade gracefully when Redis is unavailable
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

  - [ ]* 7.3 Write property test for concurrency control
    - **Property 7: At most one switchover proceeds under concurrency**
    - **Validates: Requirements 12.1, 12.2, 12.4**
    - Use asyncio + Hypothesis over N concurrent `run()` attempts against the in-process guard; assert exactly one proceeds and the guard is reusable after completion; ≥100 examples; tag `Feature: ha-orchestrated-switchover, Property 7`

  - [ ]* 7.4 Write endpoint unit/regression tests
    - HA-not-configured → 404; not-`standby` → abort; already-`primary` → 409; non-`global_admin` → 403 with no role change; confirmation/reason validation
    - Regression: assert `/promote`, `/demote`, `/demote-and-sync` are still registered and unchanged and split-brain guidance is preserved
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 12.3, 16.1, 16.2, 17.1, 17.2, 17.4_

- [ ] 8. Frontend — HAReplication promote decision + progress modal (frontend-v2)
  - [ ] 8.1 Create the SwitchoverProgressModal component
    - New file `frontend-v2/src/pages/admin/components/SwitchoverProgressModal.tsx` using the existing `Modal` primitive
    - Pre-run form (mode banner orchestrated/fallback, reason input, CONFIRM input, force toggle in fallback only, drain-timeout number input); running state (ordered 7-row phase checklist with status icons + live `replication_lag_seconds` during drain, non-cancellable); terminal state (outcome banner + remediation + Close)
    - Confirm enabled only when `confirmText === 'CONFIRM'` and reason non-empty; consume all API data with `?.` / `?? []` / `?? null`
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6_

  - [ ] 8.2 Wire the Promote button decision logic and new ModalAction in HAReplication.tsx
    - Edit `frontend-v2/src/pages/admin/HAReplication.tsx`: add `'switchover'` to the `ModalAction` union and new state (`switchoverRunning`, `switchoverId`, `switchoverPhases`, `switchoverOutcome`, `switchoverPath`, `drainTimeout`)
    - Promote click decides orchestrated vs fallback mode from peer reachability/`peer_role`; when `peer_admin_configured` is false, fall back to the existing manual promote modal with an inline note
    - Call `POST /ha/switchover` → receive `202 { switchover_id, path }`; then poll `GET /ha/switchover/status?switchover_id` every 2s; stop and show the outcome banner when `status.result` is non-null (terminal) — the status endpoint, not the POST response, is the source of truth (survives proxy/client timeout and any worker); trigger `fetchData()` on close
    - Keep ALL existing standby action-bar buttons and their handlers intact (Promote, Init/Stop Replication, Re-sync, Enter/Exit Maintenance, Demote-and-Sync, Reset)
    - _Requirements: 14.2, 14.3, 14.5, 14.6, 17.1, 17.2, 17.3, 17.4_

  - [ ]* 8.3 Write vitest tests for the modal and decision logic
    - Test orchestrated vs fallback banner selection, Confirm enable/disable gating, live phase rendering, outcome banners, and the 409/403/404/network error UI states
    - Run `npx vitest --run` and `npx tsc --noEmit` from `frontend-v2/`
    - _Requirements: 14.2, 14.3, 14.5, 14.6_

- [ ] 9. Checkpoint - full stack wired
  - Ensure all backend tests and frontend `npx vitest --run` + `npx tsc --noEmit` pass, ask the user if questions arise.

- [ ] 10. Integration tests against real standby pairs
  - [ ]* 10.1 Write PeerHAClient + maintenance integration tests against the Dev pair
    - Against Dev primary (local :80) ↔ Dev standby (Pi :8081): `authenticate` obtains a Global_Admin JWT and is rejected for non-admin; `enter_maintenance`/`exit_maintenance` toggle peer maintenance while the peer keeps serving reads + `/ha/*`
    - Requires real paired nodes (live hardware)
    - _Requirements: 2.5, 4.1, 4.4, 8.5, 16.3_

  - [ ]* 10.2 Write remote demote / promote / repoint integration tests
    - Remote `demote` sets peer role `standby` and drops its publication; `promote_local` creates the publication (`init_primary`); `repoint_subscription` via `POST /ha/replication/resume` makes the old primary subscribe to the new primary using stored config with `copy_data=false` and reports active — **assert no truncate/full-resync occurred** (row counts unchanged on the old primary across the re-point); assert the Redis lock is set on start and gone on finish, and the Redis progress store holds the terminal result
    - Requires real paired nodes (live hardware)
    - _Requirements: 6.1, 6.2, 7.3, 7.4, 8.1, 8.2, 8.3, 8.6, 12.5_

  - [ ]* 10.3 Write end-to-end happy-path switchover integration test on the Dev pair
    - A full orchestrated switchover leaves exactly one primary and a healthy reversed cluster (new primary owns publication; old primary subscribed, reversed direction)
    - Requires real paired nodes (live hardware)
    - _Requirements: 9.5, 10.1_

## Notes

- Tasks marked with `*` are optional (tests and live-hardware integration) and can be skipped for a faster MVP; core implementation tasks are never optional.
- Each task references specific requirements/properties for traceability.
- The 8 Correctness Properties each map to exactly one Hypothesis property-test sub-task (Properties 1–6 and 8 under task 2; Property 7 under task 7), sequenced so the pure safety-critical decisions are validated before the async orchestrator is built.
- This feature is strictly additive to `app/modules/ha/`; the existing promote/demote/demote-and-sync endpoints and `HAService` methods are reused and preserved.
- HA management is `frontend-v2` (global admin) only — never mobile.
