"""Create multi-currency tables: exchange_rates and org_currencies.

Revision ID: 0052
Revises: 0051
Create Date: 2025-01-15

Requirements: Multi-Currency Module — Task 40.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0052"
down_revision: str = "0051"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # --- exchange_rates ---
    op.create_table(
        "exchange_rates",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("base_currency", sa.String(3), nullable=False),
        sa.Column("target_currency", sa.String(3), nullable=False),
        sa.Column("rate", sa.Numeric(18, 8), nullable=False),
        sa.Column("source", sa.String(50), server_default="manual", nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("base_currency", "target_currency", "effective_date", name="uq_exchange_rate_pair_date"),
    )

    # --- org_currencies ---
    op.create_table(
        "org_currencies",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("is_base", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "currency_code", name="uq_org_currency"),
    )
    op.create_index("idx_org_currencies_org", "org_currencies", ["org_id"])


def downgrade() -> None:
    op.drop_index("idx_org_currencies_org", table_name="org_currencies")
    op.drop_table("org_currencies")
    op.drop_table("exchange_rates")
