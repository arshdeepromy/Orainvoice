# Requirements Document

## Introduction

This feature implements a hybrid file storage and replication strategy for OraInvoice's HA (High Availability) deployment. Branding files (logos, favicons) are small and few — they move into PostgreSQL as BYTEA columns so they replicate automatically via the existing logical replication pipeline. Job card attachments and compliance documents remain on disk (Docker volumes) but gain an rsync-based sync system that copies the uploads volume from the Pi primary to the local standby. A new "Volume Replication" section on the existing HA Replication admin page lets the global admin configure, monitor, and trigger file sync operations.

## Glossary

- **Branding_Service**: The backend service layer (`app/modules/branding/service.py`) responsible for reading and writing platform branding configuration, including file data.
- **Branding_Router**: The FastAPI router (`app/modules/branding/router.py`) that exposes branding upload and serving endpoints.
- **Branding_Model**: The SQLAlchemy ORM model (`app/modules/branding/models.py`) mapping to the `platform_branding` table.
- **Volume_Sync_Service**: A new backend service that manages rsync-based replication of Docker volume data (uploads, compliance files) from the primary node to the standby node.
- **Volume_Sync_Router**: A new set of FastAPI endpoints under the HA module for configuring and triggering volume sync operations.
- **Rsync_Config_Model**: A new SQLAlchemy model storing rsync configuration (standby host, SSH key path, remote upload path, sync interval, enabled flag).
- **Sync_History_Model**: A new SQLAlchemy model storing a log of each sync execution (timestamp, status, file count, total size, duration, error message).
- **HA_Replication_Page**: The existing frontend admin page (`frontend/src/pages/admin/HAReplication.tsx`) for managing HA cluster configuration and replication.
- **Global_Admin**: A user with the `global_admin` role who has access to platform-level administration.
- **Primary_Node**: The active OraInvoice instance (Raspberry Pi 5 at 192.168.1.90) that accepts writes and serves traffic.
- **Standby_Node**: The passive HA instance (local Windows desktop) that receives replicated data and can be promoted if the primary fails.
- **Branding_File**: A logo (light or dark mode) or favicon image uploaded through the branding admin interface. Each file is under 2 MB.
- **BYTEA_Column**: A PostgreSQL binary data column type used to store raw file bytes directly in the database.

## Requirements

### Requirement 1: Store Branding File Data in PostgreSQL

**User Story:** As a global admin, I want branding files (logos, favicons) stored directly in the PostgreSQL database, so that they replicate automatically to the standby node via the existing logical replication pipeline without any additional file sync infrastructure.

#### Acceptance Criteria

1. THE Branding_Model SHALL include BYTEA columns `logo_data`, `dark_logo_data`, and `favicon_data` to store raw file bytes for each branding file.
2. THE Branding_Model SHALL include String columns `logo_content_type`, `dark_logo_content_type`, and `favicon_content_type` to store the MIME type of each branding file.
3. THE Branding_Model SHALL include String columns `logo_filename`, `dark_logo_filename`, and `favicon_filename` to store the original filename of each branding file.
4. WHEN a branding file is uploaded via the Branding_Router, THE Branding_Service SHALL store the processed image bytes in the corresponding BYTEA column of the Branding_Model instead of writing to the filesystem.
5. WHEN a branding file is uploaded, THE Branding_Service SHALL enforce a maximum file size of 2 MB for logos and 512 KB for favicons, consistent with the existing limits.
6. WHEN a branding file is uploaded, THE Branding_Router SHALL continue to validate file content types against the existing allowed types (PNG, JPEG, WebP, SVG for logos; plus ICO for favicons).
7. WHEN a branding file is uploaded, THE Branding_Router SHALL continue to process and optimise images using the existing `_process_image` function before storing in the database.

### Requirement 2: Serve Branding Files from PostgreSQL

**User Story:** As a public user visiting the login page, I want branding files served reliably regardless of which HA node is active, so that the platform logo and favicon always display correctly after a failover.

#### Acceptance Criteria

1. WHEN a request is made to `GET /api/v1/public/branding/file/{file_type}`, THE Branding_Router SHALL read the file bytes from the corresponding BYTEA column in the database and return them with the correct `Content-Type` header.
2. THE Branding_Router SHALL accept `file_type` values of `logo`, `dark_logo`, and `favicon` to identify which branding file to serve.
3. IF the requested branding file BYTEA column is NULL, THEN THE Branding_Router SHALL return HTTP 404 with a descriptive error message.
4. WHEN serving a branding file, THE Branding_Router SHALL include a `Cache-Control: public, max-age=86400` header to enable client-side caching.
5. WHEN a branding file is uploaded, THE Branding_Service SHALL update the corresponding `_url` field (logo_url, dark_logo_url, favicon_url) to point to the new database-backed serving endpoint using the `/api/v1/public/branding/file/{file_type}` pattern.
6. THE Branding_Router SHALL maintain backward compatibility by continuing to serve any legacy disk-based files that exist at the old UUID-based paths until they are re-uploaded.

