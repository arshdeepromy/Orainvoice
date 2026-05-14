"""Add is_package and package_components columns to items_catalogue.

Extends the items_catalogue table to support bundled service packages
that combine labour with inventory components (parts, fluids, tyres).
A package item carries a boolean flag and a JSONB column describing its
linked inventory products and quantities.

Revision ID: 0188
Revises: 0187
Create Date: 2026-05-15

Requirements: 7.1, 7.7
"""

from __future__ import annotations

from alembic import op

revision: str = "0188"
down_revision: str = "0187"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE items_catalogue
        ADD COLUMN IF NOT EXISTS is_package BOOLEAN NOT NULL DEFAULT false
    """)
    op.execute("""
        ALTER TABLE items_catalogue
        ADD COLUMN IF NOT EXISTS package_components JSONB NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE items_catalogue DROP COLUMN IF EXISTS package_components")
    op.execute("ALTER TABLE items_catalogue DROP COLUMN IF EXISTS is_package")
