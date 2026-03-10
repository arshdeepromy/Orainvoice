"""Add booking modal enhancement columns to bookings table.

New columns: service_catalogue_id (FK), service_price, send_email_confirmation,
send_sms_confirmation, reminder_offset_hours, reminder_scheduled_at,
reminder_cancelled.

Revision ID: 0081_booking_modal_enhancements
Revises: 0080_enhance_staff_members
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0081_booking_modal_enhancements"
down_revision = "0080_enhance_staff_members"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bookings",
        sa.Column(
            "service_catalogue_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("service_catalogue.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "bookings",
        sa.Column("service_price", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "bookings",
        sa.Column(
            "send_email_confirmation",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "bookings",
        sa.Column(
            "send_sms_confirmation",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "bookings",
        sa.Column("reminder_offset_hours", sa.Numeric(5, 1), nullable=True),
    )
    op.add_column(
        "bookings",
        sa.Column(
            "reminder_scheduled_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "bookings",
        sa.Column(
            "reminder_cancelled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("bookings", "reminder_cancelled")
    op.drop_column("bookings", "reminder_scheduled_at")
    op.drop_column("bookings", "reminder_offset_hours")
    op.drop_column("bookings", "send_sms_confirmation")
    op.drop_column("bookings", "send_email_confirmation")
    op.drop_column("bookings", "service_price")
    op.drop_column("bookings", "service_catalogue_id")
