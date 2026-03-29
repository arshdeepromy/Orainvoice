"""Add stock_item_id column to line_items table.

Revision ID: 0121
Revises: 0120
Create Date: 2026-03-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0121"
down_revision: str = "0120"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "line_items",
        sa.Column("stock_item_id", UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("line_items", "stock_item_id")
