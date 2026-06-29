"""Append-only audit retention test for ``audit_log`` (spec task 7.7).

Proves that the ``audit_log`` table is **append-only** — it rejects ``UPDATE``
and ``DELETE`` for the application's runtime DB role — so the recorded history
of tax-configuration changes (platform saves, org overrides, resets, and
access-denied entries written by the payroll-tax feature) can never be silently
altered or erased after the fact (Req 10.3).

The immutability is enforced by migration ``0008`` via::

    REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC

so the app role may only ``INSERT`` (append) and ``SELECT`` (read history), but
not ``UPDATE`` or ``DELETE`` existing rows.

Why this test does more than a naive update+delete
---------------------------------------------------
The test database connection is the ``postgres`` **superuser** (see
``docker-compose.yml``). PostgreSQL **always bypasses table privileges for
superusers and for a table's owner** — so a naive "insert a row then UPDATE /
DELETE it" performed on the test connection would *succeed* and demonstrate
nothing about the ``REVOKE`` (it would spuriously pass the writes). The design
explicitly calls this out: the append-only guarantee for Req 10.3 only holds
when the app connects as a **non-owner, non-superuser** role.

To exercise the grant model as written, this test — inside a single transaction
that is **rolled back** at the end (so nothing persists) — :

1. creates a throwaway **non-superuser** role and grants it exactly the
   privileges the application runtime role is expected to hold on ``audit_log``:
   ``SELECT`` and ``INSERT`` only (the ``REVOKE ... FROM PUBLIC`` means it gets
   **no** ``UPDATE``/``DELETE``);
2. inserts (as the superuser) a target ``audit_log`` row to act on — a
   representative ``payroll_tax.platform.updated`` configuration-change entry;
3. **role sanity check** — confirms the throwaway role is genuinely
   ``NOSUPERUSER`` (otherwise the rejections below would be meaningless because
   a superuser bypasses the grant);
4. ``SET LOCAL ROLE`` to the non-superuser role and asserts:
   - ``SELECT`` of the target row **succeeds** (history is readable and the row
     exists — so the failures below are about privilege, not a missing row),
   - ``INSERT`` of a new entry **succeeds** (the log is append-able),
   - ``UPDATE`` of the target row is **rejected** with a permission error,
   - ``DELETE`` of the target row is **rejected** with a permission error.

Each forbidden write runs inside its own ``SAVEPOINT`` (``begin_nested``) so the
aborted-transaction state it produces is rolled back to the savepoint and the
test can continue to the next assertion. The whole outer transaction is rolled
back in ``finally``, so the throwaway role, the seeded rows, and the role
context all vanish and nothing persists.

**Validates: Requirements 10.3**

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings``. When Postgres is unreachable the test skips rather
  than fails red, matching the other DB-backed tests in this repo
  (e.g. ``tests/test_payroll_tax_rls_smoke.py``).
- Backend tests run via ``docker compose exec app python -m pytest``.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

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
# DB-backed tests in this repo (e.g. tests/test_payroll_tax_rls_smoke.py).
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
        pytest.skip(f"Postgres not reachable for audit append-only test: {exc}")


def _is_permission_error(exc: BaseException) -> bool:
    """True if ``exc`` (or its cause chain) is a Postgres insufficient-privilege
    error (SQLSTATE 42501 / "permission denied").

    Driver-agnostic: inspects the asyncpg ``sqlstate`` attribute when present
    and falls back to the rendered message text.
    """
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        sqlstate = getattr(cur, "sqlstate", None) or getattr(cur, "pgcode", None)
        if sqlstate == "42501":
            return True
        if "permission denied" in str(cur).lower():
            return True
        cur = cur.__cause__ or cur.__context__
    return False


async def _insert_audit_row(session: AsyncSession, entry_id: uuid.UUID) -> None:
    """INSERT a representative tax-config-change ``audit_log`` row (as the
    superuser), mirroring ``app.core.audit.write_audit_log``'s column set."""
    await session.execute(
        sa.text(
            """
            INSERT INTO audit_log (
                id, org_id, user_id, action, entity_type, entity_id,
                before_value, after_value, ip_address, device_info, created_at
            ) VALUES (
                :id, NULL, NULL, :action, :entity_type, NULL,
                NULL, CAST(:after AS jsonb), NULL, NULL, :created_at
            )
            """
        ),
        {
            "id": str(entry_id),
            "action": "payroll_tax.platform.updated",
            "entity_type": "platform_tax_default",
            "after": '{"acc_levy_rate": "0.0153"}',
            "created_at": datetime.now(timezone.utc),
        },
    )


