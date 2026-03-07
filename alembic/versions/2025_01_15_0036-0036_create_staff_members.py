"""Create staff_members and staff_location_assignments tables.

Revision ID: 0036
Revises: 0035
Create Date: 2025-01-15

Requirements: Staff Module — Task 24.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0036"
down_revision: str = "0035"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "staff_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("role_type", sa.String(20), server_default=sa.text("'employee'"), nullable=False),
        sa.Column("hourly_rate", sa.Numeric(10, 2), nullable=True),
        sa.Column("overtime_rate", sa.Numeric(10, 2), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("availability_schedule", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("skills", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_staff_members_org_id"),
    )
    op.create_index("idx_staff_members_org", "staff_members", ["org_id"])
    op.create_index("idx_staff_members_active", "staff_members", ["org_id", "is_active"])

    op.create_table(
        "staff_location_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("staff_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["staff_id"], ["staff_members.id"], name="fk_staff_loc_staff_id", ondelete="CASCADE"),
        sa.UniqueConstraint("staff_id", "location_id", name="uq_staff_location_assignment"),
    )
    op.create_index("idx_staff_loc_staff", "staff_location_assignments", ["staff_id"])
    op.create_index("idx_staff_loc_location", "staff_location_assignments", ["location_id"])


def downgrade() -> None:
    op.drop_index("idx_staff_loc_location", table_name="staff_location_assignments")
    op.drop_index("idx_staff_loc_staff", table_name="staff_location_assignments")
    op.drop_table("staff_location_assignments")
    op.drop_index("idx_staff_members_active", table_name="staff_members")
    op.drop_index("idx_staff_members_org", table_name="staff_members")
    op.drop_table("staff_members")
