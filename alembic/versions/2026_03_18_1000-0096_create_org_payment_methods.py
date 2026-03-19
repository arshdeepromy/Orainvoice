"""Create org_payment_methods table.

Revision ID: 0096
Revises: 0095
Create Date: 2026-03-18

Requirements: 5.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "0096"
down_revision: str = "0095"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "org_payment_methods",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "stripe_payment_method_id",
            sa.String(255),
            nullable=False,
            unique=True,
        ),
        sa.Column("brand", sa.String(50), nullable=False),
        sa.Column("last4", sa.String(4), nullable=False),
        sa.Column("exp_month", sa.SmallInteger, nullable=False),
        sa.Column("exp_year", sa.SmallInteger, nullable=False),
        sa.Column(
            "is_default",
            sa.Boolean,
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "is_verified",
            sa.Boolean,
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "expiry_notified_at",
            sa.DateTime(timezone=True),
            nullable=True,
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
    )

    # Indexes
    op.create_index(
        "ix_org_payment_methods_org_id", "org_payment_methods", ["org_id"]
    )

    # Enable RLS for tenant isolation
    op.execute("ALTER TABLE org_payment_methods ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON org_payment_methods "
        "USING (org_id = current_setting('app.current_org_id')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON org_payment_methods")
    op.execute("ALTER TABLE org_payment_methods DISABLE ROW LEVEL SECURITY")

    op.drop_index("ix_org_payment_methods_org_id", table_name="org_payment_methods")
    op.drop_table("org_payment_methods")
