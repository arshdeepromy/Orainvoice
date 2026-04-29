"""Add unique constraint on billing_receipts.stripe_payment_intent_id.

Prevents duplicate receipt records from webhook re-delivery or race
conditions.  Also cleans up any existing duplicates by keeping only
the earliest row per stripe_payment_intent_id.

Revision ID: 0168
Revises: 0167
Create Date: 2026-04-29

Fixes: Duplicate billing receipt for Advance Automotive (ISSUE-107)
"""

from alembic import op

revision = "0168"
down_revision = "0167"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Delete duplicate receipts, keeping the earliest per payment intent ---
    op.execute(
        """
        DELETE FROM billing_receipts
        WHERE id NOT IN (
            SELECT DISTINCT ON (stripe_payment_intent_id) id
            FROM billing_receipts
            WHERE stripe_payment_intent_id IS NOT NULL
            ORDER BY stripe_payment_intent_id, created_at ASC
        )
        AND stripe_payment_intent_id IS NOT NULL
        """
    )

    # --- Add unique index (partial — only for non-null values) ---
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_billing_receipts_stripe_pi
            ON billing_receipts (stripe_payment_intent_id)
            WHERE stripe_payment_intent_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_billing_receipts_stripe_pi")
