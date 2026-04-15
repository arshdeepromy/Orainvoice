"""Create gst_filing_periods table and add is_gst_locked to invoices/expenses.

OraFlows Accounting & Tax — Sprint 3: GST Filing Periods + IRD Readiness.

Creates the gst_filing_periods table with RLS and adds is_gst_locked boolean
columns to the invoices and expenses tables for period locking.

Revision ID: 0143
Revises: 0142
Create Date: 2026-04-10

Requirements: 11.1, 11.3, 14.4, 32.1, 36.1
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision: str = "0143"
down_revision: str = "0142"
branch_labels = None
depends_on = None


_HA_ADD_TPL = """
DO $ha_block$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'ora_publication') THEN
        ALTER PUBLICATION ora_publication ADD TABLE {table};
    END IF;
END
$ha_block$
"""

_HA_DROP_TPL = """
DO $ha_block$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'ora_publication') THEN
        ALTER PUBLICATION ora_publication DROP TABLE IF EXISTS {table};
    END IF;
END
$ha_block$
"""


def upgrade() -> None:
    # ── 1. gst_filing_periods table ───────────────────────────────────────
    op.create_table(
        "gst_filing_periods",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("period_type", sa.String(20), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("filed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("filed_by", UUID(as_uuid=True), nullable=True),
        sa.Column("ird_reference", sa.String(50), nullable=True),
        sa.Column("return_data", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # Foreign keys
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_gst_filing_periods_org_id"),
        sa.ForeignKeyConstraint(["filed_by"], ["users.id"], name="fk_gst_filing_periods_filed_by"),
        # CHECK constraints
        sa.CheckConstraint(
            "period_type IN ('two_monthly','six_monthly','annual')",
            name="ck_gst_filing_periods_type",
        ),
        sa.CheckConstraint(
            "status IN ('draft','ready','filed','accepted','rejected')",
            name="ck_gst_filing_periods_status",
        ),
    )

    op.create_index("ix_gst_filing_periods_org_id", "gst_filing_periods", ["org_id"])
    op.create_index("ix_gst_filing_periods_org_status", "gst_filing_periods", ["org_id", "status"])

    # ── 2. Enable RLS + org isolation policy ──────────────────────────────
    op.execute("ALTER TABLE gst_filing_periods ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY gst_filing_periods_org_isolation ON gst_filing_periods "
        "USING (org_id = current_setting('app.current_org_id')::uuid)"
    )

    # ── 3. Add to HA replication publication if exists ────────────────────
    op.execute(sa.text(_HA_ADD_TPL.format(table="gst_filing_periods")))

    # ── 4. Add is_gst_locked columns to invoices and expenses ─────────────
    op.add_column("invoices", sa.Column("is_gst_locked", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("expenses", sa.Column("is_gst_locked", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    # Remove is_gst_locked columns
    op.drop_column("expenses", "is_gst_locked")
    op.drop_column("invoices", "is_gst_locked")

    # Drop HA publication membership
    op.execute(sa.text(_HA_DROP_TPL.format(table="gst_filing_periods")))

    # Drop RLS policy
    op.execute("DROP POLICY IF EXISTS gst_filing_periods_org_isolation ON gst_filing_periods")

    # Drop indexes and table
    op.drop_index("ix_gst_filing_periods_org_status", table_name="gst_filing_periods")
    op.drop_index("ix_gst_filing_periods_org_id", table_name="gst_filing_periods")
    op.drop_table("gst_filing_periods")
