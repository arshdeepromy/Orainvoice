# Implementation Plan: Cloud Backup & Restore (Platform DR/BCP)

## Overview

This plan implements the platform-wide DR/BCP subsystem in a new backend module `app/modules/backup_restore/` (Python 3.11 / FastAPI / SQLAlchemy async) plus Global-Admin pages in the active `frontend-v2/` app (React 18 / TypeScript). Work proceeds bottom-up: module scaffolding and platform/global data models first, then the escrowed BMK/BDK key hierarchy, the provider-agnostic `Storage_Interface` and four adapters, the content-addressed backup pipeline, the full/per-org restore pipelines, prune/GC, jobs/progress, audit/residency/config, the restore-maintenance middleware + scheduler wiring + Global-Admin API, and finally the frontend wizard and admin pages. Each step builds on the previous and ends wired into the running app.

Design-grounded invariants honoured throughout:
- New tables are **platform/global** (no `org_id`, no RLS); services use `flush()` + `await db.refresh()` (never `commit()`).
- Backup artifacts are encrypted under the escrowed **BMK→BDK** hierarchy (Argon2id via the already-installed `cryptography` lib), NOT `ENCRYPTION_MASTER_KEY`; operational secrets (OAuth/S3/NAS creds) stay under `ENCRYPTION_MASTER_KEY`.
- Migrations: new tables via `CREATE TABLE IF NOT EXISTS` following head (~0194); indexes in a separate migration using `CREATE INDEX CONCURRENTLY IF NOT EXISTS` inside `op.get_context().autocommit_block()` (copy `2026_05_30_2300-0202_add_perf_indexes.py`) — never `op.create_index`.
- Property tests use **Hypothesis** (min 100 iterations), tagged `# Feature: cloud-backup-restore, Property N: <text>`, with storage adapters and the DB mocked. INTEGRATION/SMOKE tests are explicitly **not** PBT.
- API mounted `/api/v1/backup` behind `require_role("global_admin")`; frontend pages under `/admin/backup/*` behind the existing `RequireGlobalAdmin` guard with a `globalAdminOnly` Sidebar item. Mobile is out of scope.

## Tasks

- [x] 1. Module scaffolding, data models, and migrations
  - [x] 1.1 Create the `app/modules/backup_restore/` module skeleton
    - Create the package tree exactly per the design module layout: `__init__.py`, `router.py`, `service.py`, `models.py`, `schemas.py`, and the `keys/`, `storage/`, `backup/`, `restore/` sub-packages with `__init__.py` files, plus empty `jobs.py`, `audit.py`, `residency.py`, `config_service.py`
    - Add placeholder Pydantic base schemas in `schemas.py` (all list responses shaped `{items, total}` per project rule)
    - _Requirements: 1.1, 3.1_
  - [x] 1.2 Define the SQLAlchemy models (platform/global tables, no `org_id`, no RLS)
    - In `models.py` define `backup_destinations`, `backup_residency_ack`, `backup_key_versions`, `backup_config` (single-row), `backups`, `backup_destination_copies`, `backup_blobs`, `blob_refcounts`, `backup_jobs`, `restore_jobs`, `restore_rehearsals` exactly per the Data Models section (columns/types/constraints)
    - Include `backup_config.restore_maintenance_active` (BOOLEAN default false), `notification_emails`/`notification_sms_numbers` (JSONB recipient lists), `orphan_gc_grace_hours`, `perorg_export_size_cap_bytes`, RPO/RTO fields; include `restore_jobs.destructive_apply_started` (BOOLEAN default false) for the cancel phase boundary
    - _Requirements: 7.1, 7.3, 7.8, 8.4, 8.7, 12.16, 13.1, 13.2, 16.10, 18.11, 20.3, 23.1, 25.1, 30.2, 30.5_
  - [x] 1.3 Create the table-creation Alembic migration following head
    - New revision after current head (~0194), revision id ≤ 64 chars; create every new table with `CREATE TABLE IF NOT EXISTS` (idempotent); no `org_id` columns and no RLS policies on any table
    - _Requirements: 1.1, 7.1, 8.4, 16.10_
  - [x] 1.4 Create the separate index-only Alembic migration
    - Copy the structure of `2026_05_30_2300-0202_add_perf_indexes.py`; create `backups(created_at DESC)`, `blob_refcounts(content_hash)`, `blob_refcounts(backup_id)`, `backup_jobs(status, created_at DESC)`, `restore_jobs(status, created_at DESC)`, `backup_destination_copies(backup_id)` using `CREATE INDEX CONCURRENTLY IF NOT EXISTS` inside `op.get_context().autocommit_block()`; never `op.create_index`
    - _Requirements: 9.1, 8.9_
  - [x] 1.5 Write a smoke test that the migrations apply and tables are platform/global
    - Single-execution smoke test: `alembic upgrade head` creates all tables; assert none carry an `org_id` column or RLS policy
    - _Requirements: 1.1_

