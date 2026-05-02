"""Add last_portal_access_at column to customers table.

Tracks when each customer last accessed the portal, enabling org admins
to identify inactive portal users.

Revision ID: 0176
Revises: 0175
Create Date: 2026-05-05
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0176"
down_revision = "0175"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column(
            "last_portal_access_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp of last portal access (Req 48.1)",
        ),
    )
    op.create_index(
        "ix_customers_last_portal_access_at",
        "customers",
        ["last_portal_access_at"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_customers_last_portal_access_at", table_name="customers")
    op.drop_column("customers", "last_portal_access_at")
