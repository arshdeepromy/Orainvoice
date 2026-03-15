"""Create reminder_queue table for batched, rate-limited reminder delivery.

Revision ID: 0089
Revises: 0088
Create Date: 2026-03-14
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0089"
down_revision = "0088"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reminder_queue",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("customer_id", UUID(as_uuid=True), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("vehicle_id", UUID(as_uuid=True), nullable=True),
        sa.Column("reminder_type", sa.String(50), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("recipient", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(255), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("scheduled_date", sa.Date(), nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(100), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("channel IN ('email','sms')", name="ck_reminder_queue_channel"),
        sa.CheckConstraint(
            "status IN ('pending','locked','sent','failed','skipped')",
            name="ck_reminder_queue_status",
        ),
    )
    # Index for the worker to pick up pending items efficiently
    op.create_index(
        "idx_reminder_queue_pending",
        "reminder_queue",
        ["status", "scheduled_for"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    # Dedup index: one reminder per org/customer/vehicle/type/date
    op.create_index(
        "idx_reminder_queue_dedup",
        "reminder_queue",
        ["org_id", "customer_id", "vehicle_id", "reminder_type", "scheduled_date"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("idx_reminder_queue_dedup", table_name="reminder_queue")
    op.drop_index("idx_reminder_queue_pending", table_name="reminder_queue")
    op.drop_table("reminder_queue")
