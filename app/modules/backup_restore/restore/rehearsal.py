"""Scheduled restore rehearsal (cloud-backup-restore Req 25.4/25.5, Req 26).

A **Restore_Rehearsal** is the living end-to-end proof that a backup actually
restores — distinct from a Dry_Run (``restore/dry_run.py``), which only verifies
the checksum + schema-compatibility and never applies the dump. A rehearsal
*does* apply a recent Full_Backup, but into a **throwaway isolated scratch
environment** that is separate from every production database and Standby_Node,
so it changes no production/standby data (Req 26.2).

Pipeline (design.md "Restore rehearsals", Req 26):

1. **Pick a recent backup.** When the caller does not pass one, select the most
   recent retained Full_Backup that contains organisation data (Req 26.2).
2. **Provision an isolated scratch environment** (an ephemeral scratch DB) and
   restore the decrypted dump into it (Req 26.2). The scratch env gets a unique
   ``scratch_env_id`` *before* the restore so it is recorded even if the restore
   fails (so a leaked environment is always traceable, Req 26.7).
3. **Validate** the scratch environment with four checks (Req 26.3):
   * **schema check** — the restored schema version matches the backup's
     recorded Alembic revision and the schema is non-empty;
   * **row-count check** — each per-org entity count recorded in the manifest is
     present in the restored scratch DB (``>=``, since the full dump also carries
     shared/global rows);
   * **file-consistency check** — every File_Index blob is fetchable and
     re-hashes to its recorded ``Content_Hash`` + byte size (Req 22.5/22.6
     semantics applied to the rehearsed backup);
   * **smoke check** — a representative application-level read succeeds against
     the restored scratch DB.
4. **Record** a :class:`~app.modules.backup_restore.models.RestoreRehearsal` row
   with ``result`` (``passed``/``failed``), each check's JSONB outcome, the
   measured restore duration, the ``scratch_env_id``, and the teardown status
   (Req 26.4). The measured duration is compared to the configured
   ``rto_seconds`` (Req 25.4); when it exceeds the RTO the RTO is recorded as
   unmet and a notification is dispatched (Req 25.5).
5. **Tear the scratch environment down regardless of outcome** in a ``finally``
   block (Req 26.5); a teardown failure is recorded + notified (Req 26.7).

**Injectable seams.** Every external dependency is injected so the rehearsal
logic can be exercised with the storage, scratch-env provisioning/teardown,
validation, wall clock, and notifications all faked:

* ``reader_factory`` — builds an :class:`ArtifactReader` (reused from the per-org
  restore flow) bound to the chosen backup; reads the manifest, decrypted dump,
  and File_Blobs from the backup's destination. Keeps the rehearsal
  provider-agnostic (Req 3).
* :class:`ScratchEnvironmentProvider` / :class:`ScratchEnvironment` — provision
  an isolated scratch DB, restore the dump into it, expose the read primitives
  the validator needs, and tear it down (Req 26.2/26.5).
* :class:`RehearsalValidator` — runs the four validation checks (Req 26.3).
* ``clock`` — injected wall clock for the measured restore duration (Req 25.4).
* ``notify_hook`` — dispatches the RTO-unmet (Req 25.5) and rehearsal-failure /
  teardown-failure (Req 26.6/26.7) notifications; channel/recipient resolution
  is the service facade's job (task 15.2), so the default merely logs.

Per the project ``session.begin()`` auto-commit pattern, the
:class:`RestoreRehearsal` row is persisted with ``flush()`` + ``refresh()`` —
never ``commit()``; the surrounding task transaction commits.
"""

