# Implementation Plan — BYO Google Drive Backup

Tasks are grouped into phases that can ship independently. Each task references the requirement IDs it satisfies and is sized in dev-days (1 dev-day ≈ 6 focused hours including tests).

Overall estimate: **17–20 dev-days for v1 (in-process scheduler)**. Add **+3.5 dev-days** to promote to the dedicated worker container in v2.

---

## Phase 1 — Foundation (3.5d)

- [ ] **1.1** Create Alembic migration `0195_byo_drive_backup` adding `org_backup_configs`, `backup_runs`, `restore_jobs` tables with indexes and constraints — _Req 2, 7, 10, 15_ — **0.75d**
- [ ] **1.2** Add SQLAlchemy models `OrgBackupConfig`, `BackupRun`, `RestoreJob` in `app/modules/backups/models.py` and register them in `app.models` — _Req 2, 7_ — **0.5d**
- [ ] **1.3** Add `feature_flags` row `byo_drive_backup` (off by default) and helper `is_byo_drive_backup_enabled()` in `app/core/feature_flags.py` — _Req 15_ — **0.25d**
- [ ] **1.4** Create `integration_configs.gdrive` row schema (Pydantic) for storing platform OAuth client_id/client_secret encrypted; add to Global Admin Integrations page — _Req 1_ — **0.5d**
- [ ] **1.5** Add Pydantic schemas in `app/modules/backups/schemas.py` for config, runs, restore jobs, manifest — _Req 1, 2, 7, 10_ — **0.5d**
- [ ] **1.6** Add `BACKUP_SOURCE_URL`, `BACKUP_SOURCE_FALLBACK_URL`, `BACKUP_MAX_LAG_SECONDS`, `BACKUP_MAX_CONCURRENCY`, `BACKUP_PROMOTION_THRESHOLD_ORGS` to `app/config.py` (settings) and `.env.example` — _Req 3, 11_ — **0.25d**
- [ ] **1.7** Write unit tests for the new SQLAlchemy models — basic CRUD via test fixtures — **0.5d**
- [ ] **1.8** Run Alembic migration in Dev, verify schema, fix any issues — **0.25d**

## Phase 2 — Google Drive Integration (3.0d)

- [ ] **2.1** Implement `app/integrations/gdrive.py`:
  - `build_authorization_url(state, redirect_uri)` returning the Google OAuth URL with `drive.file` scope and `prompt=consent` — _Req 1_
  - `exchange_code_for_tokens(code, redirect_uri)` returning `{access_token, refresh_token, expires_in, email}` — _Req 1_
  - `refresh_access_token(refresh_token)` returning new `access_token` — _Req 1, 12_
  - `revoke_token(refresh_token)` calling Google's revocation endpoint — _Req 1_
  - **1.0d**
- [ ] **2.2** Implement Drive folder operations:
  - `find_or_create_folder(access_token, name, parent_id=None)` — _Req 1, 6_
  - `delete_file(access_token, file_id)` — _Req 2_
  - `list_snapshots(access_token, folder_id)` returning subfolders ordered by name — _Req 9_
  - `get_about(access_token)` returning Drive quota/usage — _Req 13_
  - **0.5d**
- [ ] **2.3** Implement resumable upload helper:
  - `upload_file_resumable(access_token, parent_id, name, file_path, properties, chunk_size=8MiB)` with exponential backoff retry — _Req 6_
  - **0.75d**
- [ ] **2.4** Implement `app/integrations/gdrive.py` integration tests using `httpx_mock` — verify chunk-by-chunk upload, resume on transient failures, retry caps — **0.5d**
- [ ] **2.5** Verify Drive client doesn't log secrets at any log level (audit pass) — _Req 12_ — **0.25d**

## Phase 3 — Per-Org Logical Exporter (3.0d)

- [ ] **3.1** Implement `app/modules/backups/org_exporter.py::discover_org_scoped_tables()` — walks `Base.metadata.sorted_tables`, classifies as direct/transitive/global, returns ordered list — _Req 3_ — **1.0d**
- [ ] **3.2** Implement `OrgExporter.export_to_csv(org_id, output_path, source_db_url)`:
  - Opens REPEATABLE READ transaction on source DB
  - For each org-scoped table, executes `COPY (SELECT ... WHERE ...) TO STDOUT WITH CSV HEADER`
  - Writes table boundary markers (`__ORAINVOICE_TABLE__`)
  - Streams output through zstd compression
  - Computes SHA-256 in flight
  - _Req 3, 12_
  - **1.0d**