- [x] 2. Key hierarchy and escrow (`keys/key_service.py`)
  - [x] 2.1 Implement BDK-keyed envelope encryption
    - Implement `backup_envelope_encrypt(plaintext, bdk)` / `backup_envelope_decrypt(blob, bdk)` reusing the `app/core/encryption.py` AES-256-GCM envelope construction but keyed by the BDK (never `ENCRYPTION_MASTER_KEY`)
    - _Requirements: 16.1, 16.2, 21.4_
  - [x] 2.2 Write property test for artifact encryption round-trip
    - **Property 2: Artifact encryption round-trip under the BDK**
    - **Validates: Requirements 16.1, 21.4**
  - [x] 2.3 Implement BMK/BDK setup, Argon2id KDF, KCV, and recovery-kit export
    - `setup(passphrase)`: generate 256-bit BMK + BDK v1, derive PWK with Argon2id (`cryptography.hazmat...Argon2id`, params + salt from design), produce `wrapped_bmk_passphrase`, `wrapped_bmk_env` (under `ENCRYPTION_MASTER_KEY`), `wrapped_bdk`, and `bmk_kcv`; persist a `backup_key_versions` row; build the Recovery Kit JSON; enforce passphrase strength rules
    - `export_recovery_kit()` re-emits the kit from retained wrapped material
    - _Requirements: 16.3, 16.4, 16.5, 16.6_
  - [x] 2.4 Implement fresh-deployment bootstrap, active-key access, and rotation
    - `bootstrap(kit, passphrase)`: derive PWK, unwrap BMK, verify against KCV (fail fast on wrong passphrase/kit), unwrap the requested BDK version — using only kit + passphrase, never `ENCRYPTION_MASTER_KEY`
    - `get_active_bdk()` / `get_bdk(version)` (seamless path via `wrapped_bmk_env`), `rotate()` (mint new version, prior versions retained)
    - `get_key_status()` → `{has_active_key, active_version, setup_complete}` reporting whether an active BMK/BDK is present on this deployment, the active key version, and whether first-run setup completed (Req 16.12)
    - Refuse with no writes when no key material is supplied or the recorded version is absent
    - _Requirements: 16.7, 16.8, 16.9, 16.10, 16.12_
  - [x] 2.5 Write property test for the fresh-deployment key-unwrap chain
    - **Property 3: Fresh-deployment key-unwrap chain works without ENCRYPTION_MASTER_KEY**
    - **Validates: Requirements 16.5, 16.6, 16.7**
  - [x] 2.6 Write property test for wrong key material
    - **Property 4: Wrong key material never yields plaintext**
    - **Validates: Requirements 16.8, 16.9**
  - [x] 2.7 Write unit tests for recovery-kit shape and passphrase strength
    - Recovery-kit JSON matches the documented shape; passphrase-strength enforcement (min length, zxcvbn ≥ 3, diceware generation); KDF params recorded per version
    - _Requirements: 16.3, 16.4_

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Provider-agnostic Storage Interface and adapters (`storage/`)
  - [x] 4.1 Define the `StorageInterface` ABC and provider-independent value types
    - `interface.py`: `ConnectionState`, `RemoteObject`, `UploadResult`, and the ABC with exactly five operations (upload/list/download/delete/connection-status); no parameter or return type references a specific provider
    - _Requirements: 3.1, 3.2, 3.3_
  - [x] 4.2 Implement the provider registry
    - `registry.py`: resolve provider-name → adapter from configuration; reject unknown/unconfigured providers with a uniform "provider unavailable" error and attempt no upload/list/download/delete
    - _Requirements: 3.4, 3.5, 3.6_
  - [x] 4.3 Implement `GoogleDriveAdapter`
    - Resumable upload session, 16 MiB chunks (256 KiB-multiple, 5–100 MiB bound), persist last acked offset, resume from offset, transient-retry with backoff, OAuth token refresh within 60 s, revoked-token → disconnected; normalise failures to uniform `StorageError`; exclude tokens from logs
    - _Requirements: 2.5, 2.6, 2.8, 4.1, 4.2, 4.3, 4.5, 4.6, 4.7, 3.7_
  - [x] 4.4 Implement `OneDriveAdapter`
    - Graph upload session with the same chunking/resume/retry semantics and token handling as Google Drive
    - _Requirements: 2.5, 2.6, 2.8, 4.1, 4.2, 4.3, 4.5, 4.6, 4.7, 3.7_
  - [x] 4.5 Implement `S3Adapter`
    - Access-key/secret/optional-session auth (creds under `ENCRYPTION_MASTER_KEY`), multipart upload with resume, endpoint/region/addressing-style support, head-bucket-or-put-then-delete connection test, Object Lock retention when `immutable_until` is given, delete refused under Object Lock
    - _Requirements: 3.8, 4.8, 27.2, 27.3, 28.4, 28.5, 28.6, 28.7, 28.9_
  - [x] 4.6 Implement `NasAdapter`
    - SMB/CIFS, NFS, or mounted `volume_path`; creds under `ENCRYPTION_MASTER_KEY`; every write is temp-file-then-atomic-rename; mount + write-then-delete connection test; not an Immutable_Copy substitute unless native WORM
    - _Requirements: 3.8, 4.9, 27.6, 29.2, 29.4, 29.5, 29.6, 29.8_
  - [x] 4.7 Write unit tests for adapter error normalisation and credential masking
    - Uniform `StorageError` identifying the failed operation preserves prior state; masked-credential save detection skips re-encrypt; tokens/creds excluded from logs
    - _Requirements: 2.8, 3.7, 28.4, 29.4_
  - [x] 4.8 Write integration tests for adapter reachability (NOT PBT)
    - 1–3 representative examples each: local MinIO (S3) and local NFS/SMB share read/write/list/delete; Google Drive/OneDrive against test accounts; verify wiring and external behaviour only
    - _Requirements: 3.4, 28.7, 29.5_

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Content-addressed store and manifest builder (`backup/cas.py`, `backup/manifest.py`)
  - [x] 6.1 Implement the content-addressed File_Blob store
    - `cas.py`: SHA-256 `Content_Hash`, HMAC-SHA-256 blob naming under a platform secret, "upload only if absent" dedup, write-through capture, known-skip recording for unreadable/missing files; each blob encrypted with `backup_envelope_encrypt` before upload
    - _Requirements: 21.3, 21.4, 21.5, 21.9_
  - [x] 6.2 Write property test for content-addressed dedup
    - **Property 5: Content-addressed dedup — identical content uploads once**
    - **Validates: Requirements 21.3, 21.5**
  - [x] 6.3 Implement the manifest, File_Index, and Per_Org_Index builders
    - `manifest.py`: cleartext catalog fields only {backup id, ISO-8601 UTC timestamp, encrypted-artifact size, checksum, scope}; encrypted envelope holding org-ID list, File_Index path/org listing, and Per_Org_Index org-identifying contents; checksum computed over encrypted dump bytes
    - _Requirements: 7.1, 7.2, 7.3, 7.8, 7.9_
  - [x] 6.4 Write property test for manifest catalog/envelope split
    - **Property 13: Manifest catalog leaks no customer structure**
    - **Validates: Requirements 7.2, 7.8**
  - [x] 6.5 Write unit test for blob-name HMAC stability
    - Same plaintext → same blob name; different plaintext → different name
    - _Requirements: 21.5_

