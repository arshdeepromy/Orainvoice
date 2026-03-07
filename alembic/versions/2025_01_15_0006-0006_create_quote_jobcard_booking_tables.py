"""Create quotes, quote_line_items, job_cards, job_card_items, time_entries,
recurring_schedules, and bookings tables — with RLS enabled.

Revision ID: 0006
Revises: 0005
Create Date: 2025-01-15

Requirements: 58.1, 59.1, 60.1, 64.1, 65.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str = "0005"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # -- quotes --------------------------------------------------------------
    op.create_table(
        "quotes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quote_number", sa.String(50), nullable=False),
        sa.Column("vehicle_rego", sa.String(20), nullable=True),
        sa.Column("vehicle_make", sa.String(100), nullable=True),
        sa.Column("vehicle_model", sa.String(100), nullable=True),
        sa.Column("vehicle_year", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column(
            "subtotal",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
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
        sa.Column("notes", sa.Text(), nullable=True),
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
            name="fk_quotes_org_id",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name="fk_quotes_customer_id",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_quotes_created_by",
        ),
        sa.CheckConstraint(
            "status IN ('draft','sent','accepted','declined','expired')",
            name="ck_quotes_status",
        ),
    )
    op.execute("ALTER TABLE quotes ENABLE ROW LEVEL SECURITY")

    # -- quote_line_items ----------------------------------------------------
    op.create_table(
        "quote_line_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("quote_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_type", sa.String(10), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column(
            "quantity",
            sa.Numeric(10, 3),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("hours", sa.Numeric(6, 2), nullable=True),
        sa.Column("hourly_rate", sa.Numeric(10, 2), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["quote_id"],
            ["quotes.id"],
            name="fk_quote_line_items_quote_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organisations.id"],
            name="fk_quote_line_items_org_id",
        ),
        sa.CheckConstraint(
            "item_type IN ('service','part','labour')",
            name="ck_quote_line_items_item_type",
        ),
    )
    op.execute("ALTER TABLE quote_line_items ENABLE ROW LEVEL SECURITY")
    op.create_index(
        "idx_quote_line_items_quote", "quote_line_items", ["quote_id"]
    )

    # -- job_cards -----------------------------------------------------------
    op.create_table(
        "job_cards",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vehicle_rego", sa.String(20), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="open",
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "assigned_to", postgresql.UUID(as_uuid=True), nullable=True
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
            name="fk_job_cards_org_id",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name="fk_job_cards_customer_id",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to"],
            ["users.id"],
            name="fk_job_cards_assigned_to",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_job_cards_created_by",
        ),
        sa.CheckConstraint(
            "status IN ('open','in_progress','completed','invoiced')",
            name="ck_job_cards_status",
        ),
    )
    op.execute("ALTER TABLE job_cards ENABLE ROW LEVEL SECURITY")

    # -- job_card_items ------------------------------------------------------
    op.create_table(
        "job_card_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("job_card_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_type", sa.String(10), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column(
            "quantity",
            sa.Numeric(10, 3),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "is_completed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "sort_order",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["job_card_id"],
            ["job_cards.id"],
            name="fk_job_card_items_job_card_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organisations.id"],
            name="fk_job_card_items_org_id",
        ),
        sa.CheckConstraint(
            "item_type IN ('service','part','labour')",
            name="ck_job_card_items_item_type",
        ),
    )
    op.execute("ALTER TABLE job_card_items ENABLE ROW LEVEL SECURITY")
    op.create_index(
        "idx_job_card_items_job_card", "job_card_items", ["job_card_id"]
    )

    # -- time_entries --------------------------------------------------------
    op.create_table(
        "time_entries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "job_card_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "invoice_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "stopped_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("hourly_rate", sa.Numeric(10, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
            name="fk_time_entries_org_id",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_time_entries_user_id",
        ),
        sa.ForeignKeyConstraint(
            ["job_card_id"],
            ["job_cards.id"],
            name="fk_time_entries_job_card_id",
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
            name="fk_time_entries_invoice_id",
        ),
    )
    op.execute("ALTER TABLE time_entries ENABLE ROW LEVEL SECURITY")
    op.create_index(
        "idx_time_entries_job_card", "time_entries", ["job_card_id"]
    )

    # -- recurring_schedules -------------------------------------------------
    op.create_table(
        "recurring_schedules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("frequency", sa.String(20), nullable=False),
        sa.Column(
            "line_items",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "auto_issue",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "next_due_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "last_generated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
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
            name="fk_recurring_schedules_org_id",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name="fk_recurring_schedules_customer_id",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_recurring_schedules_created_by",
        ),
        sa.CheckConstraint(
            "frequency IN ('weekly','fortnightly','monthly','quarterly','annually')",
            name="ck_recurring_schedules_frequency",
        ),
    )
    op.execute("ALTER TABLE recurring_schedules ENABLE ROW LEVEL SECURITY")

    # -- bookings ------------------------------------------------------------
    op.create_table(
        "bookings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "customer_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("vehicle_rego", sa.String(20), nullable=True),
        sa.Column(
            "branch_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("service_type", sa.String(255), nullable=True),
        sa.Column(
            "scheduled_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "duration_minutes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("60"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="scheduled",
        ),
        sa.Column(
            "reminder_sent",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "assigned_to", postgresql.UUID(as_uuid=True), nullable=True
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
            name="fk_bookings_org_id",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name="fk_bookings_customer_id",
        ),
        sa.ForeignKeyConstraint(
            ["branch_id"],
            ["branches.id"],
            name="fk_bookings_branch_id",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to"],
            ["users.id"],
            name="fk_bookings_assigned_to",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_bookings_created_by",
        ),
        sa.CheckConstraint(
            "status IN ('scheduled','confirmed','completed','cancelled')",
            name="ck_bookings_status",
        ),
    )
    op.execute("ALTER TABLE bookings ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE bookings DISABLE ROW LEVEL SECURITY")
    op.drop_table("bookings")

    op.execute("ALTER TABLE recurring_schedules DISABLE ROW LEVEL SECURITY")
    op.drop_table("recurring_schedules")

    op.execute("ALTER TABLE time_entries DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_time_entries_job_card", table_name="time_entries")
    op.drop_table("time_entries")

    op.execute("ALTER TABLE job_card_items DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_job_card_items_job_card", table_name="job_card_items")
    op.drop_table("job_card_items")

    op.execute("ALTER TABLE job_cards DISABLE ROW LEVEL SECURITY")
    op.drop_table("job_cards")

    op.execute("ALTER TABLE quote_line_items DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_quote_line_items_quote", table_name="quote_line_items")
    op.drop_table("quote_line_items")

    op.execute("ALTER TABLE quotes DISABLE ROW LEVEL SECURITY")
    op.drop_table("quotes")
