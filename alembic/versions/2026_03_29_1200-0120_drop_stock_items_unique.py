"""Drop unique constraint on stock_items to allow multiple entries per catalogue item.

Revision ID: 0120
Revises: 0119
Create Date: 2026-03-29
"""
from __future__ import annotations
from alembic import op

revision: str = "0120"
down_revision: str = "0119"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_stock_items_org_catalogue", "stock_items", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_stock_items_org_catalogue",
        "stock_items",
        ["org_id", "catalogue_item_id", "catalogue_type"],
    )
