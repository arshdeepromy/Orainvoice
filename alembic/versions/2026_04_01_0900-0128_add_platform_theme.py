"""Add platform_theme to platform_branding.

Revision ID: 0128
Revises: 0127
Create Date: 2026-04-01 09:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "0128"
down_revision = "0127"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "platform_branding",
        sa.Column("platform_theme", sa.String(50), nullable=False, server_default="classic"),
    )


def downgrade() -> None:
    op.drop_column("platform_branding", "platform_theme")
