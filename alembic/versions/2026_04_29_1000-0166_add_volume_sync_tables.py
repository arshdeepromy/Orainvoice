"""Add volume_sync_config and volume_sync_history tables.

Stores rsync-based volume replication configuration and sync history
for HA file synchronisation between primary and standby nodes.

Tables:
  - volume_sync_config: singleton config row with SSH host, port, key path,
    remote paths, sync interval, and enabled flag.
  - volume_sync_history: log of each sync execution with status, file count,
    bytes transferred, and error details.

Revision ID: 0166
Revises: 0165
Create Date: 2026-04-29

Requirements: 9.1, 9.2, 9.3, 9.4
"""

from alembic import op

revision = "0166"
down_revision = "0165"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: IF NOT EXISTS guard so re-running is safe.

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS volume_sync_config (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            standby_ssh_host VARCHAR(255) NOT NULL,
            ssh_port INTEGER NOT NULL DEFAULT 22,
            ssh_key_path VARCHAR(500) NOT NULL,
            remote_upload_path VARCHAR(500) NOT NULL DEFAULT '/app/uploads/',
            remote_compliance_path VARCHAR(500) NOT NULL DEFAULT '/app/compliance_files/',
            sync_interval_minutes INTEGER NOT NULL DEFAULT 5,
            enabled BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS volume_sync_history (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            started_at TIMESTAMP WITH TIME ZONE NOT NULL,
            completed_at TIMESTAMP WITH TIME ZONE,
            status VARCHAR(20) NOT NULL,
            files_transferred INTEGER NOT NULL DEFAULT 0,
            bytes_transferred BIGINT NOT NULL DEFAULT 0,
            error_message TEXT,
            sync_type VARCHAR(20) NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS volume_sync_history")
    op.execute("DROP TABLE IF EXISTS volume_sync_config")
