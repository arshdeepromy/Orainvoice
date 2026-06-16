"""Unit tests for backup-pipeline invalid-scope rejection.

# Feature: cloud-backup-restore, task 8.4 — invalid scope rejection

Covers ``app/modules/backup_restore/backup/pipeline.py`` pre-flight scope
validation (design "Backup Pipeline" step 1a):

* **Invalid Backup_Scope is rejected (Req 6.1, 6.2).** ``BackupPipeline.run`` (and
  the ``run_backup`` convenience wrapper) raise :class:`BackupScopeError` when the
  scope is absent/empty or not one of ``settings_only`` / ``organisations_only`` /
  ``both``. Rejection happens BEFORE any work, so:
    - the injected ``dump_runner`` is never called (no dump is produced),
    - the destination storage adapters record ZERO uploads (no artifact/manifest
      is created at any destination),
    - the supplied ``BackupJob`` (when provided) is marked ``failed``.

Per the project PBT/test rule the storage adapters and the DB session are
replaced by in-memory doubles modelled on ``tests/test_backup_prune.py`` and
``tests/test_backup_cas_dedup_property.py``:

* ``RaisingDumpRunner`` raises ``AssertionError`` if invoked — its non-invocation
  is the proof the dump never ran.
* ``FakeStorage`` records every ``upload`` call so we can assert zero uploads.
* ``FakeAsyncSession`` is an in-memory stand-in supporting the ``flush()`` /
  ``refresh()`` seam ``_mark_job_failed`` relies on.
* A real :class:`DestinationTarget` wraps a :class:`BackupDestination` row + a
  ``FakeStorage`` so the fan-out path would be exercised IF reached (it must not).

No real network, SDK, or database is touched.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.backup_restore.backup.pipeline import (
    BackupPipeline,
    BackupScopeError,
    DestinationTarget,
    run_backup,
)
from app.modules.backup_restore.models import BackupDestination, BackupJob
from app.modules.backup_restore.storage.interface import (
    AsyncByteStream,
    ConnectionState,
    RemoteObject,
    StorageInterface,
    UploadResult,
)

# Scopes that must be rejected: absent (None), empty, and arbitrary non-members
# of {settings_only, organisations_only, both} (Req 6.1, 6.2).
INVALID_SCOPES = ["", "everything", "orgs", "ORG", "settings", "both ", None]


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class RaisingDumpRunner:
    """A ``dump_runner`` that fails the test if it is ever invoked.

    Scope validation must reject an invalid scope before the database dump
    stage, so this must never be called (Req 6.2 — no artifact created).
    """

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, db, *args, **kwargs):
        self.calls += 1
        raise AssertionError(
            "dump_runner was invoked for an invalid scope — the pipeline must "
            "reject the scope before producing any dump (Req 6.2)."
        )


class FakeStorage(StorageInterface):
    """Storage adapter that records every upload (and any other mutation).

    For an invalid scope nothing should be written anywhere, so ``uploads``
    must stay empty (Req 6.2 — no backup artefact or Backup_Manifest created).
    """

    def __init__(self) -> None:
        self.uploads: list[str] = []
        self.deletes: list[str] = []

    async def upload(
        self,
        key: str,
        source: AsyncByteStream,
        *,
        content_length: int,
        immutable_until=None,
    ) -> UploadResult:  # pragma: no cover - must never run for an invalid scope
        self.uploads.append(key)
        return UploadResult(key=key, size_bytes=content_length, checksum="")

    async def list(self, prefix: str) -> list[RemoteObject]:  # pragma: no cover
        return []

    async def download(self, key: str) -> AsyncByteStream:  # pragma: no cover
        async def _gen():
            yield b""

        return _gen()

    async def delete(self, key: str) -> None:  # pragma: no cover
        self.deletes.append(key)

    async def connection_status(self) -> ConnectionState:  # pragma: no cover
        return ConnectionState.connected


class FakeKeyService:
    """Minimal key service returning a fixed active BDK.

    Only used by the positive-control test so a VALID scope can proceed past
    the scope gate and key-resolution stage to the (stubbed) dump runner.
    """

    async def get_active_bdk(self) -> tuple[int, bytes]:
        return 1, bytes(range(32))


class FakeAsyncSession:
    """In-memory stand-in for the async DB session.

    Invalid-scope rejection only touches the ``flush()`` / ``refresh()`` seam
    via ``_mark_job_failed`` (when a job is supplied); ``execute`` / ``add`` are
    provided defensively and assert they are never reached on this path.
    """

    def __init__(self) -> None:
        self.flushes = 0
        self.refreshed: list[object] = []
        self.added: list[object] = []

    async def flush(self) -> None:
        self.flushes += 1

    async def refresh(self, obj: object) -> None:
        self.refreshed.append(obj)

    def add(self, obj: object) -> None:  # pragma: no cover - not on this path
        self.added.append(obj)

    async def execute(self, *args, **kwargs):  # pragma: no cover - not on this path
        raise AssertionError(
            "db.execute must not be called when the scope is rejected up front."
        )


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------


def _primary_target() -> tuple[DestinationTarget, FakeStorage]:
    """A real DestinationTarget (primary) wrapping a FakeStorage adapter."""
    storage = FakeStorage()
    dest = BackupDestination(
        id=uuid.uuid4(),
        provider_type="s3",
        display_name="primary",
        is_primary=True,
    )
    return DestinationTarget(destination=dest, storage=storage), storage


def _new_job() -> BackupJob:
    return BackupJob(id=uuid.uuid4(), status="queued", progress_pct=0)


# ---------------------------------------------------------------------------
# Invalid scope rejection (Req 6.1, 6.2, 6.5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", INVALID_SCOPES)
async def test_invalid_scope_rejected_with_no_artifact(scope):
    """An invalid Backup_Scope is rejected: no dump, no upload, job failed.

    Validates Requirements 6.1, 6.5 — the request is rejected before any backup
    artefact or manifest is created.
    """
    target, storage = _primary_target()
    dump_runner = RaisingDumpRunner()
    db = FakeAsyncSession()
    job = _new_job()

    pipeline = BackupPipeline(
        db,  # type: ignore[arg-type]
        destinations=[target],
        dump_runner=dump_runner,
    )

    with pytest.raises(BackupScopeError) as exc_info:
        await pipeline.run(scope=scope, job=job)

    # The error lists the accepted values (Req 6.2).
    message = str(exc_info.value)
    assert "settings_only" in message
    assert "organisations_only" in message
    assert "both" in message

    # No dump produced (Req 6.2 — no artefact created).
    assert dump_runner.calls == 0
    # No upload happened at the destination (no artefact/manifest written).
    assert storage.uploads == []
    assert storage.deletes == []
    # The job is marked failed with a reason recorded.
    assert job.status == "failed"
    assert job.error_message
    assert job.finished_at is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", INVALID_SCOPES)
async def test_invalid_scope_rejected_without_job(scope):
    """Rejection works (and touches no destination) even when no job is supplied.

    Validates Requirements 6.1, 6.5.
    """
    target, storage = _primary_target()
    dump_runner = RaisingDumpRunner()
    db = FakeAsyncSession()

    pipeline = BackupPipeline(
        db,  # type: ignore[arg-type]
        destinations=[target],
        dump_runner=dump_runner,
    )

    with pytest.raises(BackupScopeError):
        await pipeline.run(scope=scope)

    assert dump_runner.calls == 0
    assert storage.uploads == []
    # With no job, the job-failed seam is skipped entirely (no DB writes).
    assert db.flushes == 0
    assert db.refreshed == []


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", INVALID_SCOPES)
async def test_run_backup_wrapper_rejects_invalid_scope(scope):
    """The ``run_backup`` convenience wrapper rejects invalid scopes too.

    Validates Requirements 6.1, 6.5.
    """
    target, storage = _primary_target()
    dump_runner = RaisingDumpRunner()
    db = FakeAsyncSession()
    job = _new_job()

    with pytest.raises(BackupScopeError):
        await run_backup(
            db,  # type: ignore[arg-type]
            scope=scope,
            job=job,
            destinations=[target],
            dump_runner=dump_runner,
        )

    assert dump_runner.calls == 0
    assert storage.uploads == []
    assert job.status == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["settings_only", "organisations_only", "both"])
async def test_valid_scope_clears_gate_and_reaches_dump(scope):
    """Sanity/positive control: a VALID scope clears the gate and reaches the dump.

    A valid scope must NOT raise ``BackupScopeError``. With key-resolution stubbed,
    the pipeline proceeds to the dump runner, which we stub to raise a sentinel —
    confirming the scope gate was cleared (it is not over-broad). The dump runner
    being invoked here is exactly the call that must NOT happen for invalid scopes.
    """

    class _Sentinel(Exception):
        pass

    invoked = {"dump": False}

    async def _dump_runner(db, *args, **kwargs):
        invoked["dump"] = True
        raise _Sentinel()

    target, _storage = _primary_target()
    db = FakeAsyncSession()
    job = _new_job()
    pipeline = BackupPipeline(
        db,  # type: ignore[arg-type]
        destinations=[target],
        dump_runner=_dump_runner,
        key_service=FakeKeyService(),  # type: ignore[arg-type]
    )

    with pytest.raises(_Sentinel):
        await pipeline.run(scope=scope, job=job)

    # The valid scope cleared the gate and the dump stage was reached.
    assert invoked["dump"] is True
    assert job.status == "running"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
