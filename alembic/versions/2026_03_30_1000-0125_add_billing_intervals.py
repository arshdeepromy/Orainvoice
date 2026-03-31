"""Add billing interval support to subscription_plans and organisations.

Adds interval_config JSONB column to subscription_plans for per-interval
discount configuration, and billing_interval VARCHAR(20) column to
organisations for tracking each org's chosen billing cadence.

Backfills existing plans with default monthly-only config and existing
orgs with billing_interval = 'monthly'. Preserves monthly_price_nzd
column unchanged.

Revision ID: 0125
Revises: 0124
Create Date: 2026-03-30

Requirements: 10.1, 10.2, 10.3, 10.4, 10.5
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0125"
down_revision: str = "0124"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- 1. Add interval_config JSONB column to subscription_plans --
    op.add_column(
        "subscription_plans",
        sa.Column("interval_config", JSONB, nullable=False, server_default="[]"),
    )

    # -- 2. Add billing_interval column to organisations --
    op.add_column(
        "organisations",
        sa.Column(
            "billing_interval",
            sa.String(20),
            nullable=False,
            server_default="monthly",
        ),
    )

    # -- 3. Add check constraint for valid billing interval values --
    op.create_check_constraint(
        "ck_organisations_billing_interval",
        "organisations",
        "billing_interval IN ('weekly', 'fortnightly', 'monthly', 'annual')",
    )

    # -- 4. Backfill existing plans with default monthly-only config --
    op.execute(
        """
        UPDATE subscription_plans
        SET interval_config = '[{"interval": "monthly", "enabled": true, "discount_percent": 0}]'::jsonb
        WHERE interval_config = '[]'::jsonb
        """
    )

    # -- 5. Backfill existing orgs with billing_interval = 'monthly' --
    # (Already handled by server_default, but explicit for clarity)
    op.execute(
        """
        UPDATE organisations
        SET billing_interval = 'monthly'
        WHERE billing_interval IS NULL
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_organisations_billing_interval", "organisations", type_="check"
    )
    op.drop_column("organisations", "billing_interval")
    op.drop_column("subscription_plans", "interval_config")
