"""Migration + RLS-isolation tests for E-Signature Field Placement (spec task 20.3).

Exercises migration ``0234`` against the configured Postgres test database:

  * **Migration 0234** — ``alembic/versions/2026_06_28_0004-0234_esign_field_templates.py``
    (revision ``0234``, parented on ``0233``): creates the ONE new org-scoped
    table this spec introduces, ``esign_field_templates``, under row-level
    security with a ``tenant_isolation`` policy keyed on
    ``current_setting('app.current_org_id', true)::uuid`` (``USING`` +
    ``WITH CHECK``) — mirroring the four esign tables from migration ``0232``.
    The two performance indexes (``ix_esign_field_templates_org`` and
    ``ix_esign_field_templates_org_agreement``) are created via
    ``CREATE INDEX CONCURRENTLY`` inside an ``autocommit_block``.

Four behaviours are asserted (per task 20.3):

  1. **Apply / revert round-trip.** Driving the chain through the real
     ``alembic`` CLI (the only faithful way to run ``0234``'s ``CONCURRENTLY``
     DDL, which cannot run inside a transaction): ``0234`` applies on top of
     ``0233`` (table + both perf indexes present), reverts cleanly back to
     ``0233`` (table + both indexes gone), and re-applies, restoring the schema.
  2. **Expected columns.** At head the table carries exactly the columns the
     migration + ORM model declare: ``id``, ``org_id``, ``name``,
     ``agreement_type``, ``fields``, ``roles``, ``created_at``, ``updated_at``,
     ``created_by``.
  3. **RLS enabled + policy present.** ``esign_field_templates`` has row-level
     security enabled and a ``tenant_isolation`` policy.
  4. **Idempotent on re-run.** ``0234``'s table/RLS DDL (``CREATE TABLE IF NOT
     EXISTS`` / ``ENABLE ROW LEVEL SECURITY`` / ``DROP POLICY IF EXISTS`` +
     ``CREATE POLICY``) and its ``CREATE INDEX CONCURRENTLY IF NOT EXISTS``
     statements are re-runnable without error.
  5. **RLS smoke (R17.3 / R17.4).** With ``app.current_org_id`` = org A, a row
     inserted under org B is invisible to a non-superuser role, and vice versa —
     the ``tenant_isolation`` policy isolates rows by org.

Why the RLS test uses a throwaway non-superuser role
----------------------------------------------------
The test DB connection is the ``postgres`` **superuser**, and the project's RLS
posture is ``ENABLE`` (not ``FORCE``). PostgreSQL **always bypasses RLS for
superusers**, so a naive "set the GUC, insert both orgs, select" on the test
connection would return *both* rows and prove nothing. This test therefore
mirrors ``tests/test_esign_migration_rls.py`` (and ``test_payroll_tax_rls_smoke``):
it creates a throwaway non-superuser role inside a rolled-back transaction, seeds
rows for two orgs as the superuser, proves the superuser sees both (control),
then ``SET LOCAL ROLE`` to the non-superuser role and asserts the
``tenant_isolation`` policy hides the other org's row.

**Validates: Requirements 17.3, 17.4**

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings``. When Postgres is unreachable the tests skip rather
  than fail red, matching the other DB-backed tests in this repo.
- The apply/revert test drives the real ``alembic`` CLI, downgrades the shared
  dev DB to ``0233`` then re-upgrades to head, always restoring head in a
  ``finally`` — the same approach as ``tests/test_esign_migration_rls.py``.
- Backend tests run via ``docker compose exec app python -m pytest``.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings

# ---------------------------------------------------------------------------
# Revisions / objects under test.
# ---------------------------------------------------------------------------

REV_BEFORE = "0233"        # the revision migration 0234 is parented on
REV_TEMPLATES = "0234"     # the migration under test (head)

MIGRATION_FILENAME = "2026_06_28_0004-0234_esign_field_templates.py"

TEMPLATES_TABLE = "esign_field_templates"
TEMPLATES_INDEXES = (
    "ix_esign_field_templates_org",
    "ix_esign_field_templates_org_agreement",
)
EXPECTED_COLUMNS = {
    "id",
    "org_id",
    "name",
    "agreement_type",
    "fields",
    "roles",
    "created_at",
    "updated_at",
    "created_by",
}
TENANT_ISOLATION_POLICY = "tenant_isolation"


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
        pytest.skip("Postgres not reachable for esign_field_templates migration/RLS test")


# ---------------------------------------------------------------------------
# Alembic CLI driver (subprocess) — the faithful way to run 0234's
# CONCURRENTLY DDL, which alembic's env.py wires through an autocommit_block.
# ---------------------------------------------------------------------------


def _run_alembic(command: str, revision: str | None = None) -> str:
    import subprocess

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


async def _columns(session: AsyncSession, table: str) -> set[str]:
    result = await session.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = :t"
        ),
        {"t": table},
    )
    return {row[0] for row in result.fetchall()}


async def _rls_enabled(session: AsyncSession, table: str) -> bool:
    result = await session.execute(
        sa.text("SELECT relrowsecurity FROM pg_class WHERE relname = :t"),
        {"t": table},
    )
    return bool(result.scalar())


async def _policy_exists(session: AsyncSession, table: str, policy: str) -> bool:
    result = await session.execute(
        sa.text(
            "SELECT 1 FROM pg_policies "
            "WHERE tablename = :t AND policyname = :p"
        ),
        {"t": table, "p": policy},
    )
    return result.first() is not None


# ===========================================================================
# Test 1 — apply / revert round-trip (table + both perf indexes).
# ===========================================================================


def test_esign_field_templates_migration_apply_revert_roundtrip() -> None:
    """Migration 0234 applies on top of 0233, reverts cleanly, and re-applies.

    Asserts the ``esign_field_templates`` table + both CONCURRENTLY perf indexes
    appear at head, disappear on downgrade to 0233, and return on re-upgrade.

    **Validates: Requirements 17.3, 17.4**
    """
    _skip_unless_db()

    # Bring the DB to head and confirm the table + indexes are present.
    _run_alembic("upgrade", "head")

    async def _assert_present() -> None:
        engine, factory = await _make_factory()
        try:
            async with factory() as session:
                assert await _table_exists(session, TEMPLATES_TABLE), (
                    f"{TEMPLATES_TABLE} should exist at head {REV_TEMPLATES}"
                )
                for index in TEMPLATES_INDEXES:
                    assert await _index_exists(session, index), (
                        f"perf index {index} should exist at head {REV_TEMPLATES}"
                    )
        finally:
            await engine.dispose()

    async def _assert_absent() -> None:
        engine, factory = await _make_factory()
        try:
            async with factory() as session:
                assert not await _table_exists(session, TEMPLATES_TABLE), (
                    f"{TEMPLATES_TABLE} must be dropped after downgrade to {REV_BEFORE}"
                )
                for index in TEMPLATES_INDEXES:
                    assert not await _index_exists(session, index), (
                        f"perf index {index} must be dropped after downgrade "
                        f"to {REV_BEFORE}"
                    )
        finally:
            await engine.dispose()

    asyncio.run(_assert_present())

    try:
        # Revert 0234 back to its parent 0233.
        _run_alembic("downgrade", REV_BEFORE)
        assert asyncio.run(_current_revision()) == REV_BEFORE
        asyncio.run(_assert_absent())

        # Re-apply — schema is faithfully restored.
        _run_alembic("upgrade", REV_TEMPLATES)
        assert asyncio.run(_current_revision()) == REV_TEMPLATES
        asyncio.run(_assert_present())
    finally:
        # Always leave the shared DB at head.
        _run_alembic("upgrade", "head")


# ===========================================================================
# Test 2 — expected columns, RLS enabled, tenant_isolation policy present.
# ===========================================================================


def test_esign_field_templates_columns_rls_and_policy() -> None:
    """At head the table carries the expected columns, has RLS enabled, and a
    ``tenant_isolation`` policy.

    **Validates: Requirements 17.3, 17.4**
    """
    _skip_unless_db()
    _run_alembic("upgrade", "head")

    async def _check() -> None:
        engine, factory = await _make_factory()
        try:
            async with factory() as session:
                cols = await _columns(session, TEMPLATES_TABLE)
                assert cols == EXPECTED_COLUMNS, (
                    f"{TEMPLATES_TABLE} columns mismatch: "
                    f"missing={EXPECTED_COLUMNS - cols}, extra={cols - EXPECTED_COLUMNS}"
                )
                assert await _rls_enabled(session, TEMPLATES_TABLE), (
                    f"row-level security must be ENABLED on {TEMPLATES_TABLE}"
                )
                assert await _policy_exists(
                    session, TEMPLATES_TABLE, TENANT_ISOLATION_POLICY
                ), (
                    f"the {TENANT_ISOLATION_POLICY} policy must exist on "
                    f"{TEMPLATES_TABLE}"
                )
        finally:
            await engine.dispose()

    asyncio.run(_check())


# ===========================================================================
# Test 3 — 0234's DDL is idempotent on re-run.
# ===========================================================================

# The transactional body of migration 0234 — every statement guarded so a
# re-run on the already-applied head is a no-op.
_TABLE_DDL = (
    """
    CREATE TABLE IF NOT EXISTS esign_field_templates (
        id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        org_id         uuid NOT NULL,
        name           text NOT NULL,
        agreement_type text NULL,
        fields         jsonb NOT NULL,
        roles          jsonb NOT NULL,
        created_at     timestamptz NOT NULL DEFAULT now(),
        updated_at     timestamptz NOT NULL DEFAULT now(),
        created_by     uuid NULL
    )
    """,
    "ALTER TABLE esign_field_templates ENABLE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS tenant_isolation ON esign_field_templates",
    """
    CREATE POLICY tenant_isolation ON esign_field_templates
        USING (org_id = current_setting('app.current_org_id', true)::uuid)
        WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid)
    """,
)


async def _run_0234_ddl_twice() -> None:
    # CONCURRENTLY DDL cannot run inside a transaction — use an AUTOCOMMIT engine
    # for both the table/policy body and the index statements.
    engine = create_async_engine(
        app_settings.database_url, isolation_level="AUTOCOMMIT"
    )
    try:
        # Pull the CONCURRENTLY index statements straight from the migration so
        # the test never drifts from the real DDL.
        import importlib.util
        import sys
        from pathlib import Path

        path = (
            Path(__file__).resolve().parent.parent
            / "alembic"
            / "versions"
            / MIGRATION_FILENAME
        )
        module_name = f"_mig_{uuid.uuid4().hex}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
        index_statements = [sql for _desc, sql in mod._UPGRADE_INDEXES]

        async with engine.connect() as conn:
            for _ in range(2):
                for stmt in _TABLE_DDL:
                    await conn.execute(sa.text(stmt))
                for sql in index_statements:
                    await conn.execute(sa.text(sql))
    finally:
        await engine.dispose()


def test_esign_field_templates_migration_is_idempotent() -> None:
    """Re-running migration 0234's table/RLS body and its CONCURRENTLY index
    statements does not error and leaves the table + both indexes present.

    **Validates: Requirements 17.3, 17.4**
    """
    _skip_unless_db()
    _run_alembic("upgrade", "head")
    asyncio.run(_run_0234_ddl_twice())

    async def _check() -> None:
        engine, factory = await _make_factory()
        try:
            async with factory() as session:
                assert await _table_exists(session, TEMPLATES_TABLE)
                for index in TEMPLATES_INDEXES:
                    assert await _index_exists(session, index), (
                        f"{index} must remain after re-running 0234's DDL"
                    )
        finally:
            await engine.dispose()

    asyncio.run(_check())


# ===========================================================================
# Test 4 — RLS isolation smoke on esign_field_templates (R17.3, R17.4).
# ===========================================================================


async def _set_org_context(session: AsyncSession, org_id: uuid.UUID) -> None:
    await session.execute(
        sa.text("SELECT set_config('app.current_org_id', :oid, true)"),
        {"oid": str(org_id)},
    )


async def _visible_ids(
    session: AsyncSession, ids: tuple[uuid.UUID, uuid.UUID]
) -> set[str]:
    result = await session.execute(
        sa.text(
            "SELECT id FROM esign_field_templates WHERE id IN (:a, :b)"
        ),
        {"a": str(ids[0]), "b": str(ids[1])},
    )
    return {str(row[0]) for row in result.fetchall()}


async def _insert_template(
    session: AsyncSession, tpl_id: uuid.UUID, org_id: uuid.UUID
) -> None:
    await session.execute(
        sa.text(
            "INSERT INTO esign_field_templates "
            "(id, org_id, name, agreement_type, fields, roles) "
            "VALUES (:id, :org, :name, 'nda', "
            " CAST(:fields AS jsonb), CAST(:roles AS jsonb))"
        ),
        {
            "id": str(tpl_id),
            "org": str(org_id),
            "name": "Standard NDA",
            "fields": "[]",
            "roles": "[]",
        },
    )


async def _run_rls_smoke() -> None:
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()

    # index 0 = org A's row, index 1 = org B's row.
    tpl_ids = (uuid.uuid4(), uuid.uuid4())

    role_name = f"esign_tpl_rls_smoke_{uuid.uuid4().hex}"
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
                await session.execute(
                    sa.text(f"GRANT SELECT ON esign_field_templates TO {qrole}")
                )

                # --- 2. Seed one template for org A and one for org B (as the
                #        superuser, so the inserts themselves are not filtered).
                await _insert_template(session, tpl_ids[0], org_a)
                await _insert_template(session, tpl_ids[1], org_b)
                await session.flush()

                # --- 3. Control: as the superuser, BOTH rows are visible — RLS
                #        is bypassed for superusers, proving the isolation in
                #        step 4 is the policy acting (and that the test would
                #        fail if RLS were off).
                await _set_org_context(session, org_a)
                visible = await _visible_ids(session, tpl_ids)
                assert visible == {str(tpl_ids[0]), str(tpl_ids[1])}, (
                    "control failed: the superuser should see BOTH org rows "
                    f"(RLS bypassed for superusers); got {visible}"
                )

                # --- 4a. As the NON-superuser role, org A context: only org A's
                #         template is visible; org B's is NOT returned.
                await _set_org_context(session, org_a)
                await session.execute(sa.text(f"SET LOCAL ROLE {qrole}"))
                try:
                    under_a = await _visible_ids(session, tpl_ids)
                finally:
                    await session.execute(sa.text("RESET ROLE"))

                assert under_a == {str(tpl_ids[0])}, (
                    "with org A context the non-superuser role must see exactly "
                    f"org A's template; got {under_a}"
                )

                # --- 4b. Mirror: org B context, only org B is visible.
                await _set_org_context(session, org_b)
                await session.execute(sa.text(f"SET LOCAL ROLE {qrole}"))
                try:
                    under_b = await _visible_ids(session, tpl_ids)
                finally:
                    await session.execute(sa.text("RESET ROLE"))

                assert under_b == {str(tpl_ids[1])}, (
                    "with org B context the non-superuser role must see exactly "
                    f"org B's template; got {under_b}"
                )
            finally:
                # Never persist — drops the throwaway role, the seeded rows, and
                # the transaction-local GUC all in one rollback.
                await session.rollback()
    finally:
        await engine.dispose()


def test_esign_field_templates_rls_isolates_other_org() -> None:
    """R17.3/R17.4: with app.current_org_id = org A, org B's
    esign_field_templates row is not visible (and vice versa) — the
    tenant_isolation policy enforces per-org scoping.

    **Validates: Requirements 17.3, 17.4**
    """
    _skip_unless_db()
    asyncio.run(_run_rls_smoke())
