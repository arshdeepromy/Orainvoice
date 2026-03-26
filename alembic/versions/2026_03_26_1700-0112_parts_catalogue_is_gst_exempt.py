"""Add is_gst_exempt to parts_catalogue (was missing from original schema).

Revision ID: 0112
Revises: 0111
Create Date: 2026-03-26
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision: str = "0112"
down_revision: str = "0111"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "parts_catalogue",
        sa.Column("is_gst_exempt", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("parts_catalogue", "is_gst_exempt")
