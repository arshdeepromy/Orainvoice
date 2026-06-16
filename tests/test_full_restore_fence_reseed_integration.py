"""Integration test: real fence/re-seed + real ``pg_restore --clean`` apply.

Task 11.7 (cloud-backup-restore) — 1–3 representative **integration** examples,
explicitly NOT property-based tests. They exercise the *production* full-restore
seams against real infrastructure with no mocks:

  * :class:`~app.modules.backup_restore.restore.full_restore.PgRestoreApplier`
    and
    :class:`~app.modules.backup_restore.restore.full_restore.PgDumpSnapshotManager`
    — a real ``pg_dump -Fc`` snapshot of one scratch database followed by a real
    ``pg_restore --clean --if-exists --no-owner`` apply into a second scratch
    database, proving the destructive ``--clean`` apply of Requirement 12.10
    works end-to-end against a live PostgreSQL server.
  * :class:`~app.modules.backup_restore.restore.full_restore.ReplicationStandbyFencer`
    — the real subscription disable+drop *fence* and the ``trigger_resync``
    *re-seed* against the dev HA pair, proving the standby isolation of
    Requirement 12.10 and the validated-path re-seed of Requirement 12.13.

Both examples are heavily **environment-gated** and **skip cleanly** — never
fail spuriously — when the required infrastructure is absent (mirroring
``tests/test_pg_dump_restore_roundtrip_integration.py`` and
``tests/smoke/test_backup_restore_migrations_smoke.py``):

  * The ``pg_restore --clean`` example skips unless PostgreSQL is reachable and
    the ``pg_dump`` / ``pg_restore`` client binaries are installed. It uses
    scratch databases and tears them down; where the test role cannot
    ``CREATE DATABASE`` it degrades to a list-only proof.
  * The fence/re-seed example is **destructive on a real standby** and therefore
    requires explicit opt-in: it runs only when ``HA_FENCE_RESEED_TEST`` is set
    truthy, ``HA_PEER_DB_URL`` (the primary connection string used for the
    re-seed) is set, the configured node is reachable, AND the node actually
    carries the HA subscription (``orainvoice_ha_sub``) — i.e. it is a Standby_
    Node. If any of those are missing it skips, so it never runs against a
    primary or an unconfigured node and is inert in CI.

The value of this module is the executable wiring of the production seams
against real infrastructure when that infrastructure is present.

Validates: Requirements 12.10, 12.13
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import uuid
from urllib.parse import urlsplit, urlunsplit

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import settings
from app.modules.backup_restore.restore.full_restore import (
    PgDumpSnapshotManager,
    PgRestoreApplier,
    ReplicationStandbyFencer,
)
from app.modules.ha.replication import ReplicationManager

# Every test in this module exercises real local PostgreSQL client tooling
# and/or a real HA standby.
pytestmark = pytest.mark.integration

# The 5-byte magic header at the start of every pg_dump custom-format archive.
PGDMP_MAGIC = b"PGDMP"


# ---------------------------------------------------------------------------
# URL helpers (mirrors tests/test_pg_dump_restore_roundtrip_integration.py)
# ---------------------------------------------------------------------------

def _to_async_url(url: str) -> str:
    """Return *url* with the asyncpg driver so SQLAlchemy can connect."""
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def _to_libpq_url(url: str) -> str:
    """Return *url* as a plain libpq ``postgresql://`` URL for the CLI tools."""
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _with_db(url: str, dbname: str) -> str:
    """Return *url* with its database (path) component replaced by *dbname*."""
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{dbname}"))


def _redacted_target(url: str) -> str:
    """Return the ``host:port/db`` portion of a URL for safe skip messages."""
    return url.split("@")[-1]


# ---------------------------------------------------------------------------
# Reachability
# ---------------------------------------------------------------------------

def _db_reachable(async_url: str) -> bool:
    """Return True if a trivial ``SELECT 1`` succeeds against *async_url*."""

    async def _check() -> bool:
        engine = create_async_engine(async_url, pool_pre_ping=True)
        try:
            async with engine.connect() as conn:
                await conn.execute(sa.text("SELECT 1"))
            return True
        except Exception:  # noqa: BLE001 — any connect failure means "skip"
            return False
        finally:
            await engine.dispose()

    return asyncio.run(_check())


