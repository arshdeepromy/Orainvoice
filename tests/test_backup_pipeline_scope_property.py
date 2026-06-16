"""Property-based test: scope determines the included data exactly.

# Feature: cloud-backup-restore, Property 18: Scope determines included data exactly

**Validates: Requirements 6.2, 6.3, 6.4, 6.5**

For any valid ``Backup_Scope`` the backup pipeline
(``app/modules/backup_restore/backup/pipeline.py``) includes exactly the data the
scope prescribes:

* **The full DB dump is always present (Req 6.5 / unconditional dump).** Every
  scope produces the ``pg_dump`` artifact — the dump is never scope-gated.
* **``settings_only`` captures NO uploaded files (Req 6.3).** Settings/integration
  configuration travels inside the dump, so no File_Blobs are captured and the
  File_Index is empty regardless of how many files exist on the volumes.
* **``organisations_only`` / ``both`` capture the uploaded files (Req 6.4, 6.5).**
  Every readable file under the storage roots is content-addressed into the store,
  so the captured File_Index count equals the number of files present.
* **The selected scope is recorded on the committed backup (Req 6.2 / 6.8).** The
  pipeline result and the committed ``backups`` row both carry the scope value.

Invalid-scope rejection (Req 6.2's reject path) is the unit test (task 8.4); this
property focuses on the inclusion behaviour of the three valid scopes.

Per the project PBT rule the database and storage are mocked: ``FakeStorage`` is an
in-memory ``StorageInterface`` recording uploaded objects, ``FakeAsyncSession`` is an
in-memory stand-in for the ``backup_blobs`` dedup index / ``backup_config`` /
``alembic_version`` reads and the catalog-row inserts, the ``pg_dump`` runner is a
fake emitting a temp dump file, and a fixed Backup_Data_Key replaces the key service.
No real network, SDK, filesystem volume, or database is exercised.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from datetime import datetime, timezone

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.modules.backup_restore.backup.pg_dump_runner import PgDumpResult
from app.modules.backup_restore.backup.pipeline import (
    BackupPipeline,
    DestinationTarget,
)
from app.modules.backup_restore.models import Backup, BackupBlob
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
    max_examples=120,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

VALID_SCOPES = ("settings_only", "organisations_only", "both")
_FILE_SCOPES = frozenset({"organisations_only", "both"})

# A fixed 32-byte Backup_Data_Key keeps envelope encryption deterministic and off
# the ENCRYPTION_MASTER_KEY path (the BDK is the only artifact key, Req 21.4).
_BDK = bytes(range(32))
_BLOB_PREFIX = "backup_blobs"


# ---------------------------------------------------------------------------
# Test doubles (mocked storage adapter, key service, dump runner, DB session)
# ---------------------------------------------------------------------------


class FakeStorage(StorageInterface):
    """In-memory StorageInterface recording every uploaded object by key."""

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

    async def list(self, prefix: str) -> list[RemoteObject]:
        return [
            RemoteObject(key=k, size_bytes=len(v), modified_at=None)
            for k, v in self.objects.items()
            if k.startswith(prefix)
        ]

    async def download(self, key: str) -> AsyncByteStream:
        data = self.objects[key]

        async def _gen():
            yield data

        return _gen()

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    async def connection_status(self) -> ConnectionState:
        return ConnectionState.connected


class FakeDestination:
    """Minimal stand-in for a ``backup_destinations`` row (single primary)."""

    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.is_primary = True
        self.is_immutable_copy = False
        self.lock_window_days = None


class FakeKeyService:
    """Key service stand-in returning a fixed active Backup_Data_Key."""

    async def get_active_bdk(self) -> tuple[int, bytes]:
        return 1, _BDK


class _Result:
    """Stand-in for an SQLAlchemy ``Result`` (scalar_one_or_none / first)."""

    def __init__(self, *, scalar=None, rows=None) -> None:
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def first(self):
        return self._rows[0] if self._rows else None


class FakeAsyncSession:
    """In-memory stand-in for the DB session used across the pipeline.

    Backs the ``backup_blobs`` dedup index (``select(BackupBlob)...``), the
    single-row ``backup_config`` read, and the ``alembic_version`` schema read,
    and records every staged catalog row (``backups`` etc.) for assertions.
    """

    def __init__(self) -> None:
        self.blobs: dict[str, BackupBlob] = {}
        self.added: list[object] = []
        self._pending_blobs: list[BackupBlob] = []

    async def execute(self, stmt):
        sql = str(stmt)
        if "alembic_version" in sql:
            return _Result(rows=[("test_revision_0194",)])
        entity = None
        try:
            entity = stmt.column_descriptions[0]["entity"]
        except Exception:
            entity = None
        if entity is BackupBlob:
            hash_value = None
            try:
                hash_value = stmt.whereclause.right.value
            except Exception:
                hash_value = None
            return _Result(scalar=self.blobs.get(hash_value))
        # backup_config (single row) and any other select: none configured.
        return _Result(scalar=None)

    def add(self, obj) -> None:
        self.added.append(obj)
        if isinstance(obj, BackupBlob):
            self._pending_blobs.append(obj)

    async def flush(self) -> None:
        for blob in self._pending_blobs:
            self.blobs[blob.content_hash] = blob
        self._pending_blobs.clear()

    async def refresh(self, obj) -> None:
        return None

    def added_of(self, cls):
        return [o for o in self.added if isinstance(o, cls)]


def _make_dump_runner(dump_bytes: bytes):
    """Build a fake ``pg_dump`` runner emitting a temp dump file of ``dump_bytes``."""

    async def _runner(db) -> PgDumpResult:
        fd, path = tempfile.mkstemp(suffix=".dump")
        with os.fdopen(fd, "wb") as fh:
            fh.write(dump_bytes)
        return PgDumpResult(
            dump_path=path,
            byte_size=len(dump_bytes),
            database_name="testdb",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        )

    return _runner


def _write_volume_files(root: str, contents: list[bytes]) -> None:
    """Create ``contents`` as files under ``root`` in org-shaped subfolders.

    Files live at ``{root}/uploads/{category}/{org_id}/{name}`` so the pipeline's
    default org-id resolver finds an owning org, mirroring real volume layout.
    """
    for idx, data in enumerate(contents):
        org_id = str(uuid.uuid4())
        sub = os.path.join(root, "invoices", org_id)
        os.makedirs(sub, exist_ok=True)
        with open(os.path.join(sub, f"file_{idx}.bin"), "wb") as fh:
            fh.write(data)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

scopes = st.sampled_from(VALID_SCOPES)
# 0..6 uploaded files; content may repeat (exercises dedup without changing the
# captured File_Index count — each readable file yields one File_Index entry).
file_contents = st.lists(st.binary(min_size=0, max_size=48), min_size=0, max_size=6)
dump_contents = st.binary(min_size=1, max_size=128)


# ---------------------------------------------------------------------------
# Property 18: Scope determines included data exactly
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(scope=scopes, contents=file_contents, dump_bytes=dump_contents)
def test_scope_determines_included_data_exactly(
    scope: str, contents: list[bytes], dump_bytes: bytes
):
    """For each valid scope, included data matches the scope exactly.

    **Validates: Requirements 6.2, 6.3, 6.4, 6.5**
    """
    n_files = len(contents)

    with tempfile.TemporaryDirectory() as uploads_root, tempfile.TemporaryDirectory() as compliance_root:
        _write_volume_files(uploads_root, contents)

        storage = FakeStorage()
        destination = DestinationTarget(destination=FakeDestination(), storage=storage)
        db = FakeAsyncSession()

        pipeline = BackupPipeline(
            db,
            key_service=FakeKeyService(),
            destinations=[destination],
            storage_roots=[uploads_root, compliance_root],
            dump_runner=_make_dump_runner(dump_bytes),
            blob_prefix=_BLOB_PREFIX,
            app_version="test-1.13.0",
        )

        result = asyncio.run(pipeline.run(scope=scope, triggered_by="manual"))

        # -- The selected scope is recorded on the backup (Req 6.2 / 6.8) ------
        assert result.scope == scope
        committed = db.added_of(Backup)
        assert len(committed) == 1
        assert committed[0].scope == scope

        # -- The full DB dump is always present, never scope-gated -------------
        assert result.dump_size_bytes == len(dump_bytes)
        assert result.encrypted_dump_size > 0

        blob_keys = [k for k in storage.objects if k.startswith(_BLOB_PREFIX + "/")]

        if scope in _FILE_SCOPES:
            # organisations_only / both: every readable file is captured (Req 6.4/6.5).
            assert result.file_count == n_files
            # File_Blobs are uploaded iff there were files to capture.
            assert (len(blob_keys) > 0) == (n_files > 0)
        else:
            # settings_only: NO uploaded files captured (Req 6.3).
            assert scope == "settings_only"
            assert result.file_count == 0
            assert blob_keys == []
            assert result.org_ids == []


if __name__ == "__main__":  # pragma: no cover
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
