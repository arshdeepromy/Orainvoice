"""Create accounts, journal_entries, journal_lines, accounting_periods tables.

OraFlows Accounting & Tax — Sprint 1 foundation tables for the
double-entry general ledger: Chart of Accounts (COA), journal engine,
and accounting period management.

Each table has RLS enabled with org_id isolation policies and is added
to the HA replication publication if it exists.

NOTE: COA seed data (30 NZ standard accounts) is NOT inserted here.
Seeding happens at org creation time via the ledger service layer so
that each org gets its own set of accounts with the correct org_id.

Revision ID: 0142
Revises: 0141
Create Date: 2026-04-09

Requirements: 1.1, 1.2, 1.3, 1.4, 1.7, 2.1, 2.6, 2.7, 3.1, 3.4, 3.5, 32.1, 36.1
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "0142"
down_revision: str = "0141"
branch_labels = None
depends_on = None


# Tables created by this migration — used for RLS + HA publication loops.
_TABLES = ["accounts", "journal_entries", "journal_lines", "accounting_periods"]

# PL/pgSQL block to conditionally add a table to the HA publication.
_HA_ADD_TPL = """
DO $ha_block$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'ora_publication') THEN
        ALTER PUBLICATION ora_publication ADD TABLE {table};
    END IF;
END
$ha_block$
"""

# PL/pgSQL block to conditionally drop a table from the HA publication.
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
    # ── 1. accounting_periods ─────────────────────────────────────────────
    # Created first because journal_entries has an FK to this table.
    op.create_table(
        "accounting_periods",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("period_name", sa.String(50), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("closed_by", UUID(as_uuid=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # Foreign keys
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_accounting_periods_org_id"),
        sa.ForeignKeyConstraint(["closed_by"], ["users.id"], name="fk_accounting_periods_closed_by"),
        # CHECK constraints
        sa.CheckConstraint("start_date < end_date", name="ck_accounting_periods_dates"),
    )

    op.create_index("ix_accounting_periods_org_id", "accounting_periods", ["org_id"])

    # ── 2. accounts (Chart of Accounts) ───────────────────────────────────
    op.create_table(
        "accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(10), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("account_type", sa.String(20), nullable=False),
        sa.Column("sub_type", sa.String(50), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("parent_id", UUID(as_uuid=True), nullable=True),
        sa.Column("tax_code", sa.String(20), nullable=True),
        sa.Column("xero_account_code", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # Foreign keys
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_accounts_org_id"),
        sa.ForeignKeyConstraint(["parent_id"], ["accounts.id"], name="fk_accounts_parent_id"),
        # Unique + CHECK constraints
        sa.UniqueConstraint("org_id", "code", name="uq_accounts_org_code"),
        sa.CheckConstraint(
            "account_type IN ('asset','liability','equity','revenue','expense','cogs')",
            name="ck_accounts_type",
        ),
    )

    op.create_index("ix_accounts_org_id", "accounts", ["org_id"])
    op.create_index("ix_accounts_org_type", "accounts", ["org_id", "account_type"])

    # ── 3. journal_entries ────────────────────────────────────────────────
    op.create_table(
        "journal_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("entry_number", sa.String(20), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("reference", sa.String(100), nullable=True),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("source_id", UUID(as_uuid=True), nullable=True),
        sa.Column("period_id", UUID(as_uuid=True), nullable=True),
        sa.Column("is_posted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # Foreign keys
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_journal_entries_org_id"),
        sa.ForeignKeyConstraint(["period_id"], ["accounting_periods.id"], name="fk_journal_entries_period_id"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_journal_entries_created_by"),
        # CHECK constraints
        sa.CheckConstraint(
            "source_type IN ('invoice','payment','expense','credit_note','manual')",
            name="ck_journal_entries_source_type",
        ),
    )

    op.create_index("ix_journal_entries_org_id", "journal_entries", ["org_id"])
    op.create_index("ix_journal_entries_org_date", "journal_entries", ["org_id", "entry_date"])
    op.create_index("ix_journal_entries_source", "journal_entries", ["source_type", "source_id"])
    op.create_index("ix_journal_entries_period", "journal_entries", ["period_id"])

    # ── 4. journal_lines ──────────────────────────────────────────────────
    op.create_table(
        "journal_lines",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("journal_entry_id", UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", UUID(as_uuid=True), nullable=False),
        sa.Column("debit", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("credit", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("description", sa.String(500), nullable=True),
        # Foreign keys
        sa.ForeignKeyConstraint(
            ["journal_entry_id"],
            ["journal_entries.id"],
            name="fk_journal_lines_entry_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_journal_lines_org_id"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name="fk_journal_lines_account_id"),
        # CHECK constraints
        sa.CheckConstraint(
            "(debit > 0 AND credit = 0) OR (debit = 0 AND credit > 0)",
            name="ck_journal_lines_one_side",
        ),
    )

    op.create_index("ix_journal_lines_entry", "journal_lines", ["journal_entry_id"])
    op.create_index("ix_journal_lines_org_id", "journal_lines", ["org_id"])
    op.create_index("ix_journal_lines_account", "journal_lines", ["account_id"])

    # ── 5. Enable RLS + create org isolation policies ─────────────────────
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_org_isolation ON {table} "
            f"USING (org_id = current_setting('app.current_org_id')::uuid)"
        )

    # ── 6. Add tables to HA replication publication if it exists ──────────
    for table in _TABLES:
        op.execute(sa.text(_HA_ADD_TPL.format(table=table)))


def downgrade() -> None:
    # Drop HA publication membership (safe even if publication doesn't exist)
    for table in reversed(_TABLES):
        op.execute(sa.text(_HA_DROP_TPL.format(table=table)))

    # Drop RLS policies
    for table in reversed(_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_org_isolation ON {table}")

    # Drop tables in reverse dependency order
    op.drop_index("ix_journal_lines_account", table_name="journal_lines")
    op.drop_index("ix_journal_lines_org_id", table_name="journal_lines")
    op.drop_index("ix_journal_lines_entry", table_name="journal_lines")
    op.drop_table("journal_lines")

    op.drop_index("ix_journal_entries_period", table_name="journal_entries")
    op.drop_index("ix_journal_entries_source", table_name="journal_entries")
    op.drop_index("ix_journal_entries_org_date", table_name="journal_entries")
    op.drop_index("ix_journal_entries_org_id", table_name="journal_entries")
    op.drop_table("journal_entries")

    op.drop_index("ix_accounts_org_type", table_name="accounts")
    op.drop_index("ix_accounts_org_id", table_name="accounts")
    op.drop_table("accounts")

    op.drop_index("ix_accounting_periods_org_id", table_name="accounting_periods")
    op.drop_table("accounting_periods")
