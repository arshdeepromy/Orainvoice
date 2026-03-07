"""Create compliance_profiles table.

Revision ID: 0012
Revises: 0011
Create Date: 2025-01-15

Requirements: 5.2
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str = "0011"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # -- compliance_profiles -------------------------------------------------
    op.create_table(
        "compliance_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("country_name", sa.String(100), nullable=False),
        sa.Column("tax_label", sa.String(20), nullable=False),
        sa.Column("default_tax_rates", postgresql.JSONB(), nullable=False),
        sa.Column("tax_number_label", sa.String(50), nullable=True),
        sa.Column("tax_number_regex", sa.String(255), nullable=True),
        sa.Column("tax_inclusive_default", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("date_format", sa.String(20), nullable=False),
        sa.Column("number_format", sa.String(20), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("report_templates", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("gdpr_applicable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("country_code", name="uq_compliance_profiles_country_code"),
    )


def downgrade() -> None:
    op.drop_table("compliance_profiles")