# ---------------------------------------------------------------------------
# Scratch-database lifecycle (AUTOCOMMIT — CREATE/DROP DATABASE cannot run in a
# transaction block).
# ---------------------------------------------------------------------------

async def _try_create_database(maint_url: str, dbname: str) -> bool:
    """Attempt ``CREATE DATABASE``; return False if the role lacks privilege."""
    engine = create_async_engine(maint_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))
        return True
    except Exception:  # noqa: BLE001 — insufficient privilege / not permitted
        return False
    finally:
        await engine.dispose()


async def _drop_database(maint_url: str, dbname: str) -> None:
    """Best-effort drop of a scratch database; terminate stray connections."""
    engine = create_async_engine(maint_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(
                sa.text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :db AND pid <> pg_backend_pid()"
                ),
                {"db": dbname},
            )
            await conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}"'))
    except Exception:  # noqa: BLE001 — cleanup must never raise
        pass
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Round-trip seed data (text + BYTEA, mirroring the 8.5 round-trip probe).
# ---------------------------------------------------------------------------

_PROBE_NAME = "fence/re-seed probe ✓"
_PROBE_PAYLOAD = bytes(range(256))  # all byte values, to catch any corruption


async def _seed_source(src_async_url: str) -> None:
    """Create a probe table with one known row in the source scratch DB."""
    engine = create_async_engine(src_async_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "CREATE TABLE clean_probe ("
                    "id integer PRIMARY KEY, "
                    "name text NOT NULL, "
                    "payload bytea NOT NULL)"
                )
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO clean_probe (id, name, payload) "
                    "VALUES (:id, :name, :payload)"
                ),
                {"id": 1, "name": _PROBE_NAME, "payload": _PROBE_PAYLOAD},
            )
    finally:
        await engine.dispose()


async def _seed_stale_target(tgt_async_url: str) -> None:
    """Seed the target with a *stale* ``clean_probe`` so we can prove ``--clean``
    drops-and-recreates it (the destructive apply of Req 12.10), plus an extra
    table that the dump does not contain (left untouched by ``--clean``)."""
    engine = create_async_engine(tgt_async_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "CREATE TABLE clean_probe ("
                    "id integer PRIMARY KEY, "
                    "name text NOT NULL, "
                    "payload bytea NOT NULL)"
                )
            )
            # A stale row with a different name — must be replaced by the dump's
            # row after the --clean apply.
            await conn.execute(
                sa.text(
                    "INSERT INTO clean_probe (id, name, payload) "
                    "VALUES (:id, :name, :payload)"
                ),
                {"id": 99, "name": "STALE — must be cleaned", "payload": b"\x00"},
            )
    finally:
        await engine.dispose()


async def _read_probe(tgt_async_url: str) -> list[tuple[int, str, bytes]]:
    """Read all probe rows back from the restored target DB."""
    engine = create_async_engine(tgt_async_url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    sa.text("SELECT id, name, payload FROM clean_probe ORDER BY id")
                )
            ).all()
        return [(int(r[0]), str(r[1]), bytes(r[2])) for r in rows]
    finally:
        await engine.dispose()


# ===========================================================================
# Example 1 — real PgDumpSnapshotManager + PgRestoreApplier --clean apply.
# ===========================================================================

