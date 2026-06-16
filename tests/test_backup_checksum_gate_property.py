"""Property-based test: the checksum gate is honoured before any restore write.

# Feature: cloud-backup-restore, Property 14: Checksum gate is honoured before any restore write

**Validates: Requirements 7.4, 7.5, 7.6**

Property 14 (design.md): *For any* restore, if the recomputed checksum of the
downloaded encrypted artifact does not equal the manifest checksum (or the
manifest/checksum is missing), the restore aborts before any data is modified
and the target is unchanged. Conversely, when the recomputed checksum matches
the manifest checksum, the integrity gate passes and the restore may proceed
(Req 7.7).

The checksum is computed over the **encrypted** dump bytes (Req 7.3), so the
gate needs no key material. Two code paths enforce it:

* ``restore/dry_run.py`` — ``verify_checksum`` re-hashes the encrypted dump and
  compares to ``manifest.catalog.checksum``; ``DryRunService.run`` turns a
  mismatch into a checksum-step FAIL / overall FAIL (Req 11.2 / 7.4–7.6).
* ``restore/per_org_restore.py`` — ``PerOrgRestoreService._verify_integrity``
  raises ``BackupUnreadableError`` on a checksum mismatch **before** extraction
  or any write to the ``RestoreTarget`` (Req 7.6, 14.8).

This test drives all three surfaces with everything mocked:

* an in-memory ``ArtifactReader`` fake returning canned encrypted-dump bytes and
  a manifest whose ``catalog.checksum`` is either correct
  (``content_hash(dump)``) or corrupted, and
* a **recording** ``RestoreTarget`` fake that counts every write
  (``insert``/``update``) and every ``set_org_context``/``atomic`` call, so the
  no-write guarantee can be asserted directly.

For any generated encrypted-dump bytes and a match/mismatch choice:

* **Match** → ``verify_checksum`` returns ``True``, the dry-run PASSes, and the
  per-org restore proceeds past the integrity gate (no ``BackupUnreadableError``).
* **Mismatch** → ``verify_checksum`` returns ``False``, the dry-run FAILs, and
  the per-org restore raises ``BackupUnreadableError`` with **zero** writes to
  the recording target (and the org RLS context is never even set).

No database, storage, or filesystem is involved.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Mapping

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import Column, MetaData, String, Table

from app.modules.backup_restore.backup.cas import content_hash
from app.modules.backup_restore.backup.manifest import build_manifest
from app.modules.backup_restore.restore.dry_run import (
    OVERALL_FAIL,
    OVERALL_PASS,
    STEP_CHECKSUM,
    STEP_FAILED,
    STEP_PASSED,
    DryRunService,
    StaticTargetVersionReader,
    verify_checksum,
)
from app.modules.backup_restore.restore.per_org_restore import (
    ArtifactReader,
    BackupUnreadableError,
    ConflictPolicy,
    DumpExtractor,
    ExtractedDataset,
    ExtractedRow,
    FileRestoreSink,
    PerOrgRestoreService,
    RestoreTarget,
    SchemaModel,
)

# ---------------------------------------------------------------------------
# Hypothesis settings (min 100 iterations) — pure in-memory, no I/O.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=200, deadline=None)

# A tiny synthetic schema keeps SchemaModel construction cheap (no need to import
# the live ~132-table metadata); the apply runs over an empty dataset on the
# match path, so the schema is barely exercised.
_TEST_METADATA = MetaData()
Table(
    "alpha",
    _TEST_METADATA,
    Column("id", String, primary_key=True),
    Column("org_id", String, nullable=False),
)
_SCHEMA = SchemaModel(metadata=_TEST_METADATA)

_TARGET_SCHEMA_VERSION = "0194"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeArtifactReader(ArtifactReader):
    """In-memory artifact reader returning a canned manifest + encrypted dump.

    The full dump plaintext is also canned for the scratch-DB extraction path,
    but extraction is only reached on the match path (after the gate passes).
    """

    def __init__(self, manifest, encrypted_dump: bytes, dump_plaintext: bytes = b"") -> None:
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


class _NoopTxn:
    """Async context manager standing in for the apply transaction."""

    def __init__(self, target: "RecordingRestoreTarget") -> None:
        self._target = target

    async def __aenter__(self) -> "_NoopTxn":
        self._target.atomic_entered += 1
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class RecordingRestoreTarget(RestoreTarget):
    """A :class:`RestoreTarget` that records every write and context call.

    The property's no-write guarantee is asserted against these counters: a
    failed checksum gate must abort before any of them is touched.
    """

    def __init__(self) -> None:
        self.writes = 0  # insert + update calls
        self.insert_calls = 0
        self.update_calls = 0
        self.set_org_context_calls = 0
        self.atomic_entered = 0

    async def set_org_context(self, org_id: str) -> None:
        self.set_org_context_calls += 1

    def atomic(self) -> _NoopTxn:
        return _NoopTxn(self)

    async def org_row_exists(self, table, pk_columns, pk) -> bool:
        return False

    async def shared_global_equivalent(self, table, row, pk_columns):
        return None

    async def insert(self, table: str, values: Mapping[str, Any]) -> None:
        self.insert_calls += 1
        self.writes += 1

    async def update(self, table, pk_columns, pk, values) -> None:
        self.update_calls += 1
        self.writes += 1


class EmptyDumpExtractor(DumpExtractor):
    """Returns an empty dataset so the match-path apply performs zero writes.

    Records whether it was reached, so we can confirm a failed checksum gate
    never advances to extraction.
    """

    def __init__(self) -> None:
        self.calls = 0

    async def extract_org(self, dump_plaintext, org_id, schema) -> ExtractedDataset:
        self.calls += 1
        return ExtractedDataset(org_id=str(org_id))


class NoopFileSink(FileRestoreSink):
    async def exists(self, path: str) -> bool:  # pragma: no cover - files skipped
        return False

    async def write_file(self, path: str, data: bytes) -> None:  # pragma: no cover
        raise AssertionError("no file write expected in the checksum-gate test")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_manifest(*, checksum: str, org_id: str, encrypted_size: int):
    """Build a manifest with an explicit catalog checksum and one contained org."""
    return build_manifest(
        backup_id="bk-checksum-gate",
        created_at=datetime(2026, 6, 11, tzinfo=timezone.utc),
        scope="both",
        checksum=checksum,
        encrypted_artifact_size=encrypted_size,
        org_ids=[org_id],
        schema_version=_TARGET_SCHEMA_VERSION,
    )


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------


@st.composite
def gate_scenarios(draw):
    """Generate (encrypted_dump, should_match, manifest_checksum, org_id).

    ``manifest_checksum`` is the correct ``content_hash(dump)`` when
    ``should_match`` is true, otherwise the hash of a *different* byte string
    (guaranteed distinct), modelling a corrupted/tampered manifest checksum.
    """
    dump = draw(st.binary(min_size=0, max_size=256))
    should_match = draw(st.booleans())
    correct = content_hash(dump)

    if should_match:
        manifest_checksum = correct
    else:
        # A checksum over different bytes — distinct from the dump's hash.
        other = draw(st.binary(min_size=0, max_size=256).filter(
            lambda b: content_hash(b) != correct
        ))
        manifest_checksum = content_hash(other)

    org_id = draw(st.uuids().map(str))
    return {
        "dump": dump,
        "should_match": should_match,
        "manifest_checksum": manifest_checksum,
        "correct_checksum": correct,
        "org_id": org_id,
    }


# ---------------------------------------------------------------------------
# Property 14: Checksum gate is honoured before any restore write
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(scenario=gate_scenarios())
def test_checksum_gate_honoured_before_any_restore_write(scenario):
    """Match → gate passes; mismatch → gate fails AND zero writes occur.

    Exercises all three checksum-gate surfaces:
      * ``verify_checksum`` (pure compare),
      * ``DryRunService.run`` (PASS/FAIL on the checksum step), and
      * ``PerOrgRestoreService.restore`` (raises ``BackupUnreadableError`` before
        any write to the recording ``RestoreTarget``).

    **Validates: Requirements 7.4, 7.5, 7.6**
    """
    dump: bytes = scenario["dump"]
    should_match: bool = scenario["should_match"]
    manifest_checksum: str = scenario["manifest_checksum"]
    org_id: str = scenario["org_id"]

    manifest = _build_manifest(
        checksum=manifest_checksum,
        org_id=org_id,
        encrypted_size=len(dump),
    )

    # --- Surface 1: pure verify_checksum (Req 7.4) --------------------------
    ok, _detail = verify_checksum(manifest, dump)
    assert ok is should_match

    # --- Surface 2: DryRunService gate (Req 11.2 / 7.4–7.6) -----------------
    dry_reader = FakeArtifactReader(manifest, dump)
    dry_service = DryRunService(
        dry_reader, StaticTargetVersionReader(_TARGET_SCHEMA_VERSION)
    )
    dry_result = asyncio.run(dry_service.run())
    checksum_step = next(s for s in dry_result.steps if s.name == STEP_CHECKSUM)

    if should_match:
        assert dry_result.checksum_ok is True
        assert checksum_step.outcome == STEP_PASSED
        # Equal schema + matching checksum → overall PASS (Req 7.7).
        assert dry_result.overall == OVERALL_PASS
    else:
        assert dry_result.checksum_ok is False
        assert checksum_step.outcome == STEP_FAILED
        # A checksum mismatch is always an overall FAIL (Req 7.6).
        assert dry_result.overall == OVERALL_FAIL

    # --- Surface 3: per-org restore gate + no-write guarantee (Req 7.6) -----
    target = RecordingRestoreTarget()
    extractor = EmptyDumpExtractor()
    reader = FakeArtifactReader(manifest, dump, dump_plaintext=b"dump-plaintext")
    service = PerOrgRestoreService(
        reader,
        target,
        extractor,
        NoopFileSink(),
        schema=_SCHEMA,
    )

    async def _restore():
        return await service.restore(
            org_id, ConflictPolicy.SKIP, restore_files=False
        )

    if should_match:
        # Gate passes: the restore proceeds past integrity without raising the
        # integrity error. Extraction is reached (empty dataset → no writes).
        result = asyncio.run(_restore())
        assert result.org_id == org_id
        assert extractor.calls == 1
        # Proceeded past the gate: org RLS context was set for the apply.
        assert target.set_org_context_calls == 1
        # Empty dataset → still zero data writes, but the gate did NOT block.
        assert target.writes == 0
    else:
        # Gate fails: BackupUnreadableError BEFORE any write (Req 7.6, 14.8).
        raised = False
        try:
            asyncio.run(_restore())
        except BackupUnreadableError:
            raised = True
        assert raised, "checksum mismatch must abort the restore"
        # No write occurred and the restore never advanced to extraction or
        # even set the org RLS context — the target is wholly untouched.
        assert target.writes == 0
        assert target.insert_calls == 0
        assert target.update_calls == 0
        assert target.set_org_context_calls == 0
        assert target.atomic_entered == 0
        assert extractor.calls == 0
