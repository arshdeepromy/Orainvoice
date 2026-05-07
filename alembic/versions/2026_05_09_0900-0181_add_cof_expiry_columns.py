"""Add cof_expiry and inspection_type columns to vehicle tables.

Adds COF (Certificate of Fitness) expiry support alongside the existing
WOF (Warrant of Fitness) system. New nullable columns are added to both
global_vehicles and org_vehicles tables.

Revision ID: 0181
Revises: 0180
Create Date: 2026-05-09

Requirements: 2.1, 2.2, 2.3, 2.4, 10.1
"""

from __future__ import annotations

from alembic import op

revision: str = "0181"
down_revision: str = "0180"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE global_vehicles
        ADD COLUMN IF NOT EXISTS cof_expiry DATE
    """)
    op.execute("""
        ALTER TABLE global_vehicles
        ADD COLUMN IF NOT EXISTS inspection_type VARCHAR(3)
    """)
    op.execute("""
        ALTER TABLE org_vehicles
        ADD COLUMN IF NOT EXISTS cof_expiry DATE
    """)
    op.execute("""
        ALTER TABLE org_vehicles
        ADD COLUMN IF NOT EXISTS inspection_type VARCHAR(3)
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE org_vehicles DROP COLUMN IF EXISTS inspection_type")
    op.execute("ALTER TABLE org_vehicles DROP COLUMN IF EXISTS cof_expiry")
    op.execute("ALTER TABLE global_vehicles DROP COLUMN IF EXISTS inspection_type")
    op.execute("ALTER TABLE global_vehicles DROP COLUMN IF EXISTS cof_expiry")
