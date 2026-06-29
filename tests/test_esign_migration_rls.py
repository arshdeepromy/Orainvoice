"""Migration + RLS-isolation tests for the E-Signature Integration (spec task 1.4).

Exercises the two esign migrations against the configured Postgres test database:

  * **Migration A** — ``alembic/versions/2026_06_28_0002-0232_esign_schema.py``
    (revision ``0232``): creates the four org-scoped tables (``esign_envelopes``,
    ``esign_recipients``, ``esign_webhook_events``, ``esign_org_connections``)
    under RLS, adds the CHECK constraints, seeds the **mandatory**
    ``module_registry`` row (slug ``esignatures``) and the **optional**
    ``feature_flags`` catalogue row (keyed ``key='esignatures'``).
  * **Migration B** — ``alembic/versions/2026_06_28_0003-0233_esign_perf_indexes.py``
    (revision ``0233``): creates the two ``esign_envelopes`` performance indexes
    via ``CREATE INDEX CONCURRENTLY`` inside an ``autocommit_block``.

Three behaviours are asserted (per task 1.4):

  1. **Apply / revert round-trip.** Driving the full chain through the real
     ``alembic`` CLI (the only faithful way to run ``0233``'s ``CONCURRENTLY``
     DDL, which cannot run inside a transaction) — both revisions apply on top of
     ``0231``, both revert cleanly back to ``0231`` (all four tables gone, both
     perf indexes gone, the ``module_registry`` seed removed, and the optional
     ``feature_flags`` row removed), and re-applying restores the full schema.
  2. **Idempotent on re-run.** ``0232``'s body is re-runnable (``CREATE TABLE IF
     NOT EXISTS`` / ``DROP CONSTRAINT IF EXISTS`` + ``ADD`` / ``DROP POLICY IF
     EXISTS`` + ``CREATE`` / ``INSERT ... ON CONFLICT DO NOTHING``) — running it
     twice never errors; ``0233``'s ``CREATE INDEX CONCURRENTLY IF NOT EXISTS``
     statements are likewise re-runnable.
  3. **Seeds.** The ``esignatures`` ``module_registry`` row is seeded (R2.1
     smoke); the optional ``feature_flags`` row, when present, is keyed by
     ``key='esignatures'`` (NOT ``slug``) and is removed on downgrade.
  4. **RLS smoke (R13.2 / R13.7).** With ``app.current_org_id`` = org A, org B's
     rows in all four tables are invisible to a non-superuser role
     (``esign_recipients`` is scoped through its parent envelope; the other three
     directly by ``org_id``).

Why the RLS test uses a throwaway non-superuser role
----------------------------------------------------
The test DB connection is the ``postgres`` **superuser**, and the project's RLS
posture is ``ENABLE`` (not ``FORCE``). PostgreSQL **always bypasses RLS for
superusers**, so a naive "set the GUC, insert both orgs, select" on the test
connection would return *both* rows and prove nothing. This test therefore
mirrors ``tests/test_payroll_tax_rls_smoke.py``: it creates a throwaway
non-superuser role inside a rolled-back transaction, seeds rows for two orgs as
the superuser, proves the superuser sees both (control), then ``SET LOCAL ROLE``
to the non-superuser role and asserts the ``tenant_isolation`` policy hides the
other org's rows.

**Validates: Requirements 2.1, 13.2, 13.7**

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings``. When Postgres is unreachable the tests skip rather
  than fail red, matching the other DB-backed tests in this repo.
- The apply/revert test drives the real ``alembic`` CLI and downgrades the shared
  dev DB to ``0231`` then re-upgrades to head, always restoring head in a
  ``finally`` — the same approach as ``tests/test_quote_migration_property.py``.
- Backend tests run via ``docker compose exec app python -m pytest``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import subprocess
import sys
import uuid
from pathlib import Path
from types import ModuleType
from typing import Callable

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings

# ---------------------------------------------------------------------------
# Revisions / objects under test.
# ---------------------------------------------------------------------------

REV_BASE = "0231"          # the revision the esign chain is parented on
REV_SCHEMA = "0232"        # Migration A
REV_PERF = "0233"          # Migration B (head)

MIGRATION_A_FILENAME = "2026_06_28_0002-0232_esign_schema.py"
MIGRATION_B_FILENAME = "2026_06_28_0003-0233_esign_perf_indexes.py"

ESIGN_TABLES = (
    "esign_envelopes",
    "esign_recipients",
    "esign_webhook_events",
    "esign_org_connections",
)
PERF_INDEXES = (
    "idx_esign_envelopes_org_updated",
    "idx_esign_envelopes_documenso_doc",
)
MODULE_SLUG = "esignatures"
FEATURE_FLAG_KEY = "esignatures"


# ---------------------------------------------------------------------------
# Engine / session helpers — fresh engine per call (asyncpg connections are
# bound to the event loop ``asyncio.run`` creates), matching the reference
# DB-backed tests in this repo.
# ---------------------------------------------------------------------------


async def _make_factory():
    engine = create_async_engine(
        app_settings.database_url,
        echo=False,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def _db_reachable() -> bool:
    engine = create_async_engine(app_settings.database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 — any connect failure means skip
        return False
    finally:
        await engine.dispose()


def _skip_unless_db() -> None:
    if not asyncio.run(_db_reachable()):
        pytest.skip("Postgres not reachable for esign migration/RLS test")


# ---------------------------------------------------------------------------
# Alembic CLI driver (subprocess) — the faithful way to run 0233's
# CONCURRENTLY DDL, which alembic's env.py wires through an autocommit_block.
# ---------------------------------------------------------------------------


def _run_alembic(command: str, revision: str | None = None) -> str:
    cmd = ["alembic", command]
    if revision:
        cmd.append(revision)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic {command} {revision or ''} failed:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result.stdout


async def _current_revision() -> str | None:
    engine, factory = await _make_factory()
    try:
        async with factory() as session:
            result = await session.execute(
                sa.text("SELECT version_num FROM alembic_version LIMIT 1")
            )
            row = result.first()
            return row[0] if row else None
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Schema-introspection helpers (run as the superuser test connection, which
# bypasses RLS — so they see every row/table regardless of the GUC).
# ---------------------------------------------------------------------------


async def _table_exists(session: AsyncSession, name: str) -> bool:
    result = await session.execute(sa.text("SELECT to_regclass(:n)"), {"n": name})
    return result.scalar() is not None


async def _index_exists(session: AsyncSession, name: str) -> bool:
    result = await session.execute(
        sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :n"), {"n": name}
    )
    return result.first() is not None


async def _module_seed_count(session: AsyncSession) -> int:
    result = await session.execute(
        sa.text("SELECT count(*) FROM module_registry WHERE slug = :s"),
        {"s": MODULE_SLUG},
    )
    return result.scalar() or 0


async def _feature_flag_count(session: AsyncSession) -> int:
    # feature_flags is keyed by `key`, NOT `slug` — assert the row is keyed
    # exactly there.
    result = await session.execute(
        sa.text("SELECT count(*) FROM feature_flags WHERE key = :k"),
        {"k": FEATURE_FLAG_KEY},
    )
    return result.scalar() or 0


async def _assert_schema_present() -> None:
    engine, factory = await _make_factory()
    try:
        async with factory() as session:
            for table in ESIGN_TABLES:
                assert await _table_exists(session, table), (
                    f"{table} should exist at head {REV_PERF}"
                )
            for index in PERF_INDEXES:
                assert await _index_exists(session, index), (
                    f"perf index {index} should exist at head {REV_PERF}"
                )
            assert await _module_seed_count(session) == 1, (
                "the esignatures module_registry seed (R2.1) must be present at head"
            )
            # The feature_flags row is optional, but this migration does seed it,
            # so when present it must be keyed by key='esignatures'.
            assert await _feature_flag_count(session) == 1, (
                "the optional feature_flags row must be keyed key='esignatures' "
                "when seeded"
            )
    finally:
        await engine.dispose()


async def _assert_schema_absent() -> None:
    engine, factory = await _make_factory()
    try:
        async with factory() as session:
            for table in ESIGN_TABLES:
                assert not await _table_exists(session, table), (
                    f"{table} must be dropped after downgrade to {REV_BASE}"
                )
            for index in PERF_INDEXES:
                assert not await _index_exists(session, index), (
                    f"perf index {index} must be dropped after downgrade to {REV_BASE}"
                )
            assert await _module_seed_count(session) == 0, (
                "the esignatures module_registry seed must be removed on downgrade"
            )
            assert await _feature_flag_count(session) == 0, (
                "the optional feature_flags row must be removed on downgrade"
            )
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Migration-module loader + direct driver (for idempotency, mirrors the 0225
# migration-test helpers).
# ---------------------------------------------------------------------------


def _load_migration_module(filename: str) -> ModuleType:
    path = (
        Path(__file__).resolve().parent.parent / "alembic" / "versions" / filename
    )
    if not path.exists():  # pragma: no cover — defensive
        raise FileNotFoundError(f"Migration not found at {path}")
    module_name = f"_mig_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:  # pragma: no cover — defensive
        raise RuntimeError(f"Could not build importlib spec for {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _invoke(sync_conn: Connection, migration: ModuleType, direction: str) -> None:
    ctx = MigrationContext.configure(connection=sync_conn)
    with Operations.context(ctx):
        fn: Callable[[], None] = getattr(migration, direction)
        fn()


# ===========================================================================
# Test 1 — apply / revert round-trip + seeds (R2.1, R13.1).
# ===========================================================================


def test_esign_migrations_apply_revert_roundtrip() -> None:
    """Both esign revisions apply on top of 0231, revert cleanly, and re-apply.

    Asserts the four tables + two perf indexes + the mandatory module_registry
    seed + the optional feature_flags row all appear at head, all disappear on
    downgrade to 0231, and all return on re-upgrade.

    **Validates: Requirements 2.1, 13.2**
    """
    _skip_unless_db()

    # Bring the DB to head, then step down to the esign perf-index revision
    # (0233). Migration 0234 (esign_field_templates, the field-placement
    # feature) sits above 0233 and is exercised by its own migration test, so
    # this integration-schema round-trip operates against REV_PERF as its top.
    _run_alembic("upgrade", "head")
    _run_alembic("downgrade", REV_PERF)
    assert asyncio.run(_current_revision()) == REV_PERF
    asyncio.run(_assert_schema_present())

    try:
        # Revert both esign revisions back to their parent 0231.
        _run_alembic("downgrade", REV_BASE)
        assert asyncio.run(_current_revision()) == REV_BASE
        asyncio.run(_assert_schema_absent())

        # Re-apply — schema is faithfully restored.
        _run_alembic("upgrade", REV_PERF)
        assert asyncio.run(_current_revision()) == REV_PERF
        asyncio.run(_assert_schema_present())
    finally:
        # Always leave the shared DB at the true head (0234).
        _run_alembic("upgrade", "head")


# ===========================================================================
# Test 2 — Migration A (0232) body is idempotent on re-run.
# ===========================================================================


async def _run_0232_twice() -> None:
    engine, _ = await _make_factory()
    try:
        migration = _load_migration_module(MIGRATION_A_FILENAME)
        async with engine.connect() as conn:
            # Run the transactional body twice in one transaction; every
            # statement is guarded (IF NOT EXISTS / DROP+ADD / ON CONFLICT) so
            # the second run must not raise.
            await conn.run_sync(_invoke, migration, "upgrade")
            await conn.run_sync(_invoke, migration, "upgrade")
            # Roll back — these are all no-ops against the already-applied head,
            # and we must not disturb the shared DB.
            await conn.rollback()
    finally:
        await engine.dispose()


def test_migration_0232_is_idempotent() -> None:
    """Re-running Migration A's body does not error (tables/constraints/policies/
    seeds are all guarded).

    **Validates: Requirements 2.1, 13.2**
    """
    _skip_unless_db()
    asyncio.run(_run_0232_twice())
    # Head schema is still intact afterwards.
    asyncio.run(_assert_schema_present())


# ===========================================================================
# Test 3 — Migration B (0233) CONCURRENTLY index DDL is idempotent on re-run.
# ===========================================================================


async def _run_0233_indexes_twice() -> None:
    # CONCURRENTLY DDL cannot run inside a transaction — use an AUTOCOMMIT engine.
    engine = create_async_engine(
        app_settings.database_url, isolation_level="AUTOCOMMIT"
    )
    try:
        migration = _load_migration_module(MIGRATION_B_FILENAME)
        statements = migration._UPGRADE_INDEXES  # (description, sql) tuples
        async with engine.connect() as conn:
            for _ in range(2):
                for _description, sql in statements:
                    # CREATE INDEX CONCURRENTLY IF NOT EXISTS — re-running on the
                    # already-built indexes is a guarded no-op.
                    await conn.execute(sa.text(sql))
    finally:
        await engine.dispose()


def test_migration_0233_indexes_are_idempotent() -> None:
    """Re-running Migration B's CONCURRENTLY index statements does not error and
    leaves both perf indexes present.

    **Validates: Requirements 13.2**
    """
    _skip_unless_db()
    asyncio.run(_run_0233_indexes_twice())
    engine, factory = asyncio.run(_make_factory())
    try:
        async def _check() -> None:
            async with factory() as session:
                for index in PERF_INDEXES:
                    assert await _index_exists(session, index), (
                        f"{index} must remain after re-running the CONCURRENTLY DDL"
                    )
        asyncio.run(_check())
    finally:
        asyncio.run(engine.dispose())


# ===========================================================================
# Test 4 — RLS isolation smoke across all four esign tables (R13.2, R13.7).
# ===========================================================================


async def _set_org_context(session: AsyncSession, org_id: uuid.UUID) -> None:
    await session.execute(
        sa.text("SELECT set_config('app.current_org_id', :oid, true)"),
        {"oid": str(org_id)},
    )


async def _visible_ids(
    session: AsyncSession, table: str, ids: tuple[uuid.UUID, uuid.UUID]
) -> set[str]:
    result = await session.execute(
        sa.text(f"SELECT id FROM {table} WHERE id IN (:a, :b)"),  # noqa: S608 — table is a constant
        {"a": str(ids[0]), "b": str(ids[1])},
    )
    return {str(row[0]) for row in result.fetchall()}


async def _run_rls_smoke() -> None:
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()

    # Per-table id pairs (index 0 = org A's row, index 1 = org B's row).
    env_ids = (uuid.uuid4(), uuid.uuid4())
    rec_ids = (uuid.uuid4(), uuid.uuid4())
    evt_ids = (uuid.uuid4(), uuid.uuid4())
    conn_ids = (uuid.uuid4(), uuid.uuid4())

    role_name = f"esign_rls_smoke_{uuid.uuid4().hex}"
    qrole = f'"{role_name}"'

    engine, factory = await _make_factory()
    try:
        async with factory() as session:
            try:
                # --- 1. Throwaway non-superuser role (rolled back with the tx).
                await session.execute(
                    sa.text(
                        f"CREATE ROLE {qrole} NOSUPERUSER NOCREATEDB "
                        f"NOCREATEROLE NOLOGIN"
                    )
                )
                await session.execute(
                    sa.text(f"GRANT USAGE ON SCHEMA public TO {qrole}")
                )
                for table in ESIGN_TABLES:
                    await session.execute(
                        sa.text(f"GRANT SELECT ON {table} TO {qrole}")
                    )

                # --- 2. Seed one row per table for org A and org B (as the
                #        superuser, so the inserts themselves are not filtered).
                for org, env_id, rec_id, evt_id, conn_id in (
                    (org_a, env_ids[0], rec_ids[0], evt_ids[0], conn_ids[0]),
                    (org_b, env_ids[1], rec_ids[1], evt_ids[1], conn_ids[1]),
                ):
                    await session.execute(
                        sa.text(
                            "INSERT INTO esign_envelopes "
                            "(id, org_id, agreement_type, originating_entity_type, "
                            " originating_entity_id, status) "
                            "VALUES (:id, :org, 'nda', 'staff', :ent, 'sent')"
                        ),
                        {"id": str(env_id), "org": str(org), "ent": str(uuid.uuid4())},
                    )
                    await session.execute(
                        sa.text(
                            "INSERT INTO esign_recipients "
                            "(id, envelope_id, name, email, signing_role) "
                            "VALUES (:id, :env, 'Signer', 'signer@example.com', 'SIGNER')"
                        ),
                        {"id": str(rec_id), "env": str(env_id)},
                    )
                    await session.execute(
                        sa.text(
                            "INSERT INTO esign_webhook_events "
                            "(id, org_id, dedupe_key) VALUES (:id, :org, :dk)"
                        ),
                        {"id": str(evt_id), "org": str(org), "dk": uuid.uuid4().hex},
                    )
                    await session.execute(
                        sa.text(
                            "INSERT INTO esign_org_connections "
                            "(id, org_id, base_url, webhook_routing_id) "
                            "VALUES (:id, :org, 'https://documenso.example', :routing)"
                        ),
                        {"id": str(conn_id), "org": str(org), "routing": uuid.uuid4().hex},
                    )
                await session.flush()

                tables_and_ids = {
                    "esign_envelopes": env_ids,
                    "esign_recipients": rec_ids,
                    "esign_webhook_events": evt_ids,
                    "esign_org_connections": conn_ids,
                }

                # --- 3. Control: as the superuser, BOTH rows are visible per
                #        table — RLS is bypassed for superusers, proving the
                #        isolation in step 4 is the policy acting (and that the
                #        test would fail if RLS were off).
                await _set_org_context(session, org_a)
                for table, ids in tables_and_ids.items():
                    visible = await _visible_ids(session, table, ids)
                    assert visible == {str(ids[0]), str(ids[1])}, (
                        f"control failed for {table}: the superuser should see "
                        f"BOTH org rows (RLS bypassed for superusers); got {visible}"
                    )

                # --- 4a. As the NON-superuser role, org A context: only org A's
                #         row is visible per table; org B's is NOT returned.
                await _set_org_context(session, org_a)
                await session.execute(sa.text(f"SET LOCAL ROLE {qrole}"))
                try:
                    under_a = {
                        table: await _visible_ids(session, table, ids)
                        for table, ids in tables_and_ids.items()
                    }
                finally:
                    await session.execute(sa.text("RESET ROLE"))

                for table, ids in tables_and_ids.items():
                    assert str(ids[1]) not in under_a[table], (
                        f"tenant isolation breach on {table}: org B's row was "
                        f"visible while app.current_org_id = org A "
                        f"(visible={under_a[table]})"
                    )
                    assert under_a[table] == {str(ids[0])}, (
                        f"with org A context the non-superuser role must see "
                        f"exactly org A's {table} row; got {under_a[table]}"
                    )

                # --- 4b. Mirror: org B context, only org B is visible.
                await _set_org_context(session, org_b)
                await session.execute(sa.text(f"SET LOCAL ROLE {qrole}"))
                try:
                    under_b = {
                        table: await _visible_ids(session, table, ids)
                        for table, ids in tables_and_ids.items()
                    }
                finally:
                    await session.execute(sa.text("RESET ROLE"))

                for table, ids in tables_and_ids.items():
                    assert str(ids[0]) not in under_b[table], (
                        f"tenant isolation breach on {table}: org A's row was "
                        f"visible while app.current_org_id = org B "
                        f"(visible={under_b[table]})"
                    )
                    assert under_b[table] == {str(ids[1])}, (
                        f"with org B context the non-superuser role must see "
                        f"exactly org B's {table} row; got {under_b[table]}"
                    )
            finally:
                # Never persist — drops the throwaway role, the seeded rows, and
                # the transaction-local GUC all in one rollback.
                await session.rollback()
    finally:
        await engine.dispose()


def test_esign_rls_isolates_other_org_across_all_tables() -> None:
    """R13.2/R13.7: with app.current_org_id = org A, org B's rows in
    esign_envelopes / esign_recipients / esign_webhook_events /
    esign_org_connections are not visible — the tenant_isolation policies
    enforce per-org scoping (recipients via their parent envelope).

    **Validates: Requirements 13.2, 13.7**
    """
    _skip_unless_db()
    asyncio.run(_run_rls_smoke())
