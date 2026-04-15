"""Add custom_roles table, password_history table, and users security columns.

Revision ID: 0140
Revises: 0139
Create Date: 2026-04-08

Requirements: 2.2, 2.7, 2.8, 4.5, 4.6
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0140"
down_revision: str = "0139"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- custom_roles --------------------------------------------------------
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'custom_roles'
            ) THEN
                CREATE TABLE custom_roles (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    org_id UUID NOT NULL REFERENCES organisations(id),
                    name VARCHAR(100) NOT NULL,
                    slug VARCHAR(100) NOT NULL,
                    description TEXT,
                    permissions JSONB NOT NULL DEFAULT '[]'::jsonb,
                    is_system BOOLEAN NOT NULL DEFAULT false,
                    created_by UUID REFERENCES users(id),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    CONSTRAINT uq_custom_roles_org_slug UNIQUE (org_id, slug)
                );
            END IF;
        END $$
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'idx_custom_roles_org'
            ) THEN
                CREATE INDEX idx_custom_roles_org ON custom_roles(org_id);
            END IF;
        END $$
    """)

    # -- password_history ----------------------------------------------------
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'password_history'
            ) THEN
                CREATE TABLE password_history (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    password_hash VARCHAR(255) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
            END IF;
        END $$
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'idx_password_history_user'
            ) THEN
                CREATE INDEX idx_password_history_user ON password_history(user_id);
            END IF;
        END $$
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'idx_password_history_created'
            ) THEN
                CREATE INDEX idx_password_history_created ON password_history(user_id, created_at DESC);
            END IF;
        END $$
    """)

    # -- users.password_changed_at -------------------------------------------
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'users' AND column_name = 'password_changed_at'
            ) THEN
                ALTER TABLE users ADD COLUMN password_changed_at TIMESTAMPTZ;
            END IF;
        END $$
    """)

    # -- users.custom_role_id ------------------------------------------------
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'users' AND column_name = 'custom_role_id'
            ) THEN
                ALTER TABLE users ADD COLUMN custom_role_id UUID
                    REFERENCES custom_roles(id) ON DELETE SET NULL;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.drop_column("users", "custom_role_id")
    op.drop_column("users", "password_changed_at")
    op.drop_index("idx_password_history_created", table_name="password_history")
    op.drop_index("idx_password_history_user", table_name="password_history")
    op.drop_table("password_history")
    op.drop_index("idx_custom_roles_org", table_name="custom_roles")
    op.drop_table("custom_roles")
