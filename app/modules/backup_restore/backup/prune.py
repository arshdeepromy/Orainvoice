"""Retention, reference-counted pruning, and mark-and-sweep GC (Req 8).

This module implements the *retention* half of Requirement 8, the
mark-and-sweep orphan GC of Req 8.10, **and** the prune/GC concurrency lock,
commit-time re-assertion, and RPO/RTO validation of Req 8.11–8.13 / 25.2 (task
7.5 — see "Prune/GC concurrency, commit-time re-assertion, and RPO validation"
near the end of this module). Three things happen here:

* **Retention by age / count (Req 8.5, 8.6).** A committed Full_Backup is
  selected for pruning when its age exceeds the configured ``retention_days`` OR
  when it falls outside the newest ``retention_count`` backups. For each selected
  backup the Backup_System deletes that backup's **database dump** and its
  **File_Index** (the manifest carries the File_Index, so deleting the manifest
  object removes the File_Index) from the destination, removes that backup's
  ``blob_refcounts`` rows, and marks the catalog row ``pruned``.

* **Reference-counted File_Blob pruning (Req 8.9).** A content-addressed
  File_Blob is deleted **only when no retained backup's File_Index references its
  ``Content_Hash``** — i.e. only when no ``blob_refcounts`` row for that
  ``content_hash`` remains after the pruned backups' rows are removed. A blob
  still referenced by at least one retained backup is never deleted or orphaned.

* **Failure handling (Req 8.7).** IF deleting a backup's artifacts from the
  destination fails, the catalog row is **kept**, marked ``prune_failed``, the
  failure is logged, and the backup is retried on the next prune cycle — its
  ``blob_refcounts`` rows are left intact so none of its blobs can be pruned
  while the backup itself still (partially) exists at the destination.

* **Mark-and-sweep orphan GC (Req 8.10).** Independently of reference-counted
  pruning, :meth:`BlobPruner.sweep_orphans` enumerates the File_Blobs stored at
  the destination (via ``StorageInterface.list(prefix=blob_prefix)``) and
  reclaims **Orphan_Blobs** — blobs referenced by no committed Full_Backup
  File_Index, i.e. a ``backup_blobs`` dedup-index row that no ``blob_refcounts``
  row references (typically left by a backup that uploaded blobs but failed
  before writing its manifest, so it is invisible to reference-counted pruning).
  An Orphan_Blob is deleted **only after it has been continuously unreferenced
  for the configured safety grace period** (``BackupConfig.orphan_gc_grace_hours``,
  default 24 h), measured from the blob's ``last_referenced_at`` — the last time
  any backup touched/referenced it (equal to ``first_seen_at`` for a blob that
  was never referenced). The ``backup_blobs`` dedup index is the platform's
  authoritative record of every blob it uploaded, so a destination object with
  **no** matching index row is treated as *untracked* (foreign / not platform
  written): it is observed and logged but never deleted, since the GC only
  reclaims blobs it can positively identify as its own orphans.

Per the project ``get_db_session`` ``session.begin()`` auto-commit pattern, DB
writes use ``flush()`` / ``await db.refresh()`` and never ``commit()``. Storage
deletes go through the provider-agnostic :class:`StorageInterface`, so retention
behaves identically across Google Drive, OneDrive, S3-compatible, and NAS
destinations.
"""

from __future__ import annotations

import contextlib
import logging
import secrets
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.backup_restore.backup.cas import DEFAULT_BLOB_PREFIX
from app.modules.backup_restore.models import (
    Backup,
    BackupBlob,
    BackupConfig,
    BlobRefcount,
)
from app.modules.backup_restore.storage.interface import StorageInterface

logger = logging.getLogger(__name__)

# prune_status values (mirror models.PRUNE_STATUSES).
PRUNE_RETAINED = "retained"
PRUNE_FAILED = "prune_failed"
PRUNE_PRUNED = "pruned"

# Storage-key convention for a backup's encrypted database dump. Matches the
# logical-key example documented on ``StorageInterface`` (``backups/<id>/dump.enc``).
DUMP_KEY_TEMPLATE = "backups/{backup_id}/dump.enc"


def dump_storage_key(backup_id: uuid.UUID | str) -> str:
    """Provider-independent storage key for a backup's encrypted dump."""
    return DUMP_KEY_TEMPLATE.format(backup_id=backup_id)


def blob_storage_key(blob_name: str, *, prefix: str = DEFAULT_BLOB_PREFIX) -> str:
    """Provider-independent storage key a content-addressed blob is stored at.

    Mirrors :meth:`backup.cas.FileBlobStore.storage_key` so prune deletes the
    exact object the CAS wrote.
    """
    return f"{prefix.rstrip('/')}/{blob_name}"


