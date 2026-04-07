"""Create stock_transfers table for inter-branch inventory transfers.

Creates the stock_transfers table with UUID PK, foreign keys to
organisations, branches (from/to), stock_items, and users
(requested_by, approved_by). Includes a CHECK constraint on status
for the transfer state machine and indexes on org_id, from_branch_id,
to_branch_id, and status.

Revision ID: 0130
Revises: 0129
Create Date: 2026-04-02

Requirements: 17.1, 17.6
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0130"
down_revision: str = "0129"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: skip if table already exists (e.g. from HA replication)
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = 'stock_transfers'"
    ))
    if result.scalar():
        return

    op.create_table(
        "stock_transfers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("from_branch_id", UUID(as_uuid=True), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("to_branch_id", UUID(as_uuid=True), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("stock_item_id", UUID(as_uuid=True), sa.ForeignKey("stock_items.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("requested_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("approved_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('pending','approved','shipped','received','cancelled')",
            name="ck_stock_transfers_status",
        ),
    )

    # Indexes for common query patterns
    op.create_index("ix_stock_transfers_org_id", "stock_transfers", ["org_id"])
    op.create_index("ix_stock_transfers_from_branch", "stock_transfers", ["from_branch_id"])
    op.create_index("ix_stock_transfers_to_branch", "stock_transfers", ["to_branch_id"])
    op.create_index("ix_stock_transfers_status", "stock_transfers", ["status"])


def downgrade() -> None:
    op.drop_index("ix_stock_transfers_status", table_name="stock_transfers")
    op.drop_index("ix_stock_transfers_to_branch", table_name="stock_transfers")
    op.drop_index("ix_stock_transfers_from_branch", table_name="stock_transfers")
    op.drop_index("ix_stock_transfers_org_id", table_name="stock_transfers")
    op.drop_table("stock_transfers")
