"""Create module_registry and org_modules tables.

Revision ID: 0011
Revises: 0010
Create Date: 2025-01-15

Requirements: 6.1, 6.2
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str = "0010"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # -- module_registry -----------------------------------------------------
    op.create_table(
        "module_registry",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("is_core", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("dependencies", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("incompatibilities", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("status", sa.String(20), server_default=sa.text("'available'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_module_registry_slug"),
    )

    # -- org_modules ---------------------------------------------------------
    op.create_table(
        "org_modules",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module_slug", sa.String(100), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("enabled_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("enabled_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "module_slug", name="uq_org_modules_org_slug"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_org_modules_org_id"),
        sa.ForeignKeyConstraint(["enabled_by"], ["users.id"], name="fk_org_modules_enabled_by"),
    )
    op.create_index("idx_org_modules_org", "org_modules", ["org_id"])


def downgrade() -> None:
    op.drop_index("idx_org_modules_org", table_name="org_modules")
    op.drop_table("org_modules")
    op.drop_table("module_registry")
