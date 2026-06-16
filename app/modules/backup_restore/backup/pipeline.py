"""Backup pipeline orchestration (cloud-backup-restore Req 5, 6, 7, 8, 17, 21, 23, 30, 31).

``backup/pipeline.py`` drives a Backup_Job end to end, composing the pieces built
in the surrounding modules:

* :mod:`backup.pg_dump_runner` (``dump_standby``) — the standby-sourced DB dump,
* :mod:`backup.cas` (``FileBlobStore``) — content-addressed, deduplicated,
  client-side-encrypted file capture from the primary's local volumes,
* :mod:`backup.manifest` — File_Index / Per_Org_Index / Backup_Manifest builders
  with the cleartext-catalog / encrypted-envelope split,
* :mod:`keys.key_service` (``BackupKeyService``/``backup_envelope_encrypt``) — the
  escrowed BMK→BDK hierarchy and BDK-keyed envelope encryption,
* :mod:`storage` (the provider-agnostic ``StorageInterface`` + registry) — the
  fan-out destinations,
* :mod:`backup.prune` (storage-key helpers) — shared artifact key conventions.

It implements the design's "Backup Pipeline" steps 1-10:

1. **Pre-flight + write-ahead audit.** Validate ``Backup_Scope`` ∈
   {``settings_only``, ``organisations_only``, ``both``} (Req 6.1, 6.2 — an
   invalid scope is rejected with NO artifact/manifest created). Durably write the
   write-ahead audit entry; abort before any work if it fails (Req 17.6, 17.7).
   Acquire the prune/GC mutual-exclusion lock for the destination set (Req 8.11).
2. **Resolve keys.** ``BackupKeyService.get_active_bdk()`` → ``(version, bdk)``.
3. **Database dump (standby-sourced).** ``dump_standby`` runs ``pg_dump -Fc`` against
   the standby replica (Req 5.1, 5.2, 23.2). A non-zero exit fails the job with a
   human-readable reason + failure notification (Req 5.6).
4. **File capture (content-addressed).** For ``organisations_only``/``both``,
   enumerate ``/app/uploads/`` (all category subfolders) and
   ``/app/compliance_files/`` **wholesale** — no hardcoded allowlist, so new
   categories are picked up automatically (Req 21.1, 21.2). DB-stored BYTEA assets
   (branding) are excluded because they travel inside the dump (Req 21.2). Files are
   read from the **primary node's own local volumes** (the rsync source of truth).
5. **Point-in-time consistency (Req 23).** Write-through CAS gives true temporal
   consistency (level **A**); the level is recorded on the Backup row (Req 23.1).
6. **Per-org logical export (opportunistic, Req 31).** Where the size budget allows
   (``perorg_export_size_cap_bytes``), emit a Per_Org_Logical_Export per org; the
   full dump remains the unconditional system-of-record (Req 31.1, 31.2).
7. **Manifest + indexes (Req 7).** Build the File_Index / Per_Org_Index / manifest;
   the checksum is computed over the **encrypted** dump bytes (Req 7.3).
8. **Fan-out upload (Req 30).** Encrypt the dump once under the BDK and fan the
   identical encrypted artifact set out to the primary + every copy destination; a
   copy-destination write failure is surfaced + notified but does NOT fail the job,
   whereas a primary write failure fails the job (Req 30.3, 30.5, 30.6). Immutable
   copies receive the set under Object Lock for their lock window (Req 27.2).
9. **Commit + re-assertion (Req 8.12).** Re-assert that every reused (deduped) blob
   still exists at the primary before committing; re-upload a missing one or fail.
   Then insert the committed catalog rows (``backups``, ``blob_refcounts``,
   ``backup_destination_copies``).
10. **Completion.** Record artifact location/size/checksum (Req 5.5), write the
    completion audit entry (Req 17.6/17.8), release the lock, and dispatch the
    success notification if enabled.

Any upload failure marks the job ``failed``, leaves prior backups untouched, and
dispatches a failure notification (Req 5.7, 21.10).

Per the project ``get_db_session`` ``session.begin()`` auto-commit pattern, DB writes
use ``flush()`` / ``await db.refresh()`` and never ``commit()``.

Composition notes (placeholders that land in later tasks):

* **Audit (audit.py, task 13.3)** is not yet implemented, so the write-ahead and
  completion audit calls go through an injectable ``audit_hook``; the default logs.
  The write-ahead-fails-then-abort contract (Req 17.7) is honoured regardless of
  which hook is supplied.
* **Notifications (service.py, task 15.2)** are dispatched through an injectable
  ``notify_hook``; the default logs. Channel/recipient resolution is the service
  facade's job.
* **The per-destination prune/GC lock (prune.py, task 7.5)** is not yet implemented,
  so an injectable ``lock_factory`` is used; the default is a no-op context manager.
* **The Per_Org_Logical_Export generator (task 10/Req 31)** is not yet implemented,
  so per-org export emission goes through an injectable ``per_org_export_fn``; the
  default emits none (the full dump remains the system-of-record either way).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import async_session_factory
from app.core.encryption import envelope_decrypt
from app.modules.backup_restore.backup.cas import (
    DEFAULT_BLOB_PREFIX,
    BlobRef,
    FileBlobStore,
    KnownSkip,
)
from app.modules.backup_restore.backup.manifest import (
    CapturedFile,
    PerOrgEntityCount,
    PerOrgIndex,
    PerOrgIndexEntry,
    build_file_index,
    build_manifest,
    build_per_org_index,
    serialize_manifest,
)
from app.modules.backup_restore.backup.pg_dump_runner import (
    PgDumpError,
    PgDumpResult,
    dump_standby,
)
from app.modules.backup_restore.backup.prune import dump_storage_key
from app.modules.backup_restore.keys.key_service import (
    BackupKeyService,
    KeyBootstrapError,
    backup_envelope_encrypt,
)
from app.modules.backup_restore.models import (
    BACKUP_SCOPES,
    Backup,
    BackupConfig,
    BackupDestination,
    BackupDestinationCopy,
    BackupJob,
    BlobRefcount,
)
from app.modules.backup_restore.storage.errors import StorageError
from app.modules.backup_restore.storage.interface import AsyncByteStream, StorageInterface
from app.modules.backup_restore.storage.registry import resolve_adapter

logger = logging.getLogger(__name__)

# Wholesale file-capture roots on the primary node's own local volumes (Req 21.1,
# 21.2). Enumerated recursively with NO hardcoded category allowlist so new
# categories are picked up automatically. Injectable for testability.
DEFAULT_STORAGE_ROOTS: tuple[str, ...] = ("/app/uploads/", "/app/compliance_files/")

# Scopes that include the customer organisations' uploaded files (Req 6.4, 6.5).
_FILE_SCOPES = frozenset({"organisations_only", "both"})

# Write-through CAS provides true temporal point-in-time consistency (Req 23.1
# level "A"): each file is content-addressed into the store at capture time, so a
# committed manifest references content that demonstrably existed when captured.
CONSISTENCY_TRUE_TEMPORAL = "A"

# Per-destination copy write-status values recorded on ``backup_destination_copies``.
WRITE_STATUS_WRITTEN = "written"
WRITE_STATUS_FAILED = "failed"

# Logical artifact storage-key conventions (shared with prune.py for the dump).
MANIFEST_KEY_TEMPLATE = "backups/{backup_id}/manifest.json"
PER_ORG_EXPORT_KEY_TEMPLATE = "backups/{backup_id}/per_org/{org_id}.enc"

# Audit action names (the durable write-ahead + completion pattern, Req 17.6).
AUDIT_ACTION_BACKUP = "backup.created"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class BackupScopeError(ValueError):
    """An invalid ``Backup_Scope`` was supplied (Req 6.1, 6.2).

    Raised during pre-flight before any artifact or manifest is created, so an
    invalid scope never produces a backup.
    """


class BackupPipelineError(RuntimeError):
    """A backup could not be produced; carries a human-readable reason (Req 5.7).

    The pipeline marks the Backup_Job ``failed`` with this reason and dispatches a
    failure notification; prior successful backups are left untouched.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass
