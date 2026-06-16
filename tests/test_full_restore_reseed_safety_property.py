"""Property-based test: a standby is never re-seeded from an unvalidated or
rolled-back primary.

# Feature: cloud-backup-restore, Property 17: A standby is never re-seeded from an unvalidated or rolled-back primary

**Validates: Requirements 12.7, 12.13**

Property 17 (design.md): *For any* full restore, standby re-seed occurs only
after post-restore validation passes on the isolated primary; on validation
failure or rollback, no re-seed is attempted.

``restore/full_restore.py`` executes the canonical Req 12.15 sequence with every
side effect injected. ``StandbyFencer.reseed()`` (the full ``trigger_resync``)
runs **only** on the validation-PASS path (step 6a). On any apply failure or
validation FAIL the service routes through the single rollback path
(``_handle_post_apply_failure``): it rolls the isolated primary back to the
Pre_Restore_Snapshot, leaves every standby fenced, and **never** calls
``reseed`` (Req 12.7, 12.13). A pre-apply cancel stops before any apply and
likewise never re-seeds (Req 12.16).

This test drives :class:`FullRestoreService` with recording fakes for every
seam (no database, storage, subprocess, or HA involved):

* a **recording** ``StandbyFencer`` counting ``fence`` / ``reseed`` /
  ``restore_ha`` calls;
* a **recording** ``SnapshotManager`` counting ``create`` / ``rollback`` /
  ``cleanup`` calls;
* a ``RestoreValidator`` returning a generated PASS/FAIL outcome;
* a ``RestoreApplier`` that either succeeds or raises (generated);
* no-op recording ``MaintenanceController`` and an in-memory ``ArtifactReader``;
* the ``FakeAsyncSession`` + ``RestoreJob`` model used by the job-lifecycle unit
  tests.

The schema-compat re-assertion and the checksum gate are arranged to always
pass (equal schema version, matching checksum) so every run reaches the
apply/validate decision the property is about.

For any generated ``(apply_succeeds, validation_passes, cancel)``:

    reseed called  ⇔  (not cancel) AND apply_succeeds AND validation_passes

and whenever reseed is *not* called because the apply or validation failed, the
rollback to the Pre_Restore_Snapshot IS performed, the standby is left fenced
(``restore_ha`` never called), and ``reseed`` is never called.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.backup_restore.backup.cas import content_hash
from app.modules.backup_restore.backup.manifest import build_manifest
from app.modules.backup_restore.models import RestoreJob
from app.modules.backup_restore.restore.full_restore import (
    CancellationToken,
    FullRestoreService,
    MaintenanceController,
    RestoreApplier,
    RestoreValidator,
    SnapshotManager,
    StandbyFencer,
    ValidationOutcome,
)
from app.modules.backup_restore.restore.dry_run import StaticTargetVersionReader
from app.modules.backup_restore.restore.per_org_restore import ArtifactReader

# ---------------------------------------------------------------------------
# Hypothesis settings (min 100 iterations) — pure in-memory, no I/O.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=200, deadline=None)

_TARGET_SCHEMA_VERSION = "0194"


# ---------------------------------------------------------------------------
# Recording fakes for the injectable seams
# ---------------------------------------------------------------------------


class RecordingFencer(StandbyFencer):
    """Records every fence / reseed / restore_ha call.

    ``reseed`` is the safety-critical operation under test: it must only ever be
    invoked on the validation-PASS path (Req 12.13).
    """

    def __init__(self) -> None:
        self.fence_calls = 0
        self.reseed_calls = 0
        self.restore_ha_calls = 0

    async def fence(self) -> None:
        self.fence_calls += 1

    async def reseed(self) -> None:
        self.reseed_calls += 1

    async def restore_ha(self) -> None:
        self.restore_ha_calls += 1


class RecordingSnapshotManager(SnapshotManager):
    """Records create / rollback / cleanup; rollback proves the Req 12.7 path."""

    def __init__(self) -> None:
        self.create_calls = 0
        self.rollback_calls = 0
        self.cleanup_calls = 0
        self.path = "/tmp/pre_restore_snapshot.dump"

    async def create(self) -> str:
        self.create_calls += 1
        return self.path

    async def rollback(self, snapshot_path: str) -> None:
        self.rollback_calls += 1

    async def cleanup(self, snapshot_path: str) -> None:
        self.cleanup_calls += 1


class RecordingMaintenanceController(MaintenanceController):
    """No-op Maintenance_Mode controller that records enable/disable calls."""

    def __init__(self) -> None:
        self.enable_calls = 0
        self.disable_calls = 0

    async def enable(self) -> None:
        self.enable_calls += 1

    async def disable(self) -> None:
        self.disable_calls += 1


class FlakyApplier(RestoreApplier):
    """A ``pg_restore --clean`` apply that either succeeds or raises (generated)."""

    def __init__(self, succeeds: bool) -> None:
        self.succeeds = succeeds
        self.apply_calls = 0

    async def apply(self, dump_plaintext: bytes) -> None:
        self.apply_calls += 1
        if not self.succeeds:
            raise RuntimeError("simulated pg_restore --clean failure")


class GeneratedValidator(RestoreValidator):
    """Returns a generated PASS/FAIL :class:`ValidationOutcome`."""

    def __init__(self, passes: bool) -> None:
        self.passes = passes
        self.validate_calls = 0

    async def validate(self, manifest) -> ValidationOutcome:
        self.validate_calls += 1
        if self.passes:
            return ValidationOutcome(passed=True, detail="all checks passed")
        return ValidationOutcome(
            passed=False,
            failed_check="row_count",
            detail="simulated post-restore validation failure",
        )


class FakeArtifactReader(ArtifactReader):
    """In-memory artifact reader returning a canned manifest + encrypted dump."""

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


class FakeAsyncSession:
    """Minimal in-memory async session (flush/refresh no-ops, stores rows)."""

    def __init__(self) -> None:
        self.store: dict = {}

    def add(self, obj) -> None:
        self.store[getattr(obj, "id", id(obj))] = obj

    async def flush(self) -> None:
        return None

    async def refresh(self, obj, attribute_names=None) -> None:
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_manifest(*, checksum: str, encrypted_size: int):
    """A manifest whose schema_version equals the target (→ proceed) and whose
    catalog checksum matches the encrypted dump (→ integrity gate passes)."""
    return build_manifest(
        backup_id="bk-reseed-safety",
        created_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
        scope="both",
        checksum=checksum,
        encrypted_artifact_size=encrypted_size,
        org_ids=[str(uuid.uuid4())],
        schema_version=_TARGET_SCHEMA_VERSION,
    )


def _make_service(*, apply_succeeds: bool, validation_passes: bool):
    """Wire a :class:`FullRestoreService` with recording fakes for one run."""
    encrypted_dump = b"encrypted-dump-bytes"
    manifest = _build_manifest(
        checksum=content_hash(encrypted_dump),
        encrypted_size=len(encrypted_dump),
    )
    reader = FakeArtifactReader(manifest, encrypted_dump, dump_plaintext=b"plaintext")
    fencer = RecordingFencer()
    snapshot = RecordingSnapshotManager()
    maintenance = RecordingMaintenanceController()
    applier = FlakyApplier(apply_succeeds)
    validator = GeneratedValidator(validation_passes)
    service = FullRestoreService(
        FakeAsyncSession(),
        reader=reader,
        target_version_reader=StaticTargetVersionReader(_TARGET_SCHEMA_VERSION),
        maintenance=maintenance,
        fencer=fencer,
        snapshot=snapshot,
        applier=applier,
        validator=validator,
    )
    job = RestoreJob(id=uuid.uuid4(), status="queued", progress_pct=0, mode="full")
    return service, job, fencer, snapshot, applier, validator


# ---------------------------------------------------------------------------
# Property 17: a standby is never re-seeded from an unvalidated/rolled-back primary
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(
    apply_succeeds=st.booleans(),
    validation_passes=st.booleans(),
    cancel=st.booleans(),
)
def test_standby_reseed_only_on_validation_pass(apply_succeeds, validation_passes, cancel):
    """reseed() is invoked IFF (not cancel) and apply succeeded and validation
    PASSED; otherwise rollback is performed (when an apply was attempted) and the
    standby is left fenced — never re-seeded.

    **Validates: Requirements 12.7, 12.13**
    """
    service, job, fencer, snapshot, applier, validator = _make_service(
        apply_succeeds=apply_succeeds, validation_passes=validation_passes
    )

    token = CancellationToken()
    if cancel:
        # A pre-apply cancel: the run loop stops at its first pre-apply
        # checkpoint having applied nothing and never re-seeds (Req 12.16).
        token.request()

    result = asyncio.run(service.run(job, cancel_token=token))

    reseed_happened = apply_succeeds and validation_passes and not cancel

    # --- The biconditional at the heart of Property 17 ----------------------
    assert (fencer.reseed_calls > 0) is reseed_happened
    assert result.standby_reseeded is reseed_happened

    if reseed_happened:
        # Success path: applied, validated, re-seeded exactly once, HA resumed,
        # and no rollback of the primary occurred.
        assert applier.apply_calls == 1
        assert validator.validate_calls == 1
        assert fencer.reseed_calls == 1
        assert snapshot.rollback_calls == 0
        assert result.status == "completed"
        return

    # --- Re-seed must NOT have happened in every other case -----------------
    assert fencer.reseed_calls == 0

    if cancel:
        # Pre-apply cancel: nothing was applied, validated, rolled back, or
        # re-seeded; the job is recorded cancelled (Req 12.16).
        assert applier.apply_calls == 0
        assert validator.validate_calls == 0
        assert snapshot.rollback_calls == 0
        assert result.status == "cancelled"
        assert result.destructive_apply_started is False
        return

    # Non-cancel failure path: the destructive apply was attempted, so the
    # service rolled the isolated primary back to the Pre_Restore_Snapshot and
    # left every standby fenced — it never re-seeded and never restored HA on
    # the standby (Req 12.7, 12.13).
    assert applier.apply_calls == 1
    assert snapshot.create_calls == 1
    assert snapshot.rollback_calls == 1
    assert fencer.fence_calls == 1
    assert fencer.restore_ha_calls == 0  # standby stays fenced
    assert result.status == "failed"
