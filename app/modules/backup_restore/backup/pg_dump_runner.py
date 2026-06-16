"""Standby-sourced ``pg_dump`` runner (cloud-backup-restore Req 5, 23.2).

Step 3 of the Backup Pipeline (design.md "Backup Pipeline"). This module runs
``pg_dump -Fc`` (custom format) against the **standby replica's database**, not
the primary, so producing a backup never loads the primary that is serving live
traffic. The standby DB is reached over the network via the peer DB connection
string built by HA's :func:`get_peer_db_url` (the ``peer_db_*`` fields on
``ha_config``); a network connection is reachable from the primary-run backup
task, unlike the standby's *filesystem* (file capture, step 4, reads the
primary's own local volumes).

Consistency (Req 23.2)
----------------------
``pg_dump`` runs the entire export inside a **single transaction snapshot**.
Custom format (``-Fc``) uses one connection whose transaction is opened at
``REPEATABLE READ`` isolation, giving an internally consistent image of the
database for the life of the dump. This satisfies the "REPEATABLE READ or
serializable export-snapshot semantics" requirement without any extra flag.

  *Note:* ``--serializable-deferrable`` is **not** used: ``SERIALIZABLE`` is
  rejected on a hot standby, and the dump runs against the standby. ``pg_dump``'s
  default ``REPEATABLE READ`` export snapshot is the correct, compatible choice.

Coverage (Req 5.1, 5.2)
-----------------------
A plain ``pg_dump -Fc`` of the database captures **every non-template object** —
all schemas, tables, sequences, views, indexes, constraints, and row data —
including feature flags, integration settings, and DB-stored BYTEA assets such
as ``platform_branding`` images, because those live in ordinary tables and so
travel inside the dump. No object filters are applied, so nothing is omitted.

Failure (Req 5.6)
-----------------
A non-zero ``pg_dump`` exit raises :class:`PgDumpError` carrying a
human-readable reason built from the captured ``stderr`` (with any password in
the connection string masked). The caller (the pipeline, task 8.2) turns that
into a ``failed`` Backup_Job and a failure notification.

This module performs the dump only; it does not encrypt, upload, checksum, or
record anything — those are the pipeline's responsibility (task 8.2).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ha.service import get_peer_db_url

logger = logging.getLogger(__name__)

# Default ``pg_dump`` binary; overridable for tests / non-standard installs.
DEFAULT_PG_DUMP_BIN = "pg_dump"

# A backup of the whole platform DB can take a long time; allow a generous
# ceiling but never block forever. 6 hours mirrors a worst-case large dump.
DEFAULT_PG_DUMP_TIMEOUT_SECONDS = 6 * 60 * 60

# The consistency guarantee recorded for the DB portion of the dump (Req 23.2).
SNAPSHOT_ISOLATION = "repeatable_read"


class PgDumpError(Exception):
    """A ``pg_dump`` run failed with a human-readable reason (Req 5.6).

    Attributes:
        reason: Human-readable failure description (safe to surface to a
            Global_Admin; never contains the connection password).
        returncode: The ``pg_dump`` exit code, when the process started and
            exited non-zero; ``None`` if the process could not be started or
            timed out.
    """

    def __init__(self, reason: str, *, returncode: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.returncode = returncode


@dataclass
class PgDumpResult:
    """The outcome of a successful standby-sourced ``pg_dump`` run.

    Returned to the pipeline (task 8.2), which then encrypts, checksums, and
    fans the dump out to destinations.
    """

    dump_path: str
    """Filesystem path of the custom-format dump file produced by ``pg_dump``."""

    byte_size: int
    """Size of the (unencrypted) dump file in bytes."""

    database_name: str
    """Name of the database that was dumped (from the peer connection string)."""

    source: str = "standby"
    """Where the dump was sourced from — always the standby replica (Req 23.2)."""

    snapshot_isolation: str = SNAPSHOT_ISOLATION
    """Transaction snapshot isolation the dump ran under (REPEATABLE READ)."""

    started_at: datetime | None = None
    """UTC timestamp ``pg_dump`` was started."""

    finished_at: datetime | None = None
    """UTC timestamp ``pg_dump`` exited 0."""


def _mask_conn(conn_url: str) -> str:
    """Return *conn_url* with any password component masked for safe logging."""
    # Mask ``://user:password@`` → ``://user:***@`` without disturbing the rest.
    return re.sub(r"(://[^:/?#@]+:)[^@/?#]*(@)", r"\1***\2", conn_url)


def _database_name(conn_url: str) -> str:
    """Extract the database name from a ``postgresql://.../<db>`` URL."""
    path = urlsplit(conn_url).path or ""
    name = path.lstrip("/")
    return name or "unknown"


