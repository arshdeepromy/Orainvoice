"""Add assigned_location_ids and franchise_group_id columns to users table.

Also updates the role CHECK constraint to include new roles.

Revision ID: 0024
Revises: 0023
Create Date: 2025-01-15

Requirements: 8.1, 8.2, 8.6
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0024"
down_revision: str = "0023"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # Add assigned_location_ids (JSONB array of UUIDs)
    op.add_column(
        "users",
        sa.Column(
            "assigned_location_ids",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    # Add franchise_group_id
    op.add_column(
        "users",
        sa.Column(
            "franchise_group_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )

    # Update the role CHECK constraint to include new roles
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('global_admin','franchise_admin','org_admin','location_manager','salesperson','staff_member')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('global_admin','org_admin','salesperson')",
    )
    op.drop_column("users", "franchise_group_id")
    op.drop_column("users", "assigned_location_ids")