### Requirement 3: Migrate Existing Disk-Based Branding Files to Database

**User Story:** As a global admin, I want existing branding files that were previously uploaded to disk to be automatically migrated into the database, so that I do not need to re-upload them manually after the upgrade.

#### Acceptance Criteria

1. WHEN the application starts and the Branding_Model has a `logo_url` pointing to a disk-based file path but `logo_data` is NULL, THE Branding_Service SHALL read the file from disk and populate the BYTEA column automatically.
2. WHEN the migration reads a disk-based branding file, THE Branding_Service SHALL determine the MIME type from the file extension and store it in the corresponding `_content_type` column.
3. WHEN the migration successfully stores a branding file in the database, THE Branding_Service SHALL update the `_url` field to point to the new database-backed serving endpoint.
4. IF a disk-based branding file referenced by the URL does not exist on the filesystem, THEN THE Branding_Service SHALL log a warning and leave the BYTEA column as NULL.
5. THE migration process SHALL be idempotent — running it multiple times SHALL produce the same result without duplicating data or causing errors.

### Requirement 4: Rsync-Based Volume Sync Configuration

**User Story:** As a global admin, I want to configure rsync settings for syncing Docker volume data (job card attachments and compliance documents) from the primary to the standby, so that file data is available on the standby node after a failover.

#### Acceptance Criteria

1. THE Rsync_Config_Model SHALL store the following settings: standby SSH host, SSH port, SSH key path, remote upload path, remote compliance path, sync interval in minutes, and an enabled flag.
2. WHEN the global admin saves rsync configuration via the Volume_Sync_Router, THE Volume_Sync_Service SHALL validate that the SSH host is not empty and the sync interval is between 1 and 1440 minutes.
3. THE Volume_Sync_Router SHALL expose a `GET /api/v1/ha/volume-sync/config` endpoint that returns the current rsync configuration.
4. THE Volume_Sync_Router SHALL expose a `PUT /api/v1/ha/volume-sync/config` endpoint that updates the rsync configuration.
5. THE Volume_Sync_Router SHALL require the `global_admin` role for all volume sync endpoints.
6. WHEN rsync configuration is saved, THE Volume_Sync_Service SHALL store the SSH key path as a filesystem reference (the key file itself is not stored in the database).

### Requirement 5: Execute Rsync Volume Synchronisation

**User Story:** As a global admin, I want the system to periodically sync upload volumes from the primary to the standby using rsync, so that job card attachments and compliance documents are replicated without manual intervention.

#### Acceptance Criteria

1. WHILE automatic sync is enabled and the node role is primary, THE Volume_Sync_Service SHALL execute an rsync operation at the configured interval (default: every 5 minutes).
2. WHEN an rsync operation executes, THE Volume_Sync_Service SHALL sync the `/app/uploads/` directory to the configured remote upload path on the standby host.
3. WHEN an rsync operation executes, THE Volume_Sync_Service SHALL sync the `/app/compliance_files/` directory to the configured remote compliance path on the standby host.
4. WHEN an rsync operation completes, THE Volume_Sync_Service SHALL record a Sync_History_Model entry with the start time, end time, status (success or failure), file count transferred, total bytes transferred, and any error message.
5. IF an rsync operation fails, THEN THE Volume_Sync_Service SHALL log the error and record the failure in the sync history without crashing the application.
6. WHEN the global admin triggers a manual sync via `POST /api/v1/ha/volume-sync/trigger`, THE Volume_Sync_Service SHALL execute an immediate rsync operation regardless of the automatic schedule.
7. THE Volume_Sync_Service SHALL use rsync with the `--archive`, `--compress`, and `--delete` flags to ensure the standby is an exact mirror of the primary's upload directories.
8. THE Volume_Sync_Service SHALL use the configured SSH key for authentication when connecting to the standby host.

### Requirement 6: Volume Sync Status and History

**User Story:** As a global admin, I want to see the current status and history of volume sync operations, so that I can verify file replication is working and diagnose any issues.

#### Acceptance Criteria

1. THE Volume_Sync_Router SHALL expose a `GET /api/v1/ha/volume-sync/status` endpoint that returns the current sync status including: last sync time, last sync result (success/failure), next scheduled sync time, total file count on the primary volumes, and total size of the primary volumes.
2. THE Volume_Sync_Router SHALL expose a `GET /api/v1/ha/volume-sync/history` endpoint that returns the most recent sync history entries (default: last 20 entries).
3. WHEN the status endpoint is called, THE Volume_Sync_Service SHALL calculate the total file count and size by scanning the `/app/uploads/` and `/app/compliance_files/` directories.
4. WHEN the history endpoint is called, THE Volume_Sync_Service SHALL return entries ordered by start time descending.
5. THE Volume_Sync_Router SHALL require the `global_admin` role for all status and history endpoints.

