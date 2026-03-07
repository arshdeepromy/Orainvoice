"""Create assets table for extended asset tracking.

Extends the existing vehicles concept into a generic asset tracking system
that supports vehicles, devices, properties, equipment, etc. based on
the organisation's trade category.

Revision ID: 0057
Revises: 0056
Create Date: 2025-01-15

Requirements: Extended Asset Tracking — Task 45.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision: str = "0057"
down_revision: str = "0056"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("customer_id", UUID(as_uuid=True), sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("asset_type", sa.String(50), nullable=False),
        sa.Column("identifier", sa.String(200), nullable=True),
        sa.Column("make", sa.String(100), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("year", sa.Integer, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("serial_number", sa.String(200), nullable=True),
        sa.Column("location", sa.Text, nullable=True),
        sa.Column("custom_fields", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("carjam_data", JSONB, nullable=True),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_index("idx_assets_org", "assets", ["org_id"])
    op.create_index("idx_assets_customer", "assets", ["customer_id"])
    op.create_index("idx_assets_identifier", "assets", ["org_id", "identifier"])


def downgrade() -> None:
    op.drop_index("idx_assets_identifier", table_name="assets")
    op.drop_index("idx_assets_customer", table_name="assets")
    op.drop_index("idx_assets_org", table_name="assets")
    op.drop_table("assets")
