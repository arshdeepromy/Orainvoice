"""Create billing_receipts table.

Stores a record of each recurring billing charge with full breakdown
(plan, overages, GST, processing fee, total).

Revision ID: 0148
Revises: 0147
Create Date: 2026-04-15
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "0148"
down_revision: str = "0147"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS billing_receipts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            stripe_payment_intent_id VARCHAR(255),
            billing_date TIMESTAMPTZ NOT NULL,
            billing_interval VARCHAR(20) NOT NULL,

            -- Breakdown (all in cents)
            plan_amount_cents INTEGER NOT NULL,
            sms_overage_cents INTEGER NOT NULL DEFAULT 0,
            carjam_overage_cents INTEGER NOT NULL DEFAULT 0,
            storage_addon_cents INTEGER NOT NULL DEFAULT 0,
            subtotal_excl_gst_cents INTEGER NOT NULL,
            gst_amount_cents INTEGER NOT NULL,
            processing_fee_cents INTEGER NOT NULL,
            total_amount_cents INTEGER NOT NULL,

            -- Descriptive
            plan_name VARCHAR(255) NOT NULL,
            sms_overage_count INTEGER NOT NULL DEFAULT 0,
            carjam_overage_count INTEGER NOT NULL DEFAULT 0,
            storage_addon_gb INTEGER NOT NULL DEFAULT 0,

            -- Metadata
            currency VARCHAR(3) NOT NULL DEFAULT 'nzd',
            status VARCHAR(20) NOT NULL DEFAULT 'paid',

            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # Add currency column if table already existed without it
    op.execute("""
        ALTER TABLE billing_receipts
        ADD COLUMN IF NOT EXISTS currency VARCHAR(3) NOT NULL DEFAULT 'nzd'
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_billing_receipts_org_id
        ON billing_receipts (org_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_billing_receipts_billing_date
        ON billing_receipts (billing_date)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_billing_receipts_billing_date")
    op.execute("DROP INDEX IF EXISTS ix_billing_receipts_org_id")
    op.execute("DROP TABLE IF EXISTS billing_receipts")
