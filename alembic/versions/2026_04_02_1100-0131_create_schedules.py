"""Create schedules table for staff scheduling per branch.

Creates the schedules table with UUID PK, foreign keys to
organisations, branches, and users. Includes composite indexes
on (org_id, branch_id) and (user_id, shift_date), plus a unique
index to prevent overlapping shifts for the same user.

Revision ID: 0131
Revises: 0130
Create Date: 2026-04-02

Requirements: 19.1
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0131"
down_revision: str = "0130"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("branch_id", UUID(as_uuid=True), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("shift_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Composite indexes for common query patterns
    op.create_index("ix_schedules_org_branch", "schedules", ["org_id", "branch_id"])
    op.create_index("ix_schedules_user_date", "schedules", ["user_id", "shift_date"])

    # Unique constraint for overlap prevention
    op.create_index(
        "uq_schedules_no_overlap",
        "schedules",
        ["user_id", "shift_date", "start_time", "end_time"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_schedules_no_overlap", table_name="schedules")
    op.drop_index("ix_schedules_user_date", table_name="schedules")
    op.drop_index("ix_schedules_org_branch", table_name="schedules")
    op.drop_table("schedules")
