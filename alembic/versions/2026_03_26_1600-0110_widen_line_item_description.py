"""Widen line_items.description from VARCHAR(500) to VARCHAR(2000).

Revision ID: 0110
Revises: 0109
Create Date: 2026-03-26
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision: str = "0110"
down_revision: str = "0109"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "line_items",
        "description",
        type_=sa.String(2000),
        existing_type=sa.String(500),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "line_items",
        "description",
        type_=sa.String(500),
        existing_type=sa.String(2000),
        existing_nullable=True,
    )
