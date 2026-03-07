"""Create global tables: subscription_plans, organisations, global_vehicles,
integration_configs, platform_settings.

Revision ID: 0001
Revises:
Create Date: 2025-01-15

Requirements: 40.1, 14.4, 48.1, 50.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # -- subscription_plans --------------------------------------------------
    op.create_table(
        "subscription_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("monthly_price_nzd", sa.Numeric(10, 2), nullable=False),
        sa.Column("user_seats", sa.Integer(), nullable=False),
        sa.Column("storage_quota_gb", sa.Integer(), nullable=False),
        sa.Column("carjam_lookups_included", sa.Integer(), nullable=False),
        sa.Column("enabled_modules", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("is_public", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_archived", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # -- organisations -------------------------------------------------------
    op.create_table(
        "organisations",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(255), nullable=True),
        sa.Column("stripe_connect_account_id", sa.String(255), nullable=True),
        sa.Column("storage_quota_gb", sa.Integer(), nullable=False),
        sa.Column("storage_used_bytes", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("carjam_lookups_this_month", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("carjam_lookups_reset_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settings", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["plan_id"], ["subscription_plans.id"], name="fk_organisations_plan_id"),
        sa.CheckConstraint(
            "status IN ('trial','active','grace_period','suspended','deleted')",
            name="ck_organisations_status",
        ),
    )

    # -- global_vehicles -----------------------------------------------------
    op.create_table(
        "global_vehicles",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("rego", sa.String(20), nullable=False),
        sa.Column("make", sa.String(100), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("colour", sa.String(50), nullable=True),
        sa.Column("body_type", sa.String(50), nullable=True),
        sa.Column("fuel_type", sa.String(50), nullable=True),
        sa.Column("engine_size", sa.String(50), nullable=True),
        sa.Column("num_seats", sa.Integer(), nullable=True),
        sa.Column("wof_expiry", sa.Date(), nullable=True),
        sa.Column("registration_expiry", sa.Date(), nullable=True),
        sa.Column("odometer_last_recorded", sa.Integer(), nullable=True),
        sa.Column("last_pulled_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rego", name="uq_global_vehicles_rego"),
    )
    op.create_index("idx_global_vehicles_rego", "global_vehicles", ["rego"])

    # -- integration_configs -------------------------------------------------
    op.create_table(
        "integration_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("config_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("is_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_integration_configs_name"),
        sa.CheckConstraint(
            "name IN ('carjam','stripe','smtp','twilio')",
            name="ck_integration_configs_name",
        ),
    )

    # -- platform_settings ---------------------------------------------------
    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("platform_settings")
    op.drop_table("integration_configs")
    op.drop_index("idx_global_vehicles_rego", table_name="global_vehicles")
    op.drop_table("global_vehicles")
    op.drop_table("organisations")
    op.drop_table("subscription_plans")