async def run_pg_dump(
    conn_url: str,
    *,
    output_path: str | None = None,
    pg_dump_bin: str = DEFAULT_PG_DUMP_BIN,
    timeout_seconds: int = DEFAULT_PG_DUMP_TIMEOUT_SECONDS,
) -> PgDumpResult:
    """Run ``pg_dump -Fc`` against *conn_url* into a custom-format dump file.

    The dump runs inside ``pg_dump``'s default single-transaction REPEATABLE
    READ export snapshot for an internally consistent image (Req 23.2) and
    captures every non-template object including BYTEA assets (Req 5.1, 5.2).
    Output is streamed to a file (``--file``) rather than buffered in memory,
    because a full platform dump can be very large.

    Args:
        conn_url: A libpq-compatible ``postgresql://`` connection string for the
            standby DB (as produced by :func:`get_peer_db_url`). May embed the
            password and an ``sslmode`` query parameter.
        output_path: Destination path for the dump file. When omitted a secure
            temporary file is created; the caller owns deleting it.
        pg_dump_bin: ``pg_dump`` executable (overridable for tests).
        timeout_seconds: Hard ceiling on the dump; exceeding it kills the
            process and raises :class:`PgDumpError`.

    Returns:
        A :class:`PgDumpResult` describing the produced dump file.

    Raises:
        PgDumpError: If ``pg_dump`` exits non-zero, cannot be started, or times
            out. The message is human-readable and never contains the password.
    """
    if not conn_url:
        raise PgDumpError("No standby database connection string was provided.")

    # asyncpg-style driver suffixes are not understood by the libpq-based
    # ``pg_dump`` CLI; normalise to a plain ``postgresql://`` URL.
    cli_conn_url = conn_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    db_name = _database_name(cli_conn_url)
    masked = _mask_conn(cli_conn_url)

    # Resolve the dump output path; create a secure temp file when none given.
    created_temp = False
    if output_path is None:
        fd, output_path = tempfile.mkstemp(prefix="orainvoice_pg_dump_", suffix=".dump")
        os.close(fd)
        created_temp = True

    # ``-Fc`` custom format; ``--no-password`` so a missing/incorrect password
    # fails fast with a clear error instead of blocking on an interactive
    # prompt. The connection string carries any password/sslmode (libpq).
    cmd = [
        pg_dump_bin,
        "--format=custom",
        "--no-password",
        f"--file={output_path}",
        f"--dbname={cli_conn_url}",
    ]

    logger.info("Starting pg_dump (custom format) against standby %s", masked)
    started_at = datetime.now(timezone.utc)

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        if created_temp:
            _safe_unlink(output_path)
        raise PgDumpError(
            f"The '{pg_dump_bin}' executable was not found; PostgreSQL client "
            "tools must be installed to create a backup.",
        )
    except Exception as exc:  # pragma: no cover - defensive
        if created_temp:
            _safe_unlink(output_path)
        raise PgDumpError(f"Failed to start pg_dump: {exc}")

    try:
        _, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        if created_temp:
            _safe_unlink(output_path)
        raise PgDumpError(
            f"pg_dump timed out after {timeout_seconds} seconds and was "
            "terminated; the database dump did not complete.",
        )

    stderr_text = (stderr or b"").decode("utf-8", errors="replace").strip()

    if process.returncode != 0:
        if created_temp:
            _safe_unlink(output_path)
        detail = _mask_conn(stderr_text) if stderr_text else ""
        reason = (
            f"pg_dump failed (exit code {process.returncode}) while dumping the "
            f"standby database '{db_name}'."
        )
        if detail:
            reason = f"{reason} {detail}"
        logger.error("pg_dump failed against standby %s: %s", masked, detail or "(no stderr)")
        raise PgDumpError(reason, returncode=process.returncode)

    try:
        byte_size = os.path.getsize(output_path)
    except OSError as exc:
        raise PgDumpError(
            f"pg_dump reported success but the dump file could not be read: {exc}",
        )

    if byte_size == 0:
        # A custom-format dump always has a header; a zero-byte file means the
        # dump did not actually produce output despite a 0 exit code.
        if created_temp:
            _safe_unlink(output_path)
        raise PgDumpError(
            "pg_dump exited successfully but produced an empty dump file.",
        )

    finished_at = datetime.now(timezone.utc)
    logger.info(
        "pg_dump completed against standby %s: %d bytes in %.1fs",
        masked, byte_size, (finished_at - started_at).total_seconds(),
    )

    return PgDumpResult(
        dump_path=output_path,
        byte_size=byte_size,
        database_name=db_name,
        started_at=started_at,
        finished_at=finished_at,
    )


async def dump_standby(
    db: AsyncSession,
    *,
    output_path: str | None = None,
    pg_dump_bin: str = DEFAULT_PG_DUMP_BIN,
    timeout_seconds: int = DEFAULT_PG_DUMP_TIMEOUT_SECONDS,
) -> PgDumpResult:
    """Resolve the standby peer DB URL and run ``pg_dump -Fc`` against it.

    Convenience entry point for the pipeline: looks up the peer DB connection
    string from ``ha_config`` via :func:`get_peer_db_url` and delegates to
    :func:`run_pg_dump`. Raises :class:`PgDumpError` with a human-readable
    reason when no standby/peer DB is configured (Req 5.6).

    Args:
        db: Async DB session used to read the HA peer DB configuration.
        output_path: Optional dump destination (see :func:`run_pg_dump`).
        pg_dump_bin: ``pg_dump`` executable (overridable for tests).
        timeout_seconds: Hard ceiling on the dump.

    Returns:
        A :class:`PgDumpResult` describing the produced dump file.
    """
    peer_db_url = await get_peer_db_url(db)
    if not peer_db_url:
        raise PgDumpError(
            "No standby (peer) database is configured, so a standby-sourced "
            "backup cannot run. Configure the HA peer database connection "
            "before creating a backup.",
        )

    return await run_pg_dump(
        peer_db_url,
        output_path=output_path,
        pg_dump_bin=pg_dump_bin,
        timeout_seconds=timeout_seconds,
    )


def _safe_unlink(path: str) -> None:
    """Best-effort removal of a partial/temp dump file; never raises."""
    try:
        os.unlink(path)
    except OSError:
        logger.debug("Could not remove pg_dump output file %s", path, exc_info=True)
