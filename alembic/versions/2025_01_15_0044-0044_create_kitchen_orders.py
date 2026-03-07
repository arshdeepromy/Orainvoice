"""Create kitchen_orders table for kitchen display system.

Revision ID: 0044
Revises: 0043
Create Date: 2025-01-15

Requirements: Kitchen Display Module — Task 32.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0044"
down_revision: str = "0043"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "kitchen_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pos_transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("table_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("item_name", sa.String(200), nullable=False),
        sa.Column("quantity", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("modifications", sa.Text(), nullable=True),
        sa.Column("station", sa.String(50), server_default=sa.text("'main'"), nullable=False),
        sa.Column("status", sa.String(20), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_kitchen_orders_org_id"),
        sa.ForeignKeyConstraint(["pos_transaction_id"], ["pos_transactions.id"], name="fk_kitchen_orders_pos_txn"),
        sa.ForeignKeyConstraint(["table_id"], ["restaurant_tables.id"], name="fk_kitchen_orders_table"),
        sa.CheckConstraint(
            "status IN ('pending', 'preparing', 'prepared', 'served')",
            name="ck_kitchen_orders_status",
        ),
    )
    op.create_index("idx_kitchen_orders_org_station", "kitchen_orders", ["org_id", "station", "status"])


def downgrade() -> None:
    op.drop_index("idx_kitchen_orders_org_station", table_name="kitchen_orders")
    op.drop_table("kitchen_orders")
