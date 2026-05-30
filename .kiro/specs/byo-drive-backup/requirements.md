# Requirements Document — BYO Google Drive Backup

## Introduction

Allow each organisation to connect their own Google Drive account and have OraInvoice automatically back up their database slice and customer files (uploads, compliance docs, attachments) to that Drive on a configurable schedule. Restore is per-organisation, with an admin-browsable tree of customers and asset types so a destroyed customer record can be selectively recovered without disturbing the rest of the org's data.

The backup workload runs against the **standby PostgreSQL replica** (the peer postgres in the existing HA topology), never against the primary postgres serving live traffic. If the standby is unreachable for longer than a configured staleness threshold, the system falls back to running the backup against the primary so that backup continuity is preserved.

Backup execution is decoupled from the API process. In v1 it runs on the in-process scheduler with concurrency caps; once organisation count crosses a threshold (initially 50), it is promoted to a dedicated worker container. The v1 design and database schema are explicitly written so that the v2 worker promotion is a configuration change, not a code rewrite.

## Glossary

- **BYO_Drive**: An organisation's own Google Drive account connected via OAuth, into which their backups are written
- **Backup_Worker**: The component that produces and uploads backups. In v1 it is the in-process scheduler in `app/tasks/scheduled.py`; in v2 it is a separate container (`app/workers/backup_worker.py`)
- **Backup_Source_DB**: The postgres instance the worker reads from when producing the database slice. Defaults to the standby replica; falls back to primary if the standby is unhealthy
- **Snapshot**: A single completed backup run consisting of three encrypted artifacts in the org's Drive folder: `db.sql.zst.enc`, `files.tar.zst.enc`, and `manifest.json.enc`
- **Manifest**: A JSON document inside each snapshot describing the customer/invoice/quote/job-card/attachment inventory for that snapshot, used to drive the selective restore UI
- **Org_Backup_Config**: The per-organisation configuration row storing the OAuth refresh token, Drive folder ID, schedule, retention, and alert recipients
- **Backup_Run**: A single attempted backup, with status (`running`, `succeeded`, `failed`), start/end timestamps, byte sizes, drive file IDs, and any error message
- **Restore_Job**: A single attempted restore, with the snapshot ID, the selected customer IDs and asset types, status, and outcome
- **Org_Admin**: A user with `role = 'org_admin'` for the target organisation
- **Drive_File_Scope**: The OAuth scope `https://www.googleapis.com/auth/drive.file`, granting the app access only to files it creates in the user's Drive — no access to existing user files

## Requirements

### Requirement 1: Google Drive OAuth Connection (per org)

**User Story:** As an org admin, I want to connect my own Google Drive to OraInvoice using my Google account, so that backups of my organisation's data are stored in storage I own and control.

#### Acceptance Criteria

1. THE Frontend SHALL provide a "Connect Google Drive" action in the organisation Settings under a "Backups" section, visible only to users with role `owner` or `org_admin`
2. WHEN the user clicks "Connect Google Drive", THE Backend SHALL generate an OAuth 2.0 authorization URL with `scope=https://www.googleapis.com/auth/drive.file` and `access_type=offline` and `prompt=consent`
3. THE OAuth flow SHALL use a single platform-level Google Cloud project's `client_id` and `client_secret` stored encrypted in `integration_configs.gdrive`
4. THE OAuth callback SHALL exchange the authorization code for `access_token` and `refresh_token`, store the `refresh_token` envelope-encrypted in `org_backup_configs.refresh_token_encrypted`, and create or reuse a folder named `OraInvoice Backups` in the user's Drive root
5. THE Backend SHALL store the resolved Drive `folder_id` in `org_backup_configs.drive_folder_id`
6. WHEN the OAuth callback returns a non-success response from Google, THE Backend SHALL display an error to the user and SHALL NOT persist any partial configuration row
7. WHEN an org admin clicks "Disconnect Google Drive", THE Backend SHALL revoke the refresh token via Google's revocation endpoint, delete the `org_backup_configs` row for that org, and disable scheduling for that org
8. THE Backend SHALL NEVER request scopes beyond `drive.file`; this avoids Google's restricted-scope verification process
9. WHEN the OAuth refresh token is rejected by Google during a scheduled backup, THE Backend SHALL mark the connection as `expired`, dispatch an alert to the org admin recipients, and stop scheduling further backups until the user reconnects

### Requirement 2: Per-Org Backup Schedule and Retention

**User Story:** As an org admin, I want to choose how often my org is backed up and how long old backups are kept, so that I can balance recovery point objective against my Drive storage budget.

#### Acceptance Criteria

