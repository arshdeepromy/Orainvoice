"""Add pricing override columns to stock_items.

Revision ID: 0118
Revises: 0117
Create Date: 2026-03-29
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision: str = "0118"
down_revision: str = "0117"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stock_items", sa.Column("purchase_price", sa.Numeric(12, 4), nullable=True))
    op.add_column("stock_items", sa.Column("sell_price", sa.Numeric(12, 4), nullable=True))
    op.add_column("stock_items", sa.Column("cost_per_unit", sa.Numeric(12, 4), nullable=True))


def downgrade() -> None:
    op.drop_column("stock_items", "cost_per_unit")
    op.drop_column("stock_items", "sell_price")
    op.drop_column("stock_items", "purchase_price")
