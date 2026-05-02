"""Add received_quantity and discrepancy_quantity to stock_transfers.

Supports partial transfer receiving — when the destination branch
receives fewer items than were shipped, the discrepancy is recorded.

Revision ID: 0178
Revises: 0177
Create Date: 2026-05-07

Requirements: 54.1, 54.2, 54.3
"""

from __future__ import annotations

from alembic import op

revision: str = "0178"
down_revision: str = "0177"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE stock_transfers
        ADD COLUMN IF NOT EXISTS received_quantity NUMERIC(12, 3) DEFAULT NULL
    """)
    op.execute("""
        ALTER TABLE stock_transfers
        ADD COLUMN IF NOT EXISTS discrepancy_quantity NUMERIC(12, 3) DEFAULT NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE stock_transfers DROP COLUMN IF EXISTS received_quantity")
    op.execute("ALTER TABLE stock_transfers DROP COLUMN IF EXISTS discrepancy_quantity")
