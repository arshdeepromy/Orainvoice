"""Pydantic request/response schemas for the Volume Sync feature.

Validates: Requirements 4.1, 4.2, 6.1, 6.2
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class VolumeSyncConfigRequest(BaseModel):
    """Request body for PUT /api/v1/ha/volume-sync/config."""

    standby_ssh_host: str
    ssh_port: int = 22
    ssh_key_path: str
    remote_upload_path: str = "/app/uploads/"
    remote_compliance_path: str = "/app/compliance_files/"
    sync_interval_minutes: int = Field(default=5, ge=1, le=1440)
    enabled: bool = False


class VolumeSyncConfigResponse(BaseModel):
    """Response for GET/PUT /api/v1/ha/volume-sync/config."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    standby_ssh_host: str
    ssh_port: int
    ssh_key_path: str
    remote_upload_path: str
    remote_compliance_path: str
    sync_interval_minutes: int
    enabled: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, v: object) -> str:
        return str(v) if v is not None else ""


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


class VolumeSyncStatusResponse(BaseModel):
    """Response for GET /api/v1/ha/volume-sync/status."""

    last_sync_time: datetime | None = None
    last_sync_result: str | None = None
    next_scheduled_sync: datetime | None = None
    total_file_count: int = 0
    total_size_bytes: int = 0
    sync_in_progress: bool = False


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


class VolumeSyncHistoryEntry(BaseModel):
    """Single sync history row returned by GET /api/v1/ha/volume-sync/history."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    started_at: datetime
    completed_at: datetime | None = None
    status: str
    files_transferred: int
    bytes_transferred: int
    error_message: str | None = None
    sync_type: str

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, v: object) -> str:
        return str(v) if v is not None else ""


# ---------------------------------------------------------------------------
# Trigger
# ---------------------------------------------------------------------------


class VolumeSyncTriggerResponse(BaseModel):
    """Response for POST /api/v1/ha/volume-sync/trigger."""

    message: str
    sync_id: str
