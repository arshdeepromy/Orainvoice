"""Pydantic v2 schemas and utility functions for the live database migration feature.

This module is separate from ``migration_schemas.py`` (which covers the V1 org
data migration tool).  All schemas here support the zero-downtime live database
migration workflow.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.3, 5.3, 5.4, 5.8, 7.6, 8.2, 9.1,
              10.4, 10.5, 11.3, 11.4
"""

from __future__ import annotations

import math
import re
from urllib.parse import urlparse, urlunparse

from pydantic import BaseModel

from app.modules.admin.migration_models import MigrationJobStatus


# ---------------------------------------------------------------------------
# Sub-schemas (must be defined before schemas that reference them)
# ---------------------------------------------------------------------------


class RowCountComparison(BaseModel):
    source: int
    target: int
    match: bool


class FinancialComparison(BaseModel):
    source_total: float
    target_total: float
    match: bool


class SequenceComparison(BaseModel):
    source_value: int
    target_value: int
    valid: bool  # target >= source


class TableProgress(BaseModel):
    table_name: str
    source_count: int
    migrated_count: int
    status: str  # pending | in_progress | completed | failed


class IntegrityCheckResult(BaseModel):
    passed: bool
    row_counts: dict[str, RowCountComparison]
    fk_errors: list[str]
    financial_totals: dict[str, FinancialComparison]
    sequence_checks: dict[str, SequenceComparison]


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class ConnectionValidateRequest(BaseModel):
    connection_string: str
    ssl_mode: str = "prefer"


class ConnectionValidateResponse(BaseModel):
    valid: bool
    server_version: str | None = None
    available_disk_space_mb: int | None = None
    has_existing_tables: bool = False
    error: str | None = None


class MigrationStartRequest(BaseModel):
    connection_string: str
    ssl_mode: str = "prefer"
    batch_size: int = 1000
    confirm_overwrite: bool = False


class MigrationStatusResponse(BaseModel):
    job_id: str
    status: MigrationJobStatus
    current_table: str | None = None
    tables: list[TableProgress] = []
    rows_processed: int = 0
    rows_total: int = 0
    progress_pct: float = 0.0
    estimated_seconds_remaining: int | None = None
    dual_write_queue_depth: int = 0
    integrity_check: IntegrityCheckResult | None = None
    error_message: str | None = None
    started_at: str = ""
    updated_at: str = ""


class CutoverRequest(BaseModel):
    confirmation_text: str


class RollbackRequest(BaseModel):
    reason: str


class MigrationJobSummary(BaseModel):
    job_id: str
    status: str
    started_at: str
    completed_at: str | None = None
    rows_total: int = 0
    source_host: str = ""
    target_host: str = ""


class MigrationJobDetail(MigrationJobSummary):
    integrity_check: IntegrityCheckResult | None = None
    error_message: str | None = None
    tables: list[TableProgress] = []


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

_EXPECTED_SCHEME = "postgresql+asyncpg"
_CONN_RE = re.compile(
    r"^postgresql\+asyncpg://[^:]+:[^@]+@[^:/]+(:\d+)?/\S+$"
)


def parse_connection_string(conn_str: str) -> dict:
    """Extract scheme, user, password, host, port, dbname from a connection URI.

    Uses ``urllib.parse.urlparse`` for robust parsing.
    """
    parsed = urlparse(conn_str)
    return {
        "scheme": parsed.scheme,
        "user": parsed.username or "",
        "password": parsed.password or "",
        "host": parsed.hostname or "",
        "port": parsed.port,
        "dbname": parsed.path.lstrip("/") if parsed.path else "",
    }


def mask_password(conn_str: str) -> str:
    """Replace the password portion of a connection string with ``****``.

    Preserves scheme, user, host, port, and dbname.
    """
    parsed = urlparse(conn_str)
    if parsed.password:
        # Rebuild netloc with masked password
        user_info = f"{parsed.username}:****"
        host_part = parsed.hostname or ""
        if parsed.port:
            host_part = f"{host_part}:{parsed.port}"
        masked_netloc = f"{user_info}@{host_part}"
        masked = parsed._replace(netloc=masked_netloc)
        return urlunparse(masked)
    return conn_str


def validate_connection_string_format(conn_str: str) -> tuple[bool, str | None]:
    """Validate that *conn_str* matches the expected PostgreSQL async URI format.

    Expected: ``postgresql+asyncpg://user:pass@host:port/dbname``

    Returns ``(True, None)`` on success or ``(False, error_message)`` on failure.
    """
    try:
        parsed = urlparse(conn_str)
    except ValueError:
        return False, (
            "Invalid connection string format. "
            "Expected: postgresql+asyncpg://user:pass@host:port/dbname"
        )

    if parsed.scheme != _EXPECTED_SCHEME:
        return False, (
            f"Invalid scheme '{parsed.scheme}'. "
            f"Expected: postgresql+asyncpg://user:pass@host:port/dbname"
        )

    if not parsed.username:
        return False, (
            "Missing username. "
            "Expected: postgresql+asyncpg://user:pass@host:port/dbname"
        )

    if not parsed.password:
        return False, (
            "Missing password. "
            "Expected: postgresql+asyncpg://user:pass@host:port/dbname"
        )

    if not parsed.hostname:
        return False, (
            "Missing host. "
            "Expected: postgresql+asyncpg://user:pass@host:port/dbname"
        )

    if not parsed.port:
        return False, (
            "Missing port. "
            "Expected: postgresql+asyncpg://user:pass@host:port/dbname"
        )

    dbname = parsed.path.lstrip("/")
    if not dbname:
        return False, (
            "Missing database name. "
            "Expected: postgresql+asyncpg://user:pass@host:port/dbname"
        )

    return True, None


def calculate_progress_pct(rows_processed: int, rows_total: int) -> float:
    """Calculate progress percentage clamped to [0, 100].

    Returns 0.0 when *rows_total* is 0.
    """
    if rows_total <= 0:
        return 0.0
    pct = (rows_processed / rows_total) * 100.0
    return max(0.0, min(100.0, pct))


def calculate_eta(
    rows_processed: int,
    elapsed_seconds: float,
    rows_total: int,
) -> int | None:
    """Estimate seconds remaining based on current throughput.

    Returns ``None`` when *rows_processed* is 0 (no throughput data).
    """
    if rows_processed <= 0:
        return None
    rate = rows_processed / elapsed_seconds
    remaining_rows = rows_total - rows_processed
    return int(remaining_rows / rate)


def partition_into_batches(rows: list, batch_size: int) -> list[list]:
    """Split *rows* into batches of at most *batch_size* elements."""
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    return [rows[i : i + batch_size] for i in range(0, len(rows), batch_size)]


def check_pg_version_compatible(version_str: str) -> bool:
    """Return ``True`` if the PostgreSQL major version is >= 13.

    Accepts version strings like ``"15.2"``, ``"13.0"``, ``"12.9"``.
    Returns ``False`` for unparseable strings.
    """
    try:
        major = int(version_str.split(".")[0])
        return major >= 13
    except (ValueError, IndexError):
        return False
