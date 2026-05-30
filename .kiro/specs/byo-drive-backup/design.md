# Design Document — BYO Google Drive Backup

## Overview

Per-org backup of OraInvoice data to each organisation's own Google Drive, with selective per-customer restore. The backup workload reads from the standby PostgreSQL replica (peer postgres in the existing HA topology) and never disturbs the primary. v1 runs in-process on the existing scheduler with concurrency caps; v2 splits into a dedicated worker container with the same code reused, only the runner changes.

## Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│  PRIMARY HOST (Pi PROD or Local Dev)                               │
│  ┌──────────────┐   ┌──────────────┐                               │
│  │  app (API)   │   │  postgres    │  ← live traffic only          │
│  └──────────────┘   └──────────────┘                               │
└─────────────────────────────┬──────────────────────────────────────┘
                              │  logical replication + rsync
┌─────────────────────────────▼──────────────────────────────────────┐
│  STANDBY HOST (Local Prod-Standby or Pi Dev-Standby)               │
│  ┌──────────────┐   ┌──────────────┐   ┌────────────────────────┐  │
│  │  app (warm)  │   │  postgres    │◄──┤  worker-backup (v2)    │  │
│  └──────────────┘   └──────────────┘   │  • per-org loop        │  │
│                                        │  • semaphore(N)        │  │
│                                        │  • Redis lease         │  │
│                                        └──────┬─────────────────┘  │
│                                               │                    │
│                       reads /app/uploads RO ──┘                    │
│                                                                    │
└─────────────────────────────┬──────────────────────────────────────┘
                              │  HTTPS (resumable upload)
                  ┌───────────▼──────────────┐
                  │  org_1's Google Drive    │
                  │   /OraInvoice Backups/   │
                  │     snapshot-{ts}/       │
                  │       db.sql.zst.enc     │
                  │       files.tar.zst.enc  │
                  │       manifest.json.enc  │
                  └──────────────────────────┘
                  ┌──────────────────────────┐
                  │  org_2's Google Drive    │   (independent OAuth,
                  │   /OraInvoice Backups/   │    independent Drive,
                  │     ...                  │    independent storage)
                  └──────────────────────────┘
