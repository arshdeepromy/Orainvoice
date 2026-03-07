"""Create schedule_entries table.

Revision ID: 0037
Revises: 0036
Create Date: 2025-01-15

Requirements: Scheduling Module — Task 25.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0037"
down_revision: str = "0036"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "schedule_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("staff_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("booking_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_type", sa.String(20), server_default=sa.text("'job'"), nullable=False),
        sa.Column("status", sa.String(20), server_default=sa.text("'scheduled'"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_schedule_entries_org_id"),
        sa.ForeignKeyConstraint(["staff_id"], ["staff_members.id"], name="fk_schedule_entries_staff_id"),
    )
    op.create_index("idx_schedule_entries_org_date", "schedule_entries", ["org_id", "start_time", "end_time"])
    op.create_index("idx_schedule_entries_staff", "schedule_entries", ["staff_id", "start_time"])


def downgrade() -> None:
    op.drop_index("idx_schedule_entries_staff", table_name="schedule_entries")
    op.drop_index("idx_schedule_entries_org_date", table_name="schedule_entries")
    op.drop_table("schedule_entries")
