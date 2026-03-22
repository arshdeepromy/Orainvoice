# Implementation Plan: Live Database Migration

## Overview

Implement a zero-downtime live database migration tool accessible from Global Settings by `global_admin` users. The backend is built with FastAPI + SQLAlchemy async + Redis, and the frontend with React + TypeScript. Tasks are ordered so each step builds on the previous, starting with data models and schemas, then core services, then the API layer, then the frontend, and finally integration wiring.

## Tasks

- [x] 1. Create MigrationJob model, enum, and Alembic migration
  - [x] 1.1 Create `MigrationJobStatus` enum and `MigrationJob` SQLAlchemy ORM model in `app/modules/admin/migration_models.py`
    - Define the `MigrationJobStatus(str, Enum)` with all 12 statuses: pending, validating, schema_migrating, copying_data, draining_queue, integrity_check, ready_for_cutover, cutting_over, completed, failed, cancelled, rolled_back
    - Define the `MigrationJob(Base)` model with all columns matching the design (id, status, source/target host/port/db_name, ssl_mode, target_conn_encrypted, batch_size, current_table, rows_processed, rows_total, progress_pct, table_progress, dual_write_queue_depth, integrity_check, error_message, timestamps, initiated_by FK)
    - Add check constraint on status and indexes on status and created_at
    - _Requirements: 10.1, 10.2_

  - [x] 1.2 Create Alembic migration for `migration_jobs` table
    - Generate a new Alembic revision that creates the `migration_jobs` table with all columns, constraints, and indexes from the design
    - _Requirements: 10.1_

- [x] 2. Create migration schemas and utility functions
  - [x] 2.1 Create Pydantic request/response schemas in `app/modules/admin/migration_schemas.py`
    - Implement all schemas: `ConnectionValidateRequest`, `ConnectionValidateResponse`, `MigrationStartRequest`, `MigrationStatusResponse`, `TableProgress`, `IntegrityCheckResult`, `RowCountComparison`, `FinancialComparison`, `SequenceComparison`, `CutoverRequest`, `RollbackRequest`, `MigrationJobSummary`, `MigrationJobDetail`
    - _Requirements: 2.1, 2.2, 5.4, 5.7, 7.6, 8.2, 9.1, 10.4, 10.5_

  - [x] 2.2 Implement connection string parsing and password masking utilities in `app/modules/admin/migration_schemas.py`
    - `parse_connection_string(conn_str) -> dict` — extract scheme, user, host, port, dbname using `urllib.parse.urlparse`
    - `mask_password(conn_str) -> str` — replace password with `****`
    - `validate_connection_string_format(conn_str) -> tuple[bool, str | None]` — check format matches `postgresql+asyncpg://user:pass@host:port/dbname`
    - _Requirements: 2.3, 2.4, 2.5, 11.3, 11.4_

  - [x] 2.3 Write property tests for connection string validation (P2)
    - **Property 2: Connection string format validation**
    - Generate random strings and well-formed connection URIs; verify validator returns valid=true only for correct format and valid=false with non-empty error for invalid format
    - **Validates: Requirements 2.3, 2.4**

  - [x] 2.4 Write property test for password masking (P3)
    - **Property 3: Password masking in all outputs**
    - Generate connection strings with random passwords; verify masked output replaces password with `****`, preserves other components, and original password does not appear
    - **Validates: Requirements 2.5, 11.3**

  - [x] 2.5 Write property test for progress percentage calculation (P7)
    - **Property 7: Progress percentage calculation**
    - Generate random (rows_processed, rows_total) pairs where rows_total > 0; verify percentage equals `(rows_processed / rows_total) * 100` clamped to [0, 100]
    - **Validates: Requirements 5.4**

  - [x] 2.6 Write property test for ETA calculation (P8)
    - **Property 8: ETA calculation**
    - Generate random positive rows_processed, elapsed_seconds, and rows_total >= rows_processed; verify ETA formula. When rows_processed is 0, ETA should be None
    - **Validates: Requirements 5.8**

  - [x] 2.7 Write property test for batch partitioning (P6)
    - **Property 6: Batch partitioning correctness**
    - Generate random row lists and batch sizes (B >= 1); verify ceil(N/B) batches, each at most B rows, concatenation equals original
    - **Validates: Requirements 5.3**

  - [x] 2.8 Write property test for PG version compatibility (P4)
    - **Property 4: PostgreSQL version compatibility check**
    - Generate random version strings; verify compatible=true iff major version >= 13
    - **Validates: Requirements 3.3**

