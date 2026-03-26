"""Widen quote_line_items.description and job_card_items.description to VARCHAR(2000).

Revision ID: 0111
Revises: 0110
Create Date: 2026-03-26
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision: str = "0111"
down_revision: str = "0110"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("quote_line_items", "description", type_=sa.String(2000), existing_type=sa.String(500), existing_nullable=True)
    op.alter_column("job_card_items", "description", type_=sa.String(2000), existing_type=sa.String(500), existing_nullable=True)


def downgrade() -> None:
    op.alter_column("quote_line_items", "description", type_=sa.String(500), existing_type=sa.String(2000), existing_nullable=True)
    op.alter_column("job_card_items", "description", type_=sa.String(500), existing_type=sa.String(2000), existing_nullable=True)
