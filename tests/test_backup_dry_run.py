"""Unit tests for dry-run validation + schema-compatibility checks.

# Feature: cloud-backup-restore, task 11.1 — dry-run + schema-compatibility checks

Covers ``app/modules/backup_restore/restore/dry_run.py``:

* **Revision ordering (Req 10).** ``parse_revision_order`` extracts the leading
  numeric run of a zero-padded Alembic revision id; the order is independent of
  padding and undeterminable for a non-numeric id.
* **Schema-compatibility decision (Req 10.2–10.5).** ``compare_schema_versions``
  classifies equal/older/newer/missing/unknown and assigns the matching decision
  (proceed / confirm_required / refused), surfacing the ``older_schema`` flag and
  both migration versions for the wizard's confirmation gate.
* **Checksum verification (Req 11.2 / 7.4).** ``verify_checksum`` re-hashes the
  encrypted dump against the manifest checksum.
* **Dry-run service (Req 11.1, 11.4–11.7, 10.8).** ``DryRunService.run`` reports
  overall PASS/FAIL plus per-step outcomes, performs no write, and records the
  comparison outcome + decision on the Restore_Job.

The artifact reader (storage + BDK) and the target-version reader are both
injected with in-memory fakes so the logic runs with no database, storage, or
filesystem (project unit-test rule).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.modules.backup_restore.backup.manifest import build_manifest
from app.modules.backup_restore.restore.dry_run import (
    COMPARE_EQUAL,
    COMPARE_MISSING,
    COMPARE_NEWER,
    COMPARE_OLDER,
    COMPARE_UNKNOWN,
    DECISION_CONFIRM_REQUIRED,
    DECISION_PROCEED,
    DECISION_REFUSED,
    OVERALL_FAIL,
    OVERALL_PASS,
    STEP_CHECKSUM,
    STEP_FAILED,
    STEP_PASSED,
    STEP_SCHEMA,
    STEP_WARNING,
    DryRunService,
    StaticTargetVersionReader,
    compare_schema_versions,
    parse_revision_order,
    verify_checksum,
)
from app.modules.backup_restore.restore.per_org_restore import (
    ArtifactReader,
    BackupUnreadableError,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeArtifactReader(ArtifactReader):
    """In-memory artifact reader: returns canned manifest + encrypted dump bytes.

    Either field can be set to an Exception to simulate an unreadable artifact.
    """

    def __init__(self, manifest, encrypted_dump):
        self._manifest = manifest
        self._encrypted_dump = encrypted_dump

    async def read_manifest(self):
        if isinstance(self._manifest, Exception):
            raise self._manifest
        return self._manifest

    async def read_encrypted_dump(self) -> bytes:
        if isinstance(self._encrypted_dump, Exception):
            raise self._encrypted_dump
        return self._encrypted_dump

    async def read_dump_plaintext(self) -> bytes:  # pragma: no cover - unused
        raise NotImplementedError

    async def read_per_org_export(self, location: str) -> bytes:  # pragma: no cover
        raise NotImplementedError

    async def read_blob(self, content_hash: str) -> bytes:  # pragma: no cover
        raise NotImplementedError


def _make_manifest(encrypted_dump: bytes, schema_version):
    """Build a manifest whose catalog checksum is over *encrypted_dump*."""
    return build_manifest(
        backup_id="bk-1",
        created_at=datetime(2026, 6, 11, tzinfo=timezone.utc),
        scope="both",
        encrypted_dump=encrypted_dump,
        schema_version=schema_version,
    )


def _new_job():
    return SimpleNamespace(
        schema_compare_outcome=None,
        restore_decision=None,
        validation_results=None,
        outcome_summary=None,
    )


# ---------------------------------------------------------------------------
# parse_revision_order
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "revision,expected",
    [
        ("0194", 194),
        ("0202", 202),
        ("0221", 221),
        ("194", 194),  # padding irrelevant
        ("0221_backup_restore", 221),  # leading numeric run
        ("0001", 1),
        ("", None),
        (None, None),
        ("abc123", None),  # no leading numeric
        ("2221e0371bbc", 2221),  # leading digits parsed
    ],
)
def test_parse_revision_order(revision, expected):
    assert parse_revision_order(revision) == expected


# ---------------------------------------------------------------------------
# compare_schema_versions (Req 10.2–10.5)
# ---------------------------------------------------------------------------


def test_compare_equal_proceeds():
    res = compare_schema_versions("0194", "0194")
    assert res.outcome == COMPARE_EQUAL
    assert res.decision == DECISION_PROCEED
    assert res.older_schema is False
    assert res.is_blocking_incompatibility is False


def test_compare_older_requires_confirmation():
    res = compare_schema_versions("0190", "0194")
    assert res.outcome == COMPARE_OLDER
    assert res.decision == DECISION_CONFIRM_REQUIRED
    assert res.older_schema is True
    # Older is a warning, not a hard incompatibility (wizard presents the gate).
    assert res.is_blocking_incompatibility is False
    # Names both versions (Req 10.5).
    assert "0190" in res.message and "0194" in res.message


def test_compare_newer_refused():
    res = compare_schema_versions("0202", "0194")
    assert res.outcome == COMPARE_NEWER
    assert res.decision == DECISION_REFUSED
    assert res.older_schema is False
    assert res.is_blocking_incompatibility is True
    # Names both versions (Req 10.3).
    assert "0202" in res.message and "0194" in res.message


@pytest.mark.parametrize("missing", [None, "", "   "])
def test_compare_missing_version_refused(missing):
    res = compare_schema_versions(missing, "0194")
    assert res.outcome == COMPARE_MISSING
    assert res.decision == DECISION_REFUSED
    assert res.is_blocking_incompatibility is True


def test_compare_unknown_when_not_in_known_revisions():
    res = compare_schema_versions(
        "0999", "0194", known_revisions={"0194", "0193", "0192"}
    )
    assert res.outcome == COMPARE_UNKNOWN
    assert res.decision == DECISION_REFUSED
    assert res.is_blocking_incompatibility is True


def test_compare_known_member_is_orderable():
    res = compare_schema_versions(
        "0193", "0194", known_revisions={"0194", "0193", "0192"}
    )
    assert res.outcome == COMPARE_OLDER
    assert res.older_schema is True


def test_compare_undeterminable_order_is_unknown():
    # Non-numeric ids that are not equal cannot be ordered → unknown/refused.
    res = compare_schema_versions("abc", "def")
    assert res.outcome == COMPARE_UNKNOWN
    assert res.decision == DECISION_REFUSED


def test_compare_equal_string_ids_compatible_even_if_unparseable():
    res = compare_schema_versions("2221e0371bbc", "2221e0371bbc")
    assert res.outcome == COMPARE_EQUAL
    assert res.decision == DECISION_PROCEED


def test_compare_is_monotonic_across_ordered_revisions():
    # For a < b < c, the decision moves older → equal → newer as the backup
    # version rises relative to a fixed target (monotonicity sanity check).
    revs = ["0100", "0150", "0200"]
    target = "0150"
    assert compare_schema_versions(revs[0], target).outcome == COMPARE_OLDER
    assert compare_schema_versions(revs[1], target).outcome == COMPARE_EQUAL
    assert compare_schema_versions(revs[2], target).outcome == COMPARE_NEWER


# ---------------------------------------------------------------------------
# verify_checksum (Req 11.2 / 7.4)
# ---------------------------------------------------------------------------


def test_verify_checksum_match():
    dump = b"encrypted-artifact-bytes"
    manifest = _make_manifest(dump, "0194")
    ok, detail = verify_checksum(manifest, dump)
    assert ok is True
    assert "matches" in detail


def test_verify_checksum_mismatch():
    manifest = _make_manifest(b"original-bytes", "0194")
    ok, detail = verify_checksum(manifest, b"tampered-bytes")
    assert ok is False
    assert "mismatch" in detail


# ---------------------------------------------------------------------------
# DryRunService.run (Req 11.1, 11.4–11.7, 10.8)
# ---------------------------------------------------------------------------


def _run(reader, target_reader, job=None):
    service = DryRunService(reader, target_reader)
    return asyncio.run(service.run(job))


def _step(result, name):
    return next(s for s in result.steps if s.name == name)


def test_dry_run_pass_on_equal_schema_records_job():
    dump = b"the-encrypted-dump"
    manifest = _make_manifest(dump, "0194")
    reader = FakeArtifactReader(manifest, dump)
    job = _new_job()

    result = _run(reader, StaticTargetVersionReader("0194"), job)

    assert result.overall == OVERALL_PASS
    assert result.checksum_ok is True
    assert result.older_schema is False
    assert result.backup_version == "0194"
    assert result.target_version == "0194"
    assert _step(result, STEP_CHECKSUM).outcome == STEP_PASSED
    assert _step(result, STEP_SCHEMA).outcome == STEP_PASSED
    # Recorded on the job (Req 10.8).
    assert job.schema_compare_outcome == COMPARE_EQUAL
    assert job.restore_decision == DECISION_PROCEED
    assert job.validation_results["dry_run"]["overall"] == OVERALL_PASS


def test_dry_run_older_schema_passes_with_warning_and_flag():
    dump = b"older-schema-dump"
    manifest = _make_manifest(dump, "0190")
    reader = FakeArtifactReader(manifest, dump)
    job = _new_job()

    result = _run(reader, StaticTargetVersionReader("0194"), job)

    # Older schema is surfaced for the confirmation gate, not a hard fail.
    assert result.overall == OVERALL_PASS
    assert result.older_schema is True
    assert result.backup_version == "0190"
    assert result.target_version == "0194"
    assert _step(result, STEP_SCHEMA).outcome == STEP_WARNING
    assert job.schema_compare_outcome == COMPARE_OLDER
    assert job.restore_decision == DECISION_CONFIRM_REQUIRED


def test_dry_run_newer_schema_fails():
    dump = b"newer-schema-dump"
    manifest = _make_manifest(dump, "0202")
    reader = FakeArtifactReader(manifest, dump)
    job = _new_job()

    result = _run(reader, StaticTargetVersionReader("0194"), job)

    assert result.overall == OVERALL_FAIL
    assert result.older_schema is False
    assert _step(result, STEP_CHECKSUM).outcome == STEP_PASSED
    assert _step(result, STEP_SCHEMA).outcome == STEP_FAILED
    assert job.schema_compare_outcome == COMPARE_NEWER
    assert job.restore_decision == DECISION_REFUSED


def test_dry_run_checksum_mismatch_fails():
    manifest = _make_manifest(b"original", "0194")
    # Reader returns different bytes than the manifest was built over.
    reader = FakeArtifactReader(manifest, b"corrupted-bytes")
    job = _new_job()

    result = _run(reader, StaticTargetVersionReader("0194"), job)

    assert result.overall == OVERALL_FAIL
    assert result.checksum_ok is False
    assert _step(result, STEP_CHECKSUM).outcome == STEP_FAILED
    # Schema still compares cleanly (the two gates are independent).
    assert _step(result, STEP_SCHEMA).outcome == STEP_PASSED


def test_dry_run_unreadable_manifest_fails_without_version():
    reader = FakeArtifactReader(
        BackupUnreadableError("manifest gone"), b"whatever"
    )
    job = _new_job()

    result = _run(reader, StaticTargetVersionReader("0194"), job)

    assert result.overall == OVERALL_FAIL
    assert result.checksum_ok is False
    # No schema version could be read → missing → refused.
    assert result.schema.outcome == COMPARE_MISSING
    assert job.restore_decision == DECISION_REFUSED


def test_dry_run_completes_within_reporting_bound():
    # Req 11.4 — naturally fast (hash + integer compare); assert well under 60 s.
    dump = b"x" * 4096
    manifest = _make_manifest(dump, "0194")
    reader = FakeArtifactReader(manifest, dump)
    result = _run(reader, StaticTargetVersionReader("0194"))
    assert result.elapsed_seconds < 60.0
