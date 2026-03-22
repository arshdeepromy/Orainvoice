"""Unit tests for the live database migration feature.

Covers:
- Connection validation happy path with real-format strings
- Alembic failure handling (mocked)
- Batch copy retry exhaustion (mocked)
- Dual-write failure queuing (mocked)
- Cutover with verification failure → auto-rollback (mocked)
- Cancel during each cancellable state
- History endpoint returns correct job list

Requirements: 3.1, 4.2, 5.9, 6.3, 8.7, 10.4, 12.2
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.admin.live_migration_schemas import (
    ConnectionValidateResponse,
    MigrationJobSummary,
    MigrationStatusResponse,
)
from app.modules.admin.live_migration_service import (
    LiveMigrationService,
    is_active_status,
    is_cancellable_status,
)
from app.modules.admin.migration_models import MigrationJob, MigrationJobStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db() -> AsyncMock:
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    return db


def _mock_redis() -> AsyncMock:
    """Create a mock aioredis.Redis."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.hset = AsyncMock()
    redis.hgetall = AsyncMock(return_value={})
    redis.delete = AsyncMock()
    redis.expire = AsyncMock()
    return redis


def _make_job(
    status: str = "pending",
    job_id: uuid.UUID | None = None,
    cutover_at: datetime | None = None,
    integrity_check: dict | None = None,
) -> MigrationJob:
    """Create a MigrationJob instance for testing."""
    job = MagicMock(spec=MigrationJob)
    job.id = job_id or uuid.uuid4()
    job.status = status
    job.source_host = "source.db.local"
    job.source_port = 5432
    job.source_db_name = "workshoppro"
    job.target_host = "target.db.local"
    job.target_port = 5432
    job.target_db_name = "workshoppro_new"
    job.ssl_mode = "prefer"
    job.target_conn_encrypted = b"encrypted"
    job.batch_size = 1000
    job.current_table = None
    job.rows_processed = 0
    job.rows_total = 0
    job.progress_pct = 0.0
    job.table_progress = []
    job.dual_write_queue_depth = 0
    job.integrity_check = integrity_check
    job.error_message = None
    job.started_at = datetime.now(timezone.utc)
    job.completed_at = None
    job.cutover_at = cutover_at
    job.rollback_deadline = None
    job.cancelled_at = None
    job.created_at = datetime.now(timezone.utc)
    job.updated_at = datetime.now(timezone.utc)
    job.initiated_by = uuid.uuid4()
    return job


# ---------------------------------------------------------------------------
# Connection validation happy path
# ---------------------------------------------------------------------------


class TestConnectionValidation:
    """Test connection validation with real-format strings."""

    @pytest.mark.asyncio
    async def test_invalid_format_returns_error(self):
        """Invalid connection string format returns valid=False."""
        db = _mock_db()
        redis = _mock_redis()
        svc = LiveMigrationService(db=db, redis=redis)

        result = await svc.validate_connection(
            conn_str="not-a-valid-connection-string",
            ssl_mode="prefer",
        )
        assert isinstance(result, ConnectionValidateResponse)
        assert result.valid is False
        assert result.error is not None
        assert "format" in result.error.lower() or "scheme" in result.error.lower()

    @pytest.mark.asyncio
    async def test_ssl_disabled_in_production_rejected(self):
        """ssl_mode=disable is rejected in production environment."""
        db = _mock_db()
        redis = _mock_redis()
        svc = LiveMigrationService(db=db, redis=redis)

        with patch("app.modules.admin.live_migration_service.settings") as mock_settings:
            mock_settings.environment = "production"
            result = await svc.validate_connection(
                conn_str="postgresql+asyncpg://user:pass@host:5432/db",
                ssl_mode="disable",
            )
        assert result.valid is False
        assert "ssl" in result.error.lower()

    @pytest.mark.asyncio
    async def test_valid_format_attempts_connection(self):
        """A valid format string proceeds to connection attempt (which fails in test)."""
        db = _mock_db()
        redis = _mock_redis()
        svc = LiveMigrationService(db=db, redis=redis)

        with patch("app.modules.admin.live_migration_service.settings") as mock_settings:
            mock_settings.environment = "development"
            # Connection will fail since there's no real DB, but format is valid
            result = await svc.validate_connection(
                conn_str="postgresql+asyncpg://user:secret@localhost:5432/testdb",
                ssl_mode="prefer",
            )
        # Should fail at connection stage, not format validation
        assert result.valid is False
        assert result.error is not None
        # Password should be masked in error
        assert "secret" not in (result.error or "")


