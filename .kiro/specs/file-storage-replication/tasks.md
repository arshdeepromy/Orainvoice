# Implementation Plan: File Storage Replication

## Overview

Hybrid file storage and replication for OraInvoice HA: branding files move into PostgreSQL BYTEA columns (auto-replicated via logical replication), while volume data (uploads, compliance files) gains rsync-based sync from primary to standby. Implementation proceeds: database migrations → backend branding changes → backend volume sync → startup integration → frontend HA page → Docker Compose updates → tests.

## Tasks

- [x] 1. Create Alembic migration 0165: add BYTEA columns to `platform_branding`
  - [x] 1.1 Create migration file `alembic/versions/2026_XX_XX_XXXX-0165_add_branding_bytea_columns.py`
    - Add 9 columns: `logo_data` (LargeBinary, nullable), `dark_logo_data` (LargeBinary, nullable), `favicon_data` (LargeBinary, nullable), `logo_content_type` (String(100), nullable), `dark_logo_content_type` (String(100), nullable), `favicon_content_type` (String(100), nullable), `logo_filename` (String(255), nullable), `dark_logo_filename` (String(255), nullable), `favicon_filename` (String(255), nullable)
    - Use `IF NOT EXISTS` pattern for idempotency
    - Downgrade drops all 9 columns
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x] 1.2 Run migration against dev database
    - Execute: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head`
    - Verify output shows "Running upgrade 0164 -> 0165"
    - _Requirements: 8.1_

- [x] 2. Create Alembic migration 0166: add `volume_sync_config` and `volume_sync_history` tables
  - [x] 2.1 Create migration file `alembic/versions/2026_XX_XX_XXXX-0166_add_volume_sync_tables.py`
    - Create `volume_sync_config` table: id (UUID PK), standby_ssh_host (String(255)), ssh_port (Integer, default 22), ssh_key_path (String(500)), remote_upload_path (String(500), default '/app/uploads/'), remote_compliance_path (String(500), default '/app/compliance_files/'), sync_interval_minutes (Integer, default 5), enabled (Boolean, default false), created_at (DateTime(tz), server_default now()), updated_at (DateTime(tz), server_default now())
    - Create `volume_sync_history` table: id (UUID PK), started_at (DateTime(tz)), completed_at (DateTime(tz), nullable), status (String(20)), files_transferred (Integer, default 0), bytes_transferred (BigInteger, default 0), error_message (Text, nullable), sync_type (String(20))
    - Use `IF NOT EXISTS` for idempotency
    - Downgrade drops both tables
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [x] 2.2 Run migration against dev database
    - Execute: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head`
    - Verify output shows "Running upgrade 0165 -> 0166"
    - _Requirements: 9.1_

- [x] 3. Checkpoint — Verify migrations applied
  - Ensure both migrations ran successfully, ask the user if questions arise.

