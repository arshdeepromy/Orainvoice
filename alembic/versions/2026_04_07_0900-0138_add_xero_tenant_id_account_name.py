"""Add xero_tenant_id and account_name to accounting_integrations.

Stores the Xero tenant ID and connected account name at OAuth connect
time so we don't need a redundant API call on every sync.

Revision ID: 0138
Revises: 0137
Create Date: 2026-04-07
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "0138"
down_revision: str = "0137"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "accounting_integrations",
        sa.Column("xero_tenant_id", sa.String(255), nullable=True,
                  comment="Xero tenant ID stored at connect time"),
    )
    op.add_column(
        "accounting_integrations",
        sa.Column("account_name", sa.String(255), nullable=True,
                  comment="Connected account name from provider"),
    )


def downgrade() -> None:
    op.drop_column("accounting_integrations", "account_name")
    op.drop_column("accounting_integrations", "xero_tenant_id")
