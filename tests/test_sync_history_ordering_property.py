"""Property-based tests for sync history ordering.

Feature: file-storage-replication, Property 7: Sync history ordering

For any set of sync history entries in the database, querying the history
endpoint SHALL return entries ordered by ``started_at`` descending
(newest first).

**Validates: Requirement 6.4**

Uses Hypothesis to generate random history entries with random timestamps
within the last 30 days, insert them into the DB, then verify that
``VolumeSyncService.get_history()`` returns them ordered by ``started_at``
descending.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings as app_settings

# Import ORM models so SQLAlchemy can resolve relationships
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.admin import models as _admin_models  # noqa: F401
from app.modules.organisations import models as _org_models  # noqa: F401
from app.modules.branding import models as _branding_models  # noqa: F401
from app.modules.billing import models as _billing_models  # noqa: F401
from app.modules.ha import volume_sync_models as _volume_sync_models  # noqa: F401

from app.modules.ha.volume_sync_models import VolumeSyncHistory
from app.modules.ha.volume_sync_service import VolumeSyncService

# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Base time: now in UTC
_NOW = datetime.now(timezone.utc)

# Random timestamps within the last 30 days
timestamp_strategy = st.floats(
    min_value=0.0,
    max_value=30 * 24 * 3600.0,  # 30 days in seconds
    allow_nan=False,
    allow_infinity=False,
).map(lambda offset: _NOW - timedelta(seconds=offset))

# Status values
status_strategy = st.sampled_from(["success", "failure", "running"])

# Sync type values
sync_type_strategy = st.sampled_from(["automatic", "manual"])

# A single history entry as a dict
history_entry_strategy = st.fixed_dictionaries({
    "started_at": timestamp_strategy,
    "status": status_strategy,
    "sync_type": sync_type_strategy,
    "files_transferred": st.integers(min_value=0, max_value=10000),
    "bytes_transferred": st.integers(min_value=0, max_value=10_000_000_000),
})

# A list of 2–20 history entries
history_entries_strategy = st.lists(
    history_entry_strategy,
    min_size=2,
    max_size=20,
)


# ---------------------------------------------------------------------------
# Per-test engine/session factory
# ---------------------------------------------------------------------------

async def _make_session() -> tuple[AsyncSession, object]:
    """Create a fresh engine + session for each test run."""
    test_engine = create_async_engine(
        app_settings.database_url,
        echo=False,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False,
    )
    session = factory()
    return session, test_engine


async def _cleanup_history(session: AsyncSession) -> None:
    """Delete all test history rows."""
    await session.execute(text("DELETE FROM volume_sync_history"))
    await session.commit()


# ---------------------------------------------------------------------------
# Property 7: Sync history ordering
# Feature: file-storage-replication, Property 7: Sync history ordering
# **Validates: Requirement 6.4**
# ---------------------------------------------------------------------------


class TestSyncHistoryOrderingProperty:
    """Property 7 — For any set of sync history entries in the database,
    querying the history endpoint SHALL return entries ordered by
    ``started_at`` descending (newest first)."""

    @PBT_SETTINGS
    @given(entries=history_entries_strategy)
    def test_history_returned_in_descending_started_at_order(self, entries):
        """Generated history entries with random timestamps SHALL be
        returned ordered by ``started_at`` descending (newest first).

        **Validates: Requirement 6.4**
        """
        import asyncio

        async def _run():
            session, engine = await _make_session()
            try:
                # Clean slate
                async with session.begin():
                    await _cleanup_history(session)

                # Insert all generated history entries
                async with session.begin():
                    for entry in entries:
                        row = VolumeSyncHistory(
                            id=uuid.uuid4(),
                            started_at=entry["started_at"],
                            completed_at=None,
                            status=entry["status"],
                            files_transferred=entry["files_transferred"],
                            bytes_transferred=entry["bytes_transferred"],
                            error_message=None,
                            sync_type=entry["sync_type"],
                        )
                        session.add(row)

                # Query via the service
                svc = VolumeSyncService()
                async with session.begin():
                    result = await svc.get_history(session, limit=50)

                # Verify we got all entries back
                assert len(result) == len(entries), (
                    f"Expected {len(entries)} entries, got {len(result)}"
                )

                # Verify ordering: started_at must be descending
                for i in range(len(result) - 1):
                    current_ts = result[i].started_at
                    next_ts = result[i + 1].started_at
                    assert current_ts >= next_ts, (
                        f"History not in descending order at index {i}: "
                        f"{current_ts} < {next_ts}"
                    )

            finally:
                try:
                    async with session.begin():
                        await _cleanup_history(session)
                except Exception:
                    pass
                await session.close()
                await engine.dispose()

        asyncio.get_event_loop().run_until_complete(_run())