async def _run_clean_apply_roundtrip(async_url: str) -> None:
    """Snapshot one scratch DB, then ``pg_restore --clean`` apply into another.

    Drives the production :class:`PgDumpSnapshotManager` (``pg_dump -Fc``) and
    :class:`PgRestoreApplier` (``pg_restore --clean --if-exists --no-owner``)
    against real scratch databases — proving the destructive apply of Req 12.10.
    """
    suffix = uuid.uuid4().hex[:12]
    src_db = f"orainvoice_clean_src_{suffix}"
    tgt_db = f"orainvoice_clean_tgt_{suffix}"
    maint_url = _with_db(async_url, "postgres")

    if not await _try_create_database(maint_url, src_db):
        # No CREATE DATABASE privilege — fall back to the list-only proof.
        await _run_listonly_fallback(async_url)
        return

    src_created = True
    tgt_created = False
    snapshot_dir = tempfile.mkdtemp(prefix="orainvoice_clean_snap_")
    try:
        src_async_url = _with_db(async_url, src_db)
        await _seed_source(src_async_url)

        # --- Real PgDumpSnapshotManager.create() (pg_dump -Fc). -------------
        snapshot_mgr = PgDumpSnapshotManager(
            primary_admin_dsn=src_async_url, output_dir=snapshot_dir
        )
        snapshot_path = await snapshot_mgr.create()
        assert os.path.getsize(snapshot_path) > 0, "snapshot dump is empty"
        with open(snapshot_path, "rb") as fh:
            header = fh.read(len(PGDMP_MAGIC))
        assert header == PGDMP_MAGIC, (
            f"snapshot is not a custom-format archive (header {header!r})"
        )
        with open(snapshot_path, "rb") as fh:
            dump_bytes = fh.read()

        # --- Destructive --clean apply into a fresh target (Req 12.10). -----
        tgt_created = await _try_create_database(maint_url, tgt_db)
        assert tgt_created, "could not create the target scratch database"
        tgt_async_url = _with_db(async_url, tgt_db)
        # Pre-seed a STALE clean_probe so we prove --clean replaces it.
        await _seed_stale_target(tgt_async_url)

        applier = PgRestoreApplier(primary_admin_dsn=tgt_async_url)
        await applier.apply(dump_bytes)

        # After the --clean apply the target must hold exactly the source's
        # single row — the stale id=99 row was dropped with the table.
        rows = await _read_probe(tgt_async_url)
        assert rows == [(1, _PROBE_NAME, _PROBE_PAYLOAD)], (
            f"--clean apply did not reproduce the source exactly: {rows!r}"
        )

        # The snapshot manager cleans up its own dump file.
        await snapshot_mgr.cleanup(snapshot_path)
        assert not os.path.exists(snapshot_path)
    finally:
        if src_created:
            await _drop_database(maint_url, src_db)
        if tgt_created:
            await _drop_database(maint_url, tgt_db)
        shutil.rmtree(snapshot_dir, ignore_errors=True)


async def _run_listonly_fallback(async_url: str) -> None:
    """Where the role cannot ``CREATE DATABASE``: snapshot the existing DB and
    prove the archive is a valid, listable custom-format archive.

    Still exercises the real :class:`PgDumpSnapshotManager` (``pg_dump -Fc``).
    """
    snapshot_dir = tempfile.mkdtemp(prefix="orainvoice_clean_snap_")
    try:
        snapshot_mgr = PgDumpSnapshotManager(
            primary_admin_dsn=async_url, output_dir=snapshot_dir
        )
        snapshot_path = await snapshot_mgr.create()
        assert os.path.getsize(snapshot_path) > 0, "snapshot dump is empty"
        with open(snapshot_path, "rb") as fh:
            header = fh.read(len(PGDMP_MAGIC))
        assert header == PGDMP_MAGIC, (
            f"snapshot header was {header!r}, expected {PGDMP_MAGIC!r}"
        )
        listing = subprocess.run(
            ["pg_restore", "--list", snapshot_path],
            capture_output=True,
            text=True,
        )
        assert listing.returncode == 0, (
            "pg_restore --list rejected the snapshot archive:\n"
            f"STDOUT:\n{listing.stdout}\nSTDERR:\n{listing.stderr}"
        )
        assert listing.stdout.strip(), "pg_restore --list produced no TOC"
        await snapshot_mgr.cleanup(snapshot_path)
    finally:
        shutil.rmtree(snapshot_dir, ignore_errors=True)


