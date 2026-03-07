"""Create stock_movements table with product_id, location_id, movement_type,
quantity_change, resulting_quantity, reference_type, reference_id, performed_by.

Revision ID: 0028
Revises: 0027
Create Date: 2025-01-15

Requirements: 9.7
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0028"
down_revision: str = "0027"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "stock_movements",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("movement_type", sa.String(50), nullable=False),
        sa.Column("quantity_change", sa.Numeric(12, 3), nullable=False),
        sa.Column("resulting_quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("reference_type", sa.String(50), nullable=True),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("performed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_stock_movements_org_id"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name="fk_stock_movements_product_id"),
        sa.ForeignKeyConstraint(["performed_by"], ["users.id"], name="fk_stock_movements_performed_by"),
    )
    op.create_index("idx_stock_movements_product", "stock_movements", ["product_id"])
    op.create_index("idx_stock_movements_product_date", "stock_movements", ["product_id", "created_at"])
    op.create_index("idx_stock_movements_org_date", "stock_movements", ["org_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_stock_movements_org_date", table_name="stock_movements")
    op.drop_index("idx_stock_movements_product_date", table_name="stock_movements")
    op.drop_index("idx_stock_movements_product", table_name="stock_movements")
    op.drop_table("stock_movements")
