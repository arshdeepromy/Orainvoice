"""Create email_providers table.

Revision ID: 0065
Revises: 0064
Create Date: 2025-01-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_providers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("provider_key", sa.String(50), nullable=False, unique=True),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("smtp_host", sa.String(255), nullable=True),
        sa.Column("smtp_port", sa.Integer, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("credentials_encrypted", sa.LargeBinary, nullable=True),
        sa.Column("credentials_set", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("config", JSONB, nullable=True, server_default=sa.text("'{}'::jsonb")),
        sa.Column("setup_guide", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.execute("""
        INSERT INTO email_providers
            (provider_key, display_name, description, smtp_host, smtp_port, setup_guide)
        VALUES
            ('brevo', 'Brevo (Sendinblue)', 'Transactional email via Brevo SMTP relay', 'smtp-relay.brevo.com', 587,
             '1. Sign up at https://www.brevo.com and verify your domain.\n2. Go to SMTP & API → SMTP and copy your SMTP key.\n3. Enter the SMTP key below as the API Key.\n4. Set From Email to a verified sender address.\n5. Click Save and send a test email to confirm delivery.'),
            ('sendgrid', 'SendGrid', 'Email delivery via Twilio SendGrid', 'smtp.sendgrid.net', 587,
             '1. Create a SendGrid account at https://sendgrid.com.\n2. Go to Settings → API Keys and create a key with Mail Send permission.\n3. Authenticate your sending domain under Settings → Sender Authentication.\n4. Paste the API key below.\n5. Use "apikey" as the SMTP username (this is automatic).\n6. Save and send a test email.'),
            ('mailgun', 'Mailgun', 'Email delivery via Mailgun SMTP', 'smtp.mailgun.org', 587,
             '1. Sign up at https://www.mailgun.com.\n2. Add and verify your sending domain under Sending → Domains.\n3. Go to Domain Settings → SMTP credentials and note your SMTP login and password.\n4. Enter them below as Username and Password.\n5. Save and send a test email.'),
            ('ses', 'Amazon SES', 'Email via Amazon Simple Email Service', 'email-smtp.us-east-1.amazonaws.com', 587,
             '1. Open the Amazon SES console and verify your sending domain or email.\n2. If in sandbox mode, also verify recipient addresses.\n3. Go to SMTP Settings and create SMTP credentials (generates an IAM user).\n4. Copy the SMTP username and password.\n5. Set the SMTP host to your region endpoint (e.g. email-smtp.ap-southeast-2.amazonaws.com).\n6. Save and send a test email.'),
            ('gmail', 'Gmail', 'Send via Gmail SMTP (limited to 500/day)', 'smtp.gmail.com', 587,
             '1. Go to your Google Account → Security.\n2. Enable 2-Step Verification if not already on.\n3. Go to App Passwords and generate a new app password for "Mail".\n4. Enter your Gmail address as Username and the app password as Password.\n5. Note: Gmail has a 500 email/day limit for regular accounts.\n6. Save and send a test email.'),
            ('outlook', 'Outlook/Office 365', 'Send via Microsoft 365 SMTP', 'smtp.office365.com', 587,
             '1. Sign in to the Microsoft 365 admin center.\n2. Ensure SMTP AUTH is enabled for the sending mailbox (Exchange admin → Mailboxes → Mail flow settings).\n3. Enter the full email address as Username and the account password.\n4. For MFA-enabled accounts, create an App Password in Security settings.\n5. Save and send a test email.'),
            ('custom_smtp', 'Custom SMTP', 'Configure your own SMTP server', NULL, 587,
             '1. Obtain the SMTP host, port, username, and password from your email provider.\n2. Common ports: 587 (STARTTLS), 465 (SSL), 25 (unencrypted, not recommended).\n3. Enter all fields below including the SMTP host.\n4. Ensure your server supports TLS for secure delivery.\n5. Save and send a test email to verify connectivity.')
    """)


def downgrade() -> None:
    op.drop_table("email_providers")
