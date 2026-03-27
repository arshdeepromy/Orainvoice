"""Add supplier_id to fluid_oil_products.

Revision ID: 0114
Revises: 0113
Create Date: 2026-03-27
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0114"
down_revision: str = "0113"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fluid_oil_products", sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=True))


def downgrade() -> None:
    op.drop_column("fluid_oil_products", "supplier_id")
