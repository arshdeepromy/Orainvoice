# Requirements Document

## Introduction

Live Database Migration enables the Global_Admin to migrate the entire WorkshopPro NZ platform database from one PostgreSQL server to another while the application continues serving requests. The feature is accessed from Global Settings and provides a guided workflow: enter a target database connection, validate connectivity, migrate all data with real-time progress tracking, verify integrity, and cut over to the new database — all with zero downtime for tenants.

## Glossary

- **Migration_Engine**: The backend service responsible for orchestrating the database migration process, including connection validation, data copying, change tracking, integrity verification, and cutover.
- **Source_Database**: The currently active PostgreSQL database that the platform reads from and writes to.
- **Target_Database**: The new PostgreSQL database that data is being migrated to.
- **Migration_Job**: A persistent record tracking the state, progress, and metadata of a single database migration attempt.
- **Dual_Write_Proxy**: The mechanism that writes incoming data changes to both the Source_Database and Target_Database simultaneously during the migration window.
- **Cutover**: The atomic operation that switches the platform's active database connection from the Source_Database to the Target_Database.
- **Progress_Screen**: The frontend UI that displays real-time migration status, progress bar, table-level counts, and error information.
- **Global_Admin**: A user with the `global_admin` role who has access to platform-wide settings and administration.
- **Integrity_Check**: A verification step that compares record counts, foreign key references, and financial totals between Source_Database and Target_Database to confirm data consistency.
- **Connection_String**: A PostgreSQL connection URI in the format `postgresql+asyncpg://user:password@host:port/dbname` used to connect to a database server.

## Requirements

### Requirement 1: Access Control

**User Story:** As a Global_Admin, I want the live database migration tool to be restricted to my role, so that only authorized administrators can initiate potentially destructive operations.

#### Acceptance Criteria

1. THE Migration_Engine SHALL restrict all migration endpoints to users with the `global_admin` role.
2. WHEN a non-global_admin user attempts to access any migration endpoint, THE Migration_Engine SHALL return a 403 Forbidden response.
3. THE Progress_Screen SHALL only be accessible from the Global Settings page within the admin panel.

### Requirement 2: Target Database Connection Input

**User Story:** As a Global_Admin, I want to enter a new database connection string in Global Settings, so that I can specify where the data should be migrated to.

#### Acceptance Criteria

1. THE Progress_Screen SHALL provide a form field for entering a Target_Database Connection_String.
2. THE Progress_Screen SHALL provide optional fields for SSL mode selection (require, prefer, disable).
3. WHEN the Global_Admin submits a Connection_String, THE Migration_Engine SHALL validate the Connection_String format before attempting a connection.
4. IF the Connection_String format is invalid, THEN THE Migration_Engine SHALL return a descriptive error message indicating the expected format.
5. THE Migration_Engine SHALL mask the password portion of the Connection_String in all API responses and logs.

### Requirement 3: Target Database Connectivity Validation

**User Story:** As a Global_Admin, I want the system to validate the target database connection before starting migration, so that I can confirm the target is reachable and properly configured.

#### Acceptance Criteria

1. WHEN a valid Connection_String is submitted, THE Migration_Engine SHALL attempt to connect to the Target_Database within 10 seconds.
2. IF the Target_Database is unreachable, THEN THE Migration_Engine SHALL return an error message containing the connection failure reason.
3. WHEN the connection succeeds, THE Migration_Engine SHALL verify that the Target_Database PostgreSQL version is compatible (version 13 or higher).
4. WHEN the connection succeeds, THE Migration_Engine SHALL verify that the connecting user has CREATE, INSERT, UPDATE, DELETE, and SELECT privileges on the Target_Database.
5. WHEN the connection succeeds, THE Migration_Engine SHALL verify that the Target_Database is empty or contains only system tables.
6. IF the Target_Database contains existing application tables, THEN THE Migration_Engine SHALL warn the Global_Admin and require explicit confirmation before proceeding.
7. WHEN all validation checks pass, THE Migration_Engine SHALL return a validation success response containing the Target_Database server version and available disk space.

### Requirement 4: Schema Migration

