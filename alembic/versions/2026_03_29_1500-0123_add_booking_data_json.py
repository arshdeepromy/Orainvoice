"""Add booking_data_json JSONB column to bookings table.

Stores optional parts and fluid usage data for inventory reservation.

Revision ID: 0123
Revises: 0122
Create Date: 2026-03-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0123"
down_revision: str = "0122"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bookings",
        sa.Column("booking_data_json", JSONB, nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("bookings", "booking_data_json")
