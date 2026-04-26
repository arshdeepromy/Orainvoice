"""Add local_lan_ip and local_pg_port columns to ha_config.

These optional columns allow GUI-based override of the auto-detected
host LAN IP and PostgreSQL port used in "View Connection Info" and
the create-replication-user endpoint.

Revision ID: 0160
Revises: 0159
Create Date: 2026-04-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "0160"
down_revision: str = "0159"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ha_config",
        sa.Column("local_lan_ip", sa.String(255), nullable=True),
    )
    op.add_column(
        "ha_config",
        sa.Column("local_pg_port", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ha_config", "local_pg_port")
    op.drop_column("ha_config", "local_lan_ip")
