"""Property-based test: content-addressed dedup — identical content uploads once.

# Feature: cloud-backup-restore, Property 5: Content-addressed dedup — identical content uploads once

**Validates: Requirements 21.3, 21.5**

For any set of file contents (with duplicates) content-addressed into the
:class:`FileBlobStore` (``app/modules/backup_restore/backup/cas.py``):

* **Upload only if absent (Req 21.3).** Identical content is uploaded to the
  destination exactly ONCE. Across many ``put_blob`` calls of the same bytes,
  the storage adapter's ``upload`` is invoked only the first time; every later
  call deduplicates against the ``backup_blobs`` index and performs no upload.
  Hence the number of distinct uploads equals the number of distinct contents.
* **Keyed naming dedupes (Req 21.5).** Identical plaintext always maps to the
  same ``blob_name`` (HMAC-SHA-256 of the plaintext under the platform secret),
  while different plaintext maps to a different ``blob_name`` — so the
  platform's own File_Index deduplicates without exposing plaintext equality.

The DB session and storage adapter are mocked per the project's PBT rule:
``FakeStorage`` records the number of ``upload`` calls per key, and
``FakeAsyncSession`` is an in-memory stand-in for the ``backup_blobs`` dedup
index backing ``db.execute(select(BackupBlob)...)`` / ``db.add`` / ``db.flush``.
No real network, SDK, or database is exercised.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.modules.backup_restore.backup.cas import FileBlobStore, content_hash
from app.modules.backup_restore.models import BackupBlob
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

# A fixed 32-byte Backup_Data_Key and blob-naming HMAC secret keep blob names
# deterministic across examples and keep the store off the settings-resolved
# secret path (the test owns both seams).
_BDK = bytes(range(32))
_HMAC_SECRET = b"property-test-blob-name-hmac-secret-0123456789"


# ---------------------------------------------------------------------------
# Test doubles (mocked storage adapter + in-memory dedup index)
# ---------------------------------------------------------------------------
class FakeStorage(StorageInterface):
    """Storage adapter that records how many times each key was uploaded."""

    def __init__(self) -> None:
        self.upload_counts: dict[str, int] = {}
        self.objects: dict[str, bytes] = {}

    async def upload(
        self,
        key: str,
        source: AsyncByteStream,
        *,
        content_length: int,
        immutable_until=None,
    ) -> UploadResult:
        self.upload_counts[key] = self.upload_counts.get(key, 0) + 1
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
    ``select(BackupBlob).where(BackupBlob.content_hash == <hash>)`` statement
    and looks it up in an in-memory dict; ``add`` stages a row and ``flush``
    commits staged rows into that dict — exactly the lookup/insert seam
    :class:`FileBlobStore` relies on for "upload only if absent".
    """

    def __init__(self) -> None:
        self.store: dict[str, BackupBlob] = {}
        self._pending: list[BackupBlob] = []

    async def execute(self, stmt) -> _FakeResult:
        # The store always queries by equality on content_hash; pull the bound
        # value out of the WHERE clause's right-hand bind parameter.
        hash_value = stmt.whereclause.right.value
        return _FakeResult(self.store.get(hash_value))

    def add(self, obj: BackupBlob) -> None:
        self._pending.append(obj)

    async def flush(self) -> None:
        for obj in self._pending:
            self.store[obj.content_hash] = obj
        self._pending.clear()


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# A set of distinct file contents (uniqueness guarantees distinct Content_Hash
# and distinct HMAC blob_name). Empty content is allowed (a valid empty file).
distinct_contents = st.lists(
    st.binary(min_size=0, max_size=256),
    min_size=1,
    max_size=8,
    unique=True,
)

# Per-content repeat counts; >1 forces duplicate put_blob calls of the same
# bytes so the "upload once" dedup is actually exercised.
repeat_counts = st.lists(st.integers(min_value=1, max_value=4), min_size=1, max_size=8)


def _interleaved_calls(contents: list[bytes], repeats: list[int]) -> list[bytes]:
    """Build a put_blob call order with duplicates interleaved across rounds.

    Pairs each distinct content with a repeat count and emits the contents in
    round-robin order, so duplicate calls of the same bytes are spread out
    rather than adjacent — a stronger exercise of the index-backed dedup.
    """
    pairs = list(zip(contents, repeats))
    order: list[bytes] = []
    for round_idx in range(max(r for _, r in pairs)):
        for data, count in pairs:
            if round_idx < count:
                order.append(data)
    return order


# ---------------------------------------------------------------------------
# Property 5: Content-addressed dedup — identical content uploads once
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(contents=distinct_contents, repeats=repeat_counts)
def test_identical_content_uploads_exactly_once(
    contents: list[bytes], repeats: list[int]
):
    """Identical content uploads once; identical/different plaintext naming.

    **Validates: Requirements 21.3, 21.5**
    """
    # Pair distinct contents with repeat counts (truncate to the shorter list).
    n = min(len(contents), len(repeats))
    distinct = contents[:n]
    call_order = _interleaved_calls(distinct, repeats[:n])

    storage = FakeStorage()
    db = FakeAsyncSession()
    store = FileBlobStore(storage, _BDK, db, hmac_secret=_HMAC_SECRET)

    async def _run():
        results = []
        for data in call_order:
            results.append((data, await store.put_blob(data)))
        return results

    results = asyncio.run(_run())

    # -- Req 21.5: naming is content-stable and content-distinct --------------
    name_by_content: dict[bytes, str] = {}
    for data, ref in results:
        # Each returned blob_name equals the keyed HMAC of the plaintext.
        expected_name = hmac.new(_HMAC_SECRET, data, hashlib.sha256).hexdigest()
        assert ref.blob_name == expected_name
        # Content_Hash is the SHA-256 of the plaintext.
        assert ref.content_hash == content_hash(data) == hashlib.sha256(data).hexdigest()
        # Identical plaintext always maps to the same blob_name.
        if data in name_by_content:
            assert name_by_content[data] == ref.blob_name
        else:
            name_by_content[data] = ref.blob_name

    # Different plaintext maps to different blob_name (naming is injective over
    # the distinct contents): distinct names == distinct contents.
    assert len(set(name_by_content.values())) == len(distinct)

    # -- Req 21.3: upload only if absent — identical content uploads once -----
    # No storage key was uploaded more than once.
    assert all(count == 1 for count in storage.upload_counts.values())
    # Exactly one upload per distinct content (total uploads == distinct count).
    assert len(storage.upload_counts) == len(distinct)
    assert sum(storage.upload_counts.values()) == len(distinct)

    # First time each content is seen it is uploaded (deduped=False); every
    # later identical call deduplicates (deduped=True) and triggers no upload.
    seen: set[bytes] = set()
    for data, ref in results:
        if data in seen:
            assert ref.deduped is True
        else:
            assert ref.deduped is False
            seen.add(data)
