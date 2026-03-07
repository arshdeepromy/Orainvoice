"""Seed compliance_profiles for NZ, AU, UK, and Generic.

Revision ID: 0020
Revises: 0019
Create Date: 2025-01-15

Requirements: 5.2
"""

from __future__ import annotations

import json
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: str = "0019"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

COMPLIANCE_PROFILES = [
    {
        "country_code": "NZ",
        "country_name": "New Zealand",
        "tax_label": "GST",
        "default_tax_rates": json.dumps([{"name": "GST", "rate": 15.0, "is_default": True}]),
        "tax_number_label": "GST Number",
        "tax_number_regex": r"^\d{2,3}-?\d{3}-?\d{3}$",
        "tax_inclusive_default": True,
        "date_format": "dd/MM/yyyy",
        "number_format": "en-NZ",
        "currency_code": "NZD",
        "report_templates": json.dumps(["gst_return"]),
        "gdpr_applicable": False,
    },
    {
        "country_code": "AU",
        "country_name": "Australia",
        "tax_label": "GST",
        "default_tax_rates": json.dumps([{"name": "GST", "rate": 10.0, "is_default": True}]),
        "tax_number_label": "ABN",
        "tax_number_regex": r"^\d{2}\s?\d{3}\s?\d{3}\s?\d{3}$",
        "tax_inclusive_default": True,
        "date_format": "dd/MM/yyyy",
        "number_format": "en-AU",
        "currency_code": "AUD",
        "report_templates": json.dumps(["bas_report"]),
        "gdpr_applicable": False,
    },
    {
        "country_code": "GB",
        "country_name": "United Kingdom",
        "tax_label": "VAT",
        "default_tax_rates": json.dumps([
            {"name": "Standard", "rate": 20.0, "is_default": True},
            {"name": "Reduced", "rate": 5.0, "is_default": False},
            {"name": "Zero", "rate": 0.0, "is_default": False},
        ]),
        "tax_number_label": "VAT Number",
        "tax_number_regex": r"^GB\d{9}$|^GB\d{12}$|^GBGD\d{3}$|^GBHA\d{3}$",
        "tax_inclusive_default": True,
        "date_format": "dd/MM/yyyy",
        "number_format": "en-GB",
        "currency_code": "GBP",
        "report_templates": json.dumps(["vat_return"]),
        "gdpr_applicable": True,
    },
    {
        "country_code": "XX",
        "country_name": "Generic",
        "tax_label": "Tax",
        "default_tax_rates": json.dumps([{"name": "None", "rate": 0.0, "is_default": True}]),
        "tax_number_label": None,
        "tax_number_regex": None,
        "tax_inclusive_default": False,
        "date_format": "MM/dd/yyyy",
        "number_format": "en-US",
        "currency_code": "USD",
        "report_templates": json.dumps([]),
        "gdpr_applicable": False,
    },
]


def upgrade() -> None:
    compliance_profiles = sa.table(
        "compliance_profiles",
        sa.column("country_code", sa.String),
        sa.column("country_name", sa.String),
        sa.column("tax_label", sa.String),
        sa.column("default_tax_rates", postgresql.JSONB),
        sa.column("tax_number_label", sa.String),
        sa.column("tax_number_regex", sa.String),
        sa.column("tax_inclusive_default", sa.Boolean),
        sa.column("date_format", sa.String),
        sa.column("number_format", sa.String),
        sa.column("currency_code", sa.String),
        sa.column("report_templates", postgresql.JSONB),
        sa.column("gdpr_applicable", sa.Boolean),
    )
    op.bulk_insert(compliance_profiles, COMPLIANCE_PROFILES)


def downgrade() -> None:
    codes = [p["country_code"] for p in COMPLIANCE_PROFILES]
    op.execute(
        sa.text("DELETE FROM compliance_profiles WHERE country_code = ANY(:codes)").bindparams(
            codes=codes
        )
    )
