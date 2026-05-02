"""Add customer_id FK column to bookings table.

The portal bookings query references customer_id but the column did not
exist — bookings only stored customer_name as text.  This migration adds
a nullable UUID FK to customers(id) and an index for portal lookups.

Revision ID: 0173
Revises: 0172
Create Date: 2026-05-02

Requirements: 3.1, 3.2, 3.3
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0173"
down_revision: str = "0172"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # Add customer_id column (nullable so existing rows are unaffected)
    op.add_column(
        "bookings",
        sa.Column(
            "customer_id",
            UUID(as_uuid=True),
            sa.ForeignKey("customers.id"),
            nullable=True,
        ),
    )

    # Create index for portal lookups by customer_id
    op.create_index(
        "ix_bookings_customer_id",
        "bookings",
        ["customer_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_bookings_customer_id", table_name="bookings")
    op.drop_column("bookings", "customer_id")