- [x] 7. Retention, pruning, and garbage collection (`backup/prune.py`)
  - [x] 7.1 Implement retention and reference-counted blob pruning
    - Age/count retention deletes a backup's dump + File_Index then prunes blobs via `blob_refcounts`; a blob is deleted only when no retained File_Index references its `Content_Hash`; failed deletion marks `prune_failed` and retries next cycle
    - _Requirements: 8.5, 8.6, 8.7, 8.9_
  - [x] 7.2 Write property test for refcount GC
    - **Property 6: Refcount GC never deletes a referenced blob**
    - **Validates: Requirements 8.9, 8.12**
  - [x] 7.3 Implement mark-and-sweep orphan GC with grace period
    - Enumerate destination blobs, find `Orphan_Blob`s referenced by no committed File_Index, delete only after continuously unreferenced for the configured grace period
    - _Requirements: 8.10_
  - [x] 7.4 Write property test for orphan GC grace period
    - **Property 7: Orphan GC respects the grace period**
    - **Validates: Requirements 8.10**
  - [x] 7.5 Implement prune/GC concurrency lock, commit-time re-assertion, and RPO/RTO validation
    - Per-destination mutual-exclusion lock excluding in-progress backups; commit-time re-assertion that reused blobs still exist; schedule/retention save validates inter-backup interval against configured RPO and warns
    - _Requirements: 8.11, 8.12, 8.13, 25.2_

