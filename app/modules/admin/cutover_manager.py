"""Cutover Manager for live database migration.

Manages the atomic cutover from source to target database, including
request pausing via Redis lock, engine swapping, connectivity verification,
and rollback support.

Requirements: 8.3, 8.4, 8.5, 8.6, 8.7, 9.2, 9.3, 9.4
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.redis import redis_pool

logger = logging.getLogger(__name__)

# Redis key used to pause incoming requests during cutover/rollback.
_MIGRATION_LOCK_KEY = "migration:lock"
_MIGRATION_LOCK_TTL = 30  # seconds


class CutoverManager:
    """Manages the atomic cutover from source to target database."""

    async def _pause_requests(self) -> None:
        """Set Redis lock key ``migration:lock`` with 30s TTL.

        Middleware checks this key and returns 503 while it is set,
        effectively pausing all incoming requests during the cutover window.
        """
        await redis_pool.set(_MIGRATION_LOCK_KEY, "1", ex=_MIGRATION_LOCK_TTL)
        logger.info("Request pause enabled (TTL=%ds)", _MIGRATION_LOCK_TTL)

    async def _resume_requests(self) -> None:
        """Remove Redis lock key to resume normal request processing."""
        await redis_pool.delete(_MIGRATION_LOCK_KEY)
        logger.info("Request pause removed — traffic resumed")

    async def _swap_engine(self, new_url: str) -> None:
        """Replace global ``engine`` and ``async_session_factory`` in
        ``app.core.database``, disposing the old connection pool.
        """
        import app.core.database as db_mod

        old_engine = db_mod.engine

        new_engine = create_async_engine(
            new_url,
            echo=False,
            pool_size=30,
            max_overflow=15,
            pool_recycle=1800,
            pool_pre_ping=True,
            pool_timeout=5,
        )

        new_session_factory = async_sessionmaker(
            new_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        # Atomic swap of module-level references
        db_mod.engine = new_engine
        db_mod.async_session_factory = new_session_factory

        # Dispose old pool to release connections
        await old_engine.dispose()
        logger.info("Engine swapped to %s", new_url.split("@")[-1] if "@" in new_url else "new target")

    async def _verify_connectivity(self) -> bool:
        """Run a test query on the current global engine.

        Returns ``True`` if the query succeeds, ``False`` otherwise.
        """
        import app.core.database as db_mod

        try:
            async with db_mod.engine.connect() as conn:
                result = await conn.execute(text("SELECT 1"))
                row = result.scalar()
                return row == 1
        except Exception:
            logger.exception("Connectivity verification failed")
            return False

    async def execute_cutover(
        self,
        target_engine: AsyncEngine,
        target_url: str,
    ) -> bool:
        """Pause requests, swap engine to target, verify, resume.

        Auto-rolls back to the source on failure.

        Returns ``True`` on success, ``False`` if cutover failed (auto-rollback
        will have been attempted).
        """
        import app.core.database as db_mod

        # Remember the current (source) URL for rollback
        source_url = str(db_mod.engine.url)

        try:
            await self._pause_requests()
            await self._swap_engine(target_url)

            if await self._verify_connectivity():
                logger.info("Cutover succeeded — now using target database")
                return True

            # Verification failed — auto-rollback
            logger.warning("Cutover verification failed — rolling back to source")
            await self._swap_engine(source_url)
            return False
        except Exception:
            logger.exception("Cutover failed with exception — attempting rollback")
            try:
                await self._swap_engine(source_url)
            except Exception:
                logger.exception("Rollback after cutover failure also failed")
            return False
        finally:
            await self._resume_requests()

    async def execute_rollback(self, source_url: str) -> bool:
        """Pause requests, swap engine back to source, verify, resume.

        Returns ``True`` on success, ``False`` on failure.
        """
        try:
            await self._pause_requests()
            await self._swap_engine(source_url)

            if await self._verify_connectivity():
                logger.info("Rollback succeeded — now using source database")
                return True

            logger.error("Rollback verification failed")
            return False
        except Exception:
            logger.exception("Rollback failed with exception")
            return False
        finally:
            await self._resume_requests()


# ---------------------------------------------------------------------------
# Pure helper functions (for property testing)
# ---------------------------------------------------------------------------


def validate_cutover_confirmation(text: str) -> bool:
    """Return ``True`` only if *text* is exactly ``'CONFIRM CUTOVER'``."""
    return text == "CONFIRM CUTOVER"


def is_rollback_available(cutover_at: datetime, now: datetime) -> bool:
    """Return ``True`` if *now* is within 24 hours of *cutover_at*."""
    return (now - cutover_at) <= timedelta(hours=24)
