"""Create storage_packages and org_storage_addons tables.

Revision ID: 0094
Revises: 0093
Create Date: 2026-03-17

Requirements: 1.1-1.5
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "0094"
down_revision: str = "0093"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # -- storage_packages (no RLS — global admin table, same pattern as subscription_plans) --
    op.create_table(
        "storage_packages",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("storage_gb", sa.Integer, nullable=False),
        sa.Column("price_nzd_per_month", sa.Numeric(10, 2), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default="true",
        ),
        sa.Column(
            "sort_order",
            sa.Integer,
            nullable=False,
            server_default="0",
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
        sa.CheckConstraint("storage_gb > 0", name="ck_storage_packages_storage_gb"),
    )

    # -- org_storage_addons (RLS scoped to org_id) ---------------------------
    op.create_table(
        "org_storage_addons",
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
            "storage_package_id",
            UUID(as_uuid=True),
            sa.ForeignKey("storage_packages.id"),
            nullable=True,
        ),
        sa.Column("quantity_gb", sa.Integer, nullable=False),
        sa.Column("price_nzd_per_month", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "is_custom",
            sa.Boolean,
            nullable=False,
            server_default="false",
        ),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("org_id", name="uq_org_storage_addons_org_id"),
        sa.CheckConstraint("quantity_gb > 0", name="ck_org_storage_addons_quantity_gb"),
    )

    op.create_index(
        "ix_org_storage_addons_org_id", "org_storage_addons", ["org_id"]
    )
    op.create_index(
        "ix_org_storage_addons_storage_package_id",
        "org_storage_addons",
        ["storage_package_id"],
    )

    # -- Enable RLS on org_storage_addons only -------------------------------
    op.execute("ALTER TABLE org_storage_addons ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON org_storage_addons "
        "USING (org_id = current_setting('app.current_org_id')::uuid)"
    )


def downgrade() -> None:
    # -- Drop RLS policy and disable RLS -------------------------------------
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON org_storage_addons")
    op.execute("ALTER TABLE org_storage_addons DISABLE ROW LEVEL SECURITY")

    # -- Drop indexes and tables ---------------------------------------------
    op.drop_index("ix_org_storage_addons_storage_package_id", table_name="org_storage_addons")
    op.drop_index("ix_org_storage_addons_org_id", table_name="org_storage_addons")
    op.drop_table("org_storage_addons")

    op.drop_table("storage_packages")