- [x] 8. Backup pipeline (`backup/pg_dump_runner.py`, `backup/pipeline.py`)
  - [x] 8.1 Implement the pg_dump runner (standby-sourced)
    - `pg_dump -Fc` against the standby replica via `HAService.get_peer_db_url()` inside a REPEATABLE READ export snapshot; capture all non-template objects incl. BYTEA assets; non-zero exit → human-readable failure
    - _Requirements: 5.1, 5.2, 5.6, 23.2_
  - [x] 8.2 Implement the backup pipeline orchestration
    - `pipeline.py`: scope validation, write-ahead audit, key resolve, dump, wholesale file capture from the primary's local volumes (`/app/uploads/` + `/app/compliance_files/`), opportunistic Per_Org_Logical_Export, manifest assembly, fan-out to primary + copy destinations, commit + re-assertion, completion/notification; record `consistency_level`
    - _Requirements: 5.5, 5.7, 6.1, 17.6, 17.7, 21.1, 21.2, 21.10, 23.1, 30.3, 30.5, 30.6, 31.1, 31.2_
  - [x] 8.3 Write property test for scope inclusion
    - **Property 18: Scope determines included data exactly**
    - **Validates: Requirements 6.2, 6.3, 6.4, 6.5**
  - [x] 8.4 Write unit test for invalid scope rejection
    - Invalid `Backup_Scope` rejected with no artifact created
    - _Requirements: 6.1, 6.5_
  - [x] 8.5 Write integration test for real pg_dump/pg_restore round-trip (NOT PBT)
    - Single representative example: real `pg_dump -Fc` then `pg_restore` into a scratch database
    - _Requirements: 5.1, 23.2_

- [x] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Row classifier and per-organisation restore (`restore/classifier.py`, `restore/per_org_restore.py`)
  - [x] 10.1 Implement the row classifier
    - `classifier.py`: three ordered rules — (1) nullable-`org_id` per-row hybrid (e.g. `bounced_addresses`), (2) non-nullable `org_id` → Org_Scoped, (3) enumerated Shared_Global allowlist override; exclude node-local/non-replicated tables (`ha_config`, `ha_event_log`, `error_log`, `audit_log`)
    - _Requirements: 14.7_
  - [x] 10.2 Write property test for classification totality and determinism
    - **Property 10: Row classification is total and deterministic**
    - **Validates: Requirements 14.7**
  - [x] 10.3 Write unit test for the allowlist against live model metadata
    - A newly-added global table with no `org_id` defaults to Shared_Global; pinned shared tables stay shared
    - _Requirements: 14.7_
  - [x] 10.4 Implement the per-organisation restore service
    - `per_org_restore.py`: integrity/presence checks, extraction (Per_Org_Logical_Export fast path or ephemeral scratch DB), classification-driven apply with conflict policy (restore-as-new/skip/overwrite), transitive references, single-transaction atomic apply under target-org RLS, file restore strictly from the backup's File_Index filtered to the org
    - _Requirements: 14.3, 14.5, 14.6, 14.7, 14.8, 14.9, 14.10, 22.2, 22.5, 22.6, 24.4, 31.3, 31.4, 31.5, 31.7_
  - [x] 10.5 Write property test for per-org isolation
    - **Property 8: Per-org restore touches no other organisation's rows**
    - **Validates: Requirements 14.3, 22.2**
  - [x] 10.6 Write property test for shared-global ensure-exists
    - **Property 9: Shared-global rows are ensured-exists, never mutated**
    - **Validates: Requirements 14.6, 14.7**
  - [x] 10.7 Write property test for restore-as-new referential integrity
    - **Property 11: Restore-as-new preserves referential integrity with zero dangling references**
    - **Validates: Requirements 14.6**
  - [x] 10.8 Write property test for per-org restore atomicity
    - **Property 12: Per-org restore is atomic**
    - **Validates: Requirements 14.10**
  - [x] 10.9 Write property test for restore-set sourcing
    - **Property 19: Restore-set is sourced strictly from the chosen backup's File_Index**
    - **Validates: Requirements 24.1, 24.3**

