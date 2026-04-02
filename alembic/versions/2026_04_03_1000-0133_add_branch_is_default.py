"""Add is_default column to branches table.

Adds a boolean is_default column to the branches table so that
the auto-created "Main" branch can be marked as the default branch
for each organisation.

Revision ID: 0133
Revises: 0132
Create Date: 2026-04-03

Requirements: 14.1, 14.2
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "0133"
down_revision: str = "0132"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "branches",
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("branches", "is_default")
