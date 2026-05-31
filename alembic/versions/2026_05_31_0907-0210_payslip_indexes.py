"""Staff Management Phase 4 — Payslip CONCURRENTLY index pack.

Adds 9 indexes to support the Phase 4 payslips feature surface
introduced by ``0209_payslip_schema`` (``pay_periods``,
``allowance_types``, ``payslips``, ``payslip_allowances``,
``payslip_deductions``, ``payslip_reimbursements``,
``payslip_leave_lines``, ``staff_recurring_allowances``):

  - **Pay-run page (1)** —
    ``idx_payslips_org_period_status`` (org_id, pay_period_id, status)
    backs the org-wide pay-run table on ``PayRunPage`` — "show me every
    payslip in this period grouped by status".

  - **Per-staff payslip history (1)** —
    ``idx_payslips_staff_period`` (staff_id, pay_period_id DESC) backs
    the Staff Detail Payslips tab and the YTD recompute query (joins
    on staff + period to filter by ``pay_periods.pay_date``).

  - **Self-service finalised list (1, G9)** —
    ``idx_payslips_staff_status_finalised_desc`` (staff_id, status,
    finalised_at DESC) backs ``GET /api/v2/staff/me/payslips`` which
    filters ``status='finalised'`` ordered by recency.

  - **Pay-period management (2)** —
    ``idx_pay_periods_org_status`` (org_id, status, start_date DESC)
    backs the Settings → People → Pay Periods page filtered by status.
    ``idx_pay_periods_org_dates`` (org_id, start_date, end_date) — G25:
    covers the "find pay_period containing :end_date" query during
    termination (``WHERE :end_date BETWEEN start_date AND end_date``).

  - **Per-payslip line joins (3)** —
    ``idx_payslip_allowances_payslip`` (payslip_id),
    ``idx_payslip_deductions_payslip`` (payslip_id),
    ``idx_payslip_leave_lines_payslip`` (payslip_id) — back the lookup
    paths from ``payslips`` to its child line tables when rendering
    the PDF or the detail drawer. (No equivalent on
    ``payslip_reimbursements`` because reimbursements are read with the
    other lines via the same payslip_id lookup pattern; if hot, add it
    in a follow-up — for now the table is small per payslip and a seq
    scan on a one-payslip filter is fine.)

  - **Recurring allowance attach (1, partial — G4)** —
    ``idx_staff_recurring_allowances_staff`` (staff_id) **partial**
    ``WHERE active = true`` — supports the auto-attach lookup at draft-
    generation time (``generate_for_period`` queries
    ``WHERE staff_id=:s AND active=true`` per draft). Inactive rules
    are excluded from the index keeping it small.

Every index is created via ``CREATE INDEX CONCURRENTLY ... IF NOT EXISTS``
inside ``op.get_context().autocommit_block()`` so the migration is:

  - **Live-safe** — only ``SHARE UPDATE EXCLUSIVE`` lock on the table
    (does not block reads or writes).
  - **Re-runnable** — IF NOT EXISTS / IF EXISTS guards make this idempotent.

Mirrors the canonical 0202 / 0204 / 0206 / 0208 templates exactly — same
``_run_outside_tx`` helper, same per-statement logging, same reverse-order
downgrade.

Refs: design.md §3.2, tasks.md A2.

Revision ID: 0210
Revises: 0209
Create Date: 2026-05-31
"""

from __future__ import annotations

import logging

from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

revision: str = "0210"
down_revision: str = "0209"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


# Each tuple: (description, SQL).
# Indexes are independent; ordering only affects logging readability.
_UPGRADE_STATEMENTS: list[tuple[str, str]] = [
    # ----------------------------------------------------------------------
    # Pay-run page — org-wide payslips in a period grouped by status.
    # ----------------------------------------------------------------------
    (
        "Pay-run page: payslips(org_id, pay_period_id, status)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_payslips_org_period_status "
        "ON payslips (org_id, pay_period_id, status)",
    ),

    # ----------------------------------------------------------------------
    # Per-staff payslip history + YTD recompute join.
    # ----------------------------------------------------------------------
    (
        "Per-staff history: payslips(staff_id, pay_period_id DESC)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_payslips_staff_period "
        "ON payslips (staff_id, pay_period_id DESC)",
    ),

    # ----------------------------------------------------------------------
    # G9 self-service finalised list.
    # ----------------------------------------------------------------------
    (
        "Self-service list: payslips(staff_id, status, finalised_at DESC)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_payslips_staff_status_finalised_desc "
        "ON payslips (staff_id, status, finalised_at DESC)",
    ),

    # ----------------------------------------------------------------------
    # Pay-period management — Settings page + termination period selection.
    # ----------------------------------------------------------------------
    (
        "Pay-periods page: pay_periods(org_id, status, start_date DESC)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_pay_periods_org_status "
        "ON pay_periods (org_id, status, start_date DESC)",
    ),
    (
        "Termination period selection (G25): pay_periods(org_id, start_date, end_date)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_pay_periods_org_dates "
        "ON pay_periods (org_id, start_date, end_date)",
    ),

    # ----------------------------------------------------------------------
    # Per-payslip line joins — PDF render + detail drawer.
    # ----------------------------------------------------------------------
    (
        "Allowances join: payslip_allowances(payslip_id)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_payslip_allowances_payslip "
        "ON payslip_allowances (payslip_id)",
    ),
    (
        "Deductions join: payslip_deductions(payslip_id)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_payslip_deductions_payslip "
        "ON payslip_deductions (payslip_id)",
    ),
    (
        "Leave lines join: payslip_leave_lines(payslip_id)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_payslip_leave_lines_payslip "
        "ON payslip_leave_lines (payslip_id)",
    ),

    # ----------------------------------------------------------------------
    # G4 recurring allowance auto-attach lookup.
    # ----------------------------------------------------------------------
    (
        "Recurring allowance attach (partial, G4): "
        "staff_recurring_allowances(staff_id) WHERE active = true",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_recurring_allowances_staff "
        "ON staff_recurring_allowances (staff_id) "
        "WHERE active = true",
    ),
]


# Drop in reverse order. Each statement is independent so order does not
# matter for correctness — reversed only for log readability.
_DOWNGRADE_STATEMENTS: list[tuple[str, str]] = [
    (
        "Drop idx_staff_recurring_allowances_staff",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_staff_recurring_allowances_staff",
    ),
    (
        "Drop idx_payslip_leave_lines_payslip",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_payslip_leave_lines_payslip",
    ),
    (
        "Drop idx_payslip_deductions_payslip",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_payslip_deductions_payslip",
    ),
    (
        "Drop idx_payslip_allowances_payslip",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_payslip_allowances_payslip",
    ),
    (
        "Drop idx_pay_periods_org_dates",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_pay_periods_org_dates",
    ),
    (
        "Drop idx_pay_periods_org_status",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_pay_periods_org_status",
    ),
    (
        "Drop idx_payslips_staff_status_finalised_desc",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_payslips_staff_status_finalised_desc",
    ),
    (
        "Drop idx_payslips_staff_period",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_payslips_staff_period",
    ),
    (
        "Drop idx_payslips_org_period_status",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_payslips_org_period_status",
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
            logger.info("[0210] %s", description)
            op.execute(sql)


def upgrade() -> None:
    _run_outside_tx(_UPGRADE_STATEMENTS)


def downgrade() -> None:
    _run_outside_tx(_DOWNGRADE_STATEMENTS)
