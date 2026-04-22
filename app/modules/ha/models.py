"""SQLAlchemy ORM models for the HA Replication feature.

Stores per-node HA configuration: identity, role, peer info, heartbeat
state, and replication sync status.  Each node maintains its own row —
this table is NOT replicated between nodes.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    LargeBinary,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class HAConfig(Base):
    """Persistent HA configuration for the local node."""

    __tablename__ = "ha_config"
    __table_args__ = (
        CheckConstraint(
            "role IN ('standalone', 'primary', 'standby')",
            name="ck_ha_config_role",
        ),
        CheckConstraint(
            "sync_status IN ("
            "'not_configured', 'initializing', 'healthy', "
            "'lagging', 'disconnected', 'resyncing', 'error'"
            ")",
            name="ck_ha_config_sync",
        ),
    )

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )

    # Node identity
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4,
    )
    node_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Role management
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="standalone",
    )

    # Peer configuration
    peer_endpoint: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Peer database connection (node-local, not replicated)
    peer_db_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    peer_db_port: Mapped[int | None] = mapped_column(Integer, nullable=True, default=5432)
    peer_db_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    peer_db_user: Mapped[str | None] = mapped_column(String(100), nullable=True)
    peer_db_password: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    peer_db_sslmode: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default="disable",
    )

    # Heartbeat HMAC shared secret (encrypted at rest, replaces env var)
    heartbeat_secret: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True,
    )

    # Failover settings
    auto_promote_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    heartbeat_interval_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10,
    )
    failover_timeout_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=90,
    )

    # Maintenance
    maintenance_mode: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )

    # Peer health tracking
    last_peer_health: Mapped[str | None] = mapped_column(
        String(20), default="unknown",
    )
    last_peer_heartbeat: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Promotion tracking (split-brain resolution)
    promoted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
    )

    # Replication state
    sync_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="not_configured",
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(),
    )