- [x] 4. Update branding model, service, and router for BYTEA storage
  - [x] 4.1 Add BYTEA columns to `PlatformBranding` model in `app/modules/branding/models.py`
    - Add 9 new `Mapped` columns matching migration 0165: `logo_data`, `dark_logo_data`, `favicon_data`, `logo_content_type`, `dark_logo_content_type`, `favicon_content_type`, `logo_filename`, `dark_logo_filename`, `favicon_filename`
    - Import `LargeBinary` from SQLAlchemy
    - _Requirements: 1.1, 1.2, 1.3_

  - [x] 4.2 Add `store_branding_file`, `get_branding_file`, and `migrate_disk_files_to_db` methods to `BrandingService` in `app/modules/branding/service.py`
    - `store_branding_file(file_type, file_data, content_type, filename)` — stores bytes in the corresponding BYTEA column and updates the `_url` field to `/api/v1/public/branding/file/{file_type}`
    - `get_branding_file(file_type)` — returns `(data, content_type, filename)` tuple or `None`
    - `migrate_disk_files_to_db()` — reads existing disk files referenced by `_url`, populates BYTEA columns, updates URLs. Idempotent: skips if `_data` already populated. Logs warning if disk file missing.
    - Use `flush()` not `commit()` per project conventions
    - _Requirements: 1.4, 1.5, 2.1, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 4.3 Modify upload handlers in `app/modules/branding/router.py` to store in DB instead of disk
    - Update `_handle_branding_upload` to call `svc.store_branding_file()` instead of writing to disk
    - Keep `_process_image()` call for image optimization before storing
    - Keep existing file size and content type validation unchanged
    - Build the public URL as `/api/v1/public/branding/file/{file_type}` pattern
    - _Requirements: 1.4, 1.5, 1.6, 1.7_

  - [x] 4.4 Modify `serve_branding_file` endpoint in `app/modules/branding/router.py` for DB-first serving
    - If `file_id` is `logo`, `dark_logo`, or `favicon` → serve from DB via `svc.get_branding_file()`
    - Otherwise → fall back to existing disk-based serving (backward compatibility for legacy UUID paths)
    - Include `Cache-Control: public, max-age=86400` header
    - Return 404 if BYTEA column is NULL
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6_

  - [x] 4.5 Write property test for branding file upload round-trip
    - **Property 1: Branding file upload round-trip**
    - **Validates: Requirements 1.4, 2.1, 2.5**

  - [x] 4.6 Write property test for branding upload input validation
    - **Property 2: Branding upload input validation**
    - **Validates: Requirements 1.5, 1.6**

- [x] 5. Checkpoint — Verify branding BYTEA storage works
  - Ensure branding upload and serving works end-to-end via DB, ask the user if questions arise.

- [x] 6. Implement volume sync models and schemas
  - [x] 6.1 Create `app/modules/ha/volume_sync_models.py` with `VolumeSyncConfig` and `VolumeSyncHistory` models
    - `VolumeSyncConfig`: singleton config with SSH host, port, key path, remote paths, interval, enabled flag, timestamps
    - `VolumeSyncHistory`: log entries with started_at, completed_at, status, files_transferred, bytes_transferred, error_message, sync_type
    - _Requirements: 4.1, 9.1, 9.2_

  - [x] 6.2 Create `app/modules/ha/volume_sync_schemas.py` with Pydantic schemas
    - `VolumeSyncConfigRequest` — input validation with `sync_interval_minutes` range [1, 1440]
    - `VolumeSyncConfigResponse` — output with `model_config = ConfigDict(from_attributes=True)`
    - `VolumeSyncStatusResponse` — last sync time, result, next scheduled, file count, size, in_progress flag
    - `VolumeSyncHistoryEntry` — history row output
    - `VolumeSyncTriggerResponse` — trigger confirmation
    - _Requirements: 4.1, 4.2, 6.1, 6.2_

- [x] 7. Implement volume sync service
  - [x] 7.1 Create `app/modules/ha/volume_sync_service.py` with `VolumeSyncService` class
    - `get_config(db)` — load singleton config row
    - `save_config(db, req)` — upsert config, validate SSH host not empty and interval in range
    - `get_status(db)` — return current sync status including directory scan results
    - `get_history(db, limit=20)` — return recent history entries ordered by `started_at` DESC
    - `trigger_sync(db)` — execute immediate manual sync, return 409 if already running
    - `build_rsync_command(config, source_path, dest_path)` — pure function constructing rsync command with `--archive`, `--compress`, `--delete` flags and SSH key auth
    - `_execute_rsync(db, config, sync_type)` — run rsync subprocess for both upload and compliance directories, record history
    - `start_periodic_sync(db)` — start background asyncio task
    - `stop_periodic_sync()` — stop background task
    - `_periodic_loop(db_factory)` — sleep loop calling `_execute_rsync` at configured interval
    - `_scan_directories()` — scan `/app/uploads/` and `/app/compliance_files/` for total file count and size
    - Use `flush()` not `commit()` per project conventions
    - _Requirements: 4.2, 4.6, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 6.1, 6.3, 6.4_

  - [x] 7.2 Write property test for rsync configuration validation
    - **Property 5: Rsync configuration validation**
    - **Validates: Requirement 4.2**

  - [x] 7.3 Write property test for rsync command construction
    - **Property 6: Rsync command construction**
    - **Validates: Requirements 5.2, 5.3, 5.7, 5.8**

  - [x] 7.4 Write property test for sync history ordering
    - **Property 7: Sync history ordering**
    - **Validates: Requirement 6.4**

