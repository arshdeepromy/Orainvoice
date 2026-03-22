# Design Document: Live Database Migration

## Overview

The Live Database Migration feature provides a guided, zero-downtime workflow for migrating the entire WorkshopPro NZ platform database from one PostgreSQL server to another. It is accessed exclusively by `global_admin` users from the Global Settings page.

The migration follows a phased pipeline:

1. **Connection Input & Validation** — The admin enters a target database connection string; the system validates format, connectivity, PostgreSQL version, user privileges, and emptiness.
2. **Schema Migration** — Alembic migrations are run against the target database to replicate the full schema.
3. **Data Copy with Dual-Write** — Data is copied table-by-table in dependency order while a dual-write proxy ensures all new writes land on both source and target databases.
4. **Integrity Verification** — Row counts, foreign key references, financial totals, and sequence values are compared between source and target.
5. **Cutover** — The application atomically switches its database engine and session factory to the target, with automatic rollback on failure.
6. **Post-Cutover Rollback Window** — A 24-hour rollback window allows reverting to the source database.

The entire lifecycle is tracked as a `MigrationJob` persisted to the database, with real-time progress exposed via a polling status endpoint and displayed on a React-based Progress Screen.

### Key Design Decisions

- **Background task via asyncio** — Migration runs as a background `asyncio.Task` rather than Celery, since the platform already uses FastAPI's async runtime and the migration is a single long-running operation per deployment. Redis is used for progress state sharing.
- **Dual-write at the SQLAlchemy event level** — Rather than database-level replication (e.g., logical replication), dual-write is implemented via SQLAlchemy `after_flush` session events. This keeps the solution self-contained and avoids requiring PostgreSQL superuser privileges on the source.
- **Alembic programmatic API** — Schema migration uses Alembic's `command.upgrade()` pointed at the target database URL, reusing the existing migration history.
- **Atomic cutover via engine swap** — Cutover replaces the global `engine` and `async_session_factory` in `app.core.database`, then disposes the old connection pool. A brief request pause (target < 5s) is achieved by holding a Redis-based migration lock that middleware checks.

```mermaid
stateDiagram-v2
    [*] --> idle
    idle --> validating: Submit connection string
    validating --> schema_migrating: Validation passed
    validating --> idle: Validation failed
    schema_migrating --> copying_data: Schema complete
    schema_migrating --> failed: Alembic error
    copying_data --> integrity_check: All tables copied + queues drained
    copying_data --> failed: Unrecoverable copy error
    copying_data --> cancelled: Admin cancels
    integrity_check --> ready_for_cutover: Integrity passed
    integrity_check --> failed: Integrity failed
    ready_for_cutover --> cutting_over: Admin confirms cutover
    cutting_over --> completed: Cutover verified
    cutting_over --> failed: Cutover verification failed (auto-rollback)
    completed --> rolled_back: Admin rolls back (within 24h)
    failed --> idle: Admin starts new migration
    cancelled --> idle: Admin starts new migration
    rolled_back --> idle: Admin starts new migration
```

## Architecture

### System Context

```mermaid
graph TB
    subgraph Frontend
        PS[Progress Screen<br/>React + TypeScript]
    end

    subgraph Backend["FastAPI Backend"]
        MR[Migration Router<br/>/api/v1/admin/migration/*]
        MS[Migration Service<br/>Orchestrator]
        DWP[Dual-Write Proxy<br/>SQLAlchemy Events]
        IC[Integrity Checker]
        CO[Cutover Manager]
    end

    subgraph Infrastructure
        SRC[(Source PostgreSQL)]
        TGT[(Target PostgreSQL)]
        RD[(Redis)]
    end

    PS -->|REST + Polling| MR
    MR --> MS
    MS --> DWP
    MS --> IC
    MS --> CO
    MS -->|Progress updates| RD
    DWP -->|Writes| SRC
    DWP -->|Writes| TGT
    IC -->|Reads| SRC
    IC -->|Reads| TGT
    CO -->|Engine swap| SRC
    CO -->|Engine swap| TGT
    PS -->|Poll every 2s| MR
```

### Component Responsibilities

