"""Dry-run validation + schema-compatibility check (cloud-backup-restore Req 10, 11).

This module performs the two **validation-only** gates that precede any restore:

1. **Checksum verification (Req 11.2 / 7.4).** Re-hash the *encrypted* dump bytes
   and compare to the checksum recorded in the manifest catalog. This is the
   primary integrity gate; it needs no key material because the checksum is
   computed over ciphertext (see :mod:`backup.manifest`).
2. **Schema-compatibility check (Req 10 / 11.3).** Compare the backup's recorded
   Alembic revision (``manifest.envelope.schema_version``) to the target
   deployment's current Alembic revision and classify the relationship as
   ``equal`` / ``older`` / ``newer`` / ``missing`` / ``unknown``.

Crucially this module performs **NO write, NO DDL, and NO data change** to the
target database (Req 11.1, 11.7). It reads the manifest + encrypted dump through
the injected :class:`~app.modules.backup_restore.restore.per_org_restore.ArtifactReader`
and reads the target revision through the injected :class:`TargetVersionReader`;
it then reports an overall ``PASS``/``FAIL`` plus per-step outcomes (Req 11.4)
and records the comparison outcome + decision on the :class:`RestoreJob`
(Req 10.8). The whole operation is inherently fast (one SHA-256 over the dump
bytes plus an integer version compare), so the 60-second reporting bound of
Req 11.4 is met with wide margin; the measured wall-clock duration is recorded
on the result for observability.

**Older-schema gate is resolved ahead of submission (Req 10.5–10.7).** The
dry-run does NOT pause or refuse an older-schema backup. Instead it returns an
``older_schema`` flag together with *both* migration versions so the restore
wizard can present the older-schema confirmation gate before the operator
submits ``POST /restore/full`` with ``confirm_older_schema=true``. The actual
refuse-unless-confirmed enforcement lives in ``restore/full_restore.py`` (task
11.4). A *newer* backup, a *missing* version, or an *unrecognised* version is a
hard FAIL here (Req 10.2, 10.3).

### Schema ordering assumption

Alembic revision identifiers in this repository are **zero-padded, monotonically
increasing numeric strings** — e.g. ``"0194"``, ``"0202"``, ``"0221"`` — minted
in migration order. The schema-compatibility decision is therefore defined by
the **integer value of the leading numeric run** of each revision id
(:func:`parse_revision_order`): a larger number is a *newer* schema. This gives
a total order over the revisions and makes the decision **monotonic in revision
order** (Req 10 / Property 15): if revision *a* < *b* < *c* numerically, then a
backup at *a* is never classified "newer" than a target at *b*, and so on.

The assumption is documented here so it is explicit: should a future revision id
ever omit a parseable leading numeric (e.g. a raw hash like ``"2221e0371bbc"``),
its order cannot be determined by this rule. In that case, when an explicit
``known_revisions`` set is supplied, an unparseable-but-equal pair still compares
``equal``; otherwise the relationship is reported as ``unknown`` and the restore
is refused (the same safe outcome as Req 10.2's unrecognised-version case)
rather than guessed.
"""

from __future__ import annotations

import logging
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Optional