def _aware(dt: datetime) -> datetime:
    """Coerce a possibly-naive datetime to an aware UTC datetime."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass
class PruneOutcome:
    """Structured result of a retention prune run (for the service/API layer)."""

    pruned_backup_ids: list[uuid.UUID] = field(default_factory=list)
    """Backups whose dump + File_Index were deleted and marked ``pruned``."""

    failed_backup_ids: list[uuid.UUID] = field(default_factory=list)
    """Backups whose artifact deletion failed; marked ``prune_failed`` (Req 8.7)."""

    deleted_blob_hashes: list[str] = field(default_factory=list)
    """File_Blobs deleted because no retained File_Index referenced them (Req 8.9)."""

    retained_blob_hashes: list[str] = field(default_factory=list)
    """Candidate blobs kept because a retained File_Index still references them."""

    failed_blob_hashes: list[str] = field(default_factory=list)
    """Blobs whose destination deletion failed (left for orphan GC to reclaim)."""


@dataclass
class OrphanSweepOutcome:
    """Structured result of a mark-and-sweep orphan GC run (Req 8.10)."""

    deleted_orphan_hashes: list[str] = field(default_factory=list)
    """Orphan_Blobs deleted because they were unreferenced past the grace period."""

    retained_orphan_hashes: list[str] = field(default_factory=list)
    """Unreferenced blobs kept because they are still within the grace period."""

    failed_orphan_hashes: list[str] = field(default_factory=list)
    """Orphan_Blobs whose destination deletion failed; retried next cycle."""

    untracked_object_keys: list[str] = field(default_factory=list)
    """Destination objects with no dedup-index row — observed/logged, not deleted."""


def select_backups_to_prune(
    backups: Iterable[Backup],
    *,
    retention_count: int | None,
    retention_days: int | None,
    now: datetime | None = None,
) -> list[Backup]:
    """Select the backups that exceed the retention policy (Req 8.5, 8.6).

    A backup is selected when:

    * it is currently ``prune_failed`` (a previous cycle failed to delete it, so
      it is always retried, Req 8.7); OR
    * counting only not-yet-pruned backups newest-first, its position is at or
      beyond ``retention_count`` (count limit exceeded, Req 8.6); OR
    * its age exceeds ``retention_days`` (retention period exceeded, Req 8.5).

    Already-``pruned`` backups are ignored. When neither ``retention_count`` nor
    ``retention_days`` is configured, only ``prune_failed`` retries are selected.
    """
    now = _aware(now) if now is not None else datetime.now(timezone.utc)

    considered = [b for b in backups if b.prune_status != PRUNE_PRUNED]
    # Newest first so index N.. are the oldest beyond the keep-count.
    considered.sort(key=lambda b: _aware(b.created_at), reverse=True)

    selected: list[Backup] = []
    for index, backup in enumerate(considered):
        if _should_prune(backup, index, retention_count, retention_days, now):
            selected.append(backup)
    return selected


def _should_prune(
    backup: Backup,
    index: int,
    retention_count: int | None,
    retention_days: int | None,
    now: datetime,
) -> bool:
    """Decide whether a single backup (at newest-first ``index``) is pruned."""
    # Always retry a previously failed prune (Req 8.7).
    if backup.prune_status == PRUNE_FAILED:
        return True
    # Count limit (Req 8.6): keep the newest ``retention_count`` backups.
    if retention_count is not None and index >= retention_count:
        return True
    # Age limit (Req 8.5): older than the retention period.
    if retention_days is not None:
        if now - _aware(backup.created_at) > timedelta(days=retention_days):
            return True
    return False


class BlobPruner:
    """Applies age/count retention and reference-counted blob pruning (Req 8.5–8.9).

    The pruner deletes each expired backup's dump + File_Index through the
    provider-agnostic :class:`StorageInterface`, removes the backup's
    ``blob_refcounts`` rows, then deletes any File_Blob no retained File_Index
    still references. A backup whose artifact deletion fails is left in place and
    marked ``prune_failed`` for retry (Req 8.7).
    """

    def __init__(
        self,
        db: AsyncSession,
        storage: StorageInterface,
        *,
        blob_prefix: str = DEFAULT_BLOB_PREFIX,
    ) -> None:
        self.db = db
        self.storage = storage
        self.blob_prefix = blob_prefix

    async def prune(
        self, config: BackupConfig, *, now: datetime | None = None
    ) -> PruneOutcome:
        """Run one retention prune cycle and return its :class:`PruneOutcome`."""
        now = _aware(now) if now is not None else datetime.now(timezone.utc)
        outcome = PruneOutcome()

        candidates = await self._load_prunable_backups()
        to_prune = select_backups_to_prune(
            candidates,
            retention_count=config.retention_count,
            retention_days=config.retention_days,
            now=now,
        )

        # Hashes whose references were removed this cycle — the only blobs that
        # could now be unreferenced and therefore prunable (Req 8.9).
        candidate_hashes: set[str] = set()

        for backup in to_prune:
            referenced = await self._referenced_hashes(backup.id)
            if not await self._delete_backup_artifacts(backup):
                # Deletion failed: keep the record, mark prune_failed, retry next
                # cycle, and leave its refcounts intact so its blobs stay
                # protected (Req 8.7).
                backup.prune_status = PRUNE_FAILED
                await self.db.flush()
                await self.db.refresh(backup)
                outcome.failed_backup_ids.append(backup.id)
                continue

            await self._remove_refcounts(backup.id)
            backup.prune_status = PRUNE_PRUNED
            await self.db.flush()
            await self.db.refresh(backup)
            outcome.pruned_backup_ids.append(backup.id)
            candidate_hashes.update(referenced)

        # Reference-counted File_Blob pruning (Req 8.9): delete a blob only when
        # no retained backup's File_Index still references its Content_Hash.
        for content_hash in sorted(candidate_hashes):
            if await self._is_referenced(content_hash):
                outcome.retained_blob_hashes.append(content_hash)
                continue
            if await self._delete_blob(content_hash):
                outcome.deleted_blob_hashes.append(content_hash)
            else:
                outcome.failed_blob_hashes.append(content_hash)

        return outcome

    async def delete_specific(
        self, backup_ids: Iterable[uuid.UUID]
    ) -> PruneOutcome:
        """Delete an explicit set of backups + their now-unreferenced blobs.

        Used by the operator-initiated "delete backup(s)" flow (gated behind a
        verification code). Reuses the exact reference-counted deletion the
        retention pruner uses: for each backup it deletes the dump + manifest
        (File_Index) from the destination, removes its ``blob_refcounts`` rows,
        and marks it ``pruned``; then any File_Blob no retained backup still
        references is deleted from the destination. A backup whose artifact
        delete fails is marked ``prune_failed`` and reported, leaving its
        refcounts intact so its blobs stay protected (Req 8.7/8.9).
        """
        wanted = list(dict.fromkeys(backup_ids))
        outcome = PruneOutcome()
        if not wanted:
            return outcome

        result = await self.db.execute(
            select(Backup).where(
                Backup.id.in_(wanted), Backup.prune_status != PRUNE_PRUNED
            )
        )
        to_delete = list(result.scalars().all())

        candidate_hashes: set[str] = set()
        for backup in to_delete:
            referenced = await self._referenced_hashes(backup.id)
            if not await self._delete_backup_artifacts(backup):
                backup.prune_status = PRUNE_FAILED
                await self.db.flush()
                await self.db.refresh(backup)
                outcome.failed_backup_ids.append(backup.id)
                continue
            await self._remove_refcounts(backup.id)
            backup.prune_status = PRUNE_PRUNED
            await self.db.flush()
            await self.db.refresh(backup)
            outcome.pruned_backup_ids.append(backup.id)
            candidate_hashes.update(referenced)

        for content_hash in sorted(candidate_hashes):
            if await self._is_referenced(content_hash):
                outcome.retained_blob_hashes.append(content_hash)
                continue
            if await self._delete_blob(content_hash):
                outcome.deleted_blob_hashes.append(content_hash)
            else:
                outcome.failed_blob_hashes.append(content_hash)

        return outcome

    async def sweep_orphans(
        self, config: BackupConfig, *, now: datetime | None = None
    ) -> OrphanSweepOutcome:
        """Run one mark-and-sweep orphan GC cycle and return its outcome (Req 8.10).

        Enumerates the File_Blobs stored at the destination, identifies each
        Orphan_Blob — a ``backup_blobs`` dedup-index row referenced by no
        committed File_Index (no ``blob_refcounts`` row) — and deletes it only
        after it has been continuously unreferenced for the configured grace
        period (``orphan_gc_grace_hours``). Destination objects with no matching
        index row are *untracked* (foreign / not platform written): they are
        observed and logged but never deleted.
        """
        now = _aware(now) if now is not None else datetime.now(timezone.utc)
        grace = timedelta(hours=config.orphan_gc_grace_hours)
        outcome = OrphanSweepOutcome()

        # Enumerate destination blobs (Req 8.10). The stored object key maps back
        # to the blob name via the CAS naming convention, so strip the prefix to
        # recover each present blob_name.
        present_names = await self._list_destination_blob_names()

        # Orphan candidates: dedup-index rows referenced by no committed
        # File_Index. These are invisible to reference-counted pruning (Req 8.9),
        # which only ever inspects the hashes of pruned backups.
        unreferenced = await self._unreferenced_blobs()

        # Every blob_name the dedup index knows about (referenced or not). A
        # destination object whose name is absent here is untracked.
        known_names = await self._all_blob_names()

        # Destination objects we have no dedup-index row for are not blobs this
        # platform is known to have written; never delete what we can't identify.
        for name in sorted(present_names - known_names):
            key = blob_storage_key(name, prefix=self.blob_prefix)
            logger.info("orphan GC: observed untracked destination object %s", key)
            outcome.untracked_object_keys.append(key)

        for blob in unreferenced:
            if blob.blob_name not in present_names:
                # The dedup-index row is stale — the object is already gone from
                # the destination. Reclaim the row once it is past the grace
                # period so the index does not grow without bound.
                if self._unreferenced_for(blob, now) >= grace:
                    await self.db.delete(blob)
                    await self.db.flush()
                    outcome.deleted_orphan_hashes.append(blob.content_hash)
                else:
                    outcome.retained_orphan_hashes.append(blob.content_hash)
                continue

            # Present at the destination: delete only after the blob has been
            # continuously unreferenced for at least the grace period (Req 8.10).
            if self._unreferenced_for(blob, now) < grace:
                outcome.retained_orphan_hashes.append(blob.content_hash)
                continue

            if await self._delete_orphan(blob):
                outcome.deleted_orphan_hashes.append(blob.content_hash)
            else:
                outcome.failed_orphan_hashes.append(blob.content_hash)

        return outcome

    @staticmethod
    def _unreferenced_for(blob: BackupBlob, now: datetime) -> timedelta:
        """How long ``blob`` has been continuously unreferenced.

        Measured from ``last_referenced_at`` — the last time any backup
        touched/referenced the blob (equal to ``first_seen_at`` for a blob that
        was never referenced, e.g. one left by a backup that uploaded it but
        failed before committing its manifest).
        """
        return now - _aware(blob.last_referenced_at)

    async def _delete_backup_artifacts(self, backup: Backup) -> bool:
        """Delete a backup's dump + File_Index (manifest) from the destination.

        Returns ``True`` only when every artifact was deleted successfully; a
        single failure returns ``False`` so the caller marks the backup
        ``prune_failed`` (Req 8.7).
        """
        keys = [dump_storage_key(backup.id)]
        if backup.manifest_key:
            keys.append(backup.manifest_key)

        for key in keys:
            try:
                await self.storage.delete(key)
            except Exception:  # noqa: BLE001 - any provider failure is retried
                logger.exception(
                    "prune: failed to delete artifact %s for backup %s",
                    key,
                    backup.id,
                )
                return False
        return True

    async def _delete_blob(self, content_hash: str) -> bool:
        """Delete a content-addressed blob from the destination + dedup index.

        Returns ``True`` on success (or when the blob row is already gone), and
        ``False`` when the destination delete fails — in which case the
        ``backup_blobs`` row is left intact so the mark-and-sweep orphan GC
        (task 7.3) can reclaim it once it is continuously unreferenced.
        """
        blob = await self._load_blob(content_hash)
        if blob is None:
            return True

        key = blob_storage_key(blob.blob_name, prefix=self.blob_prefix)
        try:
            await self.storage.delete(key)
        except Exception:  # noqa: BLE001 - leave the row for orphan GC to reclaim
            logger.exception(
                "prune: failed to delete File_Blob %s (%s)", content_hash, key
            )
            return False

        await self.db.delete(blob)
        await self.db.flush()
        return True

    async def _delete_orphan(self, blob: BackupBlob) -> bool:
        """Delete an Orphan_Blob's destination object + dedup-index row (Req 8.10).

        Returns ``True`` on success; ``False`` when the destination delete fails,
        in which case the ``backup_blobs`` row is left intact so the next GC
        cycle retries it (the blob remains an orphan until reclaimed).
        """
        key = blob_storage_key(blob.blob_name, prefix=self.blob_prefix)
        try:
            await self.storage.delete(key)
        except Exception:  # noqa: BLE001 - retry on the next GC cycle
            logger.exception(
                "orphan GC: failed to delete Orphan_Blob %s (%s)",
                blob.content_hash,
                key,
            )
            return False

        await self.db.delete(blob)
        await self.db.flush()
        return True

    # -- DB access (thin query wrappers) ------------------------------------

    async def _load_prunable_backups(self) -> list[Backup]:
        """All not-yet-``pruned`` catalog rows (retention candidates)."""
        result = await self.db.execute(
            select(Backup).where(Backup.prune_status != PRUNE_PRUNED)
        )
        return list(result.scalars().all())

    async def _referenced_hashes(self, backup_id: uuid.UUID) -> set[str]:
        """Content_Hashes referenced by a backup's File_Index (its refcount rows)."""
        result = await self.db.execute(
            select(BlobRefcount.content_hash).where(
                BlobRefcount.backup_id == backup_id
            )
        )
        return set(result.scalars().all())

    async def _remove_refcounts(self, backup_id: uuid.UUID) -> None:
        """Remove a pruned backup's ``blob_refcounts`` rows."""
        await self.db.execute(
            sa_delete(BlobRefcount).where(BlobRefcount.backup_id == backup_id)
        )
        await self.db.flush()

    async def _is_referenced(self, content_hash: str) -> bool:
        """True when any remaining ``blob_refcounts`` row references ``content_hash``."""
        result = await self.db.execute(
            select(BlobRefcount.backup_id)
            .where(BlobRefcount.content_hash == content_hash)
            .limit(1)
        )
        return result.first() is not None

    async def _load_blob(self, content_hash: str) -> BackupBlob | None:
        """Load the ``backup_blobs`` dedup-index row for a Content_Hash."""
        return await self.db.get(BackupBlob, content_hash)

    async def reassert_reused_hashes(
        self, content_hashes: Iterable[str]
    ) -> ReassertionResult:
        """Commit-time re-assertion that reused blobs still exist (Req 8.12).

        Given the Content_Hashes a committing Backup_Job *reused* under the
        dedup rule (Req 21.3, "upload only if absent") rather than re-uploading,
        load each blob's dedup-index row, resolve its destination key, and
        verify the object is still present at the destination. Returns a
        :class:`ReassertionResult` partitioning the hashes into present/missing
        so the pipeline can re-upload (or fail the job, Req 8.12) any blob a
        concurrent prune/GC removed between dedup-skip and commit.

        A hash with no dedup-index row is reported as missing — the platform has
        no record of having stored it, so it cannot be safely treated as present.
        """
        wanted = list(dict.fromkeys(content_hashes))  # de-dupe, preserve order
        if not wanted:
            return ReassertionResult(present_hashes=[], missing_hashes=[])

        blobs: list[BackupBlob] = []
        missing_hashes: list[str] = []
        for content_hash in wanted:
            blob = await self._load_blob(content_hash)
            if blob is None:
                # No index row → cannot positively confirm presence (Req 8.12).
                missing_hashes.append(content_hash)
            else:
                blobs.append(blob)

        result = await reassert_blobs_present(
            self.storage, blobs, blob_prefix=self.blob_prefix
        )
        # Fold the no-index-row hashes into the missing set.
        return ReassertionResult(
            present_hashes=result.present_hashes,
            missing_hashes=result.missing_hashes + missing_hashes,
        )

    async def _list_destination_blob_names(self) -> set[str]:
        """Enumerate destination blobs and recover their blob names (Req 8.10).

        Lists every object under the blob prefix via the provider-agnostic
        :class:`StorageInterface` and strips the prefix to recover each stored
        blob's name (the CAS stores a blob at ``<prefix>/<blob_name>``).
        """
        objects = await self.storage.list(self.blob_prefix)
        return {obj.key.rsplit("/", 1)[-1] for obj in objects}

    async def _unreferenced_blobs(self) -> list[BackupBlob]:
        """Dedup-index rows referenced by no committed File_Index (orphan candidates).

        A ``backup_blobs`` row is unreferenced when no ``blob_refcounts`` row maps
        to its ``content_hash`` — exactly the blobs reference-counted pruning
        (Req 8.9) can never see, so mark-and-sweep reclaims them (Req 8.10).
        """
        referenced = (
            select(BlobRefcount.content_hash)
            .where(BlobRefcount.content_hash == BackupBlob.content_hash)
            .exists()
        )
        result = await self.db.execute(select(BackupBlob).where(~referenced))
        return list(result.scalars().all())

    async def _all_blob_names(self) -> set[str]:
        """Every ``blob_name`` recorded in the dedup index (Req 8.10).

        Used to tell platform-written blobs (which always have an index row)
        apart from untracked/foreign destination objects.
        """
        result = await self.db.execute(select(BackupBlob.blob_name))
        return set(result.scalars().all())


