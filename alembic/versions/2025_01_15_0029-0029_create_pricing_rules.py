"""Create pricing_rules table with product_id, rule_type, priority,
customer_id, customer_tag, quantity ranges, date ranges, price_override,
discount_percent.

Revision ID: 0029
Revises: 0028
Create Date: 2025-01-15

Requirements: 10.1, 10.2
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0029"
down_revision: str = "0028"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "pricing_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rule_type", sa.String(50), nullable=False),
        sa.Column("priority", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("customer_tag", sa.String(100), nullable=True),
        sa.Column("min_quantity", sa.Numeric(12, 3), nullable=True),
        sa.Column("max_quantity", sa.Numeric(12, 3), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("price_override", sa.Numeric(12, 2), nullable=True),
        sa.Column("discount_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_pricing_rules_org_id"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name="fk_pricing_rules_product_id"),
    )
    op.create_index("idx_pricing_rules_product_active", "pricing_rules", ["product_id", "is_active", "priority"])
    op.create_index("idx_pricing_rules_org", "pricing_rules", ["org_id"])


def downgrade() -> None:
    op.drop_index("idx_pricing_rules_org", table_name="pricing_rules")
    op.drop_index("idx_pricing_rules_product_active", table_name="pricing_rules")
    op.drop_table("pricing_rules")
