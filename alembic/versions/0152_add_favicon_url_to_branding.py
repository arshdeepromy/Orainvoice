"""Add favicon_url to platform_branding.

Revision ID: 0152
Revises: 0151
"""

from alembic import op
import sqlalchemy as sa

revision = "0152"
down_revision = "0151"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "platform_branding",
        sa.Column("favicon_url", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("platform_branding", "favicon_url")
