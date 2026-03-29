"""Add kiosk to users role CHECK constraint.

Allows the 'kiosk' value in the users.role column for the
customer check-in kiosk feature.

Revision ID: 0124
Revises: 0123
Create Date: 2026-03-30
"""
from alembic import op

revision: str = "0124"
down_revision: str = "0123"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('global_admin','franchise_admin','org_admin','location_manager','salesperson','staff_member','kiosk')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('global_admin','franchise_admin','org_admin','location_manager','salesperson','staff_member')",
    )