from app.modules.backup_restore.backup.manifest import (
    BackupManifest,
    compute_artifact_checksum,
)
from app.modules.backup_restore.restore.per_org_restore import (
    ArtifactReader,
    BackupUnreadableError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

# Overall dry-run outcome (Req 11.4).
OVERALL_PASS = "PASS"
OVERALL_FAIL = "FAIL"

# Per-step outcomes.
STEP_PASSED = "passed"
STEP_FAILED = "failed"
STEP_WARNING = "warning"  # older-schema: not a failure, but needs confirmation

# Schema comparison outcomes recorded in ``RestoreJob.schema_compare_outcome``
# (Req 10.8 lists "newer, equal, or older"; we add the two error categories of
# Req 10.2 so the recorded value is never ambiguous).
COMPARE_EQUAL = "equal"
COMPARE_OLDER = "older"
COMPARE_NEWER = "newer"
COMPARE_MISSING = "missing"  # no/empty version recorded in the backup (Req 10.2)
COMPARE_UNKNOWN = "unknown"  # recorded but not a known/orderable revision (Req 10.2)

# Decision recorded in ``RestoreJob.restore_decision``. The canonical
# proceeded/refused/cancelled vocabulary of Req 10.8 is written by the *actual*
# full restore (task 11.4); the dry-run records its validation conclusion:
#   - ``proceed``          : schema equal — a subsequent restore may proceed.
#   - ``confirm_required`` : older schema — needs ``confirm_older_schema`` (Req 10.5).
#   - ``refused``          : newer/missing/unknown — restore would be refused.
DECISION_PROCEED = "proceed"
DECISION_CONFIRM_REQUIRED = "confirm_required"
DECISION_REFUSED = "refused"

# Step names.
STEP_CHECKSUM = "checksum_verification"
STEP_SCHEMA = "schema_compatibility"


# ---------------------------------------------------------------------------
# Revision ordering (documented numeric-prefix assumption)
# ---------------------------------------------------------------------------

_LEADING_DIGITS = re.compile(r"^\s*(\d+)")


def parse_revision_order(revision: Optional[str]) -> Optional[int]:
    """Return the integer order of an Alembic *revision* id, or ``None``.

    The order is the integer value of the revision's leading numeric run
    (zero-padding is irrelevant: ``"0194"`` → ``194``). Returns ``None`` when
    *revision* is empty/``None`` or has no parseable leading numeric — its order
    cannot be determined under the documented numeric-prefix assumption.
    """
    if revision is None:
        return None
    match = _LEADING_DIGITS.match(str(revision))
    if match is None:
        return None
    return int(match.group(1))


def _normalise(revision: Optional[str]) -> Optional[str]:
    """Strip a revision id to a non-empty string, or ``None`` if empty."""
    if revision is None:
        return None
    text = str(revision).strip()
    return text or None


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class SchemaCompatResult:
    """The outcome of the Schema_Compatibility_Check (Req 10)."""

    backup_version: Optional[str]
    target_version: Optional[str]
    outcome: str
    """One of ``equal`` / ``older`` / ``newer`` / ``missing`` / ``unknown``."""
    older_schema: bool
    """True only when the backup is *older* than the target (Req 10.5)."""
    decision: str
    """``proceed`` / ``confirm_required`` / ``refused`` (see module constants)."""
    message: str
    """Human-readable summary naming both versions where relevant (Req 10.3/10.5)."""

    @property
    def is_blocking_incompatibility(self) -> bool:
        """Whether this outcome is a hard dry-run FAIL (newer / missing / unknown).

        An *older* schema is NOT blocking here: it is surfaced as a warning with
        the ``older_schema`` flag so the wizard can present the confirmation gate
        (Req 10.5). Only ``newer`` (Req 10.3) and a missing/unrecognised version
        (Req 10.2) make the schema step fail.
        """
        return self.outcome in (COMPARE_NEWER, COMPARE_MISSING, COMPARE_UNKNOWN)


@dataclass
class DryRunStepResult:
    """One validation step's individual outcome (Req 11.4)."""

    name: str
    outcome: str  # passed | failed | warning
    detail: str

    def to_dict(self) -> dict:
        return {"name": self.name, "outcome": self.outcome, "detail": self.detail}


@dataclass
class DryRunResult:
    """The overall dry-run result reported to the Global_Admin (Req 11.4).

    Carries the ``older_schema`` flag plus *both* migration versions so the
    wizard can present the older-schema confirmation gate ahead of submission
    (Req 10.5). It performs/represents no change to the target database.
    """

    overall: str  # PASS | FAIL
    steps: list[DryRunStepResult] = field(default_factory=list)
    checksum_ok: bool = False
    schema: Optional[SchemaCompatResult] = None
    older_schema: bool = False
    backup_version: Optional[str] = None
    target_version: Optional[str] = None
    elapsed_seconds: float = 0.0

    @property
    def passed(self) -> bool:
        return self.overall == OVERALL_PASS

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "checksum_ok": self.checksum_ok,
            "older_schema": self.older_schema,
            "backup_version": self.backup_version,
            "target_version": self.target_version,
            "schema_outcome": self.schema.outcome if self.schema else None,
            "schema_decision": self.schema.decision if self.schema else None,
            "elapsed_seconds": round(self.elapsed_seconds, 4),
            "steps": [s.to_dict() for s in self.steps],
        }


# ---------------------------------------------------------------------------
# Target-version reader (injectable for tests)
# ---------------------------------------------------------------------------


class TargetVersionReader(ABC):
    """Reads the target deployment's current Alembic revision (Req 10.1).

    Injected so the dry-run logic can be tested without a live database: tests
    supply :class:`StaticTargetVersionReader`; production uses
    :class:`AlembicTargetVersionReader` reading the ``alembic_version`` table.
    """

    @abstractmethod
    async def current_revision(self) -> Optional[str]:
        """Return the target deployment's current Alembic revision id, or ``None``."""

    def known_revisions(self) -> Optional[set[str]]:
        """Return the set of revision ids known to the target, or ``None``.

        When a set is returned, a backup version that is *not* a member is
        treated as unrecognised (Req 10.2). The default returns ``None`` (no
        membership constraint — ordering is decided purely by the numeric-prefix
        assumption).
        """
        return None


