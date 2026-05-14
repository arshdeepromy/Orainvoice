"""Add cost_price column to line_items table for internal profit/margin
tracking.

- cost_price: Numeric(12, 2), nullable, no default
- Snapshot of purchase/cost price at time item was added to invoice
- Internal only — never shown to customers or in PDFs

Revision ID: 0186
Revises: 0185
Create Date: 2026-05-14

Requirements: Internal profitability tracking
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0186"
down_revision = "0185"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE line_items
        ADD COLUMN IF NOT EXISTS cost_price NUMERIC(12, 2) DEFAULT NULL
    """)


def downgrade() -> None:
    op.drop_column("line_items", "cost_price")
