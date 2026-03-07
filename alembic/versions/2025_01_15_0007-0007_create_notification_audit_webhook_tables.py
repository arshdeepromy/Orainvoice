"""Create notification_templates, notification_log, overdue_reminder_rules,
notification_preferences, audit_log, error_log, webhooks, webhook_deliveries,
accounting_integrations, accounting_sync_log, discount_rules, and
stock_movements tables.

Revision ID: 0007
Revises: 0006
Create Date: 2025-01-15

Requirements: 34.3, 35.1, 38.1, 49.2, 51.3, 70.1, 68.1, 67.1, 62.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str = "0006"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # -- notification_templates ----------------------------------------------
    op.create_table(
        "notification_templates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_type", sa.String(50), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("subject", sa.String(255), nullable=True),
        sa.Column(
            "body_blocks",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organisations.id"],
            name="fk_notification_templates_org_id",
        ),
        sa.CheckConstraint(
            "channel IN ('email','sms')",
            name="ck_notification_templates_channel",
        ),
        sa.UniqueConstraint(
            "org_id",
            "template_type",
            "channel",
            name="uq_notification_templates_org_type_channel",
        ),
    )
    op.execute("ALTER TABLE notification_templates ENABLE ROW LEVEL SECURITY")

    # -- notification_log ----------------------------------------------------
    op.create_table(
        "notification_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("recipient", sa.String(255), nullable=False),
        sa.Column("template_type", sa.String(50), nullable=False),
        sa.Column("subject", sa.String(255), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="queued",
        ),
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organisations.id"],
            name="fk_notification_log_org_id",
        ),
        sa.CheckConstraint(
            "channel IN ('email','sms')",
            name="ck_notification_log_channel",
        ),
        sa.CheckConstraint(
            "status IN ('queued','sent','delivered','bounced','opened','failed')",
            name="ck_notification_log_status",
        ),
    )
    op.execute("ALTER TABLE notification_log ENABLE ROW LEVEL SECURITY")
    op.create_index(
        "idx_notification_log_org",
        "notification_log",
        ["org_id", sa.text("created_at DESC")],
    )

    # -- overdue_reminder_rules ----------------------------------------------
    op.create_table(
        "overdue_reminder_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("days_after_due", sa.Integer(), nullable=False),
        sa.Column(
            "send_email",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "send_sms",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organisations.id"],
            name="fk_overdue_reminder_rules_org_id",
        ),
        sa.UniqueConstraint(
            "org_id",
            "days_after_due",
            name="uq_overdue_reminder_rules_org_days",
        ),
    )
    op.execute("ALTER TABLE overdue_reminder_rules ENABLE ROW LEVEL SECURITY")

    # -- notification_preferences --------------------------------------------
    op.create_table(
        "notification_preferences",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notification_type", sa.String(50), nullable=False),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "channel",
            sa.String(20),
            nullable=False,
            server_default="email",
        ),
        sa.Column(
            "config",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organisations.id"],
            name="fk_notification_preferences_org_id",
        ),
        sa.CheckConstraint(
            "channel IN ('email','sms','both')",
            name="ck_notification_preferences_channel",
        ),
        sa.UniqueConstraint(
            "org_id",
            "notification_type",
            name="uq_notification_preferences_org_type",
        ),
    )
    op.execute(
        "ALTER TABLE notification_preferences ENABLE ROW LEVEL SECURITY"
    )

    # -- audit_log (append-only, NO RLS) ------------------------------------
    # NOTE: REVOKE UPDATE, DELETE on audit_log will be applied in migration
    # 0008 (RLS policies migration) to keep DDL concerns separated.
    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("before_value", postgresql.JSONB, nullable=True),
        sa.Column("after_value", postgresql.JSONB, nullable=True),
        sa.Column("ip_address", postgresql.INET, nullable=True),
        sa.Column("device_info", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_audit_log_org",
        "audit_log",
        ["org_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_audit_log_entity",
        "audit_log",
        ["entity_type", "entity_id"],
    )

    # -- error_log (no RLS, Global Admin only) -------------------------------
    op.create_table(
        "error_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("module", sa.String(100), nullable=False),
        sa.Column("function_name", sa.String(100), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("stack_trace", sa.Text(), nullable=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("http_method", sa.String(10), nullable=True),
        sa.Column("http_endpoint", sa.String(500), nullable=True),
        sa.Column("request_body_sanitised", postgresql.JSONB, nullable=True),
        sa.Column("response_body_sanitised", postgresql.JSONB, nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="open",
        ),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "severity IN ('info','warning','error','critical')",
            name="ck_error_log_severity",
        ),
        sa.CheckConstraint(
            "category IN ('payment','integration','storage','authentication','data','background_job','application')",
            name="ck_error_log_category",
        ),
        sa.CheckConstraint(
            "status IN ('open','investigating','resolved')",
            name="ck_error_log_status",
        ),
    )
    op.create_index(
        "idx_error_log_severity",
        "error_log",
        ["severity", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_error_log_category",
        "error_log",
        ["category", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_error_log_org",
        "error_log",
        ["org_id", sa.text("created_at DESC")],
    )

    # -- webhooks ------------------------------------------------------------
    op.create_table(
        "webhooks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("secret_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organisations.id"],
            name="fk_webhooks_org_id",
        ),
    )
    op.execute("ALTER TABLE webhooks ENABLE ROW LEVEL SECURITY")

    # -- webhook_deliveries --------------------------------------------------
    op.create_table(
        "webhook_deliveries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("webhook_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["webhook_id"],
            ["webhooks.id"],
            name="fk_webhook_deliveries_webhook_id",
        ),
        sa.CheckConstraint(
            "status IN ('pending','delivered','failed')",
            name="ck_webhook_deliveries_status",
        ),
    )

    # -- accounting_integrations ---------------------------------------------
    op.create_table(
        "accounting_integrations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(10), nullable=False),
        sa.Column("access_token_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("refresh_token_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column(
            "token_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "is_connected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "last_sync_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organisations.id"],
            name="fk_accounting_integrations_org_id",
        ),
        sa.CheckConstraint(
            "provider IN ('xero','myob')",
            name="ck_accounting_integrations_provider",
        ),
        sa.UniqueConstraint(
            "org_id",
            "provider",
            name="uq_accounting_integrations_org_provider",
        ),
    )
    op.execute(
        "ALTER TABLE accounting_integrations ENABLE ROW LEVEL SECURITY"
    )

    # -- accounting_sync_log -------------------------------------------------
    op.create_table(
        "accounting_sync_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(10), nullable=False),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organisations.id"],
            name="fk_accounting_sync_log_org_id",
        ),
        sa.CheckConstraint(
            "status IN ('synced','failed','pending')",
            name="ck_accounting_sync_log_status",
        ),
    )
    op.execute("ALTER TABLE accounting_sync_log ENABLE ROW LEVEL SECURITY")

    # -- discount_rules ------------------------------------------------------
    op.create_table(
        "discount_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("rule_type", sa.String(20), nullable=False),
        sa.Column("threshold_value", sa.Numeric(10, 2), nullable=True),
        sa.Column("discount_type", sa.String(10), nullable=False),
        sa.Column("discount_value", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organisations.id"],
            name="fk_discount_rules_org_id",
        ),
        sa.CheckConstraint(
            "rule_type IN ('visit_count','spend_threshold','customer_tag')",
            name="ck_discount_rules_rule_type",
        ),
        sa.CheckConstraint(
            "discount_type IN ('percentage','fixed')",
            name="ck_discount_rules_discount_type",
        ),
    )
    op.execute("ALTER TABLE discount_rules ENABLE ROW LEVEL SECURITY")

    # -- stock_movements -----------------------------------------------------
    op.create_table(
        "stock_movements",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("part_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity_change", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(50), nullable=False),
        sa.Column(
            "reference_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("recorded_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organisations.id"],
            name="fk_stock_movements_org_id",
        ),
        sa.ForeignKeyConstraint(
            ["part_id"],
            ["parts_catalogue.id"],
            name="fk_stock_movements_part_id",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by"],
            ["users.id"],
            name="fk_stock_movements_recorded_by",
        ),
        sa.CheckConstraint(
            "reason IN ('invoice','manual_adjustment','restock','return')",
            name="ck_stock_movements_reason",
        ),
    )
    op.execute("ALTER TABLE stock_movements ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE stock_movements DISABLE ROW LEVEL SECURITY")
    op.drop_table("stock_movements")

    op.execute("ALTER TABLE discount_rules DISABLE ROW LEVEL SECURITY")
    op.drop_table("discount_rules")

    op.execute("ALTER TABLE accounting_sync_log DISABLE ROW LEVEL SECURITY")
    op.drop_table("accounting_sync_log")

    op.execute(
        "ALTER TABLE accounting_integrations DISABLE ROW LEVEL SECURITY"
    )
    op.drop_table("accounting_integrations")

    op.drop_table("webhook_deliveries")

    op.execute("ALTER TABLE webhooks DISABLE ROW LEVEL SECURITY")
    op.drop_table("webhooks")

    op.drop_index("idx_error_log_org", table_name="error_log")
    op.drop_index("idx_error_log_category", table_name="error_log")
    op.drop_index("idx_error_log_severity", table_name="error_log")
    op.drop_table("error_log")

    op.drop_index("idx_audit_log_entity", table_name="audit_log")
    op.drop_index("idx_audit_log_org", table_name="audit_log")
    op.drop_table("audit_log")

    op.execute(
        "ALTER TABLE notification_preferences DISABLE ROW LEVEL SECURITY"
    )
    op.drop_table("notification_preferences")

    op.execute(
        "ALTER TABLE overdue_reminder_rules DISABLE ROW LEVEL SECURITY"
    )
    op.drop_table("overdue_reminder_rules")

    op.execute("ALTER TABLE notification_log DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_notification_log_org", table_name="notification_log")
    op.drop_table("notification_log")

    op.execute(
        "ALTER TABLE notification_templates DISABLE ROW LEVEL SECURITY"
    )
    op.drop_table("notification_templates")