class StaticTargetVersionReader(TargetVersionReader):
    """A fixed-version reader for tests and direct callers."""

    def __init__(
        self,
        version: Optional[str],
        *,
        known_revisions: Optional[Iterable[str]] = None,
    ) -> None:
        self._version = version
        self._known = (
            {str(r) for r in known_revisions} if known_revisions is not None else None
        )

    async def current_revision(self) -> Optional[str]:
        return self._version

    def known_revisions(self) -> Optional[set[str]]:
        return self._known


class AlembicTargetVersionReader(TargetVersionReader):
    """Reads the current revision from the live ``alembic_version`` table.

    Read-only (a single ``SELECT``); consistent with Req 11.1's no-write rule.
    """

    def __init__(self, session) -> None:
        self._session = session

    async def current_revision(self) -> Optional[str]:
        from sqlalchemy import text

        result = await self._session.execute(
            text("SELECT version_num FROM alembic_version LIMIT 1")
        )
        row = result.first()
        return None if row is None else str(row[0])


# ---------------------------------------------------------------------------
# Pure comparison logic (Req 10.2–10.5)
# ---------------------------------------------------------------------------


def compare_schema_versions(
    backup_version: Optional[str],
    target_version: Optional[str],
    *,
    known_revisions: Optional[set[str]] = None,
) -> SchemaCompatResult:
    """Compare backup vs target Alembic revision (Req 10.2–10.5).

    Decision table (monotonic in numeric revision order — Property 15):

    * backup version missing/empty                  → ``missing``  → refused (10.2)
    * backup not a known revision (when constrained) → ``unknown``  → refused (10.2)
    * backup order or target order undeterminable    → ``unknown``  → refused (10.2)
    * backup numeric == target numeric               → ``equal``    → proceed (10.4)
    * backup numeric  > target numeric               → ``newer``    → refused (10.3)
    * backup numeric  < target numeric               → ``older``    → confirm  (10.5)

    Args:
        backup_version: The Alembic revision recorded in the Backup_Manifest.
        target_version: The target deployment's current Alembic revision.
        known_revisions: Optional set of revisions known to the target; when
            given, a backup version outside it is unrecognised (Req 10.2).
    """
    backup = _normalise(backup_version)
    target = _normalise(target_version)

    # Req 10.2 — missing/empty recorded version.
    if backup is None:
        return SchemaCompatResult(
            backup_version=backup,
            target_version=target,
            outcome=COMPARE_MISSING,
            older_schema=False,
            decision=DECISION_REFUSED,
            message=(
                "the backup does not record a database migration version; the "
                "restore cannot be validated and is refused"
            ),
        )

    # Req 10.2 — recorded but not a known revision in the target deployment.
    if known_revisions is not None and backup not in known_revisions:
        return SchemaCompatResult(
            backup_version=backup,
            target_version=target,
            outcome=COMPARE_UNKNOWN,
            older_schema=False,
            decision=DECISION_REFUSED,
            message=(
                f"the backup migration version {backup!r} does not correspond to "
                f"a known Alembic revision in the target deployment; the restore "
                f"is refused"
            ),
        )

    # Equal revision ids are compatible regardless of numeric parseability
    # (Req 10.4) — this also covers raw-hash revision ids that share an id.
    if target is not None and backup == target:
        return SchemaCompatResult(
            backup_version=backup,
            target_version=target,
            outcome=COMPARE_EQUAL,
            older_schema=False,
            decision=DECISION_PROCEED,
            message=(
                f"backup and target are both at migration version {backup!r}; "
                f"the restore may proceed"
            ),
        )

    backup_order = parse_revision_order(backup)
    target_order = parse_revision_order(target)

    # Ordering undeterminable under the numeric-prefix assumption (Req 10.2 —
    # treat as unrecognised rather than guessing).
    if backup_order is None or target_order is None:
        return SchemaCompatResult(
            backup_version=backup,
            target_version=target,
            outcome=COMPARE_UNKNOWN,
            older_schema=False,
            decision=DECISION_REFUSED,
            message=(
                f"the migration-version relationship between backup {backup!r} "
                f"and target {target!r} could not be determined; the restore is "
                f"refused"
            ),
        )

    if backup_order == target_order:
        # Same numeric order but different id strings — treat as equal/compatible.
        return SchemaCompatResult(
            backup_version=backup,
            target_version=target,
            outcome=COMPARE_EQUAL,
            older_schema=False,
            decision=DECISION_PROCEED,
            message=(
                f"backup version {backup!r} matches the target migration order; "
                f"the restore may proceed"
            ),
        )

    if backup_order > target_order:
        # Req 10.3 — backup newer than target: refuse, naming both versions.
        return SchemaCompatResult(
            backup_version=backup,
            target_version=target,
            outcome=COMPARE_NEWER,
            older_schema=False,
            decision=DECISION_REFUSED,
            message=(
                f"schema incompatibility: the backup migration version {backup!r} "
                f"is newer than the target deployment version {target!r}; the "
                f"restore is refused"
            ),
        )

    # Req 10.5 — backup older than target: surface as an older-schema warning
    # naming both versions and requiring explicit confirmation to proceed.
    return SchemaCompatResult(
        backup_version=backup,
        target_version=target,
        outcome=COMPARE_OLDER,
        older_schema=True,
        decision=DECISION_CONFIRM_REQUIRED,
        message=(
            f"older-schema warning: the backup migration version {backup!r} is "
            f"older than the target deployment version {target!r}; explicit "
            f"confirmation is required to proceed"
        ),
    )


