"""Property-based test: job progress either advances or heartbeats, stalls fail.

# Feature: cloud-backup-restore, Property 20: Job progress either advances or heartbeats, and stalls fail

**Validates: Requirements 13.2, 13.5**

This property drives the real ``JobService``
(``app/modules/backup_restore/jobs.py``) over a generated timeline of emissions
and checks the progress/heartbeat state machine at every step.

We model a job that has been started (``queued -> running``) and then receives a
sequence of generated steps. Each step is one of:

* ``progress`` — a percentage update via ``emit_progress`` (clamped to be
  monotonic non-decreasing so the call is valid), or
* ``heartbeat`` — a liveness ping via ``emit_heartbeat``.

Each step carries a ``gap_seconds`` — the wall-clock time that elapses (via the
injected ``FakeClock``) *before* the step is processed. Because ``start`` and
every successful emission re-stamp the liveness window, the gap measured by the
service against the previous emission is exactly this step's ``gap_seconds``.

For any generated timeline the test asserts:

1. **Monotonic progress** — ``emit_progress`` never lets ``progress_pct`` move
   backwards; across all progress steps the percentage is non-decreasing
   (Req 13.2).
2. **Stalls fail** — the first time a gap exceeds ``STALL_TIMEOUT_SECONDS``
   (60 s), ``is_stalled`` is ``True`` and ``enforce_progress_timeout`` force-fails
   the job (status ``failed`` with the progress-timeout outcome). The job is then
   terminal, so the timeline stops (Req 13.5).
3. **No false force-fail** — while every gap stays ``<= 60 s`` the job is never
   stalled and ``enforce_progress_timeout`` leaves it ``running`` (Req 13.5).

Everything is in-memory: the controllable ``FakeClock`` and ``FakeAsyncSession``
doubles are reused from the lifecycle unit test, so no real time passes and no
database is involved.
"""

from __future__ import annotations

import asyncio
import uuid

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.backup_restore.jobs import (
    JobService,
    PROGRESS_TIMEOUT_SUMMARY,
    STALL_TIMEOUT_SECONDS,
)
from app.modules.backup_restore.models import BackupJob, RestoreJob

# Reuse the controllable clock + in-memory async session doubles (no mocks).
from tests.test_backup_job_lifecycle_unit import FakeAsyncSession, FakeClock

# ---------------------------------------------------------------------------
# Hypothesis settings (min 100 iterations) — pure in-memory, no I/O.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=200, deadline=None)


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------


def _build_job(kind: str):
    """Build a fresh queued job of the requested model type."""
    if kind == "restore":
        return RestoreJob(id=uuid.uuid4(), status="queued", progress_pct=0, mode="full")
    return BackupJob(id=uuid.uuid4(), status="queued", progress_pct=0)


@st.composite
def timelines(draw):
    """Generate (job_kind, [steps]).

    Each step is ``{"kind": "progress"|"heartbeat", "gap": int, "pct": int}``.

    ``gap`` is drawn across a range straddling the 60 s stall threshold (so both
    the "keeps alive" and the "stalls" branches are exercised), and ``pct`` is a
    target percentage in ``[0, 100]`` (the driver clamps it monotonically before
    emitting so the call is always valid).
    """
    job_kind = draw(st.sampled_from(["backup", "restore"]))
    steps = draw(
        st.lists(
            st.fixed_dictionaries(
                {
                    "kind": st.sampled_from(["progress", "heartbeat"]),
                    # 0..120s straddles the 60s threshold (incl. the boundary).
                    "gap": st.integers(min_value=0, max_value=120),
                    "pct": st.integers(min_value=0, max_value=100),
                }
            ),
            min_size=1,
            max_size=30,
        )
    )
    return {"job_kind": job_kind, "steps": steps}


# ---------------------------------------------------------------------------
# Property 20: Job progress either advances or heartbeats, and stalls fail
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(timeline=timelines())
def test_progress_advances_or_heartbeats_and_stalls_fail(timeline):
    """Drive the JobService over a timeline and check the state machine.

    **Validates: Requirements 13.2, 13.5**
    """
    job_kind = timeline["job_kind"]
    steps = timeline["steps"]

    async def run() -> None:
        job = _build_job(job_kind)
        clock = FakeClock()
        svc = JobService(FakeAsyncSession([job]), clock=clock)
        await svc.start(job)

        last_pct = job.progress_pct  # 0 right after start
        stalled_at_step = None

        for index, step in enumerate(steps):
            gap = step["gap"]

            # Advance wall-clock time before processing this step. The gap is
            # measured against the previous emission (re-stamped by start and by
            # every successful emit), so it equals this step's ``gap``.
            clock.advance(gap)

            if gap > STALL_TIMEOUT_SECONDS:
                # Invariant 2: a >60s gap stalls the job and force-fails it.
                assert svc.is_stalled(job) is True
                await svc.enforce_progress_timeout(job)
                assert job.status == "failed"
                assert job.finished_at is not None
                assert job.outcome_summary == PROGRESS_TIMEOUT_SUMMARY
                assert job.error_message == PROGRESS_TIMEOUT_SUMMARY
                stalled_at_step = index
                break

            # Invariant 3: a gap within the window never force-fails the job.
            assert svc.is_stalled(job) is False
            result = await svc.enforce_progress_timeout(job)
            assert result.status == "running"

            if step["kind"] == "progress":
                # Clamp to keep the emission valid (non-decreasing); the service
                # itself rejects any decrease, which is what enforces Invariant 1.
                target = max(last_pct, step["pct"])
                await svc.emit_progress(job, target)
                # Invariant 1: progress is monotonic non-decreasing.
                assert job.progress_pct >= last_pct
                assert job.progress_pct == target
                last_pct = job.progress_pct
            else:
                before = job.progress_pct
                await svc.emit_heartbeat(job)
                # A heartbeat keeps the job alive without changing the percentage.
                assert job.progress_pct == before
                assert job.last_heartbeat_at == clock()

        if stalled_at_step is None:
            # Every gap stayed within the window: the job is never force-failed.
            assert job.status == "running"
        else:
            # A stall occurred exactly once and ended the timeline.
            assert any(s["gap"] > STALL_TIMEOUT_SECONDS for s in steps)

    asyncio.run(run())