| Component | Responsibility |
|---|---|
| `Migration Router` | REST endpoints for all migration operations; enforces `global_admin` RBAC |
| `Migration Service` | Orchestrates the full migration pipeline as a background task |
| `Connection Validator` | Validates connection string format, connectivity, PG version, privileges, emptiness |
| `Schema Migrator` | Runs Alembic `upgrade head` against the target database |
| `Data Copier` | Copies data table-by-table in dependency order with configurable batch sizes |
| `Dual-Write Proxy` | Intercepts SQLAlchemy flush events to replicate writes to the target database |
| `Integrity Checker` | Compares row counts, FK references, financial totals, and sequences |
| `Cutover Manager` | Swaps the global engine/session factory, disposes old pools, verifies connectivity |
| `Progress Screen` | React UI displaying real-time progress, integrity results, and action buttons |


## Components and Interfaces

### Backend Components

#### 1. Migration Router (`app/modules/admin/migration_router.py`)

A dedicated sub-router mounted under the existing admin router. All endpoints require `global_admin` role via `require_role("global_admin")` dependency.

```python
# Endpoints
POST   /api/v1/admin/migration/validate       # Validate target connection
POST   /api/v1/admin/migration/start           # Start migration pipeline
GET    /api/v1/admin/migration/status/{job_id} # Poll migration progress
POST   /api/v1/admin/migration/cutover/{job_id}  # Confirm cutover
POST   /api/v1/admin/migration/rollback/{job_id} # Rollback to source
POST   /api/v1/admin/migration/cancel/{job_id}   # Cancel in-progress migration
GET    /api/v1/admin/migration/history          # List past migration jobs
GET    /api/v1/admin/migration/history/{job_id} # Get full job details
```

#### 2. Migration Schemas (`app/modules/admin/migration_schemas.py`)

```python
class ConnectionValidateRequest(BaseModel):
    connection_string: str          # postgresql+asyncpg://...
    ssl_mode: str = "prefer"        # require | prefer | disable

class ConnectionValidateResponse(BaseModel):
    valid: bool
    server_version: str | None = None
    available_disk_space_mb: int | None = None
    has_existing_tables: bool = False
    error: str | None = None

class MigrationStartRequest(BaseModel):
    connection_string: str
    ssl_mode: str = "prefer"
    batch_size: int = 1000
    confirm_overwrite: bool = False  # Required if target has existing tables

class MigrationStatusResponse(BaseModel):
    job_id: str
    status: MigrationJobStatus
    current_table: str | None = None
    tables: list[TableProgress]
    rows_processed: int
    rows_total: int
    progress_pct: float
    estimated_seconds_remaining: int | None = None
    dual_write_queue_depth: int = 0
    integrity_check: IntegrityCheckResult | None = None
    error_message: str | None = None
    started_at: str
    updated_at: str

class TableProgress(BaseModel):
    table_name: str
    source_count: int
    migrated_count: int
    status: str  # pending | in_progress | completed | failed

class IntegrityCheckResult(BaseModel):
    passed: bool
    row_counts: dict[str, RowCountComparison]
    fk_errors: list[str]
    financial_totals: dict[str, FinancialComparison]
    sequence_checks: dict[str, SequenceComparison]

class RowCountComparison(BaseModel):
    source: int
    target: int
    match: bool

class FinancialComparison(BaseModel):
    source_total: float
    target_total: float
    match: bool

class SequenceComparison(BaseModel):
    source_value: int
    target_value: int
    valid: bool  # target >= source

class CutoverRequest(BaseModel):
    confirmation_text: str  # Must be "CONFIRM CUTOVER"

class RollbackRequest(BaseModel):
    reason: str

class MigrationJobSummary(BaseModel):
    job_id: str
    status: str
    started_at: str
    completed_at: str | None
    rows_total: int
    source_host: str
    target_host: str

class MigrationJobDetail(MigrationJobSummary):
    integrity_check: IntegrityCheckResult | None
    error_message: str | None
    tables: list[TableProgress]
```

#### 3. Migration Service (`app/modules/admin/migration_service.py`)

