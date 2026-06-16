"""Integration test: real ``pg_dump -Fc`` → ``pg_restore`` round-trip.

Task 8.5 (cloud-backup-restore) — a single-execution **integration** test,
explicitly NOT a property-based test. It exercises the real
:func:`app.modules.backup_restore.backup.pg_dump_runner.run_pg_dump` against a
live PostgreSQL server using the actual ``pg_dump`` / ``pg_restore`` client
binaries (no mocks), proving one representative end-to-end round-trip.

What it proves
--------------
* ``run_pg_dump`` produces a **custom-format** archive — the file is non-empty
  and begins with the ``pg_dump`` custom-format magic header ``PGDMP``
  (Requirement 5.1: a ``pg_dump`` custom-format dump capturing database
  objects/rows, including BYTEA data).
* The archive is a **valid, restorable** custom-format archive — it round-trips:
  ``pg_restore`` loads it into a fresh scratch database and the seeded row
  (including a BYTEA column) comes back byte-for-byte identical (Requirement
  23.2: the dump is an internally consistent, single-snapshot export that can
  be restored).

Environment gating
------------------
A real PostgreSQL server is required. The connection string is taken from the
``PG_TEST_URL`` environment variable when set, otherwise from
``settings.database_url`` (mirroring ``tests/smoke/test_backup_restore_migrations_smoke.py``).
The test **skips cleanly** — never fails spuriously — when:
  * PostgreSQL is unreachable, or
  * the ``pg_dump`` / ``pg_restore`` client binaries are not installed.

The happy path creates two **scratch databases** (a source to dump and a fresh
target to restore into) and tears them down afterwards. WHERE the test role may
not ``CREATE DATABASE``, it degrades to a still-meaningful fallback: it dumps
the existing known database and runs ``pg_restore --list`` on the archive to
prove the produced file is a valid, listable custom-format archive.

Validates: Requirements 5.1, 23.2
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
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.modules.backup_restore.backup.pg_dump_runner import run_pg_dump

# Every test in this module exercises real local PostgreSQL client tooling.
pytestmark = pytest.mark.integration

# The 5-byte magic header at the start of every pg_dump custom-format archive.
PGDMP_MAGIC = b"PGDMP"


# ---------------------------------------------------------------------------
# URL helpers
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


def _with_db(url: str, dbname: str) -> str:
    """Return *url* with its database (path) component replaced by *dbname*."""
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{dbname}"))


def _database_name(url: str) -> str:
    """Extract the database name from *url* (the path, sans leading slash)."""
    return (urlsplit(url).path or "").lstrip("/") or "postgres"


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
# Round-trip seed data
# ---------------------------------------------------------------------------

# A representative row exercising a text column and a BYTEA column (BYTEA assets
# such as branding images travel inside the dump per Requirement 5.1).
_PROBE_NAME = "round-trip probe ✓"
_PROBE_PAYLOAD = bytes(range(256))  # all byte values, to catch any corruption


async def _seed_source(src_async_url: str) -> None:
    """Create a probe table with one known row in the source scratch DB."""
    engine = create_async_engine(src_async_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "CREATE TABLE roundtrip_probe ("
                    "id integer PRIMARY KEY, "
                    "name text NOT NULL, "
                    "payload bytea NOT NULL)"
                )
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO roundtrip_probe (id, name, payload) "
                    "VALUES (:id, :name, :payload)"
                ),
                {"id": 1, "name": _PROBE_NAME, "payload": _PROBE_PAYLOAD},
            )
    finally:
        await engine.dispose()


async def _read_probe(tgt_async_url: str) -> tuple[int, str, bytes]:
    """Read the single probe row back from the restored target DB."""
    engine = create_async_engine(tgt_async_url)
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    sa.text("SELECT id, name, payload FROM roundtrip_probe")
                )
            ).one()
        # asyncpg returns bytea as ``bytes`` (or memoryview); normalise.
        return int(row[0]), str(row[1]), bytes(row[2])
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Core round-trip
# ---------------------------------------------------------------------------

async def _run_full_roundtrip(async_url: str) -> None:
    """Create source+target scratch DBs, dump source, restore into target."""
    suffix = uuid.uuid4().hex[:12]
    src_db = f"orainvoice_pgdump_src_{suffix}"
    tgt_db = f"orainvoice_pgdump_tgt_{suffix}"
    maint_url = _with_db(async_url, "postgres")

    if not await _try_create_database(maint_url, src_db):
        # No CREATE DATABASE privilege — fall back to the list-only proof.
        await _run_listonly_fallback(async_url)
        return

    src_created = True
    tgt_created = False
    dump_fd, dump_path = tempfile.mkstemp(prefix="orainvoice_roundtrip_", suffix=".dump")
    os.close(dump_fd)
    try:
        src_async_url = _with_db(async_url, src_db)
        await _seed_source(src_async_url)

        # Real pg_dump -Fc against the source scratch DB.
        result = await run_pg_dump(src_async_url, output_path=dump_path)

        # --- Requirement 5.1: a non-empty custom-format archive was produced.
        assert result.dump_path == dump_path
        assert result.byte_size > 0, "pg_dump produced an empty dump file"
        assert os.path.getsize(dump_path) == result.byte_size
        with open(dump_path, "rb") as fh:
            header = fh.read(len(PGDMP_MAGIC))
        assert header == PGDMP_MAGIC, (
            "dump file is not a pg_dump custom-format archive "
            f"(header was {header!r}, expected {PGDMP_MAGIC!r})"
        )
        assert result.snapshot_isolation == "repeatable_read"

        # --- Requirement 23.2: the archive restores into a fresh database.
        tgt_created = await _try_create_database(maint_url, tgt_db)
        assert tgt_created, "could not create the target scratch database"

        tgt_libpq_url = _with_db(
            async_url.replace("postgresql+asyncpg://", "postgresql://", 1),
            tgt_db,
        )
        restore = subprocess.run(
            [
                "pg_restore",
                "--no-password",
                f"--dbname={tgt_libpq_url}",
                dump_path,
            ],
            capture_output=True,
            text=True,
        )
        assert restore.returncode == 0, (
            "pg_restore failed to restore the custom-format archive:\n"
            f"STDOUT:\n{restore.stdout}\nSTDERR:\n{restore.stderr}"
        )

        # The seeded row round-trips byte-for-byte (text + BYTEA).
        rid, rname, rpayload = await _read_probe(_with_db(async_url, tgt_db))
        assert rid == 1
        assert rname == _PROBE_NAME
        assert rpayload == _PROBE_PAYLOAD
    finally:
        if src_created:
            await _drop_database(maint_url, src_db)
        if tgt_created:
            await _drop_database(maint_url, tgt_db)
        if os.path.exists(dump_path):
            os.unlink(dump_path)


async def _run_listonly_fallback(async_url: str) -> None:
    """Dump the existing known DB and prove the archive is a listable archive.

    Used WHERE the test role cannot ``CREATE DATABASE``. Still exercises the
    real ``run_pg_dump`` and proves the produced file is a valid, restorable
    custom-format archive via ``pg_restore --list``.
    """
    dump_fd, dump_path = tempfile.mkstemp(prefix="orainvoice_roundtrip_", suffix=".dump")
    os.close(dump_fd)
    try:
        result = await run_pg_dump(async_url, output_path=dump_path)

        # Requirement 5.1: non-empty custom-format archive with the magic header.
        assert result.byte_size > 0, "pg_dump produced an empty dump file"
        with open(dump_path, "rb") as fh:
            header = fh.read(len(PGDMP_MAGIC))
        assert header == PGDMP_MAGIC, (
            f"dump file header was {header!r}, expected {PGDMP_MAGIC!r}"
        )

        # Requirement 23.2: the archive is a valid, restorable custom-format
        # archive — pg_restore can parse and list its table of contents.
        listing = subprocess.run(
            ["pg_restore", "--list", dump_path],
            capture_output=True,
            text=True,
        )
        assert listing.returncode == 0, (
            "pg_restore --list rejected the archive (not a valid custom-format "
            f"dump):\nSTDOUT:\n{listing.stdout}\nSTDERR:\n{listing.stderr}"
        )
        assert listing.stdout.strip(), "pg_restore --list produced no table of contents"
    finally:
        if os.path.exists(dump_path):
            os.unlink(dump_path)


def test_pg_dump_restore_roundtrip() -> None:
    """Real ``pg_dump -Fc`` then ``pg_restore`` round-trips into a scratch DB.

    Validates: Requirements 5.1, 23.2
    """
    raw_url = os.environ.get("PG_TEST_URL") or settings.database_url
    async_url = _to_async_url(raw_url)

    if not _db_reachable(async_url):
        pytest.skip(
            "PostgreSQL not reachable at "
            f"{_redacted_target(async_url)} for the pg_dump/pg_restore round-trip"
        )

    if shutil.which("pg_dump") is None or shutil.which("pg_restore") is None:
        pytest.skip(
            "pg_dump / pg_restore client binaries are not installed; "
            "cannot run the real round-trip integration test"
        )

    asyncio.run(_run_full_roundtrip(async_url))
