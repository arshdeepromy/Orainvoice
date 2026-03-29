"""Add inventory_locations table and location column to stock_items.

Revision ID: 0119
Revises: 0118
Create Date: 2026-03-29
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0119"
down_revision: str = "0118"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_locations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("org_id", "name", name="uq_inventory_locations_org_name"),
    )
    op.add_column("stock_items", sa.Column("location", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("stock_items", "location")
    op.drop_table("inventory_locations")
