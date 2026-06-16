"""Pydantic request/response schemas for Cloud Backup & Restore.

Placeholder base schemas establishing project conventions for this module.
Per the project rule, every list response is shaped ``{items, total}`` and never
a bare array. Concrete request/response models are added in later tasks.

Requirements: 1.1, 3.1
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

ItemT = TypeVar("ItemT")


class BackupBaseModel(BaseModel):
    """Base for all backup/restore response models.

    Enables ORM attribute population so SQLAlchemy rows serialize directly.
    """

    model_config = ConfigDict(from_attributes=True)


class ListResponse(BackupBaseModel, Generic[ItemT]):
    """Standard list envelope: arrays are always wrapped as ``{items, total}``.

    ``total`` is the total number of matching records (for pagination), which may
    exceed ``len(items)`` when ``offset``/``limit`` are applied.
    """

    items: list[ItemT] = Field(default_factory=list)
    total: int = 0


# ===========================================================================
# Request / response schemas for the Global-Admin API surface (task 15.3)
#
# Every list response reuses :class:`ListResponse` (``{items, total}``).
# Credentials are masked in every destination response (the service layer
# applies :func:`app.modules.backup_restore.config_service.mask_config`); no
# schema field ever carries a clear secret. ``offset`` / ``limit`` pagination
# is applied by the router, and ``total`` reflects the full match count.
# ===========================================================================

# ---------------------------------------------------------------------------
# Destinations
# ---------------------------------------------------------------------------
class DestinationCreateRequest(BackupBaseModel):
    """Create a backup storage destination (Req 2.1 / 30.2).

    ``config`` carries the provider-independent settings + credentials (S3
    keys / NAS creds / OAuth client). Credentials are envelope-encrypted under
    ``ENCRYPTION_MASTER_KEY`` by the service and never returned in clear.
    """

    provider_type: str = Field(..., description="google_drive | onedrive | s3 | nas")
    display_name: str
    config: dict[str, Any] = Field(default_factory=dict)
    residency: Optional[str] = None
    is_immutable_copy: bool = False
    lock_window_days: Optional[int] = None


class DestinationEditRequest(BackupBaseModel):
    """Edit a destination's display name / immutable flag / non-secret config.

    A credential field submitted as its masked placeholder is preserved (the
    stored ciphertext is kept). ``is_primary`` is never changed here — that is
    the ``set-primary`` endpoint's job (Req 30.7).
    """

    display_name: Optional[str] = None
    is_immutable_copy: Optional[bool] = None
    lock_window_days: Optional[int] = None
    config: Optional[dict[str, Any]] = None


class DestinationResponse(BackupBaseModel):
    """A configured destination with credentials masked (Req 30.2)."""

    id: uuid.UUID
    provider_type: str
    display_name: str
    is_primary: bool
    is_immutable_copy: bool
    connection_state: str
    residency: str
    lock_window_days: Optional[int] = None
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ConnectionTestResponse(BackupBaseModel):
    """Outcome of a destination connection test (Req 2.7)."""

    state: str
    detail: str = ""


class ResidencyNoticeResponse(BackupBaseModel):
    """The data-residency disclosure notice for a destination (Req 20)."""

    residency: str
    destination_label: str
    offshore_warning: bool
    requires_acknowledgement: bool
    headline: str
    body: str
    biometric_notice: str
    text: str
    acknowledged: bool = False


class ResidencyAckResponse(BackupBaseModel):
    """Result of acknowledging a destination's residency (Req 20.3)."""

    destination_id: uuid.UUID
    acknowledged: bool
    acknowledged_at: Optional[datetime] = None


class OAuthConnectResponse(BackupBaseModel):
    """The provider authorization URL the SPA opens in a popup (Req 2.5)."""

    authorization_url: str
    state: str


# ---------------------------------------------------------------------------
# Backups + jobs
# ---------------------------------------------------------------------------
class RunBackupRequest(BackupBaseModel):
    """Trigger an immediate backup (Req 8.8). ``scope`` defaults to config."""

    scope: Optional[str] = None


class BackupResponse(BackupBaseModel):
    """A committed Full_Backup catalog row (cleartext catalog fields only)."""

    id: uuid.UUID
    created_at: datetime
    scope: str
    app_version: Optional[str] = None
    schema_version: Optional[str] = None
    key_version: Optional[int] = None
    dump_size_bytes: Optional[int] = None
    dump_checksum: Optional[str] = None
    file_count: Optional[int] = None
    file_bytes: Optional[int] = None
    consistency_level: Optional[str] = None
    prune_status: str
    # True when this backup was created by a manual run (a ``backup_jobs`` row
    # with ``triggered_by='manual'``) — only these may be operator-deleted.
    is_manual: bool = False


