"""Create akahu_connections, bank_accounts, bank_transactions tables.

OraFlows Accounting & Tax — Sprint 4: Akahu Bank Feeds + Reconciliation.

Creates the three banking tables with RLS, org_id isolation policies,
unique constraints on Akahu IDs, and the one-match CHECK constraint on
bank_transactions.

Revision ID: 0144
Revises: 0143
Create Date: 2026-04-11

Requirements: 15.6, 16.4, 17.6, 18.5, 32.1, 36.1
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision: str = "0144"
down_revision: str = "0143"
branch_labels = None
depends_on = None


_TABLES = ["akahu_connections", "bank_accounts", "bank_transactions"]

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
    # ── 1. akahu_connections ──────────────────────────────────────────────
    op.create_table(
        "akahu_connections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("access_token_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # Foreign keys
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_akahu_connections_org_id"),
        # Unique: one connection per org
        sa.UniqueConstraint("org_id", name="uq_akahu_connections_org"),
    )

    op.create_index("ix_akahu_connections_org_id", "akahu_connections", ["org_id"])

    # ── 2. bank_accounts ──────────────────────────────────────────────────
    op.create_table(
        "bank_accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("akahu_account_id", sa.String(100), nullable=False),
        sa.Column("account_name", sa.String(200), nullable=False),
        sa.Column("account_number", sa.String(50), nullable=True),
        sa.Column("bank_name", sa.String(100), nullable=True),
        sa.Column("account_type", sa.String(50), nullable=True),
        sa.Column("balance", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("currency", sa.String(3), nullable=False, server_default=sa.text("'NZD'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("linked_gl_account_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # Foreign keys
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_bank_accounts_org_id"),
        sa.ForeignKeyConstraint(["linked_gl_account_id"], ["accounts.id"], name="fk_bank_accounts_gl_account"),
        # Unique: one Akahu account per org
        sa.UniqueConstraint("org_id", "akahu_account_id", name="uq_bank_accounts_org_akahu"),
    )

    op.create_index("ix_bank_accounts_org_id", "bank_accounts", ["org_id"])

    # ── 3. bank_transactions ──────────────────────────────────────────────
    op.create_table(
        "bank_transactions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("bank_account_id", UUID(as_uuid=True), nullable=False),
        sa.Column("akahu_transaction_id", sa.String(100), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("balance", sa.Numeric(12, 2), nullable=True),
        sa.Column("merchant_name", sa.String(200), nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("reconciliation_status", sa.String(20), nullable=False, server_default=sa.text("'unmatched'")),
        sa.Column("matched_invoice_id", UUID(as_uuid=True), nullable=True),
        sa.Column("matched_expense_id", UUID(as_uuid=True), nullable=True),
        sa.Column("matched_journal_id", UUID(as_uuid=True), nullable=True),
        sa.Column("akahu_raw", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # Foreign keys
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_bank_transactions_org_id"),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"], name="fk_bank_transactions_bank_account"),
        sa.ForeignKeyConstraint(["matched_invoice_id"], ["invoices.id"], name="fk_bank_transactions_invoice"),
        sa.ForeignKeyConstraint(["matched_expense_id"], ["expenses.id"], name="fk_bank_transactions_expense"),
        sa.ForeignKeyConstraint(["matched_journal_id"], ["journal_entries.id"], name="fk_bank_transactions_journal"),
        # Unique: one Akahu transaction per org
        sa.UniqueConstraint("org_id", "akahu_transaction_id", name="uq_bank_transactions_org_akahu"),
        # CHECK: reconciliation_status values
        sa.CheckConstraint(
            "reconciliation_status IN ('unmatched','matched','excluded','manual')",
            name="ck_bank_transactions_status",
        ),
        # CHECK: at most one match FK set
        sa.CheckConstraint(
            "(CASE WHEN matched_invoice_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN matched_expense_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN matched_journal_id IS NOT NULL THEN 1 ELSE 0 END) <= 1",
            name="ck_bank_transactions_one_match",
        ),
    )

    op.create_index("ix_bank_transactions_org_id", "bank_transactions", ["org_id"])
    op.create_index("ix_bank_transactions_bank_account", "bank_transactions", ["bank_account_id"])
    op.create_index("ix_bank_transactions_org_date", "bank_transactions", ["org_id", "date"])
    op.create_index("ix_bank_transactions_status", "bank_transactions", ["org_id", "reconciliation_status"])

    # ── 4. Enable RLS + create org isolation policies ─────────────────────
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_org_isolation ON {table} "
            f"USING (org_id = current_setting('app.current_org_id')::uuid)"
        )

    # ── 5. Add tables to HA replication publication if it exists ──────────
    for table in _TABLES:
        op.execute(sa.text(_HA_ADD_TPL.format(table=table)))


def downgrade() -> None:
    # Drop HA publication membership
    for table in reversed(_TABLES):
        op.execute(sa.text(_HA_DROP_TPL.format(table=table)))

    # Drop RLS policies
    for table in reversed(_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_org_isolation ON {table}")

    # Drop tables in reverse dependency order
    op.drop_index("ix_bank_transactions_status", table_name="bank_transactions")
    op.drop_index("ix_bank_transactions_org_date", table_name="bank_transactions")
    op.drop_index("ix_bank_transactions_bank_account", table_name="bank_transactions")
    op.drop_index("ix_bank_transactions_org_id", table_name="bank_transactions")
    op.drop_table("bank_transactions")

    op.drop_index("ix_bank_accounts_org_id", table_name="bank_accounts")
    op.drop_table("bank_accounts")

    op.drop_index("ix_akahu_connections_org_id", table_name="akahu_connections")
    op.drop_table("akahu_connections")