async def run_retention_prune(
    db: AsyncSession,
    storage: StorageInterface,
    config: BackupConfig,
    *,
    now: datetime | None = None,
    blob_prefix: str = DEFAULT_BLOB_PREFIX,
    destinations: str | Iterable[str] | None = None,
    lock_backend: "PruneGcLockBackend | None" = None,
) -> PruneOutcome:
    """Convenience entry point: run a single retention prune cycle (Req 8.5–8.9).

    When ``destinations`` is given, the cycle runs under the per-destination
    prune/GC mutual-exclusion lock (Req 8.11) and is **skipped** (returns an
    empty :class:`PruneOutcome`) if a Backup_Job currently holds the lock — so a
    prune can never race a concurrent backup into deleting a reused blob.
    """
    pruner = BlobPruner(db, storage, blob_prefix=blob_prefix)
    if destinations is None:
        return await pruner.prune(config, now=now)
    async with prune_gc_lock(destinations, backend=lock_backend) as acquired:
        if not acquired:
            return PruneOutcome()
        return await pruner.prune(config, now=now)


async def run_orphan_gc(
    db: AsyncSession,
    storage: StorageInterface,
    config: BackupConfig,
    *,
    now: datetime | None = None,
    blob_prefix: str = DEFAULT_BLOB_PREFIX,
    destinations: str | Iterable[str] | None = None,
    lock_backend: "PruneGcLockBackend | None" = None,
) -> OrphanSweepOutcome:
    """Convenience entry point: run one mark-and-sweep orphan GC cycle (Req 8.10).

    When ``destinations`` is given, the sweep runs under the per-destination
    prune/GC mutual-exclusion lock (Req 8.11) and is **skipped** (returns an
    empty :class:`OrphanSweepOutcome`) if a Backup_Job currently holds the lock.
    """
    pruner = BlobPruner(db, storage, blob_prefix=blob_prefix)
    if destinations is None:
        return await pruner.sweep_orphans(config, now=now)
    async with prune_gc_lock(destinations, backend=lock_backend) as acquired:
        if not acquired:
            return OrphanSweepOutcome()
        return await pruner.sweep_orphans(config, now=now)


