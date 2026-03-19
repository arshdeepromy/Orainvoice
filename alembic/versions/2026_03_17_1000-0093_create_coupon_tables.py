"""Create coupons and organisation_coupons tables.

Revision ID: 0093
Revises: 0092
Create Date: 2026-03-17

Requirements: 1.1-1.10, 9.1-9.8
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "0093"
down_revision: str = "0092"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # -- coupons (no RLS — global admin table, same pattern as subscription_plans) --
    op.create_table(
        "coupons",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("code", sa.String(50), unique=True, nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("discount_type", sa.String(20), nullable=False),
        sa.Column("discount_value", sa.Numeric(10, 2), nullable=False),
        sa.Column("duration_months", sa.Integer, nullable=True),
        sa.Column("usage_limit", sa.Integer, nullable=True),
        sa.Column(
            "times_redeemed",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default="true",
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "discount_type IN ('percentage', 'fixed_amount', 'trial_extension')",
            name="ck_coupons_discount_type",
        ),
    )

    op.create_index("ix_coupons_code", "coupons", ["code"])

    # -- organisation_coupons (RLS scoped to org_id) -------------------------
    op.create_table(
        "organisation_coupons",
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
        sa.Column(
            "coupon_id",
            UUID(as_uuid=True),
            sa.ForeignKey("coupons.id"),
            nullable=False,
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "billing_months_used",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "is_expired",
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
        sa.UniqueConstraint(
            "org_id", "coupon_id", name="uq_organisation_coupons_org_coupon"
        ),
    )

    op.create_index(
        "ix_organisation_coupons_org_id", "organisation_coupons", ["org_id"]
    )
    op.create_index(
        "ix_organisation_coupons_coupon_id", "organisation_coupons", ["coupon_id"]
    )

    # -- Enable RLS on organisation_coupons only -----------------------------
    op.execute("ALTER TABLE organisation_coupons ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON organisation_coupons "
        "USING (org_id = current_setting('app.current_org_id')::uuid)"
    )


def downgrade() -> None:
    # -- Drop RLS policy and disable RLS -------------------------------------
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON organisation_coupons")
    op.execute("ALTER TABLE organisation_coupons DISABLE ROW LEVEL SECURITY")

    # -- Drop indexes and tables ---------------------------------------------
    op.drop_index("ix_organisation_coupons_coupon_id", table_name="organisation_coupons")
    op.drop_index("ix_organisation_coupons_org_id", table_name="organisation_coupons")
    op.drop_table("organisation_coupons")

    op.drop_index("ix_coupons_code", table_name="coupons")
    op.drop_table("coupons")