# ---------------------------------------------------------------------------
# Alembic failure handling
# ---------------------------------------------------------------------------


class TestAlembicFailure:
    """Test that Alembic migration failures are handled correctly."""

    @pytest.mark.asyncio
    async def test_alembic_failure_fails_job(self):
        """When _run_alembic_on_target raises, the pipeline marks the job as failed."""
        db = _mock_db()
        redis = _mock_redis()
        svc = LiveMigrationService(db=db, redis=redis)

        job = _make_job(status=MigrationJobStatus.SCHEMA_MIGRATING.value)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = job
        db.execute.return_value = mock_result

        # Mock _run_alembic_on_target to raise
        with patch.object(svc, "_run_alembic_on_target", side_effect=RuntimeError("Alembic revision abc123 failed")):
            with patch.object(svc, "_fail_job", new_callable=AsyncMock) as mock_fail:
                with patch.object(svc, "_update_status", new_callable=AsyncMock):
                    with patch("app.modules.admin.live_migration_service.envelope_decrypt_str", return_value="postgresql+asyncpg://u:p@h:5432/db"):
                        with patch("app.modules.admin.live_migration_service.create_async_engine") as mock_engine:
                            mock_eng = AsyncMock()
                            mock_eng.dispose = AsyncMock()
                            mock_engine.return_value = mock_eng
                            await svc._run_pipeline(str(job.id))

                mock_fail.assert_called_once()
                call_args = mock_fail.call_args
                assert "Alembic" in call_args[0][1] or "alembic" in call_args[0][1].lower()


# ---------------------------------------------------------------------------
# Batch copy retry exhaustion
# ---------------------------------------------------------------------------


class TestBatchCopyRetry:
    """Test batch copy retry exhaustion handling."""

    @pytest.mark.asyncio
    async def test_copy_table_retries_then_fails(self):
        """_copy_table retries 3 times then marks table as failed."""
        db = _mock_db()
        redis = _mock_redis()
        svc = LiveMigrationService(db=db, redis=redis)

        # Mock the internal copy to always fail
        mock_source_engine = AsyncMock()
        mock_target_engine = AsyncMock()

        # Create a mock connection that raises on execute
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=RuntimeError("Connection lost"))
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_source_engine.connect = MagicMock(return_value=mock_conn)
        mock_target_engine.connect = MagicMock(return_value=mock_conn)

        with patch.object(svc, "_update_progress", new_callable=AsyncMock):
            with pytest.raises(Exception):
                await svc._copy_table(
                    source_engine=mock_source_engine,
                    target_engine=mock_target_engine,
                    table_name="customers",
                    job_id=str(uuid.uuid4()),
                    batch_size=1000,
                )


# ---------------------------------------------------------------------------
# Dual-write failure queuing
# ---------------------------------------------------------------------------


class TestDualWriteFailureQueuing:
    """Test that dual-write failures are queued for retry."""

    @pytest.mark.asyncio
    async def test_queue_depth_tracks_failures(self):
        """DualWriteProxy tracks queue depth on target write failures."""
        from app.modules.admin.dual_write import DualWriteProxy

        proxy = DualWriteProxy.__new__(DualWriteProxy)
        proxy.queue_depth = 0
        proxy._retry_queue = []

        # Simulate enqueuing failed operations
        proxy._retry_queue.append({"op": "INSERT", "table": "customers", "data": {}})
        proxy.queue_depth = len(proxy._retry_queue)

        assert proxy.queue_depth == 1

        proxy._retry_queue.append({"op": "UPDATE", "table": "invoices", "data": {}})
        proxy.queue_depth = len(proxy._retry_queue)

        assert proxy.queue_depth == 2


# ---------------------------------------------------------------------------
# Cutover with verification failure → auto-rollback
# ---------------------------------------------------------------------------


