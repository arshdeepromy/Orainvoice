"""Add dismissed_at column to pending_qr_sessions for kiosk soft-dismiss.

When the kiosk staff press "Close" on the QR popup, the row is marked
``dismissed_at = now()`` instead of being deleted. The poll filters out
dismissed rows so the popup doesn't re-appear on a kiosk page refresh,
but the underlying Stripe PaymentIntent stays alive so a customer who
already scanned can complete payment from their phone.

The next QR Payment click (whether reuse-branch or fresh PI) clears the
flag so the popup re-appears for the new attempt.

Both columns of the change set:

- ``dismissed_at TIMESTAMPTZ NULL`` — when the kiosk dismissed this
  pending session display. NULL = visible to kiosk poll.

Revision ID: 0194
Revises: 0193
Create Date: 2026-05-26
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0194"
down_revision: str = "0193"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "pending_qr_sessions",
        sa.Column(
            "dismissed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment=(
                "When the kiosk dismissed this pending session display. "
                "NULL = visible to kiosk poll. NOT NULL = hidden but "
                "Stripe session stays alive for the customer to complete "
                "payment."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("pending_qr_sessions", "dismissed_at")
