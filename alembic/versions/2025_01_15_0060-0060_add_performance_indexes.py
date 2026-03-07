"""Add performance indexes for common query patterns.

Revision ID: 0060
Revises: 0059
Create Date: 2025-01-15

Requirements: 43 — Storage and Performance Management (Task 52.7)
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0060"
down_revision: str = "0059"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # Invoices by org + status + date (common list/filter query)
    op.create_index(
        "idx_invoices_org_status_date",
        "invoices",
        ["org_id", "status", "issue_date"],
    )

    # Customers by org + search (name lookup)
    op.create_index(
        "idx_customers_org_name",
        "customers",
        ["org_id", "name"],
    )

    # Products by org + SKU (barcode/SKU lookup)
    op.create_index(
        "idx_products_org_sku",
        "products",
        ["org_id", "sku"],
        unique=True,
    )

    # Jobs by org + status (kanban board, filtered lists)
    op.create_index(
        "idx_jobs_org_status_v2",
        "jobs",
        ["org_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("idx_jobs_org_status_v2", table_name="jobs")
    op.drop_index("idx_products_org_sku", table_name="products")
    op.drop_index("idx_customers_org_name", table_name="customers")
    op.drop_index("idx_invoices_org_status_date", table_name="invoices")
