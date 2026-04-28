"""SQLAlchemy ORM models for the Volume Sync feature.

Stores rsync-based volume replication configuration and sync history
for HA deployments.  The primary node periodically rsyncs Docker volume
data (uploads, compliance files) to the standby node over SSH.

**Validates: Requirements 4.1, 9.1, 9.2**
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class VolumeSyncConfig(Base):
    """Singleton-style rsync configuration for volume replication.

    Only one row should exist.  Stores SSH connection details, remote
    paths, sync interval, and an enabled flag.
    """

    __tablename__ = "volume_sync_config"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )

    # SSH connection details
    standby_ssh_host: Mapped[str] = mapped_column(
        String(255), nullable=False,
    )
    ssh_port: Mapped[int] = mapped_column(
        Integer, nullable=False, default=22,
    )
    ssh_key_path: Mapped[str] = mapped_column(
        String(500), nullable=False,
    )

    # Remote destination paths
    remote_upload_path: Mapped[str] = mapped_column(
        String(500), nullable=False, default="/app/uploads/",
    )
    remote_compliance_path: Mapped[str] = mapped_column(
        String(500), nullable=False, default="/app/compliance_files/",
    )

    # Sync schedule
    sync_interval_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5,
    )

    # Enable/disable toggle
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(),
    )


class VolumeSyncHistory(Base):
    """Log entry for each rsync execution (automatic or manual).

    Records timing, status, transfer stats, and any error message.
    """

    __tablename__ = "volume_sync_history"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )

    # Timing
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Status: 'running', 'success', 'failure'
    status: Mapped[str] = mapped_column(
        String(20), nullable=False,
    )

    # Transfer statistics
    files_transferred: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    bytes_transferred: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0,
    )

    # Error details (only populated on failure)
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )

    # Sync trigger type: 'automatic' or 'manual'
    sync_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
    )
