"""Create quotes table.

Revision ID: 0031
Revises: 0030
Create Date: 2025-01-15

Requirements: 12.1, 12.2, 12.3, 12.7
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0031"
down_revision: str = "0030"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # Table was originally created in migration 0006 with a different schema.
    # Drop and recreate with the new schema (uses JSONB line_items, versioning, etc.)
    op.execute("ALTER TABLE IF EXISTS quotes DISABLE ROW LEVEL SECURITY")
    op.execute("DROP TABLE IF EXISTS quote_line_items CASCADE")
    op.execute("DROP TABLE IF EXISTS quotes CASCADE")

    op.create_table(
        "quotes",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quote_number", sa.String(50), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(20), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("terms", sa.Text(), nullable=True),
        sa.Column("internal_notes", sa.Text(), nullable=True),
        sa.Column("line_items", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2), server_default=sa.text("0"), nullable=False),
        sa.Column("tax_amount", sa.Numeric(12, 2), server_default=sa.text("0"), nullable=False),
        sa.Column("total", sa.Numeric(12, 2), server_default=sa.text("0"), nullable=False),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("version_number", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("previous_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("converted_invoice_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("acceptance_token", sa.String(255), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_quotes_org_id"),
        sa.ForeignKeyConstraint(["previous_version_id"], ["quotes.id"], name="fk_quotes_previous_version"),
        sa.UniqueConstraint("org_id", "quote_number", name="uq_quotes_org_quote_number"),
    )
    op.create_index("idx_quotes_org_status", "quotes", ["org_id", "status"])
    op.create_index("idx_quotes_customer", "quotes", ["customer_id"])
    op.create_index("idx_quotes_expiry", "quotes", ["status", "expiry_date"])
    op.create_index("idx_quotes_acceptance_token", "quotes", ["acceptance_token"], unique=True)


def downgrade() -> None:
    op.drop_index("idx_quotes_acceptance_token", table_name="quotes")
    op.drop_index("idx_quotes_expiry", table_name="quotes")
    op.drop_index("idx_quotes_customer", table_name="quotes")
    op.drop_index("idx_quotes_org_status", table_name="quotes")
    op.drop_table("quotes")
