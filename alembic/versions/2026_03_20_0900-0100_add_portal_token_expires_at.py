"""Add portal_token_expires_at column to customers table.

Adds a timestamp column for portal token expiry with a default of
now() + 90 days. Existing rows with a portal_token get the default
applied; rows without a token remain NULL.

REM-15: Portal Token TTL and Rotation.

Revision ID: 0100
Revises: 0099
Create Date: 2026-03-20 09:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0100"
down_revision = "0099"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column(
            "portal_token_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text("now() + interval '90 days'"),
        ),
    )
    # Back-fill expiry for existing customers that already have a portal token.
    op.execute(
        "UPDATE customers SET portal_token_expires_at = now() + interval '90 days' "
        "WHERE portal_token IS NOT NULL AND portal_token_expires_at IS NULL"
    )


def downgrade() -> None:
    op.drop_column("customers", "portal_token_expires_at")
