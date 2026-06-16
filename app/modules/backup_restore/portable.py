"""Portable backup bundles — export a backup as a single self-contained file,
and (re)read one for a destination-less restore.

A committed Full_Backup is normally spread across several objects at a
destination: the encrypted ``dump.enc``, the ``manifest.json``, and many
content-addressed File_Blobs under ``blobs/``. That layout is great for dedup
and incremental upload, but it makes "grab one backup and take it elsewhere"
awkward.

This module packages a backup into a single **portable bundle** — an
uncompressed ``.tar`` — that is fully self-contained:

```
bundle.json            # cleartext metadata (format, backup_id, key_version, scope…)
manifest.json          # the backup's manifest object, exactly as stored (still
                       #   encrypted-envelope; readable only with the BDK)
dump.enc               # the encrypted pg_dump, exactly as stored
blobs/<content_hash>   # each referenced File_Blob, exactly as stored, but named
                       #   by its Content_Hash so the bundle needs no database
```

Crucially the bundle carries **only ciphertext** — the dump, manifest envelope,
and blobs stay encrypted under the per-backup Backup_Data_Key. It does NOT
contain the Recovery Kit or passphrase: those remain the operator's separate
secret and are supplied at restore time to unwrap the BDK (the same fresh-server
DR path as Req 16.7). So a leaked bundle is useless without the key material.

Blobs are renamed to their Content_Hash (instead of the CAS HMAC blob-name)
specifically so a restore reading the bundle never needs the ``backup_blobs``
mapping table — which does not exist yet on a freshly-provisioned server.
"""

from __future__ import annotations

import json
import logging
import os
import tarfile
import tempfile
import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.backup_restore.backup.cas import DEFAULT_BLOB_PREFIX
from app.modules.backup_restore.backup.prune import (
    blob_storage_key,
    dump_storage_key,
)
from app.modules.backup_restore.models import Backup
from app.modules.backup_restore.storage.interface import StorageInterface

logger = logging.getLogger(__name__)

BUNDLE_FORMAT = "orainvoice_backup_bundle/v1"
_BUNDLE_META_NAME = "bundle.json"
_BUNDLE_MANIFEST_NAME = "manifest.json"
_BUNDLE_DUMP_NAME = "dump.enc"
_BUNDLE_BLOB_DIR = "blobs"

_DOWNLOAD_CHUNK = 8 * 1024 * 1024  # stream artifacts to disk in 8 MiB chunks


class BundleError(Exception):
    """Raised when a portable bundle cannot be built or read."""


@dataclass
class BundleMetadata:
    """Cleartext bundle metadata (mirrors the cleartext backup catalog fields)."""

    format: str
    backup_id: str
    key_version: Optional[int]
    scope: Optional[str]
    app_version: Optional[str]
    schema_version: Optional[str]
    created_at: Optional[str]
    dump_checksum: Optional[str]
    blob_count: int

    def to_json(self) -> bytes:
        return json.dumps(
            {
                "format": self.format,
                "backup_id": self.backup_id,
                "key_version": self.key_version,
                "scope": self.scope,
                "app_version": self.app_version,
                "schema_version": self.schema_version,
                "created_at": self.created_at,
                "dump_checksum": self.dump_checksum,
                "blob_count": self.blob_count,
            },
            indent=2,
        ).encode("utf-8")

    @classmethod
    def from_json(cls, raw: bytes) -> "BundleMetadata":
        try:
            d = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise BundleError(f"bundle.json is not valid JSON: {exc}") from exc
        if d.get("format") != BUNDLE_FORMAT:
            raise BundleError(f"unsupported bundle format {d.get('format')!r}")
        return cls(
            format=d["format"],
            backup_id=str(d.get("backup_id")),
            key_version=d.get("key_version"),
            scope=d.get("scope"),
            app_version=d.get("app_version"),
            schema_version=d.get("schema_version"),
            created_at=d.get("created_at"),
            dump_checksum=d.get("dump_checksum"),
            blob_count=int(d.get("blob_count", 0)),
        )


