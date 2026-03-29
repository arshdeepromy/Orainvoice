"""Create stock_items table and add stock_item_id to stock_movements.

Revision ID: 0117
Revises: 0116
Create Date: 2026-03-29

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0117"
down_revision: str = "0116"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- 1. Create stock_items table --
    op.create_table(
        "stock_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("catalogue_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("catalogue_type", sa.String(10), nullable=False),
        sa.Column("current_quantity", sa.Numeric(12, 3), server_default=sa.text("0"), nullable=False),
        sa.Column("min_threshold", sa.Numeric(12, 3), server_default=sa.text("0"), nullable=False),
        sa.Column("reorder_quantity", sa.Numeric(12, 3), server_default=sa.text("0"), nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("barcode", sa.String(255), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_stock_items_org_id"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], name="fk_stock_items_supplier_id"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_stock_items_created_by"),
        sa.CheckConstraint("catalogue_type IN ('part', 'tyre', 'fluid')", name="ck_stock_items_catalogue_type"),
        sa.UniqueConstraint("org_id", "catalogue_item_id", "catalogue_type", name="uq_stock_items_org_catalogue"),
    )

    # -- 2. Indexes on stock_items --
    op.create_index("idx_stock_items_org", "stock_items", ["org_id"])
    op.create_index(
        "idx_stock_items_barcode",
        "stock_items",
        ["barcode"],
        postgresql_where=sa.text("barcode IS NOT NULL"),
    )

    # -- 3. Make product_id nullable (stock-item-linked movements don't need it) --
    op.alter_column("stock_movements", "product_id", nullable=True)

    # -- 4. Add stock_item_id FK column to stock_movements --
    op.add_column(
        "stock_movements",
        sa.Column("stock_item_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_stock_movements_stock_item_id",
        "stock_movements",
        "stock_items",
        ["stock_item_id"],
        ["id"],
    )

    # -- 4. Partial index on stock_movements.stock_item_id --
    op.create_index(
        "idx_stock_movements_stock_item",
        "stock_movements",
        ["stock_item_id"],
        postgresql_where=sa.text("stock_item_id IS NOT NULL"),
    )


def downgrade() -> None:
    # -- Reverse order: drop index, FK, column on stock_movements, then drop stock_items --
    op.drop_index("idx_stock_movements_stock_item", table_name="stock_movements")
    op.drop_constraint("fk_stock_movements_stock_item_id", "stock_movements", type_="foreignkey")
    op.drop_column("stock_movements", "stock_item_id")
    op.alter_column("stock_movements", "product_id", nullable=False)
    op.drop_index("idx_stock_items_barcode", table_name="stock_items")
    op.drop_index("idx_stock_items_org", table_name="stock_items")
    op.drop_table("stock_items")
