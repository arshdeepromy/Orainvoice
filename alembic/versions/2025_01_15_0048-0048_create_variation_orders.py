"""Create variation_orders table for construction variation orders module.

Revision ID: 0048
Revises: 0047
Create Date: 2025-01-15

Requirements: Variation Module — Task 36.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0048"
down_revision: str = "0047"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "variation_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("variation_number", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("cost_impact", sa.Numeric(14, 2), nullable=False),
        sa.Column("status", sa.String(20), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_variation_orders_org_id"),
        sa.CheckConstraint("status IN ('draft', 'submitted', 'approved', 'rejected')", name="ck_variation_orders_status"),
        sa.UniqueConstraint("org_id", "project_id", "variation_number", name="uq_variation_orders_org_project_number"),
    )
    op.create_index("idx_variation_orders_org", "variation_orders", ["org_id"])
    op.create_index("idx_variation_orders_project", "variation_orders", ["project_id"])
    op.create_index("idx_variation_orders_status", "variation_orders", ["org_id", "status"])


def downgrade() -> None:
    op.drop_index("idx_variation_orders_status", table_name="variation_orders")
    op.drop_index("idx_variation_orders_project", table_name="variation_orders")
    op.drop_index("idx_variation_orders_org", table_name="variation_orders")
    op.drop_table("variation_orders")