**User Story:** As a Global_Admin, I want the system to replicate the database schema on the target before copying data, so that the target database structure matches the source.

#### Acceptance Criteria

1. WHEN migration is initiated, THE Migration_Engine SHALL run all Alembic migrations on the Target_Database to create the schema.
2. IF an Alembic migration fails on the Target_Database, THEN THE Migration_Engine SHALL halt the migration, log the error, and report the failing migration revision to the Global_Admin.
3. WHEN schema migration completes, THE Migration_Engine SHALL verify that all tables present in the Source_Database exist in the Target_Database.
4. THE Migration_Engine SHALL create all indexes, constraints, and triggers on the Target_Database that exist on the Source_Database.

### Requirement 5: Data Migration with Progress Tracking

**User Story:** As a Global_Admin, I want to see real-time progress of the data migration, so that I know how much data has been copied and how long it will take.

#### Acceptance Criteria

1. WHEN data migration begins, THE Migration_Engine SHALL copy data table-by-table from the Source_Database to the Target_Database.
2. THE Migration_Engine SHALL process tables in dependency order to satisfy foreign key constraints.
3. THE Migration_Engine SHALL copy data in configurable batch sizes (default 1000 rows per batch) to avoid locking the Source_Database.
4. WHILE migration is in progress, THE Migration_Engine SHALL update the Migration_Job record with the current table name, rows processed, total rows, and percentage complete.
5. WHILE migration is in progress, THE Migration_Engine SHALL expose a status endpoint that returns the current Migration_Job state.
6. THE Progress_Screen SHALL poll the status endpoint every 2 seconds and display a progress bar showing overall completion percentage.
7. THE Progress_Screen SHALL display a table-level breakdown showing each table name, source row count, migrated row count, and status (pending, in_progress, completed, failed).
8. THE Progress_Screen SHALL display an estimated time remaining based on the current migration throughput.
9. IF a batch copy fails, THEN THE Migration_Engine SHALL retry the batch up to 3 times with exponential backoff before marking the table as failed.

### Requirement 6: Dual-Write During Migration

**User Story:** As a Global_Admin, I want the application to continue operating normally during migration, so that tenants experience zero downtime.

#### Acceptance Criteria

1. WHILE migration is in progress, THE Dual_Write_Proxy SHALL write all new INSERT, UPDATE, and DELETE operations to both the Source_Database and the Target_Database.
2. WHILE migration is in progress, THE Migration_Engine SHALL continue reading from the Source_Database for all application queries.
3. IF a write to the Target_Database fails during dual-write, THEN THE Migration_Engine SHALL log the failure and queue the operation for retry without affecting the Source_Database write.
4. WHILE migration is in progress, THE Migration_Engine SHALL track all queued retry operations and report the queue depth via the status endpoint.
5. THE Migration_Engine SHALL apply queued retry operations in order before the Integrity_Check phase begins.

### Requirement 7: Integrity Verification

**User Story:** As a Global_Admin, I want the system to verify data integrity after migration, so that I can be confident no data was lost or corrupted.

#### Acceptance Criteria

1. WHEN all tables have been copied and dual-write queues are drained, THE Migration_Engine SHALL perform an Integrity_Check.
2. THE Integrity_Check SHALL compare row counts for every table between Source_Database and Target_Database.
3. THE Integrity_Check SHALL verify that all foreign key references in the Target_Database are valid.
4. THE Integrity_Check SHALL compare financial totals (invoice amounts, payment totals, credit note totals) between Source_Database and Target_Database.
5. THE Integrity_Check SHALL verify that sequence values in the Target_Database are equal to or greater than those in the Source_Database.
6. WHEN the Integrity_Check completes, THE Progress_Screen SHALL display the Integrity_Check results including per-table row count comparison, financial total comparison, and any reference errors.
7. IF the Integrity_Check fails, THEN THE Migration_Engine SHALL prevent Cutover and display the specific failures to the Global_Admin.

### Requirement 8: Database Cutover

**User Story:** As a Global_Admin, I want to switch the application to use the new database once migration is verified, so that I can decommission the old database.

#### Acceptance Criteria

