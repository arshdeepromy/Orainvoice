"""Add SMS billing fields to subscription_plans and organisations, create sms_package_purchases table.

Adds per-SMS cost, included quota, and package tier pricing to subscription plans.
Adds monthly SMS usage counter and reset timestamp to organisations.
Creates sms_package_purchases table for bulk SMS credit tracking.

Revision ID: 0071
Revises: 0070
Create Date: 2025-01-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- subscription_plans: SMS pricing fields ---
    op.add_column(
        "subscription_plans",
        sa.Column("per_sms_cost_nzd", sa.Numeric(10, 4), nullable=False, server_default="0"),
    )
    op.add_column(
        "subscription_plans",
        sa.Column("sms_included_quota", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "subscription_plans",
        sa.Column(
            "sms_package_pricing",
            JSONB,
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    # --- organisations: SMS usage tracking fields ---
    op.add_column(
        "organisations",
        sa.Column("sms_sent_this_month", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "organisations",
        sa.Column("sms_sent_reset_at", sa.DateTime(timezone=True), nullable=True),
    )

    # --- sms_package_purchases table ---
    op.create_table(
        "sms_package_purchases",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("tier_name", sa.String(100), nullable=False),
        sa.Column("sms_quantity", sa.Integer(), nullable=False),
        sa.Column("price_nzd", sa.Numeric(10, 2), nullable=False),
        sa.Column("credits_remaining", sa.Integer(), nullable=False),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("sms_package_purchases")
    op.drop_column("organisations", "sms_sent_reset_at")
    op.drop_column("organisations", "sms_sent_this_month")
    op.drop_column("subscription_plans", "sms_package_pricing")
    op.drop_column("subscription_plans", "sms_included_quota")
    op.drop_column("subscription_plans", "per_sms_cost_nzd")