```

### Why standby-sourced

- Primary postgres serves API traffic. pg_dump and per-org `COPY` queries are CPU- and I/O-heavy. Running them against primary would cause request latency spikes during backup windows (already documented as a concern in `app/core/backup.py`).
- Standby postgres receives every change via logical replication (`wal_level=logical` is set in `docker-compose.ha-standby.yml` and `docker-compose.standby-prod.yml`). It is a hot, byte-identical copy.
- The standby host is also where `app/modules/ha/volume_sync_service.py` rsyncs `/app/uploads/` to. The worker can read both DB and files locally with zero load on primary.

### Why per-org BYO Drive

- Storage cost is borne by the org (free 15 GB tier covers most small orgs).
- Drive's per-user API quota (20K req / 100s) is per *Google account*, so each org gets independent rate limiting — no cross-org contention.
- Compromise blast radius is one org at a time.
- `drive.file` scope avoids Google's restricted-scope verification process. We never see the user's other Drive files.
- Restore browsing is naturally scoped — no risk of one org seeing another's manifest.

### v1 vs v2 runner

| Aspect | v1 (in-process scheduler) | v2 (worker container) |
|---|---|---|
| Code location | `app/tasks/scheduled.py:_DAILY_TASKS` adds `byo_drive_backup_task` | `app/workers/backup_worker.py` (long-running async loop) |
| Trigger | Existing 30s scheduler tick | Redis sorted-set queue keyed by `next_run_at` |
| Concurrency | `asyncio.Semaphore(BACKUP_MAX_CONCURRENCY)` inside the task | Same semaphore inside the worker loop |
| Resource isolation | Shares API process | Dedicated container, dedicated CPU/memory |
| Promotion trigger | Eligible-org count exceeds `BACKUP_PROMOTION_THRESHOLD_ORGS` (default 50) | — |

The job logic (per-org export, manifest builder, encrypt, upload, alert) is identical. Promotion is a deploy-only change.

## Components

### Backend modules

- `app/modules/backups/` — new module
  - `models.py` — `OrgBackupConfig`, `BackupRun`, `RestoreJob`
  - `schemas.py` — Pydantic request/response shapes
  - `router.py` — REST endpoints under `/api/v1/backups`
  - `service.py` — orchestration (config CRUD, run history queries)
  - `runner.py` — the per-org backup pipeline (export, manifest, encrypt, upload)
  - `restore_service.py` — selective restore execution
  - `manifest.py` — manifest builder + reader
  - `org_exporter.py` — per-org logical export (model-registry-driven `COPY` per table)
- `app/integrations/gdrive.py` — Google Drive client (OAuth, resumable upload, list, delete, about)
- `app/tasks/scheduled.py` — adds `byo_drive_backup_task` to `_DAILY_TASKS`
- `app/workers/backup_worker.py` (v2) — standalone runner, imports `runner.py`

### Database tables

#### `org_backup_configs`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `org_id` | UUID FK orgs.id | UNIQUE — singleton per org |
| `provider` | VARCHAR(32) | `'gdrive'` (open for future S3, Dropbox) |
| `refresh_token_encrypted` | BYTEA | envelope-encrypted via existing helper |
| `drive_folder_id` | VARCHAR(128) | resolved at OAuth-connect time |
| `drive_folder_name` | VARCHAR(255) | display name, default `OraInvoice Backups` |
| `connected_email` | VARCHAR(255) | which Google account is connected, for audit |
| `connection_status` | VARCHAR(32) | `'active'`, `'expired'`, `'revoked'` |
| `schedule_cron` | VARCHAR(64) | NZST cron expression |
| `schedule_window_seconds` | INT | default 3600 (stagger window) |
| `retention_days` | INT | 7–365, default 30 |
| `enabled` | BOOLEAN | default true |
| `paused_until` | TIMESTAMPTZ | nullable |
| `alert_emails` | TEXT[] | empty → defaults to org admins |
| `alert_in_app` | BOOLEAN | default true |
| `alert_failures_only` | BOOLEAN | default true |
| `consecutive_failure_count` | INT | default 0, reset on success |
| `last_run_at` | TIMESTAMPTZ | denormalised for fast list queries |
| `last_run_status` | VARCHAR(32) | denormalised |
| `next_run_at` | TIMESTAMPTZ | computed at config save / after each run |
| `created_at`, `updated_at`, `created_by`, `updated_by` | standard | |

#### `backup_runs`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `org_id` | UUID FK orgs.id | indexed |
| `config_id` | UUID FK org_backup_configs.id | |
| `triggered_by` | VARCHAR(32) | `'scheduled'`, `'manual'`, `'retry'` |
| `triggered_by_user_id` | UUID FK users.id | nullable |
| `started_at` | TIMESTAMPTZ NOT NULL | |
| `finished_at` | TIMESTAMPTZ | nullable while running |
| `status` | VARCHAR(32) | `'running'`, `'succeeded'`, `'failed'`, `'cancelled'` |
| `source` | VARCHAR(32) | `'standby'` or `'primary_fallback'` |
| `app_version` | VARCHAR(32) | snapshot of running app version |
| `db_size_bytes` | BIGINT | nullable until upload complete |
| `files_size_bytes` | BIGINT | |
| `manifest_size_bytes` | BIGINT | |
| `customer_count` | INT | from manifest |
| `file_count` | INT | from manifest |
| `db_sha256` | CHAR(64) | hash of decrypted db slice |
| `drive_snapshot_folder_id` | VARCHAR(128) | nullable until folder created |
| `drive_db_file_id` | VARCHAR(128) | |
| `drive_files_file_id` | VARCHAR(128) | |
| `drive_manifest_file_id` | VARCHAR(128) | |
| `error_code` | VARCHAR(64) | nullable |
| `error_message` | TEXT | nullable |
| `retention_status` | VARCHAR(32) | `'retained'`, `'deleted'`, `'delete_failed'` |
| `created_at` | standard | |

Indexes: `(org_id, started_at DESC)`, `(status)`, `(retention_status)`.

#### `restore_jobs`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `org_id` | UUID FK orgs.id | indexed |
| `backup_run_id` | UUID FK backup_runs.id | |
| `triggered_by_user_id` | UUID FK users.id | |
| `customer_ids` | UUID[] | requested scope |
| `asset_types` | TEXT[] | requested scope |
| `conflict_policy` | VARCHAR(32) | `'restore_as_copy'` or `'skip_existing'` |
| `started_at` | TIMESTAMPTZ NOT NULL | |
| `finished_at` | TIMESTAMPTZ | |
| `status` | VARCHAR(32) | `'running'`, `'succeeded'`, `'partial'`, `'failed'` |
| `customers_restored` | INT | |
| `rows_inserted` | INT | per-table counts in `details` JSON below |
| `files_restored` | INT | |
| `details` | JSONB | per-table insert counts and per-row errors |
| `error_code`, `error_message` | | nullable |
| `created_at` | standard | |

### Snapshot artifact layout in Drive

```
/OraInvoice Backups/
  snapshot-2026-05-30T14-00-00Z/
    db.sql.zst.enc
    files.tar.zst.enc
    manifest.json.enc