### Requirement 7: HA Replication Page — Volume Sync Section

**User Story:** As a global admin, I want a "Volume Data Replication" section on the existing HA Replication admin page, so that I can configure, monitor, and control file sync from the same place I manage database replication.

#### Acceptance Criteria

1. THE HA_Replication_Page SHALL include a new "Volume Data Replication" section below the existing database replication sections.
2. THE Volume Data Replication section SHALL display the rsync configuration form with fields for: standby SSH host, SSH port, SSH key path, remote upload path, remote compliance path, sync interval, and an enable/disable toggle.
3. WHEN the global admin clicks "Save Configuration" in the volume sync section, THE HA_Replication_Page SHALL send the configuration to `PUT /api/v1/ha/volume-sync/config` and display a success or error message.
4. THE Volume Data Replication section SHALL display the current sync status: last sync time, last sync result, next scheduled sync time, file count, and total size.
5. THE Volume Data Replication section SHALL include a "Sync Now" button that triggers `POST /api/v1/ha/volume-sync/trigger` and displays a loading state while the sync is in progress.
6. THE Volume Data Replication section SHALL display a sync history table showing the most recent sync operations with columns: time, status, files transferred, bytes transferred, duration, and error (if any).
7. WHILE a sync operation is in progress, THE HA_Replication_Page SHALL display a progress indicator and disable the "Sync Now" button.
8. THE Volume Data Replication section SHALL poll for updated status every 10 seconds, consistent with the existing HA page polling interval.
9. THE HA_Replication_Page SHALL use optional chaining (`?.`) and nullish coalescing (`?? []`, `?? 0`) on all API response data, consistent with the safe API consumption patterns.

### Requirement 8: Alembic Migration for Branding BYTEA Columns

**User Story:** As a developer, I want a database migration that adds the BYTEA and metadata columns to the platform_branding table, so that the schema change is tracked and applied consistently across all environments.

#### Acceptance Criteria

1. THE migration SHALL add columns `logo_data` (LargeBinary, nullable), `dark_logo_data` (LargeBinary, nullable), and `favicon_data` (LargeBinary, nullable) to the `platform_branding` table.
2. THE migration SHALL add columns `logo_content_type` (String(100), nullable), `dark_logo_content_type` (String(100), nullable), and `favicon_content_type` (String(100), nullable) to the `platform_branding` table.
3. THE migration SHALL add columns `logo_filename` (String(255), nullable), `dark_logo_filename` (String(255), nullable), and `favicon_filename` (String(255), nullable) to the `platform_branding` table.
4. THE migration SHALL be idempotent by using `IF NOT EXISTS` checks or equivalent Alembic patterns.
5. THE migration downgrade SHALL drop the added columns to allow rollback.

### Requirement 9: Alembic Migration for Volume Sync Models

**User Story:** As a developer, I want database migrations for the rsync configuration and sync history tables, so that the volume sync feature has proper schema support.

#### Acceptance Criteria

1. THE migration SHALL create a `volume_sync_config` table with columns: id (UUID, primary key), standby_ssh_host (String), ssh_port (Integer, default 22), ssh_key_path (String), remote_upload_path (String), remote_compliance_path (String), sync_interval_minutes (Integer, default 5), enabled (Boolean, default false), created_at (DateTime), and updated_at (DateTime).
2. THE migration SHALL create a `volume_sync_history` table with columns: id (UUID, primary key), started_at (DateTime), completed_at (DateTime, nullable), status (String — 'running', 'success', 'failure'), files_transferred (Integer, default 0), bytes_transferred (BigInteger, default 0), error_message (Text, nullable), and sync_type (String — 'automatic' or 'manual').
3. THE migration SHALL be idempotent by using `IF NOT EXISTS` checks for table creation.
4. THE migration downgrade SHALL drop both tables to allow rollback.

### Requirement 10: Docker Volume Configuration for Uploads

**User Story:** As a developer, I want the Docker Compose configurations to consistently mount the uploads volume across all environments, so that branding uploads (during migration) and job card attachments are accessible to the application.

#### Acceptance Criteria

1. THE docker-compose.yml app service SHALL mount the `app_uploads` volume at `/app/uploads`.
2. THE docker-compose.pi.yml app service SHALL mount the `app_uploads` volume at `/app/uploads`.
3. THE docker-compose.ha-standby.yml app service SHALL continue to mount the `standby_uploads` volume at `/app/uploads`.
4. WHEN rsync is configured, THE Volume_Sync_Service SHALL sync from the primary's `/app/uploads/` to the standby's corresponding volume mount path.
