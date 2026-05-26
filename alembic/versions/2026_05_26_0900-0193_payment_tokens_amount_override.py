"""Add amount_override and last_pi_amount_cents columns to payment_tokens.

Adds two nullable columns to ``payment_tokens`` to support the QR
partial-payment flow:

- ``amount_override NUMERIC(12,2) NULL`` — set when a QR session is
  created for a partial amount; the public payment page surfaces this
  value as the "amount due now" instead of ``invoice.balance_due``.
  NULL preserves the existing behaviour (use the invoice's balance).
- ``last_pi_amount_cents BIGINT NULL`` — cached cents value of the
  PaymentIntent's last-known amount. Used by
  ``create_qr_session_for_existing_invoice`` to decide whether the
  current PI can be reused (same amount) or must be cancelled and
  replaced (different amount), without a synchronous Stripe API call.
  Refreshed on every PI create and update-surcharge.

Both columns are nullable with no server default so existing rows
get NULL automatically — no data backfill required, no table rewrite,
and the change is fully backwards compatible.

Revision ID: 0193
Revises: 0192
Create Date: 2026-05-26

Requirements: 5.1, 6.1
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0193"
down_revision: str = "0192"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "payment_tokens",
        sa.Column(
            "amount_override",
            sa.Numeric(12, 2),
            nullable=True,
            comment=(
                "Partial-payment amount for the QR partial-payment flow. "
                "NULL means use invoice.balance_due (default behaviour)."
            ),
        ),
    )
    op.add_column(
        "payment_tokens",
        sa.Column(
            "last_pi_amount_cents",
            sa.BigInteger(),
            nullable=True,
            comment=(
                "Cached cents value of the PaymentIntent's last-known "
                "amount, used by create_qr_session_for_existing_invoice "
                "to make a same-amount-reuse decision without a "
                "synchronous Stripe API call. Refreshed on every "
                "successful PI create or update-surcharge call."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("payment_tokens", "last_pi_amount_cents")
    op.drop_column("payment_tokens", "amount_override")
