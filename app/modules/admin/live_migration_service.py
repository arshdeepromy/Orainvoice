"""Live database migration service.

Orchestrates the full zero-downtime migration pipeline: connection validation,
schema migration, data copy with dual-write, integrity verification, cutover,
rollback, and cancellation.

This module is separate from ``migration_service.py`` (which covers the V1 org
data migration tool).

Requirements: 2.3–2.5, 3.1–3.7, 4.1–4.4, 5.1–5.9, 6.1–6.5, 7.1, 8.1–8.8,
              9.1–9.6, 10.1–10.5, 11.1–11.5, 12.1–12.4
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import settings
from app.core.audit import write_audit_log
from app.core.encryption import envelope_decrypt_str, envelope_encrypt
from app.core.redis import redis_pool
from app.modules.admin.cutover_manager import (
    CutoverManager,
    is_rollback_available,
    validate_cutover_confirmation,
)
from app.modules.admin.dual_write import DualWriteProxy
from app.modules.admin.integrity_checker import IntegrityChecker
from app.modules.admin.live_migration_schemas import (
    ConnectionValidateResponse,
    IntegrityCheckResult,
    MigrationJobDetail,
    MigrationJobSummary,
    MigrationStatusResponse,
    TableProgress,
    calculate_eta,
    calculate_progress_pct,
    check_pg_version_compatible,
    mask_password,
    parse_connection_string,
    validate_connection_string_format,
)
from app.modules.admin.migration_models import MigrationJob, MigrationJobStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Active status sets
# ---------------------------------------------------------------------------

_ACTIVE_STATUSES = frozenset({
    MigrationJobStatus.VALIDATING.value,
    MigrationJobStatus.SCHEMA_MIGRATING.value,
    MigrationJobStatus.COPYING_DATA.value,
    MigrationJobStatus.DRAINING_QUEUE.value,
    MigrationJobStatus.INTEGRITY_CHECK.value,
    MigrationJobStatus.READY_FOR_CUTOVER.value,
    MigrationJobStatus.CUTTING_OVER.value,
})

_CANCELLABLE_STATUSES = frozenset({
    MigrationJobStatus.VALIDATING.value,
    MigrationJobStatus.SCHEMA_MIGRATING.value,
    MigrationJobStatus.COPYING_DATA.value,
    MigrationJobStatus.DRAINING_QUEUE.value,
})

# Redis keys
_ACTIVE_JOB_KEY = "migration:active_job"
_PROGRESS_KEY_PREFIX = "migration:progress:"
_CANCEL_FLAG_PREFIX = "migration:cancel:"


# ---------------------------------------------------------------------------
# Pure helper functions (property-testable)
# ---------------------------------------------------------------------------


def get_table_dependency_order(dependencies: dict[str, list[str]]) -> list[str]:
    """Topological sort of table FK dependencies.

    *dependencies* maps each table name to a list of tables it depends on
    (i.e. tables whose rows must exist first due to foreign keys).

    Returns tables in dependency order — a table appears only after all
    tables it depends on.

    Raises ``ValueError`` if a cycle is detected.
    """
    # Kahn's algorithm
    in_degree: dict[str, int] = {}
    graph: dict[str, list[str]] = {}

    # Initialise all nodes
    all_tables: set[str] = set(dependencies.keys())
    for deps in dependencies.values():
        all_tables.update(deps)

    for table in all_tables:
        in_degree[table] = 0
        graph[table] = []

    for table, deps in dependencies.items():
        for dep in deps:
            graph[dep].append(table)  # dep -> table (table depends on dep)
            in_degree[table] += 1

    queue: deque[str] = deque()
    for table in sorted(all_tables):  # sorted for determinism
        if in_degree[table] == 0:
            queue.append(table)

    result: list[str] = []
    while queue:
        node = queue.popleft()
        result.append(node)
        for neighbour in sorted(graph[node]):  # sorted for determinism
            in_degree[neighbour] -= 1
            if in_degree[neighbour] == 0:
                queue.append(neighbour)

    if len(result) != len(all_tables):
        raise ValueError("Cycle detected in table dependencies")

    return result


def is_active_status(status: str) -> bool:
    """Return ``True`` if *status* is in the active set."""
    return status in _ACTIVE_STATUSES


def is_cancellable_status(status: str) -> bool:
    """Return ``True`` if *status* is cancellable."""
    return status in _CANCELLABLE_STATUSES


def check_ssl_required(environment: str, ssl_mode: str) -> tuple[bool, str | None]:
    """Return ``(allowed, error_message)``.

    ``ssl_mode='disable'`` is rejected in production and staging environments.
    """
    if environment in ("production", "staging") and ssl_mode == "disable":
        return False, "SSL is required for database connections in production/staging environments"
    return True, None


# ---------------------------------------------------------------------------
# LiveMigrationService
# ---------------------------------------------------------------------------


class LiveMigrationService:
    """Orchestrates the full live database migration pipeline."""

    def __init__(self, db: AsyncSession, redis: aioredis.Redis) -> None:
        self.db = db
        self.redis = redis

    # -- 8.1: validate_connection -------------------------------------------

    async def validate_connection(
        self,
        conn_str: str,
        ssl_mode: str,
    ) -> ConnectionValidateResponse:
        """Validate target database connection.

        Steps:
        1. Validate connection string format.
        2. Check SSL requirement for prod/staging.
        3. Attempt connection with 10s timeout.
        4. Check PostgreSQL version >= 13.
        5. Check user privileges (CREATE, INSERT, UPDATE, DELETE, SELECT).
        6. Check whether the target database is empty.
        """
        # 1. Format validation
        valid, err = validate_connection_string_format(conn_str)
        if not valid:
            return ConnectionValidateResponse(valid=False, error=err)

        # 2. SSL check
        ssl_ok, ssl_err = check_ssl_required(settings.environment, ssl_mode)
        if not ssl_ok:
            return ConnectionValidateResponse(valid=False, error=ssl_err)

        # 3. Attempt connection with 10s timeout
        try:
            target_engine = create_async_engine(conn_str, echo=False)
            async with asyncio.timeout(10):
                async with target_engine.connect() as conn:
                    # 4. Check PG version
                    result = await conn.execute(text("SHOW server_version"))
                    version_str = result.scalar_one()
                    if not check_pg_version_compatible(version_str):
                        await target_engine.dispose()
                        return ConnectionValidateResponse(
                            valid=False,
                            error=(
                                f"PostgreSQL version {version_str} is not supported. "
                                "Minimum required: 13.0"
                            ),
                        )

                    # 5. Check privileges
                    priv_query = text(
                        "SELECT privilege_type FROM information_schema.role_table_grants "
                        "WHERE grantee = current_user "
                        "UNION "
                        "SELECT privilege_type FROM information_schema.role_usage_grants "
                        "WHERE grantee = current_user"
                    )
                    priv_result = await conn.execute(priv_query)
                    granted = {row[0].upper() for row in priv_result.fetchall()}

                    # Also check schema-level CREATE privilege
                    schema_priv_query = text(
                        "SELECT has_schema_privilege(current_user, 'public', 'CREATE')"
                    )
                    has_create = (await conn.execute(schema_priv_query)).scalar_one()
                    if has_create:
                        granted.add("CREATE")

                    required = {"CREATE", "INSERT", "UPDATE", "DELETE", "SELECT"}
                    missing = required - granted
                    if missing:
                        await target_engine.dispose()
                        return ConnectionValidateResponse(
                            valid=False,
                            error=(
                                f"Missing privileges: {', '.join(sorted(missing))}. "
                                "Required: CREATE, INSERT, UPDATE, DELETE, SELECT"
                            ),
                        )

                    # 6. Check emptiness
                    tables_query = text(
                        "SELECT tablename FROM pg_tables "
                        "WHERE schemaname = 'public'"
                    )
                    tables_result = await conn.execute(tables_query)
                    app_tables = [row[0] for row in tables_result.fetchall()]
                    has_existing = len(app_tables) > 0

                    # Get disk space (best effort)
                    try:
                        disk_query = text(
                            "SELECT pg_database_size(current_database())"
                        )
                        disk_result = await conn.execute(disk_query)
                        db_size_bytes = disk_result.scalar_one()
                        available_mb = int(db_size_bytes / (1024 * 1024))
                    except Exception:
                        available_mb = None

            await target_engine.dispose()

            return ConnectionValidateResponse(
                valid=True,
                server_version=version_str,
                available_disk_space_mb=available_mb,
                has_existing_tables=has_existing,
            )

        except asyncio.TimeoutError:
            masked = mask_password(conn_str)
            return ConnectionValidateResponse(
                valid=False,
                error=f"Connection timed out after 10 seconds to {masked}",
            )
        except Exception as exc:
            masked = mask_password(conn_str)
            # Ensure the original password doesn't leak in the error message
            error_msg = str(exc)
            parsed = parse_connection_string(conn_str)
            if parsed.get("password"):
                error_msg = error_msg.replace(parsed["password"], "****")
            return ConnectionValidateResponse(
                valid=False,
                error=f"Connection failed: {error_msg}",
            )


    # -- 8.2: start_migration & _run_pipeline --------------------------------

    async def start_migration(
        self,
        conn_str: str,
        ssl_mode: str,
        batch_size: int,
        user_id: UUID,
    ) -> str:
        """Start a new live database migration.

        Checks no active migration exists, creates a ``MigrationJob`` record,
        encrypts the connection string, and launches the background pipeline.

        Returns the new job ID.
        """
        # Check for active migration
        active_job = await self.redis.get(_ACTIVE_JOB_KEY)
        if active_job:
            raise ValueError(
                f"A migration is already in progress (job_id: {active_job}). "
                "Cancel it first."
            )

        # Parse connection components for storage
        parsed = parse_connection_string(conn_str)

        # Get source connection info from current database
        source_parsed = parse_connection_string(settings.database_url)

        # Encrypt the target connection string
        encrypted_conn = envelope_encrypt(conn_str)

        # Create MigrationJob record
        job = MigrationJob(
            id=uuid.uuid4(),
            status=MigrationJobStatus.VALIDATING.value,
            source_host=source_parsed.get("host", ""),
            source_port=source_parsed.get("port") or 5432,
            source_db_name=source_parsed.get("dbname", ""),
            target_host=parsed.get("host", ""),
            target_port=parsed.get("port") or 5432,
            target_db_name=parsed.get("dbname", ""),
            ssl_mode=ssl_mode,
            target_conn_encrypted=encrypted_conn,
            batch_size=batch_size,
            started_at=datetime.now(timezone.utc),
            initiated_by=user_id,
        )
        self.db.add(job)
        await self.db.flush()

        job_id = str(job.id)

        # Mark as active in Redis
        await self.redis.set(_ACTIVE_JOB_KEY, job_id)

        # Initialise progress hash in Redis
        await self.redis.hset(
            f"{_PROGRESS_KEY_PREFIX}{job_id}",
            mapping={
                "status": MigrationJobStatus.VALIDATING.value,
                "current_table": "",
                "rows_processed": "0",
                "rows_total": "0",
                "progress_pct": "0.0",
                "dual_write_queue_depth": "0",
                "error_message": "",
                "started_at": job.started_at.isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        await self.redis.expire(f"{_PROGRESS_KEY_PREFIX}{job_id}", 86400)  # 24h TTL

        # Log audit event
        await write_audit_log(
            self.db,
            action="migration.started",
            entity_type="migration_job",
            user_id=user_id,
            entity_id=job.id,
            after_value={
                "target_host": parsed.get("host", ""),
                "target_port": parsed.get("port"),
                "target_db_name": parsed.get("dbname", ""),
                "ssl_mode": ssl_mode,
                "batch_size": batch_size,
            },
        )

        # Launch background pipeline
        asyncio.create_task(self._run_pipeline(job_id))

        return job_id

    async def _run_pipeline(self, job_id: str) -> None:
        """Run the full migration pipeline as a background task.

        Steps:
        1. Create target engine from encrypted connection string.
        2. Run Alembic migrations on target (schema migration).
        3. Enable dual-write proxy.
        4. Copy data table-by-table in dependency order.
        5. Drain dual-write retry queue.
        6. Run integrity checks.
        7. Update job status to ready_for_cutover or failed.
        """
        try:
            # Load the job
            result = await self.db.execute(
                select(MigrationJob).where(MigrationJob.id == uuid.UUID(job_id))
            )
            job = result.scalar_one_or_none()
            if not job:
                logger.error("Migration job %s not found", job_id)
                return

            # Decrypt connection string
            conn_str = envelope_decrypt_str(job.target_conn_encrypted)

            # Create target engine
            target_engine = create_async_engine(conn_str, echo=False)

            # -- Step 1: Schema migration (Alembic) -------------------------
            await self._update_status(job_id, MigrationJobStatus.SCHEMA_MIGRATING.value)

            if await self._is_cancelled(job_id):
                await self._handle_cancellation(job_id, target_engine)
                return

            try:
                await self._run_alembic_on_target(conn_str)
            except Exception as exc:
                logger.exception("Alembic migration failed for job %s", job_id)
                await self._fail_job(job_id, f"Schema migration failed: {exc}")
                await target_engine.dispose()
                return

            # -- Step 2: Enable dual-write -----------------------------------
            await self._update_status(job_id, MigrationJobStatus.COPYING_DATA.value)

            dual_write = DualWriteProxy(target_engine)
            dual_write.enable()

            if await self._is_cancelled(job_id):
                dual_write.disable()
                await self._handle_cancellation(job_id, target_engine)
                return

            # -- Step 3: Copy data table-by-table ----------------------------
            try:
                await self._copy_all_tables(job_id, job, target_engine, dual_write)
            except Exception as exc:
                logger.exception("Data copy failed for job %s", job_id)
                dual_write.disable()
                await self._fail_job(job_id, f"Data copy failed: {exc}")
                await target_engine.dispose()
                return

            if await self._is_cancelled(job_id):
                dual_write.disable()
                await self._handle_cancellation(job_id, target_engine)
                return

            # -- Step 4: Drain retry queue -----------------------------------
            await self._update_status(job_id, MigrationJobStatus.DRAINING_QUEUE.value)

            try:
                await dual_write.drain_retry_queue()
            except Exception as exc:
                logger.exception("Queue drain failed for job %s", job_id)
                dual_write.disable()
                await self._fail_job(job_id, f"Queue drain failed: {exc}")
                await target_engine.dispose()
                return

            dual_write.disable()

            if await self._is_cancelled(job_id):
                await self._handle_cancellation(job_id, target_engine)
                return

            # -- Step 5: Integrity check -------------------------------------
            await self._update_status(job_id, MigrationJobStatus.INTEGRITY_CHECK.value)

            import app.core.database as db_mod

            checker = IntegrityChecker(db_mod.engine, target_engine)
            integrity_result = await checker.run()

            # Store integrity results
            result_dict = integrity_result.model_dump()
            await self.db.execute(
                select(MigrationJob).where(MigrationJob.id == uuid.UUID(job_id))
            )
            job = (
                await self.db.execute(
                    select(MigrationJob).where(MigrationJob.id == uuid.UUID(job_id))
                )
            ).scalar_one()
            job.integrity_check = result_dict
            await self.db.flush()

            # Update Redis with integrity results
            await self.redis.hset(
                f"{_PROGRESS_KEY_PREFIX}{job_id}",
                "integrity_check",
                json.dumps(result_dict),
            )

            if integrity_result.passed:
                await self._update_status(
                    job_id, MigrationJobStatus.READY_FOR_CUTOVER.value,
                )
            else:
                await self._fail_job(
                    job_id,
                    "Integrity check failed. Review the integrity report for details.",
                )
                await target_engine.dispose()
                return

            # Keep target engine alive for cutover
            logger.info("Migration job %s ready for cutover", job_id)

        except Exception as exc:
            logger.exception("Pipeline failed for job %s", job_id)
            await self._fail_job(job_id, f"Pipeline error: {exc}")

    # -- Pipeline helpers ----------------------------------------------------

    async def _run_alembic_on_target(self, target_url: str) -> None:
        """Run Alembic ``upgrade head`` against the target database."""
        from alembic import command
        from alembic.config import Config

        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", target_url.replace("+asyncpg", ""))

        # Run in a thread to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, command.upgrade, alembic_cfg, "head")

    async def _copy_all_tables(
        self,
        job_id: str,
        job: MigrationJob,
        target_engine: Any,
        dual_write: DualWriteProxy,
    ) -> None:
        """Copy data from all tables in dependency order."""
        import app.core.database as db_mod

        # Get table dependencies
        dependencies = await self._get_table_dependencies(db_mod.engine)
        table_order = get_table_dependency_order(dependencies)

        # Get total row counts
        total_rows = 0
        table_counts: dict[str, int] = {}
        for table in table_order:
            async with db_mod.engine.connect() as conn:
                result = await conn.execute(text(f"SELECT count(*) FROM {table}"))  # noqa: S608
                count = result.scalar_one()
                table_counts[table] = count
                total_rows += count

        # Update job totals
        job.rows_total = total_rows
        await self.db.flush()

        await self.redis.hset(
            f"{_PROGRESS_KEY_PREFIX}{job_id}",
            "rows_total",
            str(total_rows),
        )

        # Initialise table progress
        tables_progress: list[dict[str, Any]] = [
            {
                "table_name": t,
                "source_count": table_counts.get(t, 0),
                "migrated_count": 0,
                "status": "pending",
            }
            for t in table_order
        ]

        rows_copied = 0

        for idx, table in enumerate(table_order):
            if await self._is_cancelled(job_id):
                return

            tables_progress[idx]["status"] = "in_progress"
            await self._update_progress(
                job_id, table, rows_copied, total_rows, tables_progress, dual_write,
            )

            source_count = table_counts.get(table, 0)
            if source_count == 0:
                tables_progress[idx]["status"] = "completed"
                continue

            # Copy in batches with retry logic
            try:
                copied = await self._copy_table(
                    job_id, table, job.batch_size, db_mod.engine, target_engine,
                )
                rows_copied += copied
                tables_progress[idx]["migrated_count"] = copied
                tables_progress[idx]["status"] = "completed"
            except Exception as exc:
                logger.exception("Failed to copy table %s for job %s", table, job_id)
                tables_progress[idx]["status"] = "failed"
                raise

            await self._update_progress(
                job_id, table, rows_copied, total_rows, tables_progress, dual_write,
            )

    async def _copy_table(
        self,
        job_id: str,
        table: str,
        batch_size: int,
        source_engine: Any,
        target_engine: Any,
    ) -> int:
        """Copy a single table in batches with retry logic (3 retries, exponential backoff)."""
        offset = 0
        total_copied = 0

        while True:
            if await self._is_cancelled(job_id):
                return total_copied

            # Fetch batch from source
            async with source_engine.connect() as conn:
                result = await conn.execute(
                    text(f"SELECT * FROM {table} LIMIT {batch_size} OFFSET {offset}")  # noqa: S608
                )
                rows = result.fetchall()
                columns = list(result.keys())

            if not rows:
                break

            # Insert batch into target with retry
            retries = 3
            for attempt in range(retries):
                try:
                    async with target_engine.begin() as conn:
                        for row in rows:
                            values = dict(zip(columns, row))
                            placeholders = ", ".join(f":{col}" for col in columns)
                            col_names = ", ".join(columns)
                            await conn.execute(
                                text(
                                    f"INSERT INTO {table} ({col_names}) "  # noqa: S608
                                    f"VALUES ({placeholders})"
                                ),
                                values,
                            )
                    break  # Success
                except Exception:
                    if attempt < retries - 1:
                        backoff = 2 ** attempt  # 1s, 2s, 4s
                        logger.warning(
                            "Batch copy retry %d/%d for table %s (backoff %ds)",
                            attempt + 1, retries, table, backoff,
                        )
                        await asyncio.sleep(backoff)
                    else:
                        raise

            total_copied += len(rows)
            offset += batch_size

        return total_copied

    async def _get_table_dependencies(self, engine: Any) -> dict[str, list[str]]:
        """Query FK relationships to build a dependency graph."""
        query = text("""
            SELECT
                tc.table_name,
                ccu.table_name AS referenced_table
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_schema = 'public'
        """)

        # Get all tables
        tables_query = text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )

        async with engine.connect() as conn:
            tables_result = await conn.execute(tables_query)
            all_tables = [row[0] for row in tables_result.fetchall()]

            fk_result = await conn.execute(query)
            fk_rows = fk_result.fetchall()

        dependencies: dict[str, list[str]] = {t: [] for t in all_tables}
        for table_name, referenced_table in fk_rows:
            if table_name in dependencies and referenced_table != table_name:
                if referenced_table not in dependencies[table_name]:
                    dependencies[table_name].append(referenced_table)

        return dependencies

    async def _update_status(self, job_id: str, status: str) -> None:
        """Update job status in both the database and Redis."""
        job = (
            await self.db.execute(
                select(MigrationJob).where(MigrationJob.id == uuid.UUID(job_id))
            )
        ).scalar_one()
        job.status = status
        await self.db.flush()

        await self.redis.hset(
            f"{_PROGRESS_KEY_PREFIX}{job_id}",
            mapping={
                "status": status,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    async def _update_progress(
        self,
        job_id: str,
        current_table: str,
        rows_processed: int,
        rows_total: int,
        tables_progress: list[dict[str, Any]],
        dual_write: DualWriteProxy,
    ) -> None:
        """Update progress in both the database and Redis."""
        pct = calculate_progress_pct(rows_processed, rows_total)

        job = (
            await self.db.execute(
                select(MigrationJob).where(MigrationJob.id == uuid.UUID(job_id))
            )
        ).scalar_one()
        job.current_table = current_table
        job.rows_processed = rows_processed
        job.progress_pct = pct
        job.table_progress = tables_progress
        job.dual_write_queue_depth = dual_write.get_queue_depth()
        await self.db.flush()

        await self.redis.hset(
            f"{_PROGRESS_KEY_PREFIX}{job_id}",
            mapping={
                "current_table": current_table,
                "rows_processed": str(rows_processed),
                "rows_total": str(rows_total),
                "progress_pct": str(pct),
                "dual_write_queue_depth": str(dual_write.get_queue_depth()),
                "tables": json.dumps(tables_progress),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    async def _fail_job(self, job_id: str, error_message: str) -> None:
        """Mark a job as failed."""
        job = (
            await self.db.execute(
                select(MigrationJob).where(MigrationJob.id == uuid.UUID(job_id))
            )
        ).scalar_one()
        job.status = MigrationJobStatus.FAILED.value
        job.error_message = error_message
        job.completed_at = datetime.now(timezone.utc)
        # Clear encrypted connection string
        job.target_conn_encrypted = None
        await self.db.flush()

        await self.redis.hset(
            f"{_PROGRESS_KEY_PREFIX}{job_id}",
            mapping={
                "status": MigrationJobStatus.FAILED.value,
                "error_message": error_message,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        # Remove active job marker
        await self.redis.delete(_ACTIVE_JOB_KEY)

    async def _is_cancelled(self, job_id: str) -> bool:
        """Check if cancellation has been requested."""
        return bool(await self.redis.get(f"{_CANCEL_FLAG_PREFIX}{job_id}"))

    async def _handle_cancellation(self, job_id: str, target_engine: Any) -> None:
        """Handle cancellation: clean up target, update status."""
        try:
            # Drop all tables on target (clean up)
            async with target_engine.begin() as conn:
                await conn.execute(text(
                    "DO $$ DECLARE r RECORD; BEGIN "
                    "FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP "
                    "EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE'; "
                    "END LOOP; END $$;"
                ))
        except Exception:
            logger.exception("Failed to clean up target for job %s", job_id)

        await target_engine.dispose()

        job = (
            await self.db.execute(
                select(MigrationJob).where(MigrationJob.id == uuid.UUID(job_id))
            )
        ).scalar_one()
        job.status = MigrationJobStatus.CANCELLED.value
        job.cancelled_at = datetime.now(timezone.utc)
        job.target_conn_encrypted = None
        await self.db.flush()

        await self.redis.hset(
            f"{_PROGRESS_KEY_PREFIX}{job_id}",
            mapping={
                "status": MigrationJobStatus.CANCELLED.value,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        await self.redis.delete(_ACTIVE_JOB_KEY)
        await self.redis.delete(f"{_CANCEL_FLAG_PREFIX}{job_id}")


    # -- 8.3: get_status, cutover, rollback, cancel, history, detail ---------

    async def get_status(self, job_id: str) -> MigrationStatusResponse:
        """Read migration progress from Redis and return a status response."""
        progress_key = f"{_PROGRESS_KEY_PREFIX}{job_id}"
        data = await self.redis.hgetall(progress_key)

        if not data:
            # Fall back to database
            job = (
                await self.db.execute(
                    select(MigrationJob).where(MigrationJob.id == uuid.UUID(job_id))
                )
            ).scalar_one_or_none()
            if not job:
                raise ValueError(f"Migration job {job_id} not found")

            tables = [
                TableProgress(**t) for t in (job.table_progress or [])
            ]
            return MigrationStatusResponse(
                job_id=job_id,
                status=MigrationJobStatus(job.status),
                current_table=job.current_table,
                tables=tables,
                rows_processed=job.rows_processed,
                rows_total=job.rows_total,
                progress_pct=job.progress_pct,
                dual_write_queue_depth=job.dual_write_queue_depth,
                integrity_check=(
                    IntegrityCheckResult(**job.integrity_check)
                    if job.integrity_check
                    else None
                ),
                error_message=job.error_message,
                started_at=job.started_at.isoformat() if job.started_at else "",
                updated_at=job.updated_at.isoformat() if job.updated_at else "",
            )

        # Parse Redis data
        rows_processed = int(data.get("rows_processed", "0"))
        rows_total = int(data.get("rows_total", "0"))
        started_at = data.get("started_at", "")
        updated_at = data.get("updated_at", "")

        # Calculate ETA
        eta = None
        if rows_processed > 0 and started_at:
            try:
                start_dt = datetime.fromisoformat(started_at)
                elapsed = (datetime.now(timezone.utc) - start_dt).total_seconds()
                if elapsed > 0:
                    eta = calculate_eta(rows_processed, elapsed, rows_total)
            except (ValueError, TypeError):
                pass

        # Parse tables progress
        tables_json = data.get("tables", "[]")
        try:
            tables_raw = json.loads(tables_json)
            tables = [TableProgress(**t) for t in tables_raw]
        except (json.JSONDecodeError, TypeError):
            tables = []

        # Parse integrity check
        integrity_check = None
        ic_json = data.get("integrity_check")
        if ic_json:
            try:
                integrity_check = IntegrityCheckResult(**json.loads(ic_json))
            except (json.JSONDecodeError, TypeError):
                pass

        return MigrationStatusResponse(
            job_id=job_id,
            status=MigrationJobStatus(data.get("status", "pending")),
            current_table=data.get("current_table") or None,
            tables=tables,
            rows_processed=rows_processed,
            rows_total=rows_total,
            progress_pct=float(data.get("progress_pct", "0.0")),
            estimated_seconds_remaining=eta,
            dual_write_queue_depth=int(data.get("dual_write_queue_depth", "0")),
            integrity_check=integrity_check,
            error_message=data.get("error_message") or None,
            started_at=started_at,
            updated_at=updated_at,
        )

    async def cutover(self, job_id: str, user_id: UUID) -> None:
        """Execute cutover to the target database.

        Validates confirmation, checks job is ready_for_cutover, delegates
        to CutoverManager, sets rollback deadline, and logs audit event.
        """
        job = (
            await self.db.execute(
                select(MigrationJob).where(MigrationJob.id == uuid.UUID(job_id))
            )
        ).scalar_one_or_none()
        if not job:
            raise ValueError(f"Migration job {job_id} not found")

        if job.status != MigrationJobStatus.READY_FOR_CUTOVER.value:
            raise ValueError(
                f"Migration is not ready for cutover (current status: {job.status})"
            )

        # Check integrity passed
        if not job.integrity_check or not job.integrity_check.get("passed"):
            raise ValueError("Integrity check has not passed. Cutover is not allowed.")

        # Update status to cutting_over
        job.status = MigrationJobStatus.CUTTING_OVER.value
        await self.db.flush()

        await self.redis.hset(
            f"{_PROGRESS_KEY_PREFIX}{job_id}",
            mapping={
                "status": MigrationJobStatus.CUTTING_OVER.value,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        # Decrypt connection string and execute cutover
        conn_str = envelope_decrypt_str(job.target_conn_encrypted)
        target_engine = create_async_engine(conn_str, echo=False)

        cutover_mgr = CutoverManager()
        success = await cutover_mgr.execute_cutover(target_engine, conn_str)

        if success:
            now = datetime.now(timezone.utc)
            job.status = MigrationJobStatus.COMPLETED.value
            job.cutover_at = now
            job.rollback_deadline = now + timedelta(hours=24)
            job.completed_at = now
            job.target_conn_encrypted = None  # Clear encrypted conn
            await self.db.flush()

            await self.redis.hset(
                f"{_PROGRESS_KEY_PREFIX}{job_id}",
                mapping={
                    "status": MigrationJobStatus.COMPLETED.value,
                    "updated_at": now.isoformat(),
                },
            )
            await self.redis.delete(_ACTIVE_JOB_KEY)

            # Audit log
            await write_audit_log(
                self.db,
                action="migration.cutover",
                entity_type="migration_job",
                user_id=user_id,
                entity_id=uuid.UUID(job_id),
                after_value={
                    "source_host": job.source_host,
                    "source_db": job.source_db_name,
                    "target_host": job.target_host,
                    "target_db": job.target_db_name,
                    "cutover_at": now.isoformat(),
                },
            )
        else:
            job.status = MigrationJobStatus.FAILED.value
            job.error_message = "Cutover verification failed — auto-rolled back to source"
            job.completed_at = datetime.now(timezone.utc)
            job.target_conn_encrypted = None
            await self.db.flush()

            await self.redis.hset(
                f"{_PROGRESS_KEY_PREFIX}{job_id}",
                mapping={
                    "status": MigrationJobStatus.FAILED.value,
                    "error_message": job.error_message,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            await self.redis.delete(_ACTIVE_JOB_KEY)

            raise ValueError(job.error_message)

    async def rollback(self, job_id: str, user_id: UUID, reason: str) -> None:
        """Roll back to the source database.

        Checks within 24h window, delegates to CutoverManager, logs audit event.
        """
        job = (
            await self.db.execute(
                select(MigrationJob).where(MigrationJob.id == uuid.UUID(job_id))
            )
        ).scalar_one_or_none()
        if not job:
            raise ValueError(f"Migration job {job_id} not found")

        if job.status != MigrationJobStatus.COMPLETED.value:
            raise ValueError(
                f"Rollback is only available for completed migrations (current: {job.status})"
            )

        if not job.cutover_at:
            raise ValueError("No cutover timestamp found — cannot determine rollback window")

        now = datetime.now(timezone.utc)
        if not is_rollback_available(job.cutover_at, now):
            raise ValueError(
                f"Rollback window expired. Cutover was at {job.cutover_at.isoformat()}, "
                "24h deadline passed."
            )

        # Execute rollback
        source_url = settings.database_url
        cutover_mgr = CutoverManager()
        success = await cutover_mgr.execute_rollback(source_url)

        if success:
            job.status = MigrationJobStatus.ROLLED_BACK.value
            await self.db.flush()

            await self.redis.hset(
                f"{_PROGRESS_KEY_PREFIX}{job_id}",
                mapping={
                    "status": MigrationJobStatus.ROLLED_BACK.value,
                    "updated_at": now.isoformat(),
                },
            )

            # Audit log
            await write_audit_log(
                self.db,
                action="migration.rollback",
                entity_type="migration_job",
                user_id=user_id,
                entity_id=uuid.UUID(job_id),
                after_value={
                    "reason": reason,
                    "source_host": job.source_host,
                    "source_db": job.source_db_name,
                    "target_host": job.target_host,
                    "target_db": job.target_db_name,
                    "rolled_back_at": now.isoformat(),
                },
            )
        else:
            raise ValueError("Rollback failed — manual intervention required")

    async def cancel_migration(self, job_id: str, user_id: UUID) -> None:
        """Cancel an in-progress migration.

        Checks cancellable state, sets cancellation flag, and logs audit event.
        The background pipeline will detect the flag and clean up.
        """
        job = (
            await self.db.execute(
                select(MigrationJob).where(MigrationJob.id == uuid.UUID(job_id))
            )
        ).scalar_one_or_none()
        if not job:
            raise ValueError(f"Migration job {job_id} not found")

        if not is_cancellable_status(job.status):
            raise ValueError(
                f"Migration is not in a cancellable state (current: {job.status})"
            )

        # Set cancellation flag in Redis for the background task to detect
        await self.redis.set(f"{_CANCEL_FLAG_PREFIX}{job_id}", "1", ex=3600)

        # If the pipeline hasn't started the heavy work yet, cancel immediately
        job.status = MigrationJobStatus.CANCELLED.value
        job.cancelled_at = datetime.now(timezone.utc)
        job.target_conn_encrypted = None
        await self.db.flush()

        await self.redis.hset(
            f"{_PROGRESS_KEY_PREFIX}{job_id}",
            mapping={
                "status": MigrationJobStatus.CANCELLED.value,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        await self.redis.delete(_ACTIVE_JOB_KEY)

        # Audit log
        await write_audit_log(
            self.db,
            action="migration.cancelled",
            entity_type="migration_job",
            user_id=user_id,
            entity_id=uuid.UUID(job_id),
            after_value={
                "cancelled_at": job.cancelled_at.isoformat(),
                "previous_status": job.status,
            },
        )

    async def get_history(self) -> list[MigrationJobSummary]:
        """Query all migration job records, returning summaries with masked passwords."""
        result = await self.db.execute(
            select(MigrationJob).order_by(MigrationJob.created_at.desc())
        )
        jobs = result.scalars().all()

        return [
            MigrationJobSummary(
                job_id=str(j.id),
                status=j.status,
                started_at=j.started_at.isoformat() if j.started_at else "",
                completed_at=j.completed_at.isoformat() if j.completed_at else None,
                rows_total=j.rows_total,
                source_host=j.source_host,
                target_host=j.target_host,
            )
            for j in jobs
        ]

    async def get_job_detail(self, job_id: str) -> MigrationJobDetail:
        """Query a single migration job with full details."""
        job = (
            await self.db.execute(
                select(MigrationJob).where(MigrationJob.id == uuid.UUID(job_id))
            )
        ).scalar_one_or_none()
        if not job:
            raise ValueError(f"Migration job {job_id} not found")

        tables = [
            TableProgress(**t) for t in (job.table_progress or [])
        ]

        integrity = None
        if job.integrity_check:
            integrity = IntegrityCheckResult(**job.integrity_check)

        return MigrationJobDetail(
            job_id=str(job.id),
            status=job.status,
            started_at=job.started_at.isoformat() if job.started_at else "",
            completed_at=job.completed_at.isoformat() if job.completed_at else None,
            rows_total=job.rows_total,
            source_host=job.source_host,
            target_host=job.target_host,
            integrity_check=integrity,
            error_message=job.error_message,
            tables=tables,
        )
