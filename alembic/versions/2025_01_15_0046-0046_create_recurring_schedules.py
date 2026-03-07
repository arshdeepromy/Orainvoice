"""Create recurring_schedules table for recurring invoices module.

Revision ID: 0046
Revises: 0045
Create Date: 2025-01-15

Requirements: Recurring Module — Task 34.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0046"
down_revision: str = "0045"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "recurring_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("line_items", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("frequency", sa.String(20), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("next_generation_date", sa.Date(), nullable=False),
        sa.Column("auto_issue", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("auto_email", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status", sa.String(20), server_default=sa.text("'active'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_recurring_schedules_org_id"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], name="fk_recurring_schedules_customer_id"),
        sa.CheckConstraint(
            "frequency IN ('weekly', 'fortnightly', 'monthly', 'quarterly', 'annually')",
            name="ck_recurring_schedules_frequency",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'completed', 'cancelled')",
            name="ck_recurring_schedules_status",
        ),
    )
    # Partial index for efficient daily cron lookup
    op.create_index(
        "idx_recurring_schedules_next",
        "recurring_schedules",
        ["next_generation_date"],
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index("idx_recurring_schedules_org", "recurring_schedules", ["org_id"])


def downgrade() -> None:
    op.drop_index("idx_recurring_schedules_org", table_name="recurring_schedules")
    op.drop_index("idx_recurring_schedules_next", table_name="recurring_schedules")
    op.drop_table("recurring_schedules")