- [x] 11. Dry-run, schema-compatibility, and full restore (`restore/dry_run.py`, `restore/full_restore.py`)
  - [x] 11.1 Implement dry-run and schema-compatibility checks
    - `dry_run.py`: checksum verification + Alembic-revision schema-compat comparison only (no write/DDL); overall PASS/FAIL + per-step outcomes within 60 s; decision recorded on the Restore_Job; return an `older_schema` flag plus both migration versions so the wizard can present the older-schema confirmation gate ahead of submission (no in-flight pause; Req 10.5)
    - _Requirements: 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 11.2, 11.3, 11.4_
  - [x] 11.2 Write property test for the checksum gate
    - **Property 14: Checksum gate is honoured before any restore write**
    - **Validates: Requirements 7.4, 7.5, 7.6**
  - [x] 11.3 Write property test for the schema-compatibility decision
    - **Property 15: Schema-compatibility decision is monotonic in version order**
    - **Validates: Requirements 10.2, 10.3, 10.4, 10.5**
  - [x] 11.4 Implement the full-restore canonical sequence
    - `full_restore.py`: re-assert schema-compat and refuse an older-schema backup unless the request carries `confirm_older_schema=true`, recording the decision as refused (Req 10.6, 10.7); enable maintenance (set `restore_maintenance_active` + `HAService.enter_maintenance_mode`) → fence every standby (disable/drop subscription via `ReplicationManager`) → `pg_dump -Fc` Pre_Restore_Snapshot of the isolated primary → set `destructive_apply_started=true` then `pg_restore --clean` apply via the privileged connection → post-restore validation → PASS: full re-seed (`trigger_resync`) then resume HA / FAIL: rollback to snapshot, leave standby fenced; disable maintenance within 10 s on terminal/rollback; abort-before-apply on maintenance/fence/snapshot failure; honour a pre-apply cancel (stop with no data applied, release maintenance/fence, record `cancelled`) and refuse cancel once `destructive_apply_started` is set (Req 12.16, 12.17)
    - _Requirements: 10.6, 10.7, 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7, 12.8, 12.9, 12.10, 12.11, 12.13, 12.14, 12.15, 12.16, 12.17_
  - [x] 11.5 Write property test for full-restore canonical ordering
    - **Property 16: Full-restore canonical ordering is always enforced**
    - **Validates: Requirements 12.3, 12.10, 12.15**
  - [x] 11.6 Write property test for standby re-seed safety
    - **Property 17: A standby is never re-seeded from an unvalidated or rolled-back primary**
    - **Validates: Requirements 12.7, 12.13**
  - [x] 11.7 Write integration test for fence/re-seed and pg_restore (NOT PBT)
    - 1–3 representative examples against the dev HA pair: real subscription disable/drop fence and `trigger_resync` re-seed; real `pg_restore --clean` into a scratch DB
    - _Requirements: 12.10, 12.13_

