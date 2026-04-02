"""Add branch_admin to users role CHECK constraint.

Allows the 'branch_admin' value in the users.role column for the
branch admin role feature. Inserted between org_admin and location_manager
in the role hierarchy.

Revision ID: 0136
Revises: 0135
Create Date: 2026-04-04
"""
from alembic import op

revision: str = "0136"
down_revision: str = "0135"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('global_admin','franchise_admin','org_admin','branch_admin','location_manager','salesperson','staff_member','kiosk')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('global_admin','franchise_admin','org_admin','location_manager','salesperson','staff_member','kiosk')",
    )
