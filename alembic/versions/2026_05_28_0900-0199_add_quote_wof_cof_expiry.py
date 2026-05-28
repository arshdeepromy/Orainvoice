"""Add vehicle_odometer, vehicle_wof_expiry and vehicle_cof_expiry columns to quotes table.

Adds nullable columns for storing odometer reading and WOF/COF expiry dates on quotes.
These values are captured at quote creation time from the CarJam lookup
data already fetched via VehicleLiveSearch.

Note: vehicle_odometer exists on the invoices table (migration 0005) but was
never added to the quotes table — this migration adds it.

Revision ID: 0199
Revises: 0198
Create Date: 2026-05-28

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5
"""

from __future__ import annotations

from alembic import op

revision: str = "0199"
down_revision: str = "0198"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE quotes
        ADD COLUMN IF NOT EXISTS vehicle_odometer INTEGER DEFAULT NULL
    """)
    op.execute("""
        ALTER TABLE quotes
        ADD COLUMN IF NOT EXISTS vehicle_wof_expiry DATE DEFAULT NULL
    """)
    op.execute("""
        ALTER TABLE quotes
        ADD COLUMN IF NOT EXISTS vehicle_cof_expiry DATE DEFAULT NULL
    """)
    # Add 'issued' to the status check constraint
    op.execute("ALTER TABLE quotes DROP CONSTRAINT IF EXISTS ck_quotes_status")
    op.execute("""
        ALTER TABLE quotes ADD CONSTRAINT ck_quotes_status
        CHECK (status IN ('draft', 'issued', 'sent', 'accepted', 'declined', 'expired', 'converted'))
    """)


def downgrade() -> None:
    # Revert status constraint
    op.execute("ALTER TABLE quotes DROP CONSTRAINT IF EXISTS ck_quotes_status")
    op.execute("""
        ALTER TABLE quotes ADD CONSTRAINT ck_quotes_status
        CHECK (status IN ('draft', 'sent', 'accepted', 'declined', 'expired', 'converted'))
    """)
    op.execute("ALTER TABLE quotes DROP COLUMN IF EXISTS vehicle_cof_expiry")
    op.execute("ALTER TABLE quotes DROP COLUMN IF EXISTS vehicle_wof_expiry")
    op.execute("ALTER TABLE quotes DROP COLUMN IF EXISTS vehicle_odometer")
