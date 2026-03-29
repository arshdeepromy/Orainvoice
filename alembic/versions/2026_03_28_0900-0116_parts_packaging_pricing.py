"""Add packaging and pricing columns to parts_catalogue.

Revision ID: 0116
Revises: 0115
Create Date: 2026-03-28
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision: str = "0116"
down_revision: str = "0115"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- 1. Add 9 new nullable columns --
    op.add_column("parts_catalogue", sa.Column("purchase_price", sa.Numeric(12, 2), nullable=True))
    op.add_column("parts_catalogue", sa.Column("packaging_type", sa.String(20), nullable=True))
    op.add_column("parts_catalogue", sa.Column("qty_per_pack", sa.Integer(), nullable=True))
    op.add_column("parts_catalogue", sa.Column("total_packs", sa.Integer(), nullable=True))
    op.add_column("parts_catalogue", sa.Column("cost_per_unit", sa.Numeric(12, 4), nullable=True))
    op.add_column("parts_catalogue", sa.Column("sell_price_per_unit", sa.Numeric(12, 4), nullable=True))
    op.add_column("parts_catalogue", sa.Column("margin", sa.Numeric(12, 4), nullable=True))
    op.add_column("parts_catalogue", sa.Column("margin_pct", sa.Numeric(8, 2), nullable=True))
    op.add_column("parts_catalogue", sa.Column("gst_mode", sa.String(10), nullable=True))

    # -- 2. Data migration: map gst_mode from legacy booleans --
    op.execute(
        "UPDATE parts_catalogue SET gst_mode = 'exempt' WHERE is_gst_exempt = true"
    )
    op.execute(
        "UPDATE parts_catalogue SET gst_mode = 'inclusive' "
        "WHERE is_gst_exempt = false AND gst_inclusive = true"
    )
    op.execute(
        "UPDATE parts_catalogue SET gst_mode = 'exclusive' "
        "WHERE is_gst_exempt = false AND gst_inclusive = false"
    )

    # -- 3. Copy default_price → sell_price_per_unit --
    op.execute(
        "UPDATE parts_catalogue SET sell_price_per_unit = default_price"
    )

    # -- 4. Set packaging defaults for all existing rows --
    op.execute(
        "UPDATE parts_catalogue "
        "SET packaging_type = 'single', qty_per_pack = 1, total_packs = 1"
    )


def downgrade() -> None:
    op.drop_column("parts_catalogue", "gst_mode")
    op.drop_column("parts_catalogue", "margin_pct")
    op.drop_column("parts_catalogue", "margin")
    op.drop_column("parts_catalogue", "sell_price_per_unit")
    op.drop_column("parts_catalogue", "cost_per_unit")
    op.drop_column("parts_catalogue", "total_packs")
    op.drop_column("parts_catalogue", "qty_per_pack")
    op.drop_column("parts_catalogue", "packaging_type")
    op.drop_column("parts_catalogue", "purchase_price")