from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from app.modules.backup_restore.backup.cas import content_hash
from app.modules.backup_restore.backup.manifest import BackupManifest
from app.modules.backup_restore.models import Backup, BackupConfig, RestoreRehearsal
from app.modules.backup_restore.restore.per_org_restore import (
    ArtifactReader,
    FileBlobUnavailableError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

RESULT_PASSED = "passed"
RESULT_FAILED = "failed"

# ``teardown_status`` values (Req 26.5/26.7).
TEARDOWN_SUCCEEDED = "succeeded"
TEARDOWN_FAILED = "failed"
TEARDOWN_SKIPPED = "skipped"  # scratch env was never provisioned

# Validation check names (Req 26.3); recorded as the JSONB column keys.
CHECK_SCHEMA = "schema"
CHECK_ROW_COUNT = "row_count"
CHECK_FILE_CONSISTENCY = "file_consistency"
CHECK_SMOKE = "smoke"

# The four checks in the order they run / are evaluated for the failed-step.
CHECK_ORDER = (CHECK_SCHEMA, CHECK_ROW_COUNT, CHECK_FILE_CONSISTENCY, CHECK_SMOKE)

# Notification event names (resolved to channels/recipients by service.py).
EVENT_REHEARSAL_FAILED = "rehearsal.failed"          # Req 26.6
EVENT_REHEARSAL_RTO_UNMET = "rehearsal.rto_unmet"    # Req 25.5
EVENT_REHEARSAL_TEARDOWN_FAILED = "rehearsal.teardown_failed"  # Req 26.7


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RehearsalError(Exception):
    """Base error for the restore-rehearsal flow."""


class NoBackupAvailableError(RehearsalError):
    """No retained Full_Backup is available to rehearse (Req 26.2)."""


# ---------------------------------------------------------------------------
# Check outcome
# ---------------------------------------------------------------------------


@dataclass
class CheckOutcome:
    """One validation step's outcome, persisted as a JSONB column (Req 26.4)."""

    name: str
    passed: bool
    detail: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            **({"data": self.data} if self.data else {}),
        }

    @classmethod
    def not_run(cls, name: str, reason: str) -> "CheckOutcome":
        """A check that did not execute (e.g. an earlier step raised) — failed."""
        return cls(name=name, passed=False, detail=f"not run: {reason}")


# ---------------------------------------------------------------------------
# Injectable seams (ABCs)
# ---------------------------------------------------------------------------


class ScratchEnvironment(ABC):
    """An isolated scratch environment a backup has been (or will be) restored into.

    The environment is throwaway and separate from every production database and
    Standby_Node (Req 26.2). It exposes only the read primitives the validator
    needs plus :meth:`restore_dump` and :meth:`teardown`. ``env_id`` is available
    immediately after provisioning so it is recorded even if the restore fails.
    """

    @property
    @abstractmethod
    def env_id(self) -> str:
        """A stable identifier for the scratch environment (recorded, Req 26.7)."""

    @abstractmethod
    async def restore_dump(self, dump_plaintext: bytes) -> None:
        """Restore the decrypted custom-format dump into the scratch env (Req 26.2)."""

    @abstractmethod
    async def list_tables(self) -> set[str]:
        """Return the set of public table names present in the scratch env."""

    @abstractmethod
    async def row_count(self, table: str) -> int:
        """Return ``SELECT count(*)`` for *table* in the scratch env."""

    @abstractmethod
    async def schema_version(self) -> Optional[str]:
        """Return the scratch env's current Alembic revision, or ``None``."""

    @abstractmethod
    async def smoke_check(self) -> tuple[bool, str]:
        """Run a representative application-level read; return ``(ok, detail)`` (Req 26.3)."""

    @abstractmethod
    async def teardown(self) -> None:
        """Release the scratch env's resources (Req 26.5). Raise on failure (Req 26.7)."""


class ScratchEnvironmentProvider(ABC):
    """Provisions a fresh isolated :class:`ScratchEnvironment` (Req 26.2)."""

    @abstractmethod
    async def provision(self) -> ScratchEnvironment:
        """Provision and return a new, empty isolated scratch environment."""


class RehearsalValidator(ABC):
    """Runs the four rehearsal validation checks against the scratch env (Req 26.3)."""

    @abstractmethod
    async def check_schema(
        self, scratch: ScratchEnvironment, manifest: BackupManifest
    ) -> CheckOutcome:
        ...

    @abstractmethod
    async def check_row_counts(
        self, scratch: ScratchEnvironment, manifest: BackupManifest
    ) -> CheckOutcome:
        ...

    @abstractmethod
    async def check_file_consistency(
        self,
        scratch: ScratchEnvironment,
        manifest: BackupManifest,
        reader: ArtifactReader,
    ) -> CheckOutcome:
        ...

    @abstractmethod
    async def check_smoke(self, scratch: ScratchEnvironment) -> CheckOutcome:
        ...


# ---------------------------------------------------------------------------
# Default validator (pure orchestration over the scratch env + manifest + reader)
# ---------------------------------------------------------------------------


