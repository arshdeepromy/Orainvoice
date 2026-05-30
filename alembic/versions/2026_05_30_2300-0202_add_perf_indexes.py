"""Performance index pack — closes the missing-index gaps from the perf audit.

Adds 20 indexes covering customer search (pg_trgm), hot list ordering
(org_id + created_at DESC), missing FK indexes, partial-index optimisations
for common filtered queries, and the org/UPPER(rego) compound that
`get_invoice` needs to fold the additional-vehicle lookup into the same
index access.

Every index is created via ``CREATE INDEX CONCURRENTLY ... IF NOT EXISTS``
and ``DROP INDEX CONCURRENTLY ... IF EXISTS`` so the migration is:

  - **Live-safe** — only ``SHARE UPDATE EXCLUSIVE`` lock on the table
    (does not block reads or writes).
  - **Re-runnable** — IF NOT EXISTS / IF EXISTS guards make this idempotent.

Because ``CONCURRENTLY`` cannot run inside a transaction, the operations
use a connection in AUTOCOMMIT mode rather than the default Alembic-managed
transaction.

Refs: PERFORMANCE_AUDIT.md §D-H4, §D-H5, §D-H7, §D-H9, §D-M1, §D-M5,
       §1 quick win #3, Appendix A.

Revision ID: 0202
Revises: 0201
Create Date: 2026-05-30
"""

from __future__ import annotations

import logging

from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

revision: str = "0202"
down_revision: str = "0201"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