# ===========================================================================
# Prune/GC concurrency, commit-time re-assertion, and RPO validation (task 7.5)
# ===========================================================================
#
# These three guards close the dedup-vs-prune race described in the Req 8
# design decision: "upload only if absent" (Req 21.3) makes a blob skip its
# upload precisely when it already exists — exactly when a naive concurrent
# prune could delete it. Defence in depth:
#
#   1. Per-destination mutual-exclusion lock (Req 8.11) — prune/GC never runs
#      concurrently with an in-progress Backup_Job for the same destination set.
#   2. Commit-time re-assertion (Req 8.12) — before a Backup_Job commits its
#      manifest, every *reused* blob is re-verified present at the destination.
#   3. RPO validation (Req 8.13, 25.2) — saving the schedule/retention warns
#      when the inter-backup interval exceeds the configured RPO.


# ---------------------------------------------------------------------------
# 1. Per-destination prune/GC mutual-exclusion lock (Req 8.11)
# ---------------------------------------------------------------------------

# Redis key convention for the per-destination prune/GC lock. The same key is
# acquired by an in-progress Backup_Job (pipeline) and by a prune/GC run, so the
# two are mutually excluded for a given destination (mirrors the codebase's
# ``scheduler:loop_lock`` SET NX EX pattern, e.g. app/tasks/scheduled.py).
PRUNE_LOCK_KEY_TEMPLATE = "backup:prune_lock:{destination}"