- [x] 8. Implement volume sync router
  - [x] 8.1 Create `app/modules/ha/volume_sync_router.py` with API endpoints
    - `GET /config` — return current rsync configuration (404 if not configured)
    - `PUT /config` — upsert rsync configuration
    - `GET /status` — return current sync status
    - `POST /trigger` — trigger manual sync (409 if already running)
    - `GET /history` — return recent sync history (default limit 20)
    - All endpoints require `global_admin` role (enforced by parent HA router prefix)
    - _Requirements: 4.3, 4.4, 4.5, 5.6, 6.1, 6.2, 6.5_

  - [x] 8.2 Mount volume sync router in `app/modules/ha/router.py` or `app/main.py`
    - Include the volume sync router under `/api/v1/ha/volume-sync/` prefix
    - Ensure it inherits the HA router's global_admin role requirement
    - _Requirements: 4.5_

- [x] 9. Checkpoint — Verify volume sync backend
  - Ensure volume sync config CRUD, status, trigger, and history endpoints work, ask the user if questions arise.

- [x] 10. Add startup integration for branding migration and volume sync
  - [x] 10.1 Add branding disk-to-DB migration startup hook in `app/main.py`
    - Add a new `@app.on_event("startup")` handler that calls `BrandingService.migrate_disk_files_to_db()`
    - Use `async_session_factory` for the DB session
    - Log migrated file count on success, log warnings on failures
    - Must be idempotent — safe to run on every startup
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 10.2 Add volume sync periodic task startup hook in `app/main.py`
    - Add a new `@app.on_event("startup")` handler that calls `VolumeSyncService.start_periodic_sync()`
    - Only start if config exists and is enabled
    - Wrap in try/except to avoid blocking app startup on failure
    - _Requirements: 5.1_

  - [x] 10.3 Register volume sync models import in `app/main.py` model imports section
    - Add `from app.modules.ha import volume_sync_models as _volume_sync_models  # noqa: F401`
    - This ensures SQLAlchemy resolves the new models during `configure_mappers()`
    - _Requirements: 9.1, 9.2_

  - [x] 10.4 Write property test for disk-to-database migration round-trip
    - **Property 3: Disk-to-database migration round-trip**
    - **Validates: Requirements 3.1, 3.2, 3.3**

  - [x] 10.5 Write property test for migration idempotence
    - **Property 4: Migration idempotence**
    - **Validates: Requirements 3.5, 8.4, 9.3**

- [x] 11. Checkpoint — Verify startup integration
  - Restart the app container and verify branding migration runs on startup and volume sync task starts if configured, ask the user if questions arise.