async def _run_append_only() -> None:
    target_id = uuid.uuid4()

    # A throwaway, non-superuser role granted exactly the application runtime
    # privileges on audit_log: SELECT + INSERT, but NOT UPDATE/DELETE (those are
    # REVOKEd FROM PUBLIC by migration 0008). The name is built from a uuid hex
    # (alphanumeric only) so interpolating it into the un-parameterisable
    # CREATE ROLE / SET ROLE statements is injection-safe.
    role_name = f"audit_append_only_{uuid.uuid4().hex}"
    qrole = f'"{role_name}"'

    engine, factory = await _make_factory()
    await _skip_if_no_db(engine)
    try:
        async with factory() as session:
            try:
                # --- 1. Throwaway non-superuser role with the app's grant model
                #        on audit_log (SELECT + INSERT only). Rolled back later.
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
                    sa.text(f"GRANT SELECT, INSERT ON audit_log TO {qrole}")
                )

                # --- 2. Seed the target audit row (as superuser, unfiltered).
                await _insert_audit_row(session, target_id)
                await session.flush()

                # --- 3. Role sanity check: the throwaway role MUST be a
                #        non-superuser, otherwise the rejections below would be
                #        meaningless (a superuser bypasses table privileges).
                rolsuper = await session.scalar(
                    sa.text("SELECT rolsuper FROM pg_roles WHERE rolname = :n"),
                    {"n": role_name},
                )
                assert rolsuper is False, (
                    "test misconfigured: the throwaway role must be NOSUPERUSER "
                    "or the append-only assertion proves nothing (superusers "
                    f"bypass the REVOKE); rolsuper={rolsuper!r}"
                )

                # --- 4a. As the non-owner role: SELECT succeeds (history is
                #         readable, and the target row exists — so the UPDATE /
                #         DELETE failures below are about privilege, not a
                #         missing row).
                await session.execute(sa.text(f"SET LOCAL ROLE {qrole}"))
                try:
                    visible = await session.scalar(
                        sa.text(
                            "SELECT count(*) FROM audit_log WHERE id = :id"
                        ),
                        {"id": str(target_id)},
                    )
                    assert visible == 1, (
                        "the non-owner role must be able to SELECT (read) the "
                        f"seeded audit_log row; count={visible!r}"
                    )

                    # --- 4b. INSERT (append) succeeds — the log is append-able.
                    appended_id = uuid.uuid4()
                    await session.execute(
                        sa.text(
                            """
                            INSERT INTO audit_log (
                                id, org_id, user_id, action, entity_type,
                                entity_id, before_value, after_value,
                                ip_address, device_info, created_at
                            ) VALUES (
                                :id, NULL, NULL, :action, :etype, NULL,
                                NULL, NULL, NULL, NULL, :created_at
                            )
                            """
                        ),
                        {
                            "id": str(appended_id),
                            "action": "payroll_tax.org.updated",
                            "etype": "org_tax_settings",
                            "created_at": datetime.now(timezone.utc),
                        },
                    )
                finally:
                    await session.execute(sa.text("RESET ROLE"))

                # --- 4c. UPDATE is rejected for the non-owner role (append-only).
                with pytest.raises(Exception) as update_exc:  # noqa: PT011
                    async with session.begin_nested():
                        await session.execute(sa.text(f"SET LOCAL ROLE {qrole}"))
                        await session.execute(
                            sa.text(
                                "UPDATE audit_log SET action = :a WHERE id = :id"
                            ),
                            {"a": "tampered", "id": str(target_id)},
                        )
                assert _is_permission_error(update_exc.value), (
                    "UPDATE on audit_log must be rejected with a permission "
                    "error for the app runtime role (append-only retention, "
                    f"Req 10.3); got: {update_exc.value!r}"
                )

                # --- 4d. DELETE is rejected for the non-owner role (append-only).
                with pytest.raises(Exception) as delete_exc:  # noqa: PT011
                    async with session.begin_nested():
                        await session.execute(sa.text(f"SET LOCAL ROLE {qrole}"))
                        await session.execute(
                            sa.text("DELETE FROM audit_log WHERE id = :id"),
                            {"id": str(target_id)},
                        )
                assert _is_permission_error(delete_exc.value), (
                    "DELETE on audit_log must be rejected with a permission "
                    "error for the app runtime role (append-only retention, "
                    f"Req 10.3); got: {delete_exc.value!r}"
                )
            finally:
                # Never persist — drops the throwaway role, the seeded rows, and
                # the transaction-local role context all in one rollback.
                await session.rollback()
    finally:
        await engine.dispose()


def test_audit_log_is_append_only_rejects_update_and_delete() -> None:
    """Req 10.3: audit_log rejects UPDATE and DELETE for the app's non-owner
    runtime role, so tax-config change history is retained (append-only)."""
    asyncio.run(_run_append_only())
