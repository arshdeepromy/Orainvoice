"""Cloud Backup & Restore — index-only migration.

Adds the indexes backing the Cloud Backup & Restore subsystem catalog and
job tables (design "Alembic migration notes"). The table-creation migration
``0221`` intentionally creates NO indexes; they live here so they can be
built with ``CREATE INDEX CONCURRENTLY`` without holding a long lock.

Indexes created (Req 9.1, 8.9):

  - ``backups(created_at DESC)``                       — catalog list ordering
  - ``blob_refcounts(content_hash)``                   — refcount GC by blob
  - ``blob_refcounts(backup_id)``                      — refcount GC by backup
  - ``backup_jobs(status, created_at DESC)``           — job list / status poll
  - ``restore_jobs(status, created_at DESC)``          — job list / status poll
  - ``backup_destination_copies(backup_id)``           — per-backup copy status

Every index is created via ``CREATE INDEX CONCURRENTLY ... IF NOT EXISTS``
and dropped via ``DROP INDEX CONCURRENTLY ... IF EXISTS`` so the migration is:

  - **Live-safe** — only ``SHARE UPDATE EXCLUSIVE`` lock on the table
    (does not block reads or writes).
  - **Re-runnable** — IF NOT EXISTS / IF EXISTS guards make this idempotent.

Because ``CONCURRENTLY`` cannot run inside a transaction, the operations
use Alembic's ``autocommit_block`` rather than the default Alembic-managed
transaction.

Revision ID: 0222
Revises: 0221
Create Date: 2026-06-11
"""

from __future__ import annotations

import logging

from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

revision: str = "0222"
down_revision: str = "0221"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


# Each tuple: (description, SQL).
# Indexes are independent; ordering only affects logging readability.
_UPGRADE_STATEMENTS: list[tuple[str, str]] = [
    (
        "Req 9.1: backups(created_at DESC) — catalog list ordering",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_backups_created_desc "
        "ON backups (created_at DESC)",
    ),
    (
        "Req 8.9: blob_refcounts(content_hash) — refcount GC by blob",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_blob_refcounts_content_hash "
        "ON blob_refcounts (content_hash)",
    ),
    (
        "Req 8.9: blob_refcounts(backup_id) — refcount GC by backup",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_blob_refcounts_backup "
        "ON blob_refcounts (backup_id)",
    ),
    (
        "Req 9.1: backup_jobs(status, created_at DESC) — job list / status poll",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_backup_jobs_status_created "
        "ON backup_jobs (status, created_at DESC)",
    ),
    (
        "Req 9.1: restore_jobs(status, created_at DESC) — job list / status poll",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_restore_jobs_status_created "
        "ON restore_jobs (status, created_at DESC)",
    ),
    (
        "Req 9.1: backup_destination_copies(backup_id) — per-backup copy status",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_backup_dest_copies_backup "
        "ON backup_destination_copies (backup_id)",
    ),
]


# Drop in reverse order. Each statement is independent so order does not
# matter for correctness — reversed only for log readability.
_DOWNGRADE_STATEMENTS: list[tuple[str, str]] = [
    ("Drop idx_backup_dest_copies_backup",      "DROP INDEX CONCURRENTLY IF EXISTS idx_backup_dest_copies_backup"),
    ("Drop idx_restore_jobs_status_created",    "DROP INDEX CONCURRENTLY IF EXISTS idx_restore_jobs_status_created"),
    ("Drop idx_backup_jobs_status_created",     "DROP INDEX CONCURRENTLY IF EXISTS idx_backup_jobs_status_created"),
    ("Drop idx_blob_refcounts_backup",          "DROP INDEX CONCURRENTLY IF EXISTS idx_blob_refcounts_backup"),
    ("Drop idx_blob_refcounts_content_hash",    "DROP INDEX CONCURRENTLY IF EXISTS idx_blob_refcounts_content_hash"),
    ("Drop idx_backups_created_desc",           "DROP INDEX CONCURRENTLY IF EXISTS idx_backups_created_desc"),
]


def _run_outside_tx(statements: list[tuple[str, str]]) -> None:
    """Execute each statement inside an Alembic ``autocommit_block``.

    ``CREATE/DROP INDEX CONCURRENTLY`` cannot run inside a transaction.
    Alembic's ``autocommit_block`` context manager commits the active
    migration transaction, runs the body in autocommit mode, and then
    starts a fresh transaction for whatever follows. That's exactly the
    semantic Postgres requires for CONCURRENTLY DDL.

    Each statement is executed independently — a failure on one does not
    roll back the others (which is the only behaviour Postgres offers
    for CONCURRENTLY anyway: the index is left around in an INVALID state
    for that one, recoverable via REINDEX or by deleting + re-running this
    migration).
    """
    with op.get_context().autocommit_block():
        for description, sql in statements:
            logger.info("[0222] %s", description)
            op.execute(sql)


def upgrade() -> None:
    _run_outside_tx(_UPGRADE_STATEMENTS)


def downgrade() -> None:
    _run_outside_tx(_DOWNGRADE_STATEMENTS)