# ---------------------------------------------------------------------------
# Checksum verification (Req 11.2 / 7.4)
# ---------------------------------------------------------------------------


def verify_checksum(manifest: BackupManifest, encrypted_dump: bytes) -> tuple[bool, str]:
    """Re-hash the encrypted dump and compare to the manifest checksum (Req 7.4).

    Returns ``(ok, detail)``. The checksum is computed over ciphertext so no key
    material is needed (see :func:`backup.manifest.compute_artifact_checksum`).
    """
    actual = compute_artifact_checksum(encrypted_dump)
    expected = manifest.catalog.checksum
    if actual == expected:
        return True, (
            f"encrypted-artifact checksum matches the manifest "
            f"({_short(expected)})"
        )
    return False, (
        f"checksum mismatch: the re-hashed encrypted artifact ({_short(actual)}) "
        f"does not match the manifest checksum ({_short(expected)})"
    )


def _short(digest: Optional[str]) -> str:
    if not digest:
        return "<none>"
    return f"{digest[:12]}…" if len(digest) > 12 else digest


# ---------------------------------------------------------------------------
# Dry-run service
# ---------------------------------------------------------------------------


class DryRunService:
    """Validation-only restore check: checksum + schema-compat (Req 10, 11).

    Performs NO write/DDL/data change to the target (Req 11.1, 11.7). All
    external dependencies are injected:

    Args:
        reader: Fetches the manifest + encrypted dump from the chosen backup's
            destination (storage + BDK). Reused from the per-org restore flow so
            the dry-run stays provider-agnostic.
        target_version_reader: Reads the target deployment's current Alembic
            revision (and optionally the known-revision set). Injectable for
            tests via :class:`StaticTargetVersionReader`.
    """

    def __init__(
        self,
        reader: ArtifactReader,
        target_version_reader: TargetVersionReader,
    ) -> None:
        self.reader = reader
        self.target_version_reader = target_version_reader

    async def run(self, restore_job=None) -> DryRunResult:
        """Run the dry-run validation and (when given) record the decision.

        Steps (Req 11.2/11.3), neither of which mutates the target database:
          1. **Checksum verification** — read the manifest + encrypted dump and
             re-hash the ciphertext against the manifest checksum (Req 7.4).
          2. **Schema-compatibility check** — compare the backup's recorded
             Alembic revision to the target's current revision (Req 10).

        When *restore_job* is supplied, the comparison outcome and decision are
        recorded on it (Req 10.8) along with the per-step dry-run detail; the
        caller is responsible for flushing the session (services use
        ``flush()`` + ``await refresh()``, never ``commit()``).

        Returns:
            A :class:`DryRunResult` with overall PASS/FAIL, per-step outcomes,
            the ``older_schema`` flag, and both migration versions (Req 11.4).
        """
        started = time.monotonic()
        steps: list[DryRunStepResult] = []

        # --- Step 1: checksum verification (Req 11.2 / 7.4) ---------------
        checksum_ok, checksum_detail = await self._verify_checksum_step()
        steps.append(
            DryRunStepResult(
                name=STEP_CHECKSUM,
                outcome=STEP_PASSED if checksum_ok else STEP_FAILED,
                detail=checksum_detail,
            )
        )

        # The manifest is needed for the schema version. If it could not be
        # read at all, the checksum step already failed; report the schema step
        # as failed too (no version to compare) and stop — no write occurs.
        manifest = self._manifest
        backup_schema_version = (
            manifest.envelope.schema_version if manifest is not None else None
        )

        # --- Step 2: schema-compatibility check (Req 11.3 / 10) -----------
        target_version = await self.target_version_reader.current_revision()
        known = self.target_version_reader.known_revisions()
        schema = compare_schema_versions(
            backup_schema_version, target_version, known_revisions=known
        )
        if schema.outcome == COMPARE_EQUAL:
            schema_step_outcome = STEP_PASSED
        elif schema.outcome == COMPARE_OLDER:
            schema_step_outcome = STEP_WARNING  # needs confirmation, not a failure
        else:
            schema_step_outcome = STEP_FAILED
        steps.append(
            DryRunStepResult(
                name=STEP_SCHEMA,
                outcome=schema_step_outcome,
                detail=schema.message,
            )
        )

        # --- Overall outcome (Req 11.4/11.5/11.6) -------------------------
        # FAIL on a checksum mismatch (Req 11.5) or a blocking schema
        # incompatibility (Req 11.6: newer/missing/unknown). An older schema is
        # a PASS-with-warning so the wizard can present the confirmation gate.
        overall = (
            OVERALL_PASS
            if checksum_ok and not schema.is_blocking_incompatibility
            else OVERALL_FAIL
        )

        result = DryRunResult(
            overall=overall,
            steps=steps,
            checksum_ok=checksum_ok,
            schema=schema,
            older_schema=schema.older_schema,
            backup_version=schema.backup_version,
            target_version=schema.target_version,
            elapsed_seconds=time.monotonic() - started,
        )

        if restore_job is not None:
            self._record_on_job(restore_job, result)

        return result

    # -- internals ----------------------------------------------------------

    _manifest: Optional[BackupManifest] = None

    async def _verify_checksum_step(self) -> tuple[bool, str]:
        """Read manifest + encrypted dump and verify the checksum (Req 7.4).

        Caches the manifest for the subsequent schema step. Any read failure is
        a checksum-step failure (the artifact is unusable) reported without a
        stack trace and without touching the target (Req 9.10, 11.7).
        """
        try:
            self._manifest = await self.reader.read_manifest()
        except Exception as exc:  # noqa: BLE001 - normalise to a readable failure
            self._manifest = None
            return False, (
                f"the backup manifest could not be read: {_reason(exc)}"
            )

        try:
            encrypted_dump = await self.reader.read_encrypted_dump()
        except Exception as exc:  # noqa: BLE001
            return False, (
                f"the encrypted backup artifact could not be read: {_reason(exc)}"
            )

        return verify_checksum(self._manifest, encrypted_dump)

    @staticmethod
    def _record_on_job(restore_job, result: DryRunResult) -> None:
        """Record the comparison outcome + decision on the Restore_Job (Req 10.8).

        Sets ``schema_compare_outcome`` and ``restore_decision`` and stashes the
        per-step dry-run detail in ``validation_results`` for status polling.
        Mutates the ORM object only; the caller flushes the session.
        """
        schema = result.schema
        if schema is not None:
            restore_job.schema_compare_outcome = schema.outcome
            restore_job.restore_decision = schema.decision
        restore_job.validation_results = {"dry_run": result.to_dict()}
        restore_job.outcome_summary = (
            f"Dry-run {result.overall}: checksum "
            f"{'ok' if result.checksum_ok else 'mismatch'}, schema "
            f"{schema.outcome if schema else 'unknown'}"
        )


def _reason(exc: BaseException) -> str:
    """A short, stack-trace-free reason string for an exception (Req 9.10)."""
    if isinstance(exc, BackupUnreadableError):
        return str(exc)
    text = str(exc).strip()
    return text or exc.__class__.__name__


# Re-export the BackupUnreadableError name for callers that want to catch the
# shared per-org/dry-run unreadable-artifact error type.
__all__ = [
    "OVERALL_PASS",
    "OVERALL_FAIL",
    "STEP_PASSED",
    "STEP_FAILED",
    "STEP_WARNING",
    "STEP_CHECKSUM",
    "STEP_SCHEMA",
    "COMPARE_EQUAL",
    "COMPARE_OLDER",
    "COMPARE_NEWER",
    "COMPARE_MISSING",
    "COMPARE_UNKNOWN",
    "DECISION_PROCEED",
    "DECISION_CONFIRM_REQUIRED",
    "DECISION_REFUSED",
    "parse_revision_order",
    "compare_schema_versions",
    "verify_checksum",
    "SchemaCompatResult",
    "DryRunStepResult",
    "DryRunResult",
    "TargetVersionReader",
    "StaticTargetVersionReader",
    "AlembicTargetVersionReader",
    "DryRunService",
]