class DefaultRehearsalValidator(RehearsalValidator):
    """The default four-check validator (Req 26.3).

    Pure orchestration over the injected :class:`ScratchEnvironment` primitives,
    the :class:`BackupManifest`, and the :class:`ArtifactReader`; no direct I/O,
    so it is fully testable with fakes.

    * **schema** — the restored schema is non-empty and (when the backup records
      one) its Alembic revision matches the backup's recorded ``schema_version``.
    * **row-count** — for every per-org entity count recorded in the manifest's
      Per_Org_Index, the restored scratch DB's count for the like-named table is
      ``>=`` the aggregated recorded count (``>=`` because the full dump also
      carries shared/global rows). Entity types with no matching table are
      skipped rather than failed.
    * **file-consistency** — every File_Index blob is fetchable via the reader
      and re-hashes to its recorded ``Content_Hash`` with the recorded byte size
      (Req 22.5/22.6 semantics).
    * **smoke** — delegates to :meth:`ScratchEnvironment.smoke_check`.
    """

    def __init__(self, *, max_files_checked: Optional[int] = None) -> None:
        # Optional cap on the number of File_Index blobs verified, for very large
        # backups; ``None`` verifies them all.
        self.max_files_checked = max_files_checked

    async def check_schema(
        self, scratch: ScratchEnvironment, manifest: BackupManifest
    ) -> CheckOutcome:
        tables = await scratch.list_tables()
        if not tables:
            return CheckOutcome(
                name=CHECK_SCHEMA,
                passed=False,
                detail="the restored scratch environment contains no tables",
            )

        expected = manifest.envelope.schema_version
        actual = await scratch.schema_version()
        data = {
            "expected_schema_version": expected,
            "actual_schema_version": actual,
            "table_count": len(tables),
        }
        if expected is None:
            return CheckOutcome(
                name=CHECK_SCHEMA,
                passed=True,
                detail=(
                    f"backup records no schema version; verified {len(tables)} "
                    f"tables restored into the scratch environment"
                ),
                data=data,
            )
        if actual == expected:
            return CheckOutcome(
                name=CHECK_SCHEMA,
                passed=True,
                detail=(
                    f"restored schema version {actual!r} matches the backup "
                    f"({len(tables)} tables)"
                ),
                data=data,
            )
        return CheckOutcome(
            name=CHECK_SCHEMA,
            passed=False,
            detail=(
                f"restored schema version {actual!r} does not match the backup's "
                f"recorded version {expected!r}"
            ),
            data=data,
        )

    async def check_row_counts(
        self, scratch: ScratchEnvironment, manifest: BackupManifest
    ) -> CheckOutcome:
        # Aggregate the Per_Org_Index entity counts by entity type across orgs.
        expected: dict[str, int] = {}
        for entry in manifest.envelope.per_org_index.entries:
            for entity in entry.entities:
                expected[entity.entity_type] = (
                    expected.get(entity.entity_type, 0) + entity.record_count
                )

        if not expected:
            return CheckOutcome(
                name=CHECK_ROW_COUNT,
                passed=True,
                detail="skipped: the backup records no per-organisation entity counts",
            )

        tables = await scratch.list_tables()
        compared = 0
        skipped: list[str] = []
        mismatches: list[str] = []
        for entity_type, expected_count in sorted(expected.items()):
            if entity_type not in tables:
                skipped.append(entity_type)
                continue
            compared += 1
            actual = await scratch.row_count(entity_type)
            if actual < expected_count:
                mismatches.append(
                    f"{entity_type}: expected >= {expected_count}, got {actual}"
                )

        data = {
            "compared": compared,
            "skipped_entity_types": skipped,
            "mismatches": mismatches,
        }
        if mismatches:
            return CheckOutcome(
                name=CHECK_ROW_COUNT,
                passed=False,
                detail=f"row-count check failed for {len(mismatches)} table(s): "
                + "; ".join(mismatches),
                data=data,
            )
        return CheckOutcome(
            name=CHECK_ROW_COUNT,
            passed=True,
            detail=(
                f"all {compared} compared table(s) meet their recorded row counts"
                + (f"; {len(skipped)} entity type(s) had no matching table" if skipped else "")
            ),
            data=data,
        )

    async def check_file_consistency(
        self,
        scratch: ScratchEnvironment,
        manifest: BackupManifest,
        reader: ArtifactReader,
    ) -> CheckOutcome:
        entries = manifest.envelope.file_index.entries
        if not entries:
            return CheckOutcome(
                name=CHECK_FILE_CONSISTENCY,
                passed=True,
                detail="skipped: the backup contains no captured files",
            )

        to_check = entries
        if self.max_files_checked is not None:
            to_check = entries[: self.max_files_checked]

        verified = 0
        missing: list[str] = []
        corrupt: list[str] = []
        for entry in to_check:
            try:
                blob = await reader.read_blob(entry.content_hash)
            except FileBlobUnavailableError:
                missing.append(entry.content_hash)
                continue
            except Exception as exc:  # noqa: BLE001 - normalise to "unavailable"
                missing.append(f"{entry.content_hash} ({exc})")
                continue
            actual_hash = content_hash(blob)
            if actual_hash != entry.content_hash or len(blob) != entry.byte_size:
                corrupt.append(entry.content_hash)
                continue
            verified += 1

        data = {
            "files_in_index": len(entries),
            "files_checked": len(to_check),
            "verified": verified,
            "missing": len(missing),
            "corrupt": len(corrupt),
        }
        if missing or corrupt:
            return CheckOutcome(
                name=CHECK_FILE_CONSISTENCY,
                passed=False,
                detail=(
                    f"file-consistency check failed: {len(missing)} blob(s) "
                    f"unavailable, {len(corrupt)} blob(s) failed their checksum"
                ),
                data=data,
            )
        return CheckOutcome(
            name=CHECK_FILE_CONSISTENCY,
            passed=True,
            detail=f"all {verified} checked file blob(s) match their recorded checksum",
            data=data,
        )

    async def check_smoke(self, scratch: ScratchEnvironment) -> CheckOutcome:
        ok, detail = await scratch.smoke_check()
        return CheckOutcome(name=CHECK_SMOKE, passed=bool(ok), detail=detail)


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class RehearsalRunResult:
    """The terminal outcome of a rehearsal run (mirrors the persisted row)."""

    backup_id: Optional[str]
    result: str  # passed | failed
    schema_check: CheckOutcome
    rowcount_check: CheckOutcome
    file_check: CheckOutcome
    smoke_check: CheckOutcome
    measured_duration_seconds: int
    scratch_env_id: Optional[str]
    teardown_status: str
    rto_seconds: Optional[int] = None
    rto_met: Optional[bool] = None
    failed_step: Optional[str] = None
    rehearsal_id: Optional[str] = None

    @property
    def passed(self) -> bool:
        return self.result == RESULT_PASSED

    def checks(self) -> list[CheckOutcome]:
        return [self.schema_check, self.rowcount_check, self.file_check, self.smoke_check]

    def to_dict(self) -> dict:
        return {
            "backup_id": self.backup_id,
            "result": self.result,
            "failed_step": self.failed_step,
            "measured_duration_seconds": self.measured_duration_seconds,
            "rto_seconds": self.rto_seconds,
            "rto_met": self.rto_met,
            "scratch_env_id": self.scratch_env_id,
            "teardown_status": self.teardown_status,
            "rehearsal_id": self.rehearsal_id,
            "checks": {
                CHECK_SCHEMA: self.schema_check.to_dict(),
                CHECK_ROW_COUNT: self.rowcount_check.to_dict(),
                CHECK_FILE_CONSISTENCY: self.file_check.to_dict(),
                CHECK_SMOKE: self.smoke_check.to_dict(),
            },
        }


