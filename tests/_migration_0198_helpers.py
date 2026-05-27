"""Shared helpers for the Phase 8b migration test suite (revision 0198).

This module is **not** itself a pytest test module — it is imported by the
four test files that exercise
``alembic/versions/2026_05_27_1200-0198_migrate_legacy_smtp_to_email_provider.py``
(tasks 8.3, 8.4, 8.5, 8.6 of the email-provider-unification spec).

Why drive the migration directly instead of via ``alembic.command.upgrade``?
We need to:
  * pre-seed integration_configs[smtp] with a specific ``updated_at`` (8.5),
  * pre-seed email_providers with credentials_set=True (8.4),
  * patch the migration's lock-timeout helper to make 8.6 finish in < 1s,
  * inspect database state between upgrade and downgrade (8.3),
all on a real Postgres database (the migration uses ``pg_advisory_lock``,
``hashtext``, ``ON CONFLICT (name)``, ``jsonb`` casts, and ``interval`` —
SQLite-style mocks cannot exercise these).

We achieve this by loading the migration module via ``importlib`` and
invoking its ``upgrade()`` / ``downgrade()`` functions inside an Alembic
``MigrationContext`` bound to a real async connection (``run_sync`` bridge
matches the pattern ``alembic/env.py`` uses). ``op.get_bind()`` then
resolves to that real connection.

A real Postgres test environment is required. When the configured
``database_url`` is unreachable the helper raises ``pytest.skip(...)`` so
CI runs without a DB simply skip these tests rather than failing
spuriously — but the suite is wired into the Phase 8b scoped test list at
[`tasks.md`](../.kiro/specs/email-provider-unification/tasks.md) and
SHOULD run in any environment that runs Phase 8b's other migration
tests.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType
from typing import Any, AsyncIterator, Awaitable, Callable

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    create_async_engine,
)

from app.config import settings as app_settings
from app.core.encryption import envelope_decrypt_str, envelope_encrypt


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIGRATION_FILENAME = "2026_05_27_1200-0198_migrate_legacy_smtp_to_email_provider.py"
"""Filename of the migration under test inside ``alembic/versions/``."""


# ---------------------------------------------------------------------------
# Loading the migration module
# ---------------------------------------------------------------------------

def load_migration_module() -> ModuleType:
    """Load the 0198 migration via importlib.

    Returns a fresh module object on each call so tests that patch
    attributes (e.g. ``_acquire_advisory_lock`` for the lock-timeout
    test) get isolation. The module is registered in ``sys.modules``
    under a unique name so the loader can satisfy any internal
    cross-references the migration body might add later.
    """
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / MIGRATION_FILENAME
    if not path.exists():  # pragma: no cover — defensive
        raise FileNotFoundError(f"Migration not found at {path}")

    module_name = f"_mig_0198_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:  # pragma: no cover — defensive
        raise RuntimeError(f"Could not build importlib spec for {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Async engine + skip-if-unreachable helper
# ---------------------------------------------------------------------------

def _build_engine() -> AsyncEngine:
    """Build a fresh async engine with a tiny pool, suitable for tests."""
    return create_async_engine(
        app_settings.database_url,
        echo=False,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
    )


async def skip_if_db_unreachable(engine: AsyncEngine) -> None:
    """Skip the calling test if Postgres is not reachable.

    Phase 8b migrations require real PG (advisory locks, ``hashtext``,
    ``interval``). A unit-test environment without a running database
    cannot meaningfully exercise this migration, so we fall back to
    ``pytest.skip`` rather than producing red CI noise.
    """
    try:
        async with engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — any connect failure means skip
        await engine.dispose()
        pytest.skip(f"Postgres not reachable for migration test: {exc}")


# ---------------------------------------------------------------------------
# Driving the migration through an Alembic MigrationContext
# ---------------------------------------------------------------------------

def _invoke_migration_function(sync_conn: Connection, migration: ModuleType, direction: str) -> None:
    """Run ``migration.upgrade()`` or ``migration.downgrade()`` against ``sync_conn``.

    The Alembic ``Operations`` proxy is bound to a real
    ``MigrationContext`` so that calls to ``op.get_bind()`` and
    ``op.execute(...)`` inside the migration resolve to the live
    connection.

    Note: this is the same wiring ``alembic/env.py`` uses inside
    ``do_run_migrations``; we just skip the surrounding
    ``begin_transaction()`` since we manage the transaction at the
    async-connection layer.
    """
    ctx = MigrationContext.configure(connection=sync_conn)
    with Operations.context(ctx):
        fn: Callable[[], None] = getattr(migration, direction)
        fn()


async def run_migration_upgrade(
    engine: AsyncEngine, migration: ModuleType
) -> None:
    """Run ``migration.upgrade()`` against ``engine`` and commit."""
    async with engine.connect() as conn:
        await conn.run_sync(_invoke_migration_function, migration, "upgrade")
        await conn.commit()


async def run_migration_downgrade(
    engine: AsyncEngine, migration: ModuleType
) -> None:
    """Run ``migration.downgrade()`` against ``engine`` and commit."""
    async with engine.connect() as conn:
        await conn.run_sync(_invoke_migration_function, migration, "downgrade")
        await conn.commit()


# ---------------------------------------------------------------------------
# Engine context manager
# ---------------------------------------------------------------------------

@asynccontextmanager
async def migration_engine() -> AsyncIterator[AsyncEngine]:
    """Yield a fresh engine and dispose it cleanly afterwards.

    Using a context manager keeps the per-test pool isolated and avoids
    the "attached to a different loop" pitfall that bit other migration
    tests in this repo (see ``test_invoice_vehicle_fk_preservation.py``
    for the same workaround).
    """
    engine = _build_engine()
    try:
        await skip_if_db_unreachable(engine)
        yield engine
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Email provider snapshotting
# ---------------------------------------------------------------------------

ProviderSnapshot = dict[str, Any]


async def snapshot_provider(engine: AsyncEngine, provider_key: str) -> ProviderSnapshot | None:
    """Capture the current state of an ``email_providers`` row.

    Returns ``None`` if the row does not exist (which would itself be a
    setup error — the seed migration 0065 inserts every supported
    provider_key — so callers can assert truthy).
    """
    async with engine.connect() as conn:
        result = await conn.execute(
            sa.text(
                "SELECT credentials_encrypted, credentials_set, is_active, "
                "priority, config, smtp_host, smtp_port, smtp_encryption "
                "FROM email_providers WHERE provider_key = :pk"
            ),
            {"pk": provider_key},
        )
        row = result.first()
        if row is None:
            return None
        return {
            "credentials_encrypted": row[0],
            "credentials_set": row[1],
            "is_active": row[2],
            "priority": row[3],
            "config": row[4],
            "smtp_host": row[5],
            "smtp_port": row[6],
            "smtp_encryption": row[7],
        }


async def restore_provider(
    engine: AsyncEngine, provider_key: str, snapshot: ProviderSnapshot
) -> None:
    """Restore an ``email_providers`` row to a previously-captured state.

    Used in test teardown so the migration's mutations do not leak into
    other tests sharing the same Postgres instance (the dev/standby
    setup runs many test suites against ``invoicing-postgres-1``).
    """
    config_json = (
        json.dumps(snapshot["config"]) if snapshot["config"] is not None else None
    )
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE email_providers SET "
                "credentials_encrypted = :credentials_encrypted, "
                "credentials_set = :credentials_set, "
                "is_active = :is_active, "
                "priority = :priority, "
                "config = CAST(:config AS jsonb), "
                "smtp_host = :smtp_host, "
                "smtp_port = :smtp_port, "
                "smtp_encryption = :smtp_encryption "
                "WHERE provider_key = :pk"
            ),
            {
                "pk": provider_key,
                "credentials_encrypted": snapshot["credentials_encrypted"],
                "credentials_set": snapshot["credentials_set"],
                "is_active": snapshot["is_active"],
                "priority": snapshot["priority"],
                "config": config_json,
                "smtp_host": snapshot["smtp_host"],
                "smtp_port": snapshot["smtp_port"],
                "smtp_encryption": snapshot["smtp_encryption"],
            },
        )


# ---------------------------------------------------------------------------
# Legacy SMTP row helpers
# ---------------------------------------------------------------------------

async def snapshot_legacy_row(engine: AsyncEngine) -> dict | None:
    """Capture the current ``integration_configs[smtp]`` row, if any."""
    async with engine.connect() as conn:
        result = await conn.execute(
            sa.text(
                "SELECT id, config_encrypted, is_verified, updated_at "
                "FROM integration_configs WHERE name = 'smtp'"
            )
        )
        row = result.first()
        if row is None:
            return None
        return {
            "id": row[0],
            "config_encrypted": row[1],
            "is_verified": row[2],
            "updated_at": row[3],
        }


async def delete_legacy_row(engine: AsyncEngine) -> None:
    """Remove any ``integration_configs[smtp]`` row."""
    async with engine.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM integration_configs WHERE name = 'smtp'")
        )


async def restore_legacy_row(engine: AsyncEngine, snapshot: dict | None) -> None:
    """Restore (or clear) the ``integration_configs[smtp]`` row.

    If ``snapshot`` is ``None`` the row is removed (matching the
    dev-environment baseline where the legacy SMTP row has not been
    written). Otherwise an upsert reinstates the captured columns.
    """
    if snapshot is None:
        await delete_legacy_row(engine)
        return
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO integration_configs (id, name, config_encrypted, is_verified, updated_at) "
                "VALUES (:id, 'smtp', :config_encrypted, :is_verified, :updated_at) "
                "ON CONFLICT (name) DO UPDATE SET "
                "config_encrypted = EXCLUDED.config_encrypted, "
                "is_verified = EXCLUDED.is_verified, "
                "updated_at = EXCLUDED.updated_at"
            ),
            {
                "id": snapshot["id"],
                "config_encrypted": snapshot["config_encrypted"],
                "is_verified": snapshot["is_verified"],
                "updated_at": snapshot["updated_at"],
            },
        )


async def seed_legacy_smtp(
    engine: AsyncEngine,
    *,
    legacy_config: dict,
    is_verified: bool = True,
    updated_at_offset_seconds: int = 60 * 60,
) -> None:
    """Insert (or replace) the ``integration_configs[smtp]`` row.

    Args:
        engine: AsyncEngine connected to the test DB.
        legacy_config: Plain-dict payload that the migration will
            ``envelope_decrypt_str`` and parse — must include
            ``provider`` plus the credentials shape the migration
            recognises (``api_key`` for REST, ``username``/``password``
            for SMTP).
        is_verified: Initial ``is_verified`` flag. The migration must
            NOT carry this onto ``email_providers`` (Req 15.8).
        updated_at_offset_seconds: How far in the past ``updated_at``
            should be set, in seconds. The migration's recent-write
            guard at ~5 minutes means callers wanting the guard NOT
            to trip should pass at least ``301``; tests for the
            guard pass a smaller value (e.g. ``60``).
    """
    encrypted_blob = envelope_encrypt(json.dumps(legacy_config))
    async with engine.begin() as conn:
        # Upsert keyed on the unique ``name`` constraint.
        await conn.execute(
            sa.text(
                "INSERT INTO integration_configs (name, config_encrypted, is_verified, updated_at) "
                "VALUES ('smtp', :blob, :is_verified, "
                "       now() - make_interval(secs => :offset)) "
                "ON CONFLICT (name) DO UPDATE SET "
                "config_encrypted = EXCLUDED.config_encrypted, "
                "is_verified = EXCLUDED.is_verified, "
                "updated_at = EXCLUDED.updated_at"
            ),
            {
                "blob": encrypted_blob,
                "is_verified": is_verified,
                "offset": updated_at_offset_seconds,
            },
        )


# ---------------------------------------------------------------------------
# Decryption helper for assertions
# ---------------------------------------------------------------------------

def decrypt_credentials(blob: bytes | memoryview | None) -> dict:
    """Decrypt a ``credentials_encrypted`` blob and parse it as JSON.

    Returns an empty dict for ``None``/empty inputs so test assertions
    can be terse (``assert decrypt_credentials(...).get("api_key") == "x"``).
    """
    if not blob:
        return {}
    return json.loads(envelope_decrypt_str(bytes(blob)))


# ---------------------------------------------------------------------------
# Direct-SQL helpers used by the lock-timeout test
# ---------------------------------------------------------------------------

ADVISORY_LOCK_SQL = "SELECT pg_advisory_lock(hashtext('email_provider_rotate'))"
ADVISORY_UNLOCK_SQL = "SELECT pg_advisory_unlock(hashtext('email_provider_rotate'))"


async def acquire_external_advisory_lock(conn: AsyncConnection) -> None:
    """Hold the email-provider advisory lock from a separate connection.

    Used by the 8.6 test to simulate ``rotate_keys.py`` running while
    the migration is invoked. Caller is responsible for releasing the
    lock with ``release_external_advisory_lock`` and for closing the
    connection.
    """
    await conn.execute(sa.text(ADVISORY_LOCK_SQL))


async def release_external_advisory_lock(conn: AsyncConnection) -> None:
    """Release the email-provider advisory lock previously acquired."""
    await conn.execute(sa.text(ADVISORY_UNLOCK_SQL))