The core orchestrator. Key methods:

```python
class MigrationService:
    async def validate_connection(self, conn_str: str, ssl_mode: str) -> ConnectionValidateResponse
    async def start_migration(self, conn_str: str, ssl_mode: str, batch_size: int, user_id: UUID) -> str  # returns job_id
    async def get_status(self, job_id: str) -> MigrationStatusResponse
    async def cancel_migration(self, job_id: str, user_id: UUID) -> None
    async def cutover(self, job_id: str, user_id: UUID) -> None
    async def rollback(self, job_id: str, user_id: UUID, reason: str) -> None
    async def get_history(self) -> list[MigrationJobSummary]
    async def get_job_detail(self, job_id: str) -> MigrationJobDetail
```

Internal pipeline methods (run as background task):

```python
    async def _run_pipeline(self, job_id: str) -> None:
        # 1. Create target engine
        # 2. Run Alembic migrations on target
        # 3. Enable dual-write proxy
        # 4. Copy data table-by-table
        # 5. Drain dual-write retry queue
        # 6. Run integrity checks
        # 7. Update job status to ready_for_cutover or failed
```

#### 4. Dual-Write Proxy (`app/modules/admin/dual_write.py`)

Hooks into SQLAlchemy's `after_flush` event on the source session factory. When enabled, it captures all pending INSERT/UPDATE/DELETE operations and replays them against the target database.

```python
class DualWriteProxy:
    def __init__(self, target_engine: AsyncEngine):
        self.target_engine = target_engine
        self.enabled = False
        self.retry_queue: asyncio.Queue = asyncio.Queue()
        self.queue_depth: int = 0

    def enable(self) -> None
    def disable(self) -> None
    async def drain_retry_queue(self) -> None
    async def _on_after_flush(self, session, flush_context) -> None
```

#### 5. Integrity Checker (`app/modules/admin/integrity_checker.py`)

```python
class IntegrityChecker:
    def __init__(self, source_engine: AsyncEngine, target_engine: AsyncEngine):
        ...

    async def run(self) -> IntegrityCheckResult:
        row_counts = await self._compare_row_counts()
        fk_errors = await self._check_foreign_keys()
        financial_totals = await self._compare_financial_totals()
        sequence_checks = await self._compare_sequences()
        ...
```

#### 6. Cutover Manager (`app/modules/admin/cutover_manager.py`)

```python
class CutoverManager:
    async def execute_cutover(self, target_engine: AsyncEngine, target_url: str) -> bool
    async def execute_rollback(self, source_url: str) -> bool
    async def _swap_engine(self, new_url: str) -> None
    async def _verify_connectivity(self) -> bool
    async def _pause_requests(self) -> None
    async def _resume_requests(self) -> None
```

### Frontend Components

#### 1. LiveMigrationTool (`frontend/src/pages/admin/LiveMigrationTool.tsx`)

A new page component (separate from the existing `MigrationTool.tsx` which handles data import). This component manages the full live database migration workflow.

Sub-components:
- `ConnectionForm` — Input for connection string and SSL mode, with validation feedback
- `MigrationProgress` — Real-time progress bar, table breakdown, ETA, dual-write queue depth
- `IntegrityReport` — Displays integrity check results (row counts, financials, FK errors, sequences)
- `CutoverPanel` — Cutover confirmation with "CONFIRM CUTOVER" text input
- `RollbackPanel` — Rollback button with 24-hour countdown timer
- `MigrationHistory` — Table of past migration jobs with detail drill-down


## Data Models

### MigrationJob Table

A new `migration_jobs` table persists the state of each migration attempt. Created via an Alembic migration.

