"""Cross-module transaction infrastructure.

Provides :class:`TransactionalOperation`, an async context manager that
wraps a single database session/transaction.  All operations performed
inside the context share the same session and are committed atomically.
If any step raises, the entire transaction is rolled back.

Usage::

    async with TransactionalOperation() as txn:
        await txn.session.execute(...)
        await some_service.do_work(session=txn.session)
        # commit happens automatically on clean exit
        # rollback happens automatically on exception

**Validates: Requirement 10.1, 10.2**
"""

from __future__ import annotations

import logging
from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory

logger = logging.getLogger(__name__)


class TransactionalOperation:
    """Async context manager wrapping a DB session for cross-module atomicity.

    On ``__aenter__`` a new session and transaction are opened.
    On clean ``__aexit__`` the transaction is committed.
    On any exception the transaction is rolled back and the exception
    re-raised so callers can handle it.
    """

    def __init__(self) -> None:
        self._session: AsyncSession | None = None
        self._owns_session: bool = True

    # Allow injecting an existing session (useful for testing)
    @classmethod
    def from_session(cls, session: AsyncSession) -> "TransactionalOperation":
        """Create a TransactionalOperation using an existing session.

        The caller retains ownership — the context manager will NOT close
        the session on exit, but will still commit/rollback.
        """
        inst = cls()
        inst._session = session
        inst._owns_session = False
        return inst

    @property
    def session(self) -> AsyncSession:
        """The underlying SQLAlchemy async session."""
        if self._session is None:
            raise RuntimeError(
                "TransactionalOperation must be used as an async context manager"
            )
        return self._session

    async def __aenter__(self) -> "TransactionalOperation":
        if self._session is None:
            self._session = async_session_factory()
            self._owns_session = True
        await self._session.begin()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        if self._session is None:
            return False

        try:
            if exc_type is not None:
                logger.warning(
                    "Rolling back cross-module transaction due to %s: %s",
                    exc_type.__name__,
                    exc_val,
                )
                await self._session.rollback()
            else:
                await self._session.commit()
        except Exception:
            logger.exception("Error during transaction finalisation")
            try:
                await self._session.rollback()
            except Exception:
                logger.exception("Rollback also failed")
            raise
        finally:
            if self._owns_session:
                await self._session.close()
                self._session = None

        # Do not suppress the original exception
        return False
