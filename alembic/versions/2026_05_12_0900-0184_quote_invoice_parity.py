"""Phase 5 — Quote ↔ Invoice Parity: new columns on quotes/quote_line_items,
new quote_attachments table, RLS policy, HA publication membership.

Adds parity fields to quotes and quote_line_items so that QuoteCreate
matches InvoiceCreate at the schema level. Creates the quote_attachments
table (mirroring invoice_attachments) with RLS and HA publication.

Revision ID: 0184
Revises: 0183
Create Date: 2026-05-12

Requirements: 13.1, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8, 13.9, 17.1, 17.2, 17.3, 17.4, 17.5
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0184"
down_revision: str = "0183"
branch_labels = None
depends_on = None

_ATT_TABLE = "quote_attachments"

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
    IF EXISTS (
        SELECT 1 FROM pg_publication_tables
        WHERE pubname = 'ora_publication' AND tablename = '{table}'
    ) THEN
        ALTER PUBLICATION ora_publication DROP TABLE {table};
    END IF;
END
$ha_block$
"""


def upgrade() -> None:
    # ── 1. New columns on quotes (all nullable — safe for existing rows) ──
    op.execute(
        "ALTER TABLE quotes "
        "ADD COLUMN IF NOT EXISTS order_number VARCHAR(100) NULL"
    )
    op.execute(
        "ALTER TABLE quotes "
        "ADD COLUMN IF NOT EXISTS salesperson_id UUID NULL "
        "REFERENCES users(id)"
    )
    op.execute(
        "ALTER TABLE quotes "
        "ADD COLUMN IF NOT EXISTS additional_vehicles JSONB NULL"
    )
    op.execute(
        "ALTER TABLE quotes "
        "ADD COLUMN IF NOT EXISTS fluid_usage JSONB NULL"
    )

    # ── 2. New columns on quote_line_items ────────────────────────────────
    op.execute(
        "ALTER TABLE quote_line_items "
        "ADD COLUMN IF NOT EXISTS catalogue_item_id UUID NULL"
    )
    op.execute(
        "ALTER TABLE quote_line_items "
        "ADD COLUMN IF NOT EXISTS stock_item_id UUID NULL"
    )
    op.execute(
        "ALTER TABLE quote_line_items "
        "ADD COLUMN IF NOT EXISTS gst_inclusive BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE quote_line_items "
        "ADD COLUMN IF NOT EXISTS inclusive_price NUMERIC(12,2) NULL"
    )
    op.execute(
        "ALTER TABLE quote_line_items "
        "ADD COLUMN IF NOT EXISTS tax_rate NUMERIC(5,2) NOT NULL DEFAULT 15"
    )

    # ── 3. Create quote_attachments table ─────────────────────────────────
    # Idempotent: skip if table already exists (e.g. from HA replication)
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = 'quote_attachments'"
    ))
    if result.scalar():
        return

    op.create_table(
        _ATT_TABLE,
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("quote_id", UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("file_key", sa.String(500), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("uploaded_by", UUID(as_uuid=True), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # Foreign keys
        sa.ForeignKeyConstraint(
            ["quote_id"],
            ["quotes.id"],
            name="fk_quote_attachments_quote_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organisations.id"],
            name="fk_quote_attachments_org_id",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name="fk_quote_attachments_uploaded_by",
        ),
    )

    # Create composite index for common query patterns
    op.create_index(
        "ix_quote_attachments_quote_org",
        _ATT_TABLE,
        ["quote_id", "org_id"],
    )

    # Enable RLS + create org isolation policy
    op.execute(f"ALTER TABLE {_ATT_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {_ATT_TABLE}_org_isolation ON {_ATT_TABLE} "
        "USING (org_id = current_setting('app.current_org_id')::uuid)"
    )

    # Add table to HA replication publication if it exists
    op.execute(sa.text(_HA_ADD_TPL.format(table=_ATT_TABLE)))


def downgrade() -> None:
    # ── 1. Drop HA publication membership (guarded) ───────────────────────
    op.execute(sa.text(_HA_DROP_TPL.format(table=_ATT_TABLE)))

    # ── 2. Drop RLS policy ────────────────────────────────────────────────
    op.execute(f"DROP POLICY IF EXISTS {_ATT_TABLE}_org_isolation ON {_ATT_TABLE}")

    # ── 3. Drop index ────────────────────────────────────────────────────
    op.execute("DROP INDEX IF EXISTS ix_quote_attachments_quote_org")

    # ── 4. Drop quote_attachments table ───────────────────────────────────
    op.execute(f"DROP TABLE IF EXISTS {_ATT_TABLE}")

    # ── 5. Drop quote_line_items columns (reverse order) ──────────────────
    op.execute("ALTER TABLE quote_line_items DROP COLUMN IF EXISTS tax_rate")
    op.execute("ALTER TABLE quote_line_items DROP COLUMN IF EXISTS inclusive_price")
    op.execute("ALTER TABLE quote_line_items DROP COLUMN IF EXISTS gst_inclusive")
    op.execute("ALTER TABLE quote_line_items DROP COLUMN IF EXISTS stock_item_id")
    op.execute("ALTER TABLE quote_line_items DROP COLUMN IF EXISTS catalogue_item_id")

    # ── 6. Drop quotes columns (reverse order) ───────────────────────────
    op.execute("ALTER TABLE quotes DROP COLUMN IF EXISTS fluid_usage")
    op.execute("ALTER TABLE quotes DROP COLUMN IF EXISTS additional_vehicles")
    op.execute("ALTER TABLE quotes DROP COLUMN IF EXISTS salesperson_id")
    op.execute("ALTER TABLE quotes DROP COLUMN IF EXISTS order_number")
