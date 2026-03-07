"""Integration tests for cross-module transaction rollback.

**Validates: Requirement 10.1, 10.2**

Tests:
- 10.6: Cross-module operation rolls back all changes on partial failure.

Uses the TransactionalOperation context manager with an in-memory
SQLite-like approach: we simulate two "module" operations inside a single
transaction and verify that a failure in the second operation rolls back
the first.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.transactions import TransactionalOperation


# ---------------------------------------------------------------------------
# Helpers — simulate two module services sharing a session
# ---------------------------------------------------------------------------

class _FakeModuleA:
    """Simulates a service that records a write inside the transaction."""

    def __init__(self) -> None:
        self.committed_values: list[str] = []
        self._pending: list[str] = []

    async def write(self, session, value: str) -> None:
        self._pending.append(value)

    def commit(self) -> None:
        self.committed_values.extend(self._pending)
        self._pending.clear()

    def rollback(self) -> None:
        self._pending.clear()


class _FakeModuleB:
    """Simulates a service that always fails."""

    async def write(self, session, value: str) -> None:
        raise RuntimeError(f"Module B failed on {value}")


# ===========================================================================
# 10.6: Cross-module operation rolls back all changes on partial failure
# ===========================================================================


class TestCrossModuleTransactionRollback:
    """Verify that TransactionalOperation rolls back on partial failure."""

    @pytest.mark.asyncio
    async def test_rollback_on_second_module_failure(self) -> None:
        """If module B fails, module A's changes must not persist."""
        mock_session = AsyncMock()
        mock_session.begin = AsyncMock(return_value=MagicMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=False),
        ))
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()

        mod_a = _FakeModuleA()
        mod_b = _FakeModuleB()

        txn = TransactionalOperation.from_session(mock_session)

        with pytest.raises(RuntimeError, match="Module B failed"):
            async with txn:
                await mod_a.write(txn.session, "invoice-123")
                await mod_b.write(txn.session, "stock-decrement")

        # The session should have been rolled back
        mock_session.rollback.assert_awaited_once()
        # Commit should NOT have been called
        mock_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_commit_on_success(self) -> None:
        """If all modules succeed, the transaction is committed."""
        mock_session = AsyncMock()
        mock_session.begin = AsyncMock(return_value=MagicMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=False),
        ))
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()

        mod_a = _FakeModuleA()

        txn = TransactionalOperation.from_session(mock_session)

        async with txn:
            await mod_a.write(txn.session, "invoice-456")

        mock_session.commit.assert_awaited_once()
        mock_session.rollback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_exception_propagates_after_rollback(self) -> None:
        """The original exception is re-raised after rollback."""
        mock_session = AsyncMock()
        mock_session.begin = AsyncMock(return_value=MagicMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=False),
        ))
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()

        txn = TransactionalOperation.from_session(mock_session)

        with pytest.raises(ValueError, match="bad data"):
            async with txn:
                raise ValueError("bad data")

        mock_session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_multiple_operations_all_rolled_back(self) -> None:
        """Three module operations — failure in the third rolls back all."""
        mock_session = AsyncMock()
        mock_session.begin = AsyncMock(return_value=MagicMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=False),
        ))
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()

        operations_executed: list[str] = []

        async def op_a(session):
            operations_executed.append("A")

        async def op_b(session):
            operations_executed.append("B")

        async def op_c(session):
            operations_executed.append("C")
            raise RuntimeError("op_c failed")

        txn = TransactionalOperation.from_session(mock_session)

        with pytest.raises(RuntimeError, match="op_c failed"):
            async with txn:
                await op_a(txn.session)
                await op_b(txn.session)
                await op_c(txn.session)

        # All three operations were attempted
        assert operations_executed == ["A", "B", "C"]
        # But the transaction was rolled back
        mock_session.rollback.assert_awaited_once()
        mock_session.commit.assert_not_awaited()
