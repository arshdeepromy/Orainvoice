"""Create bookings and booking_rules tables.

Revision ID: 0038
Revises: 0037
Create Date: 2025-01-15

Requirements: Booking Module — Task 26.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0038"
down_revision: str = "0037"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # Table was originally created in migration 0006 with a different schema.
    # Drop and recreate with the new schema (staff_id FK, confirmation_token, etc.)
    op.execute("ALTER TABLE IF EXISTS bookings DISABLE ROW LEVEL SECURITY")
    op.execute("DROP TABLE IF EXISTS bookings CASCADE")

    op.create_table(
        "bookings",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_name", sa.String(255), nullable=False),
        sa.Column("customer_email", sa.String(255), nullable=True),
        sa.Column("customer_phone", sa.String(50), nullable=True),
        sa.Column("staff_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("service_type", sa.String(255), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("confirmation_token", sa.String(255), nullable=True),
        sa.Column("converted_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("converted_invoice_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_bookings_org_id"),
        sa.ForeignKeyConstraint(["staff_id"], ["staff_members.id"], name="fk_bookings_staff_id"),
    )
    op.create_index("idx_bookings_org_date", "bookings", ["org_id", "start_time"])
    op.create_index("idx_bookings_status", "bookings", ["org_id", "status"])
    op.create_index("idx_bookings_staff", "bookings", ["staff_id"])

    op.create_table(
        "booking_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("service_type", sa.String(255), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), server_default=sa.text("60"), nullable=False),
        sa.Column("min_advance_hours", sa.Integer(), server_default=sa.text("2"), nullable=False),
        sa.Column("max_advance_days", sa.Integer(), server_default=sa.text("90"), nullable=False),
        sa.Column("buffer_minutes", sa.Integer(), server_default=sa.text("15"), nullable=False),
        sa.Column("available_days", postgresql.JSONB(), server_default=sa.text("'[1,2,3,4,5]'::jsonb"), nullable=False),
        sa.Column("available_hours", postgresql.JSONB(), server_default=sa.text("'{\"start\":\"09:00\",\"end\":\"17:00\"}'::jsonb"), nullable=False),
        sa.Column("max_per_day", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_booking_rules_org_id"),
    )
    op.create_index("idx_booking_rules_org", "booking_rules", ["org_id"])


def downgrade() -> None:
    op.drop_index("idx_booking_rules_org", table_name="booking_rules")
    op.drop_table("booking_rules")
    op.drop_index("idx_bookings_staff", table_name="bookings")
    op.drop_index("idx_bookings_status", table_name="bookings")
    op.drop_index("idx_bookings_org_date", table_name="bookings")
    op.drop_table("bookings")
