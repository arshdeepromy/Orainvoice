"""Staff Management Phase 3 — Time-clock CONCURRENTLY index pack.

Adds 10 indexes to support the Phase 3 time-clock feature surface introduced
by ``0207_time_clock_schema`` (``time_clock_entries``, ``break_records``,
``timesheet_approvals``, ``overtime_requests``, ``shift_swap_requests``,
``shift_cover_requests``):

  - **Hours-tab drill-down (1)** —
    ``idx_time_clock_org_staff_date`` (org_id, staff_id, clock_in_at DESC)
    backs the per-staff week view on the Hours tab and the
    ``GET /api/v2/staff/:id/clock-entries`` listing.

  - **Open-clock-in lookups (2)** —
    ``idx_time_clock_open`` (staff_id) **partial**
    ``WHERE clock_out_at IS NULL`` is the canonical "is this staff
    currently clocked in?" probe used by every clock-action handler
    (kiosk, self-service, admin manual). At most one row per staff
    matches.
    ``idx_time_clock_org_open`` (org_id, clock_in_at) **partial**
    ``WHERE clock_out_at IS NULL`` backs the
    ``check_missed_clock_outs`` scheduled task (design §4.3) which
    sweeps the org's open entries hourly.

  - **Break join (1)** —
    ``idx_break_records_entry`` (time_clock_entry_id) backs the
    break-history join when computing worked_minutes for a clock entry.

  - **Approval queue + per-staff history (2)** —
    ``idx_timesheet_approvals_org_status`` (org_id, status,
    week_start DESC) backs the org-wide approval queue
    (status='pending') ordered newest-week-first.
    ``idx_timesheet_approvals_staff`` (staff_id, week_start DESC) backs
    the "my approved weeks" history strip on the staff Detail Hours tab.

  - **Overtime queue (1)** —
    ``idx_overtime_requests_org_status`` (org_id, status,
    created_at DESC) backs the overtime-request approval queue.

  - **Shift swap + cover queues (2)** —
    ``idx_shift_swaps_status`` (org_id, status, created_at DESC) backs
    the swap manager queue (status='awaiting_manager' filter — G8) and
    the all-swaps history view.
    ``idx_shift_cover_status`` (org_id, status, broadcast_at DESC) backs
    the open shifts board (status='open' filter).

  - **Flagged entries (1, partial — G10)** —
    ``idx_time_clock_flagged`` (org_id, staff_id) **partial**
    ``WHERE (flags->>'flagged_for_review')::boolean = true`` —
    supports the flagged-entries query on the Hours tab and the
    ``FlaggedReviewBanner`` count. Most rows have ``flags = '{}'`` so
    the partial index stays small even for orgs with high clock volume.

Every index is created via ``CREATE INDEX CONCURRENTLY ... IF NOT EXISTS``
inside ``op.get_context().autocommit_block()`` so the migration is:

  - **Live-safe** — only ``SHARE UPDATE EXCLUSIVE`` lock on the table
    (does not block reads or writes).
  - **Re-runnable** — IF NOT EXISTS / IF EXISTS guards make this idempotent.

Mirrors the canonical 0202 / 0204 / 0206 templates exactly — same
``_run_outside_tx`` helper, same per-statement logging, same reverse-order
downgrade.

Refs: design.md §3.2, tasks.md A2.

Revision ID: 0208
Revises: 0207
Create Date: 2026-05-31
"""

from __future__ import annotations

import logging

from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

revision: str = "0208"
down_revision: str = "0207"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