1. THE Org_Backup_Config row SHALL include `schedule_cron` (string, e.g. `0 2 * * *` for daily 02:00), `retention_days` (integer, 7–365), `enabled` (boolean), and `paused_until` (nullable timestamp)
2. THE Frontend SHALL allow the org admin to choose from preset schedules ("Daily 02:00", "Every 12 hours", "Every 6 hours", "Weekly Sunday 02:00") and custom cron, with all times displayed and stored in NZST/NZDT
3. WHEN `paused_until` is set to a future timestamp, THE Backup_Worker SHALL NOT enqueue runs for that org until the timestamp has passed
4. WHEN the worker computes the next-run time for an org, THE Backup_Worker SHALL apply a sticky per-org offset of `hash(org_id) % schedule_window_seconds` so that 500 orgs configured for "Daily 02:00" are spread evenly across the configured window (default 60 minutes)
5. THE Frontend SHALL display the next scheduled backup time and the most recent backup status (succeeded/failed/running) in the Settings → Backups view
6. WHEN `retention_days` elapses for a snapshot, THE Backup_Worker SHALL delete the snapshot's three Drive files via the Drive API and remove the corresponding `backup_runs` row from history view
7. WHEN retention deletion fails for a Drive file, THE Backup_Worker SHALL retain the `backup_runs` row, mark the run with `retention_status = 'delete_failed'`, log the failure, and retry on the next worker cycle

### Requirement 3: Database Slice (Standby-Sourced)

**User Story:** As a platform operator, I want each org's backup database slice to be produced from the standby postgres replica, so that backup workload never touches the primary postgres serving live API traffic.

#### Acceptance Criteria

1. THE Backup_Worker SHALL connect to the database URL specified in the `BACKUP_SOURCE_URL` environment variable for all backup-related read queries
2. WHEN `BACKUP_SOURCE_URL` is not set, THE Backup_Worker SHALL fall back to `DATABASE_URL` and SHALL log a warning at WARN level on every startup
3. WHEN the standby replica is reachable but the replication lag exceeds `BACKUP_MAX_LAG_SECONDS` (default 600), THE Backup_Worker SHALL fall back to `BACKUP_SOURCE_FALLBACK_URL` (the primary) for that backup attempt and SHALL annotate the `backup_runs` row with `source = 'primary_fallback'`
4. WHEN the standby replica is unreachable (connection refused or timeout > 30s), THE Backup_Worker SHALL fall back to `BACKUP_SOURCE_FALLBACK_URL` and SHALL annotate the row with `source = 'primary_fallback'`
5. THE Backup_Worker SHALL run all per-org export queries inside a `REPEATABLE READ` transaction so that the slice is consistent across tables for the duration of the dump
6. THE Backup_Worker SHALL emit one `COPY (SELECT ... WHERE org_id = :org_id) TO STDOUT` per org-scoped table, streaming the output through `zstd -3` to a temporary file in the worker's `/tmp` volume
7. THE per-org table inventory SHALL be derived at runtime from the `org_id` foreign key declared on each SQLAlchemy model in `app.models` so that newly added tables are picked up automatically without code changes
8. THE Backup_Worker SHALL skip system tables and tables without an `org_id` column, and SHALL log them with `[skipped: no org_id column]` in the run log
9. THE Backup_Worker SHALL complete the database slice for a single org with up to 100,000 invoices and 10,000 customers in under 5 minutes when run against a healthy standby

### Requirement 4: File Slice (Per-Org Tarball)

**User Story:** As an org admin, I want every customer file uploaded for my org included in each backup, so that a restore can put files back exactly as they were.

#### Acceptance Criteria

1. THE Backup_Worker SHALL include in each org's tarball every file under `/app/uploads/{category}/{org_id}/` and `/app/compliance_files/{org_id}/` where `{org_id}` matches the target org
2. THE Backup_Worker SHALL stream the tarball through `tar | zstd -3 | envelope_encrypt` to a temporary file before upload, with peak memory usage bounded to under 256 MB regardless of org file count
3. THE Backup_Worker SHALL skip files that fail to read (permission errors, broken symlinks) and SHALL record the skipped paths in the run log with severity WARN
4. WHEN the worker container is colocated with the standby host, THE Backup_Worker SHALL read files from the rsync-replicated copy populated by `app/modules/ha/volume_sync_service.py`
5. WHEN the worker container is colocated with the primary host (rare), THE Backup_Worker SHALL read files directly from the primary's volume mounts
6. THE Backup_Worker SHALL include a top-level `_meta/version.txt` and `_meta/created_at.txt` in every tarball describing the OraInvoice app version and snapshot timestamp