```

Each Drive file's `properties` metadata is set to `{org_id, snapshot_id, app_version, artifact_type}` for forensic traceability.

### Manifest schema (decrypted)

```json
{
  "schema_version": 1,
  "snapshot_id": "uuid",
  "org_id": "uuid",
  "started_at": "2026-05-30T14:00:00Z",
  "finished_at": "2026-05-30T14:03:42Z",
  "app_version": "1.13.0",
  "source": "standby",
  "summary": {
    "customer_count": 611,
    "invoice_count": 72,
    "quote_count": 14,
    "job_card_count": 33,
    "attachment_count": 88,
    "file_count": 122,
    "total_db_rows": 2480,
    "db_sha256": "abcdef..."
  },
  "org_assets": {
    "settings_keys": [...],
    "branding_file_keys": ["branding/{org_id}/{uuid}.png", ...],
    "integration_configs": ["xero", "stripe"]
  },
  "customers": [
    {
      "id": "uuid",
      "customer_code": "C-0001",
      "first_name": "John",
      "last_name": "Smith",
      "email": "...",
      "invoice_ids": ["uuid", ...],
      "quote_ids": ["uuid", ...],
      "job_card_ids": ["uuid", ...],
      "payment_ids": ["uuid", ...],
      "credit_note_ids": ["uuid", ...],
      "vehicle_ids": ["uuid", ...],
      "attachment_keys": ["invoice-attachments/{org_id}/{uuid}.pdf", ...]
    },
    ...
  ]
}
```

The manifest is the single source of truth for the restore UI. The DB slice and tar slice are addressed by the IDs and keys listed here.

## Per-org logical export

This is the riskiest new piece, so it gets its own section.

### Approach

Walk the SQLAlchemy model registry (`app.models` discovers all `Base.metadata.tables`). For each table:
- If the table has a column named `org_id` (matched case-sensitively) of type UUID, mark it as **org-scoped**.
- If the table has no `org_id` and no FK to an org-scoped table, mark it as **global** (skipped).
- If the table has no `org_id` but has a FK to an org-scoped table (e.g. `invoice_line_items.invoice_id → invoices.id`), mark it as **transitively-org-scoped**. Walk the FK to derive the slicing query.

For each org-scoped or transitive table, emit:

```sql
COPY (
  SELECT * FROM {table}
  WHERE org_id = '{org_id}'           -- direct
   OR    {table}.{fk_col} IN (        -- transitive
           SELECT id FROM {parent_table} WHERE org_id = '{org_id}'
         )
) TO STDOUT WITH (FORMAT CSV, HEADER, ENCODING 'UTF8')
```

Stream the CSV into a single `db.sql.csv` file, prefixed by a JSON header describing the table order, columns, and types. We use CSV (not pg_dump's text format) because:

- It is significantly faster for selective slicing.
- Restore can parse it row-by-row and apply with conflict policies.
- pg_dump's `--data-only --table=... --where=...` does not support compound WHERE clauses across tables, so per-org slicing through pg_dump alone is not viable.

### Table inventory at runtime

```python
def discover_org_scoped_tables() -> list[ExportTable]:
    """Return ExportTable list ordered by FK dependency (parents first)."""
    tables = []
    for table in Base.metadata.sorted_tables:
        cols = {c.name for c in table.columns}
        if 'org_id' in cols:
            tables.append(ExportTable(name=table.name, mode='direct'))
        else:
            parent = _find_org_scoped_parent(table)
            if parent:
                tables.append(ExportTable(
                    name=table.name, mode='transitive',
                    parent_table=parent.table, parent_fk=parent.fk_col,
                ))
    return tables