1. WHEN the Integrity_Check passes, THE Progress_Screen SHALL enable a "Cut Over to New Database" button.
2. WHEN the Global_Admin clicks the cutover button, THE Progress_Screen SHALL require the Global_Admin to type "CONFIRM CUTOVER" to proceed.
3. WHEN cutover is confirmed, THE Migration_Engine SHALL pause all incoming requests for a brief maintenance window (target under 5 seconds).
4. DURING cutover, THE Migration_Engine SHALL update the active database engine and session factory to point to the Target_Database.
5. DURING cutover, THE Migration_Engine SHALL flush all connection pools connected to the Source_Database.
6. WHEN cutover completes, THE Migration_Engine SHALL verify that the application can read from and write to the Target_Database.
7. IF the cutover verification fails, THEN THE Migration_Engine SHALL automatically roll back to the Source_Database and report the failure.
8. WHEN cutover succeeds, THE Migration_Engine SHALL log the cutover event in the audit log with the Global_Admin user ID, timestamp, and both database connection identifiers (with passwords masked).

### Requirement 9: Rollback Capability

**User Story:** As a Global_Admin, I want to roll back to the old database if something goes wrong after cutover, so that I can recover from unexpected issues.

#### Acceptance Criteria

1. WHEN cutover has completed, THE Progress_Screen SHALL display a "Roll Back to Previous Database" button for 24 hours.
2. WHEN the Global_Admin initiates a rollback, THE Migration_Engine SHALL switch the active database connection back to the Source_Database.
3. DURING rollback, THE Migration_Engine SHALL pause incoming requests for a brief maintenance window (target under 5 seconds).
4. WHEN rollback completes, THE Migration_Engine SHALL verify that the application can read from and write to the Source_Database.
5. THE Migration_Engine SHALL log the rollback event in the audit log with the reason provided by the Global_Admin.
6. IF more than 24 hours have passed since cutover, THEN THE Progress_Screen SHALL disable the rollback button and display a warning that rollback is no longer available due to potential data divergence.

### Requirement 10: Migration Job Persistence and History

**User Story:** As a Global_Admin, I want to see a history of past migration attempts, so that I can audit previous migrations and troubleshoot failures.

#### Acceptance Criteria

1. THE Migration_Engine SHALL persist every Migration_Job to the database with status, timestamps, source and target connection identifiers (passwords masked), progress data, and Integrity_Check results.
2. THE Migration_Engine SHALL allow only one active Migration_Job at a time.
3. IF a migration is already in progress, THEN THE Migration_Engine SHALL reject new migration requests with a descriptive error.
4. THE Progress_Screen SHALL display a list of past Migration_Jobs with their status, start time, end time, and record counts.
5. WHEN the Global_Admin selects a past Migration_Job, THE Progress_Screen SHALL display the full details including Integrity_Check results and any error messages.

### Requirement 11: Security

**User Story:** As a Global_Admin, I want the migration process to handle credentials securely, so that database passwords are not exposed.

#### Acceptance Criteria

1. THE Migration_Engine SHALL encrypt the Target_Database Connection_String at rest using the platform's envelope encryption.
2. THE Migration_Engine SHALL transmit Connection_Strings only over HTTPS.
3. THE Migration_Engine SHALL never include database passwords in API responses, log output, or error messages.
4. WHEN a Migration_Job is stored, THE Migration_Engine SHALL store only the host, port, and database name — not the full Connection_String.
5. THE Migration_Engine SHALL validate that the Target_Database connection uses SSL when the platform environment is production or staging.

### Requirement 12: Cancellation

**User Story:** As a Global_Admin, I want to cancel a migration that is in progress, so that I can abort if I made a mistake or conditions changed.

#### Acceptance Criteria

1. WHILE migration is in progress, THE Progress_Screen SHALL display a "Cancel Migration" button.
2. WHEN the Global_Admin cancels a migration, THE Migration_Engine SHALL stop copying data, disable dual-write, and clean up any partially migrated data on the Target_Database.
3. WHEN cancellation completes, THE Migration_Engine SHALL update the Migration_Job status to "cancelled" and log the cancellation in the audit log.
4. AFTER cancellation, THE Migration_Engine SHALL continue operating normally using the Source_Database with no residual effects.
