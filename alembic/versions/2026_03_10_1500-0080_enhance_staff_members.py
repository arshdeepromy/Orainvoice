"""Enhance staff_members table with first_name, last_name, employee_id, position,
reporting_to, shift_start, shift_end columns. Migrate existing 'name' data into
first_name/last_name.

Revision ID: 0080_enhance_staff_members
Revises: 0079_add_quote_discount_fields
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0080_enhance_staff_members"
down_revision = "0079_add_quote_discount_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns
    op.add_column("staff_members", sa.Column("first_name", sa.String(100), nullable=True))
    op.add_column("staff_members", sa.Column("last_name", sa.String(100), nullable=True))
    op.add_column("staff_members", sa.Column("employee_id", sa.String(50), nullable=True))
    op.add_column("staff_members", sa.Column("position", sa.String(100), nullable=True))
    op.add_column("staff_members", sa.Column("reporting_to", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("staff_members", sa.Column("shift_start", sa.String(5), nullable=True))
    op.add_column("staff_members", sa.Column("shift_end", sa.String(5), nullable=True))

    # Migrate existing name data: split "name" into first_name / last_name
    op.execute("""
        UPDATE staff_members
        SET first_name = split_part(name, ' ', 1),
            last_name = CASE
                WHEN position(' ' in name) > 0
                THEN substring(name from position(' ' in name) + 1)
                ELSE ''
            END
        WHERE first_name IS NULL
    """)

    # Make first_name NOT NULL after migration
    op.alter_column("staff_members", "first_name", nullable=False, server_default="")

    # Add FK for reporting_to (self-referencing)
    op.create_foreign_key(
        "fk_staff_members_reporting_to",
        "staff_members", "staff_members",
        ["reporting_to"], ["id"],
        ondelete="SET NULL",
    )

    # Index on employee_id for lookups
    op.create_index("idx_staff_members_employee_id", "staff_members", ["org_id", "employee_id"])


def downgrade() -> None:
    op.drop_index("idx_staff_members_employee_id", table_name="staff_members")
    op.drop_constraint("fk_staff_members_reporting_to", "staff_members", type_="foreignkey")
    op.drop_column("staff_members", "shift_end")
    op.drop_column("staff_members", "shift_start")
    op.drop_column("staff_members", "reporting_to")
    op.drop_column("staff_members", "position")
    op.drop_column("staff_members", "employee_id")
    op.drop_column("staff_members", "last_name")
    op.drop_column("staff_members", "first_name")