# Default lock TTL. Must exceed a prune/GC cycle (or be renewed). A held lock
# self-expires after this many seconds so a crashed holder never wedges
# backups/prunes permanently — the same fail-safe the scheduler lock relies on.
DEFAULT_PRUNE_LOCK_TTL = 900  # 15 minutes


def destination_lock_key(destination: str) -> str:
    """Redis key for a destination's prune/GC mutual-exclusion lock (Req 8.11)."""
    return PRUNE_LOCK_KEY_TEMPLATE.format(destination=destination)


class PruneGcLockBackend:
    """Abstract backend for the per-destination prune/GC lock (Req 8.11).

    Implementations provide a single-attempt ``try_acquire`` (atomic
    test-and-set with a TTL), a token-checked ``release``, and an optional
    ``renew`` for long-running holders. The default :class:`RedisPruneGcLockBackend`
    is Redis-backed; tests can substitute an in-memory backend so the locking
    logic is exercised without a live Redis.
    """

    async def try_acquire(self, key: str, token: str, ttl_seconds: int) -> bool:
        raise NotImplementedError

    async def release(self, key: str, token: str) -> None:
        raise NotImplementedError

    async def renew(self, key: str, token: str, ttl_seconds: int) -> bool:
        """Extend a held lock's TTL. Default: best-effort re-acquire semantics."""
        raise NotImplementedError