- [x] 3. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement Integrity Checker
  - [x] 4.1 Create `IntegrityChecker` class in `app/modules/admin/integrity_checker.py`
    - Implement `__init__(self, source_engine, target_engine)`
    - Implement `async run() -> IntegrityCheckResult` that orchestrates all checks
    - Implement `_compare_row_counts()` — query `SELECT count(*)` for every table in both databases and compare
    - Implement `_check_foreign_keys()` — verify all FK references in target are valid
    - Implement `_compare_financial_totals()` — compare sums for invoice amounts, payment totals, credit note totals
    - Implement `_compare_sequences()` — compare sequence current values, target must be >= source
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 4.2 Write property test for row count and financial total comparison (P11)
    - **Property 11: Row count and financial total comparison correctness**
    - Generate source/target count maps; verify match=true iff values are equal, overall passes iff all match
    - **Validates: Requirements 7.2, 7.4**

  - [x] 4.3 Write property test for sequence value validation (P12)
    - **Property 12: Sequence value validation**
    - Generate source/target sequence maps; verify valid=true iff target >= source, overall passes iff all valid
    - **Validates: Requirements 7.5**

- [x] 5. Implement Dual-Write Proxy
  - [x] 5.1 Create `DualWriteProxy` class in `app/modules/admin/dual_write.py`
    - Implement `__init__(self, target_engine)` with `asyncio.Queue` for retry queue
    - Implement `enable()` / `disable()` to attach/detach SQLAlchemy `after_flush` event listener
    - Implement `_on_after_flush(session, flush_context)` to capture INSERT/UPDATE/DELETE and replay against target engine
    - On target write failure: log error, enqueue operation to Redis retry list `migration:dual_write_retry:{job_id}`, increment `queue_depth`
    - Implement `drain_retry_queue()` to replay queued operations in FIFO order
    - Implement `get_queue_depth() -> int`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 5.2 Write property test for retry queue depth accuracy (P9)
    - **Property 9: Dual-write retry queue depth accuracy**
    - Generate enqueue/dequeue sequences; verify reported depth equals enqueued minus dequeued
    - **Validates: Requirements 6.4**

  - [x] 5.3 Write property test for retry queue FIFO ordering (P10)
    - **Property 10: Dual-write retry queue FIFO ordering**
    - Generate operation sequences; verify drain yields same order as enqueued
    - **Validates: Requirements 6.5**

- [x] 6. Implement Cutover Manager
  - [x] 6.1 Create `CutoverManager` class in `app/modules/admin/cutover_manager.py`
    - Implement `_pause_requests()` / `_resume_requests()` using Redis lock key `migration:lock` with 30s TTL
    - Implement `_swap_engine(new_url)` to replace global `engine` and `async_session_factory` in `app.core.database`, dispose old pool
    - Implement `_verify_connectivity()` to run a test query on the new engine
    - Implement `execute_cutover(target_engine, target_url) -> bool` — pause requests, swap engine, verify, resume; auto-rollback on failure
    - Implement `execute_rollback(source_url) -> bool` — pause requests, swap engine back, verify, resume
    - _Requirements: 8.3, 8.4, 8.5, 8.6, 8.7, 9.2, 9.3, 9.4_

  - [x] 6.2 Write property test for cutover confirmation text validation (P14)
    - **Property 14: Cutover confirmation text validation**
    - Generate random strings; verify only exact `"CONFIRM CUTOVER"` is accepted
    - **Validates: Requirements 8.2**

  - [x] 6.3 Write property test for rollback availability within 24h window (P16)
    - **Property 16: Rollback availability within 24-hour window**
    - Generate cutover timestamps; verify rollback available iff current time within 24h of cutover_at
    - **Validates: Requirements 9.1, 9.6**