```sql
CREATE TABLE migration_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status          VARCHAR(30) NOT NULL DEFAULT 'pending',
    -- Connection info (passwords NEVER stored)
    source_host     VARCHAR(255) NOT NULL,
    source_port     INTEGER NOT NULL,
    source_db_name  VARCHAR(255) NOT NULL,
    target_host     VARCHAR(255) NOT NULL,
    target_port     INTEGER NOT NULL,
    target_db_name  VARCHAR(255) NOT NULL,
    ssl_mode        VARCHAR(10) NOT NULL DEFAULT 'prefer',
    -- Encrypted connection string for active use (cleared after completion/cancellation)
    target_conn_encrypted BYTEA,
    -- Progress tracking
    batch_size      INTEGER NOT NULL DEFAULT 1000,
    current_table   VARCHAR(255),
    rows_processed  BIGINT NOT NULL DEFAULT 0,
    rows_total      BIGINT NOT NULL DEFAULT 0,
    progress_pct    REAL NOT NULL DEFAULT 0.0,
    table_progress  JSONB NOT NULL DEFAULT '[]',
    dual_write_queue_depth INTEGER NOT NULL DEFAULT 0,
    -- Integrity check results
    integrity_check JSONB,
    -- Error tracking
    error_message   TEXT,
    -- Timestamps
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    cutover_at      TIMESTAMPTZ,
    rollback_deadline TIMESTAMPTZ,  -- cutover_at + 24 hours
    cancelled_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Who initiated
    initiated_by    UUID NOT NULL REFERENCES users(id),
    -- Constraint: status must be valid
    CONSTRAINT ck_migration_job_status CHECK (
        status IN (
            'pending', 'validating', 'schema_migrating', 'copying_data',
            'draining_queue', 'integrity_check', 'ready_for_cutover',
            'cutting_over', 'completed', 'failed', 'cancelled', 'rolled_back'
        )
    )
);

CREATE INDEX idx_migration_jobs_status ON migration_jobs(status);
CREATE INDEX idx_migration_jobs_created ON migration_jobs(created_at DESC);
```

### SQLAlchemy ORM Model

```python
class MigrationJob(Base):
    __tablename__ = "migration_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")

    source_host: Mapped[str] = mapped_column(String(255), nullable=False)
    source_port: Mapped[int] = mapped_column(Integer, nullable=False)
    source_db_name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_host: Mapped[str] = mapped_column(String(255), nullable=False)
    target_port: Mapped[int] = mapped_column(Integer, nullable=False)
    target_db_name: Mapped[str] = mapped_column(String(255), nullable=False)
    ssl_mode: Mapped[str] = mapped_column(String(10), nullable=False, default="prefer")

    target_conn_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    batch_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    current_table: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rows_processed: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    rows_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    progress_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    table_progress: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="'[]'")
    dual_write_queue_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    integrity_check: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cutover_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rollback_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    initiated_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
```

### MigrationJobStatus Enum

```python
class MigrationJobStatus(str, Enum):
    PENDING = "pending"
    VALIDATING = "validating"
    SCHEMA_MIGRATING = "schema_migrating"
    COPYING_DATA = "copying_data"
    DRAINING_QUEUE = "draining_queue"
    INTEGRITY_CHECK = "integrity_check"
    READY_FOR_CUTOVER = "ready_for_cutover"
    CUTTING_OVER = "cutting_over"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ROLLED_BACK = "rolled_back"
```

### Redis Keys

| Key | Type | TTL | Purpose |
|---|---|---|---|
| `migration:active_job` | String (job_id) | None | Ensures only one active migration at a time |
| `migration:progress:{job_id}` | Hash | 24h | Real-time progress data for polling |
| `migration:lock` | String | 30s | Request pause lock during cutover/rollback |
| `migration:dual_write_retry:{job_id}` | List | None | Queued retry operations for failed dual-writes |

### Connection String Parsing

The connection string is parsed using `urllib.parse.urlparse` to extract host, port, and database name for storage. The full connection string is encrypted via `envelope_encrypt()` and stored in `target_conn_encrypted` only while the migration is active. It is cleared (set to NULL) upon completion, cancellation, or failure.

Password masking for API responses and logs uses a regex replacement: `postgresql+asyncpg://user:****@host:port/dbname`.


## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: RBAC enforcement on migration endpoints

*For any* user with a role other than `global_admin`, and *for any* migration endpoint, the system should return a 403 Forbidden response. Conversely, *for any* user with the `global_admin` role, the system should allow access (not return 403).

**Validates: Requirements 1.1, 1.2**

