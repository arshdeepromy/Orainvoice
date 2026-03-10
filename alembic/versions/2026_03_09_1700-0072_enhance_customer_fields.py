"""Enhance customer fields for comprehensive customer management.

Adds fields matching Zoho-style customer form:
- Customer type (business/individual)
- Salutation, company name, display name
- Separate work/mobile phone fields
- Currency and language preferences
- Payment terms and tax settings
- Portal access and bank payment options
- Structured billing/shipping addresses
- Contact persons and custom fields

Revision ID: 0072_enhance_customer_fields
Revises: 202603091600
Create Date: 2026-03-09 17:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "0072_enhance_customer_fields"
down_revision = "202603091600"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns to customers table
    op.add_column(
        "customers",
        sa.Column(
            "customer_type",
            sa.String(20),
            nullable=False,
            server_default="individual",
            comment="business or individual",
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "salutation",
            sa.String(20),
            nullable=True,
            comment="Mr, Mrs, Ms, Dr, etc.",
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "company_name",
            sa.String(255),
            nullable=True,
            comment="Company name for business customers",
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "display_name",
            sa.String(255),
            nullable=True,
            comment="Display name for invoices and communications",
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "currency",
            sa.String(3),
            nullable=False,
            server_default="NZD",
            comment="ISO 4217 currency code",
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "work_phone",
            sa.String(50),
            nullable=True,
            comment="Work phone number",
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "mobile_phone",
            sa.String(50),
            nullable=True,
            comment="Mobile phone number",
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "language",
            sa.String(10),
            nullable=False,
            server_default="en",
            comment="Customer preferred language code",
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "tax_rate_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Default tax rate for this customer",
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "company_id",
            sa.String(100),
            nullable=True,
            comment="Business registration / company ID number",
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "payment_terms",
            sa.String(50),
            nullable=False,
            server_default="due_on_receipt",
            comment="Payment terms: due_on_receipt, net_15, net_30, net_60",
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "enable_bank_payment",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="Allow customer to pay via bank account",
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "enable_portal",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="Allow customer portal access",
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "billing_address",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            server_default=sa.text("'{}'::jsonb"),
            comment="Structured billing address: street, city, state, postal_code, country",
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "shipping_address",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            server_default=sa.text("'{}'::jsonb"),
            comment="Structured shipping address",
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "contact_persons",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment="Additional contact persons array",
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "custom_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment="Custom fields key-value pairs",
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "remarks",
            sa.Text(),
            nullable=True,
            comment="Additional remarks/comments",
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "documents",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment="Attached document references",
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Customer owner/assigned user",
        ),
    )

    # Migrate existing phone data to mobile_phone
    op.execute("""
        UPDATE customers 
        SET mobile_phone = phone 
        WHERE phone IS NOT NULL AND mobile_phone IS NULL
    """)

    # Create index on customer_type for filtering
    op.create_index(
        "idx_customers_type",
        "customers",
        ["org_id", "customer_type"],
    )

    # Create index on company_name for business customer search
    op.create_index(
        "idx_customers_company",
        "customers",
        ["org_id", "company_name"],
        postgresql_where=sa.text("company_name IS NOT NULL"),
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index("idx_customers_company", table_name="customers")
    op.drop_index("idx_customers_type", table_name="customers")

    # Drop columns
    op.drop_column("customers", "owner_user_id")
    op.drop_column("customers", "documents")
    op.drop_column("customers", "remarks")
    op.drop_column("customers", "custom_fields")
    op.drop_column("customers", "contact_persons")
    op.drop_column("customers", "shipping_address")
    op.drop_column("customers", "billing_address")
    op.drop_column("customers", "enable_portal")
    op.drop_column("customers", "enable_bank_payment")
    op.drop_column("customers", "payment_terms")
    op.drop_column("customers", "company_id")
    op.drop_column("customers", "tax_rate_id")
    op.drop_column("customers", "language")
    op.drop_column("customers", "mobile_phone")
    op.drop_column("customers", "work_phone")
    op.drop_column("customers", "currency")
    op.drop_column("customers", "display_name")
    op.drop_column("customers", "company_name")
    op.drop_column("customers", "salutation")
    op.drop_column("customers", "customer_type")
