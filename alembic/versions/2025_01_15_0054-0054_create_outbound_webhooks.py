"""Create outbound_webhooks and webhook_delivery_log tables.

Revision ID: 0054
Revises: 0053
Create Date: 2025-01-15

Requirements: Webhook Management — Task 42.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0054"
down_revision: str = "0053"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # --- outbound_webhooks ---
    op.create_table(
        "outbound_webhooks",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_url", sa.String(500), nullable=False),
        sa.Column("event_types", postgresql.JSONB(), nullable=False),
        sa.Column("secret_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_outbound_webhooks_org", "outbound_webhooks", ["org_id"])

    # --- webhook_delivery_log ---
    op.create_table(
        "webhook_delivery_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("webhook_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["webhook_id"], ["outbound_webhooks.id"], name="fk_delivery_log_webhook"),
    )
    op.create_index("idx_webhook_delivery_webhook", "webhook_delivery_log", ["webhook_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_webhook_delivery_webhook", table_name="webhook_delivery_log")
    op.drop_table("webhook_delivery_log")
    op.drop_index("idx_outbound_webhooks_org", table_name="outbound_webhooks")
    op.drop_table("outbound_webhooks")