### Property 2: Connection string format validation

*For any* string, the connection string validator should return valid=true if and only if the string matches the PostgreSQL async connection URI format (`postgresql+asyncpg://user:pass@host:port/dbname`). *For any* string that does not match, the validator should return valid=false with a non-empty error message describing the expected format.

**Validates: Requirements 2.3, 2.4**

### Property 3: Password masking in all outputs

*For any* PostgreSQL connection string containing a password, the `mask_password()` function should return a string where the password is replaced with `****`, the scheme/user/host/port/dbname are preserved, and the original password does not appear anywhere in the output.

**Validates: Requirements 2.5, 11.3**

### Property 4: PostgreSQL version compatibility check

*For any* PostgreSQL version string, the version checker should return compatible=true if and only if the major version is >= 13. Version strings like "13.4", "14.0", "15.1" should pass; "12.9", "11.0", "9.6" should fail.

**Validates: Requirements 3.3**

### Property 5: Table dependency ordering

*For any* directed acyclic graph of table foreign key dependencies, the dependency sorter should produce a topological ordering where every table appears after all tables it depends on (i.e., for every foreign key from table A to table B, B appears before A in the sorted list).

**Validates: Requirements 5.2**

### Property 6: Batch partitioning correctness

*For any* list of N rows and *for any* batch size B (where B >= 1), the batch generator should produce exactly `ceil(N / B)` batches, each batch should have at most B rows, and the concatenation of all batches should equal the original list in order.

**Validates: Requirements 5.3**

### Property 7: Progress percentage calculation

*For any* non-negative integers `rows_processed` and `rows_total` (where `rows_total > 0`), the progress percentage should equal `(rows_processed / rows_total) * 100`, clamped to the range [0, 100].

**Validates: Requirements 5.4**

### Property 8: ETA calculation

*For any* positive `rows_processed`, positive `elapsed_seconds`, and `rows_total >= rows_processed`, the estimated time remaining should equal `(rows_total - rows_processed) / (rows_processed / elapsed_seconds)`. When `rows_processed` is 0, the ETA should be None.

**Validates: Requirements 5.8**

### Property 9: Dual-write retry queue depth accuracy

*For any* sequence of enqueue and dequeue operations on the retry queue, the reported queue depth should always equal the number of enqueued items minus the number of successfully dequeued items.

**Validates: Requirements 6.4**

### Property 10: Dual-write retry queue FIFO ordering

*For any* sequence of operations enqueued to the retry queue, draining the queue should yield the operations in the exact same order they were enqueued (first-in, first-out).

**Validates: Requirements 6.5**

### Property 11: Row count and financial total comparison correctness

*For any* two maps of table names to numeric values (representing source and target counts or totals), the comparison function should return `match=true` for a given key if and only if the source and target values are equal. The overall check should pass if and only if all individual comparisons match.

**Validates: Requirements 7.2, 7.4**

### Property 12: Sequence value validation

*For any* two maps of sequence names to integer values (source and target), the sequence check should return `valid=true` for a given sequence if and only if `target_value >= source_value`. The overall check should pass if and only if all individual sequence checks are valid.

**Validates: Requirements 7.5**

### Property 13: Cutover availability determined by integrity check result

*For any* migration job, the cutover action should be allowed if and only if the job status is `ready_for_cutover` and the integrity check result has `passed=true`. *For any* job where the integrity check has `passed=false`, the cutover endpoint should return an error.

**Validates: Requirements 7.7, 8.1**

### Property 14: Cutover confirmation text validation

*For any* string that is not exactly `"CONFIRM CUTOVER"`, the cutover endpoint should reject the request. Only the exact string `"CONFIRM CUTOVER"` should be accepted.

**Validates: Requirements 8.2**

### Property 15: Audit log entries contain required fields with masked passwords

*For any* migration event (cutover or rollback), the audit log entry should contain the acting user ID, a timestamp, and both source and target database identifiers. No audit log entry should contain a plaintext database password.

**Validates: Requirements 8.8, 9.5**

### Property 16: Rollback availability within 24-hour window

