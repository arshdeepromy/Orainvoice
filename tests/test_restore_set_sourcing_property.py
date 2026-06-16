"""Property-based test: the per-org restore set is sourced strictly from the
chosen backup's File_Index, filtered to the selected organisation.

# Feature: cloud-backup-restore, Property 19: Restore-set is sourced strictly from the chosen backup's File_Index

**Validates: Requirements 24.1, 24.3**

For any File_Index containing entries for multiple organisations (and
global / ``None``-owned entries), restoring a selected organisation ``X`` via
``PerOrgFileRestorer.restore_files`` (``restore/per_org_restore.py``):

* **(Req 24.3)** fetches and writes exactly the File_Index entries whose owning
  ``org_id`` equals ``X`` — never another organisation's file, never a global /
  non-org-owned file, and never a file absent from the chosen index. The set of
  fetched ``Content_Hash`` values equals the content hashes of
  ``filter_file_index_for_org(index, X)``, and the set of written paths equals
  that filtered entry set's paths.
* **(Req 24.1)** the restore set is determined strictly from *this* backup's
  File_Index. Blobs that exist at the destination but are referenced only by a
  *different* backup's index (modelled here as decoy blobs the reader can serve
  but that are absent from the chosen File_Index) are never requested.

Per the project PBT rule the storage/key seam and the filesystem are mocked: an
in-memory ``FakeArtifactReader`` serves File_Blobs by ``Content_Hash`` (returning
bytes whose hash matches the requested entry) and records every requested hash,
and an in-memory ``FakeFileRestoreSink`` records every written path. No real
network, SDK, filesystem, or database is exercised.
"""

from __future__ import annotations

import asyncio

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.modules.backup_restore.backup.cas import content_hash
from app.modules.backup_restore.backup.manifest import FileIndex, FileIndexEntry
from app.modules.backup_restore.restore.per_org_restore import (
    ArtifactReader,
    FileBlobUnavailableError,
    FileRestoreSink,
    PerOrgFileRestorer,
    filter_file_index_for_org,
)

# ---------------------------------------------------------------------------
# Hypothesis settings (min 100 iterations)
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# A small org universe so generated indices reliably mix several orgs plus
# global (``None``-owned) entries. ``None`` is the explicit global/non-org owner.
_OWNERS = (None, "org-A", "org-B", "org-C", "org-D")
_SELECTABLE_ORGS = ("org-A", "org-B", "org-C", "org-D")


# ---------------------------------------------------------------------------
# Test doubles (mocked ArtifactReader + FileRestoreSink)
# ---------------------------------------------------------------------------


class FakeArtifactReader(ArtifactReader):
    """In-memory ArtifactReader that serves File_Blobs by Content_Hash.

    ``read_blob`` returns bytes whose ``content_hash`` matches the requested
    entry (so the restorer's integrity check passes) and records every requested
    hash so the test can assert exactly which blobs were fetched. The other
    artifact seams are never exercised by file restore.
    """

    def __init__(self, blobs: dict[str, bytes]) -> None:
        self._blobs = dict(blobs)
        self.requested_hashes: list[str] = []

    async def read_manifest(self):  # pragma: no cover - unused by file restore
        raise NotImplementedError

    async def read_encrypted_dump(self):  # pragma: no cover - unused
        raise NotImplementedError

    async def read_dump_plaintext(self):  # pragma: no cover - unused
        raise NotImplementedError

    async def read_per_org_export(self, location):  # pragma: no cover - unused
        raise NotImplementedError

    async def read_blob(self, content_hash: str) -> bytes:
        self.requested_hashes.append(content_hash)
        if content_hash not in self._blobs:
            raise FileBlobUnavailableError(
                f"no blob for {content_hash}", file_reference=content_hash
            )
        return self._blobs[content_hash]


class FakeFileRestoreSink(FileRestoreSink):
    """In-memory FileRestoreSink recording every written path -> bytes."""

    def __init__(self) -> None:
        self.written: dict[str, bytes] = {}

    async def exists(self, path: str) -> bool:
        return path in self.written

    async def write_file(self, path: str, data: bytes) -> None:
        self.written[path] = data


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

