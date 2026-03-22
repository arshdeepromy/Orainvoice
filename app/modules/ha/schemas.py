"""Pydantic request/response schemas for the HA Replication feature.

Requirements: 1.1, 1.5, 2.1, 4.1, 4.3, 7.1, 8.4
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class HAConfigRequest(BaseModel):
    """Request body for PUT /api/v1/ha/configure."""

    node_name: str = Field(description="Human-readable name (e.g. 'Pi-Main')")
    role: str = Field(description="'primary' or 'standby'")
    peer_endpoint: str = Field(
        description="URL of peer node API (e.g. 'http://192.168.x.x:8999')",
    )
    auto_promote_enabled: bool = Field(default=False)
    heartbeat_interval_seconds: int = Field(default=10)
    failover_timeout_seconds: int = Field(default=90)

    # Peer database connection (optional — falls back to HA_PEER_DB_URL env var)
    peer_db_host: str | None = Field(default=None, description="Peer PostgreSQL host")
    peer_db_port: int | None = Field(default=5432, description="Peer PostgreSQL port")
    peer_db_name: str | None = Field(default=None, description="Peer database name")
    peer_db_user: str | None = Field(default=None, description="Peer database user")
    peer_db_password: str | None = Field(default=None, description="Peer database password (stored encrypted)")
    peer_db_sslmode: str | None = Field(default="disable", description="SSL mode: disable, require, verify-ca, verify-full")


class HAConfigResponse(BaseModel):
    """Response for GET /api/v1/ha/identity and PUT /api/v1/ha/configure."""

    model_config = ConfigDict(from_attributes=True)

    node_id: str
    node_name: str
    role: str
    peer_endpoint: str
    auto_promote_enabled: bool
    heartbeat_interval_seconds: int
    failover_timeout_seconds: int
    created_at: datetime
    updated_at: datetime

    # Peer database connection (password never returned — only a configured flag)
    peer_db_host: str | None = None
    peer_db_port: int | None = None
    peer_db_name: str | None = None
    peer_db_user: str | None = None
    peer_db_configured: bool = Field(default=False, description="True when peer DB credentials are stored")
    peer_db_sslmode: str | None = Field(default="disable", description="SSL mode for peer DB connection")


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


class HeartbeatResponse(BaseModel):
    """Response for GET /api/v1/ha/heartbeat — peer health check."""

    node_id: str
    node_name: str
    role: str
    status: str = Field(description="'healthy'")
    database_status: str = Field(description="'connected' | 'error'")
    replication_lag_seconds: float | None = Field(
        default=None, description="Only populated on standby nodes",
    )
    sync_status: str = Field(
        description="'healthy' | 'lagging' | 'disconnected' | 'resyncing' | 'not_configured'",
    )
    uptime_seconds: float
    maintenance: bool
    timestamp: str = Field(description="ISO 8601 timestamp")
    hmac_signature: str = Field(description="HMAC-SHA256 of payload")


class HeartbeatHistoryEntry(BaseModel):
    """Single entry in the heartbeat history ring buffer."""

    timestamp: str
    peer_status: str
    replication_lag_seconds: float | None = None
    response_time_ms: float | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Public status (login page indicator)
# ---------------------------------------------------------------------------


class PublicStatusResponse(BaseModel):
    """Response for GET /api/v1/ha/status — lightweight, no sensitive data.

    Requirements: 8.4, 11.3
    """

    node_name: str
    role: str
    peer_status: str = Field(
        description="'healthy' | 'degraded' | 'unreachable' | 'unknown'",
    )
    sync_status: str


# ---------------------------------------------------------------------------
# Promote / Demote
# ---------------------------------------------------------------------------


class PromoteRequest(BaseModel):
    """Request body for POST /api/v1/ha/promote."""

    confirmation_text: str = Field(description="Must be exactly 'CONFIRM'")
    reason: str
    force: bool = Field(
        default=False,
        description="Required when replication lag > 5 s",
    )


class DemoteRequest(BaseModel):
    """Request body for POST /api/v1/ha/demote."""

    confirmation_text: str = Field(description="Must be exactly 'CONFIRM'")
    reason: str


# ---------------------------------------------------------------------------
# Replication
# ---------------------------------------------------------------------------


class ReplicationStatusResponse(BaseModel):
    """Response for GET /api/v1/ha/replication/status."""

    publication_name: str | None = None
    subscription_name: str | None = None
    subscription_status: str | None = Field(
        default=None, description="'active' | 'disabled' | 'error' | None",
    )
    replication_lag_seconds: float | None = None
    last_replicated_at: str | None = None
    tables_published: int
    is_healthy: bool


class ResyncProgressResponse(BaseModel):
    """Response for re-sync progress tracking."""

    status: str = Field(description="'idle' | 'in_progress' | 'completed' | 'error'")
    tables_synced: int
    tables_total: int
    rows_copied: int
    estimated_seconds_remaining: int | None = None
    started_at: str | None = None
    error_message: str | None = None


class PeerDBTestRequest(BaseModel):
    """Request body for POST /api/v1/ha/test-db-connection."""

    host: str = Field(description="PostgreSQL host")
    port: int = Field(default=5432, description="PostgreSQL port")
    dbname: str = Field(description="Database name")
    user: str = Field(description="Database user")
    password: str = Field(description="Database password")
    sslmode: str = Field(default="disable", description="SSL mode: disable, require, verify-ca, verify-full")


class CreateReplicationUserRequest(BaseModel):
    """Request body for POST /api/v1/ha/create-replication-user."""

    username: str = Field(default="replicator", description="Replication user name")
    password: str = Field(description="Password for the replication user")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


class HANodeStatusForDashboard(BaseModel):
    """Per-node status row shown in the admin HA Status Panel.

    Requirements: 7.1
    """

    node_name: str
    role: str
    health: str = Field(description="'healthy' | 'degraded' | 'unreachable'")
    sync_status: str
    replication_lag_seconds: float | None = None
    last_heartbeat: str | None = None
    maintenance: bool
    is_local: bool = Field(description="True for the node the admin is connected to")
