"""Add peer_db_sslmode column to ha_config.

Allows each node to specify the SSL mode for peer database connections:
disable, require, verify-ca, verify-full.

Revision ID: 0104
Revises: 0103
Create Date: 2026-03-22 11:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0104"
down_revision = "0103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ha_config",
        sa.Column("peer_db_sslmode", sa.String(20), nullable=True, server_default="disable"),
    )


def downgrade() -> None:
    op.drop_column("ha_config", "peer_db_sslmode")