class DeletionRequestBody(BackupBaseModel):
    """Request a deletion verification code for a set of backups (or all manual)."""

    backup_ids: Optional[list[uuid.UUID]] = None
    all_manual: bool = False


class DeletionChallengeResponse(BackupBaseModel):
    """A verification code was emailed; confirm with the returned challenge id."""

    challenge_id: str
    expires_at: datetime
    recipient: str
    backup_count: int


class DeletionConfirmBody(BackupBaseModel):
    """Confirm a backup deletion with the emailed 6-digit code."""

    challenge_id: str
    code: str


class DeletionResultResponse(BackupBaseModel):
    """Outcome of a confirmed backup deletion."""

    requested: int
    deleted: int
    failed: int
    blobs_deleted: int
    failed_ids: list[uuid.UUID] = []


class DeletionJobAcceptedResponse(BackupBaseModel):
    """A confirmed deletion was accepted and runs in the background."""

    job_id: str
    requested: int
    status: str


class DeletionJobStatusResponse(BackupBaseModel):
    """Live/terminal status of a background backup-deletion job."""

    status: str  # running | completed | failed
    requested: int
    deleted: int
    failed: int
    blobs_deleted: int
    error: Optional[str] = None


class StorageUsageResponse(BackupBaseModel):
    """A destination's storage quota/usage (any field null if not reported)."""

    reported: bool
    total_bytes: Optional[int] = None
    used_bytes: Optional[int] = None
    available_bytes: Optional[int] = None


class JobStatusResponse(BackupBaseModel):
    """A point-in-time job status view (Req 13.3)."""

    id: uuid.UUID
    status: str
    progress_pct: int
    elapsed_seconds: float
    seconds_since_last_update: float
    # Terminal detail (populated once the job finishes) so the UI can show a
    # human-readable summary, surface the error on failure, and link to the
    # resulting backup. Null while the job is still queued/running.
    outcome_summary: Optional[str] = None
    error_message: Optional[str] = None
    backup_id: Optional[uuid.UUID] = None


class JobAcceptedResponse(BackupBaseModel):
    """A background job was accepted; poll ``job_id`` for status."""

    job_id: uuid.UUID
    status: str


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------
class DryRunStepResponse(BackupBaseModel):
    name: str
    outcome: str
    detail: str


class DryRunRequest(BackupBaseModel):
    """Request a validation-only dry-run for a backup (Req 11.1)."""

    backup_id: uuid.UUID
    # Optional recovery key material for a fresh deployment (Req 16.7); when
    # omitted the seamless ENCRYPTION_MASTER_KEY path is used.
    recovery_kit: Optional[dict[str, Any]] = None
    passphrase: Optional[str] = None


class DryRunResponse(BackupBaseModel):
    """Dry-run result with the ``older_schema`` gate flag + both versions (Req 10.6/11.4)."""

    overall: str
    checksum_ok: bool
    older_schema: bool
    backup_version: Optional[str] = None
    target_version: Optional[str] = None
    schema_outcome: Optional[str] = None
    schema_decision: Optional[str] = None
    elapsed_seconds: float = 0.0
    steps: list[DryRunStepResponse] = Field(default_factory=list)


class FullRestoreRequest(BackupBaseModel):
    """Launch a full-platform restore (Req 12.1).

    ``confirm_older_schema`` must be ``true`` to proceed with an older-schema
    backup (pre-submission gate resolved by the dry-run, Req 10.6/10.7).
    """

    backup_id: uuid.UUID
    confirm_older_schema: bool = False
    recovery_kit: Optional[dict[str, Any]] = None
    passphrase: Optional[str] = None


class PerOrgRestoreRequest(BackupBaseModel):
    """Launch a per-organisation restore (Req 14)."""

    backup_id: uuid.UUID
    org_id: uuid.UUID
    conflict_policy: str = Field(
        "restore_as_new", description="restore_as_new | skip | overwrite"
    )
    selected_tables: Optional[list[str]] = None
    restore_files: bool = True
    recovery_kit: Optional[dict[str, Any]] = None
    passphrase: Optional[str] = None


class BrowseEntityResponse(BackupBaseModel):
    entity_type: str
    record_count: int