```

Tables appearing in `Base.metadata.sorted_tables` are already topologically ordered by FK, so insert ordering during restore is given for free.

### Output format

```
db.sql.csv
├─ HEADER LINE 1 (JSON):  {"schema_version":1, "tables":["customers","invoices",...]}
├─ TABLE customers
│    column1,column2,...
│    row1
│    row2
│    ...
├─ TABLE invoices
│    column1,column2,...
│    ...
```

A line starting with the literal token `__ORAINVOICE_TABLE__` separates table sections. The reader parses sequentially and dispatches each row to the appropriate `INSERT`.

## Restore execution

### Algorithm

1. Validate `restore_jobs` request (auth, org match, conflict policy).
2. Acquire Redis lock `restore:{org_id}` with TTL 30 min — return 409 if held.
3. Download manifest, db slice, files tar from Drive into worker `/tmp`.
4. Verify db slice SHA-256 matches manifest's `db_sha256`. If mismatch, abort.
5. Compute the **closure of selected rows**:
   - Start with the chosen `customer_ids`.
   - Filter manifest entries to those customers and chosen `asset_types`.
   - Walk transitive deps: for each chosen invoice, include its `line_items`, `tax_details`, `payments` (if not in scope already), etc. Use the FK graph from the model registry.
6. Open a single DB transaction.
7. For each table in topological order:
   - For each row whose ID is in the closure:
     - Apply conflict policy (`restore_as_copy` rewrites IDs; `skip_existing` checks PK existence).
     - Build `INSERT ... ON CONFLICT DO NOTHING` (skip mode) or `INSERT ... RETURNING id` (copy mode).
     - For copy mode, record `old_id → new_id` mapping.
     - Rewrite outgoing FKs in subsequent rows using the mapping.
8. For each attachment file_key in the closure:
   - Extract from `files.tar.zst` to `/app/uploads/{category}/{org_id}/{new_uuid}.{ext}`.
   - Update the corresponding `attachment_url` / `file_key` field in already-inserted rows.
9. Commit. Update `restore_jobs` row with summary.
10. Release Redis lock. Dispatch success notification.

### Conflict policies

**`restore_as_copy` (default)** — every row gets a new UUID. Result: customer "John Smith" exists twice in the DB after restore. Safe but creates duplicates the admin must resolve manually.

**`skip_existing`** — if PK exists in target, skip the row. Safer for "restore once and walk away" but useless for the common case where the customer was deleted and the admin wants a clean re-add.

### Why no overwrite policy

Overwriting is dangerous: the admin might restore old data on top of newer work. Out of scope for v1. If demanded, a future v2 can add `overwrite_with_diff_review` that surfaces the diff before applying.

## Google Drive integration

### OAuth client

Single platform-level Google Cloud project with OAuth client of type **Web Application**, configured with redirect URI `{frontend_base_url}/settings/backups/oauth-callback`.

`client_id` and `client_secret` stored in `integration_configs.gdrive.config` (envelope-encrypted), per the existing pattern in `.kiro/steering/integration-credentials-architecture.md`.

### Scopes

```
https://www.googleapis.com/auth/drive.file
```

Critically: this scope grants access only to files the app creates. The app cannot read the user's other Drive files. Google does not require restricted-scope verification for this scope, so we can ship without going through Google's app-verification process.

### Resumable upload flow

```python
# Initiate
POST https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable
Headers: Authorization: Bearer {access_token}
         Content-Type: application/json
Body: {name, parents:[folder_id], properties:{...}}
→ 200 with Location: {session_uri}