### Requirement 5: Manifest Generation

**User Story:** As an org admin restoring a snapshot, I want to browse my customers and pick exactly which ones to restore, so that I do not have to overwrite my entire org to recover one record.

#### Acceptance Criteria

1. THE Backup_Worker SHALL produce a `manifest.json` document for every snapshot with the schema documented in `design.md`, including for each customer the customer ID, name, customer code, and the IDs of every invoice, quote, job card, payment, and credit note linked to that customer, plus the file keys of every attachment owned by that customer
2. THE Manifest SHALL include a top-level summary block with the snapshot timestamp, app version, total customer count, total file count, total db row count, and a SHA-256 hash of the database slice file
3. THE Manifest SHALL include a list of org-level entities (settings, branding files, integration configs) that are not customer-scoped but are part of the backup
4. THE Backup_Worker SHALL envelope-encrypt the `manifest.json` to `manifest.json.enc` before upload
5. THE Manifest SHALL be small enough (target under 5 MB for an org with 10,000 customers) to be downloaded fully by the restore UI without paging

### Requirement 6: Snapshot Upload to Drive

**User Story:** As an org admin, I want my backups uploaded reliably to my own Drive folder, so that snapshots are durable even if the OraInvoice host fails.

#### Acceptance Criteria

1. THE Backup_Worker SHALL upload the three artifact files (`db.sql.zst.enc`, `files.tar.zst.enc`, `manifest.json.enc`) into a per-snapshot subfolder named `snapshot-{ISO_TIMESTAMP}` inside the org's `OraInvoice Backups` Drive folder
2. THE Backup_Worker SHALL use Google Drive's resumable upload API with 8 MB chunks and resume on failure for up to 3 attempts per file
3. THE Backup_Worker SHALL NOT delete the local temporary files until all three uploads have completed and Google has returned a final 200 response with a non-empty `id` for each
4. WHEN any of the three uploads fails after retries, THE Backup_Worker SHALL delete any partially uploaded files in the snapshot folder, mark the `backup_runs` row as `failed` with the underlying error, and dispatch a failure alert
5. WHEN the user's Drive is full (storage quota error), THE Backup_Worker SHALL mark the run with `error_code = 'drive_quota_exceeded'`, dispatch a distinct alert template, and pause further backups for that org for 24 hours
6. THE Backup_Worker SHALL set the Drive file's `properties` metadata to include `org_id`, `snapshot_id`, `app_version`, and `artifact_type` for forensic traceability

### Requirement 7: Backup History and Audit

**User Story:** As an org admin, I want to see the history of my backup runs and what they contained, so that I can verify backups are working and find the right snapshot to restore from.

#### Acceptance Criteria

1. THE Backend SHALL expose `GET /api/v1/backups/runs` returning a paginated list of `backup_runs` for the caller's org, ordered by `started_at` descending, with offset/limit pagination as `{items: [...], total: N}`
2. THE Backup_Run record SHALL include `id`, `org_id`, `started_at`, `finished_at`, `status`, `source` (standby/primary_fallback), `db_size_bytes`, `files_size_bytes`, `manifest_size_bytes`, `customer_count`, `file_count`, `drive_snapshot_folder_id`, `error_code`, `error_message`, `triggered_by` (scheduled/manual)
3. THE Backend SHALL expose `POST /api/v1/backups/runs/manual` to trigger an on-demand backup for the caller's org, returning 202 Accepted with the `run_id`
4. THE Backend SHALL expose `GET /api/v1/backups/runs/{run_id}` returning the run's metadata plus the manifest summary (counts, not the full manifest)
5. THE Backend SHALL expose `GET /api/v1/backups/runs/{run_id}/manifest` returning the decrypted manifest JSON, gated by org admin role
6. THE Backend SHALL log every successful backup, every failure, and every restore action to the existing `audit_logs` table with appropriate `entity_type` and `action` fields
7. THE Backend SHALL rate-limit manual backup triggers to one per org per 15 minutes to prevent abuse

### Requirement 8: Backup Failure Alerts

**User Story:** As an org admin, I want to be notified when a backup fails, so that I can fix the cause before the next scheduled run.

#### Acceptance Criteria

