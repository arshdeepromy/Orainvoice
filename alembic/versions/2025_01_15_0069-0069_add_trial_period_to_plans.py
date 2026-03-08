"""Add trial_duration and trial_duration_unit columns to subscription_plans.

Allows Global Admins to configure trial periods per plan in days, weeks, or months.

Revision ID: 0069
Revises: 0068
Create Date: 2025-01-15
"""

from alembic import op
import sqlalchemy as sa

revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subscription_plans",
        sa.Column("trial_duration", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "subscription_plans",
        sa.Column(
            "trial_duration_unit",
            sa.String(10),
            nullable=False,
            server_default="days",
        ),
    )
    op.create_check_constraint(
        "ck_subscription_plans_trial_unit",
        "subscription_plans",
        "trial_duration_unit IN ('days', 'weeks', 'months')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_subscription_plans_trial_unit", "subscription_plans")
    op.drop_column("subscription_plans", "trial_duration_unit")
    op.drop_column("subscription_plans", "trial_duration")
