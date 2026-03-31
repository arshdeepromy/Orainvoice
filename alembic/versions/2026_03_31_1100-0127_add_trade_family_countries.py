"""Add country_codes and gated_features to trade_families.

Revision ID: 0127
Revises: 0126
Create Date: 2026-03-31 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0127"
down_revision = "0126"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add country_codes column - empty array means available to all countries
    op.add_column(
        "trade_families",
        sa.Column("country_codes", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    # Add gated_features column - list of feature slugs gated behind this family
    op.add_column(
        "trade_families",
        sa.Column("gated_features", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("trade_families", "gated_features")
    op.drop_column("trade_families", "country_codes")
