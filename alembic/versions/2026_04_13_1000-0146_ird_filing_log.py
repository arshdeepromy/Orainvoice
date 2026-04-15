"""Create ird_filing_log table.

OraFlows Accounting & Tax — Sprint 6: IRD Gateway SOAP Integration.

Creates the ird_filing_log table with RLS, org_id isolation policy,
CHECK constraint on filing_type, and HA publication membership.

Also updates the accounting_integrations provider CHECK constraint
to allow 'ird' as a valid provider value.

Revision ID: 0146
Revises: 0145
Create Date: 2026-04-13

Requirements: 28.1, 28.2, 32.1, 36.1
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "0146"
down_revision: str = "0145"
branch_labels = None
depends_on = None


_TABLE = "ird_filing_log"

_HA_ADD = """
DO $ha_block$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'ora_publication') THEN
        ALTER PUBLICATION ora_publication ADD TABLE {table};
    END IF;
END
$ha_block$
"""

_HA_DROP = """
DO $ha_block$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'ora_publication') THEN
        ALTER PUBLICATION ora_publication DROP TABLE IF EXISTS {table};
    END IF;
END
$ha_block$
"""


def upgrade() -> None:
    # ── 1. ird_filing_log table ───────────────────────────────────────────
    op.create_table(
        _TABLE,
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("filing_type", sa.String(20), nullable=False),
        sa.Column("period_id", UUID(as_uuid=True), nullable=True),
        sa.Column("request_xml", sa.Text, nullable=True),
        sa.Column("response_xml", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("ird_reference", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # Foreign keys
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_ird_filing_log_org_id"),
        # CHECK: filing_type values
        sa.CheckConstraint(
            "filing_type IN ('gst','income_tax')",
            name="ck_ird_filing_log_type",
        ),
    )

    op.create_index("ix_ird_filing_log_org_id", _TABLE, ["org_id"])

    # ── 2. Enable RLS + create org isolation policy ───────────────────────
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {_TABLE}_org_isolation ON {_TABLE} "
        f"USING (org_id = current_setting('app.current_org_id')::uuid)"
    )

    # ── 3. Add table to HA replication publication if it exists ───────────
    op.execute(sa.text(_HA_ADD.format(table=_TABLE)))

    # ── 4. Update accounting_integrations provider CHECK to include 'ird' ─
    op.execute("ALTER TABLE accounting_integrations DROP CONSTRAINT IF EXISTS ck_accounting_integrations_provider")
    op.execute(
        "ALTER TABLE accounting_integrations ADD CONSTRAINT ck_accounting_integrations_provider "
        "CHECK (provider IN ('xero','myob','ird'))"
    )


def downgrade() -> None:
    # Restore original provider CHECK constraint
    op.execute("ALTER TABLE accounting_integrations DROP CONSTRAINT IF EXISTS ck_accounting_integrations_provider")
    op.execute(
        "ALTER TABLE accounting_integrations ADD CONSTRAINT ck_accounting_integrations_provider "
        "CHECK (provider IN ('xero','myob'))"
    )

    # Drop HA publication membership
    op.execute(sa.text(_HA_DROP.format(table=_TABLE)))

    # Drop RLS policy
    op.execute(f"DROP POLICY IF EXISTS {_TABLE}_org_isolation ON {_TABLE}")

    # Drop table
    op.drop_index("ix_ird_filing_log_org_id", table_name=_TABLE)
    op.drop_table(_TABLE)
