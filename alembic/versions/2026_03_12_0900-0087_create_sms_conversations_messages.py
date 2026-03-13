"""Create sms_conversations and sms_messages tables with RLS, seed Connexus
provider, remove Twilio/AWS SNS providers, update integration_configs check
constraint.

Revision ID: 0087
Revises: 0086_add_vehicle_service_due_date
Create Date: 2026-03-12

Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7, 16.8,
              7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 3.5
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "0087"
down_revision: str = "0086_add_vehicle_service_due_date"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # -- sms_conversations ---------------------------------------------------
    op.create_table(
        "sms_conversations",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organisations.id"),
            nullable=False,
        ),
        sa.Column("phone_number", sa.String(20), nullable=False),
        sa.Column("contact_name", sa.String(255), nullable=True),
        sa.Column(
            "last_message_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("last_message_preview", sa.String(100), nullable=False),
        sa.Column(
            "unread_count",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "is_archived",
            sa.Boolean,
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("org_id", "phone_number", name="uq_sms_conversations_org_phone"),
    )

    # Indexes for sms_conversations
    op.create_index(
        "ix_sms_conversations_org_last_msg",
        "sms_conversations",
        ["org_id", sa.text("last_message_at DESC")],
    )

    # -- sms_messages --------------------------------------------------------
    op.create_table(
        "sms_messages",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sms_conversations.id"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organisations.id"),
            nullable=False,
        ),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("from_number", sa.String(20), nullable=False),
        sa.Column("to_number", sa.String(20), nullable=False),
        sa.Column("external_message_id", sa.String(100), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "parts_count",
            sa.Integer,
            nullable=False,
            server_default="1",
        ),
        sa.Column("cost_nzd", sa.Numeric(10, 4), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "direction IN ('inbound', 'outbound')",
            name="ck_sms_messages_direction",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'queued', 'delivered', 'undelivered', 'failed')",
            name="ck_sms_messages_status",
        ),
    )

    # Indexes for sms_messages
    op.create_index(
        "ix_sms_messages_conv_created",
        "sms_messages",
        ["conversation_id", "created_at"],
    )
    op.execute(
        "CREATE INDEX ix_sms_messages_external_id ON sms_messages (external_message_id) "
        "WHERE external_message_id IS NOT NULL"
    )

    # -- Enable RLS on both tables -------------------------------------------
    op.execute("ALTER TABLE sms_conversations ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON sms_conversations "
        "USING (org_id = current_setting('app.current_org_id')::uuid)"
    )

    op.execute("ALTER TABLE sms_messages ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON sms_messages "
        "USING (org_id = current_setting('app.current_org_id')::uuid)"
    )

    # -- Seed Connexus provider and remove Twilio/AWS SNS --------------------
    op.execute("""
        INSERT INTO sms_verification_providers
            (provider_key, display_name, description, icon, is_active, priority, setup_guide)
        VALUES
            ('connexus', 'WebSMS Connexus', 'SMS messaging via WebSMS Connexus API', 'message-square', false, 10,
             '1. Create a WebSMS Connexus account at https://websms.co.nz.\n2. Navigate to API Settings and generate a Client ID and Client Secret.\n3. Configure your Sender ID (the number or name that appears as the SMS sender).\n4. Enter the credentials below.\n5. Use the Configure Webhooks button to register incoming SMS and delivery status callback URLs.')
    """)

    op.execute(
        "DELETE FROM sms_verification_providers WHERE provider_key IN ('twilio_verify', 'aws_sns')"
    )

    # -- Update integration_configs check constraint -------------------------
    op.drop_constraint("ck_integration_configs_name", "integration_configs", type_="check")
    op.create_check_constraint(
        "ck_integration_configs_name",
        "integration_configs",
        "name IN ('carjam','stripe','smtp')",
    )


def downgrade() -> None:
    # -- Restore integration_configs check constraint ------------------------
    op.drop_constraint("ck_integration_configs_name", "integration_configs", type_="check")
    op.create_check_constraint(
        "ck_integration_configs_name",
        "integration_configs",
        "name IN ('carjam','stripe','smtp','twilio')",
    )

    # -- Restore Twilio/AWS SNS providers, remove Connexus -------------------
    op.execute("""
        INSERT INTO sms_verification_providers
            (provider_key, display_name, description, icon, priority, setup_guide)
        VALUES
            ('twilio_verify', 'Twilio Verify', 'SMS verification via Twilio Verify service', 'phone', 10,
             '1. Create a Twilio account at https://www.twilio.com.\n2. Go to Console → Verify → Services and create a new Verify Service.\n3. Copy the Service SID (starts with VA...).\n4. Find your Account SID and Auth Token on the Console dashboard.\n5. Enter all three values below.\n6. Twilio Verify handles OTP generation, delivery, and validation automatically.'),
            ('aws_sns', 'AWS SNS', 'SMS messaging via Amazon Simple Notification Service', 'cloud', 30,
             '1. Sign in to the AWS Console and navigate to SNS.\n2. Create an IAM user with SNS publish permissions (sns:Publish).\n3. Generate an Access Key ID and Secret Access Key for the IAM user.\n4. Choose your preferred AWS region (e.g. ap-southeast-2 for Sydney).\n5. Optionally set a Sender ID for branded SMS (not supported in all countries).\n6. Enter the credentials below.')
    """)

    op.execute("DELETE FROM sms_verification_providers WHERE provider_key = 'connexus'")

    # -- Drop RLS policies ---------------------------------------------------
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON sms_messages")
    op.execute("ALTER TABLE sms_messages DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON sms_conversations")
    op.execute("ALTER TABLE sms_conversations DISABLE ROW LEVEL SECURITY")

    # -- Drop indexes and tables ---------------------------------------------
    op.execute("DROP INDEX IF EXISTS ix_sms_messages_external_id")
    op.drop_index("ix_sms_messages_conv_created", table_name="sms_messages")
    op.drop_table("sms_messages")

    op.drop_index("ix_sms_conversations_org_last_msg", table_name="sms_conversations")
    op.drop_table("sms_conversations")
