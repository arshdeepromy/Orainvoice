"""Create pos_transactions table.

Revision ID: 0040
Revises: 0039
Create Date: 2025-01-15

Requirements: POS Module — Task 27.2
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0040"
down_revision: str = "0039"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "pos_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("table_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("offline_transaction_id", sa.String(100), nullable=True),
        sa.Column("payment_method", sa.String(20), nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(12, 2), server_default=sa.text("0"), nullable=False),
        sa.Column("tip_amount", sa.Numeric(12, 2), server_default=sa.text("0"), nullable=False),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
        sa.Column("cash_tendered", sa.Numeric(12, 2), nullable=True),
        sa.Column("change_given", sa.Numeric(12, 2), nullable=True),
        sa.Column("is_offline_sync", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("sync_status", sa.String(20), nullable=True),
        sa.Column("sync_conflicts", postgresql.JSONB(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_pos_transactions_org_id"),
        sa.ForeignKeyConstraint(["session_id"], ["pos_sessions.id"], name="fk_pos_transactions_session_id"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], name="fk_pos_transactions_invoice_id", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], name="fk_pos_transactions_customer_id"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_pos_transactions_created_by"),
        # NOTE: table_id FK to restaurant_tables is omitted — that table is created in Task 31.
        # The FK constraint will be added in a future migration after restaurant_tables exists.
    )
    op.create_index("idx_pos_transactions_org", "pos_transactions", ["org_id", "created_at"])
    op.create_index("idx_pos_transactions_offline", "pos_transactions", ["offline_transaction_id"])


def downgrade() -> None:
    op.drop_index("idx_pos_transactions_offline", table_name="pos_transactions")
    op.drop_index("idx_pos_transactions_org", table_name="pos_transactions")
    op.drop_table("pos_transactions")
