"""Add value_encrypted column to platform_settings.

The platform_settings table already exists with key/value/version/updated_at.
This migration adds a value_encrypted BYTEA column for storing
envelope-encrypted secrets (Xero API keys, webhook keys, etc.).

Revision ID: 0139
Revises: 0138
Create Date: 2026-04-07
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "0139"
down_revision: str = "0138"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add encrypted value column to existing platform_settings table
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'platform_settings' AND column_name = 'value_encrypted'
            ) THEN
                ALTER TABLE platform_settings ADD COLUMN value_encrypted BYTEA;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.drop_column("platform_settings", "value_encrypted")
