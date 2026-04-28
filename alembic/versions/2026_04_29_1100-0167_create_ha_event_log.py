"""Create ha_event_log table for persistent HA event history.

Stores HA events (heartbeat failures, role changes, replication errors,
split-brain detections, auto-promote attempts, volume sync errors,
config changes, recovery actions) per node.  This table is NOT
replicated — each node maintains its own event history.

Columns:
  - id: UUID primary key (gen_random_uuid)
  - timestamp: when the event occurred (server default now())
  - event_type: category string (heartbeat_failure, role_change, etc.)
  - severity: info | warning | error | critical
  - message: human-readable description
  - details: optional JSONB payload (stack traces, peer response, lag)
  - node_name: which node logged the event

Indexes:
  - ix_ha_event_log_timestamp  (timestamp DESC) — recent-first queries
  - ix_ha_event_log_event_type (event_type)     — filtered queries
  - ix_ha_event_log_severity   (severity)       — filtered queries

Revision ID: 0167
Revises: 0166
Create Date: 2026-04-29

Requirements: 34.1, 34.8
"""

from alembic import op

revision = "0167"
down_revision = "0166"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: IF NOT EXISTS guard so re-running is safe.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ha_event_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            event_type VARCHAR(50) NOT NULL,
            severity VARCHAR(20) NOT NULL,
            message TEXT NOT NULL,
            details JSONB,
            node_name VARCHAR(100) NOT NULL
        )
        """
    )

    # Indexes — use IF NOT EXISTS for idempotency.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_ha_event_log_timestamp
            ON ha_event_log (timestamp DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_ha_event_log_event_type
            ON ha_event_log (event_type)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_ha_event_log_severity
            ON ha_event_log (severity)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ha_event_log_severity")
    op.execute("DROP INDEX IF EXISTS ix_ha_event_log_event_type")
    op.execute("DROP INDEX IF EXISTS ix_ha_event_log_timestamp")
    op.execute("DROP TABLE IF EXISTS ha_event_log")
