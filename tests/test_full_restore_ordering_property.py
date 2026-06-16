"""Property-based test: the full-restore canonical ordering is always enforced.

# Feature: cloud-backup-restore, Property 16: Full-restore canonical ordering is always enforced

**Validates: Requirements 12.3, 12.10, 12.15**

Property 16 (design.md): *For any* full restore, the operations occur in exactly
the canonical order — enable maintenance → fence every standby → take the
Pre_Restore_Snapshot → ``--clean`` apply → validate → (PASS: re-seed then resume
HA | FAIL: rollback the isolated primary, leave the standby fenced, no re-seed).
**No destructive apply ever occurs before the standby is fenced and the
Pre_Restore_Snapshot exists.**

This test drives :class:`FullRestoreService.run` across many runs with varied
injected outcomes:

* the schema re-assertion result (equal / older+confirm → proceed; older without
  confirmation / newer / missing → refused before any maintenance is enabled),
* which injectable seam (if any) fails, and at which stage
  (maintenance-enable / fence / snapshot before the apply; apply / validation /
  re-seed at or after the apply).

For every run it asserts the canonical-ordering invariant on
``result.executed_phases``:

* whenever the destructive ``APPLY`` phase executes, ``MAINTENANCE_ENABLE``,
  ``FENCE_STANDBY`` and ``SNAPSHOT`` all appear **before** it (Req 12.3/12.10/
  12.15) — the fence (step 2) and snapshot (step 3) always precede the
  destructive ``--clean`` apply;
* a run that aborts in a pre-apply phase (a maintenance / fence / snapshot
  failure, or a refused schema re-assertion) **never** reaches ``APPLY`` and
  leaves the target unchanged;
* the recorded phases are a prefix of the single canonical sequence (no phase is
  ever recorded out of order).

Everything is in-memory: all side-effecting seams (maintenance controller,
standby fencer, snapshot manager, restore applier, validator, artifact reader,
target-version reader) are fakes, and the Restore_Job is driven through a
lightweight in-memory async session + the real :class:`JobService`.
"""

from __future__ import annotations

import asyncio
import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.backup_restore.backup.manifest import build_manifest
from app.modules.backup_restore.jobs import JobService
from app.modules.backup_restore.models import RestoreJob
from app.modules.backup_restore.restore.dry_run import StaticTargetVersionReader
from app.modules.backup_restore.restore.full_restore import (
    CANONICAL_PREAPPLY_ORDER,
    FullRestorePhase,
    FullRestoreService,
    MaintenanceController,
    RestoreApplier,
    SnapshotManager,
    StandbyFencer,
    ValidationOutcome,
    RestoreValidator,
)
from app.modules.backup_restore.restore.per_org_restore import ArtifactReader

# ---------------------------------------------------------------------------
# Hypothesis settings (min 100 iterations) — pure in-memory, no I/O.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=200, deadline=None)

# A fixed target Alembic revision; the backup's schema_version is generated
# relative to it so the schema re-assertion produces each outcome of Req 10.2-7.
_TARGET_REVISION = "0194"


# ---------------------------------------------------------------------------
# In-memory async session (flush()/refresh() per the project session pattern)
# ---------------------------------------------------------------------------


class FakeAsyncSession:
    """Minimal async session: records flush/refresh, stores rows for JobService."""

    def __init__(self, jobs: list[object] | None = None) -> None:
        self.store: dict[uuid.UUID, object] = {}
        for job in jobs or []:
            self.store[job.id] = job
        self.flushes = 0

    def add(self, obj: object) -> None:
        self.store[obj.id] = obj

    async def flush(self) -> None:
        self.flushes += 1

    async def refresh(self, obj: object, *args: Any, **kwargs: Any) -> None:
        # No-op: the in-memory object already holds the latest attribute values.
        return None


# ---------------------------------------------------------------------------
# Fake seams — each can be told to fail so abort/rollback paths are exercised
# ---------------------------------------------------------------------------


class _SeamError(Exception):
    """A generic injected seam failure."""


class FakeMaintenanceController(MaintenanceController):
    def __init__(self, *, fail_enable: bool = False) -> None:
        self.fail_enable = fail_enable
        self.enabled = False
        self.disabled = False

    async def enable(self) -> None:
        if self.fail_enable:
            raise _SeamError("maintenance enable failed")
        self.enabled = True

    async def disable(self) -> None:
        self.disabled = True


class FakeStandbyFencer(StandbyFencer):
    def __init__(self, *, fail_fence: bool = False, fail_reseed: bool = False) -> None:
        self.fail_fence = fail_fence
        self.fail_reseed = fail_reseed
        self.fenced = False
        self.reseeded = False
        self.restored_ha = False

    async def fence(self) -> None:
        if self.fail_fence:
            raise _SeamError("standby could not be isolated")
        self.fenced = True

    async def reseed(self) -> None:
        if self.fail_reseed:
            raise _SeamError("re-seed failed")
        self.reseeded = True

    async def restore_ha(self) -> None:
        self.restored_ha = True


