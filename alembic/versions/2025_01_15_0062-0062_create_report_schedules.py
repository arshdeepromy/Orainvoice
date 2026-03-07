"""Create report_schedules table.

Revision ID: 0062
Revises: 0061
Create Date: 2025-01-15

**Validates: Task 54.9 — Scheduled Reports**
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_schedules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("report_type", sa.String(100), nullable=False),
        sa.Column("frequency", sa.String(20), server_default="daily", nullable=False),
        sa.Column("filters", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("recipients", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true"), nullable=False),
        sa.Column("last_generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_report_schedules_org", "report_schedules", ["org_id"])
    op.create_index("idx_report_schedules_active", "report_schedules", ["is_active"])


def downgrade() -> None:
    op.drop_index("idx_report_schedules_active")
    op.drop_index("idx_report_schedules_org")
    op.drop_table("report_schedules")
