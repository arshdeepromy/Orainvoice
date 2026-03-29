"""Add reserved_quantity column to stock_items for inventory holds.

Revision ID: 0122
Revises: 0121
Create Date: 2026-03-29
"""
from alembic import op
import sqlalchemy as sa

revision: str = "0122"
down_revision: str = "0121"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stock_items",
        sa.Column("reserved_quantity", sa.Numeric(12, 3), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("stock_items", "reserved_quantity")
