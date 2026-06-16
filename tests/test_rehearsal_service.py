"""Unit tests for the scheduled restore rehearsal service.

# Feature: cloud-backup-restore, Task 14.1 — restore/rehearsal.py

Covers the core run_rehearsal behaviour (Req 25.4/25.5, Req 26): restore a
recent backup into an isolated scratch environment, run the four validation
checks, record pass/fail + per-check outcomes + measured duration vs the
configured RTO, and tear the scratch environment down regardless of outcome.

Everything is in-memory: the artifact reader, scratch environment + provider,
wall clock, notifications, and the DB session are fakes.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Optional

from app.modules.backup_restore.backup.cas import content_hash
from app.modules.backup_restore.backup.manifest import (
    FileIndex,
    FileIndexEntry,
    PerOrgEntityCount,
    PerOrgIndex,
    PerOrgIndexEntry,
    build_manifest,
)
from app.modules.backup_restore.restore.per_org_restore import (
    ArtifactReader,
    FileBlobUnavailableError,
)
from app.modules.backup_restore.restore.rehearsal import (
    CHECK_FILE_CONSISTENCY,
    CHECK_SCHEMA,
    CHECK_SMOKE,
    EVENT_REHEARSAL_FAILED,
    EVENT_REHEARSAL_RTO_UNMET,
    EVENT_REHEARSAL_TEARDOWN_FAILED,
    RESULT_FAILED,
    RESULT_PASSED,
    TEARDOWN_FAILED,
    TEARDOWN_SUCCEEDED,
    NoBackupAvailableError,
    RehearsalService,
    ScratchEnvironment,
    ScratchEnvironmentProvider,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

TARGET_REVISION = "0194"
BLOB_DATA = b"file-blob-contents"
BLOB_HASH = content_hash(BLOB_DATA)


def _build_manifest():
    file_index = FileIndex(
        entries=[
            FileIndexEntry(
                path="attachments/org-1/a.pdf",
                org_id="org-1",
                content_hash=BLOB_HASH,
                byte_size=len(BLOB_DATA),
            )
        ]
    )
    per_org_index = PerOrgIndex(
        entries=[
            PerOrgIndexEntry(
                org_id="org-1",
                entities=[
                    PerOrgEntityCount(entity_type="customers", record_count=3),
                    PerOrgEntityCount(entity_type="invoices", record_count=2),
                ],
            )
        ]
    )
    return build_manifest(
        backup_id=str(uuid.uuid4()),
        created_at=datetime.now(timezone.utc),
        scope="both",
        checksum="deadbeef",
        encrypted_artifact_size=1234,
        file_index=file_index,
        per_org_index=per_org_index,
        schema_version=TARGET_REVISION,
    )


class FakeReader(ArtifactReader):
    def __init__(self, manifest, *, blobs: Optional[dict[str, bytes]] = None, dump_fail: bool = False):
        self._manifest = manifest
        self._blobs = blobs if blobs is not None else {BLOB_HASH: BLOB_DATA}
        self._dump_fail = dump_fail

    async def read_manifest(self):
        return self._manifest

    async def read_encrypted_dump(self) -> bytes:
        return b"encrypted"

    async def read_dump_plaintext(self) -> bytes:
        if self._dump_fail:
            raise RuntimeError("dump unreadable")
        return b"plaintext-dump"

    async def read_per_org_export(self, location: str) -> bytes:  # pragma: no cover
        raise NotImplementedError

    async def read_blob(self, content_hash_: str) -> bytes:
        if content_hash_ not in self._blobs:
            raise FileBlobUnavailableError("missing", file_reference=content_hash_)
        return self._blobs[content_hash_]


class FakeScratchEnvironment(ScratchEnvironment):
    def __init__(
        self,
        *,
        tables: Optional[dict[str, int]] = None,
        schema_version_value: Optional[str] = TARGET_REVISION,
        smoke_ok: bool = True,
        restore_fail: bool = False,
        teardown_fail: bool = False,
    ):
        self._tables = tables if tables is not None else {"customers": 5, "invoices": 4}
        self._schema_version = schema_version_value
        self._smoke_ok = smoke_ok
        self._restore_fail = restore_fail
        self._teardown_fail = teardown_fail
        self.restored = False
        self.torn_down = False
        self._id = f"scratch_{uuid.uuid4().hex[:8]}"

    @property
    def env_id(self) -> str:
        return self._id

    async def restore_dump(self, dump_plaintext: bytes) -> None:
        if self._restore_fail:
            raise RuntimeError("pg_restore failed")
        self.restored = True

    async def list_tables(self) -> set[str]:
        return set(self._tables)

    async def row_count(self, table: str) -> int:
        return self._tables[table]

    async def schema_version(self) -> Optional[str]:
        return self._schema_version

    async def smoke_check(self) -> tuple[bool, str]:
        return (self._smoke_ok, "ok" if self._smoke_ok else "smoke failed")

    async def teardown(self) -> None:
        if self._teardown_fail:
            raise RuntimeError("could not drop scratch db")
        self.torn_down = True


class FakeProvider(ScratchEnvironmentProvider):
    def __init__(self, env: FakeScratchEnvironment):
        self._env = env

    async def provision(self) -> ScratchEnvironment:
        return self._env


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeSession:
    """Minimal async session: serves BackupConfig, records the persisted row."""

    def __init__(self, *, rto_seconds: Optional[int] = 14400):
        self._config = SimpleNamespace(rto_seconds=rto_seconds) if rto_seconds is not None else None
        self.added: list[Any] = []
        self.flushes = 0

    async def execute(self, *_args, **_kwargs):
        # Only used for the BackupConfig lookup in these tests.
        return FakeResult(self._config)

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)

    async def flush(self):
        self.flushes += 1
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def refresh(self, obj, *args, **kwargs):
        return None


class RecordingNotifier:
    def __init__(self):
        self.events: list[dict] = []

    async def __call__(self, **kwargs):
        self.events.append(kwargs)


def _clock(times: list[datetime]):
    it = iter(times)
    last = {"v": times[-1]}

    def _now():
        try:
            last["v"] = next(it)
        except StopIteration:
            pass
        return last["v"]

    return _now


def _backup():
    return SimpleNamespace(id=uuid.uuid4(), scope="both")


def _service(session, env, reader, notifier, *, times=None, backup=None):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    times = times or [base, base + timedelta(seconds=120)]
    return RehearsalService(
        session,
        scratch_provider=FakeProvider(env),
        reader_factory=lambda b: reader,
        clock=_clock(times),
        notify_hook=notifier,
        recent_backup_selector=(lambda: _async(backup)) if backup is not None else None,
    )


async def _async(value):
    return value


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_passing_rehearsal_records_passed_and_tears_down():
    async def run():
        session = FakeSession(rto_seconds=14400)
        env = FakeScratchEnvironment()
        reader = FakeReader(_build_manifest())
        notifier = RecordingNotifier()
        svc = _service(session, env, reader, notifier)

        result = await svc.run_rehearsal(_backup())

        assert result.result == RESULT_PASSED
        assert result.failed_step is None
        assert all(c.passed for c in result.checks())
        assert env.restored is True
        assert env.torn_down is True
        assert result.teardown_status == TEARDOWN_SUCCEEDED
        assert result.measured_duration_seconds == 120
        assert result.rto_met is True
        # persisted + no notifications on a clean pass
        assert len(session.added) == 1
        assert session.added[0].result == RESULT_PASSED
        assert notifier.events == []

    asyncio.run(run())


def test_failed_smoke_marks_failed_and_notifies():
    async def run():
        session = FakeSession()
        env = FakeScratchEnvironment(smoke_ok=False)
        reader = FakeReader(_build_manifest())
        notifier = RecordingNotifier()
        svc = _service(session, env, reader, notifier)

        result = await svc.run_rehearsal(_backup())

        assert result.result == RESULT_FAILED
        assert result.failed_step == CHECK_SMOKE
        assert env.torn_down is True
        events = [e["event"] for e in notifier.events]
        assert EVENT_REHEARSAL_FAILED in events

    asyncio.run(run())


def test_restore_failure_marks_first_check_failed_and_tears_down():
    async def run():
        session = FakeSession()
        env = FakeScratchEnvironment(restore_fail=True)
        reader = FakeReader(_build_manifest())
        notifier = RecordingNotifier()
        svc = _service(session, env, reader, notifier)

        result = await svc.run_rehearsal(_backup())

        assert result.result == RESULT_FAILED
        # restore failed before any check ran ⇒ first check (schema) attributed
        assert result.failed_step == CHECK_SCHEMA
        assert result.schema_check.passed is False
        assert env.restored is False
        assert env.torn_down is True  # teardown still runs (Req 26.5)

    asyncio.run(run())


def test_file_consistency_fails_on_missing_blob():
    async def run():
        session = FakeSession()
        env = FakeScratchEnvironment()
        reader = FakeReader(_build_manifest(), blobs={})  # no blobs available
        notifier = RecordingNotifier()
        svc = _service(session, env, reader, notifier)

        result = await svc.run_rehearsal(_backup())

        assert result.result == RESULT_FAILED
        assert result.failed_step == CHECK_FILE_CONSISTENCY
        assert result.file_check.passed is False

    asyncio.run(run())


def test_rto_unmet_dispatches_notification():
    async def run():
        session = FakeSession(rto_seconds=60)
        env = FakeScratchEnvironment()
        reader = FakeReader(_build_manifest())
        notifier = RecordingNotifier()
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        svc = _service(
            session, env, reader, notifier,
            times=[base, base + timedelta(seconds=300)],
        )

        result = await svc.run_rehearsal(_backup())

        assert result.result == RESULT_PASSED  # checks passed
        assert result.measured_duration_seconds == 300
        assert result.rto_met is False
        events = [e["event"] for e in notifier.events]
        assert EVENT_REHEARSAL_RTO_UNMET in events

    asyncio.run(run())


def test_teardown_failure_recorded_and_notified():
    async def run():
        session = FakeSession()
        env = FakeScratchEnvironment(teardown_fail=True)
        reader = FakeReader(_build_manifest())
        notifier = RecordingNotifier()
        svc = _service(session, env, reader, notifier)

        result = await svc.run_rehearsal(_backup())

        assert result.teardown_status == TEARDOWN_FAILED
        assert result.scratch_env_id == env.env_id
        events = [e["event"] for e in notifier.events]
        assert EVENT_REHEARSAL_TEARDOWN_FAILED in events

    asyncio.run(run())


def test_schema_mismatch_fails():
    async def run():
        session = FakeSession()
        env = FakeScratchEnvironment(schema_version_value="0190")
        reader = FakeReader(_build_manifest())  # backup recorded 0194
        notifier = RecordingNotifier()
        svc = _service(session, env, reader, notifier)

        result = await svc.run_rehearsal(_backup())

        assert result.result == RESULT_FAILED
        assert result.failed_step == CHECK_SCHEMA

    asyncio.run(run())


def test_no_backup_available_raises():
    async def run():
        session = FakeSession()
        env = FakeScratchEnvironment()
        reader = FakeReader(_build_manifest())
        notifier = RecordingNotifier()
        # selector returns None ⇒ nothing to rehearse
        svc = RehearsalService(
            session,
            scratch_provider=FakeProvider(env),
            reader_factory=lambda b: reader,
            notify_hook=notifier,
            recent_backup_selector=lambda: _async(None),
        )
        raised = False
        try:
            await svc.run_rehearsal()
        except NoBackupAvailableError:
            raised = True
        assert raised is True

    asyncio.run(run())
