"""Add cancellation columns to quotes table and update CHECK constraint.

Adds cancel_reason (Text), cancelled_at (DateTime TZ), and cancelled_by
(UUID FK → users.id) nullable columns to the quotes table. Updates the
ck_quotes_status CHECK constraint to include 'cancelled' as a valid status.

Revision ID: 0201
Revises: 0200
Create Date: 2026-05-30

Requirements: 3.1, 3.2, 3.3, 3.4
"""

from __future__ import annotations

from alembic import op

revision: str = "0201"
down_revision: str = "0200"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # ── 1. Add cancellation columns (all nullable — safe for existing rows) ──
    op.execute(
        "ALTER TABLE quotes "
        "ADD COLUMN IF NOT EXISTS cancel_reason TEXT NULL"
    )
    op.execute(
        "ALTER TABLE quotes "
        "ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMP WITH TIME ZONE NULL"
    )
    op.execute(
        "ALTER TABLE quotes "
        "ADD COLUMN IF NOT EXISTS cancelled_by UUID NULL "
        "REFERENCES users(id)"
    )

    # ── 2. Update CHECK constraint to include 'cancelled' ─────────────────
    op.execute("ALTER TABLE quotes DROP CONSTRAINT IF EXISTS ck_quotes_status")
    op.execute("""
        ALTER TABLE quotes ADD CONSTRAINT ck_quotes_status
        CHECK (status IN ('draft', 'issued', 'sent', 'accepted', 'declined', 'expired', 'converted', 'cancelled'))
    """)


def downgrade() -> None:
    # ── 1. Restore original CHECK constraint (without 'cancelled') ────────
    op.execute("ALTER TABLE quotes DROP CONSTRAINT IF EXISTS ck_quotes_status")
    op.execute("""
        ALTER TABLE quotes ADD CONSTRAINT ck_quotes_status
        CHECK (status IN ('draft', 'issued', 'sent', 'accepted', 'declined', 'expired', 'converted'))
    """)

    # ── 2. Drop cancellation columns (reverse order) ──────────────────────
    op.execute("ALTER TABLE quotes DROP COLUMN IF EXISTS cancelled_by")
    op.execute("ALTER TABLE quotes DROP COLUMN IF EXISTS cancelled_at")
    op.execute("ALTER TABLE quotes DROP COLUMN IF EXISTS cancel_reason")