1. THE Org_Backup_Config row SHALL include `alert_emails` (text[]) and `alert_in_app` (boolean, default true) and `alert_failures_only` (boolean, default true)
2. WHEN `alert_emails` is empty, THE Backup_Worker SHALL default to sending alerts to the org's primary `org_admin` and `owner` users
3. WHEN a backup run fails for any reason, THE Backup_Worker SHALL dispatch an email using the `backup_failed` template via the existing `app/tasks/notifications.py` pipeline within 60 seconds of the failure
4. WHEN a backup run fails, THE Backup_Worker SHALL also dispatch an in-app notification via `app/modules/notifications/service.py` so that the next time the user logs into OraInvoice they see the failure
5. WHEN `alert_failures_only` is false, THE Backup_Worker SHALL also dispatch a "backup succeeded" notification with the snapshot summary
6. WHEN three consecutive backup runs for the same org fail, THE Backup_Worker SHALL escalate by emailing all `owner` users for that org and setting `consecutive_failure_count` on the config so the Settings UI can render a banner
7. THE Notification_Service SHALL register `backup_failed`, `backup_succeeded`, `backup_drive_quota_exceeded`, and `backup_oauth_revoked` as new template types in the existing template registry

### Requirement 9: Selective Restore — Browsing

**User Story:** As an org admin recovering data, I want to browse the contents of any of my snapshots and pick exactly what to restore, so that I do not damage current data when recovering one customer.

#### Acceptance Criteria

1. THE Frontend SHALL expose a `Restore` page reachable from `Settings → Backups → Restore`, visible only to `owner` and `org_admin`
2. THE Restore page SHALL list every snapshot in the org's Drive folder ordered by snapshot timestamp descending, with status badges and size totals
3. WHEN the user selects a snapshot, THE Frontend SHALL fetch the manifest via `GET /api/v1/backups/runs/{run_id}/manifest` and render a tree view: Customer → (Invoices, Quotes, Job Cards, Attachments)
4. THE Restore tree SHALL support search (by customer name, customer code, invoice number, vehicle plate) and pagination at the customer node level (page size 50)
5. THE Frontend SHALL allow the user to select one or more customers, and for each selected customer, optionally restrict to specific asset types (invoices only, attachments only, etc.)
6. THE Frontend SHALL display a preview pane showing the selected counts (e.g. "3 customers, 47 invoices, 18 attachments") and the resulting restore mode

### Requirement 10: Selective Restore — Execution

**User Story:** As an org admin recovering a customer, I want the restore to insert their data without overwriting current records, so that I do not lose any work that has happened since the snapshot was taken.

#### Acceptance Criteria

