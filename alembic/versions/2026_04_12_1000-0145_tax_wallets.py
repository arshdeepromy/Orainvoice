"""Create tax_wallets and tax_wallet_transactions tables.

OraFlows Accounting & Tax — Sprint 5: Tax Savings Wallets.

Creates the two tax wallet tables with RLS, org_id isolation policies,
unique constraint on (org_id, wallet_type), CHECK constraints on
wallet_type and transaction_type.

Revision ID: 0145
Revises: 0144
Create Date: 2026-04-12

Requirements: 20.1, 20.2, 20.3, 32.1, 36.1
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "0145"
down_revision: str = "0144"
branch_labels = None
depends_on = None


_TABLES = ["tax_wallets", "tax_wallet_transactions"]

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
    # ── 1. tax_wallets ────────────────────────────────────────────────────
    op.create_table(
        "tax_wallets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("wallet_type", sa.String(20), nullable=False),
        sa.Column("balance", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("target_balance", sa.Numeric(12, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # Foreign keys
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_tax_wallets_org_id"),
        # Unique: one wallet per type per org
        sa.UniqueConstraint("org_id", "wallet_type", name="uq_tax_wallets_org_type"),
        # CHECK: wallet_type values
        sa.CheckConstraint(
            "wallet_type IN ('gst','income_tax','provisional_tax')",
            name="ck_tax_wallets_type",
        ),
    )

    op.create_index("ix_tax_wallets_org_id", "tax_wallets", ["org_id"])

    # ── 2. tax_wallet_transactions ────────────────────────────────────────
    op.create_table(
        "tax_wallet_transactions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("wallet_id", UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("transaction_type", sa.String(20), nullable=False),
        sa.Column("source_payment_id", UUID(as_uuid=True), nullable=True),
        sa.Column("description", sa.String(200), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # Foreign keys
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_wallet_tx_org_id"),
        sa.ForeignKeyConstraint(["wallet_id"], ["tax_wallets.id"], name="fk_wallet_tx_wallet_id"),
        sa.ForeignKeyConstraint(["source_payment_id"], ["payments.id"], name="fk_wallet_tx_payment"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_wallet_tx_created_by"),
        # CHECK: transaction_type values
        sa.CheckConstraint(
            "transaction_type IN ('auto_sweep','manual_deposit','manual_withdrawal','tax_payment')",
            name="ck_wallet_tx_type",
        ),
    )

    op.create_index("ix_wallet_tx_org_id", "tax_wallet_transactions", ["org_id"])
    op.create_index("ix_wallet_tx_wallet_id", "tax_wallet_transactions", ["wallet_id"])

    # ── 3. Enable RLS + create org isolation policies ─────────────────────
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_org_isolation ON {table} "
            f"USING (org_id = current_setting('app.current_org_id')::uuid)"
        )

    # ── 4. Add tables to HA replication publication if it exists ──────────
    for table in _TABLES:
        op.execute(sa.text(_HA_ADD_TPL.format(table=table)))

    # ── 5. Add tax sweep settings defaults to organisations.settings ──────
    # These are JSONB defaults — existing orgs keep their current settings,
    # new orgs get these via application-level defaults.
    # No ALTER TABLE needed since settings is already a JSONB column.


def downgrade() -> None:
    # Drop HA publication membership
    for table in reversed(_TABLES):
        op.execute(sa.text(_HA_DROP_TPL.format(table=table)))

    # Drop RLS policies
    for table in reversed(_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_org_isolation ON {table}")

    # Drop tables in reverse dependency order
    op.drop_index("ix_wallet_tx_wallet_id", table_name="tax_wallet_transactions")
    op.drop_index("ix_wallet_tx_org_id", table_name="tax_wallet_transactions")
    op.drop_table("tax_wallet_transactions")

    op.drop_index("ix_tax_wallets_org_id", table_name="tax_wallets")
    op.drop_table("tax_wallets")