# Each tuple: (description, SQL).
# Indexes are independent; ordering only affects logging readability.
_UPGRADE_STATEMENTS: list[tuple[str, str]] = [
    # ----------------------------------------------------------------------
    # pg_trgm extension — required for trigram GIN indexes on customer
    # search columns (D-H7). Idempotent: IF NOT EXISTS guards both the
    # CREATE EXTENSION and the dependent indexes.
    # ----------------------------------------------------------------------
    (
        "Enable pg_trgm extension (D-H7 prerequisite)",
        "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    ),

    # ----------------------------------------------------------------------
    # D-H4 — hot-list ordering. The list endpoints (invoices, quotes,
    # payments, credit_notes) all sort by ``created_at DESC`` filtered
    # by ``org_id``. Without a (org_id, created_at DESC) compound index
    # the planner falls back to ``idx_*_org`` + in-memory sort, which
    # gets slow as the per-org row count grows.
    # ----------------------------------------------------------------------
    (
        "D-H4: invoices(org_id, created_at DESC)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_invoices_org_created_desc "
        "ON invoices (org_id, created_at DESC)",
    ),
    (
        "D-H4: invoices(org_id, status, created_at DESC) — for status-filtered list",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_invoices_org_status_created "
        "ON invoices (org_id, status, created_at DESC)",
    ),
    (
        "D-H4: quotes(org_id, created_at DESC)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_quotes_org_created_desc "
        "ON quotes (org_id, created_at DESC)",
    ),
    (
        "D-H4: payments(org_id, created_at DESC)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_payments_org_created_desc "
        "ON payments (org_id, created_at DESC)",
    ),
    (
        "D-H4: credit_notes(org_id, created_at DESC)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_credit_notes_org_created_desc "
        "ON credit_notes (org_id, created_at DESC)",
    ),

    # ----------------------------------------------------------------------
    # D-H5 — missing FK indexes. Each of these tables has an org_id /
    # customer_id FK declared in the model but no covering index, so any
    # ``WHERE org_id = ?`` or ``WHERE customer_id = ?`` query falls back
    # to a sequential scan.
    # ----------------------------------------------------------------------
    (
        "D-H5: payments(org_id)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_payments_org "
        "ON payments (org_id)",
    ),
    (
        "D-H5: line_items(org_id)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_line_items_org "
        "ON line_items (org_id)",
    ),
    (
        "D-H5: credit_notes(org_id)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_credit_notes_org "
        "ON credit_notes (org_id)",
    ),
    (
        "D-H5: quote_line_items(org_id)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_quote_line_items_org "
        "ON quote_line_items (org_id)",
    ),
    (
        "D-H5: customer_vehicles(customer_id)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customer_vehicles_customer "
        "ON customer_vehicles (customer_id)",
    ),
    (
        "D-H5: org_vehicles(org_id, UPPER(rego)) — folds additional-vehicle lookup",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_org_vehicles_org_rego_upper "
        "ON org_vehicles (org_id, UPPER(rego))",
    ),

    # ----------------------------------------------------------------------
    # D-H7 — customer search. The current query path uses ILIKE on
    # first_name / last_name / company_name / email / phone / display_name,
    # none of which the existing GIN-on-tsvector index can serve. The
    # tsvector index stays in place (it's used by full-text search
    # endpoints); these trigram indexes serve the live-search ILIKE path.
    # ----------------------------------------------------------------------
    (
        "D-H7: customers(first_name) trigram GIN",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customers_first_trgm "
        "ON customers USING gin (first_name gin_trgm_ops)",
    ),
    (
        "D-H7: customers(last_name) trigram GIN",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customers_last_trgm "
        "ON customers USING gin (last_name gin_trgm_ops)",
    ),
    (
        "D-H7: customers(company_name) trigram GIN",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customers_company_trgm "
        "ON customers USING gin (company_name gin_trgm_ops)",
    ),
    (
        "D-H7: customers(display_name) trigram GIN — search hits this column too",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customers_display_trgm "
        "ON customers USING gin (display_name gin_trgm_ops)",
    ),
    (
        "D-H7: customers(lower(email)) — case-insensitive equality lookups",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customers_email_lower "
        "ON customers (lower(email))",
    ),
    (
        "D-H7: customers(phone)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customers_phone "
        "ON customers (phone)",
    ),

    # ----------------------------------------------------------------------
    # D-H9 — overdue invoices. ``mark_invoices_overdue`` cron task
    # reads every active overdue candidate; this partial index makes
    # the scan cover only the small "active and unpaid" subset of rows.
    # ----------------------------------------------------------------------
    (
        "D-H9: invoices(due_date) WHERE status IN (issued, partially_paid) AND balance_due > 0",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_invoices_due_overdue "
        "ON invoices (due_date) "
        "WHERE status IN ('issued','partially_paid') AND balance_due > 0",
    ),

    # ----------------------------------------------------------------------
    # D-M1 — partial active indexes for the common "non-anonymised"
    # and "non-dismissed" filters that appear in every customer list and
    # kiosk-QR-poll query.
    # ----------------------------------------------------------------------
    (
        "D-M1: customers(org_id) WHERE is_anonymised = false",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customers_org_active "
        "ON customers (org_id) WHERE is_anonymised = false",
    ),
    (
        "D-M1: pending_qr_sessions(org_id) WHERE dismissed_at IS NULL",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_pending_qr_active "
        "ON pending_qr_sessions (org_id) WHERE dismissed_at IS NULL",
    ),

    # ----------------------------------------------------------------------
    # D-M5 — covering for the ``has_stripe_payment`` correlated subquery
    # in ``search_invoices``. Filtered to non-refund stripe payments only;
    # ~10x smaller than the full payments table on most orgs.
    # ----------------------------------------------------------------------
    (
        "D-M5: payments(invoice_id) WHERE method='stripe' AND is_refund=false",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_payments_inv_method_refund "
        "ON payments (invoice_id) WHERE method = 'stripe' AND is_refund = false",
    ),
]


# Drop in reverse order. Each statement is independent so order does not
# matter for correctness — reversed only for log readability.
_DOWNGRADE_STATEMENTS: list[tuple[str, str]] = [
    ("Drop idx_payments_inv_method_refund", "DROP INDEX CONCURRENTLY IF EXISTS idx_payments_inv_method_refund"),
    ("Drop idx_pending_qr_active",          "DROP INDEX CONCURRENTLY IF EXISTS idx_pending_qr_active"),
    ("Drop idx_customers_org_active",       "DROP INDEX CONCURRENTLY IF EXISTS idx_customers_org_active"),
    ("Drop idx_invoices_due_overdue",       "DROP INDEX CONCURRENTLY IF EXISTS idx_invoices_due_overdue"),
    ("Drop idx_customers_phone",            "DROP INDEX CONCURRENTLY IF EXISTS idx_customers_phone"),
    ("Drop idx_customers_email_lower",      "DROP INDEX CONCURRENTLY IF EXISTS idx_customers_email_lower"),
    ("Drop idx_customers_display_trgm",     "DROP INDEX CONCURRENTLY IF EXISTS idx_customers_display_trgm"),
    ("Drop idx_customers_company_trgm",     "DROP INDEX CONCURRENTLY IF EXISTS idx_customers_company_trgm"),
    ("Drop idx_customers_last_trgm",        "DROP INDEX CONCURRENTLY IF EXISTS idx_customers_last_trgm"),
    ("Drop idx_customers_first_trgm",       "DROP INDEX CONCURRENTLY IF EXISTS idx_customers_first_trgm"),
    ("Drop idx_org_vehicles_org_rego_upper", "DROP INDEX CONCURRENTLY IF EXISTS idx_org_vehicles_org_rego_upper"),
    ("Drop idx_customer_vehicles_customer", "DROP INDEX CONCURRENTLY IF EXISTS idx_customer_vehicles_customer"),
    ("Drop idx_quote_line_items_org",       "DROP INDEX CONCURRENTLY IF EXISTS idx_quote_line_items_org"),
    ("Drop idx_credit_notes_org",           "DROP INDEX CONCURRENTLY IF EXISTS idx_credit_notes_org"),
    ("Drop idx_line_items_org",             "DROP INDEX CONCURRENTLY IF EXISTS idx_line_items_org"),
    ("Drop idx_payments_org",               "DROP INDEX CONCURRENTLY IF EXISTS idx_payments_org"),
    ("Drop idx_credit_notes_org_created_desc", "DROP INDEX CONCURRENTLY IF EXISTS idx_credit_notes_org_created_desc"),
    ("Drop idx_payments_org_created_desc",  "DROP INDEX CONCURRENTLY IF EXISTS idx_payments_org_created_desc"),
    ("Drop idx_quotes_org_created_desc",    "DROP INDEX CONCURRENTLY IF EXISTS idx_quotes_org_created_desc"),
    ("Drop idx_invoices_org_status_created", "DROP INDEX CONCURRENTLY IF EXISTS idx_invoices_org_status_created"),
    ("Drop idx_invoices_org_created_desc",  "DROP INDEX CONCURRENTLY IF EXISTS idx_invoices_org_created_desc"),
    # pg_trgm extension is intentionally left in place on downgrade —
    # other migrations or app code may come to depend on it. Removing it
    # would also drop any trigram indexes added afterwards.
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
            logger.info("[0202] %s", description)
            op.execute(sql)


def upgrade() -> None:
    _run_outside_tx(_UPGRADE_STATEMENTS)


def downgrade() -> None:
    _run_outside_tx(_DOWNGRADE_STATEMENTS)