- [ ] **3.3** Implement source DB selection logic in `app/modules/backups/runner.py::resolve_source_db_url()`:
  - Try standby URL first
  - Check replication lag via `pg_last_wal_receive_lsn()` query
  - Fall back to primary if lag > threshold or connection fails
  - Annotate run with `source` field
  - _Req 3_
  - **0.5d**
- [ ] **3.4** Unit tests:
  - Discovery returns expected counts for known fixtures
  - Transitive table slicing query is well-formed
  - SHA-256 matches independent compute
  - Fallback triggers on connection refused
  - **0.5d**

## Phase 4 — Manifest, Files Tarball, Encryption (2.0d)

- [ ] **4.1** Implement `app/modules/backups/manifest.py::build_manifest(org_id, db)`:
  - Queries customers + transitive entities for the org
  - Builds the customer→assets graph
  - Computes summary block (counts)
  - Returns `Manifest` dataclass / Pydantic model
  - _Req 5_
  - **0.75d**
- [ ] **4.2** Implement `app/modules/backups/runner.py::build_files_tarball(org_id, output_path)`:
  - Walks `/app/uploads/*/{org_id}/` and `/app/compliance_files/{org_id}/`
  - Streams `tar | zstd` to output_path
  - Adds `_meta/version.txt` and `_meta/created_at.txt`
  - Records skipped files with WARN log
  - _Req 4_
  - **0.5d**
- [ ] **4.3** Wire envelope encryption around each artifact:
  - `_encrypt_file(in_path, out_path)` using existing `app.core.encryption.envelope_encrypt`
  - Verify decrypt round trip preserves bytes
  - _Req 12_
  - **0.25d**
- [ ] **4.4** Unit tests for manifest builder (fixed org seed → known manifest), tarball builder (mock filesystem), encryption round trip — **0.5d**

## Phase 5 — Backup Pipeline (Runner) (2.5d)

- [ ] **5.1** Implement `app/modules/backups/runner.py::run_backup(config_id) -> BackupRun`:
  - Acquire Redis lock `backup:run:{org_id}` (TTL 1h, returns False if held)
  - Insert `backup_runs` row with status=running
  - Resolve source DB URL
  - Export DB slice → encrypted file
  - Build files tarball → encrypted file
  - Build manifest → encrypted file
  - Find/create org's Drive folder
  - Create `snapshot-{ts}` subfolder
  - Upload all three artifacts (resumable)
  - Update `backup_runs` row with sizes, file IDs, status=succeeded
  - Update `org_backup_configs.last_run_*` and `next_run_at`
  - Cleanup temp files
  - On error: set status=failed, error_code, error_message; cleanup partial Drive files
  - _Req 3, 4, 5, 6, 11, 12_
  - **1.0d**
- [ ] **5.2** Implement OAuth refresh handling inside runner:
  - Decrypt refresh_token from config row
  - Refresh access_token at start of run
  - On 401 from Drive after refresh, mark connection_status='expired' and dispatch `backup_oauth_revoked` alert
  - _Req 1, 8_
  - **0.5d**
- [ ] **5.3** Implement Drive quota error path:
  - Detect `storageQuotaExceeded` error code
  - Mark error_code='drive_quota_exceeded'
  - Dispatch `backup_drive_quota_exceeded` alert
  - Set `paused_until = now + 24h`
  - _Req 6, 8_
  - **0.25d**
- [ ] **5.4** Implement consecutive-failure escalation in runner: increment `consecutive_failure_count` on failure; reset on success; dispatch escalation alert at threshold 3 — _Req 8_ — **0.25d**
- [ ] **5.5** Integration test: end-to-end backup against a docker-compose'd test postgres + mock Drive — assert artifacts uploaded with correct properties — **0.5d**

## Phase 6 — Scheduler Integration (1.0d)