- [x] 12. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Jobs/progress, audit, residency, and config (`jobs.py`, `audit.py`, `residency.py`, `config_service.py`)
  - [x] 13.1 Implement the job/progress/heartbeat model
    - `jobs.py`: Backup_Job/Restore_Job lifecycle (`queued→running→completed|failed|cancelled`), ≤5 s progress-or-heartbeat emission, status query (status/%/elapsed/time-since-last), >60 s stall force-fail, terminal recording, unknown-id → not-found
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_
  - [x] 13.2 Write property test for job progress/heartbeat state machine
    - **Property 20: Job progress either advances or heartbeats, and stalls fail**
    - **Validates: Requirements 13.2, 13.5**
  - [x] 13.3 Implement the audit writer
    - `audit.py`: write-ahead + completion entries into the existing `audit_log` (actor, action type, target id, UTC timestamp); write-ahead failure aborts before any change; completion-audit failure queues async retry without undoing the operation; secrets excluded from audit fields
    - _Requirements: 1.5, 1.6, 17.5, 17.6, 17.7, 17.8_
  - [x] 13.4 Implement the residency service
    - `residency.py`: derive offshore/onshore/unknown residency per destination, derive the disclosure notice, gate first upload on a persisted acknowledgement
    - _Requirements: 20.2, 20.3, 20.5, 20.8, 20.9_
  - [x] 13.5 Write property test for residency notice derivation
    - **Property 21: Data-residency notice derivation matches destination residency**
    - **Validates: Requirements 20.2, 20.8, 20.9**
  - [x] 13.6 Implement the config service
    - `config_service.py`: schedule (NZ tz cron) + backup window + retention count/days + RPO/RTO + notification toggles/channels + webhook URL + `notification_emails`/`notification_sms_numbers` recipient lists; multi-destination management with exactly one primary, including edit-destination-config and set-primary that clears the prior primary and sets the new one in one atomic transaction enforcing exactly-one-primary (Req 30.7); resolve notification recipients (explicit lists, else fallback to all `global_admin` emails, else record per-channel delivery failure — Req 18.11); PUT validates RPO/RTO and warns
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 18.11, 25.2, 30.2, 30.7_
  - [x] 13.7 Write unit tests for config/residency examples and edge cases
    - Older/newer/equal schema decisions, empty-backup listing empty-state, residency-notice derivation examples, RPO/RTO warning thresholds, exactly-one-primary invariant on set-primary/edit (Req 30.7), notification recipient resolution incl. global_admin fallback and no-recipient delivery-failure (Req 18.11), key-status reporting (has_active_key/active_version/setup_complete, Req 16.12)
    - _Requirements: 9.1, 10.3, 10.4, 16.12, 18.11, 20.2, 25.2, 30.7_

- [x] 14. Restore rehearsal (`restore/rehearsal.py`)
  - [x] 14.1 Implement the scheduled restore rehearsal
    - `rehearsal.py`: restore a recent backup into an isolated scratch environment, run schema + row-count + file-consistency + smoke checks, record pass/fail + measured duration vs RTO, tear the scratch environment down regardless of outcome
    - _Requirements: 25.4, 25.5, 26.1_

