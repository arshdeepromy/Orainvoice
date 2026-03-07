"""Create tips and tip_allocations tables for tipping module.

Revision ID: 0045
Revises: 0044
Create Date: 2025-01-15

Requirements: Tipping Module — Task 33.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0045"
down_revision: str = "0044"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # --- tips ---
    op.create_table(
        "tips",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pos_transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("payment_method", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_tips_org_id"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], name="fk_tips_invoice_id"),
        sa.ForeignKeyConstraint(["pos_transaction_id"], ["pos_transactions.id"], name="fk_tips_pos_transaction_id"),
    )
    op.create_index("idx_tips_org", "tips", ["org_id"])
    op.create_index("idx_tips_org_created", "tips", ["org_id", "created_at"])

    # --- tip_allocations ---
    op.create_table(
        "tip_allocations",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("staff_member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tip_id"], ["tips.id"], name="fk_tip_allocations_tip_id"),
    )
    op.create_index("idx_tip_allocations_staff", "tip_allocations", ["staff_member_id"])
    op.create_index("idx_tip_allocations_tip", "tip_allocations", ["tip_id"])


def downgrade() -> None:
    op.drop_index("idx_tip_allocations_tip", table_name="tip_allocations")
    op.drop_index("idx_tip_allocations_staff", table_name="tip_allocations")
    op.drop_table("tip_allocations")
    op.drop_index("idx_tips_org_created", table_name="tips")
    op.drop_index("idx_tips_org", table_name="tips")
    op.drop_table("tips")
