"""Create fluid_oil_products table.

Revision ID: 0113
Revises: 0112
Create Date: 2026-03-27
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0113"
down_revision: str = "0112"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fluid_oil_products",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("fluid_type", sa.String(10), nullable=False),  # 'oil' or 'non-oil'
        sa.Column("oil_type", sa.String(30), nullable=True),  # engine, hydraulic, brake, gear, transmission, power_steering
        sa.Column("grade", sa.String(50), nullable=True),  # e.g. 5W-30
        sa.Column("synthetic_type", sa.String(20), nullable=True),  # semi_synthetic, full_synthetic, mineral
        sa.Column("product_name", sa.String(255), nullable=True),  # for non-oil
        sa.Column("brand_name", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("pack_size", sa.String(50), nullable=True),  # for non-oil
        # Pack / purchase format
        sa.Column("qty_per_pack", sa.Numeric(10, 2), nullable=True),
        sa.Column("unit_type", sa.String(10), server_default=sa.text("'litre'"), nullable=False),  # litre or gallon
        sa.Column("container_type", sa.String(20), nullable=True),  # drum, box, bottle, bulk_bag
        sa.Column("total_quantity", sa.Numeric(10, 2), nullable=True),
        sa.Column("total_volume", sa.Numeric(12, 2), nullable=True),  # auto-calculated
        # Pricing
        sa.Column("purchase_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("gst_mode", sa.String(10), nullable=True),  # inclusive, exclusive, exempt
        sa.Column("cost_per_unit", sa.Numeric(12, 4), nullable=True),  # auto-calculated
        sa.Column("sell_price_per_unit", sa.Numeric(12, 4), nullable=True),
        sa.Column("margin", sa.Numeric(12, 4), nullable=True),  # auto-calculated
        sa.Column("margin_pct", sa.Numeric(8, 2), nullable=True),  # auto-calculated
        # Stock
        sa.Column("current_stock_volume", sa.Numeric(12, 2), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        # Timestamps
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fluid_oil_products_org_id", "fluid_oil_products", ["org_id"])


def downgrade() -> None:
    op.drop_index("ix_fluid_oil_products_org_id")
    op.drop_table("fluid_oil_products")
