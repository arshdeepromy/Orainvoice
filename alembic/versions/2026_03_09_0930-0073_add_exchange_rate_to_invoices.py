"""Add exchange_rate_to_nzd column to invoices table.

Revision ID: 0073_add_exchange_rate_to_invoices
Revises: 0072_enhance_customer_fields
Create Date: 2026-03-09 09:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0073_add_exchange_rate_to_invoices"
down_revision = "0072_enhance_customer_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add exchange_rate_to_nzd column to invoices table
    op.add_column(
        "invoices",
        sa.Column(
            "exchange_rate_to_nzd",
            sa.Numeric(12, 6),
            nullable=False,
            server_default="1.000000",
        ),
    )


def downgrade() -> None:
    op.drop_column("invoices", "exchange_rate_to_nzd")
