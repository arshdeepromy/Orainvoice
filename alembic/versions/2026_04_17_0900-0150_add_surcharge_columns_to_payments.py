"""Add surcharge_amount and payment_method_type columns to payments.

Stores the surcharge amount and payment method type separately on each
payment record so that invoice amount_paid is never contaminated by
surcharge fees.  Surcharge configuration itself lives in the existing
org.settings JSONB column — no new tables needed.

Revision ID: 0150
Revises: 0149
Create Date: 2026-04-17

Requirements: 6.1, 6.2
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "0150"
down_revision: str = "0149"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- payments.surcharge_amount -------------------------------------------
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'payments' AND column_name = 'surcharge_amount'
            ) THEN
                ALTER TABLE payments
                ADD COLUMN surcharge_amount NUMERIC(12, 2) NOT NULL DEFAULT 0.00;
            END IF;
        END $$
    """)

    # -- payments.payment_method_type ----------------------------------------
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'payments' AND column_name = 'payment_method_type'
            ) THEN
                ALTER TABLE payments
                ADD COLUMN payment_method_type VARCHAR(50);
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.drop_column("payments", "payment_method_type")
    op.drop_column("payments", "surcharge_amount")
