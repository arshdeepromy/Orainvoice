"""Migration test for revision 0225 — cycle-scoped ``pay_periods`` uniqueness.

Drives the actual migration body of
``alembic/versions/2026_06_13_0002-0225_pay_periods_cycle_unique.py`` against the
configured Postgres test database. Real PG is required (the migration manipulates
a real table constraint + unique index and the assertions rely on PostgreSQL
enforcing the unique index), so when no DB is reachable the tests skip rather
than fail red — matching the pattern in
``tests/test_migration_legacy_smtp_to_email_provider.py``.

**Validates: Requirements 8.3, 9.2 — design Decision 5; Testing Strategy → Migration test**

Scenarios covered (per task 1.1):
  * After upgrade, two **active** cycles can each hold a ``pay_period`` with the
    same ``start_date`` (REQ 8.3) — impossible under the old
    ``UNIQUE(org_id, start_date)`` key.
  * A single cycle still cannot duplicate a ``(org_id, pay_cycle_id, start_date)``
    key — the relaxed key keeps single-cycle behaviour intact (REQ 9.2).
  * The upgrade is idempotent — running it twice is a no-op (project rule).
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import AsyncIterator, Callable

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import settings as app_settings

MIGRATION_FILENAME = "2026_06_13_0002-0225_pay_periods_cycle_unique.py"
NEW_INDEX = "uq_pay_periods_org_cycle_start"
OLD_CONSTRAINT = "uq_pay_periods_org_start"


# ---------------------------------------------------------------------------
# Loading + driving the migration (mirrors the 0198 migration-test helpers)
# ---------------------------------------------------------------------------

def _load_migration_module() -> ModuleType:
    """Load the 0225 migration via importlib so we can call upgrade/downgrade."""
    path = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / MIGRATION_FILENAME
    )
    if not path.exists():  # pragma: no cover — defensive
        raise FileNotFoundError(f"Migration not found at {path}")
    module_name = f"_mig_0225_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:  # pragma: no cover — defensive
        raise RuntimeError(f"Could not build importlib spec for {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _invoke(sync_conn: Connection, migration: ModuleType, direction: str) -> None:
    """Run ``migration.upgrade()`` / ``downgrade()`` bound to a live connection."""
    ctx = MigrationContext.configure(connection=sync_conn)
    with Operations.context(ctx):
        fn: Callable[[], None] = getattr(migration, direction)
        fn()


async def _run(engine: AsyncEngine, migration: ModuleType, direction: str) -> None:
    async with engine.connect() as conn:
        await conn.run_sync(_invoke, migration, direction)
        await conn.commit()


@asynccontextmanager
async def _migration_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        app_settings.database_url,
        echo=False,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
    )
    try:
        try:
            async with engine.connect() as conn:
                await conn.execute(sa.text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 — any connect failure means skip
            await engine.dispose()
            pytest.skip(f"Postgres not reachable for migration test: {exc}")
        yield engine
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Schema-introspection + seed helpers
# ---------------------------------------------------------------------------

async def _index_exists(engine: AsyncEngine, name: str) -> bool:
    async with engine.connect() as conn:
        result = await conn.execute(
            sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :n"),
            {"n": name},
        )
        return result.first() is not None


async def _constraint_exists(engine: AsyncEngine, name: str) -> bool:
    async with engine.connect() as conn:
        result = await conn.execute(
            sa.text(
                "SELECT 1 FROM pg_constraint WHERE conname = :n "
                "AND conrelid = 'pay_periods'::regclass"
            ),
            {"n": name},
        )
        return result.first() is not None


async def _seed_cycle(engine: AsyncEngine, org_id: uuid.UUID, name: str) -> uuid.UUID:
    """Insert one active ``pay_cycles`` row (RLS-scoped) and return its id."""
    cycle_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            sa.text("SELECT set_config('app.current_org_id', :oid, true)"),
            {"oid": str(org_id)},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO pay_cycles (id, org_id, name, frequency, anchor_date, "
                "is_default, active) "
                "VALUES (:id, :org, :name, 'weekly', :anchor, false, true)"
            ),
            {
                "id": str(cycle_id),
                "org": str(org_id),
                "name": name,
                "anchor": date(2026, 1, 5),
            },
        )
    return cycle_id


async def _insert_period(
    engine: AsyncEngine,
    org_id: uuid.UUID,
    cycle_id: uuid.UUID,
    start: date,
) -> uuid.UUID:
    """Insert one ``pay_periods`` row (RLS-scoped). Raises on a unique violation."""
    period_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            sa.text("SELECT set_config('app.current_org_id', :oid, true)"),
            {"oid": str(org_id)},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO pay_periods (id, org_id, pay_cycle_id, start_date, "
                "end_date, pay_date, status) "
                "VALUES (:id, :org, :cycle, :start, :end, :pay, 'open')"
            ),
            {
                "id": str(period_id),
                "org": str(org_id),
                "cycle": str(cycle_id),
                "start": start,
                "end": start,
                "pay": start,
            },
        )
    return period_id


async def _cleanup(engine: AsyncEngine, org_id: uuid.UUID) -> None:
    """Remove every row this test seeded for ``org_id`` (RLS-disabled wipe)."""
    async with engine.begin() as conn:
        await conn.execute(sa.text("RESET app.current_org_id"))
        await conn.execute(
            sa.text("DELETE FROM pay_periods WHERE org_id = :oid"),
            {"oid": str(org_id)},
        )
        await conn.execute(
            sa.text("DELETE FROM pay_cycles WHERE org_id = :oid"),
            {"oid": str(org_id)},
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upgrade_allows_two_cycles_same_start_date() -> None:
    """After upgrade, two active cycles can each own a period with the same
    ``start_date``; a single cycle still cannot duplicate that key.

    **Validates: Requirements 8.3, 9.2**
    """
    org_id = uuid.uuid4()
    async with _migration_engine() as engine:
        migration = _load_migration_module()
        # Upgrade is idempotent (DROP ... IF EXISTS / CREATE ... IF NOT EXISTS),
        # so it brings the schema to the cycle-scoped key from any start state.
        await _run(engine, migration, "upgrade")

        assert await _index_exists(engine, NEW_INDEX), (
            "upgrade must create the cycle-scoped unique index"
        )
        assert not await _constraint_exists(engine, OLD_CONSTRAINT), (
            "upgrade must drop the old org+start_date unique constraint"
        )

        try:
            cycle_a = await _seed_cycle(engine, org_id, "Weekly")
            cycle_b = await _seed_cycle(engine, org_id, "Fortnightly")
            shared_start = date(2026, 6, 8)

            # REQ 8.3: two different active cycles, same start_date — both allowed.
            await _insert_period(engine, org_id, cycle_a, shared_start)
            await _insert_period(engine, org_id, cycle_b, shared_start)

            # REQ 9.2: a single cycle still cannot duplicate
            # (org_id, pay_cycle_id, start_date).
            with pytest.raises(IntegrityError):
                await _insert_period(engine, org_id, cycle_a, shared_start)
        finally:
            await _cleanup(engine, org_id)


@pytest.mark.asyncio
async def test_upgrade_is_idempotent() -> None:
    """Re-running the upgrade is a no-op: the index stays present and no error
    is raised the second time.

    **Validates: Requirements 8.3 (project idempotency rule)**
    """
    async with _migration_engine() as engine:
        migration = _load_migration_module()
        await _run(engine, migration, "upgrade")
        assert await _index_exists(engine, NEW_INDEX)

        # Second run must not raise and must leave the index in place.
        await _run(engine, migration, "upgrade")
        assert await _index_exists(engine, NEW_INDEX), (
            "re-running the upgrade must keep the cycle-scoped unique index"
        )
        assert not await _constraint_exists(engine, OLD_CONSTRAINT)


@pytest.mark.asyncio
async def test_downgrade_then_upgrade_round_trip() -> None:
    """Downgrade restores the old constraint and removes the new index;
    re-upgrading returns to the cycle-scoped key (leaving the DB at head state).

    **Validates: Requirements 8.3, 9.2 (reversibility)**
    """
    async with _migration_engine() as engine:
        migration = _load_migration_module()
        try:
            await _run(engine, migration, "upgrade")
            await _run(engine, migration, "downgrade")

            assert await _constraint_exists(engine, OLD_CONSTRAINT), (
                "downgrade must restore the org+start_date unique constraint"
            )
            assert not await _index_exists(engine, NEW_INDEX), (
                "downgrade must drop the cycle-scoped unique index"
            )
        finally:
            # Re-upgrade so the shared DB is left at the 0225 (head) schema.
            await _run(engine, migration, "upgrade")
            assert await _index_exists(engine, NEW_INDEX)
            assert not await _constraint_exists(engine, OLD_CONSTRAINT)
