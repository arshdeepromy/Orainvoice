"""Add quote_data_json JSONB column to quotes table.

Stores vehicle details (multi-vehicle, odometer, service due, WOF expiry)
and fluid usage data that don't have dedicated columns.

Revision ID: 0157
Revises: 0156
Create Date: 2026-04-08
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0157"
down_revision: str = "0156"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "quotes",
        sa.Column("quote_data_json", JSONB, nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("quotes", "quote_data_json")