class RedisPruneGcLockBackend(PruneGcLockBackend):
    """Redis ``SET NX EX`` prune/GC lock backend (the default, Req 8.11).

    Follows the cluster-wide ``SET key token NX EX ttl`` lock pattern used by
    the scheduler loop lock and the HA auto-promote lock: a single atomic
    acquire, a token-checked release (so a holder never deletes a lock another
    worker re-acquired after our TTL lapsed), and a token-checked renew.
    """

    def __init__(self, redis=None) -> None:
        # Lazily fall back to the shared pool so importing this module never
        # requires Redis (e.g. unit tests that inject an in-memory backend).
        self._redis = redis

    @property
    def redis(self):
        if self._redis is None:
            from app.core.redis import redis_pool

            self._redis = redis_pool
        return self._redis

    async def try_acquire(self, key: str, token: str, ttl_seconds: int) -> bool:
        return bool(
            await self.redis.set(key, token, nx=True, ex=ttl_seconds)
        )

    async def release(self, key: str, token: str) -> None:
        try:
            stored = await self.redis.get(key)
        except Exception as exc:  # noqa: BLE001 - release is best-effort
            logger.warning("prune lock release: GET failed for %s: %s", key, exc)
            return
        if stored is None:
            return
        if isinstance(stored, bytes):
            stored = stored.decode("utf-8", errors="ignore")
        if stored == token:
            try:
                await self.redis.delete(key)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "prune lock release: DELETE failed for %s: %s", key, exc
                )

    async def renew(self, key: str, token: str, ttl_seconds: int) -> bool:
        try:
            stored = await self.redis.get(key)
            if stored is None:
                # Lock lapsed — re-claim it only if still free.
                return bool(
                    await self.redis.set(key, token, nx=True, ex=ttl_seconds)
                )
            if isinstance(stored, bytes):
                stored = stored.decode("utf-8", errors="ignore")
            if stored != token:
                return False
            await self.redis.expire(key, ttl_seconds)
            return True
        except Exception as exc:  # noqa: BLE001 - renewal is best-effort
            logger.warning("prune lock renew failed for %s: %s", key, exc)
            return False


def _normalise_destinations(destinations: str | Iterable[str]) -> list[str]:
    """Normalise a destination or destination set into a sorted, de-duped list.

    Locks are acquired in a stable (sorted) order so two callers contending for
    the same multi-destination set can never deadlock by grabbing the locks in
    opposite orders.
    """
    if isinstance(destinations, str):
        items = [destinations]
    else:
        items = list(destinations)
    return sorted({d for d in items if d})


@contextlib.asynccontextmanager
async def prune_gc_lock(
    destinations: str | Iterable[str],
    *,
    backend: PruneGcLockBackend | None = None,
    ttl_seconds: int = DEFAULT_PRUNE_LOCK_TTL,
    wait_timeout: float = 0.0,
    poll_interval: float = 0.5,
):
    """Per-destination prune/GC mutual-exclusion lock (Req 8.11).

    Acquires the lock for **every** destination in ``destinations`` (in a stable
    sorted order to avoid deadlock). Yields ``True`` only when the entire set was
    acquired, and ``False`` otherwise — a prune/GC caller MUST skip its run when
    this yields ``False`` (a Backup_Job holds the lock; deleting now could race
    a blob the in-progress backup will reuse). On exit every acquired lock is
    released, token-checked, so a self-expired-then-retaken lock is never
    clobbered.

    ``wait_timeout`` controls how long to keep retrying acquisition before
    giving up (default ``0.0`` = a single non-blocking attempt, the right
    posture for an opportunistic prune/GC cycle). The Backup_Job pipeline can
    pass a larger ``wait_timeout`` so a backup waits for an in-flight prune
    rather than skipping.

    Mirrors the SET NX EX lock pattern already used across the codebase
    (``scheduler:loop_lock``, HA auto-promote, PPSR ``redis_lock``).
    """
    import asyncio

    backend = backend or RedisPruneGcLockBackend()
    keys = [destination_lock_key(d) for d in _normalise_destinations(destinations)]
    token = secrets.token_hex(16)
    acquired_keys: list[str] = []
    deadline = asyncio.get_event_loop().time() + wait_timeout

    async def _release_all() -> None:
        for key in acquired_keys:
            await backend.release(key, token)
        acquired_keys.clear()

    try:
        all_acquired = True
        for key in keys:
            got = False
            while True:
                try:
                    got = await backend.try_acquire(key, token, ttl_seconds)
                except Exception as exc:  # noqa: BLE001 - treat as contended
                    logger.warning(
                        "prune lock acquire failed for %s: %s", key, exc
                    )
                    got = False
                if got:
                    acquired_keys.append(key)
                    break
                if asyncio.get_event_loop().time() >= deadline:
                    break
                await asyncio.sleep(poll_interval)
            if not got:
                all_acquired = False
                break

        if not all_acquired:
            # Could not lock the whole destination set — release partial holds
            # and signal the caller to skip (mutual exclusion, Req 8.11).
            await _release_all()
            logger.info(
                "prune/GC lock not acquired for %s — a backup is in progress; "
                "skipping this cycle",
                keys,
            )
            yield False
            return

        yield True
    finally:
        await _release_all()