# One File_Index entry spec: an owning org (or global None) plus the file's
# plaintext bytes (its Content_Hash is derived so the reader can serve it).
_entry_spec = st.fixed_dictionaries(
    {
        "owner": st.sampled_from(_OWNERS),
        "content": st.binary(min_size=0, max_size=24),
    }
)


def _build_index(entry_specs: list[dict]) -> tuple[FileIndex, dict[str, bytes]]:
    """Build a File_Index and its backing blob map from generated specs.

    Paths are made unique by entry position so per-org path sets are disjoint
    across owners; identical content across entries is allowed and naturally
    deduplicates to one Content_Hash (a realistic File_Index property).
    """
    entries: list[FileIndexEntry] = []
    blobs: dict[str, bytes] = {}
    for i, spec in enumerate(entry_specs):
        owner = spec["owner"]
        data = spec["content"]
        digest = content_hash(data)
        owner_seg = "global" if owner is None else owner
        path = f"uploads/receipts/{owner_seg}/{i}-file.bin"
        entries.append(
            FileIndexEntry(
                path=path,
                org_id=owner,
                content_hash=digest,
                byte_size=len(data),
            )
        )
        blobs[digest] = data
    return FileIndex(entries=entries, skipped_count=0), blobs


# ---------------------------------------------------------------------------
# Property 19
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(
    entry_specs=st.lists(_entry_spec, min_size=0, max_size=14),
    selected_org=st.sampled_from(_SELECTABLE_ORGS),
)
def test_restore_set_sourced_strictly_from_chosen_index(
    entry_specs: list[dict], selected_org: str
) -> None:
    """Restoring org X fetches/writes exactly the chosen index's org-X entries."""
    chosen_index, blobs = _build_index(entry_specs)

    # Decoy blobs: present at the destination but referenced only by a *different*
    # backup's File_Index (Req 24.1). The reader can serve them, but a correct
    # restore confined to the chosen index must never request them.
    decoy = {
        content_hash(b"DECOY-" + bytes([k])): b"DECOY-" + bytes([k])
        for k in range(4)
    }
    decoy = {h: d for h, d in decoy.items() if h not in blobs}

    reader = FakeArtifactReader({**blobs, **decoy})
    sink = FakeFileRestoreSink()
    restorer = PerOrgFileRestorer(reader, sink)

    result = asyncio.run(restorer.restore_files(chosen_index, selected_org))

    # The authoritative expectation: strictly the chosen index filtered to X.
    expected_entries = filter_file_index_for_org(chosen_index, selected_org)
    expected_hashes = {e.content_hash for e in expected_entries}
    expected_paths = [e.path for e in expected_entries]

    requested = set(reader.requested_hashes)

    # (Req 24.3) Fetched blobs are exactly the org-X filtered entries' hashes.
    assert requested == expected_hashes

    # (Req 24.3) Written paths are exactly the org-X filtered entries' paths,
    # in index order, with no extras.
    assert result.restored_paths == expected_paths
    assert set(sink.written.keys()) == set(expected_paths)

    # Never another org's / global file: hashes that appear ONLY in non-X
    # entries (i.e. not shared by any org-X entry via dedup) are never fetched.
    x_hashes = {
        e.content_hash
        for e in chosen_index.entries
        if e.org_id is not None and str(e.org_id) == selected_org
    }
    non_x_only_hashes = {
        e.content_hash
        for e in chosen_index.entries
        if not (e.org_id is not None and str(e.org_id) == selected_org)
    } - x_hashes
    assert requested.isdisjoint(non_x_only_hashes)

    # Never another org's / global file written (paths are unique per entry, so
    # non-X entry paths are disjoint from org-X paths by construction).
    other_paths = {e.path for e in chosen_index.entries} - set(expected_paths)
    assert set(sink.written.keys()).isdisjoint(other_paths)

    # (Req 24.1) A blob referenced only by another backup's index is never
    # touched: the restore set is sourced strictly from THIS index.
    assert requested.isdisjoint(set(decoy.keys()))

    # The restored set ⊆ the chosen File_Index entries for org X.
    assert requested.issubset(expected_hashes)

    # Post-restore consistency holds: every intended file is present, nothing
    # is reported missing.
    assert result.missing_references == []
    assert result.file_consistency_outcome == "passed"
