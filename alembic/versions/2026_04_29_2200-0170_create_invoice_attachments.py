"""Create invoice_attachments table for file attachments on invoices.

Creates the invoice_attachments table for storing metadata about images
(JPEG, PNG, WebP, GIF) and PDFs attached to invoices. The actual file
content is stored encrypted on disk at the path specified by file_key.

- CREATE TABLE invoice_attachments with all columns
- CREATE INDEX on (invoice_id, org_id)
- Enable RLS with policy matching app.current_org_id
- Add table to HA replication publication if it exists

Revision ID: 0170
Revises: 0169
Create Date: 2026-04-29

Requirements: 1.1, 1.2, 1.3, 1.4
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "0170"
down_revision: str = "0169"
branch_labels = None
depends_on = None


_TABLE = "invoice_attachments"

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
    # Idempotent: skip if table already exists (e.g. from HA replication)
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = 'invoice_attachments'"
    ))
    if result.scalar():
        return

    # ── 1. Create invoice_attachments table ───────────────────────────────
    op.create_table(
        _TABLE,
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("invoice_id", UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("file_key", sa.String(500), nullable=False, comment="Path to encrypted file on disk"),
        sa.Column("file_name", sa.String(255), nullable=False, comment="Original filename"),
        sa.Column("file_size", sa.Integer(), nullable=False, comment="Size in bytes after compression/encryption"),
        sa.Column("mime_type", sa.String(100), nullable=False, comment="MIME type, e.g. image/jpeg, application/pdf"),
        sa.Column("uploaded_by", UUID(as_uuid=True), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # Foreign keys
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
            name="fk_invoice_attachments_invoice_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organisations.id"],
            name="fk_invoice_attachments_org_id",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name="fk_invoice_attachments_uploaded_by",
        ),
    )

    # ── 2. Create composite index for common query patterns ───────────────
    op.create_index(
        "ix_invoice_attachments_invoice_org",
        _TABLE,
        ["invoice_id", "org_id"],
    )

    # ── 3. Enable RLS + create org isolation policy ───────────────────────
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {_TABLE}_org_isolation ON {_TABLE} "
        "USING (org_id = current_setting('app.current_org_id')::uuid)"
    )

    # ── 4. Add table to HA replication publication if it exists ───────────
    op.execute(sa.text(_HA_ADD_TPL.format(table=_TABLE)))


def downgrade() -> None:
    # Drop HA publication membership
    op.execute(sa.text(_HA_DROP_TPL.format(table=_TABLE)))

    # Drop RLS policy
    op.execute(f"DROP POLICY IF EXISTS {_TABLE}_org_isolation ON {_TABLE}")

    # Drop index
    op.drop_index("ix_invoice_attachments_invoice_org", table_name=_TABLE)

    # Drop table
    op.drop_table(_TABLE)
