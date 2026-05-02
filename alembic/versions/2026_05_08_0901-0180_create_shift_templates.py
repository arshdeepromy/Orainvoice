"""Create shift_templates table.

Stores reusable shift template definitions per organisation.

Revision ID: 0180
Revises: 0179
Create Date: 2026-05-08

Requirements: 57.1, 57.2, 57.3
"""

from __future__ import annotations

from alembic import op

revision: str = "0180"
down_revision: str = "0179"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS shift_templates (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES organisations(id),
            name VARCHAR(255) NOT NULL,
            start_time TIME NOT NULL,
            end_time TIME NOT NULL,
            entry_type VARCHAR(20) NOT NULL DEFAULT 'job',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_shift_templates_org_id
        ON shift_templates (org_id)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS shift_templates")
