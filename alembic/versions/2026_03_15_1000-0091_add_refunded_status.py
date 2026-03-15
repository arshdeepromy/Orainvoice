"""Add 'refunded' to invoice status check constraint.

Revision ID: 0091
Revises: 0090
Create Date: 2026-03-15
"""

from alembic import op

revision = "0091"
down_revision = "0090"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop old constraint and add new one with 'refunded' status
    op.drop_constraint("ck_invoices_status", "invoices", type_="check")
    op.create_check_constraint(
        "ck_invoices_status",
        "invoices",
        "status IN ('draft','issued','partially_paid','paid','overdue','voided','refunded','partially_refunded')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_invoices_status", "invoices", type_="check")
    op.create_check_constraint(
        "ck_invoices_status",
        "invoices",
        "status IN ('draft','issued','partially_paid','paid','overdue','voided')",
    )
