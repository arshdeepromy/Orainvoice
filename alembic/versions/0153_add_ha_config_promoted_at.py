"""Add promoted_at column to ha_config.

Records the UTC timestamp when a node is promoted to primary (manual or
auto-promote).  Used for split-brain resolution — the node with the older
(or null) promoted_at is the stale primary.

Revision ID: 0153
Revises: 0152
"""

from alembic import op

revision = "0153"
down_revision = "0152"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: IF NOT EXISTS guard so re-running is safe.
    op.execute(
        "ALTER TABLE ha_config "
        "ADD COLUMN IF NOT EXISTS promoted_at TIMESTAMPTZ"
    )


def downgrade() -> None:
    op.drop_column("ha_config", "promoted_at")