class BrowseOrgResponse(BackupBaseModel):
    """One organisation's browsable contents in a backup (Req 15.1)."""

    org_id: str
    org_name: Optional[str] = None
    entities: list[BrowseEntityResponse] = Field(default_factory=list)
    logical_export_emitted: bool = False


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------
class KeyStatusResponse(BackupBaseModel):
    """Backup-key state for the restore wizard / setup page (Req 16.12)."""

    has_active_key: bool
    active_version: Optional[int] = None
    setup_complete: bool


class KeySetupRequest(BackupBaseModel):
    """First-run key setup with an operator passphrase (Req 16.3/16.4)."""

    passphrase: str


class KeySetupResponse(BackupBaseModel):
    """The one-time Recovery Kit produced by setup (download once)."""

    recovery_kit: dict[str, Any]
    message: str = (
        "Store this Recovery Kit and passphrase offline. It cannot be re-derived "
        "and is required to restore on a fresh deployment."
    )


class RecoveryKitResponse(BackupBaseModel):
    """A re-exported Recovery Kit (Req 16.4)."""

    recovery_kit: dict[str, Any]


class KeyRotateResponse(BackupBaseModel):
    """Result of a key rotation (Req 16.10)."""

    active_version: int


class KeyBootstrapRequest(BackupBaseModel):
    """Fresh-deployment bootstrap from a Recovery Kit + passphrase (Req 16.7)."""

    recovery_kit: dict[str, Any]
    passphrase: str
    version: Optional[int] = None


class KeyBootstrapResponse(BackupBaseModel):
    has_active_key: bool
    active_version: Optional[int] = None
    setup_complete: bool


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
class ConfigResponse(BackupBaseModel):
    """The single-row backup configuration (Req 8 / 18 / 25)."""

    id: uuid.UUID
    schedule_cron: Optional[str] = None
    backup_window_start: Optional[Any] = None
    backup_window_end: Optional[Any] = None
    retention_count: Optional[int] = None
    retention_days: Optional[int] = None
    default_scope: str
    rpo_seconds: int
    rto_seconds: int
    notify_backup_failure: bool
    notify_backup_success: bool
    notify_restore_failure: bool
    notify_restore_success: bool
    webhook_url: Optional[str] = None
    sms_enabled: bool
    email_enabled: bool
    notification_emails: list[str] = Field(default_factory=list)
    notification_sms_numbers: list[str] = Field(default_factory=list)
    orphan_gc_grace_hours: int
    perorg_export_size_cap_bytes: Optional[int] = None
    rehearsal_cron: Optional[str] = None
    restore_maintenance_active: bool


class ConfigUpdateRequest(BackupBaseModel):
    """A partial configuration update (Req 8 / 18 / 25). Unknown keys ignored."""

    schedule_cron: Optional[str] = None
    backup_window_start: Optional[Any] = None
    backup_window_end: Optional[Any] = None
    retention_count: Optional[int] = None
    retention_days: Optional[int] = None
    default_scope: Optional[str] = None
    rpo_seconds: Optional[int] = None
    rto_seconds: Optional[int] = None
    notify_backup_failure: Optional[bool] = None
    notify_backup_success: Optional[bool] = None
    notify_restore_failure: Optional[bool] = None
    notify_restore_success: Optional[bool] = None
    webhook_url: Optional[str] = None
    sms_enabled: Optional[bool] = None
    email_enabled: Optional[bool] = None
    notification_emails: Optional[list[str]] = None
    notification_sms_numbers: Optional[list[str]] = None
    orphan_gc_grace_hours: Optional[int] = None
    perorg_export_size_cap_bytes: Optional[int] = None
    rehearsal_cron: Optional[str] = None


class ConfigUpdateResponse(BackupBaseModel):
    """A config update result with any non-blocking RPO warnings (Req 25.2)."""

    config: ConfigResponse
    warnings: list[str] = Field(default_factory=list)


class ChannelResultResponse(BackupBaseModel):
    channel: str
    ok: bool
    detail: str


class NotificationTestResponse(BackupBaseModel):
    """Per-channel test-notification outcome (Req 18.12)."""

    results: list[ChannelResultResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Rehearsals
# ---------------------------------------------------------------------------
class RehearsalResponse(BackupBaseModel):
    """A recorded restore-rehearsal result (Req 26.4)."""

    id: uuid.UUID
    backup_id: Optional[uuid.UUID] = None
    result: Optional[str] = None
    measured_duration_seconds: Optional[int] = None
    scratch_env_id: Optional[str] = None
    teardown_status: Optional[str] = None
    created_at: datetime
    schema_check: Optional[dict[str, Any]] = None
    rowcount_check: Optional[dict[str, Any]] = None
    file_check: Optional[dict[str, Any]] = None
    smoke_check: Optional[dict[str, Any]] = None