# Upload chunks
PUT {session_uri}
Headers: Content-Range: bytes 0-8388607/{total}
Body: <8 MB chunk>
→ 308 Resume Incomplete (continue with next chunk)
→ 200 OK with file metadata (final chunk)
```

Resume on transient failures (connection reset, 500/502/503, 429) using exponential backoff (1s, 2s, 4s, 8s) up to 3 attempts per chunk.

### Folder structure

```
GET /drive/v3/files?q="{folder_id}" in parents and mimeType="application/vnd.google-apps.folder"
```

If `OraInvoice Backups` exists under root, reuse its ID. Otherwise create. `snapshot-{ts}` subfolders are created per run and never reused.

### Refresh token rotation

Google rotates refresh tokens on use under some conditions. After every token exchange, store the latest `refresh_token` from the response (not just the access_token) — this matches the Xero OAuth handling in `app/integrations/xero.py`.

## Concurrency, scheduling, and worker promotion

### v1 — in-process

Add to `_DAILY_TASKS` in `app/tasks/scheduled.py`:

```python
(byo_drive_backup_task, 60, "byo_drive_backup"),  # check every minute
```

The task:
1. Queries `org_backup_configs WHERE enabled = true AND (paused_until IS NULL OR paused_until < now()) AND next_run_at <= now()`.
2. Acquires `asyncio.Semaphore(BACKUP_MAX_CONCURRENCY)` (default 4).
3. For each due org, acquires Redis lock `backup:run:{org_id}` (TTL 1h) and runs the pipeline.
4. Updates `next_run_at` after success/failure using the cron expression and the per-org sticky offset `hash(org_id) % schedule_window_seconds`.

This task is **not added to `WRITE_TASKS`** because it does not write to the source DB — it only reads from standby.

### v2 — worker container

`app/workers/backup_worker.py`:

```python
async def main():
    sem = asyncio.Semaphore(int(os.environ.get("BACKUP_MAX_CONCURRENCY", "8")))
    while not stop_event.is_set():
        due_configs = await fetch_due_configs()
        for cfg in due_configs:
            asyncio.create_task(_run_with_semaphore(sem, cfg))
        await asyncio.sleep(30)
```

Compose addition:

```yaml
worker-backup:
  build: { context: ., dockerfile: Dockerfile }
  command: python -m app.workers.backup_worker
  environment:
    DATABASE_URL: ...                # standby's DB for state writes
    BACKUP_SOURCE_URL: ...           # standby's DB for export reads
    BACKUP_SOURCE_FALLBACK_URL: ...  # primary, only used if standby unhealthy
    REDIS_URL: redis://redis:6379/2
    BACKUP_MAX_CONCURRENCY: "8"
    BACKUP_MAX_LAG_SECONDS: "600"
  volumes:
    - app_uploads:/app/uploads:ro
    - compliance_files:/app/compliance_files:ro
  depends_on:
    - postgres
    - redis
  restart: unless-stopped
