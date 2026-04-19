"""Add heartbeat_secret column to ha_config.

Moves the HMAC shared secret from env var (HA_HEARTBEAT_SECRET) to the
database so it can be configured via the GUI alongside other HA settings.

Revision ID: 0151
Revises: 0150
"""

from alembic import op
import sqlalchemy as sa

revision = "0151"
down_revision = "0150"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ha_config",
        sa.Column("heartbeat_secret", sa.LargeBinary(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ha_config", "heartbeat_secret")
