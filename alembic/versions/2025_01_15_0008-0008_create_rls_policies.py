"""Create tenant_isolation RLS policies on every tenant-scoped table and
revoke UPDATE/DELETE on audit_log for immutability.

Revision ID: 0008
Revises: 0007
Create Date: 2025-01-15

Requirements: 54.1, 54.2, 51.3
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str = "0007"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

# All tenant-scoped tables that have an org_id column and RLS enabled.
TENANT_TABLES: list[str] = [
    # migration 0002 – tenant-scoped core tables
    "users",
    "sessions",
    "branches",
    "fleet_accounts",
    "customers",
    # migration 0003 – vehicle tables
    "org_vehicles",
    "customer_vehicles",
    # migration 0004 – catalogue / inventory tables
    "service_catalogue",
    "parts_catalogue",
    "suppliers",
    "labour_rates",
    # migration 0005 – invoice / payment tables
    "invoices",
    "line_items",
    "credit_notes",
    "payments",
    "invoice_sequences",
    "quote_sequences",
    "credit_note_sequences",
    # migration 0006 – quotes / job cards / bookings
    "quotes",
    "quote_line_items",
    "job_cards",
    "job_card_items",
    "time_entries",
    "recurring_schedules",
    "bookings",
    # migration 0007 – notifications / webhooks / accounting / discount / stock
    "notification_templates",
    "notification_log",
    "overdue_reminder_rules",
    "notification_preferences",
    "webhooks",
    "accounting_integrations",
    "accounting_sync_log",
    "discount_rules",
    "stock_movements",
]


def upgrade() -> None:
    # Create tenant_isolation RLS policy on every tenant-scoped table.
    # Each policy restricts rows to those matching the session-level
    # app.current_org_id variable set by the tenant middleware.
    for table in TENANT_TABLES:
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (org_id = current_setting('app.current_org_id')::uuid)"
        )

    # Audit log immutability – prevent any role from updating or deleting
    # audit entries.  The application role should only INSERT into audit_log.
    # Adjust the role name below if the deployment uses a named role instead
    # of PUBLIC.
    op.execute("REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC")


def downgrade() -> None:
    # Drop all tenant_isolation policies.
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")

    # Re-grant UPDATE/DELETE on audit_log (reverting immutability).
    op.execute("GRANT UPDATE, DELETE ON audit_log TO PUBLIC")
