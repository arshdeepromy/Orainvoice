"""Add payment_pending to organisations status check constraint.

Revision ID: 0095
Revises: 0094
Create Date: 2026-03-18

The payment_pending status was added to support the signup flow where
no-trial plans require upfront payment before the org is activated.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0095"
down_revision: str = "0094"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_organisations_status", "organisations", type_="check")
    op.create_check_constraint(
        "ck_organisations_status",
        "organisations",
        "status IN ('trial','active','payment_pending','grace_period','suspended','deleted')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_organisations_status", "organisations", type_="check")
    op.create_check_constraint(
        "ck_organisations_status",
        "organisations",
        "status IN ('trial','active','grace_period','suspended','deleted')",
    )
