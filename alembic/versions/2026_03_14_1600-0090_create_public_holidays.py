"""Create public_holidays table for synced calendar data.

Revision ID: 0090
Revises: 0089_create_reminder_queue
Create Date: 2026-03-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0090"
down_revision: str = "0089"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "public_holidays",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("holiday_date", sa.Date, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("local_name", sa.String(255), nullable=True),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("is_fixed", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("country_code", "holiday_date", "name", name="uq_public_holidays_country_date_name"),
    )
    op.create_index("ix_public_holidays_country_year", "public_holidays", ["country_code", "year"])


def downgrade() -> None:
    op.drop_index("ix_public_holidays_country_year", table_name="public_holidays")
    op.drop_table("public_holidays")
