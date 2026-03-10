"""Add odometer_readings history table.

Revision ID: 0075_add_odometer_readings_table
Revises: 0074_add_email_provider_encryption_priority
Create Date: 2026-03-10 09:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0075_add_odometer_readings_table"
down_revision = "0074_add_email_provider_encryption_priority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "odometer_readings",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("global_vehicle_id", UUID(as_uuid=True), sa.ForeignKey("global_vehicles.id"), nullable=False),
        sa.Column("reading_km", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),  # carjam, manual, invoice
        sa.Column("recorded_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("invoice_id", UUID(as_uuid=True), sa.ForeignKey("invoices.id"), nullable=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "source IN ('carjam','manual','invoice')",
            name="ck_odometer_readings_source",
        ),
    )
    op.create_index("idx_odometer_readings_vehicle", "odometer_readings", ["global_vehicle_id", "recorded_at"])


def downgrade() -> None:
    op.drop_index("idx_odometer_readings_vehicle")
    op.drop_table("odometer_readings")
