"""PPSR Module — CONCURRENTLY index pack.

Adds 4 indexes to support the PPSR module surface introduced by
``0211_ppsr_module`` (table ``ppsr_searches``):

  - **History page (1)** —
    ``idx_ppsr_searches_org_created`` (org_id, created_at DESC) backs the
    ``GET /api/v2/ppsr/searches`` paginated history list filtered by
    org. Without it, the planner falls back to a seq-scan + in-memory
    sort once the per-org row count grows past the cache.

  - **Cache lookup (1, G30)** —
    ``idx_ppsr_searches_org_rego_options_created`` (org_id, rego,
    options_hash, created_at DESC) backs the 5-minute Redis-paired
    cache lookup at ``PpsrService._find_recent_match`` keyed on
    ``(org_id, rego, options_hash)`` — G30 closure: the canonical-JSON
    sha256 hash of the search options dict means re-ordered JSON keys
    still hit the cache. Plain ``rego`` (not ``UPPER(rego)``) is
    sufficient because rego is normalised to upper-case at insert time
    in the service layer.

  - **Per-user activity report (1)** —
    ``idx_ppsr_searches_user`` (user_id, created_at DESC) backs
    per-user filters on the history page and any future "my activity"
    report.

  - **Vehicle Profile embed (1, partial — G13/G39)** —
    ``idx_ppsr_searches_org_vehicle`` (org_id, org_vehicle_id,
    created_at DESC) **partial** ``WHERE org_vehicle_id IS NOT NULL``
    backs the ``PpsrCard`` latest-match-per-vehicle lookup on the
    Vehicle Profile page. The partial predicate keeps the index small
    because the bulk of historical search rows are not yet linked to
    an org-vehicle row.

Every index is created via ``CREATE INDEX CONCURRENTLY ... IF NOT EXISTS``
inside ``op.get_context().autocommit_block()`` so the migration is:

  - **Live-safe** — only ``SHARE UPDATE EXCLUSIVE`` lock on the table
    (does not block reads or writes).
  - **Re-runnable** — IF NOT EXISTS / IF EXISTS guards make this
    idempotent.

Mirrors the canonical 0202 / 0204 / 0206 / 0208 / 0210 templates exactly
— same ``_run_outside_tx`` helper, same per-statement logging, same
reverse-order downgrade.

Refs: design.md §3.2, tasks.md A2, performance-and-resilience steering.

Revision ID: 0212
Revises: 0211
Create Date: 2026-05-31
"""

from __future__ import annotations

import logging

from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

revision: str = "0212"
down_revision: str = "0211"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


# Each tuple: (description, SQL).
# Indexes are independent; ordering only affects logging readability.
_UPGRADE_STATEMENTS: list[tuple[str, str]] = [
    # ----------------------------------------------------------------------
    # History page — paginated org-wide search list ordered by recency.
    # ----------------------------------------------------------------------
    (
        "History page: ppsr_searches(org_id, created_at DESC)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ppsr_searches_org_created "
        "ON ppsr_searches (org_id, created_at DESC)",
    ),

    # ----------------------------------------------------------------------
    # G30 cache lookup — keyed on (org_id, rego, options_hash) so
    # re-ordered options-JSON keys still land on the same cached row.
    # ----------------------------------------------------------------------
    (
        "Cache lookup (G30): "
        "ppsr_searches(org_id, rego, options_hash, created_at DESC)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ppsr_searches_org_rego_options_created "
        "ON ppsr_searches (org_id, rego, options_hash, created_at DESC)",
    ),

    # ----------------------------------------------------------------------
    # Per-user activity report — history page user filter + "my searches".
    # ----------------------------------------------------------------------
    (
        "Per-user activity: ppsr_searches(user_id, created_at DESC)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ppsr_searches_user "
        "ON ppsr_searches (user_id, created_at DESC)",
    ),

    # ----------------------------------------------------------------------
    # G13/G39 Vehicle Profile embed — latest match per linked org_vehicle.
    # Partial index keeps it small (most historical rows are unlinked).
    # ----------------------------------------------------------------------
    (
        "Vehicle Profile embed (partial, G13/G39): "
        "ppsr_searches(org_id, org_vehicle_id, created_at DESC) "
        "WHERE org_vehicle_id IS NOT NULL",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ppsr_searches_org_vehicle "
        "ON ppsr_searches (org_id, org_vehicle_id, created_at DESC) "
        "WHERE org_vehicle_id IS NOT NULL",
    ),
]


# Drop in reverse order. Each statement is independent so order does not
# matter for correctness — reversed only for log readability.
_DOWNGRADE_STATEMENTS: list[tuple[str, str]] = [
    (
        "Drop idx_ppsr_searches_org_vehicle",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_ppsr_searches_org_vehicle",
    ),
    (
        "Drop idx_ppsr_searches_user",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_ppsr_searches_user",
    ),
    (
        "Drop idx_ppsr_searches_org_rego_options_created",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_ppsr_searches_org_rego_options_created",
    ),
    (
        "Drop idx_ppsr_searches_org_created",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_ppsr_searches_org_created",
    ),
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
    for CONCURRENTLY anyway: the partial index is left around in an
    INVALID state for that one, recoverable via REINDEX or by deleting
    + re-running this migration).
    """
    with op.get_context().autocommit_block():
        for description, sql in statements:
            logger.info("[0212] %s", description)
            op.execute(sql)


def upgrade() -> None:
    _run_outside_tx(_UPGRADE_STATEMENTS)


def downgrade() -> None:
    _run_outside_tx(_DOWNGRADE_STATEMENTS)