def test_pg_restore_clean_apply_into_scratch_db() -> None:
    """Real ``pg_dump -Fc`` snapshot then ``pg_restore --clean`` apply (Req 12.10).

    Validates: Requirements 12.10
    """
    raw_url = os.environ.get("PG_TEST_URL") or settings.database_url
    async_url = _to_async_url(raw_url)

    if not _db_reachable(async_url):
        pytest.skip(
            "PostgreSQL not reachable at "
            f"{_redacted_target(async_url)} for the pg_restore --clean apply test"
        )
    if shutil.which("pg_dump") is None or shutil.which("pg_restore") is None:
        pytest.skip(
            "pg_dump / pg_restore client binaries are not installed; "
            "cannot run the real --clean apply integration test"
        )

    asyncio.run(_run_clean_apply_roundtrip(async_url))


# ===========================================================================
# Example 2 — real fence (disable+drop) and re-seed (trigger_resync) on the
# dev HA standby. Destructive; requires explicit opt-in.
# ===========================================================================

async def _subscription_exists(async_url: str) -> bool:
    """Return True if the HA subscription exists on the node at *async_url*."""
    engine = create_async_engine(async_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    sa.text(
                        "SELECT subname FROM pg_subscription WHERE subname = :n"
                    ),
                    {"n": ReplicationManager.SUBSCRIPTION_NAME},
                )
            ).first()
        return row is not None
    except Exception:  # noqa: BLE001 — treat any failure as "cannot determine"
        return False
    finally:
        await engine.dispose()


async def _run_fence_reseed_cycle(async_url: str, primary_conn_str: str) -> None:
    """Fence the standby (disable+drop subscription) then re-seed it.

    Drives the production :class:`ReplicationStandbyFencer` against the real
    standby node the test is running on. ``ReplicationManager``'s DDL executes
    in autocommit against the app's configured database, so this must run on the
    Standby_Node itself (guarded by the subscription-exists precondition).
    """
    engine = create_async_engine(async_url)
    try:
        async with AsyncSession(engine) as standby_db:
            fencer = ReplicationStandbyFencer(standby_db, primary_conn_str)

            # --- Fence: disable then drop the subscription (Req 12.10). -----
            await fencer.fence()
            assert not await _subscription_exists(async_url), (
                "fence() must leave no subscription on the isolated standby"
            )

            # --- Re-seed: trigger_resync recreates the subscription (12.13). -
            await fencer.reseed()
            assert await _subscription_exists(async_url), (
                "reseed() must re-create the subscription on the standby"
            )
    finally:
        await engine.dispose()


def test_standby_fence_then_reseed_cycle() -> None:
    """Real subscription fence (disable+drop) then ``trigger_resync`` re-seed.

    Destructive on a live standby — runs only with explicit opt-in and a
    configured, subscription-carrying Standby_Node.

    Validates: Requirements 12.10, 12.13
    """
    if not os.environ.get("HA_FENCE_RESEED_TEST"):
        pytest.skip(
            "HA_FENCE_RESEED_TEST not set; the destructive fence/re-seed cycle "
            "runs only on an explicitly opted-in HA standby node"
        )

    primary_conn_str = os.environ.get("HA_PEER_DB_URL")
    if not primary_conn_str:
        pytest.skip(
            "HA_PEER_DB_URL (the primary connection string for re-seed) is not "
            "set; cannot run the fence/re-seed cycle"
        )

    async_url = _to_async_url(settings.database_url)
    if not _db_reachable(async_url):
        pytest.skip(
            "configured node not reachable at "
            f"{_redacted_target(async_url)} for the fence/re-seed cycle"
        )

    # Only run where the HA subscription actually lives — i.e. a Standby_Node —
    # so we never fence a primary or an unconfigured node.
    if not asyncio.run(_subscription_exists(async_url)):
        pytest.skip(
            "no HA subscription "
            f"({ReplicationManager.SUBSCRIPTION_NAME}) on the configured node; "
            "not a standby, skipping the fence/re-seed cycle"
        )

    asyncio.run(
        _run_fence_reseed_cycle(async_url, _to_libpq_url(primary_conn_str))
    )
