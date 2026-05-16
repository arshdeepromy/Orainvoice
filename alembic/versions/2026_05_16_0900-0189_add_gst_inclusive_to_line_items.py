"""Add gst_inclusive and inclusive_price to line_items.

Persists GST-inclusive metadata on line items so that when an invoice is
loaded for editing the original inclusive pricing is preserved and GST is
not recalculated incorrectly.

Revision ID: 0189
Revises: 0188
Create Date: 2026-05-16

Requirements: Fix GST-inclusive metadata loss on invoice edit
"""
from __future__ import annotations

from alembic import op

revision: str = "0189"
down_revision: str = "0188"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE line_items
        ADD COLUMN IF NOT EXISTS gst_inclusive BOOLEAN NOT NULL DEFAULT false
    """)
    op.execute("""
        ALTER TABLE line_items
        ADD COLUMN IF NOT EXISTS inclusive_price NUMERIC(10, 2) DEFAULT NULL
    """)


def downgrade() -> None:
    op.drop_column("line_items", "inclusive_price")
    op.drop_column("line_items", "gst_inclusive")
