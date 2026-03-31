"""Add next_billing_date column to organisations.

Adds a nullable timezone-aware datetime column for tracking when each
organisation is next due for a recurring billing charge. Used by the
direct PaymentIntent billing engine instead of Stripe Subscriptions.

Revision ID: 0126
Revises: 0125
Create Date: 2026-03-31

Requirements: 1.1
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision: str = "0126"
down_revision: str = "0125"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organisations",
        sa.Column("next_billing_date", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organisations", "next_billing_date")
