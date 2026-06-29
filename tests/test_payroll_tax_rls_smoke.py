"""RLS smoke test for ``org_tax_settings`` tenant isolation (spec task 5.3).

Proves that the ``tenant_isolation`` row-level-security policy created by
migration ``0231_payroll_tax_settings`` genuinely scopes ``org_tax_settings``
reads to the organisation named by ``app.current_org_id``: with the GUC set to
org A, org B's row is **not** visible (Req 3.4).

Why this test does more than a naive insert+select
---------------------------------------------------
The test database connection is the ``postgres`` **superuser** (see
``docker-compose.yml`` and ``docs/PERFORMANCE_AUDIT.md`` Theme A — the app
currently connects as ``postgres`` and the project's RLS posture is ``ENABLE``,
not ``FORCE``). PostgreSQL **always bypasses RLS for superusers** (and for a
table's owner under plain ``ENABLE``). So a naive "set ``app.current_org_id`` to
A, insert A and B, select" performed on the test connection would return *both*
rows and demonstrate nothing about the policy.

To exercise the policy as written, this test, inside a single transaction that
is **rolled back** at the end:

1. creates a throwaway **non-superuser** role (rolled back with the
   transaction), grants it ``SELECT`` on ``org_tax_settings``;
2. inserts an ``org_tax_settings`` row for org A and one for org B (as the
   superuser, so the inserts are not themselves filtered);
3. **control assertion** — as the superuser, with ``app.current_org_id`` = A,
   selects and confirms *both* rows are visible. This proves RLS is bypassed for
   the superuser and therefore that the isolation seen in step 4 is the *policy*
   acting, not a ``WHERE`` clause. If RLS were off, step 4 would see both rows
   exactly like this control does;
4. ``SET LOCAL ROLE`` to the non-superuser role and, with
   ``app.current_org_id`` = A, selects and asserts **only org A's row is
   visible — org B's row is not returned**; then repeats with the GUC = B and
   asserts the mirror (only B visible, A hidden).

Everything runs in a rolled-back transaction, so the throwaway role, the seeded
rows, and the GUC all vanish and nothing persists.

**Validates: Requirements 3.4**

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings``. When Postgres is unreachable the test skips rather
  than fails red, matching the other DB-backed tests in this repo.
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
# Engine / session helper — fresh engine per test (asyncpg connections are
# bound to the event loop ``asyncio.run`` creates), matching the reference
# DB-backed tests in this repo (e.g. tests/test_payroll_tax_seed_migration.py).
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


async def _skip_if_no_db(engine) -> None:
    try:
        async with engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — any connect failure means skip
        await engine.dispose()
        pytest.skip(f"Postgres not reachable for RLS smoke test: {exc}")


async def _visible_org_ids(
    session: AsyncSession, candidates: tuple[uuid.UUID, uuid.UUID]
) -> set[str]:
    """Return which of ``candidates`` are visible to the current session.

    Filters to just the two org ids this test seeded so unrelated rows on the
    shared dev DB never affect the assertion; what gets filtered *out* by the
    ``tenant_isolation`` policy is the whole point of the test.
    """
    result = await session.execute(
        sa.text(
            "SELECT org_id FROM org_tax_settings "
            "WHERE org_id IN (:a, :b)"
        ),
        {"a": str(candidates[0]), "b": str(candidates[1])},
    )
    return {str(row[0]) for row in result.fetchall()}


async def _set_org_context(session: AsyncSession, org_id: uuid.UUID) -> None:
    """Set the RLS GUC ``app.current_org_id`` for the current transaction."""
    await session.execute(
        sa.text("SELECT set_config('app.current_org_id', :oid, true)"),
        {"oid": str(org_id)},
    )


async def _run_rls_smoke() -> None:
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    candidates = (org_a, org_b)

    # A throwaway, non-superuser role so RLS is actually enforced (the test
    # connection is the postgres superuser, which bypasses RLS). The name is
    # built from a uuid hex (alphanumeric only) so interpolating it into the
    # un-parameterisable CREATE ROLE / SET ROLE statements is injection-safe.
    role_name = f"rls_smoke_{uuid.uuid4().hex}"
    qrole = f'"{role_name}"'

    engine, factory = await _make_factory()
    await _skip_if_no_db(engine)
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
                    sa.text(f"GRANT SELECT ON org_tax_settings TO {qrole}")
                )

                # --- 2. Seed one row for org A and one for org B (as superuser,
                #        so the inserts themselves are not filtered).
                await session.execute(
                    sa.text(
                        "INSERT INTO org_tax_settings (id, org_id, overrides) "
                        "VALUES (:id, :org, '{}'::jsonb)"
                    ),
                    {"id": str(uuid.uuid4()), "org": str(org_a)},
                )
                await session.execute(
                    sa.text(
                        "INSERT INTO org_tax_settings (id, org_id, overrides) "
                        "VALUES (:id, :org, '{}'::jsonb)"
                    ),
                    {"id": str(uuid.uuid4()), "org": str(org_b)},
                )
                await session.flush()

                # --- 3. Control: as the superuser, with org A context, BOTH
                #        rows are visible — RLS is bypassed for superusers, so
                #        this proves the isolation in step 4 is the policy
                #        acting (and that the test would fail if RLS were off).
                await _set_org_context(session, org_a)
                superuser_visible = await _visible_org_ids(session, candidates)
                assert superuser_visible == {str(org_a), str(org_b)}, (
                    "control failed: the superuser test connection should see "
                    "BOTH org rows (RLS is bypassed for superusers); got "
                    f"{superuser_visible}. Without this, step 4 proves nothing."
                )

                # --- 4a. As the NON-superuser role, with org A context: only
                #         org A's row is visible; org B's row is NOT returned.
                await _set_org_context(session, org_a)
                await session.execute(sa.text(f"SET LOCAL ROLE {qrole}"))
                try:
                    visible_under_a = await _visible_org_ids(session, candidates)
                finally:
                    await session.execute(sa.text("RESET ROLE"))

                assert str(org_b) not in visible_under_a, (
                    "tenant isolation breach: org B's org_tax_settings row was "
                    "visible while app.current_org_id was set to org A "
                    f"(visible={visible_under_a})"
                )
                assert visible_under_a == {str(org_a)}, (
                    "with org A context the non-superuser role must see exactly "
                    f"org A's row; got {visible_under_a}"
                )

                # --- 4b. Mirror: with org B context, only org B is visible and
                #         org A is hidden — isolation holds both directions.
                await _set_org_context(session, org_b)
                await session.execute(sa.text(f"SET LOCAL ROLE {qrole}"))
                try:
                    visible_under_b = await _visible_org_ids(session, candidates)
                finally:
                    await session.execute(sa.text("RESET ROLE"))

                assert str(org_a) not in visible_under_b, (
                    "tenant isolation breach: org A's org_tax_settings row was "
                    "visible while app.current_org_id was set to org B "
                    f"(visible={visible_under_b})"
                )
                assert visible_under_b == {str(org_b)}, (
                    "with org B context the non-superuser role must see exactly "
                    f"org B's row; got {visible_under_b}"
                )
            finally:
                # Never persist — drops the throwaway role, the seeded rows, and
                # the transaction-local GUC all in one rollback.
                await session.rollback()
    finally:
        await engine.dispose()


def test_org_tax_settings_rls_isolates_other_org() -> None:
    """Req 3.4: with app.current_org_id = org A, org B's org_tax_settings row
    is not visible — the tenant_isolation policy enforces per-org scoping."""
    asyncio.run(_run_rls_smoke())
