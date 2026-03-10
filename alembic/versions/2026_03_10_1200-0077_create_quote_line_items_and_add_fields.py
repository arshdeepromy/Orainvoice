"""Create quote_line_items table and add missing columns to quotes.

Revision ID: 0077
Revises: 0076_register_vehicles_module
Create Date: 2026-03-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0077_quote_line_items_and_fields"
down_revision: str = "0076_register_vehicles_module"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # Create quote_line_items table (the ORM model expects it)
    op.create_table(
        "quote_line_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("quote_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_type", sa.String(10), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("quantity", sa.Numeric(10, 3), server_default=sa.text("1"), nullable=False),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("hours", sa.Numeric(6, 2), nullable=True),
        sa.Column("hourly_rate", sa.Numeric(10, 2), nullable=True),
        sa.Column("is_gst_exempt", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("warranty_note", sa.Text(), nullable=True),
        sa.Column("line_total", sa.Numeric(12, 2), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["quote_id"], ["quotes.id"], name="fk_quote_line_items_quote_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_quote_line_items_org_id"),
        sa.CheckConstraint("item_type IN ('service','part','labour')", name="ck_quote_line_items_item_type"),
    )
    op.create_index("idx_quote_line_items_quote", "quote_line_items", ["quote_id"])

    # Add missing columns to quotes table that the ORM model expects
    # valid_until (the ORM uses this, DB has expiry_date)
    op.add_column("quotes", sa.Column("valid_until", sa.Date(), nullable=True))
    # notes (the ORM uses this, DB has terms/internal_notes)
    op.add_column("quotes", sa.Column("notes", sa.Text(), nullable=True))
    # gst_amount (the ORM uses this, DB has tax_amount)
    op.add_column("quotes", sa.Column("gst_amount", sa.Numeric(12, 2), server_default=sa.text("0"), nullable=True))
    # vehicle fields
    op.add_column("quotes", sa.Column("vehicle_rego", sa.String(20), nullable=True))
    op.add_column("quotes", sa.Column("vehicle_make", sa.String(100), nullable=True))
    op.add_column("quotes", sa.Column("vehicle_model", sa.String(100), nullable=True))
    op.add_column("quotes", sa.Column("vehicle_year", sa.Integer(), nullable=True))

    # Update the status check constraint to include 'converted'
    op.execute("ALTER TABLE quotes DROP CONSTRAINT IF EXISTS ck_quotes_status")
    op.create_check_constraint(
        "ck_quotes_status",
        "quotes",
        "status IN ('draft','sent','accepted','declined','expired','converted')",
    )

    # Enable RLS on quote_line_items
    op.execute("ALTER TABLE quote_line_items ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE quote_line_items DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_quote_line_items_quote", table_name="quote_line_items")
    op.drop_table("quote_line_items")
    op.drop_column("quotes", "vehicle_year")
    op.drop_column("quotes", "vehicle_model")
    op.drop_column("quotes", "vehicle_make")
    op.drop_column("quotes", "vehicle_rego")
    op.drop_column("quotes", "gst_amount")
    op.drop_column("quotes", "notes")
    op.drop_column("quotes", "valid_until")
    op.execute("ALTER TABLE quotes DROP CONSTRAINT IF EXISTS ck_quotes_status")
    op.execute("ALTER TABLE quotes ADD CONSTRAINT ck_quotes_status CHECK (status IN ('draft','sent','accepted','declined','expired'))")