class DestinationTarget:
    """A resolved fan-out destination: its catalog row + its storage adapter."""

    destination: BackupDestination
    storage: StorageInterface

    @property
    def is_primary(self) -> bool:
        return bool(self.destination.is_primary)

    @property
    def immutable_until(self) -> datetime | None:
        """Object-Lock retain-until for an Immutable_Copy destination (Req 27.2)."""
        dest = self.destination
        if dest.is_immutable_copy and dest.lock_window_days:
            return datetime.now(timezone.utc) + timedelta(days=int(dest.lock_window_days))
        return None


@dataclass
class CopyWriteResult:
    """Per-destination write outcome recorded for the fan-out (Req 30.5)."""

    destination_id: uuid.UUID
    is_primary: bool
    status: str = WRITE_STATUS_WRITTEN
    errors: list[str] = field(default_factory=list)
    immutable_until: datetime | None = None

    def fail(self, message: str) -> None:
        self.status = WRITE_STATUS_FAILED
        self.errors.append(message)


@dataclass
class BackupPipelineResult:
    """Structured outcome of a successful pipeline run."""

    backup_id: uuid.UUID
    scope: str
    consistency_level: str
    key_version: int
    dump_size_bytes: int
    encrypted_dump_size: int
    dump_checksum: str
    file_count: int
    file_bytes: int
    skipped_file_count: int
    org_ids: list[str]
    manifest_key: str
    per_org_exports_emitted: int
    copy_results: list[CopyWriteResult]

    @property
    def copy_failures(self) -> list[CopyWriteResult]:
        return [c for c in self.copy_results if c.status == WRITE_STATUS_FAILED]


# Injectable hook signatures.
AuditHook = Callable[..., Awaitable[None] | None]
NotifyHook = Callable[..., Awaitable[None] | None]
LockFactory = Callable[[Sequence[uuid.UUID]], "contextlib.AbstractAsyncContextManager"]
OrgIdResolver = Callable[[str, str], str | None]
PerOrgExportFn = Callable[
    [AsyncSession, Sequence[str], bytes], Awaitable[Sequence[tuple[str, bytes]]]
]


# ---------------------------------------------------------------------------
# Default hooks (placeholders for audit.py / service.py / prune.py task 7.5)
# ---------------------------------------------------------------------------


async def _default_audit_hook(**kwargs: object) -> None:
    """Default write-ahead/completion audit hook — logs only (audit.py, task 13.3).

    The durable audit writer is implemented in task 13.3; until then this logs the
    audit intent. Because it never raises, the write-ahead-fails-then-abort path
    (Req 17.7) is exercised only when a real durable hook is injected.
    """
    logger.info("backup audit (placeholder): %s", kwargs)


async def _default_notify_hook(**kwargs: object) -> None:
    """Default notification hook — logs only (service.py notifications, task 15.2)."""
    logger.info("backup notification (placeholder): %s", kwargs)


@contextlib.asynccontextmanager
async def _noop_lock(destination_ids: Sequence[uuid.UUID]) -> AsyncIterator[None]:
    """Default prune/GC mutual-exclusion lock — no-op (prune.py lock, task 7.5).

    The per-destination lock excluding concurrent prune/GC (Req 8.11) is built in
    task 7.5; until then this is a no-op context manager so the pipeline composes.
    """
    logger.debug(
        "prune/GC lock (placeholder no-op) acquired for destinations %s",
        list(destination_ids),
    )
    yield


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _default_org_id_resolver(abs_path: str, root: str) -> str | None:
    """Derive a file's owning ``org_id`` from its path under a storage root.

    Uploaded files follow ``{root}/{category}/{org_id}/{file}`` (uploads) or
    ``{root}/compliance/{org_id}/{file}`` (compliance), so the owning org is the
    first UUID-shaped path component below the root. A file with no UUID component
    (for example platform-global page-editor media) is treated as a global/non-org
    file (``None``), the explicit global indicator the File_Index supports (Req 7.2).
    """
    try:
        rel = os.path.relpath(abs_path, root)
    except ValueError:
        return None
    parts = [p for p in rel.split(os.sep) if p not in ("", ".", "..")]
    # Exclude the filename itself (last component) from org-id consideration.
    for part in parts[:-1]:
        if _is_uuid(part):
            return part
    return None


# ---------------------------------------------------------------------------
# Stream helpers
# ---------------------------------------------------------------------------


