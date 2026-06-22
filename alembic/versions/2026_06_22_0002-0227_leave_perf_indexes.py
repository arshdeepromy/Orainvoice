"""Leave balances & eligibility — performance indexes (CONCURRENTLY).

Separate revision from ``0226`` because mixing ``CREATE INDEX CONCURRENTLY``
with transactional DDL in one ``upgrade()`` is a banned pattern (it changes the
transaction semantics for the rest of the migration). All DDL here runs inside
``op.get_context().autocommit_block()`` — the canonical ``0202_add_perf_indexes``
/ ``0224`` autocommit template — because Postgres rejects
``CREATE/DROP INDEX CONCURRENTLY`` inside a transaction.

Indexes:
  - ``idx_leave_balances_org`` on ``leave_balances (org_id)`` — the org-wide
    balances list filters by ``org_id`` (R1.3/R1.4).
  - ``idx_leave_elig_notes_staff_type`` on
    ``leave_eligibility_notes (staff_id, leave_type_id)`` — per-staff eligibility
    note lookups in the drill-in + vesting de-dup.

Every statement carries ``IF NOT EXISTS`` / ``IF EXISTS`` guards so a partial
(INVALID) build left by an interrupted CONCURRENTLY run is safely re-runnable.

Refs: requirements 1.3, 1.4.

Revision ID: 0227
Revises: 0226
Create Date: 2026-06-22
"""

from __future__ import annotations

import logging

from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

revision: str = "0227"
down_revision: str = "0226"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


_UPGRADE_INDEXES: list[tuple[str, str]] = [
    (
        "idx_leave_balances_org — org-wide balances list filter",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_leave_balances_org "
        "ON leave_balances (org_id)",
    ),
    (
        "idx_leave_elig_notes_staff_type — per-staff eligibility note lookup",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_leave_elig_notes_staff_type "
        "ON leave_eligibility_notes (staff_id, leave_type_id)",
    ),
]

_DOWNGRADE_INDEXES: list[tuple[str, str]] = [
    (
        "Drop idx_leave_elig_notes_staff_type",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_leave_elig_notes_staff_type",
    ),
    (
        "Drop idx_leave_balances_org",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_leave_balances_org",
    ),
]


def _run_outside_tx(statements: list[tuple[str, str]]) -> None:
    with op.get_context().autocommit_block():
        for description, sql in statements:
            logger.info("[0227] %s", description)
            op.execute(sql)


def upgrade() -> None:
    _run_outside_tx(_UPGRADE_INDEXES)


def downgrade() -> None:
    _run_outside_tx(_DOWNGRADE_INDEXES)