async def _blob_names_for_backup(
    db: AsyncSession, backup_id: uuid.UUID
) -> dict[str, str]:
    """Return ``{content_hash: blob_name}`` for every blob this backup references.

    Joins ``blob_refcounts`` (what this backup references) with ``backup_blobs``
    (the CAS dedup index that maps a Content_Hash to its stored blob name).
    """
    rows = await db.execute(
        text(
            """
            SELECT bb.content_hash, bb.blob_name
            FROM blob_refcounts br
            JOIN backup_blobs bb ON bb.content_hash = br.content_hash
            WHERE br.backup_id = :bid
            """
        ),
        {"bid": str(backup_id)},
    )
    return {r[0]: r[1] for r in rows.fetchall()}


async def _stream_to_file(storage: StorageInterface, key: str, dest_path: str) -> None:
    """Download the object at *key* to *dest_path*, streaming in chunks."""
    stream = await storage.download(key)
    with open(dest_path, "wb") as fh:
        async for chunk in stream:
            fh.write(chunk)


async def build_backup_bundle(
    db: AsyncSession,
    storage: StorageInterface,
    backup: Backup,
    *,
    blob_prefix: str = DEFAULT_BLOB_PREFIX,
    work_dir: Optional[str] = None,
) -> str:
    """Assemble a portable bundle ``.tar`` for *backup* and return its file path.

    Streams the dump, manifest, and every referenced File_Blob from the
    destination into a temp working directory, then tars it. The caller owns the
    returned path and must delete it (and may delete its parent temp dir) after
    streaming it to the client.
    """
    base = tempfile.mkdtemp(prefix="ora-bundle-", dir=work_dir)
    staging = os.path.join(base, "stage")
    os.makedirs(os.path.join(staging, _BUNDLE_BLOB_DIR), exist_ok=True)

    # Manifest (exactly as stored — still envelope-encrypted).
    manifest_key = backup.manifest_key or f"backups/{backup.id}/manifest.json"
    await _stream_to_file(
        storage, manifest_key, os.path.join(staging, _BUNDLE_MANIFEST_NAME)
    )
    # Encrypted dump.
    await _stream_to_file(
        storage, dump_storage_key(backup.id), os.path.join(staging, _BUNDLE_DUMP_NAME)
    )

    # Referenced File_Blobs, renamed to their Content_Hash so the bundle is
    # self-contained (no backup_blobs table needed on restore).
    blob_map = await _blob_names_for_backup(db, backup.id)
    written = 0
    for content_hash, blob_name in blob_map.items():
        key = blob_storage_key(blob_name, prefix=blob_prefix)
        dest = os.path.join(staging, _BUNDLE_BLOB_DIR, content_hash)
        try:
            await _stream_to_file(storage, key, dest)
            written += 1
        except Exception as exc:  # noqa: BLE001 - a missing blob must not be silent
            raise BundleError(
                f"could not read File_Blob {content_hash} from the destination: {exc}"
            ) from exc

    meta = BundleMetadata(
        format=BUNDLE_FORMAT,
        backup_id=str(backup.id),
        key_version=backup.key_version,
        scope=backup.scope,
        app_version=backup.app_version,
        schema_version=backup.schema_version,
        created_at=backup.created_at.isoformat() if backup.created_at else None,
        dump_checksum=backup.dump_checksum,
        blob_count=written,
    )
    with open(os.path.join(staging, _BUNDLE_META_NAME), "wb") as fh:
        fh.write(meta.to_json())

    tar_path = os.path.join(base, f"backup-{backup.id}.tar")
    # Build the tar from the staging dir (offloaded so we never block the loop).
    import asyncio

    def _make_tar() -> None:
        with tarfile.open(tar_path, "w") as tar:
            for name in sorted(os.listdir(staging)):
                tar.add(os.path.join(staging, name), arcname=name)

    await asyncio.to_thread(_make_tar)
    return tar_path



# ---------------------------------------------------------------------------
# BundleArtifactReader — reads artifacts from an unpacked bundle on disk,
# decrypting with a provided BDK. No StorageInterface, no database needed.
# ---------------------------------------------------------------------------