class FakeSnapshotManager(SnapshotManager):
    def __init__(self, *, fail_create: bool = False) -> None:
        self.fail_create = fail_create
        self.created = False
        self.rolled_back = False

    async def create(self) -> str:
        if self.fail_create:
            raise _SeamError("snapshot creation failed")
        self.created = True
        return "/tmp/pre_restore_snapshot.dump"

    async def rollback(self, snapshot_path: str) -> None:
        self.rolled_back = True

    async def cleanup(self, snapshot_path: str) -> None:
        return None


class FakeRestoreApplier(RestoreApplier):
    def __init__(self, *, fail_apply: bool = False) -> None:
        self.fail_apply = fail_apply
        self.applied = False

    async def apply(self, dump_plaintext: bytes) -> None:
        if self.fail_apply:
            raise _SeamError("pg_restore --clean apply failed")
        self.applied = True


class FakeRestoreValidator(RestoreValidator):
    def __init__(self, *, passed: bool = True) -> None:
        self.passed = passed

    async def validate(self, manifest) -> ValidationOutcome:
        if self.passed:
            return ValidationOutcome(passed=True, detail="all checks passed")
        return ValidationOutcome(
            passed=False, failed_check="row_count", detail="row count mismatch"
        )


class FakeArtifactReader(ArtifactReader):
    """In-memory reader returning a manifest + matching encrypted dump bytes."""

    def __init__(self, manifest, encrypted_dump: bytes, dump_plaintext: bytes) -> None:
        self._manifest = manifest
        self._encrypted_dump = encrypted_dump
        self._dump_plaintext = dump_plaintext

    async def read_manifest(self):
        return self._manifest

    async def read_encrypted_dump(self) -> bytes:
        return self._encrypted_dump

    async def read_dump_plaintext(self) -> bytes:
        return self._dump_plaintext

    async def read_per_org_export(self, location: str) -> bytes:  # pragma: no cover
        raise NotImplementedError

    async def read_blob(self, content_hash: str) -> bytes:  # pragma: no cover
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Scenario generator
# ---------------------------------------------------------------------------


class SchemaChoice(str, enum.Enum):
    EQUAL = "equal"                      # proceed (Req 10.4)
    OLDER_CONFIRMED = "older_confirmed"  # proceed with confirm flag (Req 10.6)
    OLDER_UNCONFIRMED = "older_unconfirmed"  # refused (Req 10.7)
    NEWER = "newer"                      # refused (Req 10.3)
    MISSING = "missing"                  # refused (Req 10.2)


class FailStage(str, enum.Enum):
    NONE = "none"
    MAINTENANCE = "maintenance"  # pre-apply abort
    FENCE = "fence"              # pre-apply abort
    SNAPSHOT = "snapshot"        # pre-apply abort
    APPLY = "apply"              # post-apply -> rollback
    VALIDATION = "validation"    # post-apply -> rollback
    RESEED = "reseed"            # after validation PASS


# Schema choices that allow the run to proceed past the schema re-assertion.
_PROCEED_SCHEMAS = {SchemaChoice.EQUAL, SchemaChoice.OLDER_CONFIRMED}
# Fail stages that abort BEFORE the destructive apply ever runs.
_PRE_APPLY_FAILS = {FailStage.MAINTENANCE, FailStage.FENCE, FailStage.SNAPSHOT}


def _schema_version_for(choice: SchemaChoice) -> Optional[str]:
    if choice in (SchemaChoice.EQUAL,):
        return _TARGET_REVISION
    if choice in (SchemaChoice.OLDER_CONFIRMED, SchemaChoice.OLDER_UNCONFIRMED):
        return "0100"  # numerically older than 0194
    if choice == SchemaChoice.NEWER:
        return "0200"  # numerically newer than 0194
    return None  # MISSING


@st.composite
def scenarios(draw):
    schema_choice = draw(st.sampled_from(list(SchemaChoice)))
    fail_stage = draw(st.sampled_from(list(FailStage)))
    encrypted_dump = draw(st.binary(min_size=0, max_size=128))
    dump_plaintext = draw(st.binary(min_size=0, max_size=128))
    return {
        "schema_choice": schema_choice,
        "fail_stage": fail_stage,
        "encrypted_dump": encrypted_dump,
        "dump_plaintext": dump_plaintext,
    }


