"""SQLAlchemy ORM models for the live database migration feature.

This module is separate from the existing ``models.py`` (which covers
V1 org data migration and other global tables).  The table is named
``live_migration_jobs`` to avoid conflicts with any existing
``migration_jobs`` table used by the V1 data-migration tool.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


# ---------------------------------------------------------------------------
# Enum
# ---------------------------------------------------------------------------

class MigrationJobStatus(str, Enum):
    """All possible states for a live database migration job."""

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


# ---------------------------------------------------------------------------
# ORM Model
# ---------------------------------------------------------------------------

class MigrationJob(Base):
    """Persistent record tracking a single live database migration attempt."""

    __tablename__ = "live_migration_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'pending', 'validating', 'schema_migrating', 'copying_data', "
            "'draining_queue', 'integrity_check', 'ready_for_cutover', "
            "'cutting_over', 'completed', 'failed', 'cancelled', 'rolled_back'"
            ")",
            name="ck_live_migration_job_status",
        ),
        Index("idx_live_migration_jobs_status", "status"),
        Index("idx_live_migration_jobs_created", "created_at", postgresql_using="btree"),
    )

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )

    # Status
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")

    # Source connection info (passwords NEVER stored)
    source_host: Mapped[str] = mapped_column(String(255), nullable=False)
    source_port: Mapped[int] = mapped_column(Integer, nullable=False)
    source_db_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Target connection info (passwords NEVER stored)
    target_host: Mapped[str] = mapped_column(String(255), nullable=False)
    target_port: Mapped[int] = mapped_column(Integer, nullable=False)
    target_db_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # SSL
    ssl_mode: Mapped[str] = mapped_column(String(10), nullable=False, default="prefer")

    # Encrypted connection string for active use (cleared after completion)
    target_conn_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True,
    )

    # Progress tracking
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    current_table: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rows_processed: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    rows_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    progress_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    table_progress: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="'[]'",
    )
    dual_write_queue_depth: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )

    # Integrity check results
    integrity_check: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Error tracking
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    cutover_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    rollback_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(),
    )

    # Who initiated
    initiated_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False,
    )