1. THE Backend SHALL expose `POST /api/v1/backups/runs/{run_id}/restore` accepting `{customer_ids: [uuid], asset_types: [string], conflict_policy: 'restore_as_copy' | 'skip_existing'}`
2. THE default conflict policy SHALL be `restore_as_copy`: every restored row receives a freshly minted UUID, and references between restored rows (invoice → customer, line_item → invoice) are rewritten to use the new UUIDs so that referential integrity is preserved
3. WHEN `conflict_policy = 'skip_existing'`, THE Restore_Service SHALL check if a row with the original UUID exists in the target org and SHALL skip insert without erroring
4. THE Restore_Service SHALL execute the restore inside a single database transaction so that a partial failure rolls back atomically
5. THE Restore_Service SHALL re-write every restored attachment's `file_key` to a new path under `/app/uploads/{category}/{org_id}/{new_uuid}.{ext}` and copy the encrypted bytes from the snapshot tarball into that path
6. THE Restore_Service SHALL NOT permit cross-org restore: the snapshot's `org_id` must match the caller's `org_id` or the request returns 403
7. THE Restore_Service SHALL produce a `restore_jobs` record with status, started_at, finished_at, summary counts, and any per-row errors
8. THE Restore_Service SHALL be rate-limited to one in-progress restore per org at a time (subsequent requests return 409 Conflict)
9. WHEN the restore inserts rows that have FK relationships beyond the selected scope (e.g. a chosen invoice references a vehicle not in the customer's selection), THE Restore_Service SHALL transitively include the dependent rows in the restore unless they already exist in the target org

### Requirement 11: Concurrency, Staggering, and Worker Capacity

**User Story:** As a platform operator, I want the backup process to scale to 500 orgs without degrading API performance, so that backups remain reliable as the customer base grows.

#### Acceptance Criteria

1. THE Backup_Worker SHALL enforce a global concurrency cap configured by `BACKUP_MAX_CONCURRENCY` (default 4 in v1, 8 in v2) using an asyncio semaphore
2. THE Backup_Worker SHALL acquire a Redis-based lease for each org's backup with TTL = max_run_duration (default 1 hour) so that two workers cannot back up the same org simultaneously
3. THE Backup_Worker SHALL skip backup for an org whose previous run is still in-progress and SHALL log this event without raising an alert
4. WHEN the in-process scheduler accumulates more than `BACKUP_PROMOTION_THRESHOLD_ORGS` (default 50) eligible orgs, THE Backend SHALL log a WARN-level message recommending promotion to the standalone worker container
5. THE v2 Worker container SHALL be runnable with `docker compose -f docker-compose.yml -f docker-compose.worker-backup.yml up -d` and SHALL share the existing `app_uploads` volume read-only and the existing Redis instance
6. THE v2 Worker container SHALL run on the standby host (not primary) by default, taking over from the primary if the primary's heartbeat indicates it is the only live node

### Requirement 12: Security and Encryption

**User Story:** As an org admin, I want to be confident that even if my Drive credentials leak, my backed-up data remains unreadable, so that I can trust the backup feature with sensitive customer information.

#### Acceptance Criteria

1. THE Backup_Worker SHALL envelope-encrypt every artifact (`db.sql.zst`, `files.tar.zst`, `manifest.json`) using the existing `app.core.encryption.envelope_encrypt` helper before upload
2. THE encryption key (KEK) SHALL be the platform's existing `ENCRYPTION_MASTER_KEY` so that restore can decrypt by reversing the same path
3. THE Backup_Worker SHALL NOT write the OAuth `access_token` to disk and SHALL only hold it in memory for the duration of a single Drive API call
4. THE OAuth `refresh_token` SHALL be stored envelope-encrypted in `org_backup_configs.refresh_token_encrypted` and SHALL never appear in logs
5. THE Restore_Service SHALL verify the SHA-256 hash recorded in the manifest matches the decrypted `db.sql.zst` content before applying any rows
6. WHEN a hash mismatch is detected, THE Restore_Service SHALL abort the restore, mark the `restore_jobs` row as `failed` with `error_code = 'integrity_check_failed'`, and dispatch an alert
7. THE Backup_Worker SHALL log Drive API requests at INFO level with the request URL and response status only — never with body content, headers, or tokens
8. THE Backend SHALL reject any attempt to upload, list, or restore a backup via API for an org whose user does not have role `owner` or `org_admin`

### Requirement 13: Storage Footprint Visibility

**User Story:** As an org admin, I want to see how much of my Drive my backups are using, so that I can adjust retention before I run out of space.

#### Acceptance Criteria

1. THE Backend SHALL expose `GET /api/v1/backups/storage` returning the sum of bytes across all snapshots in the org's Drive folder, the count of snapshots, and the user's overall Drive quota usage and limit (from Drive's `about` endpoint)
2. THE Frontend SHALL display the storage summary on the Backups Settings page with a progress bar and the warning threshold at 80% used
3. WHEN Drive quota usage exceeds 95%, THE Backup_Worker SHALL dispatch a `backup_drive_quota_warning` notification on the next run
4. THE Frontend SHALL surface a "Reduce retention" CTA when usage is over 80%, linking to the schedule/retention editor

### Requirement 14: Cancellation and Pause

**User Story:** As an org admin, I want to cancel a running backup and pause future ones, so that I can perform maintenance or troubleshoot a problem without flooding my Drive.

#### Acceptance Criteria

1. THE Backend SHALL expose `POST /api/v1/backups/runs/{run_id}/cancel` returning 200 if the run was cancelled or 409 if the run had already completed
2. WHEN a run is cancelled mid-upload, THE Backup_Worker SHALL delete any partially uploaded files in the snapshot folder and mark the run as `cancelled`
3. THE Backend SHALL expose `PATCH /api/v1/backups/config` accepting `{paused_until?: ISO_DATETIME, enabled?: bool}` for pause/resume
4. WHEN `enabled = false`, THE Frontend Settings page SHALL display "Backups paused" with a Resume button and SHALL NOT show the next-run countdown

### Requirement 15: Backward Compatibility and Rollout

**User Story:** As a platform operator, I want to deploy this feature without breaking existing orgs that have not connected a Drive, so that adoption can be gradual.

#### Acceptance Criteria

1. THE feature SHALL be off by default for every org until the org admin completes the OAuth connect flow
2. THE Alembic migration SHALL add `org_backup_configs`, `backup_runs`, and `restore_jobs` tables; orgs without a config row are simply skipped by the worker
3. THE feature SHALL be gated by a `feature_flags` row `byo_drive_backup` so that platform admins can disable it across all orgs in case of incident
4. WHEN the feature flag is off, THE Frontend Settings → Backups section SHALL render a "This feature is currently unavailable" message rather than the connect button
5. THE existing platform-level backup scripts (`scripts/update.sh`, `scripts/deploy-prod.sh`) SHALL remain unchanged and SHALL NOT be affected by this feature
