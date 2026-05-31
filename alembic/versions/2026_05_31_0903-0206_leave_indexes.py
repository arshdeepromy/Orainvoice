"""Staff Management Phase 2 — Leave engine CONCURRENTLY index pack.

Adds 8 indexes to support the Phase 2 leave feature surface introduced by
``0205_leave_schema`` (``leave_types``, ``leave_balances``, ``leave_requests``,
``leave_ledger``):

  - **Balance lookups (2)** —
    ``idx_leave_balances_staff_type`` (staff_id, leave_type_id) covers the
    Leave-tab dashboard query (load all balances for one staff).
    ``idx_leave_balances_org`` (org_id) backs FK / RLS scans.

  - **Approval queue (1)** —
    ``idx_leave_requests_org_status`` (org_id, status, created_at DESC)
    is the primary index for the org-wide approval queue (`GET
    /api/v2/leave/requests`) — filters by status and orders newest-first.

  - **Per-staff request list (1)** —
    ``idx_leave_requests_staff`` (staff_id, start_date DESC) backs the
    "my upcoming leave" view on the Leave tab.

  - **Ledger surfaces (3)** —
    ``idx_leave_ledger_staff_type_occurred`` (staff_id, leave_type_id,
    occurred_at DESC) is the primary ledger query (history per staff per
    type).
    ``idx_leave_ledger_org`` (org_id) backs RLS / FK scans.
    ``idx_leave_ledger_request`` (request_id) **partial** ``WHERE request_id
    IS NOT NULL`` — only ledger rows tied to a request need this lookup
    (manual_adjustment / accrual rows have NULL request_id and don't
    benefit).

  - **Active leave types per org (1)** —
    ``idx_leave_types_org_active`` (org_id, display_order) **partial**
    ``WHERE active = true`` — backs the Settings → Leave Types listing
    and the request modal type picker, both of which only ever surface
    active types.

Every index is created via ``CREATE INDEX CONCURRENTLY ... IF NOT EXISTS``
inside ``op.get_context().autocommit_block()`` so the migration is:

  - **Live-safe** — only ``SHARE UPDATE EXCLUSIVE`` lock on the table
    (does not block reads or writes).
  - **Re-runnable** — IF NOT EXISTS / IF EXISTS guards make this idempotent.

Mirrors the canonical 0202 / 0204 templates exactly — same
``_run_outside_tx`` helper, same per-statement logging, same reverse-order
downgrade.

Refs: design.md §3.3, tasks.md A2.

Revision ID: 0206
Revises: 0205
Create Date: 2026-05-31
"""

from __future__ import annotations

import logging

from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

revision: str = "0206"
down_revision: str = "0205"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


# Each tuple: (description, SQL).
# Indexes are independent; ordering only affects logging readability.
_UPGRADE_STATEMENTS: list[tuple[str, str]] = [
    # ----------------------------------------------------------------------
    # Balance lookups — staff dashboard + FK scans.
    # ----------------------------------------------------------------------
    (
        "Leave balances: leave_balances(staff_id, leave_type_id)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_leave_balances_staff_type "
        "ON leave_balances (staff_id, leave_type_id)",
    ),
    (
        "Leave balances: leave_balances(org_id)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_leave_balances_org "
        "ON leave_balances (org_id)",
    ),

    # ----------------------------------------------------------------------
    # Approval queue — primary list endpoint.
    # ----------------------------------------------------------------------
    (
        "Approval queue: leave_requests(org_id, status, created_at DESC)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_leave_requests_org_status "
        "ON leave_requests (org_id, status, created_at DESC)",
    ),

    # ----------------------------------------------------------------------
    # Per-staff request list — "my upcoming leave".
    # ----------------------------------------------------------------------
    (
        "Per-staff requests: leave_requests(staff_id, start_date DESC)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_leave_requests_staff "
        "ON leave_requests (staff_id, start_date DESC)",
    ),

    # ----------------------------------------------------------------------
    # Ledger surfaces — primary history query + RLS scan + request join.
    # ----------------------------------------------------------------------
    (
        "Ledger history: leave_ledger(staff_id, leave_type_id, occurred_at DESC)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_leave_ledger_staff_type_occurred "
        "ON leave_ledger (staff_id, leave_type_id, occurred_at DESC)",
    ),
    (
        "Ledger RLS scan: leave_ledger(org_id)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_leave_ledger_org "
        "ON leave_ledger (org_id)",
    ),
    (
        "Ledger request join (partial): leave_ledger(request_id) WHERE request_id IS NOT NULL",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_leave_ledger_request "
        "ON leave_ledger (request_id) "
        "WHERE request_id IS NOT NULL",
    ),

    # ----------------------------------------------------------------------
    # Active leave types per org — Settings list + request modal picker.
    # ----------------------------------------------------------------------
    (
        "Active leave types (partial): leave_types(org_id, display_order) WHERE active = true",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_leave_types_org_active "
        "ON leave_types (org_id, display_order) "
        "WHERE active = true",
    ),
]


# Drop in reverse order. Each statement is independent so order does not
# matter for correctness — reversed only for log readability.
_DOWNGRADE_STATEMENTS: list[tuple[str, str]] = [
    (
        "Drop idx_leave_types_org_active",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_leave_types_org_active",
    ),
    (
        "Drop idx_leave_ledger_request",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_leave_ledger_request",
    ),
    (
        "Drop idx_leave_ledger_org",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_leave_ledger_org",
    ),
    (
        "Drop idx_leave_ledger_staff_type_occurred",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_leave_ledger_staff_type_occurred",
    ),
    (
        "Drop idx_leave_requests_staff",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_leave_requests_staff",
    ),
    (
        "Drop idx_leave_requests_org_status",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_leave_requests_org_status",
    ),
    (
        "Drop idx_leave_balances_org",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_leave_balances_org",
    ),
    (
        "Drop idx_leave_balances_staff_type",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_leave_balances_staff_type",
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
            logger.info("[0206] %s", description)
            op.execute(sql)


def upgrade() -> None:
    _run_outside_tx(_UPGRADE_STATEMENTS)


def downgrade() -> None:
    _run_outside_tx(_DOWNGRADE_STATEMENTS)
