"""Create sms_verification_providers table.

Revision ID: 0064
Revises: 0063
Create Date: 2025-01-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sms_verification_providers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("provider_key", sa.String(50), nullable=False, unique=True),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("icon", sa.String(50), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("credentials_encrypted", sa.LargeBinary, nullable=True),
        sa.Column("credentials_set", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("config", JSONB, nullable=True, server_default=sa.text("'{}'::jsonb")),
        sa.Column("setup_guide", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    # Seed the three built-in providers
    op.execute("""
        INSERT INTO sms_verification_providers (provider_key, display_name, description, icon, priority, setup_guide)
        VALUES
            ('twilio_verify', 'Twilio Verify', 'SMS verification via Twilio Verify service', 'phone', 10,
             '1. Create a Twilio account at https://www.twilio.com.\n2. Go to Console → Verify → Services and create a new Verify Service.\n3. Copy the Service SID (starts with VA...).\n4. Find your Account SID and Auth Token on the Console dashboard.\n5. Enter all three values below.\n6. Twilio Verify handles OTP generation, delivery, and validation automatically.'),
            ('firebase_phone_auth', 'Firebase Phone Auth', 'Phone verification via Firebase Identity Toolkit with invisible reCAPTCHA (free 10K/month on Blaze plan)', 'firebase', 20,
             '1. Go to the Firebase Console and select your project (or create one).\n2. Enable Phone Authentication under Authentication → Sign-in method.\n3. Go to Project Settings → General and copy the Project ID, API Key, and App ID.\n4. For production, add your domain to the Authorized domains list.\n5. The Blaze plan includes 10K free phone verifications per month.\n6. Enter the credentials below.'),
            ('aws_sns', 'AWS SNS', 'SMS messaging via Amazon Simple Notification Service', 'cloud', 30,
             '1. Sign in to the AWS Console and navigate to SNS.\n2. Create an IAM user with SNS publish permissions (sns:Publish).\n3. Generate an Access Key ID and Secret Access Key for the IAM user.\n4. Choose your preferred AWS region (e.g. ap-southeast-2 for Sydney).\n5. Optionally set a Sender ID for branded SMS (not supported in all countries).\n6. Enter the credentials below.')
    """)


def downgrade() -> None:
    op.drop_table("sms_verification_providers")
