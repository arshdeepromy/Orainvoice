"""Property-based test: the end-to-end backup→restore round-trip preserves data.

# Feature: cloud-backup-restore, Property 1: Backup→restore round-trip preserves data

**Validates: Requirements 5.1, 22.1, 24.2**

*For any* valid file set, content-addressing it into a Full_Backup (encrypting
each File_Blob under the per-backup Backup_Data_Key, recording the File_Index
and Backup_Manifest) and then restoring it (re-reading each File_Blob by its
Content_Hash, decrypting under the same key, and writing it back) yields a file
set byte-equivalent to the original — and the manifest round-trips: the org-ID
list, File_Index, and Per_Org_Index recovered under the BDK equal what was
captured.

This is the headline round-trip property at the PURE-LOGIC layer, exercising the
real backup + restore code paths with storage and DB mocked (project PBT rule):

* **Backup (Req 5.1).** Each generated file's bytes are content-addressed
  through the real :class:`FileBlobStore` (``backup/cas.py``) into an in-memory
  ``FakeStorage`` under a fixed Backup_Data_Key — every blob is encrypted
  client-side with :func:`backup_envelope_encrypt` before it lands in storage.
  The captured :class:`BlobRef` results build the real File_Index +
  Backup_Manifest (``backup/manifest.py``), and the manifest is serialised with
  its structure-revealing envelope encrypted under the BDK.
* **Manifest round-trip (Req 5.1 / 7).** The serialised manifest is read back
  with :func:`deserialize_manifest` under the same BDK; the recovered org-ID
  list, File_Index entries, and Per_Org_Index must equal the captured values.
* **Restore (Req 22.1 / 24.2).** The recovered File_Index drives the real
  :class:`PerOrgFileRestorer` (``restore/per_org_restore.py``). For every
  organisation it fetches each entry's File_Blob *by Content_Hash* through a
  ``FakeArtifactReader`` that resolves the blob the same way production does —
  Content_Hash → ``backup_blobs`` index row → stored object → decrypt under the
  BDK — verifies the Content_Hash, and writes the plaintext to a
  ``FakeFileRestoreSink``. Every restored file's bytes must equal the original.

Storage and DB are mocked: ``FakeStorage`` is an in-memory object store and
``FakeAsyncSession`` is an in-memory stand-in for the ``backup_blobs`` dedup
index (the same fakes used by ``test_backup_cas_dedup_property.py``). No real
network, SDK, filesystem, or database is exercised. ``max_examples`` >= 100.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.modules.backup_restore.backup.cas import FileBlobStore, content_hash
from app.modules.backup_restore.backup.manifest import (
    CapturedFile,
    PerOrgEntityCount,
    PerOrgIndexEntry,
    build_file_index,
    build_manifest,
    build_per_org_index,
    deserialize_manifest,
    serialize_manifest,
)
from app.modules.backup_restore.keys.key_service import (
    backup_envelope_decrypt,
    backup_envelope_encrypt,
)
from app.modules.backup_restore.models import BackupBlob
from app.modules.backup_restore.restore.per_org_restore import (
    ArtifactReader,
    FileBlobUnavailableError,
    FileRestoreSink,
    PerOrgFileRestorer,
    filter_file_index_for_org,
)
from app.modules.backup_restore.storage.interface import (
    AsyncByteStream,
    ConnectionState,
    RemoteObject,
    StorageInterface,
    UploadResult,
)

# ---------------------------------------------------------------------------
# Hypothesis settings (min 100 iterations)
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# A fixed 32-byte Backup_Data_Key and blob-naming HMAC secret keep the backup
# deterministic across examples and keep the store off the settings-resolved
# secret path (the test owns both seams). The SAME BDK is used on the restore
# side — a round-trip "with the same key version" (design Property 1).
_BDK = bytes(range(32))
_HMAC_SECRET = b"property-test-roundtrip-blob-name-hmac-secret-0123456789"

# A small org universe so generated file sets reliably mix several orgs.
_ORGS = ("org-A", "org-B", "org-C")


# ---------------------------------------------------------------------------
# Test doubles (mocked storage adapter + in-memory dedup index)
# ---------------------------------------------------------------------------


class FakeStorage(StorageInterface):
    """In-memory object store: records uploaded ciphertext per storage key."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def upload(
        self,
        key: str,
        source: AsyncByteStream,
        *,
        content_length: int,
        immutable_until=None,
    ) -> UploadResult:
        chunks: list[bytes] = []
        async for chunk in source:
            chunks.append(chunk)
        data = b"".join(chunks)
        self.objects[key] = data
        return UploadResult(key=key, size_bytes=len(data), checksum="")

    async def list(self, prefix: str) -> list[RemoteObject]:  # pragma: no cover
        return [
            RemoteObject(key=k, size_bytes=len(v), modified_at=None)
            for k, v in self.objects.items()
            if k.startswith(prefix)
        ]

    async def download(self, key: str) -> AsyncByteStream:  # pragma: no cover
        async def _gen():
            yield self.objects[key]

        return _gen()

    async def delete(self, key: str) -> None:  # pragma: no cover
        self.objects.pop(key, None)

    async def connection_status(self) -> ConnectionState:  # pragma: no cover
        return ConnectionState.connected


