"""Unit tests for the Backup_Job / Restore_Job model (Task 13.1, Req 13).

Covers ``app.modules.backup_restore.jobs.JobService``:
  - lifecycle transitions queued -> running -> completed | failed | cancelled
    and rejection of invalid transitions (Req 13.1);
  - progress-or-heartbeat emission stamping ``last_progress_at`` /
    ``last_heartbeat_at`` (Req 13.2);
  - status query (status, progress %, elapsed seconds, time-since-last-update)
    and unknown-id -> not-found with no job created (Req 13.3, 13.6);
  - >60s progress-timeout force-fail with heartbeats keeping a job alive
    (Req 13.5);
  - terminal recording of finished_at + outcome/error (Req 13.4);
  - generic operation over BOTH BackupJob and RestoreJob.

Per the project test rule, the async DB session is a lightweight in-memory
stand-in (no mock framework) and the wall clock is injected so the 5s / 60s
thresholds are exercised deterministically.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.backup_restore.jobs import (
    InvalidJobTransition,
    JobNotFoundError,
    JobService,
    PROGRESS_TIMEOUT_SUMMARY,
    STALL_TIMEOUT_SECONDS,
)
from app.modules.backup_restore.models import BackupJob, RestoreJob


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeClock:
    """Controllable monotone clock returning tz-aware UTC datetimes."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)


class _Result:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> "_Result":
        return self

    def first(self) -> object | None:
        return self._rows[0] if self._rows else None


class FakeAsyncSession:
    """In-memory async session: stores jobs and answers ``select(...).where(id==)``."""

    def __init__(self, jobs: list[object] | None = None) -> None:
        self.store: dict[uuid.UUID, object] = {}
        for job in jobs or []:
            self.store[job.id] = job
        self.flushes = 0
        self.refreshed: list[object] = []

    def add(self, obj: object) -> None:
        self.store[obj.id] = obj

    async def flush(self) -> None:
        self.flushes += 1

    async def refresh(self, obj: object) -> None:
        self.refreshed.append(obj)

    async def execute(self, statement):
        # Extract the bound id from the WHERE clause of `select(model).where(model.id == x)`.
        wanted = None
        try:
            crit = list(statement._where_criteria)[0]
            wanted = crit.right.value
        except Exception:  # pragma: no cover - defensive
            wanted = None
        rows = [self.store[wanted]] if wanted in self.store else []
        return _Result(rows)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _backup_job() -> BackupJob:
    return BackupJob(id=uuid.uuid4(), status="queued", progress_pct=0)


def _restore_job() -> RestoreJob:
    return RestoreJob(id=uuid.uuid4(), status="queued", progress_pct=0, mode="full")


# Both models exercise the identical lifecycle columns.
JOB_BUILDERS = [pytest.param(_backup_job, id="backup_job"),
                pytest.param(_restore_job, id="restore_job")]


# ---------------------------------------------------------------------------
# Lifecycle transitions (Req 13.1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("build", JOB_BUILDERS)
async def test_start_moves_queued_to_running_and_stamps_times(build):
    job = build()
    clock = FakeClock()
    svc = JobService(FakeAsyncSession([job]), clock=clock)

    await svc.start(job)

    assert job.status == "running"
    assert job.started_at == clock()
    assert job.last_progress_at == clock()
    assert job.last_heartbeat_at == clock()


@pytest.mark.asyncio
@pytest.mark.parametrize("build", JOB_BUILDERS)
async def test_complete_records_terminal_state_and_100pct(build):
    job = build()
    clock = FakeClock()
    svc = JobService(FakeAsyncSession([job]), clock=clock)
    await svc.start(job)
    clock.advance(30)

    await svc.complete(job, outcome_summary="all good")

    assert job.status == "completed"
    assert job.progress_pct == 100
    assert job.finished_at == clock()
    assert job.outcome_summary == "all good"


@pytest.mark.asyncio
@pytest.mark.parametrize("build", JOB_BUILDERS)
async def test_fail_records_error_and_outcome(build):
    job = build()
    svc = JobService(FakeAsyncSession([job]))
    await svc.start(job)

    await svc.fail(job, error_message="dump failed", outcome_summary="backup failed")

    assert job.status == "failed"
    assert job.finished_at is not None
    assert job.error_message == "dump failed"
    assert job.outcome_summary == "backup failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("build", JOB_BUILDERS)
async def test_cancel_from_queued_and_from_running(build):
    queued = build()
    svc = JobService(FakeAsyncSession([queued]))
    await svc.cancel(queued)
    assert queued.status == "cancelled"
    assert queued.finished_at is not None

    running = build()
    svc2 = JobService(FakeAsyncSession([running]))
    await svc2.start(running)
    await svc2.cancel(running)
    assert running.status == "cancelled"


@pytest.mark.asyncio
@pytest.mark.parametrize("build", JOB_BUILDERS)
async def test_invalid_transition_from_terminal_is_rejected(build):
    job = build()
    svc = JobService(FakeAsyncSession([job]))
    await svc.start(job)
    await svc.complete(job)

    with pytest.raises(InvalidJobTransition):
        await svc.complete(job)
    with pytest.raises(InvalidJobTransition):
        await svc.fail(job, "x")
    with pytest.raises(InvalidJobTransition):
        await svc.cancel(job)


@pytest.mark.asyncio
async def test_cannot_complete_a_queued_job():
    job = _backup_job()
    svc = JobService(FakeAsyncSession([job]))
    with pytest.raises(InvalidJobTransition):
        await svc.complete(job)