# Injectable-callable type aliases.
ReaderFactory = Callable[[Backup], "ArtifactReader | Awaitable[ArtifactReader]"]
NotifyHook = Callable[..., "Awaitable[None] | None"]
RecentBackupSelector = Callable[[], Awaitable[Optional[Backup]]]


async def _default_notify_hook(**kwargs: object) -> None:
    """Default notification hook — logs only (service.py notifications, task 15.2)."""
    logger.info("rehearsal notification (placeholder): %s", kwargs)


async def _maybe_await(value: "Any") -> "Any":
    if hasattr(value, "__await__"):
        return await value
    return value


# ---------------------------------------------------------------------------
# Rehearsal service
# ---------------------------------------------------------------------------


class RehearsalService:
    """Runs a scheduled Restore_Rehearsal end-to-end (Req 25.4/25.5, Req 26).

    All side-effecting dependencies are injected (see the module docstring). The
    persisted :class:`RestoreRehearsal` row is written with ``flush()`` +
    ``refresh()`` (never ``commit()``); the surrounding task transaction commits.

    Args:
        db: The ``AsyncSession`` used to select the backup, read the
            ``backup_config`` RTO, and persist the rehearsal row.
        scratch_provider: Provisions the isolated scratch environment (Req 26.2).
        reader_factory: Builds an :class:`ArtifactReader` for a chosen backup.
        validator: The four-check validator (defaults to
            :class:`DefaultRehearsalValidator`).
        clock: Injected wall clock for the measured restore duration (Req 25.4).
        notify_hook: Dispatches rehearsal notifications (Req 25.5/26.6/26.7).
        recent_backup_selector: Selects the backup to rehearse when none is
            passed (defaults to the most recent retained org-bearing Full_Backup).
    """

    def __init__(
        self,
        db,
        *,
        scratch_provider: ScratchEnvironmentProvider,
        reader_factory: ReaderFactory,
        validator: Optional[RehearsalValidator] = None,
        clock: Optional[Callable[[], datetime]] = None,
        notify_hook: Optional[NotifyHook] = None,
        recent_backup_selector: Optional[RecentBackupSelector] = None,
    ) -> None:
        self.db = db
        self.scratch_provider = scratch_provider
        self.reader_factory = reader_factory
        self.validator = validator or DefaultRehearsalValidator()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.notify_hook = notify_hook or _default_notify_hook
        self._recent_backup_selector = recent_backup_selector

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    async def run_rehearsal(self, backup: Optional[Backup] = None) -> RehearsalRunResult:
        """Rehearse *backup* (or a recently selected one) into a scratch env.

        Restores the backup into a freshly provisioned isolated scratch
        environment, runs the four validation checks, records the result + each
        check + the measured duration vs the configured RTO, and tears the
        scratch environment down in a ``finally`` block regardless of outcome.

        Raises:
            NoBackupAvailableError: when no backup is passed and none can be
                selected to rehearse (Req 26.2).
        """
        if backup is None:
            backup = await self._select_recent_backup()
        if backup is None:
            raise NoBackupAvailableError(
                "no retained Full_Backup is available to rehearse"
            )

        reader = await _maybe_await(self.reader_factory(backup))
        rto_seconds = await self._load_rto_seconds()

        started = self._clock()
        scratch: Optional[ScratchEnvironment] = None
        scratch_env_id: Optional[str] = None
        teardown_status = TEARDOWN_SKIPPED

        # Default every check to "not run" so a failure before/within validation
        # still produces a complete, persistable record (Req 26.4).
        schema_check = CheckOutcome.not_run(CHECK_SCHEMA, "rehearsal did not reach validation")
        rowcount_check = CheckOutcome.not_run(CHECK_ROW_COUNT, "rehearsal did not reach validation")
        file_check = CheckOutcome.not_run(CHECK_FILE_CONSISTENCY, "rehearsal did not reach validation")
        smoke_check = CheckOutcome.not_run(CHECK_SMOKE, "rehearsal did not reach validation")

        try:
            # --- Provision + restore (Req 26.2) ---------------------------
            scratch = await self.scratch_provider.provision()
            scratch_env_id = scratch.env_id

            dump_plaintext = await reader.read_dump_plaintext()
            await scratch.restore_dump(dump_plaintext)

            manifest = await reader.read_manifest()

            # --- Validate (Req 26.3) --------------------------------------
            schema_check = await self.validator.check_schema(scratch, manifest)
            rowcount_check = await self.validator.check_row_counts(scratch, manifest)
            file_check = await self.validator.check_file_consistency(
                scratch, manifest, reader
            )
            smoke_check = await self.validator.check_smoke(scratch)
        except Exception as exc:  # noqa: BLE001 - any failure ⇒ a failed rehearsal
            logger.warning(
                "Restore rehearsal of backup %s failed during restore/validation: %s",
                getattr(backup, "id", None),
                exc,
            )
            # Attribute the failure to the first check still marked "not run".
            reason = _reason(exc)
            for check in (schema_check, rowcount_check, file_check, smoke_check):
                if check.detail.startswith("not run"):
                    check.passed = False
                    check.detail = f"failed: {reason}"
                    break
        finally:
            measured_end = self._clock()
            # --- Teardown regardless of outcome (Req 26.5) ----------------
            if scratch is not None:
                teardown_status = await self._teardown(scratch, backup)

        measured_duration_seconds = max(
            0, int(round((measured_end - started).total_seconds()))
        )

        checks = {
            CHECK_SCHEMA: schema_check,
            CHECK_ROW_COUNT: rowcount_check,
            CHECK_FILE_CONSISTENCY: file_check,
            CHECK_SMOKE: smoke_check,
        }
        failed_step = next(
            (name for name in CHECK_ORDER if not checks[name].passed), None
        )
        result_value = RESULT_PASSED if failed_step is None else RESULT_FAILED

        # --- RTO comparison (Req 25.4 / 25.5) ------------------------------
        rto_met: Optional[bool] = None
        if rto_seconds is not None:
            rto_met = measured_duration_seconds <= rto_seconds

        run_result = RehearsalRunResult(
            backup_id=str(getattr(backup, "id", None)) if getattr(backup, "id", None) else None,
            result=result_value,
            schema_check=schema_check,
            rowcount_check=rowcount_check,
            file_check=file_check,
            smoke_check=smoke_check,
            measured_duration_seconds=measured_duration_seconds,
            scratch_env_id=scratch_env_id,
            teardown_status=teardown_status,
            rto_seconds=rto_seconds,
            rto_met=rto_met,
            failed_step=failed_step,
        )

        # --- Persist the rehearsal row (Req 26.4) --------------------------
        await self._persist(run_result, backup)

        # --- Notifications (Req 25.5 / 26.6) -------------------------------
        await self._dispatch_notifications(run_result)

        return run_result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    async def _select_recent_backup(self) -> Optional[Backup]:
        """Select the most recent retained org-bearing Full_Backup (Req 26.2)."""
        if self._recent_backup_selector is not None:
            return await self._recent_backup_selector()

        from sqlalchemy import select

        stmt = (
            select(Backup)
            .where(
                Backup.prune_status == "retained",
                Backup.scope.in_(("organisations_only", "both")),
            )
            .order_by(Backup.created_at.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _load_rto_seconds(self) -> Optional[int]:
        """Read the configured Recovery_Time_Objective in seconds (Req 25.4)."""
        from sqlalchemy import select

        result = await self.db.execute(select(BackupConfig).limit(1))
        config = result.scalar_one_or_none()
        return int(config.rto_seconds) if config is not None else None

    async def _teardown(self, scratch: ScratchEnvironment, backup: Backup) -> str:
        """Tear the scratch env down; record + notify on failure (Req 26.5/26.7)."""
        try:
            await scratch.teardown()
            return TEARDOWN_SUCCEEDED
        except Exception as exc:  # noqa: BLE001 - a teardown failure is recorded, not raised
            reason = _reason(exc)
            logger.error(
                "Restore rehearsal: tearing down scratch environment %s failed; "
                "manual cleanup may be required: %s",
                scratch.env_id,
                reason,
            )
            await self._notify(
                event=EVENT_REHEARSAL_TEARDOWN_FAILED,
                success=False,
                backup_id=str(getattr(backup, "id", None)),
                scratch_env_id=scratch.env_id,
                detail=(
                    f"the rehearsal scratch environment {scratch.env_id!r} could "
                    f"not be torn down: {reason}"
                ),
            )
            return TEARDOWN_FAILED

    async def _persist(self, run_result: RehearsalRunResult, backup: Backup) -> None:
        """Persist the :class:`RestoreRehearsal` row (flush + refresh, Req 26.4)."""
        row = RestoreRehearsal(
            backup_id=getattr(backup, "id", None),
            result=run_result.result,
            schema_check=run_result.schema_check.to_dict(),
            rowcount_check=run_result.rowcount_check.to_dict(),
            file_check=run_result.file_check.to_dict(),
            smoke_check=run_result.smoke_check.to_dict(),
            measured_duration_seconds=run_result.measured_duration_seconds,
            scratch_env_id=run_result.scratch_env_id,
            teardown_status=run_result.teardown_status,
        )
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        run_result.rehearsal_id = str(row.id)

    async def _dispatch_notifications(self, run_result: RehearsalRunResult) -> None:
        """Dispatch failure (Req 26.6) and RTO-unmet (Req 25.5) notifications."""
        if run_result.result == RESULT_FAILED:
            failed = run_result.failed_step
            detail = ""
            if failed is not None:
                detail = {
                    CHECK_SCHEMA: run_result.schema_check,
                    CHECK_ROW_COUNT: run_result.rowcount_check,
                    CHECK_FILE_CONSISTENCY: run_result.file_check,
                    CHECK_SMOKE: run_result.smoke_check,
                }[failed].detail
            await self._notify(
                event=EVENT_REHEARSAL_FAILED,
                success=False,
                backup_id=run_result.backup_id,
                failed_step=failed,
                detail=f"restore rehearsal failed at the {failed!r} check: {detail}",
            )

        # Req 25.5 — measured duration exceeded the configured RTO.
        if run_result.rto_met is False:
            await self._notify(
                event=EVENT_REHEARSAL_RTO_UNMET,
                success=False,
                backup_id=run_result.backup_id,
                measured_duration_seconds=run_result.measured_duration_seconds,
                rto_seconds=run_result.rto_seconds,
                detail=(
                    f"restore rehearsal measured duration "
                    f"{run_result.measured_duration_seconds}s exceeded the "
                    f"configured Recovery_Time_Objective of {run_result.rto_seconds}s"
                ),
            )

    async def _notify(self, **kwargs: object) -> None:
        """Invoke the notify hook; a failed notification is non-fatal."""
        try:
            await _maybe_await(self.notify_hook(**kwargs))
        except Exception as exc:  # noqa: BLE001
            logger.error("rehearsal notification dispatch failed: %s", exc)


def _reason(exc: BaseException) -> str:
    """A short, stack-trace-free reason string for an exception (Req 9.10)."""
    text = str(exc).strip()
    return text or exc.__class__.__name__


# ===========================================================================
# Production scratch-environment implementation.
#
# Provisions an ephemeral scratch PostgreSQL database on the admin server,
# ``pg_restore``\\ s the dump into it, exposes the validator read primitives over
# asyncpg, and always drops the database on teardown (Req 26.2/26.5). Mirrors
# ``ScratchDbDumpExtractor`` (per_org_restore.py). Tests inject fakes instead.
# ===========================================================================


class PgScratchEnvironment(ScratchEnvironment):
    """An ephemeral scratch PostgreSQL database for a rehearsal (Req 26.2/26.5)."""

    def __init__(
        self,
        admin_dsn: str,
        scratch_db: str,
        *,
        pg_restore_bin: str = "pg_restore",
        smoke_table_candidates: Optional[list[str]] = None,
    ) -> None:
        self.admin_dsn = admin_dsn
        self._scratch_db = scratch_db
        self.pg_restore_bin = pg_restore_bin
        # Representative core tables tried (in order) for the smoke read; the
        # first that exists is counted.
        self.smoke_table_candidates = smoke_table_candidates or [
            "organizations",
            "organisations",
            "users",
        ]

    @property
    def env_id(self) -> str:
        return self._scratch_db

    def _asyncpg_dsn(self, dsn: str) -> str:
        return dsn.replace("postgresql+asyncpg://", "postgresql://", 1)

    def _scratch_dsn(self) -> str:
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(self._asyncpg_dsn(self.admin_dsn))
        return urlunsplit(parts._replace(path=f"/{self._scratch_db}"))

    async def restore_dump(self, dump_plaintext: bytes) -> None:
        import asyncio
        import os
        import tempfile

        dump_path = None
        try:
            fd, dump_path = tempfile.mkstemp(prefix="orainvoice_rehearsal_", suffix=".dump")
            with os.fdopen(fd, "wb") as fh:
                fh.write(dump_plaintext)

            cmd = [
                self.pg_restore_bin,
                "--no-owner",
                "--no-privileges",
                f"--dbname={self._scratch_dsn()}",
                dump_path,
            ]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()
            if process.returncode != 0:
                detail = (stderr or b"").decode("utf-8", errors="replace").strip()
                raise RehearsalError(
                    f"restoring the dump into the scratch environment failed "
                    f"(pg_restore exit {process.returncode}): {detail}"
                )
        finally:
            if dump_path is not None:
                try:
                    os.unlink(dump_path)
                except OSError:
                    pass

    async def _connect(self):
        import asyncpg

        return await asyncpg.connect(self._scratch_dsn())

    async def list_tables(self) -> set[str]:
        conn = await self._connect()
        try:
            rows = await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
            return {r["tablename"] for r in rows}
        finally:
            await conn.close()

    async def row_count(self, table: str) -> int:
        conn = await self._connect()
        try:
            return int(await conn.fetchval(f'SELECT count(*) FROM "{table}"'))
        finally:
            await conn.close()

    async def schema_version(self) -> Optional[str]:
        conn = await self._connect()
        try:
            value = await conn.fetchval(
                "SELECT version_num FROM alembic_version LIMIT 1"
            )
            return None if value is None else str(value)
        except Exception:  # noqa: BLE001 - no alembic_version table ⇒ unknown
            return None
        finally:
            await conn.close()

    async def smoke_check(self) -> tuple[bool, str]:
        conn = await self._connect()
        try:
            # A representative application-level read: confirm connectivity and
            # count a core table when present.
            await conn.fetchval("SELECT 1")
            existing = {
                r["tablename"]
                for r in await conn.fetch(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                )
            }
            for table in self.smoke_table_candidates:
                if table in existing:
                    count = int(await conn.fetchval(f'SELECT count(*) FROM "{table}"'))
                    return True, f"smoke read succeeded: {table} has {count} row(s)"
            return True, "smoke read succeeded: connectivity confirmed"
        except Exception as exc:  # noqa: BLE001
            return False, f"smoke read failed: {_reason(exc)}"
        finally:
            await conn.close()

    async def teardown(self) -> None:
        conn = await self._connect_admin()
        try:
            await conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = $1 AND pid <> pg_backend_pid()",
                self._scratch_db,
            )
            await conn.execute(f'DROP DATABASE IF EXISTS "{self._scratch_db}"')
        finally:
            await conn.close()

    async def _connect_admin(self):
        import asyncpg

        return await asyncpg.connect(self._asyncpg_dsn(self.admin_dsn))


class PgScratchEnvironmentProvider(ScratchEnvironmentProvider):
    """Provisions a uniquely-named ephemeral scratch PostgreSQL database (Req 26.2)."""

    def __init__(
        self,
        admin_dsn: str,
        *,
        pg_restore_bin: str = "pg_restore",
        db_name_prefix: str = "orainvoice_rehearsal_",
    ) -> None:
        self.admin_dsn = admin_dsn
        self.pg_restore_bin = pg_restore_bin
        self.db_name_prefix = db_name_prefix

    def _asyncpg_dsn(self, dsn: str) -> str:
        return dsn.replace("postgresql+asyncpg://", "postgresql://", 1)

    async def provision(self) -> ScratchEnvironment:
        import asyncpg

        scratch_db = f"{self.db_name_prefix}{uuid.uuid4().hex}"
        conn = await asyncpg.connect(self._asyncpg_dsn(self.admin_dsn))
        try:
            await conn.execute(f'CREATE DATABASE "{scratch_db}"')
        finally:
            await conn.close()
        return PgScratchEnvironment(
            self.admin_dsn, scratch_db, pg_restore_bin=self.pg_restore_bin
        )


__all__ = [
    # vocabulary
    "RESULT_PASSED",
    "RESULT_FAILED",
    "TEARDOWN_SUCCEEDED",
    "TEARDOWN_FAILED",
    "TEARDOWN_SKIPPED",
    "CHECK_SCHEMA",
    "CHECK_ROW_COUNT",
    "CHECK_FILE_CONSISTENCY",
    "CHECK_SMOKE",
    "CHECK_ORDER",
    "EVENT_REHEARSAL_FAILED",
    "EVENT_REHEARSAL_RTO_UNMET",
    "EVENT_REHEARSAL_TEARDOWN_FAILED",
    # errors
    "RehearsalError",
    "NoBackupAvailableError",
    # outcome + result
    "CheckOutcome",
    "RehearsalRunResult",
    # seams
    "ScratchEnvironment",
    "ScratchEnvironmentProvider",
    "RehearsalValidator",
    "DefaultRehearsalValidator",
    # service
    "RehearsalService",
    # production impls
    "PgScratchEnvironment",
    "PgScratchEnvironmentProvider",
]
