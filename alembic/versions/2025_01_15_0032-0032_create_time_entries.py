"""Create time_entries table.

Revision ID: 0032
Revises: 0031
Create Date: 2025-01-15

Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0032"
down_revision: str = "0031"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "time_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("staff_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("is_billable", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("hourly_rate", sa.Numeric(10, 2), nullable=True),
        sa.Column("is_invoiced", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_timer_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_time_entries_org_id"),
    )
    op.create_index("idx_time_entries_org_user", "time_entries", ["org_id", "user_id"])
    op.create_index("idx_time_entries_job", "time_entries", ["job_id"])
    op.create_index("idx_time_entries_project", "time_entries", ["project_id"])
    op.create_index("idx_time_entries_date", "time_entries", ["org_id", "start_time"])


def downgrade() -> None:
    op.drop_index("idx_time_entries_date", table_name="time_entries")
    op.drop_index("idx_time_entries_project", table_name="time_entries")
    op.drop_index("idx_time_entries_job", table_name="time_entries")
    op.drop_index("idx_time_entries_org_user", table_name="time_entries")
    op.drop_table("time_entries")
