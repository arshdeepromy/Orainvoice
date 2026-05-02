"""Create transfer_actions table for stock transfer audit trail.

Each status transition (created, approved, rejected, executed, received)
is logged with the user who performed it, optional notes, and a timestamp.

Revision ID: 0177
Revises: 0176
Create Date: 2026-05-06

Requirements: 53.1, 53.2, 53.3
"""

from __future__ import annotations

from alembic import op

revision: str = "0177"
down_revision: str = "0176"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS transfer_actions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            transfer_id UUID NOT NULL REFERENCES stock_transfers(id) ON DELETE CASCADE,
            action VARCHAR(50) NOT NULL,
            performed_by UUID REFERENCES users(id),
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_transfer_actions_transfer_id
        ON transfer_actions (transfer_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_transfer_actions_created_at
        ON transfer_actions (created_at)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS transfer_actions")
