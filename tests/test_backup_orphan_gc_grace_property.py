"""Property-based test: orphan GC respects the configured grace period.

# Feature: cloud-backup-restore, Property 7: Orphan GC respects the grace period

**Validates: Requirements 8.10**

For any generated set of Orphan_Blobs (``backup_blobs`` dedup-index rows that no
committed File_Index references) with varied "continuously unreferenced" ages,
alongside any referenced blobs and any untracked destination objects, after
``BlobPruner.sweep_orphans`` runs with a configured ``orphan_gc_grace_hours`` the
following invariant ALWAYS holds:

* **Grace-period IFF (Req 8.10).** A present Orphan_Blob is deleted IFF it has
  been continuously unreferenced for at least the grace period (boundary
  inclusive, ``unreferenced_for >= grace``) AND is present at the destination.
  An orphan still within the grace period is retained, never deleted.
* **Referenced blobs are never swept.** A blob whose Content_Hash is referenced
  by a committed File_Index is never an orphan: it is neither deleted from the
  destination nor removed from the dedup index, regardless of age.
* **Untracked objects are never deleted.** A destination object with no
  ``backup_blobs`` index row is observed/logged but never deleted.

The DB session and storage adapter are mocked per the project's PBT rule. This
test reuses the ``InMemoryPruner`` (a :class:`BlobPruner` subclass backed by
in-memory ``backups`` / ``blob_refcounts`` / ``backup_blobs`` dicts) and
``FakeStorage`` (which records deletes and answers ``list``) from
``tests.test_backup_prune`` so the property drives the real ``sweep_orphans``
orchestration over generated in-memory state. No real network, cloud SDK, or
database is exercised.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.modules.backup_restore.backup.prune import blob_storage_key
from app.modules.backup_restore.models import Backup, BackupBlob, BackupConfig

# Reuse the in-memory orphan-GC harness from the task-7.1 unit tests.
from tests.test_backup_prune import FakeStorage, InMemoryPruner

# ---------------------------------------------------------------------------
# Hypothesis settings (min 100 iterations)
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Smart generators
# ---------------------------------------------------------------------------


@st.composite
def _scenario(draw):
    """Generate (orphans, referenced, untracked_names, grace_hours).

    * ``grace_hours`` — the configured ``orphan_gc_grace_hours`` (1..72 h).
    * ``orphans`` — 0..8 Orphan_Blobs (no ``blob_refcounts`` row), each with a
      ``last_referenced_at`` an integer number of hours in the past. Integer
      hours are used so the ``>= grace`` boundary is hit *exactly* (inclusive
      boundary coverage), with the age range straddling the grace value so both
      within-grace and past-grace orphans are generated densely. All orphans are
      present at the destination, so the IFF's "AND present" conjunct is true and
      deletion is governed purely by the grace period.
    * ``referenced`` — 0..4 blobs each referenced by a committed File_Index
      (a ``blob_refcounts`` row), present at the destination, with arbitrarily
      old ages — these must never be swept.
    * ``untracked_names`` — 0..4 destination object names with no dedup-index
      row — these must never be deleted.
    """
    grace_hours = draw(st.integers(min_value=1, max_value=72))

    # Orphan ages straddle the grace boundary (0 .. grace*2 + a margin) so the
    # generator densely produces within-grace, exactly-at-grace, and past-grace
    # orphans for the same example.
    max_age = grace_hours * 2 + 24
    n_orphans = draw(st.integers(min_value=0, max_value=8))
    orphan_ages = draw(
        st.lists(
            st.integers(min_value=0, max_value=max_age),
            min_size=n_orphans,
            max_size=n_orphans,
        )
    )
    orphans: list[BackupBlob] = []
    for i, age_hours in enumerate(orphan_ages):
        ts = NOW - timedelta(hours=age_hours)
        orphans.append(
            BackupBlob(
                content_hash=f"orphan-{i:02d}",
                blob_name=f"bn-orphan-{i:02d}",
                byte_size=1,
                first_seen_at=ts,
                last_referenced_at=ts,
            )
        )

    # Referenced blobs: a committed File_Index points at each, so they are not
    # orphans. Arbitrary (possibly very old) ages prove age is irrelevant here.
    n_ref = draw(st.integers(min_value=0, max_value=4))
    ref_ages = draw(
        st.lists(
            st.integers(min_value=0, max_value=10_000),
            min_size=n_ref,
            max_size=n_ref,
        )
    )
    referenced: list[BackupBlob] = []
    refcounts: dict = {}
    for i, age_hours in enumerate(ref_ages):
        ts = NOW - timedelta(hours=age_hours)
        blob = BackupBlob(
            content_hash=f"ref-{i:02d}",
            blob_name=f"bn-ref-{i:02d}",
            byte_size=1,
            first_seen_at=ts,
            last_referenced_at=ts,
        )
        referenced.append(blob)
        refcounts[uuid.uuid4()] = {blob.content_hash}

    # Untracked destination objects: present at the destination but with no
    # dedup-index row (foreign / not platform written).
    n_untracked = draw(st.integers(min_value=0, max_value=4))
    untracked_names = [f"bn-foreign-{i:02d}" for i in range(n_untracked)]

    return orphans, referenced, refcounts, untracked_names, grace_hours


# ---------------------------------------------------------------------------
# Property 7
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(scenario=_scenario())
def test_orphan_gc_respects_grace_period(scenario):
    """An orphan is deleted IFF unreferenced >= grace AND present (Req 8.10)."""
    orphans, referenced, refcounts, untracked_names, grace_hours = scenario

    grace = timedelta(hours=grace_hours)

    # All index-backed blobs (orphans + referenced) are present at the
    # destination, plus the untracked foreign objects.
    all_blobs = orphans + referenced
    present_keys = {blob_storage_key(b.blob_name) for b in all_blobs}
    present_keys |= {blob_storage_key(name) for name in untracked_names}

    # Reliable storage so the delete decision is governed purely by the grace
    # rule (no injected delete failures).
    storage = FakeStorage(present_keys=present_keys)
    blob_map = {b.content_hash: b for b in all_blobs}
    pruner = InMemoryPruner(
        storage,
        backups=[],
        refcounts=refcounts,
        blobs=blob_map,
    )

    config = BackupConfig()
    config.orphan_gc_grace_hours = grace_hours

    outcome = asyncio.run(pruner.sweep_orphans(config, now=NOW))

    deleted = set(outcome.deleted_orphan_hashes)
    retained = set(outcome.retained_orphan_hashes)
    deleted_storage_keys = set(storage.deleted)

    # --- Grace-period IFF for each orphan (Req 8.10) -----------------------
    for orphan in orphans:
        unreferenced_for = NOW - orphan.last_referenced_at  # naive: tz-equal
        past_grace = unreferenced_for >= grace
        h = orphan.content_hash
        key = blob_storage_key(orphan.blob_name)

        if past_grace:
            # Unreferenced >= grace AND present  =>  deleted.
            assert h in deleted, (
                f"orphan {h} unreferenced {unreferenced_for} >= grace {grace} "
                f"was not deleted"
            )
            assert h not in retained, f"deleted orphan {h} also reported retained"
            assert key in deleted_storage_keys, (
                f"orphan {h} reported deleted but destination object {key} survived"
            )
            assert h not in pruner.blobs, (
                f"deleted orphan {h} still present in the dedup index"
            )
        else:
            # Within the grace period  =>  retained, never deleted.
            assert h in retained, (
                f"orphan {h} unreferenced {unreferenced_for} < grace {grace} "
                f"was not retained"
            )
            assert h not in deleted, f"within-grace orphan {h} was deleted"
            assert key not in deleted_storage_keys, (
                f"within-grace orphan {h} destination object {key} was deleted"
            )
            assert h in pruner.blobs, (
                f"within-grace orphan {h} was removed from the dedup index"
            )

    # --- Referenced blobs are never swept ----------------------------------
    for blob in referenced:
        h = blob.content_hash
        key = blob_storage_key(blob.blob_name)
        assert h not in deleted, f"referenced blob {h} was deleted by orphan GC"
        assert h not in retained, f"referenced blob {h} treated as an orphan"
        assert key not in deleted_storage_keys, (
            f"referenced blob {h} destination object {key} was deleted"
        )
        assert h in pruner.blobs, (
            f"referenced blob {h} was removed from the dedup index"
        )

    # --- Untracked destination objects are never deleted -------------------
    for name in untracked_names:
        key = blob_storage_key(name)
        assert key in outcome.untracked_object_keys, (
            f"untracked object {key} was not observed/logged"
        )
        assert key not in deleted_storage_keys, (
            f"untracked object {key} was deleted (only platform orphans may be)"
        )


if __name__ == "__main__":  # pragma: no cover
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
