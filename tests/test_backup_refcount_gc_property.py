"""Property-based test: refcount GC never deletes a referenced blob.

# Feature: cloud-backup-restore, Property 6: Refcount GC never deletes a referenced blob

**Validates: Requirements 8.9, 8.12**

For any generated set of backups (varied ages and pruning states), their
``blob_refcounts`` (which Content_Hash each backup's File_Index references), the
content-addressed File_Blobs backing those hashes, and any Retention_Policy
(``retention_count`` / ``retention_days``, either or both possibly unset), after
``BlobPruner.prune`` runs the following invariant ALWAYS holds:

* **No referenced blob is deleted (Req 8.9).** For every File_Blob whose
  Content_Hash is still referenced by at least one *retained* backup (a backup
  whose ``prune_status`` is not ``pruned`` after the run), that blob is NEVER
  deleted from the destination and is NEVER removed from the ``backup_blobs``
  dedup index. Reference-counted pruning may only reclaim a blob referenced
  exclusively by pruned backups.
* **Commit-time safety analog (Req 8.12).** A committed (retained) backup's
  File_Index never ends up pointing at a deleted blob: every Content_Hash a
  surviving backup references survives the prune.

The DB session and storage adapter are mocked per the project's PBT rule. This
test reuses the ``InMemoryPruner`` (a :class:`BlobPruner` subclass backed by
in-memory ``backups`` / ``blob_refcounts`` / ``backup_blobs`` dicts) and
``FakeStorage`` from ``tests.test_backup_prune`` so the property drives the real
``prune`` orchestration over generated in-memory state. No real network, cloud
SDK, or database is exercised.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.modules.backup_restore.backup.prune import (
    PRUNE_FAILED,
    PRUNE_PRUNED,
    PRUNE_RETAINED,
    blob_storage_key,
)
from app.modules.backup_restore.models import Backup, BackupBlob, BackupConfig

# Reuse the in-memory prune harness from the task-7.1 unit tests.
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

# A small fixed pool of content hashes keeps sharing between backups likely, so
# the "shared with a retained backup" case is exercised densely.
_HASH_POOL = [f"hash-{i:02d}" for i in range(8)]


def _blob_name(content_hash: str) -> str:
    """Deterministic blob name per Content_Hash (mirrors CAS keyed naming)."""
    return f"bn-{content_hash}"


# ---------------------------------------------------------------------------
# Smart generators
# ---------------------------------------------------------------------------


@st.composite
def _scenario(draw):
    """Generate (backups, refcounts, blobs, config).

    * ``backups`` — 1..6 backups with varied ages and a pruning state of
      ``retained`` / ``prune_failed`` / ``pruned`` (already-pruned rows must be
      ignored by selection).
    * ``refcounts`` — each backup's File_Index references a subset of the hash
      pool.
    * ``blobs`` — one ``backup_blobs`` row per hash referenced by any backup.
    * ``config`` — a Retention_Policy with ``retention_count`` and/or
      ``retention_days`` possibly unset.
    """
    n = draw(st.integers(min_value=1, max_value=6))

    backups: list[Backup] = []
    refcounts: dict = {}
    for _ in range(n):
        age_days = draw(st.floats(min_value=0.0, max_value=120.0))
        status = draw(
            st.sampled_from([PRUNE_RETAINED, PRUNE_FAILED, PRUNE_PRUNED])
        )
        backup = Backup(
            id=uuid.uuid4(),
            created_at=NOW - timedelta(days=age_days),
            scope="both",
            prune_status=status,
            manifest_key=None,
        )
        refs = draw(
            st.sets(st.sampled_from(_HASH_POOL), min_size=0, max_size=len(_HASH_POOL))
        )
        backups.append(backup)
        refcounts[backup.id] = refs

    # One blob row per hash referenced by any backup.
    referenced_hashes = set().union(*refcounts.values()) if refcounts else set()
    blobs = {
        h: BackupBlob(content_hash=h, blob_name=_blob_name(h), byte_size=1)
        for h in referenced_hashes
    }

    retention_count = draw(st.one_of(st.none(), st.integers(min_value=0, max_value=n)))
    retention_days = draw(
        st.one_of(st.none(), st.integers(min_value=0, max_value=120))
    )
    config = BackupConfig()
    config.retention_count = retention_count
    config.retention_days = retention_days

    return backups, refcounts, blobs, config


# ---------------------------------------------------------------------------
# Property 6
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(scenario=_scenario())
def test_refcount_gc_never_deletes_a_referenced_blob(scenario):
    """A blob referenced by any retained backup is never deleted (Req 8.9, 8.12)."""
    backups, refcounts, blobs, config = scenario

    # Reliable storage so prune-status outcomes are determined purely by the
    # retention policy + refcount GC rule (no injected delete failures).
    storage = FakeStorage()
    pruner = InMemoryPruner(
        storage,
        backups=backups,
        refcounts=refcounts,
        blobs=blobs,
    )

    outcome = asyncio.run(pruner.prune(config, now=NOW))

    # Backups that survived this prune cycle (commit-time "retained" set).
    retained_backups = [
        b for b in backups if b.prune_status != PRUNE_PRUNED
    ]

    # Every Content_Hash still referenced by a retained backup's File_Index.
    referenced_by_retained: set[str] = set()
    for b in retained_backups:
        referenced_by_retained |= set(refcounts.get(b.id, set()))

    deleted_storage_keys = set(storage.deleted)

    for content_hash in referenced_by_retained:
        # The dedup-index row must survive (blob not removed from backup_blobs).
        assert content_hash in pruner.blobs, (
            f"referenced blob {content_hash} was removed from the index"
        )
        # The destination object must never have been deleted.
        assert blob_storage_key(_blob_name(content_hash)) not in deleted_storage_keys, (
            f"referenced blob {content_hash} was deleted from the destination"
        )
        # And it must not appear in the prune outcome's deleted list.
        assert content_hash not in outcome.deleted_blob_hashes, (
            f"referenced blob {content_hash} reported as deleted by prune"
        )


if __name__ == "__main__":  # pragma: no cover
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
