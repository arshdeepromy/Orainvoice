"""SQLAlchemy models for Cloud Backup & Restore (platform DR/BCP).

All tables defined here are **platform/global** tables: they carry NO
``org_id`` column and have NO Row-Level Security policy. This feature is
Global-Admin-only and access control is enforced at the API layer via
``require_role('global_admin')`` — matching how ``audit_log``, ``error_log``,
``subscription_plans`` and the HA tables (``ha_config`` …) work. A global-admin
request runs with ``app.current_org_id`` reset, which RLS uses to deny tenant
tables; these tables simply have no RLS policy so the global admin reads/writes
them directly through the standard session.

Services use ``flush()`` (never ``commit()``) per the ``get_db_session``
``session.begin()`` auto-commit pattern; after ``flush()``, ``await db.refresh(obj)``
before returning ORM objects for Pydantic serialization.

Requirements: 7.1, 7.3, 7.8, 8.4, 8.7, 12.16, 13.1, 13.2, 16.10, 18.11,
20.3, 23.1, 25.1, 30.2, 30.5
"""

from __future__ import annotations

import uuid
from datetime import datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    Time,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# ---------------------------------------------------------------------------
# Enumerated value sets (enforced at the service/API layer, mirrored here for
# documentation; the columns are plain VARCHAR per project convention).
# ---------------------------------------------------------------------------
PROVIDER_TYPES = ("google_drive", "onedrive", "s3", "nas")
CONNECTION_STATES = ("connected", "disconnected", "error")
RESIDENCY_VALUES = ("offshore", "onshore", "unknown")
BACKUP_SCOPES = ("settings_only", "organisations_only", "both")
CONSISTENCY_LEVELS = ("A", "C")
PRUNE_STATUSES = ("retained", "prune_failed", "pruned")
JOB_STATUSES = ("queued", "running", "completed", "failed", "cancelled")
JOB_TRIGGERS = ("scheduled", "manual")
RESTORE_MODES = ("full", "per_org", "dry_run")
REHEARSAL_RESULTS = ("passed", "failed")


class BackupDestination(Base):
    """A configured storage destination (provider-agnostic).

    Exactly one destination is the primary (enforced in the service layer,
    Req 30.2). ``config_encrypted`` holds the envelope-encrypted (under
    ``ENCRYPTION_MASTER_KEY``) provider credentials/JSON (Req 2.4, 28.4, 29.4).
    """

    __tablename__ = "backup_destinations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    # google_drive | onedrive | s3 | nas
    provider_type: Mapped[str] = mapped_column(String(20), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    # exactly one primary enforced in service layer (Req 30.2)
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    # Object-Lock target (Req 27)
    is_immutable_copy: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    # connected | disconnected | error
    connection_state: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="'disconnected'",
    )
    # envelope-encrypted (under ENCRYPTION_MASTER_KEY) JSON: OAuth tokens /
    # S3 keys / NAS creds (Req 2.4, 28.4, 29.4)
    config_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # offshore | onshore | unknown (Req 20.8 / 20.9)
    residency: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="'unknown'",
    )
    # for immutable copy
    lock_window_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
        nullable=False,
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )


class BackupResidencyAck(Base):
    """A global-admin acknowledgement of a destination's data residency.

    First upload to a destination is gated on a persisted acknowledgement
    (Req 20.3, 20.5).
    """

    __tablename__ = "backup_residency_ack"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    destination_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("backup_destinations.id"),
        nullable=False,
    )
    # acting global admin (Req 20.3, 20.5)
    acknowledged_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    acknowledged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class BackupKeyVersion(Base):
    """A version of the escrowed BMK→BDK key hierarchy.

    Exactly one row is active. Rotation mints a new version with a new BDK;
    prior versions are retained (``is_active=false``) for at least the
    configured backup retention period so historical backups stay restorable
    (Req 16.10).
    """

    __tablename__ = "backup_key_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    # monotonic key version (Req 16.10)
    version: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    # exactly one active
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    # argon2id (or scrypt)
    kdf_algo: Mapped[str] = mapped_column(String(20), nullable=False)
    # mem/time/parallel; salt stored separately
    kdf_params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Argon2id salt
    kdf_salt: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # BMK wrapped by PWK (recovery path)
    wrapped_bmk_passphrase: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # BMK wrapped by ENCRYPTION_MASTER_KEY (seamless runtime)
    wrapped_bmk_env: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # this version's BDK wrapped by BMK
    wrapped_bdk: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # key-check value (verifies correct passphrase/kit)
    bmk_kcv: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # retained >= retention period (Req 16.10)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class BackupConfig(Base):
    """Single-row global backup configuration (like ``ha_config``).

    Holds the schedule, backup window, retention, RPO/RTO, notification
    settings + recipient lists, GC grace period, per-org export cap, the
    rehearsal schedule, and the ``restore_maintenance_active`` flag read by
    ``RestoreMaintenanceMiddleware`` to gate/drain traffic during a full
    restore.
    """

    __tablename__ = "backup_config"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    # NZ-tz cron (Req 8.1)
    schedule_cron: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # backup window (Req 8.2 / 8.3)
    backup_window_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    backup_window_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    # retention (Req 8.4)
    retention_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # settings_only | organisations_only | both
    default_scope: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="'both'",
    )
    # RPO/RTO (Req 25)
    rpo_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="86400",
    )
    rto_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="14400",
    )
    rpo_rto_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    # notification toggles
    notify_backup_failure: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true",
    )
    notify_backup_success: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    notify_restore_failure: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true",
    )
    notify_restore_success: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    sms_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    email_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true",
    )
    # explicit recipient lists; empty email list falls back to all
    # global_admin emails, and an enabled channel resolving to no recipient is
    # recorded as a per-channel delivery failure (Req 18.11)
    notification_emails: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="'[]'::jsonb",
    )
    notification_sms_numbers: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="'[]'::jsonb",
    )
    # mark-and-sweep orphan GC safety grace (default 24h, Req 8.10)
    orphan_gc_grace_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="24",
    )
    perorg_export_size_cap_bytes: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True,
    )
    rehearsal_cron: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # DB-backed flag read by RestoreMaintenanceMiddleware to gate/drain
    # traffic during a full restore (Req 12.1 / 12.2)
    restore_maintenance_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
        nullable=False,
    )


