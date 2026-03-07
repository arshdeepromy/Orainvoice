"""Create products table with all fields and indexes.

Revision ID: 0027
Revises: 0026
Create Date: 2025-01-15

Requirements: 9.1, 9.2, 9.9, 9.10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0027"
down_revision: str = "0026"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("sku", sa.String(100), nullable=True),
        sa.Column("barcode", sa.String(100), nullable=True),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("unit_of_measure", sa.String(50), server_default=sa.text("'each'"), nullable=False),
        sa.Column("sale_price", sa.Numeric(12, 2), server_default=sa.text("0"), nullable=False),
        sa.Column("cost_price", sa.Numeric(12, 2), server_default=sa.text("0"), nullable=True),
        sa.Column("tax_applicable", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("tax_rate_override", sa.Numeric(5, 2), nullable=True),
        sa.Column("stock_quantity", sa.Numeric(12, 3), server_default=sa.text("0"), nullable=False),
        sa.Column("low_stock_threshold", sa.Numeric(12, 3), server_default=sa.text("0"), nullable=True),
        sa.Column("reorder_quantity", sa.Numeric(12, 3), server_default=sa.text("0"), nullable=True),
        sa.Column("allow_backorder", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("supplier_sku", sa.String(100), nullable=True),
        sa.Column("images", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_products_org_id"),
        sa.ForeignKeyConstraint(["category_id"], ["product_categories.id"], name="fk_products_category_id"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], name="fk_products_supplier_id"),
        sa.UniqueConstraint("org_id", "sku", name="uq_products_org_sku"),
    )
    op.create_index("idx_products_org", "products", ["org_id"])
    op.create_index("idx_products_barcode", "products", ["org_id", "barcode"])
    op.create_index("idx_products_category", "products", ["org_id", "category_id"])
    op.create_index("idx_products_supplier", "products", ["org_id", "supplier_id"])
    op.create_index("idx_products_location", "products", ["location_id"])


def downgrade() -> None:
    op.drop_index("idx_products_location", table_name="products")
    op.drop_index("idx_products_supplier", table_name="products")
    op.drop_index("idx_products_category", table_name="products")
    op.drop_index("idx_products_barcode", table_name="products")
    op.drop_index("idx_products_org", table_name="products")
    op.drop_table("products")
