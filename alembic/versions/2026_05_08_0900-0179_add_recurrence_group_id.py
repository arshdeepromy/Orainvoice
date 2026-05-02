"""Add recurrence_group_id to schedule_entries.

Links recurring schedule entries together so they can be identified
and managed as a group.

Revision ID: 0179
Revises: 0178
Create Date: 2026-05-08

Requirements: 56.1, 56.2, 56.3
"""

from __future__ import annotations

from alembic import op

revision: str = "0179"
down_revision: str = "0178"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE schedule_entries
        ADD COLUMN IF NOT EXISTS recurrence_group_id UUID DEFAULT NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_schedule_entries_recurrence_group_id
        ON schedule_entries (recurrence_group_id)
        WHERE recurrence_group_id IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_schedule_entries_recurrence_group_id")
    op.execute("ALTER TABLE schedule_entries DROP COLUMN IF EXISTS recurrence_group_id")
