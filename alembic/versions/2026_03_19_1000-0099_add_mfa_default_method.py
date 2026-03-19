"""Add is_default column to user_mfa_methods.

Allows users to designate one MFA method as their preferred/default
method, which will be pre-selected during the MFA challenge flow.

Revision ID: 0099
Revises: 0098
Create Date: 2026-03-19 10:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0099"
down_revision = "0098"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_mfa_methods",
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_mfa_methods", "is_default")