# ---------------------------------------------------------------------------
# Progress-or-heartbeat emission (Req 13.2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("build", JOB_BUILDERS)
async def test_emit_progress_advances_pct_and_stamps_progress_time(build):
    job = build()
    clock = FakeClock()
    svc = JobService(FakeAsyncSession([job]), clock=clock)
    await svc.start(job)
    clock.advance(10)

    await svc.emit_progress(job, 42)

    assert job.progress_pct == 42
    assert job.last_progress_at == clock()


@pytest.mark.asyncio
async def test_emit_progress_rejects_decrease_and_out_of_range():
    job = _backup_job()
    svc = JobService(FakeAsyncSession([job]))
    await svc.start(job)
    await svc.emit_progress(job, 50)

    with pytest.raises(ValueError):
        await svc.emit_progress(job, 49)  # backwards
    with pytest.raises(ValueError):
        await svc.emit_progress(job, 101)  # > 100
    with pytest.raises(ValueError):
        await svc.emit_progress(job, -1)  # < 0


@pytest.mark.asyncio
async def test_emit_requires_running_state():
    job = _backup_job()  # still queued
    svc = JobService(FakeAsyncSession([job]))
    with pytest.raises(InvalidJobTransition):
        await svc.emit_progress(job, 10)
    with pytest.raises(InvalidJobTransition):
        await svc.emit_heartbeat(job)


@pytest.mark.asyncio
@pytest.mark.parametrize("build", JOB_BUILDERS)
async def test_emit_heartbeat_stamps_heartbeat_time_without_pct_change(build):
    job = build()
    clock = FakeClock()
    svc = JobService(FakeAsyncSession([job]), clock=clock)
    await svc.start(job)
    await svc.emit_progress(job, 20)
    clock.advance(4)

    await svc.emit_heartbeat(job)

    assert job.progress_pct == 20  # unchanged
    assert job.last_heartbeat_at == clock()


# ---------------------------------------------------------------------------
# Status query (Req 13.3, 13.6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_status_reports_status_pct_elapsed_and_since_last():
    job = _backup_job()
    clock = FakeClock()
    session = FakeAsyncSession([job])
    svc = JobService(session, clock=clock)
    await svc.start(job)
    clock.advance(10)
    await svc.emit_progress(job, 25)
    clock.advance(3)  # 3s since the last progress emission

    status = await svc.get_status(job.id, BackupJob)

    assert status.status == "running"
    assert status.progress_pct == 25
    assert status.elapsed_seconds == pytest.approx(13.0)
    assert status.seconds_since_last_update == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_unknown_job_id_is_not_found_and_creates_no_job():
    session = FakeAsyncSession([])
    svc = JobService(session)
    missing = uuid.uuid4()

    with pytest.raises(JobNotFoundError):
        await svc.get_status(missing, RestoreJob)

    assert session.store == {}  # no job created (Req 13.6)


@pytest.mark.asyncio
async def test_terminal_status_freezes_elapsed_at_finish():
    job = _backup_job()
    clock = FakeClock()
    svc = JobService(FakeAsyncSession([job]), clock=clock)
    await svc.start(job)
    clock.advance(20)
    await svc.complete(job)
    clock.advance(100)  # time passes after completion

    status = svc.status_of(job)
    assert status.status == "completed"
    assert status.elapsed_seconds == pytest.approx(20.0)  # frozen at finish


# ---------------------------------------------------------------------------
# Stall detection / progress-timeout force-fail (Req 13.5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("build", JOB_BUILDERS)
async def test_running_job_with_no_emission_over_60s_is_force_failed(build):
    job = build()
    clock = FakeClock()
    svc = JobService(FakeAsyncSession([job]), clock=clock)
    await svc.start(job)
    clock.advance(STALL_TIMEOUT_SECONDS + 1)

    assert svc.is_stalled(job) is True
    await svc.enforce_progress_timeout(job)

    assert job.status == "failed"
    assert job.finished_at is not None
    assert job.outcome_summary == PROGRESS_TIMEOUT_SUMMARY
    assert job.error_message == PROGRESS_TIMEOUT_SUMMARY


@pytest.mark.asyncio
async def test_heartbeating_job_is_never_force_failed():
    job = _restore_job()
    clock = FakeClock()
    svc = JobService(FakeAsyncSession([job]), clock=clock)
    await svc.start(job)

    # Emit a heartbeat every 50s for 10 minutes — never a 60s gap.
    for _ in range(12):
        clock.advance(50)
        assert svc.is_stalled(job) is False
        await svc.emit_heartbeat(job)

    result = await svc.enforce_progress_timeout(job)
    assert result.status == "running"  # still alive


@pytest.mark.asyncio
async def test_exactly_60s_is_not_a_timeout_boundary():
    job = _backup_job()
    clock = FakeClock()
    svc = JobService(FakeAsyncSession([job]), clock=clock)
    await svc.start(job)
    clock.advance(STALL_TIMEOUT_SECONDS)  # exactly 60s -> not > 60

    assert svc.is_stalled(job) is False
    await svc.enforce_progress_timeout(job)
    assert job.status == "running"


@pytest.mark.asyncio
async def test_terminal_job_is_not_stalled():
    job = _backup_job()
    clock = FakeClock()
    svc = JobService(FakeAsyncSession([job]), clock=clock)
    await svc.start(job)
    await svc.complete(job)
    clock.advance(10_000)

    assert svc.is_stalled(job) is False
