"""Pydantic schemas for the Accounting integration module.

Requirements: 68.1, 68.2, 68.3, 68.4, 68.5, 68.6
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

VALID_PROVIDERS = ("xero", "myob")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class AccountingConnectionResponse(BaseModel):
    """Single accounting connection in API responses."""

    id: str = Field(..., description="Connection UUID")
    org_id: str = Field(..., description="Organisation UUID")
    provider: str = Field(..., description="Provider: xero or myob")
    is_connected: bool = Field(..., description="Whether the connection is active")
    last_sync_at: Optional[str] = Field(None, description="ISO 8601 last sync timestamp")
    created_at: str = Field(..., description="ISO 8601 creation timestamp")


class AccountingConnectionListResponse(BaseModel):
    """GET /connections response."""

    connections: list[AccountingConnectionResponse] = Field(
        default_factory=list, description="Connected accounting integrations"
    )
    total: int = Field(0, description="Total count")


class OAuthRedirectResponse(BaseModel):
    """Response containing the OAuth authorization URL."""

    authorization_url: str = Field(..., description="URL to redirect the user to")


class SyncLogEntry(BaseModel):
    """Single sync log entry."""

    id: str = Field(..., description="Log entry UUID")
    provider: str = Field(..., description="Provider: xero or myob")
    entity_type: str = Field(..., description="Entity type: invoice, payment, credit_note")
    entity_id: str = Field(..., description="Entity UUID")
    external_id: Optional[str] = Field(None, description="External ID in accounting software")
    status: str = Field(..., description="Sync status: synced, failed, pending")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    created_at: str = Field(..., description="ISO 8601 timestamp")


class SyncLogListResponse(BaseModel):
    """GET /sync-log response."""

    entries: list[SyncLogEntry] = Field(
        default_factory=list, description="Sync log entries"
    )
    total: int = Field(0, description="Total count")


class SyncStatusResponse(BaseModel):
    """Response after triggering a manual sync."""

    provider: str = Field(..., description="Provider synced")
    synced: int = Field(0, description="Number of entities successfully synced")
    failed: int = Field(0, description="Number of entities that failed to sync")
    message: str = Field("", description="Summary message")


# ---------------------------------------------------------------------------
# Dashboard view (consolidated response for frontend)
# ---------------------------------------------------------------------------


class AccountingConnectionDetail(BaseModel):
    """Detailed connection info for dashboard view."""

    provider: str = Field(..., description="Provider: xero or myob")
    connected: bool = Field(False, description="Whether connected")
    account_name: Optional[str] = Field(None, description="Connected account name")
    connected_at: Optional[str] = Field(None, description="ISO 8601 connection timestamp")
    last_sync_at: Optional[str] = Field(None, description="ISO 8601 last sync timestamp")
    sync_status: str = Field("idle", description="Sync status: idle, syncing, success, failed")
    error_message: Optional[str] = Field(None, description="Last error message if any")


class SyncLogEntryDashboard(BaseModel):
    """Sync log entry for dashboard view."""

    id: str
    provider: str
    entity_type: str
    entity_id: str
    entity_ref: str = Field(..., description="Human-readable reference (invoice number, etc)")
    status: str = Field(..., description="success or failed")
    error_message: Optional[str] = None
    synced_at: str = Field(..., description="ISO 8601 timestamp")


class AccountingDashboardResponse(BaseModel):
    """GET / response - consolidated view for frontend dashboard."""

    xero: AccountingConnectionDetail
    myob: AccountingConnectionDetail
    sync_log: list[SyncLogEntryDashboard] = Field(default_factory=list)
