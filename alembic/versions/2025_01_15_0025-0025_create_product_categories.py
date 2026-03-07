"""Create product_categories table with org_id, name, parent_id, display_order.

Revision ID: 0025
Revises: 0024
Create Date: 2025-01-15

Requirements: 9.2
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0025"
down_revision: str = "0024"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "product_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("display_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_product_categories_org_id"),
        sa.ForeignKeyConstraint(["parent_id"], ["product_categories.id"], name="fk_product_categories_parent_id"),
    )
    op.create_index("idx_product_categories_org", "product_categories", ["org_id"])
    op.create_index("idx_product_categories_parent", "product_categories", ["org_id", "parent_id"])


def downgrade() -> None:
    op.drop_index("idx_product_categories_parent", table_name="product_categories")
    op.drop_index("idx_product_categories_org", table_name="product_categories")
    op.drop_table("product_categories")
