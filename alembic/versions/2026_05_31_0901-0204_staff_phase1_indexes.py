"""Staff Management Phase 1 — CONCURRENTLY index pack.

Adds 10 indexes to support the Phase 1 staff feature surface:

  - **Pay rate ledger access (2)** —
    ``idx_staff_pay_rates_staff_effective`` (staff_id, effective_from DESC)
    and ``idx_staff_pay_rates_org`` (org_id) cover the pay-rate history
    list endpoint and the FK lookups without forcing a sequential scan.

  - **Compliance surfaces on staff_members (5)** — partial indexes,
    each filtered to ``is_active = true`` so the index footprint stays
    proportional to the active workforce, not the lifetime total:
      * ``idx_staff_review_due``          — anniversary review query
      * ``idx_staff_probation_end``       — probation expiry surface
      * ``idx_staff_visa_expiry``         — visa expiry surface (G2)
      * ``idx_staff_roster_email_optin``  — roster broadcast email scan
      * ``idx_staff_roster_sms_optin``    — roster broadcast SMS scan

  - **G1/G3 missing-field counters (2)** — partial indexes that back the
    new ``compliance_summary.missing_employee_id`` and
    ``compliance_summary.missing_start_date`` aggregates on
    ``GET /api/v2/staff``:
      * ``idx_staff_missing_employee_id`` — ``WHERE is_active=true AND employee_id IS NULL``
      * ``idx_staff_missing_start_date``  — ``WHERE is_active=true AND employment_start_date IS NULL``

  - **Public roster viewer lookup (1)** —
    ``idx_staff_roster_view_tokens_token`` UNIQUE on ``(token)`` so the
    unauthenticated ``GET /api/v2/public/staff-roster/:token`` endpoint
    is an O(1) index hit (G8 — token leak protection requires the
    lookup to never escalate to a sequential scan as the table grows).

Every index is created via ``CREATE INDEX CONCURRENTLY ... IF NOT EXISTS``
inside ``op.get_context().autocommit_block()`` so the migration is:

  - **Live-safe** — only ``SHARE UPDATE EXCLUSIVE`` lock on the table
    (does not block reads or writes).
  - **Re-runnable** — IF NOT EXISTS / IF EXISTS guards make this idempotent.

Mirrors the canonical 0202 template (``0202_add_perf_indexes``) exactly —
same ``_run_outside_tx`` helper, same per-statement logging, same
reverse-order downgrade.

Refs: performance-and-resilience steering, requirements R6,
       gap-analysis G1, G3, G8.

Revision ID: 0204
Revises: 0203
Create Date: 2026-05-31
"""

from __future__ import annotations

import logging

from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

revision: str = "0204"
down_revision: str = "0203"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


# Each tuple: (description, SQL).
# Indexes are independent; ordering only affects logging readability.
_UPGRADE_STATEMENTS: list[tuple[str, str]] = [
    # ----------------------------------------------------------------------
    # Pay-rate ledger access — staff history list + FK by org.
    # ----------------------------------------------------------------------
    (
        "Pay rate ledger: staff_pay_rates(staff_id, effective_from DESC)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_pay_rates_staff_effective "
        "ON staff_pay_rates (staff_id, effective_from DESC)",
    ),
    (
        "Pay rate ledger: staff_pay_rates(org_id)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_pay_rates_org "
        "ON staff_pay_rates (org_id)",
    ),

    # ----------------------------------------------------------------------
    # Compliance surfaces on staff_members — partial indexes filtered to
    # is_active=true so the index covers only the active workforce.
    # ----------------------------------------------------------------------
    (
        "Anniversary review surface — pay-review-due query",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_review_due "
        "ON staff_members (org_id, last_pay_review_date) "
        "WHERE is_active = true",
    ),
    (
        "Probation expiry surface",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_probation_end "
        "ON staff_members (org_id, probation_end_date) "
        "WHERE is_active = true AND probation_end_date IS NOT NULL",
    ),
    (
        "Visa expiry surface (G2)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_visa_expiry "
        "ON staff_members (org_id, visa_expiry_date) "
        "WHERE is_active = true AND visa_expiry_date IS NOT NULL",
    ),
    (
        "Roster broadcast scan — active staff with email opt-in",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_roster_email_optin "
        "ON staff_members (org_id) "
        "WHERE is_active = true AND weekly_roster_email_enabled = true",
    ),
    (
        "Roster broadcast scan — active staff with SMS opt-in",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_roster_sms_optin "
        "ON staff_members (org_id) "
        "WHERE is_active = true AND weekly_roster_sms_enabled = true",
    ),

    # ----------------------------------------------------------------------
    # G1/G3 — missing-field compliance counters. Partial indexes back
    # the COUNT(*) FILTER aggregates on GET /api/v2/staff.
    # ----------------------------------------------------------------------
    (
        "G1: missing employee_id — supports compliance_summary.missing_employee_id",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_missing_employee_id "
        "ON staff_members (org_id) "
        "WHERE is_active = true AND employee_id IS NULL",
    ),
    (
        "G3: missing employment_start_date — supports compliance_summary.missing_start_date",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_missing_start_date "
        "ON staff_members (org_id) "
        "WHERE is_active = true AND employment_start_date IS NULL",
    ),

    # ----------------------------------------------------------------------
    # Public roster viewer lookup — token-only WHERE, must be O(1).
    # UNIQUE because the application contract guarantees token uniqueness
    # and the public endpoint relies on a single-row hit.
    # ----------------------------------------------------------------------
    (
        "Public viewer lookup: staff_roster_view_tokens(token) UNIQUE",
        "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_roster_view_tokens_token "
        "ON staff_roster_view_tokens (token)",
    ),
]


# Drop in reverse order. Each statement is independent so order does not
# matter for correctness — reversed only for log readability.
_DOWNGRADE_STATEMENTS: list[tuple[str, str]] = [
    (
        "Drop idx_staff_roster_view_tokens_token",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_staff_roster_view_tokens_token",
    ),
    (
        "Drop idx_staff_missing_start_date",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_staff_missing_start_date",
    ),
    (
        "Drop idx_staff_missing_employee_id",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_staff_missing_employee_id",
    ),
    (
        "Drop idx_staff_roster_sms_optin",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_staff_roster_sms_optin",
    ),
    (
        "Drop idx_staff_roster_email_optin",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_staff_roster_email_optin",
    ),
    (
        "Drop idx_staff_visa_expiry",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_staff_visa_expiry",
    ),
    (
        "Drop idx_staff_probation_end",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_staff_probation_end",
    ),
    (
        "Drop idx_staff_review_due",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_staff_review_due",
    ),
    (
        "Drop idx_staff_pay_rates_org",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_staff_pay_rates_org",
    ),
    (
        "Drop idx_staff_pay_rates_staff_effective",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_staff_pay_rates_staff_effective",
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
            logger.info("[0204] %s", description)
            op.execute(sql)


def upgrade() -> None:
    _run_outside_tx(_UPGRADE_STATEMENTS)


def downgrade() -> None:
    _run_outside_tx(_DOWNGRADE_STATEMENTS)