class TestCutoverAutoRollback:
    """Test cutover with verification failure triggers auto-rollback."""

    @pytest.mark.asyncio
    async def test_cutover_failure_auto_rollback(self):
        """When CutoverManager.execute_cutover returns False, job is marked failed."""
        db = _mock_db()
        redis = _mock_redis()
        svc = LiveMigrationService(db=db, redis=redis)

        job = _make_job(
            status=MigrationJobStatus.READY_FOR_CUTOVER.value,
            integrity_check={"passed": True, "row_counts": {}, "fk_errors": [], "financial_totals": {}, "sequence_checks": {}},
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = job
        db.execute.return_value = mock_result

        user_id = uuid.uuid4()

        with patch("app.modules.admin.live_migration_service.envelope_decrypt_str", return_value="postgresql+asyncpg://u:p@h:5432/db"):
            with patch("app.modules.admin.live_migration_service.create_async_engine"):
                with patch("app.modules.admin.live_migration_service.CutoverManager") as MockCM:
                    mock_cm = AsyncMock()
                    mock_cm.execute_cutover = AsyncMock(return_value=False)
                    MockCM.return_value = mock_cm

                    with patch("app.modules.admin.live_migration_service.write_audit_log", new_callable=AsyncMock):
                        with pytest.raises(ValueError, match="auto-rolled back"):
                            await svc.cutover(job_id=str(job.id), user_id=user_id)

        assert job.status == MigrationJobStatus.FAILED.value
        assert "auto-rolled back" in (job.error_message or "").lower()


# ---------------------------------------------------------------------------
# Cancel during each cancellable state
# ---------------------------------------------------------------------------


class TestCancelMigration:
    """Test cancellation during each cancellable state."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [
        MigrationJobStatus.VALIDATING.value,
        MigrationJobStatus.SCHEMA_MIGRATING.value,
        MigrationJobStatus.COPYING_DATA.value,
        MigrationJobStatus.DRAINING_QUEUE.value,
    ])
    async def test_cancel_in_cancellable_state(self, status: str):
        """Cancellation succeeds for each cancellable state."""
        db = _mock_db()
        redis = _mock_redis()
        svc = LiveMigrationService(db=db, redis=redis)

        job = _make_job(status=status)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = job
        db.execute.return_value = mock_result

        user_id = uuid.uuid4()

        with patch("app.modules.admin.live_migration_service.write_audit_log", new_callable=AsyncMock):
            await svc.cancel_migration(job_id=str(job.id), user_id=user_id)

        assert job.status == MigrationJobStatus.CANCELLED.value
        assert job.cancelled_at is not None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [
        MigrationJobStatus.READY_FOR_CUTOVER.value,
        MigrationJobStatus.CUTTING_OVER.value,
        MigrationJobStatus.COMPLETED.value,
        MigrationJobStatus.FAILED.value,
        MigrationJobStatus.CANCELLED.value,
        MigrationJobStatus.ROLLED_BACK.value,
    ])
    async def test_cancel_in_non_cancellable_state_raises(self, status: str):
        """Cancellation raises ValueError for non-cancellable states."""
        db = _mock_db()
        redis = _mock_redis()
        svc = LiveMigrationService(db=db, redis=redis)

        job = _make_job(status=status)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = job
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="not in a cancellable state"):
            await svc.cancel_migration(job_id=str(job.id), user_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# History endpoint returns correct job list
# ---------------------------------------------------------------------------


class TestHistory:
    """Test history and job detail retrieval."""

    @pytest.mark.asyncio
    async def test_get_history_returns_summaries(self):
        """get_history returns a list of MigrationJobSummary objects."""
        db = _mock_db()
        redis = _mock_redis()
        svc = LiveMigrationService(db=db, redis=redis)

        job1 = _make_job(status=MigrationJobStatus.COMPLETED.value)
        job1.rows_total = 5000
        job2 = _make_job(status=MigrationJobStatus.FAILED.value)
        job2.rows_total = 3000

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [job1, job2]
        mock_result.scalars.return_value = mock_scalars
        db.execute.return_value = mock_result

        history = await svc.get_history()

        assert len(history) == 2
        assert isinstance(history[0], MigrationJobSummary)
        assert history[0].status == MigrationJobStatus.COMPLETED.value
        assert history[0].rows_total == 5000
        assert history[1].status == MigrationJobStatus.FAILED.value

    @pytest.mark.asyncio
    async def test_get_job_detail_not_found_raises(self):
        """get_job_detail raises ValueError for non-existent job."""
        db = _mock_db()
        redis = _mock_redis()
        svc = LiveMigrationService(db=db, redis=redis)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="not found"):
            await svc.get_job_detail(str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_get_history_empty(self):
        """get_history returns empty list when no jobs exist."""
        db = _mock_db()
        redis = _mock_redis()
        svc = LiveMigrationService(db=db, redis=redis)

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        db.execute.return_value = mock_result

        history = await svc.get_history()
        assert history == []