# Each tuple: (description, SQL).
# Indexes are independent; ordering only affects logging readability.
_UPGRADE_STATEMENTS: list[tuple[str, str]] = [
    # ----------------------------------------------------------------------
    # Hours-tab drill-down — per-staff week view.
    # ----------------------------------------------------------------------
    (
        "Hours tab: time_clock_entries(org_id, staff_id, clock_in_at DESC)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_time_clock_org_staff_date "
        "ON time_clock_entries (org_id, staff_id, clock_in_at DESC)",
    ),

    # ----------------------------------------------------------------------
    # Open-clock-in lookups — clock-action probe + missed-clock-out sweep.
    # ----------------------------------------------------------------------
    (
        "Open clock-in probe (partial): time_clock_entries(staff_id) "
        "WHERE clock_out_at IS NULL",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_time_clock_open "
        "ON time_clock_entries (staff_id) "
        "WHERE clock_out_at IS NULL",
    ),
    (
        "Missed clock-out sweep (partial): time_clock_entries(org_id, clock_in_at) "
        "WHERE clock_out_at IS NULL",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_time_clock_org_open "
        "ON time_clock_entries (org_id, clock_in_at) "
        "WHERE clock_out_at IS NULL",
    ),

    # ----------------------------------------------------------------------
    # Break join — worked_minutes computation.
    # ----------------------------------------------------------------------
    (
        "Break join: break_records(time_clock_entry_id)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_break_records_entry "
        "ON break_records (time_clock_entry_id)",
    ),

    # ----------------------------------------------------------------------
    # Timesheet approvals — org queue + per-staff history.
    # ----------------------------------------------------------------------
    (
        "Approval queue: timesheet_approvals(org_id, status, week_start DESC)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_timesheet_approvals_org_status "
        "ON timesheet_approvals (org_id, status, week_start DESC)",
    ),
    (
        "Per-staff history: timesheet_approvals(staff_id, week_start DESC)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_timesheet_approvals_staff "
        "ON timesheet_approvals (staff_id, week_start DESC)",
    ),

    # ----------------------------------------------------------------------
    # Overtime requests — approval queue.
    # ----------------------------------------------------------------------
    (
        "Overtime queue: overtime_requests(org_id, status, created_at DESC)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_overtime_requests_org_status "
        "ON overtime_requests (org_id, status, created_at DESC)",
    ),

    # ----------------------------------------------------------------------
    # Shift swap + cover — manager queue + open shifts board.
    # ----------------------------------------------------------------------
    (
        "Shift swap queue: shift_swap_requests(org_id, status, created_at DESC)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_shift_swaps_status "
        "ON shift_swap_requests (org_id, status, created_at DESC)",
    ),
    (
        "Open shifts board: shift_cover_requests(org_id, status, broadcast_at DESC)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_shift_cover_status "
        "ON shift_cover_requests (org_id, status, broadcast_at DESC)",
    ),

    # ----------------------------------------------------------------------
    # Flagged entries (G10) — Hours tab follow-up review banner.
    # ----------------------------------------------------------------------
    (
        "Flagged entries (partial): time_clock_entries(org_id, staff_id) "
        "WHERE (flags->>'flagged_for_review')::boolean = true",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_time_clock_flagged "
        "ON time_clock_entries (org_id, staff_id) "
        "WHERE (flags->>'flagged_for_review')::boolean = true",
    ),
]


# Drop in reverse order. Each statement is independent so order does not
# matter for correctness — reversed only for log readability.
_DOWNGRADE_STATEMENTS: list[tuple[str, str]] = [
    (
        "Drop idx_time_clock_flagged",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_time_clock_flagged",
    ),
    (
        "Drop idx_shift_cover_status",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_shift_cover_status",
    ),
    (
        "Drop idx_shift_swaps_status",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_shift_swaps_status",
    ),
    (
        "Drop idx_overtime_requests_org_status",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_overtime_requests_org_status",
    ),
    (
        "Drop idx_timesheet_approvals_staff",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_timesheet_approvals_staff",
    ),
    (
        "Drop idx_timesheet_approvals_org_status",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_timesheet_approvals_org_status",
    ),
    (
        "Drop idx_break_records_entry",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_break_records_entry",
    ),
    (
        "Drop idx_time_clock_org_open",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_time_clock_org_open",
    ),
    (
        "Drop idx_time_clock_open",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_time_clock_open",
    ),
    (
        "Drop idx_time_clock_org_staff_date",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_time_clock_org_staff_date",
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
            logger.info("[0208] %s", description)
            op.execute(sql)


def upgrade() -> None:
    _run_outside_tx(_UPGRADE_STATEMENTS)


def downgrade() -> None:
    _run_outside_tx(_DOWNGRADE_STATEMENTS)