# ---------------------------------------------------------------------------
# 2. Commit-time re-assertion that reused blobs still exist (Req 8.12)
# ---------------------------------------------------------------------------


@dataclass
class ReassertionResult:
    """Outcome of a commit-time reused-blob re-assertion (Req 8.12)."""

    present_hashes: list[str] = field(default_factory=list)
    """Reused blobs still present at the destination (safe to reference)."""

    missing_hashes: list[str] = field(default_factory=list)
    """Reused blobs found absent — must be re-uploaded or the job fails."""

    @property
    def all_present(self) -> bool:
        """True when every reused blob is still present (commit may proceed)."""
        return not self.missing_hashes


async def reassert_blobs_present(
    storage: StorageInterface,
    blobs: Iterable[BackupBlob],
    *,
    blob_prefix: str = DEFAULT_BLOB_PREFIX,
) -> ReassertionResult:
    """Re-assert a set of (reused) File_Blobs still exist at the destination.

    Lists the destination's blob namespace once via the provider-agnostic
    :class:`StorageInterface` and partitions ``blobs`` into present/missing by
    matching each blob's stored object key. Used at backup-commit time (Req
    8.12) so a manifest never commits a reference to a blob a concurrent
    prune/GC deleted between the dedup-skip and the commit.
    """
    blob_list = list(blobs)
    result = ReassertionResult()
    if not blob_list:
        return result

    objects = await storage.list(blob_prefix)
    present_keys = {obj.key for obj in objects}

    for blob in blob_list:
        key = blob_storage_key(blob.blob_name, prefix=blob_prefix)
        if key in present_keys:
            result.present_hashes.append(blob.content_hash)
        else:
            logger.warning(
                "commit re-assertion: reused File_Blob %s (%s) is absent at "
                "the destination — must re-upload before commit (Req 8.12)",
                blob.content_hash,
                key,
            )
            result.missing_hashes.append(blob.content_hash)

    return result


# ---------------------------------------------------------------------------
# 3. RPO validation of schedule/retention (Req 8.13, 25.2)
# ---------------------------------------------------------------------------


@dataclass
class _CronSpec:
    """Parsed 5-field cron expression (minute hour day-of-month month day-of-week)."""

    minutes: set[int]
    hours: set[int]
    doms: set[int]
    months: set[int]
    dows: set[int]
    dom_restricted: bool
    dow_restricted: bool


def _parse_cron_field(field_text: str, low: int, high: int) -> set[int]:
    """Parse one cron field (supports ``*``, lists, ranges, and ``*/n`` steps)."""
    values: set[int] = set()
    for part in field_text.split(","):
        part = part.strip()
        if not part:
            raise ValueError(f"empty cron field component in {field_text!r}")
        step = 1
        range_text = part
        if "/" in part:
            range_text, step_text = part.split("/", 1)
            step = int(step_text)
            if step <= 0:
                raise ValueError(f"non-positive step in {part!r}")
        if range_text == "*":
            start, end = low, high
        elif "-" in range_text:
            start_text, end_text = range_text.split("-", 1)
            start, end = int(start_text), int(end_text)
        else:
            start = end = int(range_text)
        if start < low or end > high or start > end:
            raise ValueError(f"cron field {part!r} out of bounds [{low},{high}]")
        values.update(range(start, end + 1, step))
    return values


def parse_cron(expr: str | None) -> _CronSpec | None:
    """Parse a standard 5-field cron expression, or ``None`` if invalid/empty.

    Supports ``*``, comma lists, ``a-b`` ranges, and ``*/n`` / ``a-b/n`` steps.
    Day-of-week accepts ``0`` or ``7`` for Sunday. Returns ``None`` for an empty
    or unparseable expression (cron *syntax* errors are surfaced elsewhere by
    the config service; this helper only cares whether it can evaluate the RPO).
    """
    if not expr or not expr.strip():
        return None
    fields = expr.split()
    if len(fields) != 5:
        return None
    try:
        minutes = _parse_cron_field(fields[0], 0, 59)
        hours = _parse_cron_field(fields[1], 0, 23)
        doms = _parse_cron_field(fields[2], 1, 31)
        months = _parse_cron_field(fields[3], 1, 12)
        dows_raw = _parse_cron_field(fields[4], 0, 7)
    except ValueError:
        return None
    # Normalise Sunday (cron allows both 0 and 7).
    dows = {0 if d == 7 else d for d in dows_raw}
    return _CronSpec(
        minutes=minutes,
        hours=hours,
        doms=doms,
        months=months,
        dows=dows,
        dom_restricted=fields[2] != "*",
        dow_restricted=fields[4] != "*",
    )


def _cron_matches(spec: _CronSpec, dt: datetime) -> bool:
    """Whether ``dt`` (minute resolution) is a cron fire time for ``spec``."""
    if dt.minute not in spec.minutes:
        return False
    if dt.hour not in spec.hours:
        return False
    if dt.month not in spec.months:
        return False
    # cron day-of-week: Sunday=0..Saturday=6; Python weekday(): Monday=0..Sunday=6.
    cron_dow = (dt.weekday() + 1) % 7
    dom_ok = dt.day in spec.doms
    dow_ok = cron_dow in spec.dows
    # Standard cron rule: when BOTH day-of-month and day-of-week are restricted,
    # a match occurs if EITHER matches; otherwise the restricted one governs.
    if spec.dom_restricted and spec.dow_restricted:
        return dom_ok or dow_ok
    if spec.dom_restricted:
        return dom_ok
    if spec.dow_restricted:
        return dow_ok
    return True


