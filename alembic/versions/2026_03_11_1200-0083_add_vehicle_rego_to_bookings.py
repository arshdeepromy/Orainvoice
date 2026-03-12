"""Add vehicle_rego column to bookings table.

Revision ID: 0083
Revises: 0082
Create Date: 2026-03-11 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "0083_add_vehicle_rego_to_bookings"
down_revision = "0082_universal_items_catalogue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bookings", sa.Column("vehicle_rego", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("bookings", "vehicle_rego")
