"""Enhance feature_flags schema with category, access_level, dependencies, updated_by.

Revision ID: 0066
Revises: 0065
Create Date: 2025-01-15

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0066"
down_revision: str = "0065"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # Add category column with default "Core", indexed
    op.add_column(
        "feature_flags",
        sa.Column("category", sa.String(50), server_default=sa.text("'Core'"), nullable=False),
    )

    # Add access_level column with default "all_users"
    op.add_column(
        "feature_flags",
        sa.Column("access_level", sa.String(50), server_default=sa.text("'all_users'"), nullable=False),
    )

    # Add dependencies column as JSONB array with default []
    op.add_column(
        "feature_flags",
        sa.Column(
            "dependencies",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )

    # Add updated_by column as UUID FK to users.id, nullable
    op.add_column(
        "feature_flags",
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_feature_flags_updated_by",
        "feature_flags",
        "users",
        ["updated_by"],
        ["id"],
    )

    # Add index on is_active for efficient filtering
    op.create_index("ix_feature_flags_is_active", "feature_flags", ["is_active"])

    # Add index on category for efficient category-based queries
    op.create_index("ix_feature_flags_category", "feature_flags", ["category"])


def downgrade() -> None:
    op.drop_index("ix_feature_flags_category", table_name="feature_flags")
    op.drop_index("ix_feature_flags_is_active", table_name="feature_flags")
    op.drop_constraint("fk_feature_flags_updated_by", "feature_flags", type_="foreignkey")
    op.drop_column("feature_flags", "updated_by")
    op.drop_column("feature_flags", "dependencies")
    op.drop_column("feature_flags", "access_level")
    op.drop_column("feature_flags", "category")
