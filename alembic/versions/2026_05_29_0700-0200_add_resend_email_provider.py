"""Add Resend email provider to email_providers table.

Resend is a REST-based email API (no SMTP) that was missing from the
original seed in migration 0065. This ensures all environments get the
Resend provider row automatically on deployment.

Revision ID: 0200
Revises: 0199
Create Date: 2026-05-29
"""

from __future__ import annotations

from alembic import op

revision: str = "0200"
down_revision: str = "0199"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO email_providers
            (provider_key, display_name, description, smtp_host, smtp_port, setup_guide)
        VALUES
            ('resend', 'Resend', 'Email delivery via Resend REST API', 'smtp.resend.com', 465,
             '1. Sign up at https://resend.com and verify your sending domain.\n2. Go to API Keys and create a new key.\n3. Enter the API key below.\n4. Set From Email to a verified sender address (e.g. noreply@yourdomain.com).\n5. Save and send a test email to confirm delivery.')
        ON CONFLICT (provider_key) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM email_providers WHERE provider_key = 'resend'")
