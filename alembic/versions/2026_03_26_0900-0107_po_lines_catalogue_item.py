"""Add catalogue_item_id to purchase_order_lines, make product_id nullable.

Revision ID: 0107
Revises: 0106
Create Date: 2026-03-26
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0107"
down_revision: str = "0106"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Make product_id nullable
    op.alter_column("purchase_order_lines", "product_id", nullable=True)

    # Add catalogue_item_id column
    op.add_column(
        "purchase_order_lines",
        sa.Column(
            "catalogue_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("parts_catalogue.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("purchase_order_lines", "catalogue_item_id")
    op.alter_column("purchase_order_lines", "product_id", nullable=False)
