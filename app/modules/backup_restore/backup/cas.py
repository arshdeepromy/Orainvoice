"""Content-addressed File_Blob store (cloud-backup-restore Req 21).

The CAS captures the deployment's uploaded files into a deduplicated,
content-addressed, client-side-encrypted blob store on a backup destination.

Design (design.md "Backup Pipeline" step 4/5):

* **Content_Hash** — each file's ``Content_Hash`` is the SHA-256 of its
  *plaintext* bytes. It is the platform's identity for a file's content and is
  what the File_Index / ``blob_refcounts`` reference for dedup and refcount
  pruning (Req 21.3, 21.6).
* **Blob name** — each File_Blob is *named* by an HMAC-SHA-256 of the plaintext
  content under a **platform secret** (not the bare plaintext hash), so the
  Cloud_Provider cannot infer plaintext equality across blobs from their names,
  while the platform's own File_Index still deduplicates (Req 21.5).
* **Upload only if absent** — before uploading a blob the store consults its own
  dedup index (the ``backup_blobs`` table — the platform's record of what is
  already stored) and uploads the blob only when that content is not already
  present, so unchanged or duplicate files dedupe across organisations and
  across time (Req 21.3).
* **Client-side encryption** — every blob is encrypted with
  :func:`backup_envelope_encrypt` under the per-backup **Backup_Data_Key (BDK)**
  before any byte leaves the platform, so destinations only ever store
  ciphertext and the escrowed key material can decrypt every blob on a fresh
  deployment — never under ``ENCRYPTION_MASTER_KEY`` (Req 21.4).
* **Write-through capture** — :meth:`FileBlobStore.capture_file` reads a file's
  bytes and content-addresses them into the store at capture time, giving the
  "write-through CAS" point-in-time consistency model (Req 23 option D).
* **Known-skips** — a file that cannot be read (permission error, broken
  symlink, missing file) is recorded as a *known-skip*: its path and reason are
  retained, it is omitted from the File_Index, the remaining files keep being
  captured, and the skip count is reported (Req 21.9).

The store receives a provider-agnostic :class:`StorageInterface` adapter and a
BDK; it performs no provider-specific logic. Per the project ``get_db_session``
``session.begin()`` auto-commit pattern, DB writes use ``flush()`` /
``await db.refresh()`` and never ``commit()``.

Building the File_Index and ``blob_refcounts`` rows from the captured
:class:`BlobRef` results is the manifest builder's job (task 6.3); this module
is solely the content-addressed blob store.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.modules.backup_restore.keys.key_service import backup_envelope_encrypt
from app.modules.backup_restore.models import BackupBlob
from app.modules.backup_restore.storage.interface import (
    AsyncByteStream,
    StorageInterface,
)

logger = logging.getLogger(__name__)

# Storage-key prefix under which content-addressed blobs are stored. Blobs are
# shared and deduplicated across every backup, so they live in one shared
# location (not under a per-backup prefix), per Req 21.8 / the fan-out step.
DEFAULT_BLOB_PREFIX = "backup_blobs"

# HKDF info label for deriving the blob-naming HMAC secret from the deployment
# secret. Domain separation guarantees this key is distinct from any other use
# of ``encryption_master_key``.
_HMAC_DERIVE_INFO = b"cloud-backup-restore/blob-name-hmac/v1"

_READ_CHUNK = 1024 * 1024  # 1 MiB read chunks for hashing/reading files


@dataclass
class BlobRef:
    """The outcome of content-addressing one piece of content into the store.

    Returned by :meth:`FileBlobStore.put_blob` and :meth:`capture_file`. The
    manifest builder turns a collection of these into the File_Index and
    ``blob_refcounts`` rows (task 6.3).
    """

    content_hash: str
    """SHA-256 hex digest of the plaintext content (Req 21.3/21.6)."""

    blob_name: str
    """HMAC-SHA-256 hex name the blob is stored under (Req 21.5)."""

    storage_key: str
    """Provider-independent key the (encrypted) blob is stored at."""

    byte_size: int
    """Size of the *plaintext* content in bytes (Req 21.6)."""

    deduped: bool
    """``True`` if the content already existed and no upload was performed."""


@dataclass
class KnownSkip:
    """A file that could not be captured and was recorded as a known-skip.

    Omitted from the File_Index but retained with its reason and counted in the
    Backup_Manifest (Req 21.9).
    """

    path: str
    reason: str


@dataclass
class CaptureSummary:
    """Aggregate result of capturing a set of files into the store."""

    blobs: list[BlobRef] = field(default_factory=list)
    """One :class:`BlobRef` per successfully captured file (File_Index input)."""

    skipped: list[KnownSkip] = field(default_factory=list)
    """Known-skips for unreadable/missing files (Req 21.9)."""

    uploaded_count: int = 0
    """Number of blobs actually uploaded this run (i.e. not deduped)."""

    deduped_count: int = 0
    """Number of files whose content was already present (deduped)."""

    @property
    def captured_count(self) -> int:
        """Files successfully content-addressed (deduped or uploaded)."""
        return len(self.blobs)

    @property
    def skipped_count(self) -> int:
        """Count of known-skipped files (reported in the manifest, Req 21.9)."""
        return len(self.skipped)


def _resolve_blob_hmac_secret() -> bytes:
    """Resolve the platform secret used to key the blob-naming HMAC.

    Uses the explicit ``backup_blob_hmac_secret`` setting when configured;
    otherwise derives a stable, deployment-specific key from
    ``encryption_master_key`` via HKDF-SHA256 with domain separation. The
    derived key is a *naming* secret only and never encrypts any artifact
    (artifact encryption is the BDK's job, Req 21.4).
    """
    explicit = (settings.backup_blob_hmac_secret or "").strip()
    if explicit:
        return explicit.encode("utf-8")

    # Derive from the deployment secret with domain separation so the
    # blob-naming key is distinct from the envelope master key's own use.
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    master = settings.encryption_master_key.encode("utf-8")
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_HMAC_DERIVE_INFO)
    return hkdf.derive(master)


def content_hash(data: bytes) -> str:
    """Return the ``Content_Hash`` (SHA-256 hex) of plaintext *data* (Req 21.3)."""
    return hashlib.sha256(data).hexdigest()


def _single_chunk_stream(data: bytes) -> AsyncByteStream:
    """Adapt a single ``bytes`` payload to the adapter's ``AsyncByteStream``."""

    async def _gen() -> AsyncByteStream:  # type: ignore[misc]
        yield data

    return _gen()


class FileBlobStore:
    """Content-addressed, client-side-encrypted, deduplicated File_Blob store.

    Args:
        storage: The provider-agnostic destination adapter (uploads go here).
        bdk: The 256-bit Backup_Data_Key used to envelope-encrypt every blob
            before upload (Req 21.4). Never ``ENCRYPTION_MASTER_KEY``.
        db: Async DB session backing the dedup index (``backup_blobs``).
        blob_prefix: Storage-key prefix for stored blobs.
        hmac_secret: Override for the blob-naming HMAC secret (testing); when
            omitted it is resolved from configuration.
    """

    def __init__(
        self,
        storage: StorageInterface,
        bdk: bytes,
        db: AsyncSession,
        *,
        blob_prefix: str = DEFAULT_BLOB_PREFIX,
        hmac_secret: bytes | None = None,
    ) -> None:
        self.storage = storage
        self.bdk = bdk
        self.db = db
        self.blob_prefix = blob_prefix.rstrip("/")
        self._hmac_secret = hmac_secret if hmac_secret is not None else _resolve_blob_hmac_secret()

    # -- naming -------------------------------------------------------------

    def blob_name(self, data: bytes) -> str:
        """HMAC-SHA-256 (hex) name for plaintext *data* under the platform secret.

        Keyed naming means the destination cannot infer plaintext equality from
        blob names, while identical content still maps to the same name so the
        platform's File_Index deduplicates (Req 21.5).
        """
        return hmac.new(self._hmac_secret, data, hashlib.sha256).hexdigest()

    def storage_key(self, blob_name: str) -> str:
        """Provider-independent storage key a blob is stored under."""
        return f"{self.blob_prefix}/{blob_name}"

    # -- dedup index --------------------------------------------------------

    async def _existing_blob(self, hash_hex: str) -> BackupBlob | None:
        """Return the recorded :class:`BackupBlob` for *hash_hex*, if present."""
        result = await self.db.execute(
            select(BackupBlob).where(BackupBlob.content_hash == hash_hex)
        )
        return result.scalar_one_or_none()

    # -- core put -----------------------------------------------------------

    async def put_blob(
        self,
        data: bytes,
        *,
        immutable_until: datetime | None = None,
    ) -> BlobRef:
        """Content-address *data*: dedup, then encrypt-and-upload if absent.

        Computes the ``Content_Hash`` and HMAC blob name, consults the dedup
        index, and uploads the **encrypted** blob only when that content is not
        already present at the destination (Req 21.3). Identical content always
        resolves to the same blob and is uploaded at most once.

        Returns a :class:`BlobRef` describing the (possibly deduped) blob.
        """
        hash_hex = content_hash(data)
        name = self.blob_name(data)
        key = self.storage_key(name)
        size = len(data)

        existing = await self._existing_blob(hash_hex)
        if existing is not None:
            # Dedup hit — content already stored; do not re-upload (Req 21.3).
            existing.last_referenced_at = datetime.now(timezone.utc)
            await self.db.flush()
            return BlobRef(
                content_hash=hash_hex,
                blob_name=existing.blob_name,
                storage_key=self.storage_key(existing.blob_name),
                byte_size=existing.byte_size,
                deduped=True,
            )

        # Absent — encrypt client-side under the BDK before any byte leaves the
        # platform (Req 21.4), then upload the ciphertext. Encryption is CPU-bound,
        # so run it in a worker thread to keep the event loop responsive during a
        # backup (otherwise concurrent dashboard requests stall / drop).
        ciphertext = await asyncio.to_thread(backup_envelope_encrypt, data, self.bdk)
        await self.storage.upload(
            key,
            _single_chunk_stream(ciphertext),
            content_length=len(ciphertext),
            immutable_until=immutable_until,
        )

        # Record the blob in the dedup index so future identical content dedups.
        blob = BackupBlob(
            content_hash=hash_hex,
            blob_name=name,
            byte_size=size,
        )
        self.db.add(blob)
        await self.db.flush()

        return BlobRef(
            content_hash=hash_hex,
            blob_name=name,
            storage_key=key,
            byte_size=size,
            deduped=False,
        )

    # -- write-through capture ---------------------------------------------

    async def capture_file(
        self,
        path: str,
        *,
        immutable_until: datetime | None = None,
    ) -> BlobRef | KnownSkip:
        """Capture a single file by path into the store (write-through).

        Reads the file's bytes and content-addresses them. A file that cannot be
        read — permission error, broken symlink, or missing file — is returned
        as a :class:`KnownSkip` rather than raising, so the surrounding capture
        loop continues (Req 21.9).
        """
        try:
            data = await asyncio.to_thread(_read_file_bytes, path)
        except OSError as exc:
            reason = f"{type(exc).__name__}: {exc.strerror or exc}"
            logger.warning("CAS skipping unreadable file %s (%s)", path, reason)
            return KnownSkip(path=path, reason=reason)

        return await self.put_blob(data, immutable_until=immutable_until)

    async def capture_paths(
        self,
        paths: list[str],
        *,
        immutable_until: datetime | None = None,
    ) -> CaptureSummary:
        """Capture a list of file paths, aggregating blobs and known-skips.

        Successfully captured files contribute a :class:`BlobRef` (File_Index
        input); unreadable/missing files are recorded as known-skips, omitted
        from the index, and counted (Req 21.9).
        """
        summary = CaptureSummary()
        for path in paths:
            outcome = await self.capture_file(path, immutable_until=immutable_until)
            if isinstance(outcome, KnownSkip):
                summary.skipped.append(outcome)
                continue
            summary.blobs.append(outcome)
            if outcome.deduped:
                summary.deduped_count += 1
            else:
                summary.uploaded_count += 1
        return summary


def _read_file_bytes(path: str) -> bytes:
    """Read a file fully into memory in chunks.

    Raises ``OSError`` (incl. ``FileNotFoundError``/``PermissionError``) for
    unreadable, missing, or broken-symlink paths so the caller can record a
    known-skip (Req 21.9).
    """
    # ``os.path.realpath`` + open surfaces broken symlinks as FileNotFoundError.
    chunks: list[bytes] = []
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(_READ_CHUNK)
            if not chunk:
                break
            chunks.append(chunk)
    return b"".join(chunks)
