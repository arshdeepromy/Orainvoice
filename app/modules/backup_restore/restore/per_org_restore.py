"""Per-organisation restore service (cloud-backup-restore Req 14, 22, 24, 31).

This module restores a *single* organisation's data from a Full_Backup without
touching any other organisation's data. It is the resolution of the central
tension in Requirement 14:

* **Req 14.3 / 22.2** — a per-org restore may insert/update/delete only
  Org_Scoped_Rows whose ``org_id`` equals the selected org. It must NEVER touch
  another organisation's rows or files.
* **Req 14.6 / 14.7** — referenced Shared_Global_Rows are handled by
  *read-and-ensure-exists* (insert only if absent, never modify or delete) so
  referential integrity holds with zero mutation of shared/global reference
  data, and restore-as-new remaps intra-org foreign keys with zero dangling
  references.

Pipeline (design.md "Per-organisation restore"):

1. **Integrity + presence** (Req 7.4, 14.8, 14.9) — re-hash the encrypted dump
   artifact and compare to the manifest checksum; abort an unreadable/corrupt
   backup. Confirm the selected ``org_id`` is present in the backup, else abort
   "organisation not found". No write happens before both gates pass.
2. **Extraction** (Req 31) — if a Per_Org_Logical_Export exists for the org,
   read the org's rows directly from it (fast path, Req 31.3). Otherwise stage
   the full dump into an **ephemeral scratch database**, extract the org's
   Org_Scoped_Rows by ``org_id``, and tear the scratch DB down regardless of
   outcome (Req 31.4, 31.5). A recorded export that fails its integrity check
   falls back to the scratch-DB path (Req 31.7).
3. **Classification-driven apply** (Req 14.3/14.6/14.7, ``restore/classifier``)
   under the target org's RLS context, in a **single transaction** so any error
   after writes begin rolls everything back (Req 14.10 / 22.5 / 22.6).
4. **File restore** (Req 22, 24) — reassemble the file set strictly from the
   chosen backup's File_Index filtered to the org, fetch each File_Blob by
   Content_Hash, and run the post-restore file-consistency check.

**Injectable seams.** Every external dependency is injected so the upcoming
property tests (tasks 10.5–10.9) can drive the pure restore logic with the DB,
storage, scratch-DB provisioning, and filesystem all mocked:

* :class:`ArtifactReader` — fetches the manifest, encrypted dump, per-org export
  bytes, and File_Blobs from a destination via the ``StorageInterface`` + BDK.
* :class:`DumpExtractor` — stages the full dump into an ephemeral scratch DB and
  extracts one org's rows (the heavy Req 31.4/31.5 path).
* :class:`RestoreTarget` — the transactional write surface (insert/update/exists
  checks) under the target org's RLS; production uses an ``AsyncSession``.
* :class:`FileRestoreSink` — writes restored file bytes to disk.

The org-scoped/shared-global classification and conflict-handling rules are
applied identically whether extraction used the logical export or the scratch
DB (Req 31.6), because both paths produce the same :class:`ExtractedDataset`.
"""

from __future__ import annotations

import enum
import json
import logging
import re
import uuid
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import MetaData

