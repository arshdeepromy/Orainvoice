"""Create invoice, line items, payments, credit notes tables and
sequence tables for gap-free numbering — with RLS enabled.

Revision ID: 0005
Revises: 0004
Create Date: 2025-01-15

Requirements: 17.1, 18.1, 19.1, 20.1, 23.1, 24.1, 25.1, 26.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str = "0004"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # -- invoice_sequences ---------------------------------------------------
    op.create_table(
        "invoice_sequences",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "last_number",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organisations.id"],
            name="fk_invoice_sequences_org_id",
        ),
        sa.UniqueConstraint("org_id", name="uq_invoice_sequences_org_id"),
    )
    op.execute("ALTER TABLE invoice_sequences ENABLE ROW LEVEL SECURITY")

    # -- quote_sequences -----------------------------------------------------
    op.create_table(
        "quote_sequences",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "last_number",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organisations.id"],
            name="fk_quote_sequences_org_id",
        ),
        sa.UniqueConstraint("org_id", name="uq_quote_sequences_org_id"),
    )
    op.execute("ALTER TABLE quote_sequences ENABLE ROW LEVEL SECURITY")

    # -- credit_note_sequences -----------------------------------------------
    op.create_table(
        "credit_note_sequences",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "last_number",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organisations.id"],
            name="fk_credit_note_sequences_org_id",
        ),
        sa.UniqueConstraint("org_id", name="uq_credit_note_sequences_org_id"),
    )
    op.execute("ALTER TABLE credit_note_sequences ENABLE ROW LEVEL SECURITY")

    # -- invoices ------------------------------------------------------------
    op.create_table(
        "invoices",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invoice_number", sa.String(50), nullable=True),
        sa.Column("vehicle_rego", sa.String(20), nullable=True),
        sa.Column("vehicle_make", sa.String(100), nullable=True),
        sa.Column("vehicle_model", sa.String(100), nullable=True),
        sa.Column("vehicle_year", sa.Integer(), nullable=True),
        sa.Column("vehicle_odometer", sa.Integer(), nullable=True),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column(
            "currency", sa.String(3), nullable=False, server_default="NZD"
        ),
        sa.Column(
            "subtotal",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "discount_amount",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("discount_type", sa.String(10), nullable=True),
        sa.Column("discount_value", sa.Numeric(12, 2), nullable=True),
        sa.Column(
            "gst_amount",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "total",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "amount_paid",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "balance_due",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("notes_internal", sa.Text(), nullable=True),
        sa.Column("notes_customer", sa.Text(), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "recurring_schedule_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "job_card_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "quote_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "invoice_data_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organisations.id"],
            name="fk_invoices_org_id",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name="fk_invoices_customer_id",
        ),
        sa.ForeignKeyConstraint(
            ["branch_id"],
            ["branches.id"],
            name="fk_invoices_branch_id",
        ),
        sa.ForeignKeyConstraint(
            ["voided_by"],
            ["users.id"],
            name="fk_invoices_voided_by",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_invoices_created_by",
        ),
        sa.CheckConstraint(
            "status IN ('draft','issued','partially_paid','paid','overdue','voided')",
            name="ck_invoices_status",
        ),
        sa.CheckConstraint(
            "discount_type IN ('percentage','fixed')",
            name="ck_invoices_discount_type",
        ),
    )
    op.execute("ALTER TABLE invoices ENABLE ROW LEVEL SECURITY")
    op.create_index("idx_invoices_org", "invoices", ["org_id"])
    op.create_index("idx_invoices_customer", "invoices", ["customer_id"])
    op.create_index("idx_invoices_status", "invoices", ["org_id", "status"])
    op.create_index(
        "idx_invoices_number", "invoices", ["org_id", "invoice_number"]
    )
    op.create_index(
        "idx_invoices_rego", "invoices", ["org_id", "vehicle_rego"]
    )
    op.create_index(
        "idx_invoices_due_date",
        "invoices",
        ["org_id", "due_date"],
        postgresql_where=sa.text("status IN ('issued','partially_paid')"),
    )

    # -- line_items ----------------------------------------------------------
    op.create_table(
        "line_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_type", sa.String(10), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column(
            "catalogue_item_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("part_number", sa.String(100), nullable=True),
        sa.Column(
            "quantity",
            sa.Numeric(10, 3),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("hours", sa.Numeric(6, 2), nullable=True),
        sa.Column("hourly_rate", sa.Numeric(10, 2), nullable=True),
        sa.Column("discount_type", sa.String(10), nullable=True),
        sa.Column("discount_value", sa.Numeric(10, 2), nullable=True),
        sa.Column(
            "is_gst_exempt",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("warranty_note", sa.Text(), nullable=True),
        sa.Column("line_total", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "sort_order",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
            name="fk_line_items_invoice_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organisations.id"],
            name="fk_line_items_org_id",
        ),
        sa.CheckConstraint(
            "item_type IN ('service','part','labour')",
            name="ck_line_items_item_type",
        ),
        sa.CheckConstraint(
            "discount_type IN ('percentage','fixed')",
            name="ck_line_items_discount_type",
        ),
    )
    op.execute("ALTER TABLE line_items ENABLE ROW LEVEL SECURITY")
    op.create_index("idx_line_items_invoice", "line_items", ["invoice_id"])

    # -- credit_notes --------------------------------------------------------
    op.create_table(
        "credit_notes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("credit_note_number", sa.String(50), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "items",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("stripe_refund_id", sa.String(255), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organisations.id"],
            name="fk_credit_notes_org_id",
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
            name="fk_credit_notes_invoice_id",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_credit_notes_created_by",
        ),
    )
    op.execute("ALTER TABLE credit_notes ENABLE ROW LEVEL SECURITY")

    # -- payments ------------------------------------------------------------
    op.create_table(
        "payments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column(
            "stripe_payment_intent_id", sa.String(255), nullable=True
        ),
        sa.Column(
            "is_refund",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("refund_note", sa.Text(), nullable=True),
        sa.Column("recorded_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organisations.id"],
            name="fk_payments_org_id",
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
            name="fk_payments_invoice_id",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by"],
            ["users.id"],
            name="fk_payments_recorded_by",
        ),
        sa.CheckConstraint(
            "method IN ('cash','stripe')",
            name="ck_payments_method",
        ),
    )
    op.execute("ALTER TABLE payments ENABLE ROW LEVEL SECURITY")
    op.create_index("idx_payments_invoice", "payments", ["invoice_id"])


def downgrade() -> None:
    op.execute("ALTER TABLE payments DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_payments_invoice", table_name="payments")
    op.drop_table("payments")

    op.execute("ALTER TABLE credit_notes DISABLE ROW LEVEL SECURITY")
    op.drop_table("credit_notes")

    op.execute("ALTER TABLE line_items DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_line_items_invoice", table_name="line_items")
    op.drop_table("line_items")

    op.execute("ALTER TABLE invoices DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_invoices_due_date", table_name="invoices")
    op.drop_index("idx_invoices_rego", table_name="invoices")
    op.drop_index("idx_invoices_number", table_name="invoices")
    op.drop_index("idx_invoices_status", table_name="invoices")
    op.drop_index("idx_invoices_customer", table_name="invoices")
    op.drop_index("idx_invoices_org", table_name="invoices")
    op.drop_table("invoices")

    op.execute("ALTER TABLE credit_note_sequences DISABLE ROW LEVEL SECURITY")
    op.drop_table("credit_note_sequences")
    op.execute("ALTER TABLE quote_sequences DISABLE ROW LEVEL SECURITY")
    op.drop_table("quote_sequences")
    op.execute("ALTER TABLE invoice_sequences DISABLE ROW LEVEL SECURITY")
    op.drop_table("invoice_sequences")