def _build_service(scenario):
    schema_choice: SchemaChoice = scenario["schema_choice"]
    fail_stage: FailStage = scenario["fail_stage"]
    encrypted_dump: bytes = scenario["encrypted_dump"]
    dump_plaintext: bytes = scenario["dump_plaintext"]

    # The manifest carries the generated schema_version and a checksum computed
    # over the encrypted dump, so the pre-apply checksum gate always passes.
    manifest = build_manifest(
        backup_id="bk-full-restore-ordering",
        created_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
        scope="both",
        encrypted_dump=encrypted_dump,
        org_ids=[str(uuid.uuid4())],
        schema_version=_schema_version_for(schema_choice),
    )

    reader = FakeArtifactReader(manifest, encrypted_dump, dump_plaintext)
    target_reader = StaticTargetVersionReader(_TARGET_REVISION)
    maintenance = FakeMaintenanceController(
        fail_enable=(fail_stage == FailStage.MAINTENANCE)
    )
    fencer = FakeStandbyFencer(
        fail_fence=(fail_stage == FailStage.FENCE),
        fail_reseed=(fail_stage == FailStage.RESEED),
    )
    snapshot = FakeSnapshotManager(fail_create=(fail_stage == FailStage.SNAPSHOT))
    applier = FakeRestoreApplier(fail_apply=(fail_stage == FailStage.APPLY))
    validator = FakeRestoreValidator(passed=(fail_stage != FailStage.VALIDATION))

    job = RestoreJob(id=uuid.uuid4(), status="queued", progress_pct=0, mode="full")
    session = FakeAsyncSession([job])
    service = FullRestoreService(
        session,
        reader=reader,
        target_version_reader=target_reader,
        maintenance=maintenance,
        fencer=fencer,
        snapshot=snapshot,
        applier=applier,
        validator=validator,
        job_service=JobService(session),
    )
    confirm_older = schema_choice == SchemaChoice.OLDER_CONFIRMED
    return service, job, confirm_older


# ---------------------------------------------------------------------------
# Property 16: Full-restore canonical ordering is always enforced
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(scenario=scenarios())
def test_full_restore_canonical_ordering_is_always_enforced(scenario):
    """Whenever APPLY runs, fence + snapshot (and maintenance) preceded it.

    Also: a refused schema re-assertion or a pre-apply seam failure never reaches
    the destructive apply, and the recorded phases never appear out of canonical
    order.

    **Validates: Requirements 12.3, 12.10, 12.15**
    """
    schema_choice: SchemaChoice = scenario["schema_choice"]
    fail_stage: FailStage = scenario["fail_stage"]

    service, job, confirm_older = _build_service(scenario)
    result = asyncio.run(service.run(job, confirm_older_schema=confirm_older))

    phases = result.executed_phases

    # --- Invariant 1: the recorded sequence is a prefix of the canonical order.
    # No phase is ever recorded before a phase that must precede it.
    canonical = [
        FullRestorePhase.SCHEMA_REASSERT,
        FullRestorePhase.CHECKSUM,
        FullRestorePhase.MAINTENANCE_ENABLE,
        FullRestorePhase.FENCE_STANDBY,
        FullRestorePhase.SNAPSHOT,
        FullRestorePhase.APPLY,
        FullRestorePhase.VALIDATE,
    ]
    canonical_index = {p: i for i, p in enumerate(canonical)}
    seen_canonical = [p for p in phases if p in canonical_index]
    for earlier, later in zip(seen_canonical, seen_canonical[1:]):
        assert canonical_index[earlier] < canonical_index[later], (
            f"phases recorded out of canonical order: {earlier} before {later} "
            f"in {[p.value for p in phases]}"
        )

    # --- Invariant 2: the core ordering guarantee of Req 12.3/12.10/12.15.
    # If the destructive APPLY ran, the standby was fenced AND the snapshot was
    # taken AND maintenance was enabled, all strictly before APPLY.
    if FullRestorePhase.APPLY in phases:
        apply_idx = phases.index(FullRestorePhase.APPLY)
        for required in (
            FullRestorePhase.MAINTENANCE_ENABLE,
            FullRestorePhase.FENCE_STANDBY,
            FullRestorePhase.SNAPSHOT,
        ):
            assert required in phases, (
                f"{required} missing although APPLY ran: "
                f"{[p.value for p in phases]}"
            )
            assert phases.index(required) < apply_idx, (
                f"{required} did not precede the destructive APPLY: "
                f"{[p.value for p in phases]}"
            )
        # Every canonical pre-apply phase precedes APPLY (Req 12.15).
        for required in CANONICAL_PREAPPLY_ORDER:
            assert phases.index(required) < apply_idx

    # --- Invariant 3: a refused schema re-assertion or a pre-apply seam failure
    # never reaches the destructive apply (target left unchanged, Req 12.2/12.4).
    schema_proceeds = schema_choice in _PROCEED_SCHEMAS
    aborts_pre_apply = (not schema_proceeds) or (fail_stage in _PRE_APPLY_FAILS)

    if aborts_pre_apply:
        assert FullRestorePhase.APPLY not in phases, (
            "the destructive apply must not run when the restore aborts "
            f"pre-apply: {[p.value for p in phases]}"
        )
        assert result.destructive_apply_started is False
    else:
        # The run proceeded past every pre-apply gate, so APPLY must have run.
        assert FullRestorePhase.APPLY in phases
        assert result.destructive_apply_started is True

    # --- Invariant 4: a refused schema re-assertion stops before maintenance.
    if not schema_proceeds:
        assert FullRestorePhase.MAINTENANCE_ENABLE not in phases
        assert FullRestorePhase.FENCE_STANDBY not in phases
        assert FullRestorePhase.SNAPSHOT not in phases
