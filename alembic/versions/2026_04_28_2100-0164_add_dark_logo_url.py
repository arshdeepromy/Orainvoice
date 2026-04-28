"""Add dark_logo_url to platform_branding.

Revision ID: 0164
Revises: 0163
Create Date: 2026-04-28 21:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "0164"
down_revision = "0163"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "platform_branding",
        sa.Column("dark_logo_url", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("platform_branding", "dark_logo_url")
