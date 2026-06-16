"""Unit tests: blob-name HMAC stability (cloud-backup-restore Req 21.5).

Covers :meth:`FileBlobStore.blob_name` in
``app/modules/backup_restore/backup/cas.py``:

* Same plaintext always yields the same blob name (deterministic / stable).
* Different plaintext yields a different blob name.
* The blob name is *keyed* — it is an HMAC under a platform secret, not a bare
  SHA-256 of the plaintext, so it differs from the plain content hash.
* A different ``hmac_secret`` yields a different blob name for the same content,
  so the Cloud_Provider cannot infer plaintext equality across deployments.

**Validates: Requirements 21.5**

``blob_name`` touches neither the storage adapter nor the DB session, so the
store is constructed with ``None`` for both and an explicit ``hmac_secret``
seam (the same seam the dedup property test uses).
"""

from __future__ import annotations

import hashlib
import hmac

from app.modules.backup_restore.backup.cas import FileBlobStore, content_hash

# Two fixed, distinct platform secrets exercised by the keyed-naming tests.
_SECRET_A = b"unit-test-blob-name-hmac-secret-A-0123456789"
_SECRET_B = b"unit-test-blob-name-hmac-secret-B-9876543210"


def _store(hmac_secret: bytes) -> FileBlobStore:
    """Build a FileBlobStore for naming-only tests (no storage / db needed)."""
    return FileBlobStore(
        storage=None,  # type: ignore[arg-type]
        bdk=bytes(range(32)),
        db=None,  # type: ignore[arg-type]
        hmac_secret=hmac_secret,
    )


def test_same_plaintext_same_blob_name_is_stable():
    """Same plaintext maps to the same blob name across repeated calls."""
    store = _store(_SECRET_A)
    data = b"the quick brown fox"

    first = store.blob_name(data)
    second = store.blob_name(data)
    third = store.blob_name(bytes(data))  # equal-but-distinct object

    assert first == second == third


def test_same_plaintext_same_name_across_store_instances():
    """Two stores with the same secret name identical content identically."""
    data = b"deterministic across instances"
    assert _store(_SECRET_A).blob_name(data) == _store(_SECRET_A).blob_name(data)


def test_different_plaintext_different_blob_name():
    """Different plaintext maps to different blob names under one secret."""
    store = _store(_SECRET_A)
    assert store.blob_name(b"alpha") != store.blob_name(b"beta")


def test_single_byte_difference_changes_blob_name():
    """A one-byte change in plaintext changes the blob name."""
    store = _store(_SECRET_A)
    assert store.blob_name(b"payload-0") != store.blob_name(b"payload-1")


def test_empty_plaintext_has_stable_blob_name():
    """Empty content (a valid empty file) names stably and is keyed."""
    store = _store(_SECRET_A)
    assert store.blob_name(b"") == store.blob_name(b"")
    # Even for empty input the name is keyed, not the bare empty-string hash.
    assert store.blob_name(b"") != hashlib.sha256(b"").hexdigest()


def test_blob_name_is_keyed_hmac_not_bare_sha256():
    """blob_name is the HMAC-SHA-256 under the secret, not the plaintext hash."""
    store = _store(_SECRET_A)
    data = b"keyed not bare"

    expected = hmac.new(_SECRET_A, data, hashlib.sha256).hexdigest()
    assert store.blob_name(data) == expected
    # It must NOT equal the bare SHA-256 (i.e. the Content_Hash) of the content.
    assert store.blob_name(data) != content_hash(data)
    assert store.blob_name(data) != hashlib.sha256(data).hexdigest()


def test_different_secret_yields_different_blob_name():
    """Same content under a different secret produces a different blob name."""
    data = b"same content, different key"
    name_a = _store(_SECRET_A).blob_name(data)
    name_b = _store(_SECRET_B).blob_name(data)
    assert name_a != name_b


def test_blob_name_is_64_hex_chars():
    """A SHA-256 HMAC hex digest is always 64 lowercase hex characters."""
    store = _store(_SECRET_A)
    name = store.blob_name(b"some bytes")
    assert len(name) == 64
    assert all(c in "0123456789abcdef" for c in name)
