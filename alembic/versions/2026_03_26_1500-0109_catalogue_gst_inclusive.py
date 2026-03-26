"""Add gst_inclusive column to items_catalogue and parts_catalogue.

Revision ID: 0109
Revises: 0108
Create Date: 2026-03-26
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision: str = "0109"
down_revision: str = "0108"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("items_catalogue", sa.Column("gst_inclusive", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("parts_catalogue", sa.Column("gst_inclusive", sa.Boolean(), server_default=sa.text("false"), nullable=False))


def downgrade() -> None:
    op.drop_column("items_catalogue", "gst_inclusive")
    op.drop_column("parts_catalogue", "gst_inclusive")
