"""Create reminder_rules table for Zoho-style configurable reminders.

Revision ID: 0088
Revises: 0087
Create Date: 2026-03-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "0088"
down_revision: str = "0087"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reminder_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("reminder_type", sa.String(50), nullable=False),
        sa.Column("target", sa.String(20), nullable=False, server_default="customer"),
        sa.Column("days_offset", sa.Integer, nullable=False, server_default="0"),
        sa.Column("timing", sa.String(10), nullable=False, server_default="after"),
        sa.Column("reference_date", sa.String(30), nullable=False, server_default="due_date"),
        sa.Column("send_email", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("send_sms", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "reminder_type IN ('payment_due', 'payment_expected', 'invoice_issued', 'quote_expiry', 'service_due', 'custom')",
            name="ck_reminder_rules_type",
        ),
        sa.CheckConstraint(
            "target IN ('customer', 'me', 'both')",
            name="ck_reminder_rules_target",
        ),
        sa.CheckConstraint(
            "timing IN ('before', 'after')",
            name="ck_reminder_rules_timing",
        ),
        sa.CheckConstraint(
            "reference_date IN ('due_date', 'expected_payment_date', 'invoice_date', 'quote_expiry_date', 'service_due_date')",
            name="ck_reminder_rules_reference_date",
        ),
    )
    op.execute(
        "ALTER TABLE reminder_rules ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "CREATE POLICY reminder_rules_org_isolation ON reminder_rules "
        "USING (org_id = current_setting('app.current_org_id')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS reminder_rules_org_isolation ON reminder_rules")
    op.drop_table("reminder_rules")
