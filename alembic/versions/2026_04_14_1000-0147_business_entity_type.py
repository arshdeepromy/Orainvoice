"""Add business entity type columns to organisations.

OraFlows Accounting & Tax — Sprint 7: Business Entity Type Classification.

Adds business_type, nzbn, nz_company_number, gst_registered,
gst_registration_date, income_tax_year_end, and provisional_tax_method
columns to the organisations table with CHECK constraints.

Revision ID: 0147
Revises: 0146
Create Date: 2026-04-14

Requirements: 29.1, 29.2
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "0147"
down_revision: str = "0146"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Add business entity columns to organisations ───────────────────
    op.add_column(
        "organisations",
        sa.Column("business_type", sa.String(20), server_default="sole_trader", nullable=True),
    )
    op.add_column(
        "organisations",
        sa.Column("nzbn", sa.String(13), nullable=True),
    )
    op.add_column(
        "organisations",
        sa.Column("nz_company_number", sa.String(10), nullable=True),
    )
    op.add_column(
        "organisations",
        sa.Column("gst_registered", sa.Boolean, server_default="false", nullable=False),
    )
    op.add_column(
        "organisations",
        sa.Column("gst_registration_date", sa.Date, nullable=True),
    )
    op.add_column(
        "organisations",
        sa.Column("income_tax_year_end", sa.Date, server_default="2026-03-31", nullable=True),
    )
    op.add_column(
        "organisations",
        sa.Column("provisional_tax_method", sa.String(20), server_default="standard", nullable=True),
    )

    # ── 2. CHECK constraints ──────────────────────────────────────────────
    op.execute(
        "ALTER TABLE organisations ADD CONSTRAINT ck_organisations_business_type "
        "CHECK (business_type IN ('sole_trader','partnership','company','trust','other'))"
    )
    op.execute(
        "ALTER TABLE organisations ADD CONSTRAINT ck_organisations_provisional_method "
        "CHECK (provisional_tax_method IN ('standard','estimation','ratio'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE organisations DROP CONSTRAINT IF EXISTS ck_organisations_provisional_method")
    op.execute("ALTER TABLE organisations DROP CONSTRAINT IF EXISTS ck_organisations_business_type")

    op.drop_column("organisations", "provisional_tax_method")
    op.drop_column("organisations", "income_tax_year_end")
    op.drop_column("organisations", "gst_registration_date")
    op.drop_column("organisations", "gst_registered")
    op.drop_column("organisations", "nz_company_number")
    op.drop_column("organisations", "nzbn")
    op.drop_column("organisations", "business_type")