def _bytes_stream(data: bytes) -> AsyncByteStream:
    """Adapt a single ``bytes`` payload to the adapter's ``AsyncByteStream``."""

    async def _gen() -> AsyncByteStream:  # type: ignore[misc]
        yield data

    return _gen()


async def _drain(stream: AsyncByteStream) -> bytes:
    """Fully read an ``AsyncByteStream`` into a single ``bytes`` value."""
    chunks: list[bytes] = []
    async for chunk in stream:
        chunks.append(chunk)
    return b"".join(chunks)


def _read_bytes(path: str) -> bytes:
    """Read a file fully into memory (raises ``OSError`` for unreadable paths)."""
    with open(path, "rb") as fh:
        return fh.read()


def _enumerate_files(root: str) -> list[str]:
    """Recursively enumerate every regular file under ``root`` (wholesale, Req 21.1).

    Walks all subfolders with no category allowlist. A non-existent root yields no
    files (a deployment may not have created a volume yet).
    """
    if not os.path.isdir(root):
        return []
    found: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            found.append(os.path.join(dirpath, name))
    return found


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class BackupPipeline:
    """Orchestrates a single Backup_Job end to end (design "Backup Pipeline").

    Args:
        db: Async DB session (uses ``flush()``/``refresh()``, never ``commit()``).
        key_service: Backup key service; defaults to a fresh ``BackupKeyService``.
        destinations: Pre-resolved fan-out targets (primary + copies). When omitted
            they are resolved from the ``backup_destinations`` table at run time;
            injecting them keeps the pipeline testable with fake storage adapters.
        storage_roots: Wholesale file-capture roots (Req 21.1); injectable for tests.
        config: The single-row ``backup_config``; loaded lazily when omitted.
        dump_runner: Standby ``pg_dump`` runner; defaults to ``dump_standby``.
        audit_hook / notify_hook: Thin durable-audit / notification hooks (placeholders
            until tasks 13.3 / 15.2 — see module docstring).
        lock_factory: Per-destination prune/GC lock (placeholder until task 7.5).
        org_id_resolver: Maps ``(abs_path, root)`` → owning ``org_id`` or ``None``.
        per_org_export_fn: Optional Per_Org_Logical_Export generator (Req 31).
        blob_prefix: Storage-key prefix for content-addressed blobs.
        clock: Injectable ``now`` provider (UTC) for deterministic tests.
        app_version: Application version recorded on the backup (Req 7.1).
    """

    def __init__(
        self,
        db: AsyncSession,
        *,
        key_service: BackupKeyService | None = None,
        destinations: Sequence[DestinationTarget] | None = None,
        storage_roots: Sequence[str] = DEFAULT_STORAGE_ROOTS,
        config: BackupConfig | None = None,
        dump_runner: Callable[..., Awaitable[PgDumpResult]] = dump_standby,
        audit_hook: AuditHook | None = None,
        notify_hook: NotifyHook | None = None,
        lock_factory: LockFactory | None = None,
        org_id_resolver: OrgIdResolver | None = None,
        per_org_export_fn: PerOrgExportFn | None = None,
        blob_prefix: str = DEFAULT_BLOB_PREFIX,
        clock: Callable[[], datetime] | None = None,
        app_version: str | None = None,
    ) -> None:
        self.db = db
        self.key_service = key_service or BackupKeyService(db)
        self._injected_destinations = list(destinations) if destinations is not None else None
        self.storage_roots = tuple(storage_roots)
        self._config = config
        self.dump_runner = dump_runner
        self.audit_hook = audit_hook or _default_audit_hook
        self.notify_hook = notify_hook or _default_notify_hook
        self.lock_factory = lock_factory or _noop_lock
        self.org_id_resolver = org_id_resolver or _default_org_id_resolver
        self.per_org_export_fn = per_org_export_fn
        self.blob_prefix = blob_prefix
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.app_version = app_version if app_version is not None else getattr(
            settings, "app_version", None
        )

        self._job: BackupJob | None = None
        self._primary: DestinationTarget | None = None
        self._copies: list[DestinationTarget] = []
        self._copy_results: dict[uuid.UUID, CopyWriteResult] = {}

    # -- public entry point -------------------------------------------------

    async def run(
        self,
        *,
        scope: str,
        triggered_by: str = "manual",
        actor_id: uuid.UUID | None = None,
        job: BackupJob | None = None,
    ) -> BackupPipelineResult:
        """Produce one Full_Backup for ``scope`` and fan it out to all destinations.

        Raises:
            BackupScopeError: the scope is invalid — no artifact/manifest created
                (Req 6.2). The job (if any) is marked ``failed``.
            BackupPipelineError: the dump or a primary write failed; the job is
                marked ``failed`` and a failure notification is dispatched (Req 5.7).
        """
        self._job = job
        backup_id = uuid.uuid4()

        # Step 1a — scope validation (Req 6.1, 6.2). Reject BEFORE any work so an
        # invalid scope never produces an artifact or manifest.
        if not scope or scope not in BACKUP_SCOPES:
            await self._mark_job_failed(
                f"Invalid Backup_Scope {scope!r}; accepted values are "
                f"{', '.join(BACKUP_SCOPES)}."
            )
            raise BackupScopeError(
                f"Invalid Backup_Scope {scope!r}; accepted values are "
                f"{', '.join(BACKUP_SCOPES)}."
            )

        await self._mark_job_running(scope, triggered_by)

        # Resolve fan-out destinations (primary + copies) and ensure a primary.
        try:
            await self._resolve_targets()
        except BackupPipelineError as exc:
            await self._fail(backup_id, exc.reason)
            raise

        destination_ids = [self._primary.destination.id] + [
            c.destination.id for c in self._copies
        ]

        # Step 1b — durable write-ahead audit; abort before any work if it fails
        # (Req 17.6, 17.7).
        try:
            await self._call_audit(
                phase="write_ahead",
                action=AUDIT_ACTION_BACKUP,
                target_id=backup_id,
                actor_id=actor_id,
                scope=scope,
            )
        except Exception as exc:  # noqa: BLE001 - audit failure aborts the op
            reason = (
                "Backup aborted: the write-ahead audit entry could not be durably "
                f"recorded ({exc})."
            )
            await self._fail(backup_id, reason)
            raise BackupPipelineError(reason) from exc

        # Step 1c — acquire the prune/GC mutual-exclusion lock for the destination
        # set so no concurrent prune/GC deletes a blob this backup may reuse
        # (Req 8.11). Placeholder no-op until task 7.5.
        try:
            async with self.lock_factory(destination_ids):
                result = await self._run_locked(
                    backup_id=backup_id,
                    scope=scope,
                    triggered_by=triggered_by,
                    actor_id=actor_id,
                )
        except (BackupPipelineError, PgDumpError) as exc:
            reason = getattr(exc, "reason", None) or str(exc)
            await self._fail(backup_id, reason)
            raise BackupPipelineError(reason) from exc

        return result

    # -- the locked body (steps 2-10) --------------------------------------

    async def _run_locked(
        self,
        *,
        backup_id: uuid.UUID,
        scope: str,
        triggered_by: str,
        actor_id: uuid.UUID | None,
    ) -> BackupPipelineResult:
        # Step 2 — resolve keys (active BDK via the seamless ENCRYPTION_MASTER_KEY path).
        try:
            key_version, bdk = await self.key_service.get_active_bdk()
        except KeyBootstrapError as exc:
            raise BackupPipelineError(
                f"Backup aborted: no usable backup key on this deployment ({exc})."
            ) from exc

        # Step 3 — database dump (standby-sourced, full, REPEATABLE READ snapshot).
        dump_path: str | None = None
        try:
            dump_result = await self.dump_runner(self.db)
            dump_path = dump_result.dump_path
            await self._progress(30, "database dump complete")

            # Step 4/5 — file capture (write-through CAS → consistency level "A").
            captured, skipped_count = await self._capture_files(scope, bdk)
            await self._progress(55, "file capture complete")

            # Read the (plaintext) dump and encrypt it once under the BDK; the
            # checksum is computed over the ENCRYPTED bytes (Req 7.3).
            dump_plaintext = await self._read_dump(dump_path)
            encrypted_dump = await asyncio.to_thread(
                backup_envelope_encrypt, dump_plaintext, bdk
            )

            # Step 6 — per-org index + opportunistic Per_Org_Logical_Export.
            # Include EVERY organisation contained in the dump (for org-inclusive
            # scopes), not just orgs that happened to have captured files — the
            # full pg_dump contains all orgs, so the restore wizard must be able to
            # browse/select any of them. File owners are a subset of these.
            file_org_ids = {c.org_id for c in captured if c.org_id}
            all_org_ids = await self._all_org_ids() if scope in _FILE_SCOPES else set()
            org_ids = sorted(all_org_ids | file_org_ids)
            entity_counts = await self._compute_per_org_entity_counts(scope, org_ids)
            per_org_index = self._build_per_org_index(scope, org_ids, entity_counts)
            per_org_artifacts = await self._maybe_per_org_exports(
                scope=scope,
                org_ids=org_ids,
                bdk=bdk,
                dump_byte_size=dump_result.byte_size,
                per_org_index=per_org_index,
                backup_id=backup_id,
            )

            # Step 7 — manifest + indexes (cleartext catalog / encrypted envelope).
            file_index = build_file_index(captured, skipped_count=skipped_count)
            schema_version = await self._read_schema_version()
            manifest = build_manifest(
                backup_id=str(backup_id),
                created_at=self.clock(),
                scope=scope,
                encrypted_dump=encrypted_dump,
                file_index=file_index,
                per_org_index=per_org_index,
                org_ids=org_ids,
                app_version=self.app_version,
                schema_version=schema_version,
                key_version=key_version,
            )
            manifest_bytes = serialize_manifest(manifest, bdk)
            manifest_key = MANIFEST_KEY_TEMPLATE.format(backup_id=backup_id)
            dump_key = dump_storage_key(backup_id)
            await self._progress(65, "manifest assembled")

            # Step 8 — fan-out the identical encrypted artifact set (Req 30.3).
            #   dump.enc + manifest.json to every destination; blobs mirrored to
            #   copies from the primary; per-org exports already fanned out above.
            await self._fanout_artifact(dump_key, encrypted_dump)
            await self._fanout_artifact(manifest_key, manifest_bytes)
            await self._mirror_blobs_to_copies(captured)
            await self._progress(85, "fan-out upload complete")

            # Step 9 — commit-time re-assertion that reused blobs still exist at the
            # primary; re-upload a missing one or fail the job (Req 8.12).
            await self._reassert_reused_blobs(captured, bdk)

            # Step 9 (commit) — write the committed catalog rows.
            backup_row = await self._commit_catalog(
                backup_id=backup_id,
                scope=scope,
                key_version=key_version,
                dump_result=dump_result,
                encrypted_dump=encrypted_dump,
                checksum=manifest.catalog.checksum,
                file_index=file_index,
                manifest_key=manifest_key,
                org_ids=org_ids,
                schema_version=schema_version,
                bdk=bdk,
            )
        finally:
            # Always remove the local plaintext dump file (it never leaves the box
            # unencrypted and must not linger on disk).
            if dump_path:
                _safe_unlink(dump_path)

        # Step 10 — completion: record outcome, completion audit, success notify.
        result = BackupPipelineResult(
            backup_id=backup_id,
            scope=scope,
            consistency_level=backup_row.consistency_level or CONSISTENCY_TRUE_TEMPORAL,
            key_version=key_version,
            dump_size_bytes=dump_result.byte_size,
            encrypted_dump_size=len(encrypted_dump),
            dump_checksum=manifest.catalog.checksum,
            file_count=file_index.file_count,
            file_bytes=file_index.total_bytes,
            skipped_file_count=skipped_count,
            org_ids=org_ids,
            manifest_key=manifest_key,
            per_org_exports_emitted=len(per_org_artifacts),
            copy_results=list(self._copy_results.values()),
        )

        await self._complete(backup_id, actor_id, result)
        return result

    # -- step 1: target resolution -----------------------------------------

    async def _resolve_targets(self) -> None:
        """Resolve and validate the fan-out destinations (exactly one primary)."""
        targets = self._injected_destinations
        if targets is None:
            targets = await self._resolve_destinations_from_db()

        primaries = [t for t in targets if t.is_primary]
        if not primaries:
            raise BackupPipelineError(
                "No primary backup destination is configured; configure exactly one "
                "primary destination before running a backup."
            )
        if len(primaries) > 1:
            raise BackupPipelineError(
                "More than one primary backup destination is configured; exactly one "
                "primary is required."
            )

        self._primary = primaries[0]
        self._copies = [t for t in targets if not t.is_primary]
        self._copy_results = {
            t.destination.id: CopyWriteResult(
                destination_id=t.destination.id,
                is_primary=t.is_primary,
                immutable_until=t.immutable_until,
            )
            for t in targets
        }

    async def _resolve_destinations_from_db(self) -> list[DestinationTarget]:
        """Build fan-out targets from the ``backup_destinations`` table.

        Decrypts each destination's ``config_encrypted`` (under ``ENCRYPTION_MASTER_KEY``
        — operational secrets, Req 2.4/28.4/29.4) and resolves a provider adapter via
        the registry. A destination whose adapter cannot be resolved raises a uniform
        provider/storage error.
        """
        result = await self.db.execute(select(BackupDestination))
        rows = list(result.scalars().all())
        targets: list[DestinationTarget] = []
        for dest in rows:
            config = self._decrypt_destination_config(dest)
            adapter = resolve_adapter(dest.provider_type, config)
            targets.append(DestinationTarget(destination=dest, storage=adapter))
        return targets

    @staticmethod
    def _decrypt_destination_config(dest: BackupDestination) -> dict:
        """Decrypt a destination's stored provider config to a plain mapping."""
        if not dest.config_encrypted:
            return {}
        try:
            plaintext = envelope_decrypt(dest.config_encrypted)
            data = json.loads(plaintext.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - normalise to a storage error
            raise StorageError(
                "The stored configuration for the backup destination could not be "
                "decoded.",
                operation="resolve",
                provider=dest.provider_type,
            ) from exc
        return data if isinstance(data, dict) else {}

    # -- step 4: file capture ----------------------------------------------

    async def _capture_files(
        self, scope: str, bdk: bytes
    ) -> tuple[list[CapturedFile], int]:
        """Capture uploaded files wholesale into the primary content-addressed store.

        Returns the per-file capture records (for the File_Index) and the known-skip
        count. For ``settings_only`` no files are captured (the dump alone carries
        settings) so this returns ``([], 0)`` (Req 6.3).
        """
        if scope not in _FILE_SCOPES:
            return [], 0

        store = FileBlobStore(
            self._primary.storage,
            bdk,
            self.db,
            blob_prefix=self.blob_prefix,
        )
        primary_iu = self._primary.immutable_until

        captured: list[CapturedFile] = []
        skipped_count = 0
        for root in self.storage_roots:
            for abs_path in _enumerate_files(root):
                outcome: BlobRef | KnownSkip = await store.capture_file(
                    abs_path, immutable_until=primary_iu
                )
                if isinstance(outcome, KnownSkip):
                    # Unreadable/missing file: omit from the File_Index, count it,
                    # keep going (Req 21.9). A primary upload failure, by contrast,
                    # raises StorageError from put_blob and fails the job below.
                    skipped_count += 1
                    continue
                org_id = self.org_id_resolver(abs_path, root)
                captured.append(
                    CapturedFile(path=abs_path, org_id=org_id, blob_ref=outcome)
                )
        return captured, skipped_count

    # -- step 6: per-org logical export ------------------------------------

    async def _all_org_ids(self) -> set[str]:
        """Every organisation id in the database.

        The full ``pg_dump`` captures all orgs, so the Per_Org_Index must list
        them all (not just orgs that had captured files) — otherwise the restore
        wizard can only ever browse/select the file-owning subset.
        """
        try:
            result = await self.db.execute(text("SELECT id FROM organisations"))
            return {str(row[0]) for row in result.fetchall()}
        except Exception:  # noqa: BLE001 - best-effort; fall back to file owners
            logger.warning(
                "could not enumerate organisations for the per-org index",
                exc_info=True,
            )
            return set()

    async def _compute_per_org_entity_counts(
        self, scope: str, org_ids: Sequence[str]
    ) -> dict[str, list[PerOrgEntityCount]]:
        """Compute per-organisation, per-entity-type row counts for the Per_Org_Index.

        These counts populate the restore wizard's per-org browse (Req 15.2, 7.9)
        so an operator can see what each organisation contains and select entity
        types to restore — without staging the full ``pg_dump``.

        Scale + safety design:
        * **O(tables), not O(tables × orgs)** — one grouped aggregate per
          org-scoped/hybrid table (``SELECT org_id, count(*) ... GROUP BY org_id``)
          returns every org's count in a single pass. Org-scoped tables are
          indexed on ``org_id`` (for RLS), so these are index-range aggregates.
        * **Bounded** — each table's count runs in its own transaction with a
          ``SET LOCAL statement_timeout``; a table that exceeds it (or errors) is
          skipped and logged, so counting can never hang or fail the backup.
        * **Isolated** — runs on a short-lived session separate from the backup's
          main transaction, holding no locks on the data being backed up.
        * Only **org-scoped** (non-null ``org_id``) and **hybrid** (non-null rows)
          tables are counted; shared/global and excluded tables are skipped.

        Counts are a point-in-time view as of backup time (display/selection
        metadata); the restore itself always reads the dump, so minor drift from
        the dump snapshot is immaterial.
        """
        if scope not in _FILE_SCOPES or not org_ids:
            return {}

        from app.modules.backup_restore.restore.classifier import (
            TableClass,
            classifiable_tables,
            classify_table,
        )

        org_set = {str(o) for o in org_ids}
        result: dict[str, list[PerOrgEntityCount]] = {str(o): [] for o in org_ids}

        try:
            tables = classifiable_tables()
        except Exception:  # noqa: BLE001 - never fail the backup over counts
            logger.warning(
                "per-org entity counts skipped: could not enumerate tables",
                exc_info=True,
            )
            return result

        async with async_session_factory() as session:
            for table in tables:
                try:
                    table_class = classify_table(table)
                except Exception:  # noqa: BLE001
                    continue
                if table_class not in (TableClass.ORG_SCOPED, TableClass.HYBRID):
                    continue
                # Hybrid tables hold platform-wide (NULL org_id) rows too; count
                # only the org-owned rows. Table names come from trusted model
                # metadata; double-quote them defensively.
                where = "WHERE org_id IS NOT NULL" if table_class is TableClass.HYBRID else ""
                sql = f'SELECT org_id, count(*) AS c FROM "{table}" {where} GROUP BY org_id'
                try:
                    async with session.begin():
                        await session.execute(
                            text("SET LOCAL statement_timeout = '60s'")
                        )
                        rows = (await session.execute(text(sql))).all()
                except Exception:  # noqa: BLE001 - skip this table, keep going
                    logger.debug(
                        "per-org entity count skipped for table %s", table, exc_info=True
                    )
                    continue
                for org_id, count in rows:
                    oid = str(org_id)
                    if oid in org_set and count:
                        result[oid].append(
                            PerOrgEntityCount(entity_type=table, record_count=int(count))
                        )

        # Stable, name-sorted entity lists for deterministic browsing.
        for oid in result:
            result[oid].sort(key=lambda e: e.entity_type)
        return result

    def _build_per_org_index(
        self,
        scope: str,
        org_ids: Sequence[str],
        entity_counts: dict[str, list[PerOrgEntityCount]] | None = None,
    ) -> PerOrgIndex:
        """Build the Per_Org_Index: one entry per contained org with its
        per-entity-type record counts (Req 7.9, 15.2).

        For ``organisations_only``/``both`` an entry is created per org (so browse
        can enumerate them) populated with the per-entity counts computed by
        :meth:`_compute_per_org_entity_counts`. For ``settings_only`` the index is
        empty.
        """
        if scope not in _FILE_SCOPES:
            return PerOrgIndex()
        counts = entity_counts or {}
        entries = [
            PerOrgIndexEntry(org_id=org_id, entities=list(counts.get(str(org_id), [])))
            for org_id in org_ids
        ]
        return build_per_org_index(entries)

    async def _maybe_per_org_exports(
        self,
        *,
        scope: str,
        org_ids: Sequence[str],
        bdk: bytes,
        dump_byte_size: int,
        per_org_index: PerOrgIndex,
        backup_id: uuid.UUID,
    ) -> list[str]:
        """Opportunistically emit Per_Org_Logical_Exports within the size budget.

        Emission is gated on ``perorg_export_size_cap_bytes`` (emit only when the
        full dump is within the cap) and on a configured generator. The full dump
        remains the unconditional system-of-record either way (Req 31.2). Returns the
        list of per-org export storage keys emitted (one per org).
        """
        if scope not in _FILE_SCOPES or not org_ids:
            return []
        if self.per_org_export_fn is None:
            logger.info(
                "Per_Org_Logical_Export skipped: no generator wired (Req 31 — the "
                "full dump remains the system-of-record); generator lands in task 10."
            )
            return []

        config = await self._get_config()
        cap = config.perorg_export_size_cap_bytes if config else None
        if cap is None:
            logger.info(
                "Per_Org_Logical_Export skipped: no perorg_export_size_cap_bytes "
                "configured (Req 31.1 budget gate)."
            )
            return []
        if dump_byte_size > cap:
            logger.info(
                "Per_Org_Logical_Export skipped: dump %d bytes exceeds cap %d "
                "(Req 31.1 budget gate).",
                dump_byte_size,
                cap,
            )
            return []

        exports = await self.per_org_export_fn(self.db, org_ids, bdk)
        emitted: list[str] = []
        index_by_org = {e.org_id: e for e in per_org_index.entries}
        for org_id, plaintext in exports:
            ciphertext = backup_envelope_encrypt(plaintext, bdk)
            key = PER_ORG_EXPORT_KEY_TEMPLATE.format(backup_id=backup_id, org_id=org_id)
            await self._fanout_artifact(key, ciphertext)
            entry = index_by_org.get(org_id)
            if entry is not None:
                entry.logical_export_emitted = True
                entry.logical_export_location = key
            emitted.append(key)
        return emitted

    # -- step 8: fan-out ----------------------------------------------------

    async def _fanout_artifact(self, key: str, data: bytes) -> None:
        """Upload one artifact to the primary + every copy destination (Req 30.3).

        A primary write failure raises :class:`BackupPipelineError` (fails the job,
        Req 30.6). A copy write failure is recorded on that destination's
        :class:`CopyWriteResult`, surfaced, and notified, but does NOT fail the job
        (Req 30.5).
        """
        # Primary first — its failure fails the whole job.
        try:
            await self._primary.storage.upload(
                key,
                _bytes_stream(data),
                content_length=len(data),
                immutable_until=self._primary.immutable_until,
            )
        except Exception as exc:  # noqa: BLE001 - any provider failure fails the job
            self._copy_results[self._primary.destination.id].fail(str(exc))
            raise BackupPipelineError(
                f"Backup failed: writing {key!r} to the primary destination failed "
                f"({exc})."
            ) from exc

        for copy in self._copies:
            try:
                await copy.storage.upload(
                    key,
                    _bytes_stream(data),
                    content_length=len(data),
                    immutable_until=copy.immutable_until,
                )
            except Exception as exc:  # noqa: BLE001 - copy failure surfaced, not fatal
                self._copy_results[copy.destination.id].fail(
                    f"failed writing {key!r}: {exc}"
                )
                logger.warning(
                    "backup fan-out: copy destination %s failed writing %s: %s",
                    copy.destination.id,
                    key,
                    exc,
                )

    async def _mirror_blobs_to_copies(self, captured: Sequence[CapturedFile]) -> None:
        """Mirror each captured File_Blob from the primary to every copy destination.

        Capture already uploaded blobs to the primary; copies receive the identical
        encrypted blob bytes by streaming each one from the primary (Req 30.3). A
        per-copy mirror failure is recorded but does not fail the job (Req 30.5).
        """
        if not self._copies or not captured:
            return

        seen: set[str] = set()
        for cf in captured:
            storage_key = cf.blob_ref.storage_key
            if storage_key in seen:
                continue
            seen.add(storage_key)

            try:
                data = await _drain(self._primary.storage.download(storage_key))
            except Exception as exc:  # noqa: BLE001 - primary copy is intact; copies miss
                for copy in self._copies:
                    self._copy_results[copy.destination.id].fail(
                        f"could not read blob {storage_key!r} from primary to mirror: {exc}"
                    )
                logger.warning(
                    "backup fan-out: blob %s could not be read back from primary "
                    "for mirroring: %s",
                    storage_key,
                    exc,
                )
                continue

            for copy in self._copies:
                try:
                    await copy.storage.upload(
                        storage_key,
                        _bytes_stream(data),
                        content_length=len(data),
                        immutable_until=copy.immutable_until,
                    )
                except Exception as exc:  # noqa: BLE001 - copy failure surfaced, not fatal
                    self._copy_results[copy.destination.id].fail(
                        f"failed mirroring blob {storage_key!r}: {exc}"
                    )

    # -- step 9: re-assertion ----------------------------------------------

    async def _reassert_reused_blobs(
        self, captured: Sequence[CapturedFile], bdk: bytes
    ) -> None:
        """Re-assert that every reused (deduped) blob still exists at the primary.

        Before committing the manifest, a backup must never reference a blob that a
        concurrent prune deleted (Req 8.12). For each reused blob still missing at the
        primary, re-upload it from its source file; if the re-upload fails, fail the
        job rather than commit a dangling reference.
        """
        reused = {
            cf.blob_ref.storage_key: cf
            for cf in captured
            if cf.blob_ref.deduped
        }
        if not reused:
            return

        try:
            present = await self._primary.storage.list(self.blob_prefix)
        except Exception as exc:  # noqa: BLE001
            raise BackupPipelineError(
                f"Backup failed: could not verify reused blobs at the primary "
                f"destination before commit ({exc})."
            ) from exc
        present_keys = {obj.key for obj in present}

        for storage_key, cf in reused.items():
            if storage_key in present_keys:
                continue
            # A reused blob is missing at the destination — re-upload its ciphertext
            # from the source file, or fail (Req 8.12).
            try:
                plaintext = await asyncio.to_thread(_read_bytes, cf.path)
                ciphertext = await asyncio.to_thread(
                    backup_envelope_encrypt, plaintext, bdk
                )
                await self._primary.storage.upload(
                    storage_key,
                    _bytes_stream(ciphertext),
                    content_length=len(ciphertext),
                    immutable_until=self._primary.immutable_until,
                )
                logger.info(
                    "re-asserted reused blob %s by re-uploading to the primary",
                    storage_key,
                )
            except Exception as exc:  # noqa: BLE001
                raise BackupPipelineError(
                    f"Backup failed: a reused blob ({storage_key!r}) is missing at "
                    f"the primary destination and could not be re-uploaded ({exc})."
                ) from exc

    # -- step 9 (commit): catalog rows -------------------------------------

    async def _commit_catalog(
        self,
        *,
        backup_id: uuid.UUID,
        scope: str,
        key_version: int,
        dump_result: PgDumpResult,
        encrypted_dump: bytes,
        checksum: str,
        file_index,
        manifest_key: str,
        org_ids: Sequence[str],
        schema_version: str | None,
        bdk: bytes,
    ) -> Backup:
        """Insert the committed ``backups`` row + refcounts + destination copies.

        Catalog writes are deferred to commit time so a failed job never leaves a
        committed catalog row. Records ``consistency_level`` (Req 23.1) and the
        encrypted org-ID list (Req 7.8).
        """
        org_ids_encrypted = backup_envelope_encrypt(
            json.dumps(list(org_ids), separators=(",", ":")), bdk
        )

        backup = Backup(
            id=backup_id,
            created_at=self.clock(),
            scope=scope,
            app_version=self.app_version,
            schema_version=schema_version,
            key_version=key_version,
            dump_size_bytes=dump_result.byte_size,
            dump_checksum=checksum,
            file_count=file_index.file_count,
            file_bytes=file_index.total_bytes,
            consistency_level=CONSISTENCY_TRUE_TEMPORAL,
            manifest_key=manifest_key,
            prune_status="retained",
            org_ids_encrypted=org_ids_encrypted,
        )
        self.db.add(backup)
        await self.db.flush()

        # One blob_refcounts row per distinct Content_Hash referenced by this
        # backup's File_Index, so reference-counted pruning (Req 8.9) is exact.
        distinct_hashes = sorted({e.content_hash for e in file_index.entries})
        for content_hash in distinct_hashes:
            self.db.add(
                BlobRefcount(content_hash=content_hash, backup_id=backup_id)
            )

        # Per-destination copy rows with their write status (Req 30.5).
        for copy_result in self._copy_results.values():
            self.db.add(
                BackupDestinationCopy(
                    backup_id=backup_id,
                    destination_id=copy_result.destination_id,
                    write_status=copy_result.status,
                    immutable_until=copy_result.immutable_until,
                )
            )

        await self.db.flush()
        await self.db.refresh(backup)
        return backup

    # -- step 10: completion / failure -------------------------------------

    async def _complete(
        self,
        backup_id: uuid.UUID,
        actor_id: uuid.UUID | None,
        result: BackupPipelineResult,
    ) -> None:
        """Record success, write the completion audit, dispatch a success notify."""
        await self._mark_job_completed(backup_id, result)

        # Completion audit (Req 17.6/17.8): a completion-audit failure is logged and
        # left for async reconciliation rather than undoing a successful backup.
        try:
            await self._call_audit(
                phase="completion",
                action=AUDIT_ACTION_BACKUP,
                target_id=backup_id,
                actor_id=actor_id,
                scope=result.scope,
                outcome="succeeded",
            )
        except Exception as exc:  # noqa: BLE001 - never undo a successful backup
            logger.error(
                "backup %s succeeded but the completion audit failed; queued for "
                "reconciliation: %s",
                backup_id,
                exc,
            )

        # Surface copy-destination failures (Req 30.5) without failing the job.
        config = await self._get_config()
        if result.copy_failures:
            messages = "; ".join(
                f"{c.destination_id}: {', '.join(c.errors)}" for c in result.copy_failures
            )
            logger.warning("backup %s copy-destination write failures: %s", backup_id, messages)
            if config is None or config.notify_backup_failure:
                await self._call_notify(
                    event="backup.copy_failed",
                    success=False,
                    message=(
                        f"Backup {backup_id} completed on the primary but failed to "
                        f"write to one or more copy destinations: {messages}"
                    ),
                )

        if config is None or config.notify_backup_success:
            await self._call_notify(
                event="backup.success",
                success=True,
                message=(
                    f"Backup {backup_id} completed: scope={result.scope}, "
                    f"files={result.file_count}, consistency={result.consistency_level}."
                ),
            )

    async def _fail(self, backup_id: uuid.UUID, reason: str) -> None:
        """Mark the job failed and dispatch a failure notification (Req 5.7, 21.10)."""
        await self._mark_job_failed(reason)
        config = await self._get_config()
        if config is None or config.notify_backup_failure:
            await self._call_notify(
                event="backup.failure",
                success=False,
                message=f"Backup {backup_id} failed: {reason}",
            )

    # -- hook + job helpers -------------------------------------------------

    async def _call_audit(self, **kwargs: object) -> None:
        await _maybe_await(self.audit_hook(**kwargs))

    async def _call_notify(self, **kwargs: object) -> None:
        try:
            await _maybe_await(self.notify_hook(**kwargs))
        except Exception as exc:  # noqa: BLE001 - a failed notification is non-fatal
            logger.error("backup notification dispatch failed: %s", exc)

    async def _get_config(self) -> BackupConfig | None:
        if self._config is None:
            result = await self.db.execute(select(BackupConfig).limit(1))
            self._config = result.scalar_one_or_none()
        return self._config

    async def _read_dump(self, dump_path: str) -> bytes:
        try:
            # Offload the (potentially large) synchronous read to a worker thread
            # so the event loop stays responsive to other requests during a backup.
            return await asyncio.to_thread(_read_bytes, dump_path)
        except OSError as exc:
            raise BackupPipelineError(
                f"Backup failed: the database dump file could not be read ({exc})."
            ) from exc

    async def _read_schema_version(self) -> str | None:
        """Read the current Alembic revision for the schema-compat record (Req 7.1)."""
        try:
            result = await self.db.execute(text("SELECT version_num FROM alembic_version"))
            row = result.first()
            return str(row[0]) if row else None
        except Exception as exc:  # noqa: BLE001 - best-effort; restore still has the dump
            logger.debug("could not read alembic_version: %s", exc)
            return None

    async def _commit_job_state(self, **fields) -> None:
        """Persist job-state fields in an INDEPENDENT, immediately-committed
        transaction so concurrent status polls see progress live.

        The whole backup runs inside a single transaction on ``self.db`` (the
        backup data must commit atomically), which means anything written to
        ``self.db`` is invisible to other connections until the very end. Job
        progress is advisory, not part of that atomic data set, so we write it on
        a separate short-lived session that commits right away — and we never
        touch the job row through ``self.db`` (so ``self.db`` never locks it,
        avoiding a deadlock with these independent writes).
        """
        if self._job is None:
            return
        job_id = self._job.id
        model = type(self._job)
        try:
            async with async_session_factory() as s:
                async with s.begin():
                    row = (
                        await s.execute(select(model).where(model.id == job_id))
                    ).scalars().first()
                    if row is not None:
                        for key, value in fields.items():
                            setattr(row, key, value)
        except Exception:  # noqa: BLE001 - progress is best-effort, never fatal
            logger.debug("could not persist live job progress", exc_info=True)

    async def _progress(self, pct: int, note: str) -> None:
        if self._job is None:
            return
        now = self.clock()
        await self._commit_job_state(
            progress_pct=pct, last_progress_at=now, last_heartbeat_at=now
        )

    async def _mark_job_running(self, scope: str, triggered_by: str) -> None:
        if self._job is None:
            return
        now = self.clock()
        # Commit independently so a polling client immediately sees the job leave
        # 'queued' and start advancing. NOT written through self.db (see
        # _commit_job_state) to avoid locking the row for the whole run.
        await self._commit_job_state(
            status="running",
            scope=scope,
            triggered_by=triggered_by,
            started_at=now,
            last_heartbeat_at=now,
            last_progress_at=now,
            progress_pct=5,
        )

    async def _mark_job_completed(
        self, backup_id: uuid.UUID, result: BackupPipelineResult
    ) -> None:
        if self._job is None:
            return
        now = self.clock()
        self._job.status = "completed"
        self._job.finished_at = now
        self._job.last_heartbeat_at = now
        self._job.progress_pct = 100
        self._job.backup_id = backup_id
        self._job.skipped_file_count = result.skipped_file_count
        self._job.outcome_summary = (
            f"scope={result.scope}, files={result.file_count}, "
            f"file_bytes={result.file_bytes}, dump_bytes={result.dump_size_bytes}, "
            f"consistency={result.consistency_level}, "
            f"copies_failed={len(result.copy_failures)}"
        )
        await self.db.flush()
        await self.db.refresh(self._job)

    async def _mark_job_failed(self, reason: str) -> None:
        if self._job is None:
            return
        now = self.clock()
        self._job.status = "failed"
        self._job.finished_at = now
        self._job.last_heartbeat_at = now
        self._job.error_message = reason
        await self.db.flush()
        await self.db.refresh(self._job)


# ---------------------------------------------------------------------------
# Module-level convenience entry point
# ---------------------------------------------------------------------------


async def run_backup(
    db: AsyncSession,
    *,
    scope: str,
    triggered_by: str = "manual",
    actor_id: uuid.UUID | None = None,
    job: BackupJob | None = None,
    destinations: Sequence[DestinationTarget] | None = None,
    **kwargs: object,
) -> BackupPipelineResult:
    """Construct a :class:`BackupPipeline` and run one Full_Backup for ``scope``."""
    pipeline = BackupPipeline(db, destinations=destinations, **kwargs)  # type: ignore[arg-type]
    return await pipeline.run(
        scope=scope, triggered_by=triggered_by, actor_id=actor_id, job=job
    )


async def _maybe_await(value: Awaitable[None] | None) -> None:
    """Await ``value`` when it is awaitable; tolerate sync hooks returning ``None``."""
    if value is not None and hasattr(value, "__await__"):
        await value


def _safe_unlink(path: str) -> None:
    """Best-effort removal of the local plaintext dump file; never raises."""
    try:
        os.unlink(path)
    except OSError:
        logger.debug("could not remove dump file %s", path, exc_info=True)
