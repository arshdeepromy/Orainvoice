"""Backup_Manifest, File_Index, and Per_Org_Index builders (cloud-backup-restore Req 7).

Every Full_Backup is accompanied by a **Backup_Manifest**: a metadata document
that lets the listing/discovery flow select a backup and lets the restore flow
verify integrity and reconstruct what the backup contains. The single hard rule
governing this module is the **cleartext-catalog / encrypted-envelope split**
(Req 7.2, 7.8):

* **Cleartext catalog** — the *only* fields a Cloud_Provider (and the listing
  flow that has no Backup_Data_Key) may read: the backup id, the ISO-8601 UTC
  creation timestamp, the encrypted-artifact byte size, the artifact checksum,
  the included ``Backup_Scope``, and the aggregate Uploaded_Files summary
  (file count + total bytes — platform-wide totals that reveal no organisation
  identity, path, or filename). These are exactly the fields needed to list and
  select a backup (Req 7.1, 7.8).
* **Encrypted envelope** — everything that reveals customer or organisation
  structure is stored *inside* an envelope encrypted under the per-backup
  **Backup_Data_Key (BDK)** via :func:`backup_envelope_encrypt`, so no
  organisation identifier, file path, or filename is ever written in cleartext
  at the destination (Req 7.2, 7.8):
    - the list of contained organisation IDs,
    - the **File_Index** (each captured file's ``file_key``/path + owning
      ``org_id`` → ``Content_Hash`` + byte size — Req 7.2),
    - the **Per_Org_Index** (per ``org_id``: per-entity-type counts/identifiers
      plus whether a Per_Org_Logical_Export was emitted and where — Req 7.9),
    - and the structure-adjacent header fields (application version, schema /
      migration version, key version) the restore flow needs.

The **artifact checksum is computed over the encrypted dump bytes** (Req 7.3),
not the plaintext — the same bytes the restore flow re-downloads and re-hashes
before any data is modified (Req 7.4).

**Known-skips** (unreadable/missing files recorded by :mod:`backup.cas`) are
*omitted* from the File_Index but their count is retained in the envelope so the
manifest still reports them (Req 7.9 / 21.9).

This module is pure builder + (de)serialisation logic; it performs no I/O and no
DB access. The pipeline (task 8.2) supplies the captured-file records, the
contained org list, the per-org entity summaries, and the encrypted-dump bytes,
then uploads the serialised manifest through the ``StorageInterface``.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.modules.backup_restore.backup.cas import BlobRef
from app.modules.backup_restore.keys.key_service import (
    backup_envelope_decrypt,
    backup_envelope_encrypt,
)

# Bump if the on-disk manifest layout changes incompatibly. Recorded in the
# cleartext catalog so a reader can reject an unknown future format.
MANIFEST_FORMAT_VERSION = 1

# Sentinel meaning "this captured file belongs to no single organisation"
# (an explicit global/non-org indicator per Req 7.2). Serialised as JSON null.
GLOBAL_ORG_ID = None


class ManifestError(Exception):
    """Raised when a manifest cannot be parsed, decrypted, or is structurally invalid."""


# ---------------------------------------------------------------------------
# File_Index (Req 7.2) — stored inside the encrypted envelope.
# ---------------------------------------------------------------------------


@dataclass
class FileIndexEntry:
    """One captured Uploaded_File's entry in the File_Index (Req 7.2).

    The ``path`` and ``org_id`` fields reveal organisation structure and
    filenames, so they live only inside the encrypted envelope.
    """

    path: str
    """The file's ``file_key`` or filesystem path (envelope-only, Req 7.2)."""

    org_id: str | None
    """Owning organisation id, or ``None`` for an explicit global/non-org file."""

    content_hash: str
    """SHA-256 ``Content_Hash`` of the file's plaintext (Req 21.3/21.6)."""

    byte_size: int
    """Size of the plaintext content in bytes (integer >= 0)."""

    @classmethod
    def from_blob_ref(
        cls, path: str, org_id: str | None, blob_ref: BlobRef
    ) -> "FileIndexEntry":
        """Build an entry from a captured :class:`BlobRef` plus its source path/org."""
        return cls(
            path=path,
            org_id=_normalise_org_id(org_id),
            content_hash=blob_ref.content_hash,
            byte_size=blob_ref.byte_size,
        )

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "org_id": self.org_id,
            "content_hash": self.content_hash,
            "byte_size": self.byte_size,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FileIndexEntry":
        try:
            return cls(
                path=str(data["path"]),
                org_id=_normalise_org_id(data.get("org_id")),
                content_hash=str(data["content_hash"]),
                byte_size=int(data["byte_size"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ManifestError(f"invalid File_Index entry: {exc}") from exc


@dataclass
class CapturedFile:
    """Pairs a captured file's source path + owning org with its store result.

    The CAS returns :class:`BlobRef` objects that intentionally do not carry the
    source path or owning organisation (the store is content-addressed). The
    pipeline knows each file's path and derives its ``org_id`` from the path
    shape (``{category}/{org_id}/{file}``); it threads both back in via this
    record so the File_Index can be built (Req 7.2).
    """

    path: str
    org_id: str | None
    blob_ref: BlobRef


@dataclass
class FileIndex:
    """The per-Full_Backup File_Index: the authoritative list of contained files.

    Known-skips are omitted from :attr:`entries` but counted in
    :attr:`skipped_count` so the manifest still reports them (Req 7.9 / 21.9).
    """

    entries: list[FileIndexEntry] = field(default_factory=list)
    skipped_count: int = 0

    @property
    def file_count(self) -> int:
        """Number of captured Uploaded_Files in the index (Req 7.1)."""
        return len(self.entries)

    @property
    def total_bytes(self) -> int:
        """Total plaintext bytes across all captured files (Req 7.1)."""
        return sum(e.byte_size for e in self.entries)

    def to_dict(self) -> dict:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "skipped_count": self.skipped_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FileIndex":
        try:
            raw_entries = data["entries"]
            skipped = int(data.get("skipped_count", 0))
        except (KeyError, TypeError, ValueError) as exc:
            raise ManifestError(f"invalid File_Index: {exc}") from exc
        if not isinstance(raw_entries, list):
            raise ManifestError("File_Index 'entries' must be a list")
        return cls(
            entries=[FileIndexEntry.from_dict(e) for e in raw_entries],
            skipped_count=skipped,
        )


def build_file_index(
    captured: Iterable[CapturedFile],
    *,
    skipped_count: int = 0,
) -> FileIndex:
    """Build a :class:`FileIndex` from captured-file records (Req 7.2).

    Args:
        captured: One :class:`CapturedFile` per successfully captured file.
            Known-skips are NOT included here (they were never captured); their
            count is supplied separately.
        skipped_count: Number of known-skipped files to record (Req 7.9 / 21.9).

    Returns:
        A :class:`FileIndex` whose entries map each ``{path, org_id}`` to its
        ``Content_Hash`` and byte size.
    """
    entries = [
        FileIndexEntry.from_blob_ref(c.path, c.org_id, c.blob_ref) for c in captured
    ]
    return FileIndex(entries=entries, skipped_count=max(0, int(skipped_count)))


# ---------------------------------------------------------------------------
# Per_Org_Index (Req 7.9) — stored inside the encrypted envelope.
# ---------------------------------------------------------------------------


@dataclass
class PerOrgEntityCount:
    """A per-entity-type record count + identifiers for one organisation.

    Sufficient to serve per-organisation browsing (Req 15) without staging the
    full custom-format ``pg_dump`` (Req 7.9). Entity types with zero records are
    retained so browsing can show them (Req 15.2).
    """

    entity_type: str
    record_count: int
    identifiers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "entity_type": self.entity_type,
            "record_count": self.record_count,
            "identifiers": list(self.identifiers),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PerOrgEntityCount":
        try:
            return cls(
                entity_type=str(data["entity_type"]),
                record_count=int(data["record_count"]),
                identifiers=[str(i) for i in data.get("identifiers", [])],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ManifestError(f"invalid Per_Org_Index entity count: {exc}") from exc


@dataclass
class PerOrgIndexEntry:
    """The Per_Org_Index record for a single contained organisation (Req 7.9)."""

    org_id: str
    entities: list[PerOrgEntityCount] = field(default_factory=list)
    logical_export_emitted: bool = False
    """Whether a Per_Org_Logical_Export was emitted for this org (Req 7.9, 31)."""
    logical_export_location: str | None = None
    """Storage key of the org's Per_Org_Logical_Export artifact, when emitted."""

    def to_dict(self) -> dict:
        return {
            "org_id": self.org_id,
            "entities": [e.to_dict() for e in self.entities],
            "logical_export_emitted": self.logical_export_emitted,
            "logical_export_location": self.logical_export_location,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PerOrgIndexEntry":
        try:
            raw_entities = data.get("entities", [])
            if not isinstance(raw_entities, list):
                raise ManifestError("Per_Org_Index 'entities' must be a list")
            return cls(
                org_id=str(data["org_id"]),
                entities=[PerOrgEntityCount.from_dict(e) for e in raw_entities],
                logical_export_emitted=bool(data.get("logical_export_emitted", False)),
                logical_export_location=(
                    str(data["logical_export_location"])
                    if data.get("logical_export_location") is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ManifestError(f"invalid Per_Org_Index entry: {exc}") from exc


@dataclass
class PerOrgIndex:
    """The Per_Org_Index: one :class:`PerOrgIndexEntry` per contained organisation.

    Produced only for ``organisations_only``/``both`` backups (Req 7.9). For
    ``settings_only`` backups it is empty.
    """

    entries: list[PerOrgIndexEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"entries": [e.to_dict() for e in self.entries]}

    @classmethod
    def from_dict(cls, data: dict) -> "PerOrgIndex":
        raw = data.get("entries", [])
        if not isinstance(raw, list):
            raise ManifestError("Per_Org_Index 'entries' must be a list")
        return cls(entries=[PerOrgIndexEntry.from_dict(e) for e in raw])


def build_per_org_index(entries: Iterable[PerOrgIndexEntry]) -> PerOrgIndex:
    """Assemble a :class:`PerOrgIndex` from per-organisation entries (Req 7.9)."""
    return PerOrgIndex(entries=list(entries))


# ---------------------------------------------------------------------------
# Catalog (cleartext) and Envelope (encrypted) halves of the manifest.
# ---------------------------------------------------------------------------


@dataclass
class ManifestCatalog:
    """The cleartext catalog: the ONLY manifest fields readable without the BDK.

    These are the fields the Cloud_Provider and the listing/discovery flow may
    read to list and select a backup (Req 7.8). They contain no organisation
    identifier, file path, or filename — only platform-wide aggregates.
    """

    backup_id: str
    created_at: datetime
    encrypted_artifact_size: int
    checksum: str
    scope: str
    file_count: int = 0
    file_bytes: int = 0

    def to_dict(self) -> dict:
        return {
            "backup_id": self.backup_id,
            "created_at": _iso_utc(self.created_at),
            "encrypted_artifact_size": self.encrypted_artifact_size,
            "checksum": self.checksum,
            "scope": self.scope,
            "file_count": self.file_count,
            "file_bytes": self.file_bytes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ManifestCatalog":
        try:
            return cls(
                backup_id=str(data["backup_id"]),
                created_at=_parse_iso_utc(data["created_at"]),
                encrypted_artifact_size=int(data["encrypted_artifact_size"]),
                checksum=str(data["checksum"]),
                scope=str(data["scope"]),
                file_count=int(data.get("file_count", 0)),
                file_bytes=int(data.get("file_bytes", 0)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ManifestError(f"invalid manifest catalog: {exc}") from exc


@dataclass
class ManifestEnvelope:
    """The structure-revealing manifest fields, stored encrypted under the BDK.

    None of these fields may appear in cleartext at the destination (Req 7.2,
    7.8). The envelope is serialised to JSON and encrypted with
    :func:`backup_envelope_encrypt`.
    """

    org_ids: list[str] = field(default_factory=list)
    file_index: FileIndex = field(default_factory=FileIndex)
    per_org_index: PerOrgIndex = field(default_factory=PerOrgIndex)
    app_version: str | None = None
    schema_version: str | None = None
    key_version: int | None = None

    def to_dict(self) -> dict:
        return {
            "org_ids": list(self.org_ids),
            "file_index": self.file_index.to_dict(),
            "per_org_index": self.per_org_index.to_dict(),
            "app_version": self.app_version,
            "schema_version": self.schema_version,
            "key_version": self.key_version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ManifestEnvelope":
        try:
            org_ids = [str(o) for o in data.get("org_ids", [])]
            file_index = FileIndex.from_dict(data.get("file_index", {"entries": []}))
            per_org_index = PerOrgIndex.from_dict(
                data.get("per_org_index", {"entries": []})
            )
            key_version = data.get("key_version")
            return cls(
                org_ids=org_ids,
                file_index=file_index,
                per_org_index=per_org_index,
                app_version=(
                    str(data["app_version"])
                    if data.get("app_version") is not None
                    else None
                ),
                schema_version=(
                    str(data["schema_version"])
                    if data.get("schema_version") is not None
                    else None
                ),
                key_version=int(key_version) if key_version is not None else None,
            )
        except (TypeError, ValueError) as exc:
            raise ManifestError(f"invalid manifest envelope: {exc}") from exc


@dataclass
class BackupManifest:
    """A complete Backup_Manifest: cleartext catalog + encrypted envelope (Req 7)."""

    catalog: ManifestCatalog
    envelope: ManifestEnvelope


# ---------------------------------------------------------------------------
# Checksum (Req 7.3) — computed over the ENCRYPTED dump bytes.
# ---------------------------------------------------------------------------


def compute_artifact_checksum(encrypted_artifact: bytes) -> str:
    """Return the SHA-256 hex checksum of the **encrypted** artifact (Req 7.3).

    This is the checksum recorded in the catalog and re-verified byte-for-byte
    by the restore flow against the re-downloaded encrypted artifact before any
    data is modified (Req 7.4). It is intentionally computed over ciphertext so
    the integrity gate needs no key material.
    """
    return hashlib.sha256(encrypted_artifact).hexdigest()


# ---------------------------------------------------------------------------
# Manifest assembly.
# ---------------------------------------------------------------------------


def build_manifest(
    *,
    backup_id: str,
    created_at: datetime,
    scope: str,
    encrypted_dump: bytes | None = None,
    checksum: str | None = None,
    encrypted_artifact_size: int | None = None,
    file_index: FileIndex | None = None,
    per_org_index: PerOrgIndex | None = None,
    org_ids: Sequence[str] | None = None,
    app_version: str | None = None,
    schema_version: str | None = None,
    key_version: int | None = None,
) -> BackupManifest:
    """Assemble a :class:`BackupManifest` from pipeline outputs (Req 7).

    Either pass ``encrypted_dump`` (the encrypted dump bytes — the checksum and
    size are then computed over them, Req 7.3) or pass ``checksum`` +
    ``encrypted_artifact_size`` precomputed. The cleartext file count/total
    bytes are derived from the File_Index so the catalog stays consistent with
    the envelope contents.

    Raises:
        ManifestError: if neither the encrypted dump nor an explicit
            checksum/size pair is supplied.
    """
    file_index = file_index or FileIndex()
    per_org_index = per_org_index or PerOrgIndex()

    if encrypted_dump is not None:
        checksum = compute_artifact_checksum(encrypted_dump)
        encrypted_artifact_size = len(encrypted_dump)
    if checksum is None or encrypted_artifact_size is None:
        raise ManifestError(
            "build_manifest requires either 'encrypted_dump' or both 'checksum' "
            "and 'encrypted_artifact_size'"
        )

    catalog = ManifestCatalog(
        backup_id=backup_id,
        created_at=created_at,
        encrypted_artifact_size=int(encrypted_artifact_size),
        checksum=checksum,
        scope=scope,
        file_count=file_index.file_count,
        file_bytes=file_index.total_bytes,
    )
    envelope = ManifestEnvelope(
        org_ids=[str(o) for o in (org_ids or [])],
        file_index=file_index,
        per_org_index=per_org_index,
        app_version=app_version,
        schema_version=schema_version,
        key_version=key_version,
    )
    return BackupManifest(catalog=catalog, envelope=envelope)


# ---------------------------------------------------------------------------
# Serialisation / deserialisation.
# ---------------------------------------------------------------------------


def serialize_manifest(manifest: BackupManifest, bdk: bytes) -> bytes:
    """Serialise a manifest to its on-disk JSON bytes (Req 7.2, 7.8).

    The result is a JSON document with a cleartext ``catalog`` object and an
    ``envelope`` field holding the base64 of the BDK-encrypted envelope. Only
    the catalog is readable without the BDK; the envelope (org IDs, File_Index
    path/org listing, Per_Org_Index org-identifying contents) decrypts only with
    the Backup_Data_Key.
    """
    envelope_plaintext = json.dumps(
        manifest.envelope.to_dict(), separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    encrypted_envelope = backup_envelope_encrypt(envelope_plaintext, bdk)

    document = {
        "manifest_format": MANIFEST_FORMAT_VERSION,
        "catalog": manifest.catalog.to_dict(),
        "envelope": base64.b64encode(encrypted_envelope).decode("ascii"),
    }
    return json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")


def read_catalog(raw: bytes | str) -> ManifestCatalog:
    """Read ONLY the cleartext catalog from a serialised manifest (no BDK needed).

    This is what the listing/discovery flow uses to present and select a backup
    without any key material (Req 7.8). It never touches the encrypted envelope.

    Raises:
        ManifestError: if the document is malformed or of an unknown format.
    """
    document = _load_document(raw)
    catalog = document.get("catalog")
    if not isinstance(catalog, dict):
        raise ManifestError("manifest is missing a 'catalog' object")
    return ManifestCatalog.from_dict(catalog)


def deserialize_manifest(raw: bytes | str, bdk: bytes) -> BackupManifest:
    """Deserialise a full manifest, decrypting the envelope with the BDK (Req 7.2).

    Raises:
        ManifestError: if the document is malformed, of an unknown format, or
            the envelope cannot be decrypted with the supplied BDK.
    """
    document = _load_document(raw)

    catalog_data = document.get("catalog")
    if not isinstance(catalog_data, dict):
        raise ManifestError("manifest is missing a 'catalog' object")
    catalog = ManifestCatalog.from_dict(catalog_data)

    encoded_envelope = document.get("envelope")
    if not isinstance(encoded_envelope, str):
        raise ManifestError("manifest is missing an 'envelope' field")
    try:
        encrypted_envelope = base64.b64decode(encoded_envelope, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ManifestError("manifest envelope is not valid base64") from exc

    try:
        envelope_plaintext = backup_envelope_decrypt(encrypted_envelope, bdk)
    except Exception as exc:
        raise ManifestError(
            "manifest envelope could not be decrypted with the supplied "
            "Backup_Data_Key"
        ) from exc

    try:
        envelope_dict = json.loads(envelope_plaintext.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ManifestError("decrypted manifest envelope is not valid JSON") from exc
    if not isinstance(envelope_dict, dict):
        raise ManifestError("decrypted manifest envelope is not a JSON object")

    envelope = ManifestEnvelope.from_dict(envelope_dict)
    return BackupManifest(catalog=catalog, envelope=envelope)


# ---------------------------------------------------------------------------
# Internal helpers.
# ---------------------------------------------------------------------------


def _load_document(raw: bytes | str) -> dict:
    """Parse the outer manifest JSON document and validate its format version."""
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ManifestError("manifest bytes are not valid UTF-8") from exc
    try:
        document = json.loads(raw)
    except ValueError as exc:
        raise ManifestError("manifest is not valid JSON") from exc
    if not isinstance(document, dict):
        raise ManifestError("manifest document is not a JSON object")

    fmt = document.get("manifest_format")
    if fmt != MANIFEST_FORMAT_VERSION:
        raise ManifestError(
            f"unsupported manifest format {fmt!r}; this build reads "
            f"format {MANIFEST_FORMAT_VERSION}"
        )
    return document


def _normalise_org_id(org_id: object) -> str | None:
    """Coerce an org id to ``str`` or ``None`` (the global/non-org indicator)."""
    if org_id is None:
        return GLOBAL_ORG_ID
    return str(org_id)


def _iso_utc(dt: datetime) -> str:
    """Format *dt* as an ISO-8601 UTC string with a ``Z`` suffix (Req 7.1)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _parse_iso_utc(value: object) -> datetime:
    """Parse an ISO-8601 UTC timestamp (accepting a trailing ``Z``)."""
    if not isinstance(value, str) or not value:
        raise ManifestError("created_at must be a non-empty ISO-8601 string")
    text = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ManifestError(f"invalid ISO-8601 timestamp: {value!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
