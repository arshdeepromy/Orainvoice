"""Backup_Job / Restore_Job lifecycle, progress, and heartbeat store (Req 13).

``JobService`` is generic over the two lifecycle models — ``BackupJob`` and
``RestoreJob`` — which share the same set of lifecycle columns (``status``,
``progress_pct``, ``last_progress_at``, ``last_heartbeat_at``, ``started_at``,
``finished_at``, ``outcome_summary``, ``error_message``). It provides:

* lifecycle transitions ``queued → running → (completed | failed | cancelled)``
  (Req 13.1);
* the progress-or-heartbeat emission contract — ``emit_progress(pct)`` stamps
  ``last_progress_at`` on a percentage advance, ``emit_heartbeat()`` stamps
  ``last_heartbeat_at`` — where the owning pipeline is expected to emit one or
  the other at intervals no greater than 5 s (Req 13.2);
* a status query returning status, progress %, elapsed running seconds, and the
  time since the most recent progress update or heartbeat (Req 13.3); an unknown
  job id resolves to not-found with no job created (Req 13.6);
* stall detection — a ``running`` job that has emitted neither a percentage
  increase nor a heartbeat for more than 60 consecutive seconds is force-failed
  with a progress-timeout outcome, while a phase that keeps heart-beating is
  never force-failed (Req 13.5);
* terminal recording of final status, UTC completion timestamp, and an outcome
  summary / error message (Req 13.4).

The job row in the database (not in-memory state) is the source of truth, so any
worker can serve a status poll. Per the ``get_db_session`` ``session.begin()``
auto-commit pattern, this service uses ``flush()`` (never ``commit()``) and
``refresh()`` before returning ORM objects.

The wall clock is injected (``clock``) so the 5 s / 60 s thresholds are testable
without real time passing.

Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Union

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.backup_restore.models import BackupJob, RestoreJob

# A job is either a Backup_Job or a Restore_Job; they share the lifecycle cols.
AnyJob = Union[BackupJob, RestoreJob]

# A clock is any zero-arg callable returning a timezone-aware UTC datetime.
Clock = Callable[[], datetime]

# ---------------------------------------------------------------------------
# Lifecycle constants (Req 13.1, 13.2, 13.5)
# ---------------------------------------------------------------------------
QUEUED = "queued"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"

#: Terminal states — a job in any of these can no longer transition.
TERMINAL_STATUSES = frozenset({COMPLETED, FAILED, CANCELLED})

#: Allowed lifecycle transitions (source -> set of permitted targets).
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    QUEUED: frozenset({RUNNING, CANCELLED, FAILED}),
    RUNNING: frozenset({COMPLETED, FAILED, CANCELLED}),
    COMPLETED: frozenset(),
    FAILED: frozenset(),
    CANCELLED: frozenset(),
}

#: Expected upper bound between progress-or-heartbeat emissions (Req 13.2).
PROGRESS_INTERVAL_SECONDS = 5

#: A running job with no progress AND no heartbeat for longer than this is
#: force-failed with a progress-timeout outcome (Req 13.5).
STALL_TIMEOUT_SECONDS = 60

#: Outcome summary recorded when the progress-timeout force-fail fires.
PROGRESS_TIMEOUT_SUMMARY = "Progress timeout: no progress or heartbeat for over 60s"


class JobNotFoundError(Exception):
    """Raised when a job id does not correspond to an existing job (Req 13.6)."""

    def __init__(self, job_id: uuid.UUID | str) -> None:
        self.job_id = job_id
        super().__init__(f"Job not found: {job_id}")


class InvalidJobTransition(Exception):
    """Raised when a requested lifecycle transition is not permitted (Req 13.1)."""

    def __init__(self, current: str, target: str) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Invalid job transition: {current} -> {target}")


@dataclass(frozen=True)
class JobStatus:
    """Point-in-time view of a job for the status endpoint (Req 13.3).

    ``elapsed_seconds`` is the running time since ``started_at`` (0 while still
    queued; frozen at the terminal duration once finished). ``seconds_since_last_update``
    is the time since the most recent progress update or liveness heartbeat
    (measured to ``finished_at`` for a terminal job, otherwise to "now").
    """

    id: uuid.UUID
    status: str
    progress_pct: int
    elapsed_seconds: float
    seconds_since_last_update: float


def _default_clock() -> datetime:
    """Default wall clock: timezone-aware UTC now."""
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """Coerce a datetime to timezone-aware UTC.

    DB columns are ``DateTime(timezone=True)`` so values are normally tz-aware,
    but a naive value (e.g. an in-memory object not yet round-tripped) is
    treated as UTC defensively so subtraction never raises.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class JobService:
    """Lifecycle / progress / heartbeat operations over a Backup_Job or Restore_Job.

    Works uniformly on either model because both expose the same lifecycle
    columns. The wall clock is injected so the 5 s / 60 s thresholds are testable.
    """

    def __init__(self, db: AsyncSession, clock: Clock | None = None) -> None:
        self._db = db
        self._clock = clock or _default_clock

    # ------------------------------------------------------------------
    # Lookup (Req 13.6)
    # ------------------------------------------------------------------
    async def get_job(
        self,
        job_id: uuid.UUID | str,
        model: type[AnyJob],
    ) -> AnyJob:
        """Load a job by id, raising :class:`JobNotFoundError` if absent.

        Never creates a job as a side effect of the lookup (Req 13.6).
        """
        result = await self._db.execute(select(model).where(model.id == job_id))
        job = result.scalars().first()
        if job is None:
            raise JobNotFoundError(job_id)
        return job

    # ------------------------------------------------------------------
    # Lifecycle transitions (Req 13.1)
    # ------------------------------------------------------------------
    async def start(self, job: AnyJob) -> AnyJob:
        """Transition ``queued → running``.

        Stamps ``started_at`` and seeds both liveness timestamps so the
        progress-timeout window (Req 13.5) is measured from the start.
        """
        self._assert_transition(job.status, RUNNING)
        now = self._now()
        job.status = RUNNING
        job.started_at = now
        job.last_progress_at = now
        job.last_heartbeat_at = now
        return await self._persist(job)

    async def complete(self, job: AnyJob, outcome_summary: str = "Completed successfully") -> AnyJob:
        """Transition ``running → completed``, recording terminal state (Req 13.4).

        Progress is reported as 100 % on successful completion.
        """
        self._assert_transition(job.status, COMPLETED)
        job.status = COMPLETED
        job.progress_pct = 100
        job.finished_at = self._now()
        job.outcome_summary = outcome_summary
        return await self._persist(job)

    async def fail(
        self,
        job: AnyJob,
        error_message: str,
        outcome_summary: str = "Failed",
    ) -> AnyJob:
        """Transition to ``failed``, recording terminal state (Req 13.4)."""
        self._assert_transition(job.status, FAILED)
        job.status = FAILED
        job.finished_at = self._now()
        job.outcome_summary = outcome_summary
        job.error_message = error_message
        return await self._persist(job)

    async def cancel(self, job: AnyJob, outcome_summary: str = "Cancelled") -> AnyJob:
        """Transition to ``cancelled``, recording terminal state (Req 13.4)."""
        self._assert_transition(job.status, CANCELLED)
        job.status = CANCELLED
        job.finished_at = self._now()
        job.outcome_summary = outcome_summary
        return await self._persist(job)

    # ------------------------------------------------------------------
    # Progress-or-heartbeat emission (Req 13.2)
    # ------------------------------------------------------------------
    async def emit_progress(self, job: AnyJob, pct: int) -> AnyJob:
        """Record a percentage-advancing progress update (Req 13.2).

        ``pct`` is clamped to ``[0, 100]`` and must not move backwards. The
        emission stamps ``last_progress_at``, which (together with heartbeats)
        resets the progress-timeout window (Req 13.5).
        """
        self._require_running(job)
        if not 0 <= pct <= 100:
            raise ValueError(f"progress percentage out of range [0, 100]: {pct}")
        if pct < job.progress_pct:
            raise ValueError(
                f"progress cannot decrease ({job.progress_pct} -> {pct})",
            )
        job.progress_pct = pct
        job.last_progress_at = self._now()
        return await self._persist(job)

    async def emit_heartbeat(self, job: AnyJob) -> AnyJob:
        """Record a liveness heartbeat without a percentage change (Req 13.2).

        Used during a long monotonic phase (multi-GB blob download, long
        ``pg_restore``) so the job is not force-failed (Req 13.5).
        """
        self._require_running(job)
        job.last_heartbeat_at = self._now()
        return await self._persist(job)

    # ------------------------------------------------------------------
    # Status query (Req 13.3)
    # ------------------------------------------------------------------
    async def get_status(
        self,
        job_id: uuid.UUID | str,
        model: type[AnyJob],
    ) -> JobStatus:
        """Return the live status view for a job, or raise if unknown (Req 13.3, 13.6)."""
        job = await self.get_job(job_id, model)
        return self.status_of(job)

    def status_of(self, job: AnyJob) -> JobStatus:
        """Build a :class:`JobStatus` snapshot from an already-loaded job (Req 13.3)."""
        is_terminal = job.status in TERMINAL_STATUSES
        # Reference "now": frozen at completion time for terminal jobs.
        ref = self._now()
        if is_terminal and job.finished_at is not None:
            ref = _as_utc(job.finished_at)

        elapsed = 0.0
        if job.started_at is not None:
            elapsed = max(0.0, (ref - _as_utc(job.started_at)).total_seconds())

        last_emit = self._last_emit(job)
        if last_emit is None:
            seconds_since = elapsed
        else:
            seconds_since = max(0.0, (ref - last_emit).total_seconds())

        return JobStatus(
            id=job.id,
            status=job.status,
            progress_pct=job.progress_pct,
            elapsed_seconds=elapsed,
            seconds_since_last_update=seconds_since,
        )

    # ------------------------------------------------------------------
    # Stall detection / progress-timeout force-fail (Req 13.5)
    # ------------------------------------------------------------------
    def is_stalled(self, job: AnyJob) -> bool:
        """Return ``True`` if a running job has emitted neither progress nor a
        heartbeat for more than ``STALL_TIMEOUT_SECONDS`` (Req 13.5).

        A non-running job is never considered stalled. A job that keeps
        heart-beating resets ``last_heartbeat_at`` and so is never stalled.
        """
        if job.status != RUNNING:
            return False
        last_emit = self._last_emit(job) or (
            _as_utc(job.started_at) if job.started_at is not None else None
        )
        if last_emit is None:
            return False
        return (self._now() - last_emit).total_seconds() > STALL_TIMEOUT_SECONDS

    async def enforce_progress_timeout(self, job: AnyJob) -> AnyJob:
        """Force-fail a stalled running job with a progress-timeout outcome (Req 13.5).

        Returns the job unchanged when it is not stalled, so callers can invoke
        this on every status poll / sweep without special-casing.
        """
        if not self.is_stalled(job):
            return job
        job.status = FAILED
        job.finished_at = self._now()
        job.outcome_summary = PROGRESS_TIMEOUT_SUMMARY
        job.error_message = PROGRESS_TIMEOUT_SUMMARY
        return await self._persist(job)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _now(self) -> datetime:
        return _as_utc(self._clock())

    @staticmethod
    def _last_emit(job: AnyJob) -> datetime | None:
        """Most recent of the progress / heartbeat timestamps (Req 13.3, 13.5)."""
        stamps = [
            _as_utc(ts)
            for ts in (job.last_progress_at, job.last_heartbeat_at)
            if ts is not None
        ]
        return max(stamps) if stamps else None

    @staticmethod
    def _assert_transition(current: str, target: str) -> None:
        if target not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
            raise InvalidJobTransition(current, target)

    @staticmethod
    def _require_running(job: AnyJob) -> None:
        if job.status != RUNNING:
            raise InvalidJobTransition(job.status, RUNNING)

    async def _persist(self, job: AnyJob) -> AnyJob:
        """Flush + refresh (never commit) per the project session pattern."""
        await self._db.flush()
        await self._db.refresh(job)
        return job
