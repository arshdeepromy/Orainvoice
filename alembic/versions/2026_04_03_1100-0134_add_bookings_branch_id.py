"""Add branch_id column to bookings table.

The Booking model had branch_id defined but no migration existed
to add the column to the database, causing 503 errors on the
bookings endpoint.

Revision ID: 0134
Revises: 0133
Create Date: 2026-04-03
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "0134"
down_revision: str = "0133"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bookings",
        sa.Column("branch_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_bookings_branch_id",
        "bookings",
        "branches",
        ["branch_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_bookings_branch_id", "bookings", type_="foreignkey")
    op.drop_column("bookings", "branch_id")