- [x] 7. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Implement Migration Service
  - [x] 8.1 Create `MigrationService` class in `app/modules/admin/migration_service.py`
    - Implement `validate_connection(conn_str, ssl_mode) -> ConnectionValidateResponse`
      - Validate format, attempt connection with 10s timeout, check PG version >= 13, check privileges (CREATE, INSERT, UPDATE, DELETE, SELECT), check emptiness, check SSL in prod/staging
      - Mask password in all responses
    - _Requirements: 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 11.3, 11.5_

  - [x] 8.2 Implement `start_migration()` and `_run_pipeline()` background task
    - `start_migration(conn_str, ssl_mode, batch_size, user_id) -> str` — check no active migration (Redis `migration:active_job`), create MigrationJob record, encrypt connection string, launch `asyncio.create_task(_run_pipeline(job_id))`
    - `_run_pipeline(job_id)` — run Alembic on target (Req 4.1–4.4), enable dual-write, copy data table-by-table in dependency order with configurable batch size and retry logic (3 retries, exponential backoff), update progress in Redis, drain retry queue, run integrity check, update job status
    - Store progress in Redis hash `migration:progress:{job_id}` for polling
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 5.4, 5.5, 5.9, 6.1, 6.2, 6.3, 6.4, 6.5, 7.1, 10.2, 10.3, 11.1_

  - [x] 8.3 Implement `get_status()`, `cutover()`, `rollback()`, `cancel_migration()`, `get_history()`, `get_job_detail()`
    - `get_status(job_id)` — read from Redis progress hash, return `MigrationStatusResponse` with ETA calculation
    - `cutover(job_id, user_id)` — validate confirmation text, check job is `ready_for_cutover`, delegate to CutoverManager, set rollback_deadline to cutover_at + 24h, log audit event
    - `rollback(job_id, user_id, reason)` — check within 24h window, delegate to CutoverManager, log audit event
    - `cancel_migration(job_id, user_id)` — check cancellable state, set cancellation flag, clean up target, update status to cancelled, log audit event
    - `get_history()` / `get_job_detail(job_id)` — query MigrationJob records, mask passwords
    - _Requirements: 5.5, 5.8, 8.1, 8.2, 8.3, 8.6, 8.7, 8.8, 9.1, 9.2, 9.4, 9.5, 9.6, 10.4, 10.5, 12.1, 12.2, 12.3, 12.4_

  - [x] 8.4 Write property test for table dependency ordering (P5)
    - **Property 5: Table dependency ordering**
    - Generate random DAGs of table FK dependencies; verify topological sort produces valid ordering
    - **Validates: Requirements 5.2**

  - [x] 8.5 Write property test for single active migration enforcement (P18)
    - **Property 18: Only one active migration at a time**
    - Generate active job states; verify new migration start is rejected with descriptive error
    - **Validates: Requirements 10.2, 10.3**

  - [x] 8.6 Write property test for cutover availability gating (P13)
    - **Property 13: Cutover availability determined by integrity check result**
    - Generate jobs with various integrity results; verify cutover allowed only when status is ready_for_cutover and integrity passed=true
    - **Validates: Requirements 7.7, 8.1**

  - [x] 8.7 Write property test for connection string encryption round-trip (P19)
    - **Property 19: Connection string encryption round-trip**
    - Generate valid connection strings; verify encrypt then decrypt returns original
    - **Validates: Requirements 11.1**

  - [x] 8.8 Write property test for stored job connection components (P20)
    - **Property 20: Stored job contains only parsed connection components**
    - Generate connection strings; verify stored MigrationJob has correct host/port/db_name and no unencrypted full connection string
    - **Validates: Requirements 11.4**

  - [x] 8.9 Write property test for SSL enforcement in prod/staging (P21)
    - **Property 21: SSL required in production and staging environments**
    - Generate environment/ssl_mode combinations; verify ssl_mode=disable rejected in production/staging, accepted in development
    - **Validates: Requirements 11.5**

  - [x] 8.10 Write property test for cancellation state transition (P22)
    - **Property 22: Cancellation updates job status and creates audit entry**
    - Generate in-progress jobs; verify cancellation transitions to cancelled and produces audit log entry
    - **Validates: Requirements 12.3**

  - [x] 8.11 Write property test for migration job serialization round-trip (P17)
    - **Property 17: Migration job serialization round-trip**
    - Generate MigrationJob instances; verify serialization to MigrationStatusResponse preserves all fields
    - **Validates: Requirements 10.1**

  - [x] 8.12 Write property test for audit log entries (P15)
    - **Property 15: Audit log entries contain required fields with masked passwords**
    - Generate migration events; verify audit log contains user ID, timestamp, source/target identifiers, no plaintext passwords
    - **Validates: Requirements 8.8, 9.5**

- [x] 9. Implement Migration Router and wire to admin module
  - [x] 9.1 Create `migration_router` in `app/modules/admin/migration_router.py`
    - Define all 8 endpoints under `/api/v1/admin/migration/*` with `require_role("global_admin")` dependency
    - `POST /validate` — call `MigrationService.validate_connection()`
    - `POST /start` — call `MigrationService.start_migration()`
    - `GET /status/{job_id}` — call `MigrationService.get_status()`
    - `POST /cutover/{job_id}` — call `MigrationService.cutover()`
    - `POST /rollback/{job_id}` — call `MigrationService.rollback()`
    - `POST /cancel/{job_id}` — call `MigrationService.cancel_migration()`
    - `GET /history` — call `MigrationService.get_history()`
    - `GET /history/{job_id}` — call `MigrationService.get_job_detail()`
    - _Requirements: 1.1, 1.2, 2.3, 3.1, 5.5, 8.1, 9.1, 10.4, 12.1_

  - [x] 9.2 Mount migration router on the existing admin router in `app/modules/admin/router.py`
    - Include `migration_router` with prefix `/migration`
    - _Requirements: 1.1_

  - [x] 9.3 Write property test for RBAC enforcement (P1)
    - **Property 1: RBAC enforcement on migration endpoints**
    - Generate random roles; verify only global_admin passes, all others get 403
    - **Validates: Requirements 1.1, 1.2**

  - [x] 9.4 Write backend unit tests in `tests/test_migration.py`
    - Test connection validation happy path with real-format strings
    - Test Alembic failure handling (mocked)
    - Test batch copy retry exhaustion (mocked)
    - Test dual-write failure queuing (mocked)
    - Test cutover with verification failure → auto-rollback (mocked)
    - Test cancel during each cancellable state
    - Test history endpoint returns correct job list
    - _Requirements: 3.1, 4.2, 5.9, 6.3, 8.7, 12.2, 10.4_

