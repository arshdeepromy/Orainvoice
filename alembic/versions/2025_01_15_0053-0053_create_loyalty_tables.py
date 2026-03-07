"""Create loyalty tables: loyalty_config, loyalty_tiers, loyalty_transactions.

Revision ID: 0053
Revises: 0052
Create Date: 2025-01-15

Requirements: Loyalty Module — Task 41.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0053"
down_revision: str = "0052"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # --- loyalty_config ---
    op.create_table(
        "loyalty_config",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("earn_rate", sa.Numeric(8, 4), server_default="1.0", nullable=False),
        sa.Column("redemption_rate", sa.Numeric(8, 4), server_default="0.01", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", name="uq_loyalty_config_org"),
    )

    # --- loyalty_tiers ---
    op.create_table(
        "loyalty_tiers",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("threshold_points", sa.Integer(), nullable=False),
        sa.Column("discount_percent", sa.Numeric(5, 2), server_default="0", nullable=False),
        sa.Column("benefits", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_loyalty_tiers_org", "loyalty_tiers", ["org_id"])

    # --- loyalty_transactions ---
    op.create_table(
        "loyalty_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transaction_type", sa.String(20), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("reference_type", sa.String(50), nullable=True),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_loyalty_tx_customer", "loyalty_transactions", ["customer_id"])
    op.create_index("idx_loyalty_tx_org", "loyalty_transactions", ["org_id"])


def downgrade() -> None:
    op.drop_index("idx_loyalty_tx_org", table_name="loyalty_transactions")
    op.drop_index("idx_loyalty_tx_customer", table_name="loyalty_transactions")
    op.drop_table("loyalty_transactions")
    op.drop_index("idx_loyalty_tiers_org", table_name="loyalty_tiers")
    op.drop_table("loyalty_tiers")
    op.drop_table("loyalty_config")