*For any* completed migration job with a `cutover_at` timestamp, the rollback action should be available if and only if the current time is within 24 hours of `cutover_at`. After 24 hours, rollback requests should be rejected.

**Validates: Requirements 9.1, 9.6**

### Property 17: Migration job serialization round-trip

*For any* valid `MigrationJob` model instance, serializing it to the `MigrationStatusResponse` schema and then comparing the fields should preserve all values (status, timestamps, progress data, integrity check results).

**Validates: Requirements 10.1**

### Property 18: Only one active migration at a time

*For any* state where a migration job exists with a status in the active set (`validating`, `schema_migrating`, `copying_data`, `draining_queue`, `integrity_check`, `ready_for_cutover`, `cutting_over`), attempting to start a new migration should be rejected with a descriptive error.

**Validates: Requirements 10.2, 10.3**

### Property 19: Connection string encryption round-trip

*For any* valid PostgreSQL connection string, encrypting it with `envelope_encrypt()` and then decrypting with `envelope_decrypt_str()` should return the original connection string.

**Validates: Requirements 11.1**

### Property 20: Stored job contains only parsed connection components

*For any* connection string, the stored `MigrationJob` record should contain `target_host`, `target_port`, and `target_db_name` matching the parsed components of the connection string, and should not contain the full connection string in any unencrypted field.

**Validates: Requirements 11.4**

### Property 21: SSL required in production and staging environments

*For any* environment value in `("production", "staging")` and *for any* connection string with `ssl_mode="disable"`, the validation should reject the connection. *For any* environment value of `"development"`, `ssl_mode="disable"` should be accepted.

**Validates: Requirements 11.5**

### Property 22: Cancellation updates job status and creates audit entry

*For any* in-progress migration job, cancelling it should transition the status to `"cancelled"` and produce an audit log entry with action `"migration.cancelled"`.

**Validates: Requirements 12.3**


## Error Handling

### Backend Error Handling

| Error Scenario | HTTP Status | Response | Recovery |
|---|---|---|---|
| Non-global_admin access | 403 | `{"detail": "Global_Admin role required"}` | N/A — access denied |
| Invalid connection string format | 422 | `{"detail": "Invalid connection string format. Expected: postgresql+asyncpg://user:pass@host:port/dbname"}` | User corrects input |
| Target database unreachable | 400 | `{"detail": "Connection failed: <reason>", "error_code": "CONNECTION_FAILED"}` | User checks target DB |
| Incompatible PG version | 400 | `{"detail": "PostgreSQL version <version> is not supported. Minimum required: 13.0"}` | User upgrades target |
| Insufficient privileges | 400 | `{"detail": "Missing privileges: <list>. Required: CREATE, INSERT, UPDATE, DELETE, SELECT"}` | User grants privileges |
| Target has existing tables (no confirm) | 409 | `{"detail": "Target database contains existing tables. Set confirm_overwrite=true to proceed."}` | User confirms |
| Migration already in progress | 409 | `{"detail": "A migration is already in progress (job_id: <id>). Cancel it first."}` | User cancels or waits |
| Alembic migration failure | 500 | Job status → `failed`, `error_message` contains revision and error | User fixes target DB, retries |
| Batch copy failure (after 3 retries) | — | Table marked `failed`, job continues with other tables | Review failed tables |
| Dual-write target failure | — | Operation queued for retry, source write succeeds | Queue drains before integrity check |
| Integrity check failure | — | Job status → `failed`, integrity results show specific failures | User reviews, starts new migration |
| Cutover verification failure | — | Auto-rollback to source, job status → `failed` | User investigates, retries |
| Invalid cutover confirmation text | 400 | `{"detail": "Confirmation text must be exactly 'CONFIRM CUTOVER'"}` | User types correct text |
| Rollback after 24h window | 400 | `{"detail": "Rollback window expired. Cutover was at <timestamp>, 24h deadline passed."}` | Manual intervention required |
| SSL required but disabled | 400 | `{"detail": "SSL is required for database connections in production/staging environments"}` | User enables SSL |
| Cancel non-active migration | 400 | `{"detail": "Migration is not in a cancellable state (current: <status>)"}` | N/A |

