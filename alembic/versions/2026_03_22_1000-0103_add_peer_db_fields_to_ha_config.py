"""Add peer database connection fields to ha_config.

Stores per-node peer database connection settings so replication can be
managed from the UI without relying on environment variables.  The
password column uses LargeBinary for envelope-encrypted storage.

Revision ID: 0103
Revises: 0102
Create Date: 2026-03-22 10:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0103"
down_revision = "0102"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ha_config", sa.Column("peer_db_host", sa.String(255), nullable=True))
    op.add_column("ha_config", sa.Column("peer_db_port", sa.Integer, nullable=True, server_default="5432"))
    op.add_column("ha_config", sa.Column("peer_db_name", sa.String(100), nullable=True))
    op.add_column("ha_config", sa.Column("peer_db_user", sa.String(100), nullable=True))
    op.add_column("ha_config", sa.Column("peer_db_password", sa.LargeBinary, nullable=True))


def downgrade() -> None:
    op.drop_column("ha_config", "peer_db_password")
    op.drop_column("ha_config", "peer_db_user")
    op.drop_column("ha_config", "peer_db_name")
    op.drop_column("ha_config", "peer_db_port")
    op.drop_column("ha_config", "peer_db_host")
