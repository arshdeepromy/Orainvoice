"""ALTER organisations table to add universal platform columns:
trade_category_id, country_code, data_residency_region, base_currency,
locale, tax_label, default_tax_rate, tax_inclusive_default, date_format,
number_format, timezone, compliance_profile_id, setup_wizard_state,
is_multi_location, franchise_group_id, white_label_enabled,
storage_quota_bytes.

Revision ID: 0013
Revises: 0012
Create Date: 2025-01-15

Requirements: 5.2, 4.1, 6.7
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str = "0012"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # -- Add universal platform columns to organisations ---------------------
    op.add_column("organisations", sa.Column("trade_category_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("organisations", sa.Column("country_code", sa.String(2), nullable=True))
    op.add_column("organisations", sa.Column("data_residency_region", sa.String(20), server_default=sa.text("'nz-au'"), nullable=False))
    op.add_column("organisations", sa.Column("base_currency", sa.String(3), server_default=sa.text("'NZD'"), nullable=False))
    op.add_column("organisations", sa.Column("locale", sa.String(10), server_default=sa.text("'en-NZ'"), nullable=False))
    op.add_column("organisations", sa.Column("tax_label", sa.String(20), server_default=sa.text("'GST'"), nullable=False))
    op.add_column("organisations", sa.Column("default_tax_rate", sa.Numeric(5, 2), server_default=sa.text("15.00"), nullable=False))
    op.add_column("organisations", sa.Column("tax_inclusive_default", sa.Boolean(), server_default=sa.text("true"), nullable=False))
    op.add_column("organisations", sa.Column("date_format", sa.String(20), server_default=sa.text("'dd/MM/yyyy'"), nullable=False))
    op.add_column("organisations", sa.Column("number_format", sa.String(20), server_default=sa.text("'en-NZ'"), nullable=False))
    op.add_column("organisations", sa.Column("timezone", sa.String(50), server_default=sa.text("'Pacific/Auckland'"), nullable=False))
    op.add_column("organisations", sa.Column("compliance_profile_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("organisations", sa.Column("setup_wizard_state", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column("organisations", sa.Column("is_multi_location", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("organisations", sa.Column("franchise_group_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("organisations", sa.Column("white_label_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("organisations", sa.Column("storage_quota_bytes", sa.BigInteger(), server_default=sa.text("5368709120"), nullable=False))

    # -- Foreign key constraints ---------------------------------------------
    op.create_foreign_key(
        "fk_organisations_trade_category_id",
        "organisations",
        "trade_categories",
        ["trade_category_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_organisations_compliance_profile_id",
        "organisations",
        "compliance_profiles",
        ["compliance_profile_id"],
        ["id"],
    )
    # NOTE: franchise_group_id FK will be added in a later migration when
    # the franchise_groups table is created (Task 43).


def downgrade() -> None:
    op.drop_constraint("fk_organisations_compliance_profile_id", "organisations", type_="foreignkey")
    op.drop_constraint("fk_organisations_trade_category_id", "organisations", type_="foreignkey")
    op.drop_column("organisations", "storage_quota_bytes")
    op.drop_column("organisations", "white_label_enabled")
    op.drop_column("organisations", "franchise_group_id")
    op.drop_column("organisations", "is_multi_location")
    op.drop_column("organisations", "setup_wizard_state")
    op.drop_column("organisations", "compliance_profile_id")
    op.drop_column("organisations", "timezone")
    op.drop_column("organisations", "number_format")
    op.drop_column("organisations", "date_format")
    op.drop_column("organisations", "tax_inclusive_default")
    op.drop_column("organisations", "default_tax_rate")
    op.drop_column("organisations", "tax_label")
    op.drop_column("organisations", "locale")
    op.drop_column("organisations", "base_currency")
    op.drop_column("organisations", "data_residency_region")
    op.drop_column("organisations", "country_code")
    op.drop_column("organisations", "trade_category_id")
