"""Create platform_branding table and seed with OraInvoice defaults.

Revision ID: 0022
Revises: 0021
Create Date: 2025-01-15

Requirements: 1.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: str = "0021"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # -- Create platform_branding table -------------------------------------
    op.create_table(
        "platform_branding",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("platform_name", sa.String(100), server_default=sa.text("'OraInvoice'"), nullable=False),
        sa.Column("logo_url", sa.String(500), nullable=True),
        sa.Column("primary_colour", sa.String(7), server_default=sa.text("'#2563EB'"), nullable=False),
        sa.Column("secondary_colour", sa.String(7), server_default=sa.text("'#1E40AF'"), nullable=False),
        sa.Column("website_url", sa.String(500), nullable=True),
        sa.Column("signup_url", sa.String(500), nullable=True),
        sa.Column("support_email", sa.String(255), nullable=True),
        sa.Column("terms_url", sa.String(500), nullable=True),
        sa.Column("auto_detect_domain", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # -- Seed default branding row ------------------------------------------
    platform_branding = sa.table(
        "platform_branding",
        sa.column("platform_name", sa.String),
        sa.column("logo_url", sa.String),
        sa.column("primary_colour", sa.String),
        sa.column("secondary_colour", sa.String),
        sa.column("website_url", sa.String),
        sa.column("signup_url", sa.String),
        sa.column("support_email", sa.String),
        sa.column("terms_url", sa.String),
        sa.column("auto_detect_domain", sa.Boolean),
    )
    op.bulk_insert(platform_branding, [
        {
            "platform_name": "OraInvoice",
            "logo_url": "/assets/logo/orainvoice-logo.svg",
            "primary_colour": "#2563EB",
            "secondary_colour": "#1E40AF",
            "website_url": "https://orainvoice.com",
            "signup_url": "https://orainvoice.com/signup",
            "support_email": "support@orainvoice.com",
            "terms_url": "https://orainvoice.com/terms",
            "auto_detect_domain": True,
        }
    ])


def downgrade() -> None:
    op.drop_table("platform_branding")