class BundleArtifactReader:
    """An :class:`ArtifactReader` backed by an unpacked portable bundle on disk.

    Satisfies the same contract as ``StorageArtifactReader`` so the full-restore
    service can drive from it transparently. The bundle directory must contain
    ``manifest.json``, ``dump.enc``, and ``blobs/<content_hash>`` — the exact
    layout produced by :func:`build_backup_bundle`.

    No database dependency: blobs are named by their content hash in the bundle,
    so there is no need to resolve a ``backup_blobs`` row. This is critical for
    a fresh-server restore where nothing exists in the DB yet.
    """

    def __init__(self, bundle_dir: str, bdk: bytes) -> None:
        self._dir = bundle_dir
        self._bdk = bdk
        self._encrypted_dump: bytes | None = None

    def _read_file(self, name: str) -> bytes:
        path = os.path.join(self._dir, name)
        if not os.path.isfile(path):
            raise BundleError(f"missing artifact {name!r} in the uploaded bundle")
        with open(path, "rb") as fh:
            return fh.read()

    async def read_manifest(self):
        """Return the decrypted BackupManifest from the bundle."""
        import asyncio

        from app.modules.backup_restore.backup.manifest import deserialize_manifest

        raw = await asyncio.to_thread(self._read_file, _BUNDLE_MANIFEST_NAME)
        return deserialize_manifest(raw, self._bdk)

    async def read_encrypted_dump(self) -> bytes:
        import asyncio

        if self._encrypted_dump is None:
            self._encrypted_dump = await asyncio.to_thread(
                self._read_file, _BUNDLE_DUMP_NAME
            )
        return self._encrypted_dump

    async def read_dump_plaintext(self) -> bytes:
        import asyncio

        from app.modules.backup_restore.keys.key_service import backup_envelope_decrypt

        encrypted = await self.read_encrypted_dump()
        return await asyncio.to_thread(backup_envelope_decrypt, encrypted, self._bdk)

    async def read_per_org_export(self, location: str) -> bytes:
        """Per-org exports are not stored in the bundle (they are provider-side).

        Always raises so the restore falls back to the scratch-DB path.
        """
        from app.modules.backup_restore.restore.per_org_restore import PerOrgExportError

        raise PerOrgExportError(
            "Per_Org_Logical_Export is not included in a portable bundle; "
            "the restore will use the scratch-DB extraction path."
        )

    async def read_blob(self, content_hash: str) -> bytes:
        """Read and decrypt a File_Blob from the bundle's blobs/ directory."""
        import asyncio

        from app.modules.backup_restore.keys.key_service import backup_envelope_decrypt
        from app.modules.backup_restore.restore.per_org_restore import (
            FileBlobUnavailableError,
        )

        blob_path = os.path.join(self._dir, _BUNDLE_BLOB_DIR, content_hash)
        if not os.path.isfile(blob_path):
            raise FileBlobUnavailableError(
                f"File_Blob {content_hash} is missing from the uploaded bundle.",
                file_reference=content_hash,
            )
        ciphertext = await asyncio.to_thread(lambda: open(blob_path, "rb").read())
        return backup_envelope_decrypt(ciphertext, self._bdk)


def unpack_bundle(tar_path: str, dest_dir: str) -> BundleMetadata:
    """Unpack a portable bundle ``.tar`` into *dest_dir* and return its metadata.

    Validates format and presence of required artifacts. Raises :class:`BundleError`
    on any structural problem.
    """
    import tarfile as _tarfile

    if not _tarfile.is_tarfile(tar_path):
        raise BundleError("the uploaded file is not a valid .tar archive")

    with _tarfile.open(tar_path, "r") as tar:
        # Security: reject any path that escapes the extraction dir.
        for member in tar.getmembers():
            if member.name.startswith("/") or ".." in member.name:
                raise BundleError(
                    f"the bundle contains an unsafe path: {member.name!r}"
                )
        tar.extractall(dest_dir)

    meta_path = os.path.join(dest_dir, _BUNDLE_META_NAME)
    if not os.path.isfile(meta_path):
        raise BundleError("the bundle is missing bundle.json")
    with open(meta_path, "rb") as fh:
        meta = BundleMetadata.from_json(fh.read())

    for required in (_BUNDLE_MANIFEST_NAME, _BUNDLE_DUMP_NAME):
        if not os.path.isfile(os.path.join(dest_dir, required)):
            raise BundleError(f"the bundle is missing {required}")

    return meta
