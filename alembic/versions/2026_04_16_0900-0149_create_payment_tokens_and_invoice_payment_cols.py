"""Create payment_tokens table and add payment columns to invoices.

Adds the payment_tokens table for secure, time-limited access to the
public invoice payment page.  Also adds stripe_payment_intent_id and
payment_page_url columns to the invoices table.

Revision ID: 0149
Revises: 0148
Create Date: 2026-04-16

Requirements: 1.2, 3.1
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "0149"
down_revision: str = "0148"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Create payment_tokens table ────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS payment_tokens (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            token VARCHAR(64) NOT NULL,
            invoice_id UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
            org_id UUID NOT NULL REFERENCES organisations(id),
            expires_at TIMESTAMPTZ NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # Unique index on token for fast lookups
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_payment_tokens_token
        ON payment_tokens (token)
    """)

    # Index on invoice_id for finding tokens by invoice
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_payment_tokens_invoice_id
        ON payment_tokens (invoice_id)
    """)

    # ── 2. Add payment columns to invoices ────────────────────────────────
    op.execute("""
        ALTER TABLE invoices
        ADD COLUMN IF NOT EXISTS stripe_payment_intent_id VARCHAR(255)
    """)

    op.execute("""
        ALTER TABLE invoices
        ADD COLUMN IF NOT EXISTS payment_page_url VARCHAR(500)
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS payment_page_url")
    op.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS stripe_payment_intent_id")
    op.execute("DROP INDEX IF EXISTS ix_payment_tokens_invoice_id")
    op.execute("DROP INDEX IF EXISTS ix_payment_tokens_token")
    op.execute("DROP TABLE IF EXISTS payment_tokens")
