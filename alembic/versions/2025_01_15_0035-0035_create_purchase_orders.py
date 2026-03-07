"""Create purchase_orders and purchase_order_lines tables.

Revision ID: 0035
Revises: 0034
Create Date: 2025-01-15

Requirements: Requirement 16 — Purchase Order Module — Task 23.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0035"
down_revision: str = "0034"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "purchase_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("po_number", sa.String(50), nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(20), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("expected_delivery", sa.Date(), nullable=True),
        sa.Column("total_amount", sa.Numeric(12, 2), server_default=sa.text("0"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_purchase_orders_org_id"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], name="fk_purchase_orders_supplier_id"),
        sa.UniqueConstraint("org_id", "po_number", name="uq_purchase_orders_org_po_number"),
    )
    op.create_index("idx_purchase_orders_org", "purchase_orders", ["org_id"])
    op.create_index("idx_purchase_orders_supplier", "purchase_orders", ["supplier_id"])
    op.create_index("idx_purchase_orders_status", "purchase_orders", ["org_id", "status"])

    op.create_table(
        "purchase_order_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("po_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("quantity_ordered", sa.Numeric(12, 3), nullable=False),
        sa.Column("quantity_received", sa.Numeric(12, 3), server_default=sa.text("0"), nullable=False),
        sa.Column("unit_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(12, 2), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["po_id"], ["purchase_orders.id"], name="fk_po_lines_po_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name="fk_po_lines_product_id"),
    )
    op.create_index("idx_po_lines_po", "purchase_order_lines", ["po_id"])
    op.create_index("idx_po_lines_product", "purchase_order_lines", ["product_id"])


def downgrade() -> None:
    op.drop_index("idx_po_lines_product", table_name="purchase_order_lines")
    op.drop_index("idx_po_lines_po", table_name="purchase_order_lines")
    op.drop_table("purchase_order_lines")
    op.drop_index("idx_purchase_orders_status", table_name="purchase_orders")
    op.drop_index("idx_purchase_orders_supplier", table_name="purchase_orders")
    op.drop_index("idx_purchase_orders_org", table_name="purchase_orders")
    op.drop_table("purchase_orders")
