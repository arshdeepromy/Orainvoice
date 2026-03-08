"""Add sms_included column to subscription_plans.

Allows Global Admins to enable/disable SMS service access per plan.

Revision ID: 0070
Revises: 0069
Create Date: 2025-01-15
"""

from alembic import op
import sqlalchemy as sa

revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subscription_plans",
        sa.Column("sms_included", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("subscription_plans", "sms_included")
