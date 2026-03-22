"""Create ha_config table for the HA Replication feature.

Stores per-node HA configuration: identity, role, peer info, heartbeat
state, and replication sync status.  Each node maintains its own row —
this table is NOT replicated between nodes.

Revision ID: 0102
Revises: 0101
Create Date: 2026-03-22 09:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0102"
down_revision = "0101"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ha_config",
        # Primary key
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        # Node identity
        sa.Column("node_id", UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("node_name", sa.String(100), nullable=False),
        # Role management
        sa.Column("role", sa.String(20), nullable=False, server_default="standalone"),
        # Peer configuration
        sa.Column("peer_endpoint", sa.String(500), nullable=True),
        # Failover settings
        sa.Column("auto_promote_enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("heartbeat_interval_seconds", sa.Integer, nullable=False, server_default="10"),
        sa.Column("failover_timeout_seconds", sa.Integer, nullable=False, server_default="90"),
        # Maintenance
        sa.Column("maintenance_mode", sa.Boolean, nullable=False, server_default=sa.text("false")),
        # Peer health tracking
        sa.Column("last_peer_health", sa.String(20), server_default="unknown"),
        sa.Column("last_peer_heartbeat", sa.DateTime(timezone=True), nullable=True),
        # Replication state
        sa.Column("sync_status", sa.String(30), nullable=False, server_default="not_configured"),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        # Check constraints
        sa.CheckConstraint(
            "role IN ('standalone', 'primary', 'standby')",
            name="ck_ha_config_role",
        ),
        sa.CheckConstraint(
            "sync_status IN ("
            "'not_configured', 'initializing', 'healthy', "
            "'lagging', 'disconnected', 'resyncing', 'error'"
            ")",
            name="ck_ha_config_sync",
        ),
    )

    # Unique constraint on node_id
    op.create_unique_constraint("uq_ha_config_node_id", "ha_config", ["node_id"])


def downgrade() -> None:
    op.drop_table("ha_config")