- [ ] **6.1** Add `byo_drive_backup_task()` to `app/tasks/scheduled.py`:
  - Query `org_backup_configs WHERE enabled AND (paused_until IS NULL OR paused_until < now()) AND next_run_at <= now()`
  - Apply asyncio.Semaphore(BACKUP_MAX_CONCURRENCY)
  - For each due config, invoke runner with timeout
  - Log promotion-recommendation when eligible-org count > threshold
  - **Do not** add to `WRITE_TASKS` (writes happen via runner's own session, not source DB)
  - _Req 11_
  - **0.5d**
- [ ] **6.2** Implement sticky per-org offset in `next_run_at` computation:
  - `offset_seconds = hash(org_id) % schedule_window_seconds`
  - Apply offset to next cron occurrence
  - _Req 2_
  - **0.25d**
- [ ] **6.3** Integration test: seed 20 configs all on Daily 02:00, advance time, assert distribution — **0.25d**

## Phase 7 — Restore Service (3.5d)

- [ ] **7.1** Implement `app/modules/backups/restore_service.py::RestoreService`:
  - `download_artifacts(run_id, work_dir)` → fetch + decrypt three artifacts
  - `verify_integrity(manifest, db_path)` → SHA-256 check, abort on mismatch
  - _Req 9, 12_
  - **0.5d**
- [ ] **7.2** Implement closure computation:
  - `compute_closure(manifest, customer_ids, asset_types) -> set[(table, row_id)]`
  - Walk FK graph for transitive deps
  - _Req 10_
  - **0.75d**
- [ ] **7.3** Implement DB row insertion:
  - `restore_rows(closure, db_csv_reader, conflict_policy, target_org_id)` in a single transaction
  - For `restore_as_copy`: mint new UUIDs, build `old_id→new_id` map per table, rewrite outgoing FKs in dependent rows
  - For `skip_existing`: use `INSERT ... ON CONFLICT DO NOTHING`
  - _Req 10_
  - **1.0d**
- [ ] **7.4** Implement file restore:
  - Extract selected file_keys from `files.tar.zst`
  - Write to `/app/uploads/{category}/{org_id}/{new_uuid}.{ext}`
  - Update corresponding `attachment_url` / `file_key` in already-inserted DB rows
  - _Req 10_
  - **0.5d**
- [ ] **7.5** Wire it together in `RestoreService.run(restore_job_id)`:
  - Acquire Redis lock `restore:{org_id}` (TTL 30 min)
  - Update `restore_jobs.status` through lifecycle
  - On success: dispatch `backup_succeeded` analog or custom `restore_completed` notification
  - **0.5d**
- [ ] **7.6** Property-based test for UUID rewriting consistency — Hypothesis fuzz over arbitrary FK graphs — **0.25d**

## Phase 8 — REST Endpoints (1.5d)

- [ ] **8.1** Implement `app/modules/backups/router.py` with all endpoints from the design table:
  - GET/PUT/PATCH `/config`
  - GET `/oauth/start`, POST `/oauth/callback`, POST `/oauth/disconnect`
  - GET `/runs`, GET `/runs/{run_id}`, GET `/runs/{run_id}/manifest`
  - POST `/runs/manual`, POST `/runs/{run_id}/cancel`, POST `/runs/{run_id}/restore`
  - GET `/restore-jobs/{job_id}`, GET `/storage`
  - All gated by `require_role('owner', 'org_admin')` and feature flag check
  - All array responses wrapped `{items, total}`
  - All write endpoints write to `audit_logs`
  - _Req 1, 7, 10, 13, 14_
  - **1.0d**
- [ ] **8.2** Add rate limiting on `POST /runs/manual` (1/15min/org) using existing rate-limit middleware — _Req 7_ — **0.25d**
- [ ] **8.3** Endpoint integration tests covering happy path + 403/404/409 cases — **0.25d**

## Phase 9 — Notifications and Alerts (1.0d)

- [ ] **9.1** Add notification templates: `backup_failed`, `backup_succeeded`, `backup_drive_quota_warning`, `backup_drive_quota_exceeded`, `backup_oauth_revoked` in `app/modules/notifications/templates/` — _Req 8_ — **0.5d**
- [ ] **9.2** Implement `_resolve_alert_recipients(config)`:
  - If `alert_emails` non-empty, use those
  - Else fall back to org's owner + org_admin users
  - _Req 8_
  - **0.25d**
- [ ] **9.3** Wire alert dispatch in runner success/failure paths — verify in-app + email both fire — **0.25d**

## Phase 10 — Frontend (3.5d)

- [ ] **10.1** Add routes and lazy imports for the four backup pages in `frontend/src/App.tsx`. Add `RequireOrgAdmin` guards. — _Req 1_ — **0.25d**
- [ ] **10.2** Add `Backups` entry to `OrgSettingsLayout` sidebar, gated by feature flag context — _Req 15_ — **0.25d**
- [ ] **10.3** Build `BackupsSettings.tsx` with all five cards (Connection, Schedule, Alerts, Storage, Recent Runs) — _Req 1, 2, 7, 8, 13_ — **1.0d**
- [ ] **10.4** Build `BackupsOAuthCallback.tsx` for the OAuth redirect handler — _Req 1_ — **0.25d**
- [ ] **10.5** Build `BackupsRestore.tsx` (snapshot list grid) — _Req 9_ — **0.5d**
- [ ] **10.6** Build `BackupsRestoreSnapshot.tsx` with manifest tree, customer search, asset-type checkboxes, conflict policy selector, restore confirm modal — _Req 9, 10_ — **1.0d**
- [ ] **10.7** Build modals: `DisconnectConfirmModal`, `RestoreConfirmModal`, `RunNowConfirmModal` — **0.25d**

## Phase 11 — Tests, Docs, Hardening (1.5d)

- [ ] **11.1** End-to-end Playwright test: connect Drive (mock OAuth), trigger manual run, view manifest, restore one customer — **0.5d**
- [ ] **11.2** Add `byo_drive_backup` entry to `docs/ISSUE_TRACKER.md` skeleton (for any issues found during dev) — **0.1d**
- [ ] **11.3** Write `.kiro/steering/backup-restore.md` capturing the standby-sourced rule and the per-org BYO model so future contributors don't accidentally point pg_dump at primary — **0.25d**
- [ ] **11.4** Add admin runbook to `docs/`: how to bulk-rotate platform OAuth client (when client_secret rotates), how to interpret error codes, how to manually delete a corrupt snapshot — **0.25d**
- [ ] **11.5** Manual QA pass with real Google Drive account on Dev environment — **0.4d**

## Phase 12 — v2 Worker Container Promotion (deferred, 3.5d)

Triggered when eligible-org count exceeds `BACKUP_PROMOTION_THRESHOLD_ORGS` (default 50) for sustained period.

- [ ] **12.1** Create `app/workers/__init__.py` and `app/workers/backup_worker.py`:
  - Async main loop reading due configs every 30s
  - Reuses `runner.run_backup()` and `restore_service.run_restore()` unchanged
  - Graceful shutdown on SIGTERM
  - **1.0d**
- [ ] **12.2** Add `docker-compose.worker-backup.yml` overlay (Pi PROD pair + Local Dev/Standby pair):
  - Mounts `app_uploads:/app/uploads:ro` and `compliance_files:/app/compliance_files:ro`
  - Connects to standby postgres via `BACKUP_SOURCE_URL`
  - Connects to existing Redis
  - Restart unless-stopped
  - **0.5d**
- [ ] **12.3** Add deployment script changes (`scripts/deploy-prod.sh`, sync to Pi) and update `.kiro/steering/project-overview.md` deployment table — **0.5d**
- [ ] **12.4** Disable `byo_drive_backup_task` in scheduler when worker container is detected (env var `BACKUP_WORKER_ENABLED=true`) to prevent dual execution — **0.25d**
- [ ] **12.5** Worker observability: structured JSON logs, Prometheus-style metrics endpoint (queue depth, runs-in-flight, last-success-timestamp-per-org) — **0.75d**
- [ ] **12.6** Load test: simulate 100 orgs with seeded data, verify worker completes daily window without backlog — **0.5d**

---

## Suggested merge order

1. Phase 1 + 2 + 9.1 — schema, Drive client, notification templates (can be reviewed independently)
2. Phase 3 + 4 — exporter and manifest (the heaviest novel logic)
3. Phase 5 + 6 — runner and scheduler wiring
4. Phase 7 — restore (depends on exporter format)
5. Phase 8 + 10 — endpoints and frontend (parallelizable across two engineers)
6. Phase 11 — hardening and ship
7. Phase 12 — promote when scale demands it

## Open questions to confirm before kicking off

- **OAuth client provisioning** — who owns the platform-level Google Cloud project and registers the OAuth consent screen? This affects which Google account the `client_id` belongs to.
- **NZ data residency** — `app/core/backup.py.APPROVED_REGIONS` flags Drive as multi-region. Confirm with stakeholders that the BYO model satisfies the residency requirement (org owns the storage). Document the answer in `requirements.md` Requirement 12.
- **Default schedule** — design assumes Daily 02:00 NZST. Confirm before shipping; could be Weekly to reduce Drive churn for free-tier orgs.
- **Restore default policy** — design defaults to `restore_as_copy`. Confirm; the alternative `skip_existing` is safer-by-default for some operators.
- **Worker host placement** — design assumes worker on standby host. Confirm Pi PROD's standby (Local) has spare capacity for the worker plus its existing standby workload.