from app.modules.backup_restore.backup.cas import content_hash
from app.modules.backup_restore.backup.manifest import (
    BackupManifest,
    FileIndex,
    FileIndexEntry,
)
from app.modules.backup_restore.restore.classifier import (
    ORG_ID_COLUMN,
    RowClass,
    TableClass,
    classifiable_tables,
    classify_table,
    is_excluded,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Conflict policy (Req 14.5)
# ---------------------------------------------------------------------------


class ConflictPolicy(enum.Enum):
    """How to handle org data that already exists in the target (Req 14.5).

    The policy governs **Org_Scoped_Rows only**. Shared_Global_Rows are always
    handled by read-and-ensure-exists regardless of the policy (Req 14.6/14.7).
    """

    RESTORE_AS_NEW = "restore_as_new"
    """Mint new identifiers for restored Org_Scoped_Rows and rewrite every
    intra-org reference so referential integrity holds with zero dangling
    references; references to Shared_Global_Rows resolve to the ensured-existing
    target row (Req 14.6)."""

    SKIP = "skip"
    """Insert an Org_Scoped_Row only if no row with the same identity already
    exists in the target; skip existing rows."""

    OVERWRITE = "overwrite"
    """Overwrite an existing Org_Scoped_Row's columns when one with the same
    identity exists in the target; insert it otherwise."""

    @classmethod
    def from_value(cls, value: "str | ConflictPolicy") -> "ConflictPolicy":
        if isinstance(value, ConflictPolicy):
            return value
        normalised = str(value).strip().lower().replace("-", "_")
        for policy in cls:
            if policy.value == normalised:
                return policy
        raise ValueError(f"unknown conflict policy: {value!r}")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PerOrgRestoreError(Exception):
    """Base error for the per-organisation restore flow."""


class BackupUnreadableError(PerOrgRestoreError):
    """The backup could not be read or failed integrity validation (Req 14.8).

    Raised before any write so the target is never touched.
    """


class OrganisationNotFoundError(PerOrgRestoreError):
    """The selected ``org_id`` is not present in the backup (Req 14.9).

    Raised before any write so the target is never touched.
    """


class FileBlobUnavailableError(PerOrgRestoreError):
    """A File_Blob referenced by the File_Index could not be fetched or failed
    its integrity check (Req 24.4)."""

    def __init__(self, message: str, *, file_reference: str | None = None) -> None:
        super().__init__(message)
        self.file_reference = file_reference


class RestoreApplyError(PerOrgRestoreError):
    """An error occurred during the atomic apply; all writes were rolled back
    (Req 14.10)."""


class RestoreCancelledError(PerOrgRestoreError):
    """The restore was cancelled before completion; any partial writes were
    rolled back atomically (Req 12.16). Raised cooperatively at a safe point so
    the target is left exactly as it was before the restore began."""


# Progress callback: (percent_complete 0-100, human status message). Awaitable so
# the owning task can persist progress to the job row in an independent session.
ProgressCallback = Callable[[int, str], Awaitable[None]]
# Cancellation probe: returns True when an abort has been requested.
CancelCheck = Callable[[], bool]


# ---------------------------------------------------------------------------
# Human-readable DB-error translation (operator-facing failure summaries)
# ---------------------------------------------------------------------------

# Friendly singular names for the tables most likely to surface in a restore
# conflict; anything else is de-pluralised heuristically.
_FRIENDLY_ENTITY = {
    "users": "user",
    "customers": "customer",
    "invoices": "invoice",
    "payments": "payment",
    "quotes": "quote",
    "line_items": "line item",
    "leave_types": "leave type",
    "allowance_types": "allowance type",
    "branches": "branch",
    "items_catalogue": "catalogue item",
    "billing_receipts": "billing receipt",
    "notification_templates": "notification template",
    "notification_log": "notification",
    "invoice_sequences": "invoice sequence",
    "org_modules": "module",
}

_PG_UNIQUE_KEY_RE = re.compile(r"Key \(([^)]+)\)=\(([^)]*)\)\s+already exists")
_PG_FK_KEY_RE = re.compile(
    r'Key \(([^)]+)\)=\(([^)]*)\) is not present in table "([^"]+)"'
)


def _friendly_entity(table: Optional[str]) -> str:
    if not table:
        return "record"
    if table in _FRIENDLY_ENTITY:
        return _FRIENDLY_ENTITY[table]
    base = table.replace("_", " ")
    return base[:-1] if base.endswith("s") else base


def _table_from_constraint(constraint: Optional[str]) -> Optional[str]:
    """Best-effort recovery of a table name from a constraint name.

    Matches the longest known entity table whose name appears in the constraint
    (e.g. ``uq_users_email`` → ``users``, ``uq_leave_types_org_code`` →
    ``leave_types``). Returns ``None`` when nothing recognisable is found.
    """
    if not constraint:
        return None
    name = constraint.lower()
    best: Optional[str] = None
    for tbl in _FRIENDLY_ENTITY:
        if tbl in name and (best is None or len(tbl) > len(best)):
            best = tbl
    return best


def humanize_restore_db_error(exc: BaseException) -> Optional[str]:
    """Translate a low-level DB integrity error into an operator-readable reason.

    Returns ``None`` when *exc* is not a recognised database constraint error so
    the caller can fall back to a generic message. The raw error is always kept
    in the logs (via the exception chain); this is only for the user-facing
    summary stored on the job and shown in the restore wizard.
    """
    orig = getattr(exc, "orig", None) or exc
    pgcode = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    detail = getattr(orig, "detail", "") or ""
    table = getattr(orig, "table_name", None)
    constraint = getattr(orig, "constraint_name", None)
    text = f"{detail}\n{orig}" if detail else str(orig)
    # asyncpg often omits table_name on unique violations — recover the entity
    # from the constraint name (e.g. "uq_users_email" → users) for a friendlier
    # message. The constraint name may be an attribute or only in the text.
    if not constraint:
        m_con = re.search(r'constraint "([^"]+)"', text)
        if m_con:
            constraint = m_con.group(1)
    if not table and constraint:
        table = _table_from_constraint(constraint)

    is_unique = (
        pgcode == "23505"
        or "duplicate key value" in text
        or "UniqueViolation" in text
    )
    is_fk = (
        pgcode == "23503"
        or "violates foreign key constraint" in text
        or "ForeignKeyViolation" in text
    )
    is_notnull = (
        pgcode == "23502"
        or "null value in column" in text
        or "NotNullViolation" in text
    )

    if is_unique:
        m = _PG_UNIQUE_KEY_RE.search(text)
        entity = _friendly_entity(table)
        if m:
            cols, vals = m.group(1), m.group(2)
            return (
                f"This organisation already has a {entity} with the same {cols} "
                f"(“{vals}”), so the restore was cancelled and nothing was changed. "
                f"The target organisation already contains overlapping data — restore "
                f"into a new or empty organisation instead."
            )
        return (
            f"This organisation already has a {entity} that conflicts with one in the "
            f"backup, so the restore was cancelled and nothing was changed."
        )

    if is_fk:
        m = _PG_FK_KEY_RE.search(text)
        child = _friendly_entity(table)
        if m:
            col, val, reftable = m.group(1), m.group(2), m.group(3)
            ref = _friendly_entity(reftable)
            return (
                f"A {child} refers to a {ref} that was not part of this restore "
                f"({col} = {val}), so the restore was cancelled and nothing was "
                f"changed. Include all related entity types — or restore the whole "
                f"organisation — so referenced records are present."
            )
        return (
            f"A {child} refers to related data that was not included in this restore, "
            f"so the restore was cancelled and nothing was changed."
        )

    if is_notnull:
        col = getattr(orig, "column_name", None)
        where = f" ({col})" if col else ""
        return (
            f"A required field{where} was missing, so the restore was cancelled and "
            f"nothing was changed."
        )

    return None


# ---------------------------------------------------------------------------
# Extracted-row model (the common currency of both extraction paths)
# ---------------------------------------------------------------------------


@dataclass
class ExtractedRow:
    """One row extracted from the backup for the selected organisation.

    Produced identically by the Per_Org_Logical_Export fast path and the
    scratch-DB path so the apply engine is agnostic to extraction (Req 31.6).
    """

    table: str
    """The table the row belongs to."""

    values: dict[str, Any]
    """All column values for the row, keyed by column name."""

    pk: tuple[Any, ...]
    """The row's primary-key value tuple (in ``pk_columns`` order)."""

    org_id: str | None
    """The row's ``org_id`` (``None`` for a nullable-``org_id`` global row)."""


@dataclass
class ExtractedDataset:
    """All rows extracted from the backup for one organisation, plus PK metadata.

    Rows are grouped by table. ``pk_columns`` records each table's primary-key
    column ordering so the apply engine can identify, compare, and remap rows.
    """

    org_id: str
    rows_by_table: dict[str, list[ExtractedRow]] = field(default_factory=dict)
    pk_columns: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def tables(self) -> list[str]:
        return list(self.rows_by_table.keys())

    def all_rows(self) -> list[ExtractedRow]:
        out: list[ExtractedRow] = []
        for rows in self.rows_by_table.values():
            out.extend(rows)
        return out

    def add_row(self, row: ExtractedRow, pk_columns: tuple[str, ...]) -> None:
        self.rows_by_table.setdefault(row.table, []).append(row)
        self.pk_columns.setdefault(row.table, pk_columns)


# ---------------------------------------------------------------------------
# Per_Org_Logical_Export serialisation (Req 31.1/31.3)
# ---------------------------------------------------------------------------

PER_ORG_EXPORT_FORMAT = "per_org_logical_export/v1"


class PerOrgExportError(PerOrgRestoreError):
    """A Per_Org_Logical_Export artifact could not be parsed or failed its
    integrity check; the caller falls back to the scratch-DB path (Req 31.7)."""


def serialize_per_org_export(dataset: ExtractedDataset) -> bytes:
    """Serialise a :class:`ExtractedDataset` to the Per_Org_Logical_Export bytes.

    This is the plaintext representation a backup-time generator (Req 31.1)
    encrypts under the BDK and the fast path (Req 31.3) decrypts and parses. The
    format is a JSON document keyed by ``org_id`` with per-table ``pk``/``rows``
    (the org's Org_Scoped_Rows as a ``COPY``/SQL-equivalent representation).
    """
    tables: dict[str, dict] = {}
    for table, rows in dataset.rows_by_table.items():
        tables[table] = {
            "pk": list(dataset.pk_columns.get(table, ())),
            "rows": [_jsonify_values(r.values) for r in rows],
        }
    document = {
        "format": PER_ORG_EXPORT_FORMAT,
        "org_id": dataset.org_id,
        "tables": tables,
    }
    return json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")


def parse_per_org_export(raw: bytes, org_id: str) -> ExtractedDataset:
    """Parse Per_Org_Logical_Export bytes into a :class:`ExtractedDataset`.

    Raises:
        PerOrgExportError: if the bytes are not a valid export document for the
            requested org — the caller falls back to staging the full dump
            (Req 31.7).
    """
    try:
        document = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise PerOrgExportError(f"per-org export is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise PerOrgExportError("per-org export is not a JSON object")
    if document.get("format") != PER_ORG_EXPORT_FORMAT:
        raise PerOrgExportError(
            f"unsupported per-org export format {document.get('format')!r}"
        )
    export_org = str(document.get("org_id"))
    if export_org != str(org_id):
        raise PerOrgExportError(
            f"per-org export is for org {export_org!r}, not the requested "
            f"{org_id!r}"
        )

    raw_tables = document.get("tables")
    if not isinstance(raw_tables, dict):
        raise PerOrgExportError("per-org export 'tables' must be an object")

    dataset = ExtractedDataset(org_id=str(org_id))
    for table, table_doc in raw_tables.items():
        if not isinstance(table_doc, dict):
            raise PerOrgExportError(f"per-org export table {table!r} is malformed")
        pk_columns = tuple(str(c) for c in table_doc.get("pk", ()))
        raw_rows = table_doc.get("rows", [])
        if not isinstance(raw_rows, list):
            raise PerOrgExportError(f"per-org export table {table!r} rows must be a list")
        dataset.pk_columns.setdefault(table, pk_columns)
        dataset.rows_by_table.setdefault(table, [])
        for raw_row in raw_rows:
            if not isinstance(raw_row, dict):
                raise PerOrgExportError(
                    f"per-org export row in {table!r} must be an object"
                )
            values = dict(raw_row)
            pk = tuple(values.get(col) for col in pk_columns)
            dataset.rows_by_table[table].append(
                ExtractedRow(
                    table=table,
                    values=values,
                    pk=pk,
                    org_id=_row_org_id(values),
                )
            )
    return dataset


def _jsonify_values(values: Mapping[str, Any]) -> dict[str, Any]:
    """Coerce row values to JSON-serialisable forms (UUID/bytes/datetime → str)."""
    out: dict[str, Any] = {}
    for key, value in values.items():
        out[key] = _jsonify_scalar(value)
    return out


def _jsonify_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        import base64

        return {"__bytes_b64__": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, (list, tuple)):
        return [_jsonify_scalar(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonify_scalar(v) for k, v in value.items()}
    # datetime, Decimal, etc. — fall back to ISO/str form.
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return str(value)


def _row_org_id(values: Mapping[str, Any]) -> str | None:
    raw = values.get(ORG_ID_COLUMN)
    return None if raw is None else str(raw)


# ---------------------------------------------------------------------------
# Injectable seams (ABCs) — production impls + test fakes both satisfy these.
# ---------------------------------------------------------------------------


class ArtifactReader(ABC):
    """Reads backup artifacts from a destination (storage + key material).

    Production wraps a ``StorageInterface`` adapter and the resolved BDK; tests
    supply in-memory bytes. The reader is the only seam that touches the
    Cloud_Provider, so the restore logic stays provider-agnostic (Req 3).
    """

    @abstractmethod
    async def read_manifest(self) -> BackupManifest:
        """Return the decrypted :class:`BackupManifest` for the chosen backup."""

    @abstractmethod
    async def read_encrypted_dump(self) -> bytes:
        """Return the raw **encrypted** dump bytes (for the checksum gate, Req 7.4)."""

    @abstractmethod
    async def read_dump_plaintext(self) -> bytes:
        """Return the decrypted custom-format ``pg_dump`` bytes (scratch-DB path)."""

    @abstractmethod
    async def read_per_org_export(self, location: str) -> bytes:
        """Return the decrypted Per_Org_Logical_Export bytes stored at *location*.

        Raises:
            PerOrgExportError: if the artifact is missing/unreadable so the
                caller falls back to the scratch-DB path (Req 31.7).
        """

    @abstractmethod
    async def read_blob(self, content_hash: str) -> bytes:
        """Return the decrypted plaintext bytes of the File_Blob for *content_hash*.

        Raises:
            FileBlobUnavailableError: if the blob cannot be fetched (Req 24.4).
        """


class DumpExtractor(ABC):
    """Stages the full dump into an ephemeral scratch DB and extracts one org.

    This is the heavy Req 31.4/31.5 path used when no Per_Org_Logical_Export was
    emitted for the org (or the recorded export failed integrity, Req 31.7). The
    implementation MUST tear the scratch environment down regardless of outcome
    (Req 31.5).
    """

    @abstractmethod
    async def extract_org(
        self,
        dump_plaintext: bytes,
        org_id: str,
        schema: "SchemaModel",
    ) -> ExtractedDataset:
        """Stage *dump_plaintext*, extract *org_id*'s Org_Scoped_Rows, tear down."""


class RestoreTarget(ABC):
    """Transactional write surface for the apply, under the target org's RLS.

    Production is an ``AsyncSession``-backed implementation that sets
    ``app.current_org_id`` to the target org (defence-in-depth alongside the
    application-level cross-org checks). Tests use an in-memory fake.

    The :meth:`atomic` context manager wraps the whole apply so any error after
    writes begin rolls everything back (Req 14.10).
    """

    @abstractmethod
    async def set_org_context(self, org_id: str) -> None:
        """Set the target-org RLS context for the connection (Req 14.3 defence)."""

    @abstractmethod
    def atomic(self) -> "Any":
        """Return an async context manager that commits on success / rolls back
        on error (a SAVEPOINT in production, a snapshot in the fake)."""

    @abstractmethod
    async def org_row_exists(
        self, table: str, pk_columns: tuple[str, ...], pk: tuple[Any, ...]
    ) -> bool:
        """Whether an Org_Scoped_Row with primary key *pk* exists in the target."""

    @abstractmethod
    async def shared_global_equivalent(
        self, table: str, row: ExtractedRow, pk_columns: tuple[str, ...]
    ) -> tuple[Any, ...] | None:
        """Return the PK of an equivalent existing Shared_Global_Row, or ``None``.

        Equivalence is by primary key by default; an implementation may use a
        natural key. Used to ensure-exists without mutating (Req 14.6/14.7).
        """

    @abstractmethod
    async def insert(self, table: str, values: Mapping[str, Any]) -> None:
        """Insert a row into *table*."""

    async def insert_or_skip(
        self,
        table: str,
        pk_columns: tuple[str, ...],
        pk: tuple[Any, ...],
        values: Mapping[str, Any],
    ) -> bool:
        """Insert *values* into *table*, skipping if a conflicting row exists.

        Returns ``True`` if a row was inserted and ``False`` if it was skipped
        because an equivalent row already exists. "Equivalent" must cover every
        uniqueness constraint on the table — the primary key *and* any natural /
        unique key (e.g. ``(org_id, code)``) — so a SKIP-policy apply does not
        abort the atomic transaction with a ``UniqueViolation`` when the backup
        row carries a different surrogate PK but the same natural key (Req 14.5).

        This default implementation checks the primary key only and is intended
        for in-memory test fakes; the production SQLAlchemy target overrides it
        with an atomic ``INSERT ... ON CONFLICT DO NOTHING`` that honours all
        unique constraints without poisoning the surrounding transaction.
        """
        if await self.org_row_exists(table, pk_columns, pk):
            return False
        await self.insert(table, values)
        return True

    @abstractmethod
    async def update(
        self,
        table: str,
        pk_columns: tuple[str, ...],
        pk: tuple[Any, ...],
        values: Mapping[str, Any],
    ) -> None:
        """Update the row identified by *pk* in *table* (overwrite policy)."""

    async def find_existing_pk(
        self,
        table: str,
        pk_columns: tuple[str, ...],
        pk: tuple[Any, ...],
        unique_keys: Sequence[tuple[str, ...]],
        values: Mapping[str, Any],
    ) -> tuple[Any, ...] | None:
        """Resolve a backup row's identity against an existing target row.

        Returns the primary key of the existing row that the backup row
        corresponds to — matched first by primary key, then by any natural /
        unique key (e.g. ``(org_id, code)`` or ``email``) — or ``None`` if no
        such row exists. Natural-key resolution is what lets SKIP/OVERWRITE work
        correctly when a per-org reference row was re-seeded with a fresh
        surrogate key but the same natural key (Req 14.5).

        This default implementation matches by primary key only and is intended
        for in-memory test fakes; the production SQLAlchemy target overrides it
        to also query the table's unique keys.
        """
        if await self.org_row_exists(table, pk_columns, pk):
            return pk
        return None


class FileRestoreSink(ABC):
    """Writes restored file bytes to the filesystem (Req 22.1)."""

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """Whether a file already exists at *path*."""

    @abstractmethod
    async def write_file(self, path: str, data: bytes) -> None:
        """Write *data* to *path*, creating parent directories as needed.

        Raises:
            OSError: on write error / insufficient space (Req 22.7).
        """


# ---------------------------------------------------------------------------
# Schema model — PK + FK + classification, derived from SQLAlchemy metadata.
# ---------------------------------------------------------------------------


@dataclass
class ForeignKeyEdge:
    """One foreign-key column → referenced table/column (for FK remapping)."""

    column: str
    ref_table: str
    ref_column: str


class SchemaModel:
    """Per-table primary-key, foreign-key, and classification metadata.

    Derived from SQLAlchemy ``Base.metadata`` (the live ~132-table schema) plus
    :mod:`restore.classifier`. Used by the apply engine to identify rows, remap
    references for restore-as-new, and decide org-scoped vs shared-global
    handling. Injectable ``metadata`` keeps it testable against a small schema.
    """

    def __init__(self, metadata: Optional[MetaData] = None) -> None:
        from app.core.database import Base
        from app.modules.backup_restore.restore.classifier import (
            ensure_all_models_imported,
        )

        if metadata is None:
            ensure_all_models_imported()
            metadata = Base.metadata
        self.metadata = metadata
        self._pk_cache: dict[str, tuple[str, ...]] = {}
        self._fk_cache: dict[str, list[ForeignKeyEdge]] = {}
        self._uk_cache: dict[str, list[tuple[str, ...]]] = {}

    def pk_columns(self, table: str) -> tuple[str, ...]:
        """Primary-key column names for *table* (defaults to ``("id",)``)."""
        if table in self._pk_cache:
            return self._pk_cache[table]
        tbl = self.metadata.tables.get(table)
        if tbl is None:
            pk = ("id",)
        else:
            pk = tuple(c.name for c in tbl.primary_key.columns) or ("id",)
        self._pk_cache[table] = pk
        return pk

    def foreign_keys(self, table: str) -> list[ForeignKeyEdge]:
        """Foreign-key edges declared on *table* (column → referenced table)."""
        if table in self._fk_cache:
            return self._fk_cache[table]
        edges: list[ForeignKeyEdge] = []
        tbl = self.metadata.tables.get(table)
        if tbl is not None:
            for col in tbl.columns:
                for fk in col.foreign_keys:
                    edges.append(
                        ForeignKeyEdge(
                            column=col.name,
                            ref_table=fk.column.table.name,
                            ref_column=fk.column.name,
                        )
                    )
        self._fk_cache[table] = edges
        return edges

    def classify(self, table: str) -> TableClass:
        return classify_table(table, self.metadata)

    def has_org_id(self, table: str) -> bool:
        tbl = self.metadata.tables.get(table)
        return tbl is not None and ORG_ID_COLUMN in tbl.columns

    def unique_keys(self, table: str) -> list[tuple[str, ...]]:
        """Natural/unique keys for *table* (column tuples), excluding the PK.

        Derived from declared ``UniqueConstraint``s and unique ``Index``es in
        the SQLAlchemy metadata. Used to resolve a backup row's identity against
        an existing target row when the surrogate primary key differs (e.g. a
        per-org reference row re-seeded with a fresh UUID but the same
        ``(org_id, code)``). The primary key itself is excluded — it is checked
        separately. Cached per table.
        """
        if table in self._uk_cache:
            return self._uk_cache[table]
        keys: list[tuple[str, ...]] = []
        tbl = self.metadata.tables.get(table)
        if tbl is not None:
            pk = set(self.pk_columns(table))
            seen: set[tuple[str, ...]] = set()
            from sqlalchemy import UniqueConstraint

            for constraint in tbl.constraints:
                if isinstance(constraint, UniqueConstraint):
                    cols = tuple(c.name for c in constraint.columns)
                    if cols and set(cols) != pk and cols not in seen:
                        seen.add(cols)
                        keys.append(cols)
            for index in tbl.indexes:
                if index.unique:
                    cols = tuple(c.name for c in index.columns)
                    if cols and set(cols) != pk and cols not in seen:
                        seen.add(cols)
                        keys.append(cols)
        self._uk_cache[table] = keys
        return keys

    def org_scoped_tables(self) -> list[str]:
        """Tables a per-org restore may write org-scoped rows to (sorted)."""
        out: list[str] = []
        for table in classifiable_tables(self.metadata):
            cls = self.classify(table)
            if cls in (TableClass.ORG_SCOPED, TableClass.HYBRID):
                out.append(table)
        return out


# ---------------------------------------------------------------------------
# Apply engine — classification-driven, conflict-policy-aware, FK-remapping.
# ---------------------------------------------------------------------------

# Default identifier factory for restore-as-new: mint a fresh UUID per row.
def _default_id_factory(table: str) -> str:
    return str(uuid.uuid4())


@dataclass
class ApplyStats:
    """Counters describing what the apply did (recorded in the job summary)."""

    org_rows_inserted: int = 0
    org_rows_updated: int = 0
    org_rows_skipped: int = 0
    shared_rows_inserted: int = 0
    shared_rows_existing: int = 0
    remapped_ids: int = 0


class PerOrgApplyEngine:
    """Applies an :class:`ExtractedDataset` for one org under a conflict policy.

    Pure orchestration over the injected :class:`RestoreTarget`: it performs the
    classification (Req 14.7), the cross-org prohibition (Req 14.3), the
    ensure-exists handling of Shared_Global_Rows (Req 14.6/14.7), the
    restore-as-new identifier minting + reference rewrite (Req 14.6), and the
    transitive inclusion of referenced same-org rows (Req 14.7).
    """

    def __init__(
        self,
        schema: SchemaModel,
        target: RestoreTarget,
        *,
        id_factory=_default_id_factory,
    ) -> None:
        self.schema = schema
        self.target = target
        self.id_factory = id_factory
        # (table, old_pk_value) -> new_pk_value for restore-as-new remapping.
        self.id_remap: dict[tuple[str, Any], Any] = {}

    # -- classification -----------------------------------------------------

    def _row_class(self, row: ExtractedRow) -> RowClass:
        """Classify a single extracted row (Req 14.7)."""
        table_class = self.schema.classify(row.table)
        if table_class is TableClass.ORG_SCOPED:
            return RowClass.ORG_SCOPED
        if table_class is TableClass.SHARED_GLOBAL:
            return RowClass.SHARED_GLOBAL
        if table_class is TableClass.HYBRID:
            return RowClass.SHARED_GLOBAL if row.org_id is None else RowClass.ORG_SCOPED
        # EXCLUDED tables must never reach the apply.
        raise RestoreApplyError(
            f"table {row.table!r} is excluded from per-org restore and must not "
            "be applied"
        )

    # -- public apply -------------------------------------------------------

    async def apply(
        self,
        dataset: ExtractedDataset,
        selected_org_id: str,
        policy: ConflictPolicy,
        *,
        selected_tables: Optional[Sequence[str]] = None,
        progress: "Optional[Callable[[int, int], Awaitable[None]]]" = None,
        should_cancel: "Optional[CancelCheck]" = None,
    ) -> ApplyStats:
        """Apply *dataset* for *selected_org_id* under *policy* atomically.

        The entire apply runs inside :meth:`RestoreTarget.atomic` so any error
        after writes begin rolls everything back (Req 14.10). The target's RLS
        context is set to the selected org first (Req 14.3 defence-in-depth).

        *progress*, if given, is awaited periodically with ``(rows_done,
        rows_total)`` so the caller can report live apply progress. *should_cancel*,
        if given, is polled between rows; when it returns ``True`` the apply
        raises :class:`RestoreCancelledError` and the atomic block rolls back so
        no partial data remains (Req 12.16).
        """
        selected_org_id = str(selected_org_id)
        stats = ApplyStats()

        # Compute the working set: the selected tables (entity subset, Req 14.4)
        # plus the transitive closure of referenced same-org rows (Req 14.7).
        working = self._working_set(dataset, selected_org_id, selected_tables, policy)

        # Req 14.3 — never touch a row whose org_id differs from the selected
        # org. Verify BEFORE any write so a stray cross-org row aborts with no
        # changes applied.
        for row in working:
            if self._row_class(row) is RowClass.ORG_SCOPED and row.org_id is not None:
                if str(row.org_id) != selected_org_id:
                    raise RestoreApplyError(
                        f"refusing to apply {row.table!r} row owned by org "
                        f"{row.org_id!r}; per-org restore is confined to "
                        f"{selected_org_id!r} (Req 14.3)"
                    )

        await self.target.set_org_context(selected_org_id)

        # Pre-compute restore-as-new id remap so reference rewrites are stable.
        if policy is ConflictPolicy.RESTORE_AS_NEW:
            self._build_id_remap(working, dataset)

        async with self.target.atomic():
            # Shared_Global_Rows first so org rows can reference ensured-exist
            # targets (Req 14.6).
            for row in working:
                if self._row_class(row) is RowClass.SHARED_GLOBAL:
                    await self._ensure_shared_global(row, stats)
            # Org_Scoped_Rows under the conflict policy, ordered so an FK-
            # referenced row is applied before the row that references it
            # (parents before children) — otherwise a child insert (e.g. a
            # payment) can transiently violate a foreign key before its parent
            # (the invoice) is inserted, aborting the whole atomic apply.
            org_rows = [
                r for r in working if self._row_class(r) is RowClass.ORG_SCOPED
            ]
            ordered = self._dependency_ordered(org_rows)
            total = len(ordered)
            for i, row in enumerate(ordered):
                # Cooperative cancellation between rows (Req 12.16) — abort and
                # roll back the whole atomic apply, leaving the org untouched.
                if should_cancel is not None and (i % 100 == 0) and should_cancel():
                    raise RestoreCancelledError(
                        "restore cancelled during apply; all changes rolled back"
                    )
                await self._apply_org_row(row, policy, stats)
                if progress is not None and (i % 100 == 0):
                    await progress(i + 1, total)
            if progress is not None:
                await progress(total, total)
        return stats

    # -- FK-dependency ordering (parents before children) -------------------

    def _dependency_ordered(
        self, rows: list[ExtractedRow]
    ) -> list[ExtractedRow]:
        """Return *rows* ordered so a row's intra-org FK targets come first.

        Uses a stable topological sort over the rows' foreign-key edges
        (shared-global references are excluded — they are ensured-exist
        separately). Rows caught in a reference cycle (e.g. mutually-referencing
        rows or self-references) are appended in their original order as a
        best-effort fallback. Runs in O(rows + edges); fine at high row counts.
        """
        from collections import deque

        n = len(rows)
        if n <= 1:
            return list(rows)

        # Index rows by (table, single-column-PK value) for FK resolution.
        index: dict[tuple[str, Any], int] = {}
        for i, row in enumerate(rows):
            pk_cols = self.schema.pk_columns(row.table)
            if len(pk_cols) == 1:
                index[(row.table, row.values.get(pk_cols[0]))] = i

        # deps[i] = indices row i depends on; dependents[j] = rows that need j.
        deps: list[set[int]] = [set() for _ in range(n)]
        dependents: list[list[int]] = [[] for _ in range(n)]
        for i, row in enumerate(rows):
            for edge in self.schema.foreign_keys(row.table):
                if self.schema.classify(edge.ref_table) is TableClass.SHARED_GLOBAL:
                    continue
                ref_value = row.values.get(edge.column)
                if ref_value is None:
                    continue
                j = index.get((edge.ref_table, ref_value))
                if j is None or j == i or j in deps[i]:
                    continue
                deps[i].add(j)
                dependents[j].append(i)

        indegree = [len(d) for d in deps]
        # Stable Kahn: seed ready rows in original order so output is
        # deterministic and close to the natural ordering.
        ready: deque[int] = deque(i for i in range(n) if indegree[i] == 0)
        emitted = [False] * n
        ordered_idx: list[int] = []
        while ready:
            i = ready.popleft()
            emitted[i] = True
            ordered_idx.append(i)
            for k in dependents[i]:
                indegree[k] -= 1
                if indegree[k] == 0:
                    ready.append(k)

        # Cycle fallback: emit any remaining rows in original order.
        if len(ordered_idx) < n:
            for i in range(n):
                if not emitted[i]:
                    ordered_idx.append(i)

        return [rows[i] for i in ordered_idx]

    # -- working set + transitive closure (Req 14.4 / 14.7) -----------------

    def _working_set(
        self,
        dataset: ExtractedDataset,
        selected_org_id: str,
        selected_tables: Optional[Sequence[str]],
        policy: ConflictPolicy,
    ) -> list[ExtractedRow]:
        """Selected-table rows plus the transitive closure of same-org refs."""
        # Index org-scoped dataset rows by (table, pk-scalar) for FK resolution.
        index: dict[tuple[str, Any], ExtractedRow] = {}
        for table, rows in dataset.rows_by_table.items():
            pk_cols = dataset.pk_columns.get(table, self.schema.pk_columns(table))
            for row in rows:
                if len(pk_cols) == 1:
                    index[(table, row.values.get(pk_cols[0]))] = row

        if selected_tables is None:
            selected = set(dataset.rows_by_table.keys())
        else:
            selected = {t for t in selected_tables}

        seen: set[int] = set()
        ordered: list[ExtractedRow] = []
        worklist: list[ExtractedRow] = []
        for table in dataset.rows_by_table:
            if table in selected:
                worklist.extend(dataset.rows_by_table[table])

        while worklist:
            row = worklist.pop()
            if id(row) in seen:
                continue
            seen.add(id(row))
            ordered.append(row)
            # Follow FK edges to other same-org rows present in the dataset.
            for edge in self.schema.foreign_keys(row.table):
                if self.schema.classify(edge.ref_table) is TableClass.SHARED_GLOBAL:
                    continue  # shared-global handled by ensure-exists, no closure
                ref_value = row.values.get(edge.column)
                if ref_value is None:
                    continue
                ref_row = index.get((edge.ref_table, ref_value))
                if ref_row is None or id(ref_row) in seen:
                    continue
                worklist.append(ref_row)

        return ordered

    # -- restore-as-new id remap (Req 14.6) ---------------------------------

    def _build_id_remap(
        self, working: Sequence[ExtractedRow], dataset: ExtractedDataset
    ) -> None:
        """Mint a new id for every Org_Scoped_Row in the working set.

        Only single-column primary keys are remapped (the platform UUID-id
        convention); multi-column-keyed rows keep their key.
        """
        self.id_remap = {}
        for row in working:
            if self._row_class(row) is not RowClass.ORG_SCOPED:
                continue
            pk_cols = dataset.pk_columns.get(
                row.table, self.schema.pk_columns(row.table)
            )
            if len(pk_cols) != 1:
                continue
            old = row.values.get(pk_cols[0])
            if old is None:
                continue
            self.id_remap[(row.table, old)] = self.id_factory(row.table)

    def _rewrite_values(self, row: ExtractedRow) -> dict[str, Any]:
        """Return *row*'s values with its PK and intra-org FKs remapped.

        References to Shared_Global_Rows are left untouched so they resolve to
        the ensured-existing target row rather than minting a new shared row
        (Req 14.6). References to org-scoped rows that were remapped are
        rewritten to the new id; references to rows that already exist in the
        target keep the original id (zero dangling references).
        """
        values = dict(row.values)
        pk_cols = self.schema.pk_columns(row.table)
        # Rewrite the PK to the newly-minted id.
        if len(pk_cols) == 1:
            old = values.get(pk_cols[0])
            new = self.id_remap.get((row.table, old))
            if new is not None:
                values[pk_cols[0]] = new
        # Rewrite intra-org foreign keys.
        for edge in self.schema.foreign_keys(row.table):
            if self.schema.classify(edge.ref_table) is TableClass.SHARED_GLOBAL:
                continue  # never remap a shared-global reference (Req 14.6)
            ref_value = values.get(edge.column)
            if ref_value is None:
                continue
            new_ref = self.id_remap.get((edge.ref_table, ref_value))
            if new_ref is not None:
                values[edge.column] = new_ref
        return values

    # -- shared-global ensure-exists (Req 14.6 / 14.7) ----------------------

    async def _ensure_shared_global(self, row: ExtractedRow, stats: ApplyStats) -> None:
        """Insert a Shared_Global_Row only if absent; never modify or delete."""
        pk_cols = self.schema.pk_columns(row.table)
        existing = await self.target.shared_global_equivalent(row.table, row, pk_cols)
        if existing is not None:
            stats.shared_rows_existing += 1
            return  # ensure-exists: leave the existing shared row untouched
        await self.target.insert(row.table, dict(row.values))
        stats.shared_rows_inserted += 1

    # -- org-scoped apply under conflict policy (Req 14.5) ------------------

    def _rewrite_intra_org_fks(self, row: ExtractedRow) -> dict[str, Any]:
        """Return *row*'s values with intra-org FKs remapped onto resolved rows.

        Unlike :meth:`_rewrite_values` (restore-as-new) this does NOT change the
        primary key — it only rewrites foreign-key columns that point at a row
        whose identity was resolved to an existing target row (recorded in
        ``id_remap`` as parents are applied before children). This keeps child
        references valid under SKIP/OVERWRITE when a referenced reference-row was
        matched to a pre-existing target row with a different surrogate key.
        """
        if not self.id_remap:
            return dict(row.values)
        values = dict(row.values)
        for edge in self.schema.foreign_keys(row.table):
            if self.schema.classify(edge.ref_table) is TableClass.SHARED_GLOBAL:
                continue
            ref_value = values.get(edge.column)
            if ref_value is None:
                continue
            new_ref = self.id_remap.get((edge.ref_table, ref_value))
            if new_ref is not None and new_ref != ref_value:
                values[edge.column] = new_ref
        return values

    def _record_identity_remap(
        self,
        table: str,
        pk_cols: tuple[str, ...],
        backup_pk: tuple[Any, ...],
        existing_pk: tuple[Any, ...],
        stats: ApplyStats,
    ) -> None:
        """Remember that *backup_pk* resolved to an existing row *existing_pk* so
        later child rows can rewrite their foreign keys onto it (single-col PKs
        only — the platform UUID-id convention)."""
        if len(pk_cols) != 1:
            return
        old = backup_pk[0]
        new = existing_pk[0]
        if old is not None and new is not None and old != new:
            self.id_remap[(table, old)] = new
            stats.remapped_ids += 1

    async def _apply_org_row(
        self, row: ExtractedRow, policy: ConflictPolicy, stats: ApplyStats
    ) -> None:
        pk_cols = self.schema.pk_columns(row.table)

        if policy is ConflictPolicy.RESTORE_AS_NEW:
            values = self._rewrite_values(row)
            if len(pk_cols) == 1 and (row.table, row.values.get(pk_cols[0])) in self.id_remap:
                stats.remapped_ids += 1
            await self.target.insert(row.table, values)
            stats.org_rows_inserted += 1
            return

        pk = tuple(row.values.get(c) for c in pk_cols)
        # Rewrite child FKs onto any parent rows already resolved to existing
        # target rows (parents are applied first via _dependency_ordered).
        values = self._rewrite_intra_org_fks(row)
        unique_keys = self.schema.unique_keys(row.table)
        # Resolve identity: existing row by PK, else by any natural/unique key.
        existing_pk = await self.target.find_existing_pk(
            row.table, pk_cols, pk, unique_keys, values
        )

        if policy is ConflictPolicy.SKIP:
            if existing_pk is not None:
                # The row already exists (possibly under a different surrogate
                # key). Skip the write but remember the mapping so child rows
                # reference the existing row rather than a row we never inserted.
                self._record_identity_remap(row.table, pk_cols, pk, existing_pk, stats)
                stats.org_rows_skipped += 1
                return
            await self.target.insert(row.table, values)
            stats.org_rows_inserted += 1
            return

        if policy is ConflictPolicy.OVERWRITE:
            if existing_pk is not None:
                # Overwrite the matched existing row in place (its surrogate key
                # may differ from the backup's). Record the mapping so child FKs
                # resolve onto it.
                await self.target.update(row.table, pk_cols, existing_pk, values)
                self._record_identity_remap(row.table, pk_cols, pk, existing_pk, stats)
                stats.org_rows_updated += 1
            else:
                await self.target.insert(row.table, values)
                stats.org_rows_inserted += 1
            return

        raise RestoreApplyError(f"unhandled conflict policy {policy!r}")


# ---------------------------------------------------------------------------
# File restore (Req 22, 24) — strictly from the chosen backup's File_Index.
# ---------------------------------------------------------------------------


@dataclass
class FileRestoreResult:
    """Outcome of the per-org file-restore phase (Req 22.5/22.6, 24)."""

    restored_paths: list[str] = field(default_factory=list)
    known_skip_count: int = 0
    missing_references: list[str] = field(default_factory=list)
    file_consistency_outcome: str = "passed"  # "passed" | "failed"


def filter_file_index_for_org(file_index: FileIndex, org_id: str) -> list[FileIndexEntry]:
    """Select the File_Index entries belonging to *org_id* (Req 22.2, 24.3).

    An entry belongs to the org when its recorded owning ``org_id`` equals the
    selected org (the authoritative ownership recorded at backup time — used for
    both org-partitioned and non-org-partitioned files). For org-partitioned
    categories the ``{category}/{org_id}/`` path segment is an additional guard.
    Files owned by another org (or global files with no owning org) are never
    included, so the restore touches no other organisation's files (Req 22.2).
    """
    org_id = str(org_id)
    selected: list[FileIndexEntry] = []
    for entry in file_index.entries:
        owning = None if entry.org_id is None else str(entry.org_id)
        if owning == org_id:
            selected.append(entry)
    return selected


class PerOrgFileRestorer:
    """Reassembles one org's file set strictly from the chosen backup's
    File_Index (Req 22, 24)."""

    def __init__(
        self,
        reader: ArtifactReader,
        sink: FileRestoreSink,
        *,
        upload_roots: Sequence[str] = ("/app/uploads", "/app/compliance_files"),
    ) -> None:
        self.reader = reader
        self.sink = sink
        self.upload_roots = tuple(upload_roots)

    async def restore_files(
        self,
        file_index: FileIndex,
        org_id: str,
        *,
        id_remap: Optional[Mapping[tuple[str, Any], Any]] = None,
    ) -> FileRestoreResult:
        """Fetch and write every File_Index entry owned by *org_id*.

        Args:
            file_index: The chosen backup's File_Index (Property 19 — the restore
                set is sourced strictly from this index).
            org_id: The selected organisation.
            id_remap: When restoring-as-new, the apply engine's id remap so each
                file's path is rewritten consistently with the rewritten row
                identifiers (Req 22.4).

        Raises:
            FileBlobUnavailableError: if a referenced File_Blob cannot be fetched
                or fails its Content_Hash check (Req 24.4) — the job fails.
        """
        result = FileRestoreResult(known_skip_count=file_index.skipped_count)
        entries = filter_file_index_for_org(file_index, org_id)

        for entry in entries:
            try:
                data = await self.reader.read_blob(entry.content_hash)
            except FileBlobUnavailableError:
                raise
            except Exception as exc:  # normalise any fetch failure (Req 24.4)
                raise FileBlobUnavailableError(
                    f"referenced File_Blob {entry.content_hash} for "
                    f"{entry.path!r} could not be retrieved: {exc}",
                    file_reference=entry.path,
                ) from exc

            # Integrity: the fetched plaintext must match the recorded hash.
            if content_hash(data) != entry.content_hash:
                raise FileBlobUnavailableError(
                    f"File_Blob for {entry.path!r} failed its integrity check "
                    f"(content hash mismatch)",
                    file_reference=entry.path,
                )

            target_path = self._rewrite_path(entry.path, id_remap)
            try:
                await self.sink.write_file(target_path, data)
            except OSError as exc:
                # Req 22.7 — record the failed path and fail the job.
                raise FileBlobUnavailableError(
                    f"failed to write restored file {target_path!r}: "
                    f"{exc.strerror or exc}",
                    file_reference=target_path,
                ) from exc
            result.restored_paths.append(target_path)

        # Post-restore file-consistency check (Req 22.5/22.6): every entry we
        # intended to restore must now exist on disk. A File_Index entry always
        # has a captured blob, so a missing file here is a genuine defect; true
        # capture-window known-skips are omitted from the index entirely and are
        # reported only as the informational ``known_skip_count``.
        for path in result.restored_paths:
            if not await self.sink.exists(path):
                result.missing_references.append(path)
        if result.missing_references:
            result.file_consistency_outcome = "failed"
        return result

    def _rewrite_path(
        self, path: str, id_remap: Optional[Mapping[tuple[str, Any], Any]]
    ) -> str:
        """Rewrite *path* so any remapped row id embedded in it is updated.

        For restore-as-new (Req 22.4) a file whose ``file_key``/path embeds a row
        id must be written under the rewritten id so the DB reference and the
        on-disk file stay consistent. Best-effort textual substitution of each
        remapped old id for its new id.
        """
        if not id_remap:
            return path
        rewritten = path
        for (_table, old_id), new_id in id_remap.items():
            if old_id is None:
                continue
            old_s = str(old_id)
            if old_s and old_s in rewritten:
                rewritten = rewritten.replace(old_s, str(new_id))
        return rewritten


# ---------------------------------------------------------------------------
# Orchestrating service.
# ---------------------------------------------------------------------------


@dataclass
class PerOrgRestoreResult:
    """The overall outcome of a per-organisation restore."""

    org_id: str
    conflict_policy: ConflictPolicy
    extraction_path: str  # "logical_export" | "scratch_db"
    apply_stats: ApplyStats
    file_result: FileRestoreResult
    succeeded: bool = True


class PerOrgRestoreService:
    """Restores a single organisation's data from a Full_Backup (Req 14).

    All external dependencies are injected so the upcoming property tests
    (10.5–10.9) can drive the logic with the DB, storage, scratch-DB
    provisioning, and filesystem mocked:

    Args:
        reader: Fetches backup artifacts (manifest, dump, per-org export, blobs).
        target: Transactional, RLS-scoped write surface for the apply.
        dump_extractor: Stages the full dump into an ephemeral scratch DB and
            extracts one org (Req 31.4/31.5) — the fallback when no usable
            Per_Org_Logical_Export exists.
        file_sink: Writes restored file bytes to disk.
        schema: Schema/PK/FK/classification model (defaults to the live schema).
        id_factory: Identifier factory for restore-as-new (testable seam).
    """

    def __init__(
        self,
        reader: ArtifactReader,
        target: RestoreTarget,
        dump_extractor: DumpExtractor,
        file_sink: FileRestoreSink,
        *,
        schema: Optional[SchemaModel] = None,
        id_factory=_default_id_factory,
    ) -> None:
        self.reader = reader
        self.target = target
        self.dump_extractor = dump_extractor
        self.file_sink = file_sink
        self.schema = schema or SchemaModel()
        self.id_factory = id_factory

    async def restore(
        self,
        org_id: str,
        conflict_policy: "str | ConflictPolicy",
        *,
        selected_tables: Optional[Sequence[str]] = None,
        restore_files: bool = True,
        on_progress: "Optional[ProgressCallback]" = None,
        should_cancel: "Optional[CancelCheck]" = None,
    ) -> PerOrgRestoreResult:
        """Run the per-organisation restore for *org_id*.

        Sequence (design.md "Per-organisation restore"):
          1. Integrity + presence gates (Req 7.4, 14.8, 14.9) — no write before
             both pass.
          2. Extraction (Req 31) — logical-export fast path, else scratch DB,
             with fallback on export integrity failure (Req 31.7).
          3. Atomic, classification-driven apply (Req 14.3/14.6/14.7/14.10).
          4. File restore from the File_Index filtered to the org (Req 22, 24).

        *on_progress(pct, message)* — if given — is awaited at each phase boundary
        and periodically during the apply so callers can show live progress.
        *should_cancel()* — if given — is polled; a requested cancel aborts the
        apply and rolls back with no data applied (Req 12.16).
        """
        org_id = str(org_id)
        policy = ConflictPolicy.from_value(conflict_policy)

        async def _emit(pct: int, message: str) -> None:
            if on_progress is not None:
                await on_progress(pct, message)

        def _check_cancel() -> None:
            if should_cancel is not None and should_cancel():
                raise RestoreCancelledError(
                    "restore cancelled before completion; no data was applied"
                )

        # --- Step 1: integrity + presence (no write before both gates) ----
        await _emit(3, "Verifying backup integrity…")
        _check_cancel()
        manifest = await self._verify_integrity()
        if org_id not in {str(o) for o in manifest.envelope.org_ids}:
            raise OrganisationNotFoundError(
                f"organisation {org_id!r} is not present in the selected backup"
            )

        # --- Step 2: extraction (Req 31) ----------------------------------
        await _emit(10, "Reading organisation data from the backup…")
        _check_cancel()
        dataset, extraction_path = await self._extract(manifest, org_id)
        row_total = sum(len(rows) for rows in dataset.rows_by_table.values())
        await _emit(
            30,
            f"Extracted {row_total:,} records; applying changes…",
        )
        _check_cancel()

        # --- Step 3: atomic, classification-driven apply ------------------
        engine = PerOrgApplyEngine(
            self.schema, self.target, id_factory=self.id_factory
        )

        async def _apply_progress(done: int, total: int) -> None:
            # Map apply row progress onto the 30–90% band.
            frac = (done / total) if total else 1.0
            pct = 30 + int(frac * 60)
            await _emit(min(90, pct), f"Applying records {done:,} / {total:,}…")

        try:
            apply_stats = await engine.apply(
                dataset,
                org_id,
                policy,
                selected_tables=selected_tables,
                progress=_apply_progress,
                should_cancel=should_cancel,
            )
        except (PerOrgRestoreError, RestoreCancelledError):
            raise
        except Exception as exc:
            # Any error after writes began rolled back inside target.atomic()
            # (Req 14.10). Surface a human-readable, rolled-back failure; the raw
            # error is preserved in the logs via the exception chain.
            logger.warning("Per-org restore apply failed", exc_info=True)
            friendly = humanize_restore_db_error(exc)
            raise RestoreApplyError(
                friendly
                or f"the restore could not be applied and was rolled back: {exc}"
            ) from exc

        # --- Step 4: file restore (Req 22, 24) ----------------------------
        if restore_files:
            await _emit(92, "Restoring stored files…")
            file_result = await PerOrgFileRestorer(
                self.reader, self.file_sink
            ).restore_files(
                manifest.envelope.file_index,
                org_id,
                id_remap=engine.id_remap if policy is ConflictPolicy.RESTORE_AS_NEW else None,
            )
        else:
            file_result = FileRestoreResult()

        await _emit(100, "Finalising…")
        return PerOrgRestoreResult(
            org_id=org_id,
            conflict_policy=policy,
            extraction_path=extraction_path,
            apply_stats=apply_stats,
            file_result=file_result,
            succeeded=file_result.file_consistency_outcome != "failed",
        )

    # -- step 1 -------------------------------------------------------------

    async def _verify_integrity(self) -> BackupManifest:
        """Verify the manifest checksum against the encrypted dump (Req 7.4/14.8).

        Aborts before any write if the artifact cannot be read or its checksum
        does not match the value recorded in the manifest catalog.
        """
        try:
            manifest = await self.reader.read_manifest()
        except Exception as exc:
            raise BackupUnreadableError(
                f"the selected backup manifest could not be read: {exc}"
            ) from exc

        try:
            encrypted_dump = await self.reader.read_encrypted_dump()
        except Exception as exc:
            raise BackupUnreadableError(
                f"the selected backup dump could not be read: {exc}"
            ) from exc

        actual = content_hash(encrypted_dump)
        if actual != manifest.catalog.checksum:
            raise BackupUnreadableError(
                "the selected backup failed integrity validation: the dump "
                "checksum does not match the manifest"
            )
        return manifest

    # -- step 2 -------------------------------------------------------------

    async def _extract(
        self, manifest: BackupManifest, org_id: str
    ) -> tuple[ExtractedDataset, str]:
        """Extract the org's rows via the fast path, else the scratch DB (Req 31).

        Tries the Per_Org_Logical_Export when recorded (Req 31.3); on a missing
        or corrupt export falls back to staging the full dump into an ephemeral
        scratch database (Req 31.4/31.7).
        """
        entry = next(
            (
                e
                for e in manifest.envelope.per_org_index.entries
                if str(e.org_id) == org_id
            ),
            None,
        )
        if (
            entry is not None
            and entry.logical_export_emitted
            and entry.logical_export_location
        ):
            try:
                raw = await self.reader.read_per_org_export(
                    entry.logical_export_location
                )
                dataset = parse_per_org_export(raw, org_id)
                logger.info(
                    "Per-org restore: extracted org %s from Per_Org_Logical_Export "
                    "(fast path, Req 31.3)",
                    org_id,
                )
                return dataset, "logical_export"
            except PerOrgExportError as exc:
                # Req 31.7 — a recorded export that fails integrity falls back to
                # staging the full dump rather than failing the restore.
                logger.warning(
                    "Per-org restore: Per_Org_Logical_Export for org %s unusable "
                    "(%s); falling back to staging the full dump (Req 31.7)",
                    org_id,
                    exc,
                )

        # Scratch-DB path (Req 31.4/31.5). The extractor owns provisioning and
        # guaranteed teardown.
        dump_plaintext = await self.reader.read_dump_plaintext()
        dataset = await self.dump_extractor.extract_org(
            dump_plaintext, org_id, self.schema
        )
        logger.info(
            "Per-org restore: extracted org %s by staging the full dump into an "
            "ephemeral scratch database (Req 31.4)",
            org_id,
        )
        return dataset, "scratch_db"


# ===========================================================================
# Production concrete implementations of the injectable seams.
#
# These wire the abstract seams above to the real StorageInterface, the
# AsyncSession (under target-org RLS), the filesystem, and an ephemeral scratch
# PostgreSQL database. Tests inject lightweight fakes instead.
# ===========================================================================


async def _consume_stream(stream) -> bytes:
    """Consume an ``AsyncByteStream`` (or awaitable thereof) fully into bytes."""
    if hasattr(stream, "__await__"):
        stream = await stream
    chunks: list[bytes] = []
    async for chunk in stream:
        chunks.append(chunk)
    return b"".join(chunks)


# Storage-key conventions (mirrors backup/pipeline.py and backup/prune.py).
MANIFEST_KEY_TEMPLATE = "backups/{backup_id}/manifest.json"
DUMP_KEY_TEMPLATE = "backups/{backup_id}/dump.enc"


class StorageArtifactReader(ArtifactReader):
    """:class:`ArtifactReader` backed by a ``StorageInterface`` adapter + BDK.

    Downloads ciphertext through the provider-agnostic interface and decrypts it
    with the resolved Backup_Data_Key, so the restore logic never touches a
    specific Cloud_Provider (Req 3) and only ever sees plaintext after the
    escrowed key has decrypted it (Req 16).
    """

    def __init__(
        self,
        storage,
        bdk: bytes,
        db,
        backup_id,
        *,
        blob_prefix: str = "backup_blobs",
    ) -> None:
        self.storage = storage
        self.bdk = bdk
        self.db = db
        self.backup_id = str(backup_id)
        self.blob_prefix = blob_prefix.rstrip("/")
        self._encrypted_dump: bytes | None = None

    async def _download(self, key: str) -> bytes:
        return await _consume_stream(self.storage.download(key))

    async def read_manifest(self) -> BackupManifest:
        from app.modules.backup_restore.backup.manifest import deserialize_manifest

        raw = await self._download(MANIFEST_KEY_TEMPLATE.format(backup_id=self.backup_id))
        return deserialize_manifest(raw, self.bdk)

    async def read_encrypted_dump(self) -> bytes:
        if self._encrypted_dump is None:
            self._encrypted_dump = await self._download(
                DUMP_KEY_TEMPLATE.format(backup_id=self.backup_id)
            )
        return self._encrypted_dump

    async def read_dump_plaintext(self) -> bytes:
        from app.modules.backup_restore.keys.key_service import backup_envelope_decrypt

        encrypted = await self.read_encrypted_dump()
        return backup_envelope_decrypt(encrypted, self.bdk)

    async def read_per_org_export(self, location: str) -> bytes:
        from app.modules.backup_restore.keys.key_service import backup_envelope_decrypt

        try:
            ciphertext = await self._download(location)
            return backup_envelope_decrypt(ciphertext, self.bdk)
        except Exception as exc:
            raise PerOrgExportError(
                f"Per_Org_Logical_Export at {location!r} could not be read/decrypted: "
                f"{exc}"
            ) from exc

    async def read_blob(self, content_hash_hex: str) -> bytes:
        from sqlalchemy import select

        from app.modules.backup_restore.keys.key_service import backup_envelope_decrypt
        from app.modules.backup_restore.models import BackupBlob

        result = await self.db.execute(
            select(BackupBlob.blob_name).where(
                BackupBlob.content_hash == content_hash_hex
            )
        )
        blob_name = result.scalar_one_or_none()
        if blob_name is None:
            raise FileBlobUnavailableError(
                f"no stored File_Blob is recorded for content hash {content_hash_hex}",
                file_reference=content_hash_hex,
            )
        key = f"{self.blob_prefix}/{blob_name}"
        try:
            ciphertext = await self._download(key)
            return backup_envelope_decrypt(ciphertext, self.bdk)
        except Exception as exc:
            raise FileBlobUnavailableError(
                f"File_Blob {content_hash_hex} could not be retrieved/decrypted: {exc}",
                file_reference=content_hash_hex,
            ) from exc


class SqlAlchemyRestoreTarget(RestoreTarget):
    """:class:`RestoreTarget` backed by an ``AsyncSession`` under target-org RLS.

    Writes run under the target org's ``app.current_org_id`` (defence-in-depth
    alongside the application-level cross-org checks, Req 14.3) and inside a
    SAVEPOINT so any error rolls the whole apply back (Req 14.10). Per the
    project ``session.begin()`` auto-commit pattern the session is not committed
    here — the surrounding request/task transaction commits on success.
    """

    def __init__(self, db, schema: SchemaModel) -> None:
        self.db = db
        self.schema = schema
        # Cache of natural/unique keys reflected from the LIVE database per
        # table (column-name tuples, PK excluded). The database — not the ORM
        # metadata — is authoritative: unique indexes added by migrations are
        # often absent from the model definitions, yet Postgres still enforces
        # them, so identity resolution must reflect what actually exists.
        self._db_unique_keys: dict[str, list[tuple[str, ...]]] = {}

    async def _reflect_unique_keys(self, table_name: str) -> list[tuple[str, ...]]:
        """Return the table's unique keys (column tuples) reflected from Postgres.

        Includes every non-primary unique index over plain columns; partial
        (``WHERE``) and expression indexes are skipped because they cannot be
        matched by a simple column-equality lookup. Cached per table.
        """
        if table_name in self._db_unique_keys:
            return self._db_unique_keys[table_name]
        from sqlalchemy import text as _text

        sql = _text(
            """
            SELECT ix.indexrelid AS index_id, a.attname AS col, k.ord AS ord
            FROM pg_index ix
            JOIN pg_class t ON t.oid = ix.indrelid
            JOIN unnest(ix.indkey) WITH ORDINALITY AS k(attnum, ord) ON true
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
            WHERE t.relname = :table
              AND t.relnamespace = 'public'::regnamespace
              AND ix.indisunique
              AND NOT ix.indisprimary
              AND ix.indpred IS NULL
              AND k.attnum <> 0
            ORDER BY ix.indexrelid, k.ord
            """
        )
        try:
            rows = (await self.db.execute(sql, {"table": table_name})).fetchall()
        except Exception:  # noqa: BLE001 - reflection is best-effort
            logger.debug(
                "could not reflect unique keys for %s", table_name, exc_info=True
            )
            rows = []
        by_index: dict[Any, list[str]] = {}
        for index_id, col, _ord in rows:
            by_index.setdefault(index_id, []).append(col)
        keys = [tuple(cols) for cols in by_index.values() if cols]
        self._db_unique_keys[table_name] = keys
        return keys

    async def set_org_context(self, org_id: str) -> None:
        from app.core.database import _set_rls_org_id

        await _set_rls_org_id(self.db, org_id)

    def atomic(self):
        # A SAVEPOINT: rolls back exactly this apply's writes on error while the
        # surrounding transaction continues so the job failure can be recorded.
        return self.db.begin_nested()

    def _table(self, table: str):
        tbl = self.schema.metadata.tables.get(table)
        if tbl is None:
            raise RestoreApplyError(f"unknown table {table!r} for per-org restore")
        return tbl

    def _filter_columns(self, table, values: Mapping[str, Any]) -> dict[str, Any]:
        cols = set(table.columns.keys())
        return {k: v for k, v in values.items() if k in cols}

    async def org_row_exists(self, table_name, pk_columns, pk) -> bool:
        from sqlalchemy import and_, select

        table = self._table(table_name)
        conditions = [table.c[col] == val for col, val in zip(pk_columns, pk)]
        result = await self.db.execute(
            select(table.c[pk_columns[0]]).where(and_(*conditions)).limit(1)
        )
        return result.first() is not None

    async def shared_global_equivalent(self, table_name, row, pk_columns):
        pk = tuple(row.values.get(c) for c in pk_columns)
        if any(v is None for v in pk):
            return None
        return pk if await self.org_row_exists(table_name, pk_columns, pk) else None

    async def find_existing_pk(
        self, table_name, pk_columns, pk, unique_keys, values
    ) -> tuple | None:
        from sqlalchemy import and_, select

        table = self._table(table_name)
        # 1) Match by primary key.
        if all(v is not None for v in pk) and await self.org_row_exists(
            table_name, pk_columns, pk
        ):
            return pk
        # 2) Match by any natural / unique key. Use the union of the keys the
        #    ORM declares and the keys actually enforced by Postgres (the latter
        #    catches unique indexes added only by migrations). The first
        #    existing match wins; its (possibly different) primary key is
        #    returned so the caller can update it in place and remap child FKs.
        reflected = await self._reflect_unique_keys(table_name)
        candidate_keys: list[tuple[str, ...]] = []
        seen: set[tuple[str, ...]] = set()
        for uk in list(unique_keys) + reflected:
            uk = tuple(uk)
            if uk and uk not in seen:
                seen.add(uk)
                candidate_keys.append(uk)
        for uk in candidate_keys:
            if any(col not in table.c for col in uk):
                continue
            uk_values = [values.get(col) for col in uk]
            if any(v is None for v in uk_values):
                continue  # a NULL never participates in a unique match
            conditions = [table.c[col] == val for col, val in zip(uk, uk_values)]
            result = await self.db.execute(
                select(*[table.c[c] for c in pk_columns])
                .where(and_(*conditions))
                .limit(1)
            )
            found = result.first()
            if found is not None:
                return tuple(found)
        return None

    async def insert(self, table_name, values) -> None:
        table = self._table(table_name)
        await self.db.execute(table.insert().values(**self._filter_columns(table, values)))
        await self.db.flush()

    async def insert_or_skip(self, table_name, pk_columns, pk, values) -> bool:
        # Atomic, race-free skip that honours EVERY unique constraint (the PK
        # and any natural/unique key such as (org_id, code)). Postgres skips the
        # row on ANY conflict without raising — so a backup row that carries a
        # different surrogate PK but the same natural key as an existing target
        # row is skipped cleanly instead of aborting the apply transaction
        # (Req 14.5). Scales to large datasets: a single round-trip per row, no
        # pre-SELECT, and no transaction poisoning.
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        table = self._table(table_name)
        stmt = (
            pg_insert(table)
            .values(**self._filter_columns(table, values))
            .on_conflict_do_nothing()
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return (result.rowcount or 0) > 0

    async def update(self, table_name, pk_columns, pk, values) -> None:
        from sqlalchemy import and_

        table = self._table(table_name)
        conditions = [table.c[col] == val for col, val in zip(pk_columns, pk)]
        payload = {
            k: v
            for k, v in self._filter_columns(table, values).items()
            if k not in set(pk_columns)
        }
        await self.db.execute(table.update().where(and_(*conditions)).values(**payload))
        await self.db.flush()


class FilesystemFileRestoreSink(FileRestoreSink):
    """:class:`FileRestoreSink` that writes under the upload storage roots.

    Writes are confined to the configured roots (``/app/uploads`` and
    ``/app/compliance_files``) so a malformed path cannot escape them, and each
    file is written temp-then-rename for atomicity.
    """

    def __init__(
        self,
        allowed_roots: Sequence[str] = ("/app/uploads", "/app/compliance_files"),
    ) -> None:
        import os

        self.allowed_roots = tuple(os.path.realpath(r) for r in allowed_roots)

    def _resolve(self, path: str) -> str:
        import os

        candidate = os.path.realpath(path if os.path.isabs(path) else os.path.join(self.allowed_roots[0], path))
        for root in self.allowed_roots:
            if candidate == root or candidate.startswith(root + os.sep):
                return candidate
        raise OSError(
            f"restore path {path!r} escapes the permitted upload roots"
        )

    async def exists(self, path: str) -> bool:
        import os

        try:
            return os.path.exists(self._resolve(path))
        except OSError:
            return False

    async def write_file(self, path: str, data: bytes) -> None:
        import os
        import tempfile

        target = self._resolve(path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target), suffix=".part")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


class ScratchDbDumpExtractor(DumpExtractor):
    """Stages the full custom-format dump into an ephemeral scratch PostgreSQL
    database and extracts one org's Org_Scoped_Rows (Req 31.4/31.5).

    Used only when no usable Per_Org_Logical_Export exists. The scratch database
    is created with a unique name, the dump is ``pg_restore``\\ -d into it, the
    org's rows are read out by ``org_id``, and the scratch database is **always**
    dropped afterwards (Req 31.5), regardless of success or failure.

    The admin connection string and binary are injectable so this is testable
    and portable; provisioning a separate scratch *server* (rather than a
    database on the same server) can be substituted by overriding
    :meth:`_provision` / :meth:`_teardown`.
    """

    def __init__(
        self,
        admin_dsn: str,
        *,
        pg_restore_bin: str = "pg_restore",
        db_name_prefix: str = "orainvoice_scratch_",
    ) -> None:
        self.admin_dsn = admin_dsn
        self.pg_restore_bin = pg_restore_bin
        self.db_name_prefix = db_name_prefix

    async def extract_org(
        self, dump_plaintext: bytes, org_id: str, schema: SchemaModel
    ) -> ExtractedDataset:
        import os
        import tempfile

        scratch_db = f"{self.db_name_prefix}{uuid.uuid4().hex}"
        dump_path = None
        try:
            await self._provision(scratch_db)

            fd, dump_path = tempfile.mkstemp(prefix="orainvoice_restore_", suffix=".dump")
            with os.fdopen(fd, "wb") as fh:
                fh.write(dump_plaintext)

            await self._pg_restore(scratch_db, dump_path)
            return await self._extract_rows(scratch_db, org_id, schema)
        finally:
            # Req 31.5 — tear the scratch DB down regardless of outcome.
            if dump_path is not None:
                try:
                    os.unlink(dump_path)
                except OSError:
                    pass
            await self._teardown(scratch_db)

    # -- provisioning -------------------------------------------------------

    async def _admin_conn(self):
        import asyncpg

        return await asyncpg.connect(self._asyncpg_dsn(self.admin_dsn))

    def _asyncpg_dsn(self, dsn: str) -> str:
        return dsn.replace("postgresql+asyncpg://", "postgresql://", 1)

    def _scratch_dsn(self, scratch_db: str) -> str:
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(self._asyncpg_dsn(self.admin_dsn))
        return urlunsplit(parts._replace(path=f"/{scratch_db}"))

    async def _provision(self, scratch_db: str) -> None:
        conn = await self._admin_conn()
        try:
            await conn.execute(f'CREATE DATABASE "{scratch_db}"')
        finally:
            await conn.close()

    async def _teardown(self, scratch_db: str) -> None:
        try:
            conn = await self._admin_conn()
        except Exception:
            logger.warning(
                "Per-org restore: could not connect to drop scratch DB %s; it may "
                "need manual cleanup",
                scratch_db,
            )
            return
        try:
            # Terminate stragglers then drop.
            await conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = $1 AND pid <> pg_backend_pid()",
                scratch_db,
            )
            await conn.execute(f'DROP DATABASE IF EXISTS "{scratch_db}"')
        except Exception:
            logger.warning(
                "Per-org restore: failed to drop scratch DB %s; manual cleanup may "
                "be required",
                scratch_db,
                exc_info=True,
            )
        finally:
            await conn.close()

    async def _pg_restore(self, scratch_db: str, dump_path: str) -> None:
        import asyncio

        cmd = [
            self.pg_restore_bin,
            "--no-owner",
            "--no-privileges",
            f"--dbname={self._scratch_dsn(scratch_db)}",
            dump_path,
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        detail = (stderr or b"").decode("utf-8", errors="replace").strip()
        if process.returncode == 0:
            return
        # pg_restore continues past per-object errors by default and still loads
        # all DATA, but exits non-zero when any object failed. The scratch DB is a
        # throwaway used ONLY to read an org's rows, so post-load object failures
        # — e.g. a FK constraint that can't be added because the SOURCE has an
        # orphaned row — are irrelevant: the rows are present. Treat "errors
        # ignored on restore" (the archive was processed to completion) as a
        # tolerable warning so a DR restore is robust to minor source-data
        # imperfections; only a hard failure (could not connect / open the dump /
        # nothing restored) is fatal.
        if "errors ignored on restore" in detail.lower():
            logger.warning(
                "pg_restore into scratch DB %s completed with ignored object "
                "errors (data loaded; some constraints/triggers were not recreated "
                "in the scratch copy, which does not affect row extraction): %s",
                scratch_db,
                detail,
            )
            return
        raise PerOrgRestoreError(
            f"staging the full dump into the scratch database failed "
            f"(pg_restore exit {process.returncode}): {detail}"
        )

    async def _extract_rows(
        self, scratch_db: str, org_id: str, schema: SchemaModel
    ) -> ExtractedDataset:
        import asyncpg

        dataset = ExtractedDataset(org_id=str(org_id))
        conn = await asyncpg.connect(self._scratch_dsn(scratch_db))
        try:
            for table in schema.org_scoped_tables():
                pk_cols = schema.pk_columns(table)
                # Org-scoped + hybrid tables both carry an org_id column; select
                # only this org's rows (hybrid NULL rows are shared-global and
                # are handled by ensure-exists, so they are excluded here).
                rows = await conn.fetch(
                    f'SELECT * FROM "{table}" WHERE {ORG_ID_COLUMN} = $1', org_id
                )
                for record in rows:
                    values = dict(record)
                    pk = tuple(values.get(c) for c in pk_cols)
                    dataset.add_row(
                        ExtractedRow(
                            table=table,
                            values=values,
                            pk=pk,
                            org_id=_row_org_id(values),
                        ),
                        pk_cols,
                    )
        finally:
            await conn.close()
        return dataset