- [x] 12. Add Volume Data Replication section to HA Replication frontend page
  - [x] 12.1 Add TypeScript interfaces for volume sync API responses in `frontend/src/pages/admin/HAReplication.tsx`
    - Add `VolumeSyncConfig`, `VolumeSyncStatus`, `VolumeSyncHistoryEntry` interfaces
    - _Requirements: 7.1_

  - [x] 12.2 Add volume sync state variables and fetch logic
    - Add state for `volumeSyncConfig`, `volumeSyncStatus`, `volumeSyncHistory`, `syncSaving`, `syncTriggering`
    - Fetch volume sync data in the existing `fetchData` callback alongside HA data
    - Use `safeFetch` with proper fallbacks (`?? []`, `?? 0` patterns)
    - Poll status every 10 seconds (same interval as existing HA polling)
    - _Requirements: 7.8, 7.9_

  - [x] 12.3 Add Volume Data Replication configuration form section
    - Fields: standby SSH host, SSH port, SSH key path, remote upload path, remote compliance path, sync interval, enable/disable toggle
    - Save button calls `PUT /api/v1/ha/volume-sync/config`
    - Display success/error messages on save
    - _Requirements: 7.2, 7.3_

  - [x] 12.4 Add sync status card and Sync Now button
    - Display: last sync time, result badge (success/failure), next scheduled sync, file count, total size
    - "Sync Now" button triggers `POST /api/v1/ha/volume-sync/trigger`
    - Show spinner while sync in progress, disable button during sync
    - _Requirements: 7.4, 7.5, 7.7_

  - [x] 12.5 Add sync history table
    - Columns: Time, Status, Files, Bytes, Duration, Error
    - Fetch from `GET /api/v1/ha/volume-sync/history`
    - Use `?.` and `?? []` on all response data
    - _Requirements: 7.6, 7.9_

  - [x] 12.6 Rebuild frontend in Docker
    - Execute: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend npx vite build`
    - _Requirements: 7.1_

- [x] 13. Checkpoint — Verify frontend volume sync section
  - Ensure the HA Replication page displays the new Volume Data Replication section with config form, status card, sync button, and history table, ask the user if questions arise.

- [x] 14. Update Docker Compose files for uploads volume mount
  - [x] 14.1 Add `app_uploads` volume mount to the base `docker-compose.yml` app service
    - Add `- app_uploads:/app/uploads` to the app service volumes
    - The `app_uploads` volume is already declared in the volumes section
    - _Requirements: 10.1_

  - [x] 14.2 Verify `docker-compose.pi.yml` already mounts `app_uploads` volume
    - Confirm `app_uploads:/app/uploads` is present in the pi app service volumes
    - _Requirements: 10.2_

  - [x] 14.3 Verify `docker-compose.ha-standby.yml` mounts `standby_uploads` volume
    - Confirm `standby_uploads:/app/uploads` is present in the standby app service volumes
    - _Requirements: 10.3_

- [x] 15. Write end-to-end test script
  - [x] 15.1 Create `scripts/test_file_storage_replication_e2e.py`
    - Login as global_admin
    - Upload a logo via branding endpoint, verify it's served from DB with correct Content-Type
    - Upload a favicon, verify content type header
    - Save volume sync config, verify it persists via GET
    - Trigger manual sync (will fail without actual standby — verify history records failure)
    - Verify status endpoint returns expected shape
    - Verify history endpoint returns entries in descending order
    - Verify non-admin gets 403 on volume sync endpoints
    - Follow `scripts/test_*_e2e.py` pattern with `TEST_E2E_` prefix for test data
    - MANDATORY cleanup of all test data in `finally` block
    - Include OWASP security checks: broken access control, injection payloads in text fields
    - _Requirements: 1.4, 2.1, 4.3, 4.4, 5.6, 6.1, 6.2, 6.4_

- [x] 16. Final checkpoint — Ensure all tests pass
  - Run all property-based tests for this feature
  - Run the e2e test script: `docker exec invoicing-app-1 python scripts/test_file_storage_replication_e2e.py`
  - Verify no regressions in existing branding tests
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation between major sections
- Property tests validate the 7 correctness properties from the design document
- Unit tests and property tests use Hypothesis (already in the project)
- The e2e test follows the project's `scripts/test_*_e2e.py` pattern with mandatory cleanup
- After creating migrations (tasks 1.1, 2.1), the migration MUST be run immediately per the database-migration-checklist steering
- All frontend code must use `?.` and `?? []` / `?? 0` patterns per safe-api-consumption steering
- Use `flush()` not `commit()` in service functions — `session.begin()` auto-commits
