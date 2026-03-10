"""Add subject column to quotes table.

Revision ID: 0078
Revises: 0077_quote_line_items_and_fields
Create Date: 2026-03-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0078_add_subject_to_quotes"
down_revision: str = "0077_quote_line_items_and_fields"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column("quotes", sa.Column("subject", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("quotes", "subject")