class _FakeResult:
    """Stand-in for an SQLAlchemy ``Result`` exposing ``scalar_one_or_none``."""

    def __init__(self, obj: BackupBlob | None) -> None:
        self._obj = obj

    def scalar_one_or_none(self) -> BackupBlob | None:
        return self._obj


class FakeAsyncSession:
    """In-memory stand-in for the ``backup_blobs`` dedup index.

    ``execute`` reads the ``content_hash`` bound value out of the
    ``select(BackupBlob).where(BackupBlob.content_hash == <hash>)`` statement and
    looks it up; ``add``/``flush`` stage and commit rows — the lookup/insert seam
    :class:`FileBlobStore` relies on, and the Content_Hash → blob_name mapping the
    restore reader resolves a blob's stored object name from.
    """

    def __init__(self) -> None:
        self.store: dict[str, BackupBlob] = {}
        self._pending: list[BackupBlob] = []

    async def execute(self, stmt) -> _FakeResult:
        hash_value = stmt.whereclause.right.value
        return _FakeResult(self.store.get(hash_value))

    def add(self, obj: BackupBlob) -> None:
        self._pending.append(obj)

    async def flush(self) -> None:
        for obj in self._pending:
            self.store[obj.content_hash] = obj
        self._pending.clear()


class FakeArtifactReader(ArtifactReader):
    """Restore-side reader that fetches a File_Blob by its Content_Hash.

    Mirrors the production resolution exactly with storage + DB mocked:
    Content_Hash → ``backup_blobs`` dedup-index row (for the stored ``blob_name``)
    → stored ciphertext object in ``FakeStorage`` → decrypt under the BDK. The
    other artifact seams are never exercised by file restore.
    """

    def __init__(
        self,
        storage: FakeStorage,
        db: FakeAsyncSession,
        bdk: bytes,
        *,
        blob_prefix: str = "backup_blobs",
    ) -> None:
        self._storage = storage
        self._db = db
        self._bdk = bdk
        self._blob_prefix = blob_prefix.rstrip("/")
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
        row = self._db.store.get(content_hash)
        if row is None:
            raise FileBlobUnavailableError(
                f"no dedup-index row for {content_hash}", file_reference=content_hash
            )
        key = f"{self._blob_prefix}/{row.blob_name}"
        ciphertext = self._storage.objects.get(key)
        if ciphertext is None:
            raise FileBlobUnavailableError(
                f"no stored object for {content_hash}", file_reference=content_hash
            )
        # Decrypt client-side under the same Backup_Data_Key the backup used.
        return backup_envelope_decrypt(ciphertext, self._bdk)


class FakeFileRestoreSink(FileRestoreSink):
    """In-memory FileRestoreSink recording every written path -> bytes."""

    def __init__(self) -> None:
        self.written: dict[str, bytes] = {}

    async def exists(self, path: str) -> bool:
        return path in self.written

    async def write_file(self, path: str, data: bytes) -> None:
        self.written[path] = data


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# One source file: an owning org plus its plaintext bytes. Empty content is a
# valid (empty) file; duplicate content across files exercises CAS dedup (one
# blob, many File_Index entries) while still round-tripping every path.
_file_spec = st.fixed_dictionaries(
    {
        "org_id": st.sampled_from(_ORGS),
        "content": st.binary(min_size=0, max_size=256),
    }
)

file_sets = st.lists(_file_spec, min_size=0, max_size=12)


