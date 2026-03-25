"""Add mileage tables and enhance expenses with reference, notes, customer, billable, tax_inclusive.

Revision ID: 0108
Revises: 0107
Create Date: 2026-03-26
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0108"
down_revision: str = "0107"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns to expenses
    op.add_column("expenses", sa.Column("reference_number", sa.String(100), nullable=True))
    op.add_column("expenses", sa.Column("notes", sa.Text(), nullable=True))
    op.add_column("expenses", sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("expenses", sa.Column("is_billable", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("expenses", sa.Column("tax_inclusive", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("expenses", sa.Column("expense_type", sa.String(20), server_default=sa.text("'expense'"), nullable=False))

    # Mileage preferences (singleton per org)
    op.create_table(
        "mileage_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("default_unit", sa.String(10), server_default=sa.text("'km'"), nullable=False),
        sa.Column("default_account", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id"),
    )

    # Mileage rates (per org, date-based)
    op.create_table(
        "mileage_rates",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("rate_per_unit", sa.Numeric(10, 4), nullable=False),
        sa.Column("currency", sa.String(3), server_default=sa.text("'NZD'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("mileage_rates")
    op.drop_table("mileage_preferences")
    op.drop_column("expenses", "expense_type")
    op.drop_column("expenses", "tax_inclusive")
    op.drop_column("expenses", "is_billable")
    op.drop_column("expenses", "customer_id")
    op.drop_column("expenses", "notes")
    op.drop_column("expenses", "reference_number")
