"""Create platform_notifications and notification_dismissals tables.

Revision ID: 0059
Revises: 0058
Create Date: 2025-01-15

Requirements: Platform Notification System — Task 48.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "0059"
down_revision: str = "0058"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_notifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("notification_type", sa.String(20), nullable=False),  # maintenance, alert, feature, info
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="info"),  # info, warning, critical
        sa.Column("target_type", sa.String(30), nullable=False, server_default="all"),  # all, country, trade_family, plan_tier, specific_orgs
        sa.Column("target_value", sa.String(500), nullable=True),  # JSON array or single value
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("maintenance_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("maintenance_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )

    op.create_index("idx_platform_notifications_active", "platform_notifications", ["is_active", "published_at"])
    op.create_index("idx_platform_notifications_scheduled", "platform_notifications", ["scheduled_at"], postgresql_where=sa.text("published_at IS NULL AND scheduled_at IS NOT NULL"))
    op.create_index("idx_platform_notifications_type", "platform_notifications", ["notification_type"])

    op.create_table(
        "notification_dismissals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("notification_id", UUID(as_uuid=True), sa.ForeignKey("platform_notifications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.UniqueConstraint("notification_id", "user_id", name="uq_notification_user_dismissal"),
    )

    op.create_index("idx_notification_dismissals_user", "notification_dismissals", ["user_id"])
    op.create_index("idx_notification_dismissals_notification", "notification_dismissals", ["notification_id"])


def downgrade() -> None:
    op.drop_table("notification_dismissals")
    op.drop_table("platform_notifications")
