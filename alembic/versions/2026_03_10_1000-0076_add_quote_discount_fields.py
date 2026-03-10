"""Add discount, shipping, adjustment fields to quotes table.

Revision ID: 0076_add_quote_discount_fields
Revises: 0075_add_odometer_readings_table
"""

import sqlalchemy as sa

revision = "0079_add_quote_discount_fields"
down_revision = "0078_add_subject_to_quotes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op = sa.schema.CreateTable  # unused, just for IDE
    from alembic import op as _op

    _op.add_column("quotes", sa.Column("discount_type", sa.String(20), nullable=True, server_default="percentage"))
    _op.add_column("quotes", sa.Column("discount_value", sa.Numeric(12, 2), nullable=False, server_default="0"))
    _op.add_column("quotes", sa.Column("discount_amount", sa.Numeric(12, 2), nullable=False, server_default="0"))
    _op.add_column("quotes", sa.Column("shipping_charges", sa.Numeric(12, 2), nullable=False, server_default="0"))
    _op.add_column("quotes", sa.Column("adjustment", sa.Numeric(12, 2), nullable=False, server_default="0"))


def downgrade() -> None:
    from alembic import op as _op

    _op.drop_column("quotes", "adjustment")
    _op.drop_column("quotes", "shipping_charges")
    _op.drop_column("quotes", "discount_amount")
    _op.drop_column("quotes", "discount_value")
    _op.drop_column("quotes", "discount_type")
