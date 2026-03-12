"""Change job_cards.assigned_to FK from users to staff_members.

Staff members are the workers assigned to jobs. They don't need login
accounts (users table) to be assignable. This migration:
1. Drops the old FK constraint referencing users.id
2. Adds a new FK constraint referencing staff_members.id
3. Nulls out any existing assigned_to values that don't exist in
   staff_members (data cleanup for rows that pointed at users.id)

Revision ID: 0084
Revises: 0083
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0084"
down_revision = "0083_add_vehicle_rego_to_bookings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Drop old FK to users
    op.drop_constraint("fk_job_cards_assigned_to", "job_cards", type_="foreignkey")

    # 2. Null out any assigned_to values that are user IDs (not staff member IDs)
    #    so the new FK doesn't fail on existing data
    op.execute("""
        UPDATE job_cards
        SET assigned_to = NULL
        WHERE assigned_to IS NOT NULL
          AND assigned_to NOT IN (SELECT id FROM staff_members)
    """)

    # 3. Add new FK to staff_members
    op.create_foreign_key(
        "fk_job_cards_assigned_to_staff",
        "job_cards",
        "staff_members",
        ["assigned_to"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_job_cards_assigned_to_staff", "job_cards", type_="foreignkey")

    # Null out staff member IDs that aren't in users
    op.execute("""
        UPDATE job_cards
        SET assigned_to = NULL
        WHERE assigned_to IS NOT NULL
          AND assigned_to NOT IN (SELECT id FROM users)
    """)

    op.create_foreign_key(
        "fk_job_cards_assigned_to",
        "job_cards",
        "users",
        ["assigned_to"],
        ["id"],
    )
