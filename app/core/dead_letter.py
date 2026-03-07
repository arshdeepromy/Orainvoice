"""Dead letter queue service.

Provides methods to store failed background tasks, retry them with
exponential backoff (1 min → 5 min → 25 min), and alert on stale entries
that have been stuck for more than 1 hour.

**Validates: Requirement 10.4**
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Awaitable

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.models.dead_letter import DeadLetterTask

logger = logging.getLogger(__name__)

# Exponential backoff schedule in minutes: 1, 5, 25
_BACKOFF_MINUTES = [1, 5, 25]


def _next_retry_at(retry_count: int) -> datetime:
    """Calculate the next retry timestamp using exponential backoff."""
    idx = min(retry_count, len(_BACKOFF_MINUTES) - 1)
    delay = timedelta(minutes=_BACKOFF_MINUTES[idx])
    return datetime.now(timezone.utc) + delay


class DeadLetterService:
    """Manages the dead letter queue for failed background tasks."""

    def __init__(self, session: AsyncSession | None = None) -> None:
        self._session = session

    async def store_failed_task(
        self,
        task_name: str,
        task_args: dict[str, Any] | None = None,
        error_message: str | None = None,
        org_id: uuid.UUID | str | None = None,
        max_retries: int = 3,
    ) -> DeadLetterTask:
        """Insert a new failed task into the dead letter queue.

        The first retry is scheduled according to the backoff schedule.
        """
        entry = DeadLetterTask(
            task_name=task_name,
            task_args=task_args or {},
            error_message=error_message,
            org_id=uuid.UUID(str(org_id)) if org_id else None,
            max_retries=max_retries,
            retry_count=0,
            status="pending",
            next_retry_at=_next_retry_at(0),
        )

        if self._session is not None:
            self._session.add(entry)
            await self._session.flush()
            return entry

        async with async_session_factory() as session:
            async with session.begin():
                session.add(entry)
                await session.flush()
                # Expunge so the object is usable outside the session
                session.expunge(entry)
        return entry

    async def retry_task(
        self,
        task_id: uuid.UUID | str,
        executor: Callable[[str, dict], Awaitable[Any]] | None = None,
    ) -> DeadLetterTask | None:
        """Attempt to re-execute a dead-letter task.

        If *executor* is provided it is called with ``(task_name, task_args)``.
        On success the task status is set to ``completed``.
        On failure the retry count is incremented and the next retry is
        scheduled (or the task is marked ``failed`` if max retries exceeded).

        Returns the updated task or ``None`` if not found.
        """
        session = self._session
        owns_session = session is None
        if owns_session:
            session = async_session_factory()

        try:
            if owns_session:
                await session.begin()

            stmt = select(DeadLetterTask).where(
                DeadLetterTask.id == uuid.UUID(str(task_id))
            )
            result = await session.execute(stmt)
            task = result.scalar_one_or_none()
            if task is None:
                return None

            # Mark as retrying
            task.status = "retrying"
            task.retry_count += 1
            task.updated_at = datetime.now(timezone.utc)

            if executor is not None:
                try:
                    await executor(task.task_name, task.task_args)
                    task.status = "completed"
                    task.error_message = None
                except Exception as exc:
                    task.error_message = str(exc)
                    if task.retry_count >= task.max_retries:
                        task.status = "failed"
                        task.next_retry_at = None
                    else:
                        task.status = "pending"
                        task.next_retry_at = _next_retry_at(task.retry_count)
            else:
                # No executor — just bump the count and reschedule
                if task.retry_count >= task.max_retries:
                    task.status = "failed"
                    task.next_retry_at = None
                else:
                    task.status = "pending"
                    task.next_retry_at = _next_retry_at(task.retry_count)

            await session.flush()

            if owns_session:
                await session.commit()
                session.expunge(task)

            return task
        except Exception:
            if owns_session:
                await session.rollback()
            raise
        finally:
            if owns_session:
                await session.close()

    async def alert_if_stale(
        self,
        stale_threshold_minutes: int = 60,
    ) -> list[DeadLetterTask]:
        """Return tasks stuck in pending/retrying for longer than *stale_threshold_minutes*.

        Callers should use the returned list to send alerts to Global Admin.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_threshold_minutes)

        session = self._session
        owns_session = session is None
        if owns_session:
            session = async_session_factory()

        try:
            if owns_session:
                await session.begin()

            stmt = select(DeadLetterTask).where(
                DeadLetterTask.status.in_(["pending", "retrying"]),
                DeadLetterTask.created_at <= cutoff,
            )
            result = await session.execute(stmt)
            stale = list(result.scalars().all())

            if stale:
                logger.warning(
                    "%d stale dead-letter tasks found (older than %d min)",
                    len(stale),
                    stale_threshold_minutes,
                )

            if owns_session:
                await session.commit()
                for t in stale:
                    session.expunge(t)

            return stale
        except Exception:
            if owns_session:
                await session.rollback()
            raise
        finally:
            if owns_session:
                await session.close()