def estimate_max_interval_seconds(
    expr: str | None,
    *,
    now: datetime | None = None,
    max_scan_days: int = 370,
    min_fires: int = 64,
) -> int | None:
    """Estimate the worst-case interval between successive cron fire times.

    Walks the schedule minute-by-minute from ``now`` and returns the largest gap
    (in seconds) between consecutive fire times — the worst-case data-loss
    window the schedule allows, which is what the RPO bounds (Req 25.2). Returns
    ``None`` when the expression is invalid/empty or fires fewer than twice
    within ``max_scan_days`` (too infrequent to satisfy any practical RPO).

    Scanning stops early once ``min_fires`` fire times are collected so frequent
    schedules resolve in microseconds; sparse schedules (monthly) scan further
    but visit only cheap integer set lookups per minute. Evaluated in wall-clock
    minutes (DST shifts are negligible against RPO durations).
    """
    spec = parse_cron(expr)
    if spec is None:
        return None

    base = now if now is not None else datetime.now(timezone.utc)
    cur = base.replace(second=0, microsecond=0)
    end = cur + timedelta(days=max_scan_days)

    fires: list[datetime] = []
    while cur < end:
        if _cron_matches(spec, cur):
            fires.append(cur)
            if len(fires) >= min_fires:
                break
        cur += timedelta(minutes=1)

    if len(fires) < 2:
        return None

    max_gap = max(
        (fires[i + 1] - fires[i]).total_seconds() for i in range(len(fires) - 1)
    )
    return int(max_gap)


def _format_duration(seconds: float) -> str:
    """Human-readable duration (e.g. ``"48 hours"``, ``"30 minutes"``)."""
    seconds = int(seconds)
    if seconds % 86400 == 0 and seconds >= 86400:
        days = seconds // 86400
        return f"{days} day{'s' if days != 1 else ''}"
    if seconds % 3600 == 0 and seconds >= 3600:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''}"
    if seconds % 60 == 0 and seconds >= 60:
        minutes = seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    return f"{seconds} second{'s' if seconds != 1 else ''}"


@dataclass
class RpoValidationResult:
    """Result of validating a backup schedule against the configured RPO (Req 25.2)."""

    satisfied: bool
    """True when the schedule meets the RPO (or could not be faulted against it)."""

    rpo_seconds: int
    """The configured Recovery_Point_Objective the schedule was checked against."""

    interval_seconds: int | None = None
    """Estimated worst-case inter-backup interval, or ``None`` if undeterminable."""

    warning: str | None = None
    """Human-readable warning to present before save when the RPO is unmet."""


def validate_schedule_against_rpo(
    config: BackupConfig, *, now: datetime | None = None
) -> RpoValidationResult:
    """Validate the configured backup schedule against the RPO (Req 8.13, 25.2).

    Computes the worst-case interval between successive scheduled backups from
    ``config.schedule_cron`` and compares it to ``config.rpo_seconds``. Returns a
    :class:`RpoValidationResult` whose ``warning`` is set (and ``satisfied`` is
    ``False``) when the interval exceeds the RPO, when no schedule is configured,
    or when the schedule is too infrequent to evaluate — so the config service
    can surface the warning to the Global_Admin *before* the configuration is
    saved. A schedule whose interval is within the RPO returns ``satisfied=True``
    with no warning.

    Note: this validates the *backup-frequency* objective of Req 25.2 (the
    inter-backup interval vs the RPO). Retention governs how long recovery
    points are kept, not the recovery-point interval, so it does not factor into
    this RPO check.
    """
    rpo = config.rpo_seconds
    rpo_text = _format_duration(rpo)

    # No schedule at all → no automatic recovery points → RPO cannot be met.
    if not config.schedule_cron or not config.schedule_cron.strip():
        return RpoValidationResult(
            satisfied=False,
            rpo_seconds=rpo,
            interval_seconds=None,
            warning=(
                "No backup schedule is configured, so the configured Recovery "
                f"Point Objective of {rpo_text} cannot be met. Configure a "
                "backup frequency at least as often as the Recovery Point "
                "Objective."
            ),
        )

    # Unparseable cron: cron-syntax validation is the config service's job; do
    # not raise a spurious RPO warning here.
    if parse_cron(config.schedule_cron) is None:
        return RpoValidationResult(
            satisfied=True,
            rpo_seconds=rpo,
            interval_seconds=None,
            warning=None,
        )

    interval = estimate_max_interval_seconds(config.schedule_cron, now=now)

    if interval is None:
        # Parseable but fires < twice within the scan horizon → far too
        # infrequent for any practical RPO.
        return RpoValidationResult(
            satisfied=False,
            rpo_seconds=rpo,
            interval_seconds=None,
            warning=(
                "The configured backup schedule is too infrequent to satisfy "
                f"the Recovery Point Objective of {rpo_text}."
            ),
        )

    if interval > rpo:
        return RpoValidationResult(
            satisfied=False,
            rpo_seconds=rpo,
            interval_seconds=interval,
            warning=(
                "The configured backup schedule runs at most every "
                f"{_format_duration(interval)}, which exceeds the configured "
                f"Recovery Point Objective of {rpo_text}. Increase the backup "
                "frequency or relax the Recovery Point Objective."
            ),
        )

    return RpoValidationResult(
        satisfied=True,
        rpo_seconds=rpo,
        interval_seconds=interval,
        warning=None,
    )
