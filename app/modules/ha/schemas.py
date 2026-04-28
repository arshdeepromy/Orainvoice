"""Pydantic request/response schemas for the HA Replication feature.

Requirements: 1.1, 1.5, 2.1, 4.1, 4.3, 5.1, 6.1, 7.1, 8.1, 8.4, 10.1, 34.6
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

    # Heartbeat HMAC secret (optional — falls back to HA_HEARTBEAT_SECRET env var)
    heartbeat_secret: str | None = Field(default=None, description="HMAC shared secret for heartbeat signing (stored encrypted)")

    # Local connection info overrides
    local_lan_ip: str | None = Field(default=None, description="Local LAN IP override for View Connection Info (auto-detected if blank)")
    local_pg_port: int | None = Field(default=None, description="Local PostgreSQL host port override (defaults to 5432 if blank)")


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
    heartbeat_secret_configured: bool = Field(default=False, description="True when heartbeat HMAC secret is stored in DB")
    local_lan_ip: str | None = None
    local_pg_port: int | None = None
    promoted_at: datetime | None = None


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
    app_version: str | None = Field(default=None, description="Application version from GIT_SHA or BUILD_DATE")
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


class ReplicationSlot(BaseModel):
    """A single replication slot from pg_replication_slots."""

    slot_name: str
    slot_type: str
    active: bool
    retained_wal: str | None = None
    active_pid: int | None = None
    idle_seconds: float | None = None


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
# Failover / Split-Brain
# ---------------------------------------------------------------------------


class FailoverStatusResponse(BaseModel):
    """Response for GET /api/v1/ha/failover-status.

    Requirements: 5.5, 12.1, 12.2
    """

    auto_promote_enabled: bool
    peer_unreachable_seconds: float | None = None
    failover_timeout_seconds: int
    seconds_until_auto_promote: float | None = None
    split_brain_detected: bool = False
    is_stale_primary: bool = False
    promoted_at: str | None = None  # ISO 8601
    peer_role: str = Field(default="unknown", description="Actual peer role from heartbeat responses")


class DemoteAndSyncRequest(BaseModel):
    """Request body for POST /api/v1/ha/demote-and-sync.

    Requirements: 7.3, 7.4
    """

    confirmation_text: str = Field(description="Must be exactly 'CONFIRM'")
    reason: str


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


# ---------------------------------------------------------------------------
# Wizard — Setup Flow
# ---------------------------------------------------------------------------


class WizardCheckReachabilityRequest(BaseModel):
    """Request body for POST /api/v1/ha/wizard/check-reachability.

    Requirements: 4.1, 5.1
    """

    address: str


class WizardCheckReachabilityResponse(BaseModel):
    """Response for POST /api/v1/ha/wizard/check-reachability.

    Requirements: 5.1, 5.2, 5.3, 5.4, 37.1, 37.2, 37.3
    """

    reachable: bool
    node_name: str | None = None
    role: str | None = None
    is_orainvoice: bool = False
    error: str | None = None
    version_warning: str | None = None


class WizardAuthenticateRequest(BaseModel):
    """Request body for POST /api/v1/ha/wizard/authenticate.

    Requirements: 6.1
    """

    address: str
    email: str
    password: str


class WizardAuthenticateResponse(BaseModel):
    """Response for POST /api/v1/ha/wizard/authenticate.

    Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
    """

    authenticated: bool
    is_global_admin: bool = False
    token: str | None = None
    error: str | None = None


class WizardHandshakeRequest(BaseModel):
    """Request body for POST /api/v1/ha/wizard/handshake.

    Requirements: 7.1
    """

    address: str
    standby_token: str


class WizardHandshakeResponse(BaseModel):
    """Response for POST /api/v1/ha/wizard/handshake.

    Requirements: 7.1, 7.8, 7.9
    """

    success: bool
    primary_ip: str | None = None
    primary_pg_port: int | None = None
    standby_ip: str | None = None
    standby_pg_port: int | None = None
    hmac_secret_set: bool = False
    error: str | None = None


class WizardReceiveHandshakeRequest(BaseModel):
    """Request body for POST /api/v1/ha/wizard/receive-handshake.

    Requirements: 10.1, 10.2, 10.3
    """

    ssh_pub_key: str
    lan_ip: str
    pg_port: int = 5432
    hmac_secret: str


class WizardReceiveHandshakeResponse(BaseModel):
    """Response for POST /api/v1/ha/wizard/receive-handshake.

    Requirements: 10.1, 10.2
    """

    ssh_pub_key: str
    lan_ip: str
    pg_port: int


class WizardSetupRequest(BaseModel):
    """Request body for POST /api/v1/ha/wizard/setup.

    Requirements: 8.1
    """

    address: str
    standby_token: str


class WizardSetupStepResult(BaseModel):
    """A single step result in the automated setup sequence.

    Requirements: 8.6, 8.7, 8.8
    """

    step: str
    status: str = Field(description="'completed' | 'failed' | 'skipped'")
    message: str | None = None
    error: str | None = None


class WizardSetupResponse(BaseModel):
    """Response for POST /api/v1/ha/wizard/setup.

    Requirements: 8.1, 8.7, 8.8
    """

    success: bool
    steps: list[WizardSetupStepResult] = []
    error: str | None = None


# ---------------------------------------------------------------------------
# HA Event Log
# ---------------------------------------------------------------------------


class HAEventResponse(BaseModel):
    """A single HA event log entry.

    Requirements: 34.6
    """

    id: str
    timestamp: str
    event_type: str
    severity: str
    message: str
    details: dict | None = None
    node_name: str


class HAEventListResponse(BaseModel):
    """Response for GET /api/v1/ha/events.

    Requirements: 34.6, 34.7
    """

    events: list[HAEventResponse] = []
    total: int = 0