```

Promotion is a deploy-only change. The DB schema, Redis keys, and code paths are identical between v1 and v2.

## Frontend Component Breakdown

### Navigation

- **Org Settings sidebar** gets a new entry: `Backups`, only visible to roles `owner` and `org_admin`.
- Routes (registered in `frontend/src/App.tsx`):
  - `/settings/backups` → `BackupsSettings`
  - `/settings/backups/oauth-callback` → `BackupsOAuthCallback`
  - `/settings/backups/restore` → `BackupsRestore`
  - `/settings/backups/restore/:runId` → `BackupsRestoreSnapshot`
- Lazy imports added to `App.tsx`.
- All routes guarded by `RequireOrgAdmin` (existing component) and feature-flag checked via `ModuleGate` for `byo_drive_backup`.

### Pages

#### 1. `BackupsSettings` (`frontend/src/pages/settings/Backups/BackupsSettings.tsx`)

- Layout: `OrgSettingsLayout`
- API:
  - `GET /api/v1/backups/config` — current config (or 404 if not connected)
  - `GET /api/v1/backups/storage` — Drive usage
  - `GET /api/v1/backups/runs?limit=10` — recent runs
- Sections:
  - **Connection** card — when not connected: `Connect Google Drive` button; when connected: shows `connected_email`, `drive_folder_name`, status badge, `Disconnect` button
  - **Schedule** card — preset radio group (Daily 02:00, Every 12h, Every 6h, Weekly Sun 02:00, Custom), retention slider 7–365 days, enable/pause toggle
  - **Alerts** card — alert email recipients (multi-select user picker + free-text email entry), in-app toggle, failures-only toggle
  - **Storage** card — progress bar of Drive used/total, snapshot count, total snapshot bytes
  - **Recent Runs** table — last 10 runs with status badge, started_at, duration, size totals, error message; row click → `BackupsRestoreSnapshot`
  - **Actions** row — `Run backup now` button (rate-limited 1/15min), `Restore from backup` link

#### 2. `BackupsOAuthCallback` (`frontend/src/pages/settings/Backups/BackupsOAuthCallback.tsx`)

- Reads `code` and `state` from URL query params
- Calls `POST /api/v1/backups/oauth/callback` with the code
- On success: redirects to `/settings/backups` with toast "Connected to Google Drive"
- On error: shows error message and Retry button

#### 3. `BackupsRestore` (`frontend/src/pages/settings/Backups/BackupsRestore.tsx`)

- Lists all snapshots in the org's Drive folder via `GET /api/v1/backups/runs?limit=100`
- Card grid: each card shows snapshot timestamp, status badge, size, customer/file counts, `Browse` button
- Empty state: "No backups yet. Connect Drive and run your first backup to enable restore."

#### 4. `BackupsRestoreSnapshot` (`frontend/src/pages/settings/Backups/BackupsRestoreSnapshot.tsx`)

- Param: `runId`
- Fetches manifest via `GET /api/v1/backups/runs/{runId}/manifest`
- Layout: split pane
  - Left: customer search input + paginated list of customers with checkboxes (page size 50)
  - Right: for each selected customer, asset-type checkboxes (Invoices, Quotes, Job Cards, Attachments) with counts
- Bottom action bar:
  - Live preview text: "3 customers, 47 invoices, 18 attachments"
  - Conflict policy radio: `Restore as copy (recommended)` / `Skip existing`
  - `Cancel` link → back to BackupsRestore
  - `Restore selected` button → confirmation modal → `POST /api/v1/backups/runs/{runId}/restore`
- After restore submitted: poll `GET /api/v1/backups/restore-jobs/{jobId}` every 2s until `status != 'running'`, then show summary screen with restored counts and link to the restored customers

### Modals

- **DisconnectConfirmModal** — "Disconnect Google Drive? Your existing backups in Drive remain but no new backups will be created." Type-org-name confirmation.
- **RestoreConfirmModal** — preview of selected scope, conflict policy summary, type "RESTORE" to confirm.
- **RunNowConfirmModal** — "Run backup now? This will use Drive bandwidth." Plain confirm.

### Toolbar specs

- **Recent Runs table** — columns: Status, Started, Duration, DB Size, Files Size, Error. Row actions: View Manifest (modal showing JSON), Restore from this Snapshot.

### Loading and error states

- All API calls wrapped in `try/catch` with `MobileSpinner` for loading, error banner with retry CTA on failure.
- All array reads use `?? []` and counts use `?? 0` per `safe-api-consumption.md`.
- All useEffect API calls use `AbortController`.

### Empty states

- `BackupsSettings` with no config row: shown above (Connect Drive CTA).
- `BackupsRestore` with no runs: shown above.
- `BackupsRestoreSnapshot` with empty manifest: "This snapshot has no customers."

## User Workflow Trace

### First-time connect

1. Org admin opens `Settings → Backups`.
2. `BackupsSettings` mounts, calls `GET /api/v1/backups/config` → 404 → renders Connect card.
3. Admin clicks `Connect Google Drive`.
4. Frontend calls `GET /api/v1/backups/oauth/start` → returns Google authorization URL.
5. Browser redirects to Google's consent screen.
6. Admin grants consent.
7. Google redirects to `/settings/backups/oauth-callback?code=...&state=...`.
8. `BackupsOAuthCallback` mounts, calls `POST /api/v1/backups/oauth/callback` with code.
9. Backend exchanges code, creates Drive folder, persists `org_backup_configs` row with default schedule (Daily 02:00, retention 30 days).
10. Frontend redirects to `/settings/backups` with success toast.

### Manual backup run

1. Admin clicks `Run backup now` in Recent Runs section.
2. Confirmation modal opens.
3. Confirm → `POST /api/v1/backups/runs/manual` → returns 202 with `run_id`.
4. Frontend polls `GET /api/v1/backups/runs/{run_id}` every 5s.
5. Status transitions: `running` → `succeeded` (or `failed`).
6. Toast on completion. Recent Runs table refreshes.

### Selective restore

1. Admin clicks `Restore from backup` → `BackupsRestore`.
2. Picks a snapshot card → `Browse` → `BackupsRestoreSnapshot`.
3. Manifest loads. Tree renders.
4. Admin searches for customer name "Acme Ltd". Tree filters.
5. Admin checks Acme's customer box, leaves all asset types checked (default).
6. Bottom bar updates: "1 customer, 12 invoices, 3 quotes, 5 attachments".
7. Admin selects `Restore as copy` policy.
8. Clicks `Restore selected` → confirmation modal.
9. Types `RESTORE`, clicks confirm.
10. `POST /api/v1/backups/runs/{runId}/restore` → 202 with `restore_job_id`.
11. Frontend polls every 2s.
12. On success: redirect to `/customers?recently_restored=true` showing the duplicated customer with a "(restored)" badge in the name.

### Backup failure

1. Scheduled run fires.
2. Drive returns 401 (refresh token revoked).
3. Worker marks run as `failed` with `error_code = 'oauth_revoked'`.
4. Worker dispatches `backup_oauth_revoked` template via `app/tasks/notifications.py` to all alert email recipients (or org admins by default).
5. Worker also writes in-app notification.
6. Worker sets `connection_status = 'expired'` on the config row.
7. Next time the admin opens `BackupsSettings`, the Connection card shows a red banner: "Google Drive connection expired. Reconnect to resume backups." with a `Reconnect` button (re-runs the OAuth flow).

## Error & Edge Case UI

| State | UI |
|---|---|
| Drive OAuth fails (user denies) | Toast: "Connection cancelled." |
| Drive quota exceeded | Banner: "Your Google Drive is full. Reduce retention or upgrade Drive storage." |
| Backup run failed | Recent Runs row turns red; click → modal with error message and link to ISSUE_TRACKER if it's a known error code |
| Standby falls back to primary | Recent Runs row badge `primary fallback` (yellow), tooltip: "Standby was unhealthy. Run completed against primary." |
| Restore in progress, second attempt | 409 Conflict → toast: "A restore is already running. Wait for it to finish." |
| Manifest hash mismatch | Restore aborts, modal: "This snapshot is corrupted (integrity check failed). Try a different snapshot." |
| Feature flag off | Settings page shows: "Google Drive backup is currently unavailable. Contact your administrator." |
| Three consecutive failures | Settings page shows persistent red banner; sends extra email to all org owners |

## Integration Points

### Notifications

Adds template types: `backup_failed`, `backup_succeeded`, `backup_drive_quota_warning`, `backup_drive_quota_exceeded`, `backup_oauth_revoked`. Templates registered in `app/modules/notifications/templates/` following the existing pattern. Recipients are computed by `_resolve_alert_recipients(config)` which falls back to org owners + org admins when `alert_emails` is empty.

### Audit logging

Every config change, every backup run, every restore writes to `audit_logs` with:
- `entity_type = 'backup_config' | 'backup_run' | 'restore_job'`
- `action = 'create' | 'update' | 'delete' | 'connect' | 'disconnect' | 'run' | 'restore' | 'cancel'`
- `before_value` / `after_value` for config diffs

### HA volume sync

The existing `app/modules/ha/volume_sync_service.py` rsyncs `/app/uploads/` from primary to standby every 5 minutes. The worker reads files from the standby's local copy. If the most recent backup needs files newer than 5 minutes old, the worker can optionally trigger an on-demand rsync via the existing service before producing the tarball — this is opt-in and disabled by default to avoid amplifying load.

### Module gating and roles

- All endpoints require `role IN ('owner', 'org_admin')` or 403.
- All endpoints require active org context middleware (`request.state.org_id` set).
- The feature flag `byo_drive_backup` in `feature_flags` table gates UI visibility and endpoint access. When off, endpoints return 503 Service Unavailable.

## API Surface

| Method | Path | Description | Role |
|---|---|---|---|
| GET | `/api/v1/backups/config` | Read config (or 404) | org_admin/owner |
| PUT | `/api/v1/backups/config` | Update schedule/retention/alerts | org_admin/owner |
| PATCH | `/api/v1/backups/config` | Pause/resume | org_admin/owner |
| GET | `/api/v1/backups/oauth/start` | Returns Google authorization URL | org_admin/owner |
| POST | `/api/v1/backups/oauth/callback` | Exchanges code for tokens | org_admin/owner |
| POST | `/api/v1/backups/oauth/disconnect` | Revokes token, deletes config | org_admin/owner |
| GET | `/api/v1/backups/runs` | Paginated list of runs | org_admin/owner |
| GET | `/api/v1/backups/runs/{run_id}` | Single run | org_admin/owner |
| GET | `/api/v1/backups/runs/{run_id}/manifest` | Decrypted manifest | org_admin/owner |
| POST | `/api/v1/backups/runs/manual` | Trigger on-demand run | org_admin/owner |
| POST | `/api/v1/backups/runs/{run_id}/cancel` | Cancel running run | org_admin/owner |
| POST | `/api/v1/backups/runs/{run_id}/restore` | Trigger selective restore | org_admin/owner |
| GET | `/api/v1/backups/restore-jobs/{job_id}` | Restore job status | org_admin/owner |
| GET | `/api/v1/backups/storage` | Drive usage and snapshot totals | org_admin/owner |

All array responses are wrapped: `{items: [...], total: N}`. All endpoints rate-limited per existing middleware. All write endpoints write to `audit_logs`.

## Security Considerations

- `drive.file` scope only — we cannot read user's other Drive files.
- Refresh tokens envelope-encrypted at rest, never logged.
- Snapshot artifacts envelope-encrypted at rest in Drive — leak of Drive token without the platform KEK does not expose data.
- SHA-256 integrity check on every restore.
- Cross-org restore prevented by org_id match enforcement on `restore` endpoint.
- Rate limit on manual backup (1/15min/org) and automatic concurrency cap.
- All backup/restore endpoints require `owner` or `org_admin` role.
- Feature flag kill-switch.

## Performance Considerations

- Standby-sourced DB reads → zero impact on primary postgres.
- Per-org export bounded to ~5 minutes for 100K invoices on the standby.
- Tarball streamed to disk → peak worker RSS under 256 MB regardless of org file count.
- Resumable Drive uploads with 8 MB chunks → no full-file rewrite on retry.
- Sticky per-org schedule offset → 500 orgs configured for the same hour distribute evenly across the configured window.
- Concurrency semaphore caps simultaneous runs at 4 (v1) or 8 (v2).
- Redis-based per-org lease prevents accidental dual-runner duplication during v2 rollout.

## Testing Strategy

- Unit tests for `org_exporter.discover_org_scoped_tables()` — verify the model registry walker correctly classifies a representative sample of tables (direct, transitive, global).
- Unit tests for manifest builder — feed a known org dataset, assert manifest counts and IDs.
- Unit tests for restore closure computation — given selected customers, verify transitive deps are pulled in.
- Integration test using a fake Drive client (`unittest.mock` of the gdrive module) — simulate full backup → manifest → restore round trip.
- Integration test for fallback logic — force standby connection refused, assert run completes against primary with `source = 'primary_fallback'`.
- Property-based test (Hypothesis) for `restore_as_copy` UUID rewriting — given an arbitrary FK graph subset, assert output FKs are consistent.
- Browser test (Playwright) for the OAuth connect flow using Google's test account.
- Browser test for the selective-restore tree navigation.

## Out of Scope (v1)

- PITR / WAL streaming to Drive — large effort, separate spec.
- Cross-org restore (admin-controlled migration tools).
- Mobile app surfacing — backups are an admin feature, mobile is not the right surface (per `mobile-app.md`).
- Other providers (S3, Dropbox, OneDrive) — `provider` column reserves the option.
- Encryption key rotation — backup artifacts use the current KEK; rotating KEK requires backfill, separate concern.
- Overwrite conflict policy — explicitly excluded for safety.
