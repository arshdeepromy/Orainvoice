"""Smoke test: cloud-backup-restore migrations apply and tables are platform/global.

Task 1.5 (cloud-backup-restore) — a single-execution **smoke** test. This is
explicitly NOT a property-based test: it runs ``alembic upgrade head`` exactly
once against a real Postgres database and asserts the resulting schema.

The Cloud Backup & Restore subsystem is a platform-level DR/BCP feature. Its
tables are deliberately **platform/global**: they carry no ``org_id`` column and
no Row-Level Security (RLS) policy, because access is gated at the API layer via
``require_role('global_admin')`` rather than by per-tenant RLS (matching how
``audit_log``, ``error_log`` and the HA tables work). This test is the guard
that those two invariants hold after the migrations apply.

After ``alembic upgrade head`` it asserts, for all 11 backup_restore tables:
  * every table exists (the table-creation migration 0221 ran),
  * none carries an ``org_id`` column,
  * none has any RLS policy (``pg_policies`` is empty for them), and RLS is
    neither enabled nor forced on the relation.

A real Postgres test database is required. When the configured
``settings.database_url`` is unreachable the test skips (matching the repo's
other migration tests, e.g. ``tests/_migration_0198_helpers.py``) rather than
failing spuriously in a DB-less environment.

Validates: Requirements 1.1
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings

# Repo root (…/Invoicing) — the cwd alembic must run from.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# The 11 platform/global tables created by migration 0221.
BACKUP_RESTORE_TABLES: list[str] = [
    "backup_destinations",
    "backup_residency_ack",
    "backup_key_versions",
    "backup_config",
    "backups",
    "backup_destination_copies",
    "backup_blobs",
    "blob_refcounts",
    "backup_jobs",
    "restore_jobs",
    "restore_rehearsals",
]


def _redacted_target(url: str) -> str:
    """Return the ``host:port/db`` portion of a URL for safe log/skip messages."""
    return url.split("@")[-1]


def _db_reachable(url: str) -> bool:
    """Return True if a trivial ``SELECT 1`` succeeds against ``url``."""

    async def _check() -> bool:
        engine = create_async_engine(url, pool_pre_ping=True)
        try:
            async with engine.connect() as conn:
                await conn.execute(sa.text("SELECT 1"))
            return True
        except Exception:  # noqa: BLE001 — any connect failure means "skip"
            return False
        finally:
            await engine.dispose()

    return asyncio.run(_check())


async def _gather_schema(
    url: str,
) -> tuple[set[str], set[str], set[str], set[str]]:
    """Introspect the live schema for the backup_restore tables.

    Returns a 4-tuple of sets:
      (existing tables, tables with an ``org_id`` column,
       tables with any RLS policy, tables with RLS enabled/forced).
    """
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            existing = (
                await conn.execute(
                    sa.text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' "
                        "AND table_name = ANY(:names)"
                    ),
                    {"names": BACKUP_RESTORE_TABLES},
                )
            ).scalars().all()

            org_id_cols = (
                await conn.execute(
                    sa.text(
                        "SELECT table_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' "
                        "AND column_name = 'org_id' "
                        "AND table_name = ANY(:names)"
                    ),
                    {"names": BACKUP_RESTORE_TABLES},
                )
            ).scalars().all()

            policies = (
                await conn.execute(
                    sa.text(
                        "SELECT tablename FROM pg_policies "
                        "WHERE schemaname = 'public' "
                        "AND tablename = ANY(:names)"
                    ),
                    {"names": BACKUP_RESTORE_TABLES},
                )
            ).scalars().all()

            rls_enabled = (
                await conn.execute(
                    sa.text(
                        "SELECT c.relname FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname = 'public' "
                        "AND c.relname = ANY(:names) "
                        "AND (c.relrowsecurity OR c.relforcerowsecurity)"
                    ),
                    {"names": BACKUP_RESTORE_TABLES},
                )
            ).scalars().all()

        return set(existing), set(org_id_cols), set(policies), set(rls_enabled)
    finally:
        await engine.dispose()


def test_backup_restore_migrations_apply_and_tables_are_platform_global() -> None:
    """``alembic upgrade head`` creates all 11 tables, none org-scoped, none RLS.

    Validates: Requirements 1.1
    """
    url = settings.database_url

    if not _db_reachable(url):
        pytest.skip(
            "Postgres not reachable at "
            f"{_redacted_target(url)} for the migration smoke test"
        )

    # Run the real migrations. The backup_restore migrations are idempotent
    # (``CREATE TABLE IF NOT EXISTS`` / ``CREATE INDEX CONCURRENTLY IF NOT
    # EXISTS``), so this is safe whether or not the DB is already at head.
    # Pass the resolved URL through to the child so it targets the same DB
    # this test introspects.
    env = dict(os.environ)
    env["DATABASE_URL"] = url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "`alembic upgrade head` failed:\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )

    existing, org_id_cols, policies, rls_enabled = asyncio.run(_gather_schema(url))

    # 1) All 11 tables exist after upgrade.
    missing = set(BACKUP_RESTORE_TABLES) - existing
    assert not missing, (
        "alembic upgrade head did not create the expected backup_restore "
        f"tables: {sorted(missing)}"
    )

    # 2) No table carries an org_id column (platform/global, not tenant-scoped).
    assert not org_id_cols, (
        "platform/global backup_restore tables must not carry an org_id "
        f"column, but these do: {sorted(org_id_cols)}"
    )

    # 3) No table has an RLS policy …
    assert not policies, (
        "platform/global backup_restore tables must have no RLS policy, but "
        f"pg_policies reports policies on: {sorted(policies)}"
    )

    # … and RLS is neither enabled nor forced on any of them.
    assert not rls_enabled, (
        "platform/global backup_restore tables must not have RLS enabled or "
        f"forced, but these do: {sorted(rls_enabled)}"
    )