# ---------------------------------------------------------------------------
# Property 1: Backup→restore round-trip preserves data
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(files=file_sets)
def test_backup_restore_roundtrip_preserves_data(files: list[dict]) -> None:
    """Backing up a file set then restoring it reproduces every file byte-for-byte.

    **Validates: Requirements 5.1, 22.1, 24.2**
    """
    storage = FakeStorage()
    db = FakeAsyncSession()

    async def _run():
        # -- BACKUP (Req 5.1) -------------------------------------------------
        # Content-address every file through the real CAS into mocked storage;
        # each blob is encrypted client-side under the BDK before it is stored.
        store = FileBlobStore(storage, _BDK, db, hmac_secret=_HMAC_SECRET)
        originals: dict[str, bytes] = {}
        captured: list[CapturedFile] = []
        for i, spec in enumerate(files):
            org = spec["org_id"]
            data = spec["content"]
            # Unique, org-partitioned path per entry so per-org path sets are
            # disjoint and identical content still maps to distinct entries.
            path = f"uploads/receipts/{org}/{i}-file.bin"
            blob_ref = await store.put_blob(data)
            captured.append(CapturedFile(path=path, org_id=org, blob_ref=blob_ref))
            originals[path] = data

        # Build the real File_Index + Per_Org_Index + Backup_Manifest.
        file_index = build_file_index(captured, skipped_count=0)
        org_ids = sorted({spec["org_id"] for spec in files})
        per_org_index = build_per_org_index(
            [
                PerOrgIndexEntry(
                    org_id=o,
                    entities=[
                        PerOrgEntityCount(
                            entity_type="uploaded_files",
                            record_count=sum(
                                1 for c in captured if c.org_id == o
                            ),
                            identifiers=[],
                        )
                    ],
                    logical_export_emitted=False,
                )
                for o in org_ids
            ]
        )
        # A (small) encrypted dump gives the manifest a real checksum/size.
        encrypted_dump = backup_envelope_encrypt(b"--pg_dump custom format--", _BDK)
        manifest = build_manifest(
            backup_id="bk-roundtrip",
            created_at=datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc),
            scope="both",
            encrypted_dump=encrypted_dump,
            file_index=file_index,
            per_org_index=per_org_index,
            org_ids=org_ids,
            app_version="1.13.0",
            schema_version="0194",
            key_version=1,
        )

        # -- MANIFEST ROUND-TRIP (Req 5.1 / 7) -------------------------------
        serialized = serialize_manifest(manifest, _BDK)
        recovered = deserialize_manifest(serialized, _BDK)

        # -- RESTORE (Req 22.1 / 24.2) ---------------------------------------
        # Drive the real per-org file restorer off the *recovered* File_Index.
        reader = FakeArtifactReader(storage, db, _BDK)
        sink = FakeFileRestoreSink()
        restorer = PerOrgFileRestorer(reader, sink)

        results: dict[str, object] = {}
        for org in org_ids:
            results[org] = await restorer.restore_files(
                recovered.envelope.file_index, org
            )

        return originals, captured, file_index, org_ids, recovered, sink, results

    originals, captured, file_index, org_ids, recovered, sink, results = asyncio.run(
        _run()
    )

    # -- Manifest round-trips (org_ids, file_index, per_org_index, catalog) ---
    assert recovered.envelope.org_ids == org_ids

    recovered_entries = recovered.envelope.file_index.entries
    assert len(recovered_entries) == len(captured)
    # Each captured file's File_Index entry survives the encrypt/serialise/decrypt
    # round-trip identically (path, owning org, Content_Hash, byte size).
    recovered_by_path = {e.path: e for e in recovered_entries}
    for c in captured:
        entry = recovered_by_path[c.path]
        assert entry.org_id == c.org_id
        assert entry.content_hash == c.blob_ref.content_hash
        assert entry.content_hash == content_hash(originals[c.path])
        assert entry.byte_size == len(originals[c.path])
    assert recovered.envelope.file_index.skipped_count == 0

    # Per_Org_Index recovered under the BDK matches what was captured.
    recovered_per_org = {e.org_id: e for e in recovered.envelope.per_org_index.entries}
    assert set(recovered_per_org) == set(org_ids)
    for org in org_ids:
        entry = recovered_per_org[org]
        counts = {e.entity_type: e.record_count for e in entry.entities}
        assert counts == {
            "uploaded_files": sum(1 for c in captured if c.org_id == org)
        }

    # Cleartext catalog aggregates stay consistent with the File_Index.
    assert recovered.catalog.file_count == len(captured)
    assert recovered.catalog.file_bytes == sum(
        len(originals[c.path]) for c in captured
    )
    assert recovered.catalog.scope == "both"

    # -- Every per-org restore reports a clean, complete outcome --------------
    for org in org_ids:
        result = results[org]
        expected_paths = [
            e.path for e in filter_file_index_for_org(file_index, org)
        ]
        # Restored exactly this org's File_Index entries (Req 24.2 — fetched by
        # Content_Hash), with the post-restore consistency check passing.
        assert result.restored_paths == expected_paths
        assert result.missing_references == []
        assert result.file_consistency_outcome == "passed"

    # -- Headline round-trip: data goes in, identical data comes back out -----
    # Every captured path was written exactly once across the per-org restores,
    # and its restored bytes are byte-identical to the original (Req 22.1).
    assert set(sink.written.keys()) == set(originals.keys())
    for path, original_bytes in originals.items():
        assert sink.written[path] == original_bytes