- [x] 15. Middleware, scheduler wiring, service facade, and API surface
  - [x] 15.1 Implement and register `RestoreMaintenanceMiddleware`
    - Net-new middleware registered alongside `StandbyWriteProtectionMiddleware`; reads `backup_config.restore_maintenance_active`, returns HTTP 503 for non-Global-Admin/non-health requests while set, drains in-flight requests via an active-request counter up to a bounded grace; abort if maintenance cannot be enabled within 10 s
    - _Requirements: 12.1, 12.2_
  - [x] 15.2 Implement the service facade and register scheduled tasks
    - `service.py` composing keys/pipeline/restore/prune/config/audit; expose `run_scheduled_backup_task()`, `run_blob_gc_task()`, `run_rehearsal_task()`; register them in `_DAILY_TASKS` and add to `WRITE_TASKS` (primary-only); scheduled backup honours cron + Backup_Window internally; dispatch outcome notifications (email/Connexus SMS/webhook) with new template types, resolving recipients via `config_service` (explicit lists → `global_admin` fallback → per-channel delivery-failure record, Req 18.11); implement `send_test_notification()` that dispatches a test message on each enabled channel and returns per-channel ok/detail without touching any backup/restore/config/job state (Req 18.12)
    - _Requirements: 8.1, 8.2, 8.3, 8.8, 2.6, 18.11, 18.12_
  - [x] 15.3 Implement the Global-Admin router and schemas
    - `router.py` mounted `/api/v1/backup` with `require_role("global_admin")`: destinations (create + edit `PUT /destinations/{id}` + `POST /destinations/{id}/set-primary` + OAuth connect/callback-with-postMessage-handoff/test/residency/delete), backups (+jobs status/cancel), restore (dry-run with `older_schema` flag / full with `confirm_older_schema` / per-org / browse / `POST /restore/jobs/{job_id}/cancel`), keys (`GET /keys/status` + setup/rotate/recovery-kit/bootstrap), config (+ `POST /config/notifications/test`), rehearsals; `{items,total}` lists with `offset`/`limit`; credentials masked; errors never expose stack traces; launch backups/restores as background tasks. Do NOT add an in-flight `confirm-schema` endpoint (older-schema confirmation is pre-submission via dry-run + `confirm_older_schema`)
    - _Requirements: 1.1, 1.2, 1.3, 9.1, 9.10, 10.6, 11.1, 12.1, 12.16, 12.17, 14.1, 15.1, 16.7, 16.12, 18.12, 26.1, 30.7_
  - [x] 15.4 Write unit tests for access control and audit-on-reject
    - Non-`global_admin` token → 403 no side effects; missing/invalid/expired → 401; rejected attempts and successful actions both write `audit_log`
    - _Requirements: 1.2, 1.3, 1.5, 1.6_
  - [x] 15.5 Write smoke tests for scheduler and middleware wiring (NOT PBT)
    - Backup/GC/rehearsal tasks present in `_DAILY_TASKS` and listed in `WRITE_TASKS`; `RestoreMaintenanceMiddleware` registered
    - _Requirements: 8.8, 12.1_
  - [x] 15.6 Write property test for the end-to-end backup→restore round-trip
    - **Property 1: Backup→restore round-trip preserves data** (pure-logic layer, storage + DB mocked)
    - **Validates: Requirements 5.1, 22.1, 24.2**

- [x] 16. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 17. Frontend-v2 Global Admin pages (`/admin/backup/*`)
  - [x] 17.1 Add navigation, route guard, and lazy routes
    - Register the six lazy routes in `frontend-v2/src/App.tsx` behind the existing `RequireGlobalAdmin` guard; add a `globalAdminOnly` Sidebar nav item "Cloud Backup" visible only when `user.role === 'global_admin'`
    - _Requirements: 1.4_
  - [x] 17.2 Implement `BackupDashboard`
    - At-a-glance status (last outcome, next scheduled, destinations health, RPO/RTO), "Run backup now" scope-picker modal, empty-state CTA; safe consumption (`?.`, `?? []`, AbortController)
    - _Requirements: 8.8, 9.1, 25.2_
  - [x] 17.3 Implement `BackupSettings` (destinations / schedule & retention / notifications)
    - Per-type Add Destination forms (OAuth connect; S3 access-key/endpoint/region/addressing; NAS share-path/mode/creds), Edit (`PUT /destinations/{id}`), Set-as-primary action on each non-primary row (`POST /destinations/{id}/set-primary`), Test Connection, Disconnect, residency notice + acknowledgement; OAuth connect via popup + `postMessage` handoff that refetches destinations so the row flips to `connected` without a manual refresh (no dead-end callback page); cron picker + window + retention with inline RPO/RTO warning; per-event notification toggles + channels + webhook URL + email/SMS recipient lists (with empty-list→global_admin fallback hint) + "Send test" button (`POST /config/notifications/test`) showing per-channel result; masked credentials
    - _Requirements: 2.1, 2.2, 2.7, 8.1, 8.2, 8.4, 18.11, 18.12, 20.3, 25.2, 28.5, 29.2, 30.2, 30.7_
  - [x] 17.4 Implement `BackupHistory`
    - `{items,total}` table (created_at, scope, size, file count, consistency, destinations, prune status), row actions (view/restore/cancel), search + offset/limit pagination, live progress badge polling `/status` every 2 s
    - _Requirements: 9.1, 13.3_
  - [x] 17.5 Implement `RestoreWizard`
    - Multi-step: on entry call `GET /keys/status`; select backup + destination; key material step (Recovery Kit + passphrase → `POST /keys/bootstrap`) shown ONLY when `has_active_key` is false, skipped otherwise (Req 16.7, 16.12); mode (full/per-org/dry-run); per-org browse entity-type tree with counts + conflict policy (block if zero selected); full path runs `POST /restore/dry-run` first and, when its `older_schema` flag is set, shows the older-schema confirmation gate then submits `POST /restore/full` with `confirm_older_schema=true` (Req 10.5–10.7); maintenance/fence/rollback banner; live progress modal with a Cancel control (`POST /restore/jobs/{job_id}/cancel`) enabled only during pre-apply phases and hidden/disabled once the destructive apply has begun (Req 12.16, 12.17)
    - _Requirements: 10.5, 10.6, 10.7, 11.1, 12.1, 12.16, 12.17, 14.1, 15.1, 15.6, 16.7, 16.12_
  - [x] 17.6 Implement `KeyRecoveryKit`
    - On load call `GET /keys/status`: when `setup_complete` is false show first-run setup (passphrase strength meter, generate kit via `POST /keys/setup`, force "I stored it offline" confirmation); when an active key exists show re-export kit (re-auth) + rotate key version (showing active version); never-recoverable warnings
    - _Requirements: 16.3, 16.4, 16.10, 16.12_
  - [x] 17.7 Implement `Rehearsals`
    - Rehearsal schedule config, history table (result, per-step outcomes, measured duration vs RTO), "Run rehearsal now"
    - _Requirements: 25.4, 26.1_
  - [x] 17.8 Write frontend unit tests for safe consumption and empty states
    - 403 hide/redirect, 409 job-running/terminal, 422 validation, network retry banner, loading spinners, empty states (no destinations / no backups / no rehearsals)
    - _Requirements: 1.4, 9.1_