- [x] 10. Checkpoint — Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Implement frontend LiveMigrationTool page and sub-components
  - [x] 11.1 Create `ConnectionForm` component
    - Input field for connection string, SSL mode dropdown (require, prefer, disable)
    - Submit button calls `POST /api/v1/admin/migration/validate`
    - Display validation result (success with server version/disk space, or inline error)
    - On validation success, show "Start Migration" button that calls `POST /api/v1/admin/migration/start`
    - Handle target-has-existing-tables warning with confirmation checkbox
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.6, 3.7_

  - [x] 11.2 Create `MigrationProgress` component
    - Poll `GET /api/v1/admin/migration/status/{job_id}` every 2 seconds
    - Display overall progress bar with percentage
    - Display table-level breakdown: table name, source count, migrated count, status badge (pending/in_progress/completed/failed)
    - Display estimated time remaining
    - Display dual-write queue depth
    - Show "Cancel Migration" button while migration is in progress
    - _Requirements: 5.6, 5.7, 5.8, 6.4, 12.1_

  - [x] 11.3 Create `IntegrityReport` component
    - Display integrity check results: per-table row count comparison, financial total comparison, FK errors list, sequence checks
    - Show pass/fail badge for each check category
    - _Requirements: 7.6_

  - [x] 11.4 Create `CutoverPanel` component
    - Show "Cut Over to New Database" button (enabled only when integrity check passed)
    - Confirmation modal requiring user to type "CONFIRM CUTOVER"
    - Display cutover result (success or failure with auto-rollback message)
    - _Requirements: 8.1, 8.2_

  - [x] 11.5 Create `RollbackPanel` component
    - Show "Roll Back to Previous Database" button with 24-hour countdown timer
    - Require reason text input before rollback
    - Disable button and show warning after 24 hours
    - _Requirements: 9.1, 9.6_

  - [x] 11.6 Create `MigrationHistory` component
    - Table listing past migration jobs: status, start time, end time, record counts, source/target hosts
    - Click a row to expand full details including integrity results and error messages
    - _Requirements: 10.4, 10.5_

  - [x] 11.7 Create `LiveMigrationTool` page in `frontend/src/pages/admin/LiveMigrationTool.tsx`
    - Compose all sub-components (ConnectionForm, MigrationProgress, IntegrityReport, CutoverPanel, RollbackPanel, MigrationHistory)
    - Manage migration state and conditionally render components based on current job status
    - Display error banner for API errors at the top
    - _Requirements: 1.3, 2.1_

  - [x] 11.8 Add route and navigation for LiveMigrationTool in the admin section
    - Add route entry for the new page
    - Add navigation link in Global Settings / admin sidebar
    - Ensure route is only accessible to global_admin users
    - _Requirements: 1.3_

- [x] 12. Checkpoint — Ensure frontend builds without errors
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Write frontend tests
  - [x] 13.1 Write frontend property tests in `frontend/src/pages/admin/__tests__/live-migration.properties.test.ts`
    - **Property 7: Progress percentage rendering** — Generate random progress values, verify progress bar renders correct percentage
    - **Property 8: ETA display** — Generate random progress states, verify ETA display
    - **Property 13: Cutover button state** — Generate jobs with various statuses, verify cutover button enabled/disabled
    - **Property 16: Rollback button visibility** — Generate cutover timestamps, verify rollback button visibility within/after 24h
    - **Validates: Requirements 5.6, 5.8, 8.1, 9.1**

  - [x] 13.2 Write frontend unit tests in `frontend/src/pages/admin/__tests__/live-migration.test.tsx`
    - Test connection form submission and validation feedback
    - Test progress polling starts/stops based on job status
    - Test cutover confirmation modal requires exact text
    - Test rollback button visibility based on time
    - Test migration history table rendering
    - Test error banner display on API failure
    - _Requirements: 2.1, 5.6, 8.2, 9.1, 10.4_

- [x] 14. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (P1–P22)
- Unit tests validate specific examples and edge cases
- All 22 backend properties and 4 frontend properties are covered
