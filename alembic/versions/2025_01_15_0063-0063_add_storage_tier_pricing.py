"""Add storage_tier_pricing column to subscription_plans.

Revision ID: 0063
Revises: 0062
Create Date: 2025-01-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subscription_plans",
        sa.Column("storage_tier_pricing", JSONB, nullable=True, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("subscription_plans", "storage_tier_pricing")
