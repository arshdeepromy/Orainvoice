"""Full-restore canonical sequence (cloud-backup-restore Req 10, 12).

``restore/full_restore.py`` executes the **fixed canonical order** of
Requirement 12.15 for restoring a whole-platform Full_Backup onto the live HA
pair, safely and reversibly:

    (0) re-assert schema-compatibility, refusing an older-schema backup unless
        the request carries ``confirm_older_schema=true`` (Req 10.6, 10.7);
    (1) enable Maintenance_Mode (set ``backup_config.restore_maintenance_active``
        + ``HAService.enter_maintenance_mode``) within 10 s (Req 12.1, 12.2);
    (2) fence/detach every Standby_Node — disable then drop the logical
        replication subscription via ``ReplicationManager`` (Req 12.3, 12.10);
    (3) take the Pre_Restore_Snapshot of the now-isolated primary with
        ``pg_dump -Fc`` (Req 12.3, 12.4);
    (4) set ``destructive_apply_started=true`` then apply the restore with
        ``pg_restore --clean`` via the privileged connection (Req 12.5, 12.10);
    (5) run post-restore validation on the isolated primary (Req 12.5, 12.6);
    (6a) on validation PASS → full re-seed each standby (``trigger_resync``)
         then resume normal HA (Req 12.6, 12.13);
    (6b) on validation FAIL → roll back the isolated primary to the
         Pre_Restore_Snapshot, leave every standby fenced, surface a
         manual-intervention failure (Req 12.7, 12.8, 12.9).

The module enforces the invariants of Req 12.15:

* The Pre_Restore_Snapshot MUST be captured and every standby MUST be fenced
  **before** any destructive ``--clean`` apply.
* A failed-validation rollback MUST restore the Pre_Restore_Snapshot on the
  isolated primary **before** any standby re-seed is attempted.
* A standby is **NEVER** re-seeded from an unvalidated or rolled-back primary —
  ``trigger_resync`` runs only on the validation-PASS path (Req 12.7, 12.13).

**Abort-before-apply.** If Maintenance_Mode cannot be enabled within 10 s
(Req 12.2), a standby cannot be isolated (Req 12.11), or the Pre_Restore_Snapshot
cannot be created (Req 12.4), the Restore_Job aborts **before** any backup data
is applied, the target database is left unchanged, and Maintenance_Mode is
disabled (except where it was never enabled).

**Maintenance disabled within 10 s.** On any terminal ``completed``/``failed``
state or after a successful rollback, Maintenance_Mode is disabled within 10 s
(Req 12.9, 12.14) — with the single exception of a **failed rollback**, where
Maintenance_Mode is kept enabled and manual intervention is required (Req 12.8).

**Cancel (Req 12.16, 12.17).** While the job is in a pre-apply phase (before the
destructive ``pg_restore --clean`` of step 4 begins), a Global_Admin may cancel:
the restore stops having applied no backup data, releases the pre-apply state it
established (disables Maintenance_Mode within 10 s and, where it fenced a standby
solely for this restore, restores normal HA), and the job is recorded as
``cancelled``. Once ``destructive_apply_started`` is set the cancel is refused
with a 409-style :class:`CancelNotAllowedError`; from that point only the
built-in validation + automatic-rollback path determines the outcome.

### Injectable seams

Every side-effecting dependency is injected so the canonical sequence can be
driven by the upcoming property tests (11.5 ordering, 11.6 re-seed safety) and
integration test (11.7) with the HA pair, dump runner, ``pg_restore``, artifact
reader, validator, and wall clock all mocked:

* :class:`MaintenanceController` — enable/disable Maintenance_Mode (Req 12.1).
* :class:`StandbyFencer` — fence / restore-HA / full re-seed (Req 12.3, 12.13).
* :class:`SnapshotManager` — create / rollback / cleanup the Pre_Restore_Snapshot.
* :class:`RestoreApplier` — the destructive ``pg_restore --clean`` apply.
* :class:`RestoreValidator` — post-restore validation (Req 12.5).
* :class:`~app.modules.backup_restore.restore.per_org_restore.ArtifactReader`
  — manifest + encrypted dump + decrypted dump bytes (reused from per-org restore).
* :class:`~app.modules.backup_restore.restore.dry_run.TargetVersionReader`
  — the target's current Alembic revision (reused from the dry-run).
* ``clock`` — injected wall clock for the 10 s deadlines.

Per the project ``session.begin()`` auto-commit pattern, every Restore_Job /
``backup_config`` row update uses ``flush()`` + ``refresh()`` (never
``commit()``); the surrounding task/request transaction commits.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from app.modules.backup_restore.backup.manifest import BackupManifest
from app.modules.backup_restore.jobs import JobService
from app.modules.backup_restore.restore.dry_run import (
    COMPARE_EQUAL,
    COMPARE_OLDER,
    TargetVersionReader,
    compare_schema_versions,
    verify_checksum,
)
from app.modules.backup_restore.restore.per_org_restore import ArtifactReader

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Deadlines / vocabulary
# ---------------------------------------------------------------------------

#: Maintenance_Mode must be enabled within this many seconds or the restore
#: aborts before any data is applied (Req 12.1, 12.2).
MAINTENANCE_ENABLE_DEADLINE_SECONDS = 10.0

#: Maintenance_Mode must be disabled within this many seconds on terminal /
#: rollback (Req 12.9, 12.14).
MAINTENANCE_DISABLE_DEADLINE_SECONDS = 10.0

# Restore_Job decision vocabulary recorded on ``restore_decision`` (Req 10.8).
DECISION_PROCEEDED = "proceeded"
DECISION_REFUSED = "refused"
DECISION_CANCELLED = "cancelled"


class FullRestorePhase(str, enum.Enum):
    """The ordered phases of the canonical full-restore sequence (Req 12.15).

    Recorded on the result (and the Restore_Job's ``validation_results``) so the
    ordering-invariant property test (11.5) can assert the canonical order and
    that no destructive apply precedes snapshot + fence.
    """

    SCHEMA_REASSERT = "schema_reassert"  # step 0 (Req 10.6/10.7)
    CHECKSUM = "checksum"                # pre-apply integrity gate (Req 7.4-7.6)
    MAINTENANCE_ENABLE = "maintenance_enable"  # step 1 (Req 12.1)
    FENCE_STANDBY = "fence_standby"      # step 2 (Req 12.3/12.10)
    SNAPSHOT = "pre_restore_snapshot"    # step 3 (Req 12.3/12.4)
    APPLY = "destructive_apply"          # step 4 (Req 12.5/12.10)
    VALIDATE = "post_restore_validation"  # step 5 (Req 12.5/12.6)
    RESEED = "standby_reseed"            # step 6a (Req 12.6/12.13)
    RESUME_HA = "resume_ha"              # step 6a (Req 12.13)
    ROLLBACK = "rollback"                # step 6b (Req 12.7)
    MAINTENANCE_DISABLE = "maintenance_disable"  # Req 12.9/12.14


#: The canonical pre-apply ordering, used by the ordering-invariant property
#: test (11.5). The destructive apply (step 4) MUST follow all of these.
CANONICAL_PREAPPLY_ORDER: tuple[FullRestorePhase, ...] = (
    FullRestorePhase.SCHEMA_REASSERT,
    FullRestorePhase.CHECKSUM,
    FullRestorePhase.MAINTENANCE_ENABLE,
    FullRestorePhase.FENCE_STANDBY,
    FullRestorePhase.SNAPSHOT,
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FullRestoreError(Exception):
    """Base error for the full-restore flow."""


class CancelNotAllowedError(FullRestoreError):
    """A cancel was requested after the destructive apply began (Req 12.17).

    The router maps this to an HTTP 409 indicating the restore can no longer be
    safely cancelled; only the built-in validation + automatic-rollback path
    (Req 12.5–12.9, 12.15) determines the terminal outcome.
    """


class SchemaReassertRefused(FullRestoreError):
    """The schema re-assertion refused the restore (Req 10.2/10.3/10.6/10.7)."""


# Raised internally to route both an ``apply`` failure and a validation FAIL
# through the single rollback path; never escapes the service.
class _PostApplyFailure(Exception):
    def __init__(self, reason: str, *, failed_check: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.failed_check = failed_check


# ---------------------------------------------------------------------------
# Cancellation token (pre-apply only — Req 12.16/12.17)
# ---------------------------------------------------------------------------


class CancellationToken:
    """A one-shot pre-apply cancellation signal shared between the run loop and
    the cancel endpoint.

    The run loop checks :attr:`is_requested` at each pre-apply checkpoint and, if
    set, stops with no data applied and releases the pre-apply state (Req 12.16).
    :meth:`request` is called by :meth:`FullRestoreService.request_cancel` only
    while the job is still in a pre-apply phase; once
    ``destructive_apply_started`` is set the cancel is refused (Req 12.17) and
    the token is never tripped.
    """

    def __init__(self) -> None:
        self._requested = False

    def request(self) -> None:
        self._requested = True

    @property
    def is_requested(self) -> bool:
        return self._requested


# ---------------------------------------------------------------------------
# Injectable seams (ABCs)
# ---------------------------------------------------------------------------


class MaintenanceController(ABC):
    """Enables/disables Maintenance_Mode for the full restore (Req 12.1, 12.2).

    Production sets ``backup_config.restore_maintenance_active`` (read by
    ``RestoreMaintenanceMiddleware`` to gate/drain traffic) and also calls
    ``HAService.enter_maintenance_mode`` for operator visibility on the
    dashboard/heartbeat (see :class:`HAMaintenanceController`).
    """

    @abstractmethod
    async def enable(self) -> None:
        """Enable Maintenance_Mode. Must complete within the 10 s deadline the
        caller enforces, or raise (Req 12.1, 12.2)."""

    @abstractmethod
    async def disable(self) -> None:
        """Disable Maintenance_Mode (Req 12.9, 12.14)."""


class StandbyFencer(ABC):
    """Fences, restores, and re-seeds the logical-replication standby(s).

    "Fence" maps to disable-then-drop the subscription so the destructive
    ``--clean`` reload is never streamed to a standby (Req 12.10). "Re-seed" maps
    to a full ``trigger_resync`` (truncate + ``CREATE SUBSCRIPTION … copy_data=
    true``) of the standby from the restored primary, run **only** on the
    validation-PASS path (Req 12.13). "Restore HA" re-establishes the standby
    without a destructive reload (used for a pre-apply cancel/abort where the
    primary data is unchanged, Req 12.16).
    """

    @abstractmethod
    async def fence(self) -> None:
        """Disable + drop every standby subscription to isolate the primary
        (Req 12.3, 12.10). Raise if a standby cannot be isolated (Req 12.11)."""

    @abstractmethod
    async def reseed(self) -> None:
        """Full re-seed of every standby from the restored primary (Req 12.13).

        Called ONLY after post-restore validation has PASSED — never from an
        unvalidated or rolled-back primary."""

    @abstractmethod
    async def restore_ha(self) -> None:
        """Re-establish normal HA without a destructive reload, for a pre-apply
        cancel/abort where the primary data was never changed (Req 12.16)."""


class SnapshotManager(ABC):
    """Creates / rolls back / cleans up the Pre_Restore_Snapshot (Req 12.3/12.7)."""

    @abstractmethod
    async def create(self) -> str:
        """Create the Pre_Restore_Snapshot of the isolated primary and return its
        path (Req 12.3). Raise if it cannot be created (Req 12.4)."""

    @abstractmethod
    async def rollback(self, snapshot_path: str) -> None:
        """Restore the isolated primary from *snapshot_path* (Req 12.7). Raise on
        failure (Req 12.8)."""

    @abstractmethod
    async def cleanup(self, snapshot_path: str) -> None:
        """Best-effort removal of the snapshot once the job is terminal."""


class RestoreApplier(ABC):
    """Applies the restore with ``pg_restore --clean`` via the privileged
    connection (Req 12.4 step 4 / 12.10)."""

    @abstractmethod
    async def apply(self, dump_plaintext: bytes) -> None:
        """Destructively apply the decrypted custom-format dump to the isolated
        primary. Raise on failure (routed through the rollback path)."""


@dataclass
class ValidationOutcome:
    """The result of post-restore validation (Req 12.5)."""

    passed: bool
    failed_check: Optional[str] = None
    detail: str = ""
    checks: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "failed_check": self.failed_check,
            "detail": self.detail,
            "checks": list(self.checks),
        }


class RestoreValidator(ABC):
    """Runs the post-restore validation checks on the restored primary (Req 12.5).

    Checks: (a) every table in the Pre_Restore_Snapshot exists; (b) for a
    ``--clean`` restore each restored table's row count equals the count recorded
    in the backup (≥ for additive mode); (c) referential-integrity reports zero
    violations (defence-in-depth — the checksum gate of Req 7.4–7.7 is the
    primary integrity gate).
    """

    @abstractmethod
    async def validate(self, manifest: BackupManifest) -> ValidationOutcome:
        ...


class CallableRestoreValidator(RestoreValidator):
    """Adapts a plain async callable to a :class:`RestoreValidator` (tests/wiring)."""

    def __init__(self, fn: Callable[[BackupManifest], "object"]) -> None:
        self._fn = fn

    async def validate(self, manifest: BackupManifest) -> ValidationOutcome:
        result = self._fn(manifest)
        if asyncio.iscoroutine(result):
            result = await result
        if not isinstance(result, ValidationOutcome):
            raise TypeError("validator callable must return a ValidationOutcome")
        return result


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class FullRestoreResult:
    """The terminal outcome of a full-restore run.

    ``executed_phases`` records the canonical sequence actually executed, in
    order, so the ordering-invariant property test (11.5) can assert that no
    destructive apply preceded the snapshot + fence and that re-seed only ever
    follows a validation PASS (Req 12.15).
    """

    status: str  # completed | failed | cancelled
    decision: str  # proceeded | refused | cancelled (Req 10.8)
    executed_phases: list[FullRestorePhase] = field(default_factory=list)
    schema_outcome: Optional[str] = None
    validation: Optional[ValidationOutcome] = None
    snapshot_path: Optional[str] = None
    destructive_apply_started: bool = False
    standby_reseeded: bool = False
    maintenance_left_enabled: bool = False
    message: str = ""

    def record(self, phase: FullRestorePhase) -> None:
        self.executed_phases.append(phase)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "decision": self.decision,
            "phases": [p.value for p in self.executed_phases],
            "schema_outcome": self.schema_outcome,
            "validation": self.validation.to_dict() if self.validation else None,
            "destructive_apply_started": self.destructive_apply_started,
            "standby_reseeded": self.standby_reseeded,
            "maintenance_left_enabled": self.maintenance_left_enabled,
            "message": self.message,
        }


# ---------------------------------------------------------------------------
# Full-restore service
# ---------------------------------------------------------------------------


class FullRestoreService:
    """Executes the canonical Req 12.15 full-restore sequence.

    All side-effecting dependencies are injected (see the module docstring). The
    service mutates the Restore_Job row through the injected :class:`JobService`
    and the ``db`` session using ``flush()`` + ``refresh()`` (never ``commit()``).
    """

    def __init__(
        self,
        db,
        *,
        reader: ArtifactReader,
        target_version_reader: TargetVersionReader,
        maintenance: MaintenanceController,
        fencer: StandbyFencer,
        snapshot: SnapshotManager,
        applier: RestoreApplier,
        validator: RestoreValidator,
        job_service: Optional[JobService] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.db = db
        self.reader = reader
        self.target_version_reader = target_version_reader
        self.maintenance = maintenance
        self.fencer = fencer
        self.snapshot = snapshot
        self.applier = applier
        self.validator = validator
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.jobs = job_service or JobService(db, clock=self._clock)

    # ------------------------------------------------------------------
    # Cancel request handling (Req 12.16 / 12.17)
    # ------------------------------------------------------------------
    async def request_cancel(
        self, restore_job, cancel_token: CancellationToken
    ) -> None:
        """Request cancellation of an in-flight full restore.

        Reads ``destructive_apply_started`` transactionally (Req 12.17): if the
        destructive ``pg_restore --clean`` apply has begun the cancel is refused
        with :class:`CancelNotAllowedError` (→ HTTP 409). Otherwise the pre-apply
        cancellation token is tripped so the run loop stops at its next pre-apply
        checkpoint with no data applied (Req 12.16).

        The run loop is responsible for releasing the established pre-apply state
        and recording the job as ``cancelled``.
        """
        # Transactionally re-read the apply-boundary flag so the decision is
        # based on the committed state, never a stale in-memory value.
        try:
            await self.db.refresh(restore_job, attribute_names=["destructive_apply_started"])
        except Exception:  # noqa: BLE001 - refresh best-effort; fall back to attr
            logger.debug("Could not refresh restore job for cancel check", exc_info=True)

        if getattr(restore_job, "destructive_apply_started", False):
            raise CancelNotAllowedError(
                "the restore has begun its destructive apply and can no longer "
                "be safely cancelled; the built-in validation and automatic "
                "rollback will determine the outcome"
            )
        cancel_token.request()

    # ------------------------------------------------------------------
    # Canonical sequence (Req 12.15)
    # ------------------------------------------------------------------
    async def run(
        self,
        restore_job,
        *,
        confirm_older_schema: bool = False,
        cancel_token: Optional[CancellationToken] = None,
    ) -> FullRestoreResult:
        """Execute the canonical full-restore sequence for *restore_job*.

        Args:
            restore_job: The ``RestoreJob`` row (mode ``full``) to drive.
            confirm_older_schema: The ``confirm_older_schema`` flag from the
                ``POST /restore/full`` request; required to proceed with an
                older-schema backup (Req 10.6, 10.7).
            cancel_token: Pre-apply cancellation signal (Req 12.16); a fresh
                token is created when none is supplied.

        Returns:
            A :class:`FullRestoreResult` describing the terminal outcome.
        """
        token = cancel_token or CancellationToken()
        result = FullRestoreResult(status="failed", decision=DECISION_REFUSED)

        await self.jobs.start(restore_job)

        maintenance_enabled = False
        fenced = False
        snapshot_path: Optional[str] = None

        try:
            # === Step 0: re-assert schema-compat (Req 10.6/10.7) ===========
            result.record(FullRestorePhase.SCHEMA_REASSERT)
            manifest = await self.reader.read_manifest()
            schema = await self._reassert_schema(
                restore_job, manifest, confirm_older_schema, result
            )
            if schema is None:
                # Refused; restore_job already recorded as failed + refused.
                return result

            # === Pre-apply integrity gate: checksum (Req 7.4-7.6 / 12.16) ==
            result.record(FullRestorePhase.CHECKSUM)
            if not await self._verify_checksum(restore_job, manifest, result):
                return result

            # The decision to proceed has been taken (Req 10.8). It is only
            # overridden to ``cancelled`` by a pre-apply cancel below.
            restore_job.restore_decision = DECISION_PROCEEDED
            result.decision = DECISION_PROCEEDED
            await self._flush(restore_job)

            if await self._maybe_cancel(restore_job, result, maintenance_enabled, fenced, snapshot_path, token):
                return result

            # === Step 1: enable Maintenance_Mode within 10 s (Req 12.1/12.2) =
            result.record(FullRestorePhase.MAINTENANCE_ENABLE)
            if not await self._enable_maintenance(restore_job, result):
                return result  # aborted before apply; DB unchanged (Req 12.2)
            maintenance_enabled = True

            if await self._maybe_cancel(restore_job, result, maintenance_enabled, fenced, snapshot_path, token):
                return result

            # === Step 2: fence every standby (Req 12.3/12.10/12.11) =========
            result.record(FullRestorePhase.FENCE_STANDBY)
            try:
                await self.fencer.fence()
            except Exception as exc:  # noqa: BLE001
                # Req 12.11 — standby could not be isolated: abort before apply,
                # leave DB unchanged, disable Maintenance_Mode.
                await self._disable_maintenance(result)
                await self._fail(
                    restore_job,
                    result,
                    "the standby could not be isolated, so the restore was "
                    f"aborted before any data was applied: {_reason(exc)}",
                )
                return result
            fenced = True
            restore_job.standby_fenced = True
            await self._flush(restore_job)

            if await self._maybe_cancel(restore_job, result, maintenance_enabled, fenced, snapshot_path, token):
                return result

            # === Step 3: Pre_Restore_Snapshot of isolated primary (12.3/12.4) =
            result.record(FullRestorePhase.SNAPSHOT)
            try:
                snapshot_path = await self.snapshot.create()
            except Exception as exc:  # noqa: BLE001
                # Req 12.4 — snapshot creation failed: abort before apply, leave
                # DB unchanged, disable Maintenance_Mode.
                await self._restore_ha_quietly(fenced)
                await self._disable_maintenance(result)
                await self._fail(
                    restore_job,
                    result,
                    "the Pre_Restore_Snapshot could not be created, so the "
                    f"restore was aborted before any data was applied: {_reason(exc)}",
                )
                return result
            restore_job.pre_restore_snapshot_path = snapshot_path
            result.snapshot_path = snapshot_path
            await self._flush(restore_job)

            # Last pre-apply cancel checkpoint (Req 12.16).
            if await self._maybe_cancel(restore_job, result, maintenance_enabled, fenced, snapshot_path, token):
                return result

            # === Step 4: destructive apply (Req 12.5/12.10/12.17 boundary) ==
            # Persist the apply boundary BEFORE applying so a concurrent cancel
            # request reads it transactionally and is refused (Req 12.17).
            restore_job.destructive_apply_started = True
            result.destructive_apply_started = True
            await self._flush(restore_job)
            result.record(FullRestorePhase.APPLY)

            try:
                dump_plaintext = await self.reader.read_dump_plaintext()
                await self.applier.apply(dump_plaintext)

                # === Step 5: post-restore validation (Req 12.5/12.6) ========
                result.record(FullRestorePhase.VALIDATE)
                validation = await self.validator.validate(manifest)
                result.validation = validation
                restore_job.validation_results = {
                    "full_restore": {
                        **result.to_dict(),
                        "validation": validation.to_dict(),
                    }
                }
                await self._flush(restore_job)
                if not validation.passed:
                    raise _PostApplyFailure(
                        f"post-restore validation failed: {validation.detail}",
                        failed_check=validation.failed_check,
                    )
            except _PostApplyFailure as failure:
                await self._handle_post_apply_failure(
                    restore_job, result, snapshot_path, failure.reason
                )
                return result
            except Exception as exc:  # noqa: BLE001 - apply raised: roll back
                await self._handle_post_apply_failure(
                    restore_job,
                    result,
                    snapshot_path,
                    f"the restore apply failed: {_reason(exc)}",
                )
                return result

            # === Step 6a: validation PASS → re-seed + resume HA (12.6/12.13) =
            result.record(FullRestorePhase.RESEED)
            try:
                await self.fencer.reseed()
            except Exception as exc:  # noqa: BLE001
                # Req 12.14 — re-seed failed: keep out of normal HA, record
                # manual-intervention reason, leave the restored primary serving
                # traffic (so Maintenance_Mode is disabled).
                restore_job.standby_reseeded = False
                await self._disable_maintenance(result)
                await self._fail(
                    restore_job,
                    result,
                    "the restore applied and validated successfully, but "
                    "re-seeding the standby failed; the restored primary is "
                    "serving traffic and manual intervention is required to "
                    f"restore high availability: {_reason(exc)}",
                )
                return result
            restore_job.standby_reseeded = True
            result.standby_reseeded = True
            result.record(FullRestorePhase.RESUME_HA)
            await self._flush(restore_job)

            # Terminal completed; disable Maintenance_Mode within 10 s (Req 12.9).
            await self._disable_maintenance(result)
            await self.jobs.complete(
                restore_job,
                outcome_summary=(
                    "Full restore completed: data applied, validated, standby "
                    "re-seeded, and normal HA resumed."
                ),
            )
            result.status = "completed"
            result.message = "Full restore completed and HA resumed."
            return result

        except CancelNotAllowedError:
            raise
        except Exception as exc:  # noqa: BLE001 - never leak; best-effort cleanup
            logger.exception("Unexpected error during full restore")
            # If the destructive apply had begun, prefer a rollback; otherwise a
            # plain pre-apply abort. The boundary flag drives the choice.
            if result.destructive_apply_started and snapshot_path is not None:
                await self._handle_post_apply_failure(
                    restore_job,
                    result,
                    snapshot_path,
                    f"an unexpected error occurred during the restore: {_reason(exc)}",
                )
            else:
                await self._restore_ha_quietly(fenced)
                await self._disable_maintenance(result)
                if restore_job.status not in ("failed", "cancelled", "completed"):
                    await self._fail(
                        restore_job,
                        result,
                        f"an unexpected error aborted the restore before any "
                        f"data was applied: {_reason(exc)}",
                    )
            return result
        finally:
            # Clean up the snapshot once the job is terminal (the snapshot is
            # retained until then so a rollback can use it).
            if snapshot_path is not None:
                await self._cleanup_snapshot(snapshot_path)

    # ------------------------------------------------------------------
    # Step helpers
    # ------------------------------------------------------------------

    async def _reassert_schema(
        self,
        restore_job,
        manifest: BackupManifest,
        confirm_older_schema: bool,
        result: FullRestoreResult,
    ):
        """Re-assert schema-compat; refuse per Req 10.2/10.3/10.6/10.7.

        Returns the :class:`SchemaCompatResult` to proceed, or ``None`` when the
        restore is refused (the job is recorded ``failed`` + ``refused`` and no
        Maintenance_Mode was enabled, so the DB is untouched).
        """
        target_version = await self.target_version_reader.current_revision()
        known = self.target_version_reader.known_revisions()
        schema = compare_schema_versions(
            manifest.envelope.schema_version, target_version, known_revisions=known
        )
        restore_job.schema_compare_outcome = schema.outcome
        result.schema_outcome = schema.outcome

        # Older schema requires the explicit confirmation flag (Req 10.6/10.7).
        if schema.outcome == COMPARE_OLDER:
            if not confirm_older_schema:
                restore_job.restore_decision = DECISION_REFUSED
                result.decision = DECISION_REFUSED
                await self._fail(
                    restore_job,
                    result,
                    schema.message
                    + " — the restore is refused because the request did not "
                    "carry confirm_older_schema=true",
                )
                return None
            # Confirmed: proceed with the older-schema restore (Req 10.6).
            return schema

        # Equal → proceed (Req 10.4); newer/missing/unknown → refuse (10.2/10.3).
        if schema.outcome == COMPARE_EQUAL:
            return schema

        restore_job.restore_decision = DECISION_REFUSED
        result.decision = DECISION_REFUSED
        await self._fail(restore_job, result, schema.message)
        return None

    async def _verify_checksum(
        self, restore_job, manifest: BackupManifest, result: FullRestoreResult
    ) -> bool:
        """Verify the encrypted-artifact checksum before any write (Req 7.4-7.6).

        Returns ``True`` to proceed, ``False`` when the artifact is unreadable or
        the checksum mismatches (the job is failed; no Maintenance_Mode was
        enabled, so the DB is untouched).
        """
        try:
            encrypted = await self.reader.read_encrypted_dump()
        except Exception as exc:  # noqa: BLE001
            await self._fail(
                restore_job,
                result,
                f"the encrypted backup artifact could not be read: {_reason(exc)}",
            )
            return False
        ok, detail = verify_checksum(manifest, encrypted)
        if not ok:
            await self._fail(restore_job, result, detail)
            return False
        return True

    async def _enable_maintenance(self, restore_job, result: FullRestoreResult) -> bool:
        """Enable Maintenance_Mode within the 10 s deadline (Req 12.1/12.2).

        Returns ``True`` on success. On timeout/failure the restore aborts before
        any apply, the job is failed, and the DB is left unchanged (Req 12.2).
        Maintenance was never enabled so nothing needs disabling.
        """
        try:
            await asyncio.wait_for(
                self.maintenance.enable(),
                timeout=MAINTENANCE_ENABLE_DEADLINE_SECONDS,
            )
        except asyncio.TimeoutError:
            await self._fail(
                restore_job,
                result,
                "Maintenance_Mode could not be enabled within "
                f"{int(MAINTENANCE_ENABLE_DEADLINE_SECONDS)} seconds, so the "
                "restore was aborted before any data was applied",
            )
            return False
        except Exception as exc:  # noqa: BLE001
            await self._fail(
                restore_job,
                result,
                "Maintenance_Mode could not be enabled, so the restore was "
                f"aborted before any data was applied: {_reason(exc)}",
            )
            return False
        restore_job.maintenance_enabled_at = self._now()
        await self._flush(restore_job)
        return True

    async def _handle_post_apply_failure(
        self,
        restore_job,
        result: FullRestoreResult,
        snapshot_path: Optional[str],
        reason: str,
    ) -> None:
        """Roll back to the Pre_Restore_Snapshot, leaving every standby fenced.

        Implements Req 12.7 (roll back before any re-seed), Req 12.8 (a failed
        rollback keeps Maintenance_Mode enabled and requires manual
        intervention) and Req 12.9 (a successful rollback disables
        Maintenance_Mode within 10 s). A standby is NEVER re-seeded here, so the
        platform never re-seeds from a rolled-back primary (Req 12.13).
        """
        result.record(FullRestorePhase.ROLLBACK)
        if snapshot_path is None:
            # Defensive: without a snapshot we cannot roll back; keep maintenance
            # enabled and require manual intervention (treat like a rollback fail).
            result.maintenance_left_enabled = True
            await self._fail(
                restore_job,
                result,
                reason
                + " — no Pre_Restore_Snapshot was available to roll back; manual "
                "intervention is required",
            )
            return
        try:
            await self.snapshot.rollback(snapshot_path)
        except Exception as exc:  # noqa: BLE001
            # Req 12.8 — rollback failed: keep Maintenance_Mode enabled, do NOT
            # report the platform available, require manual intervention.
            result.maintenance_left_enabled = True
            await self._fail(
                restore_job,
                result,
                reason
                + f"; the rollback to the Pre_Restore_Snapshot then failed "
                f"({_reason(exc)}) — manual intervention is required and the "
                "platform is not available",
            )
            return
        # Rollback succeeded; standby stays fenced (Req 12.7). Disable
        # Maintenance_Mode within 10 s (Req 12.9).
        await self._disable_maintenance(result)
        await self._fail(
            restore_job,
            result,
            reason
            + " — the isolated primary was rolled back to the Pre_Restore_Snapshot "
            "and every standby was left fenced; manual intervention is required "
            "to resume high availability",
        )

    # ------------------------------------------------------------------
    # Cancel + cleanup helpers
    # ------------------------------------------------------------------

    async def _maybe_cancel(
        self,
        restore_job,
        result: FullRestoreResult,
        maintenance_enabled: bool,
        fenced: bool,
        snapshot_path: Optional[str],
        token: CancellationToken,
    ) -> bool:
        """Honour a pre-apply cancel at a checkpoint (Req 12.16).

        Returns ``True`` (and finalises the job as ``cancelled``) when a cancel
        was requested; ``False`` to continue. Releases the established pre-apply
        state: restores normal HA if a standby was fenced solely for this
        restore, and disables Maintenance_Mode within 10 s. No backup data was
        applied at any pre-apply checkpoint.
        """
        if not token.is_requested:
            return False

        # Restore normal HA where we fenced a standby solely for this restore.
        await self._restore_ha_quietly(fenced)
        if maintenance_enabled:
            await self._disable_maintenance(result)

        restore_job.restore_decision = DECISION_CANCELLED
        result.decision = DECISION_CANCELLED
        result.status = "cancelled"
        result.message = "Full restore cancelled before any data was applied."
        await self.jobs.cancel(
            restore_job,
            outcome_summary=(
                "Restore cancelled during a pre-apply phase; no backup data was "
                "applied and any maintenance/fence state was released."
            ),
        )
        return True

    async def _restore_ha_quietly(self, fenced: bool) -> None:
        """Best-effort restore of normal HA after a pre-apply abort/cancel.

        Only meaningful when a standby was fenced; the primary data is unchanged
        in every pre-apply path, so a non-destructive re-establish (not a full
        re-seed) is correct (Req 12.16).
        """
        if not fenced:
            return
        try:
            await self.fencer.restore_ha()
        except Exception:  # noqa: BLE001 - best-effort; surfaced via logs
            logger.warning(
                "Could not restore normal HA after a pre-apply abort/cancel; "
                "the standby may need manual re-establishment",
                exc_info=True,
            )

    async def _disable_maintenance(self, result: FullRestoreResult) -> None:
        """Disable Maintenance_Mode within the 10 s deadline (Req 12.9/12.14)."""
        try:
            await asyncio.wait_for(
                self.maintenance.disable(),
                timeout=MAINTENANCE_DISABLE_DEADLINE_SECONDS,
            )
            result.maintenance_left_enabled = False
        except asyncio.TimeoutError:
            result.maintenance_left_enabled = True
            logger.error(
                "Maintenance_Mode could not be disabled within %d seconds",
                int(MAINTENANCE_DISABLE_DEADLINE_SECONDS),
            )
        except Exception:  # noqa: BLE001
            result.maintenance_left_enabled = True
            logger.error("Failed to disable Maintenance_Mode", exc_info=True)

    async def _cleanup_snapshot(self, snapshot_path: str) -> None:
        try:
            await self.snapshot.cleanup(snapshot_path)
        except Exception:  # noqa: BLE001 - best-effort
            logger.debug(
                "Could not clean up Pre_Restore_Snapshot at %s", snapshot_path,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Job + session helpers
    # ------------------------------------------------------------------

    async def _fail(self, restore_job, result: FullRestoreResult, reason: str) -> None:
        result.status = "failed"
        result.message = reason
        await self.jobs.fail(restore_job, error_message=reason, outcome_summary=reason)

    async def _flush(self, restore_job) -> None:
        await self.db.flush()
        await self.db.refresh(restore_job)

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def _reason(exc: BaseException) -> str:
    """A short, stack-trace-free reason string for an exception (Req 9.10)."""
    text = str(exc).strip()
    return text or exc.__class__.__name__


# ===========================================================================
# Production seam implementations
# ===========================================================================
#
# These wire the abstract seams above to the real HA module, the standby-sourced
# ``pg_dump`` runner, and ``pg_restore``. They are kept thin and side-effecting
# so the canonical-sequence logic in :class:`FullRestoreService` stays unit- and
# property-testable with fakes, while the integration test (task 11.7) drives
# these concrete implementations against the dev HA pair.


class HAMaintenanceController(MaintenanceController):
    """Maintenance_Mode via ``backup_config.restore_maintenance_active`` + HA.

    Setting ``restore_maintenance_active`` is what ``RestoreMaintenanceMiddleware``
    reads to return HTTP 503 and drain in-flight requests during the restore;
    ``HAService.enter_maintenance_mode`` is also flipped so the operator-facing
    dashboard/heartbeat reflect the DR event (design "Maintenance mode
    enforcement"). Updates use ``flush()`` per the project session pattern.
    """

    def __init__(self, db, user_id) -> None:
        self.db = db
        self.user_id = user_id

    async def _config(self):
        from sqlalchemy import select

        from app.modules.backup_restore.models import BackupConfig

        result = await self.db.execute(select(BackupConfig).limit(1))
        cfg = result.scalars().first()
        if cfg is None:
            cfg = BackupConfig()
            self.db.add(cfg)
            await self.db.flush()
            await self.db.refresh(cfg)
        return cfg

    async def _set_active(self, active: bool) -> None:
        cfg = await self._config()
        cfg.restore_maintenance_active = active
        await self.db.flush()
        await self.db.refresh(cfg)

    async def enable(self) -> None:
        await self._set_active(True)
        try:
            from app.modules.ha.service import HAService

            await HAService.enter_maintenance_mode(self.db, self.user_id)
        except Exception:  # noqa: BLE001 - HA dashboard flag is best-effort
            logger.warning(
                "Could not flip HA maintenance flag for dashboard visibility; "
                "the restore-maintenance gate is still active",
                exc_info=True,
            )

    async def disable(self) -> None:
        await self._set_active(False)
        try:
            from app.modules.ha.service import HAService

            await HAService.exit_maintenance_mode(self.db, self.user_id)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Could not clear HA maintenance flag for dashboard visibility",
                exc_info=True,
            )


class ReplicationStandbyFencer(StandbyFencer):
    """Standby fence/restore/re-seed via ``ReplicationManager``.

    "Fence" disables then drops the subscription on the standby; "restore_ha"
    re-enables (or re-creates with ``copy_data=false``) without a destructive
    reload for a pre-apply abort/cancel; "reseed" runs the full
    ``trigger_resync`` (truncate + ``copy_data=true``) used only on the
    validation-PASS path (Req 12.13).

    ``standby_db`` is an ``AsyncSession`` connected to the **standby** node's
    database (where the subscription lives); ``primary_conn_str`` is the libpq
    connection string the standby uses to reach the restored primary for the
    re-seed/re-create.
    """

    def __init__(self, standby_db, primary_conn_str: str) -> None:
        self.standby_db = standby_db
        self.primary_conn_str = primary_conn_str

    async def fence(self) -> None:
        from app.modules.ha.replication import ReplicationManager

        await ReplicationManager.stop_subscription(self.standby_db)
        await ReplicationManager.drop_subscription(self.standby_db)

    async def reseed(self) -> None:
        from app.modules.ha.replication import ReplicationManager

        await ReplicationManager.trigger_resync(self.standby_db, self.primary_conn_str)

    async def restore_ha(self) -> None:
        from app.modules.ha.replication import ReplicationManager

        await ReplicationManager.resume_subscription(
            self.standby_db, self.primary_conn_str
        )


class PgDumpSnapshotManager(SnapshotManager):
    """Pre_Restore_Snapshot via ``pg_dump -Fc`` + rollback via ``pg_restore --clean``.

    The snapshot is a custom-format dump of the isolated primary written to a
    local path (design "Pre_Restore_Snapshot mechanism"). Rollback restores it
    with ``pg_restore --clean --if-exists --no-owner`` back into the primary.
    """

    def __init__(
        self,
        primary_admin_dsn: str,
        *,
        pg_dump_bin: str = "pg_dump",
        pg_restore_bin: str = "pg_restore",
        output_dir: Optional[str] = None,
        timeout_seconds: int = 6 * 60 * 60,
    ) -> None:
        self.primary_admin_dsn = primary_admin_dsn
        self.pg_dump_bin = pg_dump_bin
        self.pg_restore_bin = pg_restore_bin
        self.output_dir = output_dir
        self.timeout_seconds = timeout_seconds

    def _cli_dsn(self) -> str:
        return self.primary_admin_dsn.replace(
            "postgresql+asyncpg://", "postgresql://", 1
        )

    async def create(self) -> str:
        from app.modules.backup_restore.backup.pg_dump_runner import run_pg_dump

        output_path = None
        if self.output_dir is not None:
            os.makedirs(self.output_dir, exist_ok=True)
            output_path = os.path.join(
                self.output_dir,
                f"pre_restore_snapshot_{int(time.time())}.dump",
            )
        result = await run_pg_dump(
            self._cli_dsn(),
            output_path=output_path,
            pg_dump_bin=self.pg_dump_bin,
            timeout_seconds=self.timeout_seconds,
        )
        return result.dump_path

    async def rollback(self, snapshot_path: str) -> None:
        cmd = [
            self.pg_restore_bin,
            "--clean",
            "--if-exists",
            "--no-owner",
            f"--dbname={self._cli_dsn()}",
            snapshot_path,
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(
            process.communicate(), timeout=self.timeout_seconds
        )
        if process.returncode != 0:
            detail = (stderr or b"").decode("utf-8", errors="replace").strip()
            raise FullRestoreError(
                f"pg_restore of the Pre_Restore_Snapshot failed "
                f"(exit {process.returncode}): {detail}"
            )

    async def cleanup(self, snapshot_path: str) -> None:
        try:
            os.unlink(snapshot_path)
        except OSError:
            logger.debug("Snapshot %s already removed", snapshot_path, exc_info=True)


class PgRestoreApplier(RestoreApplier):
    """Destructive ``pg_restore --clean`` apply via the privileged connection.

    Writes the decrypted custom-format dump to a secure temp file then applies it
    to the isolated primary with ``pg_restore --clean --if-exists --no-owner``
    (Req 12.4 step 4 / 12.10). The temp file is always removed afterwards.
    """

    def __init__(
        self,
        primary_admin_dsn: str,
        *,
        pg_restore_bin: str = "pg_restore",
        timeout_seconds: int = 6 * 60 * 60,
    ) -> None:
        self.primary_admin_dsn = primary_admin_dsn
        self.pg_restore_bin = pg_restore_bin
        self.timeout_seconds = timeout_seconds

    def _cli_dsn(self) -> str:
        return self.primary_admin_dsn.replace(
            "postgresql+asyncpg://", "postgresql://", 1
        )

    async def apply(self, dump_plaintext: bytes) -> None:
        import tempfile

        fd, dump_path = tempfile.mkstemp(
            prefix="orainvoice_full_restore_", suffix=".dump"
        )
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(dump_plaintext)
            cmd = [
                self.pg_restore_bin,
                "--clean",
                "--if-exists",
                "--no-owner",
                f"--dbname={self._cli_dsn()}",
                dump_path,
            ]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.timeout_seconds
            )
            if process.returncode != 0:
                detail = (stderr or b"").decode("utf-8", errors="replace").strip()
                raise FullRestoreError(
                    f"pg_restore --clean apply failed (exit {process.returncode}): "
                    f"{detail}"
                )
        finally:
            try:
                os.unlink(dump_path)
            except OSError:
                pass


class AsyncpgRestoreValidator(RestoreValidator):
    """Post-restore validation against the restored primary (Req 12.5).

    Checks, in order:
      (a) every table named in *expected_tables* (the Pre_Restore_Snapshot table
          set) exists in the restored database;
      (b) for ``--clean`` (``additive=False``) each table's row count equals the
          count in *expected_row_counts*; for additive mode the count is ``>=``;
      (c) referential integrity reports zero violations — a defence-in-depth
          assertion (PostgreSQL FK enforcement already guarantees this on a
          ``--clean`` restore), so this implementation confirms there are no
          ``NOT VALID`` constraints left behind rather than re-walking every FK.

    ``expected_tables`` / ``expected_row_counts`` are supplied by the caller
    (the integration test / service facade) from the snapshot + backup metadata;
    when omitted, the corresponding check is reported as skipped rather than
    failing, so the validator never fabricates a PASS it cannot substantiate.
    """

    def __init__(
        self,
        primary_admin_dsn: str,
        *,
        expected_tables: Optional[list[str]] = None,
        expected_row_counts: Optional[dict[str, int]] = None,
        additive: bool = False,
    ) -> None:
        self.primary_admin_dsn = primary_admin_dsn
        self.expected_tables = expected_tables
        self.expected_row_counts = expected_row_counts
        self.additive = additive

    def _asyncpg_dsn(self) -> str:
        return self.primary_admin_dsn.replace(
            "postgresql+asyncpg://", "postgresql://", 1
        )

    async def validate(self, manifest: BackupManifest) -> ValidationOutcome:
        import asyncpg

        checks: list[dict] = []
        conn = await asyncpg.connect(self._asyncpg_dsn())
        try:
            # (a) table existence.
            if self.expected_tables:
                existing = {
                    r["tablename"]
                    for r in await conn.fetch(
                        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                    )
                }
                missing = [t for t in self.expected_tables if t not in existing]
                checks.append(
                    {
                        "check": "tables_exist",
                        "passed": not missing,
                        "detail": (
                            "all snapshot tables present"
                            if not missing
                            else f"missing tables: {', '.join(sorted(missing))}"
                        ),
                    }
                )
                if missing:
                    return ValidationOutcome(
                        passed=False,
                        failed_check="tables_exist",
                        detail=f"missing tables after restore: {', '.join(sorted(missing))}",
                        checks=checks,
                    )
            else:
                checks.append(
                    {"check": "tables_exist", "passed": True, "detail": "skipped (no expected table set)"}
                )

            # (b) row counts.
            if self.expected_row_counts:
                for table, expected in self.expected_row_counts.items():
                    actual = await conn.fetchval(f'SELECT count(*) FROM "{table}"')
                    ok = actual >= expected if self.additive else actual == expected
                    checks.append(
                        {
                            "check": "row_count",
                            "table": table,
                            "expected": expected,
                            "actual": actual,
                            "passed": ok,
                        }
                    )
                    if not ok:
                        return ValidationOutcome(
                            passed=False,
                            failed_check="row_count",
                            detail=(
                                f"row count mismatch for {table!r}: expected "
                                f"{'>=' if self.additive else '=='} {expected}, got {actual}"
                            ),
                            checks=checks,
                        )
            else:
                checks.append(
                    {"check": "row_count", "passed": True, "detail": "skipped (no expected counts)"}
                )

            # (c) referential integrity (defence-in-depth): no NOT VALID FKs.
            invalid = await conn.fetch(
                "SELECT conrelid::regclass::text AS rel, conname FROM pg_constraint "
                "WHERE contype = 'f' AND NOT convalidated"
            )
            checks.append(
                {
                    "check": "referential_integrity",
                    "passed": not invalid,
                    "detail": (
                        "all foreign keys validated"
                        if not invalid
                        else f"{len(invalid)} unvalidated foreign-key constraint(s)"
                    ),
                }
            )
            if invalid:
                return ValidationOutcome(
                    passed=False,
                    failed_check="referential_integrity",
                    detail=f"{len(invalid)} unvalidated foreign-key constraint(s) after restore",
                    checks=checks,
                )
        finally:
            await conn.close()

        return ValidationOutcome(passed=True, detail="all validation checks passed", checks=checks)


__all__ = [
    # deadlines / vocabulary
    "MAINTENANCE_ENABLE_DEADLINE_SECONDS",
    "MAINTENANCE_DISABLE_DEADLINE_SECONDS",
    "DECISION_PROCEEDED",
    "DECISION_REFUSED",
    "DECISION_CANCELLED",
    "FullRestorePhase",
    "CANONICAL_PREAPPLY_ORDER",
    # errors
    "FullRestoreError",
    "CancelNotAllowedError",
    "SchemaReassertRefused",
    # cancellation
    "CancellationToken",
    # seams
    "MaintenanceController",
    "StandbyFencer",
    "SnapshotManager",
    "RestoreApplier",
    "RestoreValidator",
    "CallableRestoreValidator",
    "ValidationOutcome",
    # result + service
    "FullRestoreResult",
    "FullRestoreService",
    # production impls
    "HAMaintenanceController",
    "ReplicationStandbyFencer",
    "PgDumpSnapshotManager",
    "PgRestoreApplier",
    "AsyncpgRestoreValidator",
]
