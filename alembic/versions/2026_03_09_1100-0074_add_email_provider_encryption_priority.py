"""Add smtp_encryption and priority to email_providers.

Revision ID: 0074_add_email_provider_encryption_priority
Revises: 0073_add_exchange_rate_to_invoices
Create Date: 2026-03-09 11:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "0074_add_email_provider_encryption_priority"
down_revision = "0073_add_exchange_rate_to_invoices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add smtp_encryption column
    op.add_column(
        "email_providers",
        sa.Column("smtp_encryption", sa.String(10), nullable=True, server_default="tls"),
    )
    # Add priority column
    op.add_column(
        "email_providers",
        sa.Column("priority", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("email_providers", "priority")
    op.drop_column("email_providers", "smtp_encryption")