class Backup(Base):
    """Committed Full_Backup catalog row.

    ``created_at``, ``scope`` and the size/checksum fields are cleartext
    catalog data; org-identifying data lives encrypted in ``org_ids_encrypted``
    (Req 7.8) and in the manifest envelope.
    """

    __tablename__ = "backups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    # cleartext catalog field
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    # settings_only | organisations_only | both
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    app_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Alembic revision (Req 10)
    schema_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # which BDK encrypts this backup
    key_version: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("backup_key_versions.version"), nullable=True,
    )
    dump_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # checksum of encrypted dump (Req 7.3)
    dump_checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # (Req 7.1)
    file_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    file_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # A or C (Req 23.1)
    consistency_level: Mapped[str | None] = mapped_column(String(2), nullable=True)
    # logical storage key of the manifest
    manifest_key: Mapped[str | None] = mapped_column(String, nullable=True)
    # retained | prune_failed | pruned (Req 8.7)
    prune_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="'retained'",
    )
    # encrypted list of org IDs (Req 7.8)
    org_ids_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)


class BackupDestinationCopy(Base):
    """M:N join of ``backups`` ↔ ``backup_destinations``.

    Records which destinations hold each backup, with per-destination write
    status (Req 30.5) and immutable-lock expiry.
    """

    __tablename__ = "backup_destination_copies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    backup_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("backups.id"), nullable=False,
    )
    destination_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("backup_destinations.id"), nullable=False,
    )
    # per-destination write status (Req 30.5)
    write_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="'pending'",
    )
    immutable_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class BackupBlob(Base):
    """A content-addressed File_Blob stored once (dedup). Used by mark-and-sweep
    GC (Req 8.10)."""

    __tablename__ = "backup_blobs"

    # SHA-256 content hash (PK)
    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    # HMAC name as stored
    blob_name: Mapped[str] = mapped_column(String, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    last_referenced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class BlobRefcount(Base):
    """(``content_hash``, ``backup_id``) join rows materialising each File_Index
    reference, so refcount pruning (Req 8.9) is a simple "delete blob where no
    remaining row references it"."""

    __tablename__ = "blob_refcounts"

    content_hash: Mapped[str] = mapped_column(
        String(64), ForeignKey("backup_blobs.content_hash"), primary_key=True,
    )
    backup_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("backups.id"), primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class BackupJob(Base):
    """Backup_Job lifecycle row (Req 13).

    ``queued → running → completed | failed | cancelled``; ``progress_pct`` and
    the heartbeat timestamps drive the ≤5 s progress-or-heartbeat contract
    (Req 13.2).
    """

    __tablename__ = "backup_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    # queued | running | completed | failed | cancelled (Req 13.1)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="'queued'",
    )
    # 0-100
    progress_pct: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    last_progress_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    # (Req 13.2)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    outcome_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # no stack traces (Req 9.10)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # scheduled | manual
    triggered_by: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="'manual'",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    # backup_jobs-specific
    scope: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # FK once committed
    backup_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("backups.id"), nullable=True,
    )
    skipped_file_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0",
    )


class RestoreJob(Base):
    """Restore_Job lifecycle row (Req 13).

    Shares the job lifecycle columns with ``backup_jobs`` and adds the restore
    specifics. ``destructive_apply_started`` is set immediately before
    ``pg_restore --clean``; the cancel handler reads it transactionally to allow
    a pre-apply cancel (→ ``cancelled``) vs refuse with 409 once the apply has
    begun (Req 12.16, 12.17).
    """

    __tablename__ = "restore_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    # queued | running | completed | failed | cancelled (Req 13.1)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="'queued'",
    )
    # 0-100
    progress_pct: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    last_progress_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    # (Req 13.2)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    outcome_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # no stack traces (Req 9.10)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # scheduled | manual
    triggered_by: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="'manual'",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    # restore_jobs-specific
    backup_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("backups.id"), nullable=True,
    )
    # full | per_org | dry_run
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    # null for full
    target_org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    conflict_policy: Mapped[str | None] = mapped_column(String(20), nullable=True)
    schema_compare_outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # (Req 10.8)
    restore_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pre_restore_snapshot_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    maintenance_enabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    standby_fenced: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    standby_reseeded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    # set immediately before pg_restore --clean; the cancel handler reads it
    # transactionally (pre-apply cancel vs 409 refusal) (Req 12.16, 12.17)
    destructive_apply_started: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    validation_results: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    file_consistency_outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)


class RestoreRehearsal(Base):
    """A scheduled restore rehearsal result (Req 25.4 / 25.5, Req 26)."""

    __tablename__ = "restore_rehearsals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    backup_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("backups.id"), nullable=True,
    )
    # passed | failed
    result: Mapped[str | None] = mapped_column(String(20), nullable=True)
    schema_check: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    rowcount_check: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    file_check: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    smoke_check: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # compared to RTO (Req 25.4 / 25.5)
    measured_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scratch_env_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    teardown_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
