"""Backfill cost_price on existing line_items from stock_items and catalogue.

Revision ID: 0187
Revises: 0186
Create Date: 2026-05-14
"""
from __future__ import annotations

from alembic import op


revision = "0187"
down_revision = "0186"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Backfill from stock_items (purchase_price first, then cost_per_unit)
    op.execute("""
        UPDATE line_items li
        SET cost_price = COALESCE(si.purchase_price, si.cost_per_unit)
        FROM stock_items si
        WHERE li.stock_item_id = si.id
          AND li.cost_price IS NULL
          AND COALESCE(si.purchase_price, si.cost_per_unit) IS NOT NULL
    """)

    # 2. Backfill from parts_catalogue for items without stock_item_id
    op.execute("""
        UPDATE line_items li
        SET cost_price = pc.purchase_price
        FROM parts_catalogue pc
        WHERE li.catalogue_item_id = pc.id
          AND li.stock_item_id IS NULL
          AND li.cost_price IS NULL
          AND pc.purchase_price IS NOT NULL
    """)


def downgrade() -> None:
    # Cannot reliably undo a backfill — leave as-is
    pass