- [x] 18. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; core implementation sub-tasks are never optional.
- Each task references specific granular requirement clauses for traceability.
- Each of the 21 correctness properties is its own Hypothesis property test (min 100 iterations), tagged `# Feature: cloud-backup-restore, Property N: <text>`, with storage adapters and the DB mocked.
- INTEGRATION (real `pg_dump`/`pg_restore`, real fence/re-seed, adapter reachability) and SMOKE (scheduler/middleware/migration wiring) tests are explicitly **not** PBT.
- Backup artifacts are encrypted only under the escrowed BMK/BDK hierarchy; operational secrets stay under `ENCRYPTION_MASTER_KEY`.
- All new tables are platform/global (no `org_id`, no RLS); services use `flush()` + `await db.refresh()`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "4.1"] },
    { "id": 2, "tasks": ["1.3", "4.2", "2.1"] },
    { "id": 3, "tasks": ["1.4", "4.3", "4.4", "4.5", "4.6", "2.2", "2.3"] },
    { "id": 4, "tasks": ["1.5", "2.4", "4.7", "4.8", "6.1"] },
    { "id": 5, "tasks": ["2.5", "2.6", "2.7", "6.2", "6.3", "7.1"] },
    { "id": 6, "tasks": ["6.4", "6.5", "7.2", "7.3", "8.1"] },
    { "id": 7, "tasks": ["7.4", "7.5", "8.2", "10.1"] },
    { "id": 8, "tasks": ["8.3", "8.4", "8.5", "10.2", "10.3", "10.4"] },
    { "id": 9, "tasks": ["10.5", "10.6", "10.7", "10.8", "10.9", "11.1", "13.1"] },
    { "id": 10, "tasks": ["11.2", "11.3", "11.4", "13.2", "13.3", "13.4"] },
    { "id": 11, "tasks": ["11.5", "11.6", "11.7", "13.5", "13.6", "14.1"] },
    { "id": 12, "tasks": ["13.7", "15.1", "15.2"] },
    { "id": 13, "tasks": ["15.3"] },
    { "id": 14, "tasks": ["15.4", "15.5", "15.6"] },
    { "id": 15, "tasks": ["17.1"] },
    { "id": 16, "tasks": ["17.2", "17.3", "17.4", "17.5", "17.6", "17.7"] },
    { "id": 17, "tasks": ["17.8"] }
  ]
}
```
