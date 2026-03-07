"""Add created_at column to platform_branding table.

The platform_branding table was created in migration 0022. This migration
adds the missing created_at column for completeness.

Revision ID: 0056
Revises: 0055
Create Date: 2025-01-15

Requirements: Global Branding — Task 44.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0056"
down_revision: str = "0055"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "platform_branding",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("platform_branding", "created_at")
