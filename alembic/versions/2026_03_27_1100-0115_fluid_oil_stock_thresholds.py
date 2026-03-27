"""Add min_stock_volume and reorder_volume to fluid_oil_products.

Revision ID: 0115
Revises: 0114
Create Date: 2026-03-27
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision: str = "0115"
down_revision: str = "0114"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fluid_oil_products", sa.Column("min_stock_volume", sa.Numeric(12, 2), server_default=sa.text("0"), nullable=False))
    op.add_column("fluid_oil_products", sa.Column("reorder_volume", sa.Numeric(12, 2), server_default=sa.text("0"), nullable=False))


def downgrade() -> None:
    op.drop_column("fluid_oil_products", "reorder_volume")
    op.drop_column("fluid_oil_products", "min_stock_volume")
