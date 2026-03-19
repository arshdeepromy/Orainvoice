"""Add first_name and last_name columns to users table.

Revision ID: 0097
Revises: 0096
Create Date: 2026-03-18 11:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "0097"
down_revision = "0096"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Columns may already exist (added via direct SQL), so use raw DDL with IF NOT EXISTS
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name VARCHAR(100)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name VARCHAR(100)")


def downgrade() -> None:
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