### Cancellable States

A migration can only be cancelled when its status is one of: `validating`, `schema_migrating`, `copying_data`, `draining_queue`.

### Retry Strategy

- **Batch copy retries**: 3 attempts with exponential backoff (1s, 2s, 4s)
- **Dual-write retries**: Queued in Redis list, drained in order before integrity check
- **Connection validation**: Single attempt with 10-second timeout

### Frontend Error Handling

- API errors are displayed in an error banner at the top of the migration tool
- Connection validation errors are shown inline below the connection string input
- Progress errors are shown in the progress tracker with a red status badge
- Integrity failures are displayed in the integrity report with per-table/per-check detail
- Network errors during polling are silently retried on the next poll interval

## Testing Strategy

### Property-Based Testing

Property-based tests use the `hypothesis` library (Python) and `fast-check` (TypeScript) with a minimum of 100 iterations per property. Each test is tagged with a comment referencing the design property.

**Python (Backend)**:
- Library: `hypothesis` with `pytest`
- Config: `@settings(max_examples=100)`
- Tag format: `# Feature: live-database-migration, Property N: <title>`

**TypeScript (Frontend)**:
- Library: `fast-check` with `vitest`
- Config: `fc.assert(property, { numRuns: 100 })`
- Tag format: `// Feature: live-database-migration, Property N: <title>`

### Backend Property Tests (`tests/properties/test_migration_properties.py`)

| Property | Test Description |
|---|---|
| P1 | Generate random roles, verify only global_admin passes RBAC check |
| P2 | Generate random strings, verify connection string validator correctness |
| P3 | Generate connection strings with random passwords, verify masking |
| P4 | Generate random PG version strings, verify compatibility check |
| P5 | Generate random table dependency DAGs, verify topological sort |
| P6 | Generate random row lists and batch sizes, verify batch partitioning |
| P7 | Generate random (rows_processed, rows_total) pairs, verify percentage |
| P8 | Generate random progress states, verify ETA calculation |
| P9 | Generate enqueue/dequeue sequences, verify queue depth |
| P10 | Generate operation sequences, verify FIFO drain order |
| P11 | Generate source/target count maps, verify comparison logic |
| P12 | Generate source/target sequence maps, verify validation |
| P13 | Generate jobs with various integrity results, verify cutover gating |
| P14 | Generate random strings, verify only "CONFIRM CUTOVER" accepted |
| P15 | Generate migration events, verify audit log fields and password masking |
| P16 | Generate cutover timestamps, verify 24h rollback window |
| P17 | Generate MigrationJob instances, verify serialization round-trip |
| P18 | Generate active job states, verify new migration rejection |
| P19 | Generate connection strings, verify encrypt/decrypt round-trip |
| P20 | Generate connection strings, verify stored fields match parsed components |
| P21 | Generate environment/ssl_mode combinations, verify SSL enforcement |
| P22 | Generate in-progress jobs, verify cancellation state transition |

### Frontend Property Tests (`frontend/src/pages/admin/__tests__/live-migration.properties.test.ts`)

| Property | Test Description |
|---|---|
| P7 | Generate random progress values, verify progress bar percentage rendering |
| P8 | Generate random progress states, verify ETA display |
| P13 | Generate jobs with various statuses, verify cutover button enabled/disabled |
| P16 | Generate cutover timestamps, verify rollback button visibility |

### Unit Tests

Unit tests complement property tests by covering specific examples, edge cases, and integration points:

**Backend** (`tests/test_migration.py`):
- Connection validation with real-format strings (happy path)
- Alembic failure handling (mocked)
- Batch copy retry exhaustion (mocked)
- Dual-write failure queuing (mocked)
- Cutover with verification failure → auto-rollback (mocked)
- Cancel during each cancellable state
- History endpoint returns correct job list

**Frontend** (`frontend/src/pages/admin/__tests__/live-migration.test.tsx`):
- Connection form submission and validation feedback
- Progress polling starts/stops based on job status
- Cutover confirmation modal requires exact text
- Rollback button visibility based on time
- Migration history table rendering
- Error banner display on API failure

