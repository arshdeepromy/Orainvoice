"""Add org-level logo BYTEA columns to organisations table.

Stores org logos in PostgreSQL (same pattern as platform_branding)
so they survive page reloads and are available for PDF rendering.

Revision ID: 0169
Revises: 0168
Create Date: 2026-04-29
"""

from alembic import op

revision = "0169"
down_revision = "0168"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE organisations "
        "ADD COLUMN IF NOT EXISTS logo_data BYTEA"
    )
    op.execute(
        "ALTER TABLE organisations "
        "ADD COLUMN IF NOT EXISTS logo_content_type VARCHAR(100)"
    )
    op.execute(
        "ALTER TABLE organisations "
        "ADD COLUMN IF NOT EXISTS logo_filename VARCHAR(255)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE organisations DROP COLUMN IF EXISTS logo_filename")
    op.execute("ALTER TABLE organisations DROP COLUMN IF EXISTS logo_content_type")
    op.execute("ALTER TABLE organisations DROP COLUMN IF EXISTS logo_data")
