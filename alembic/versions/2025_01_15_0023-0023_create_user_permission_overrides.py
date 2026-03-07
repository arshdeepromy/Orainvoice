"""Create user_permission_overrides table.

Revision ID: 0023
Revises: 0022
Create Date: 2025-01-15

Requirements: 8.5, 8.7
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0023"
down_revision: str = "0022"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "user_permission_overrides",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("permission_key", sa.String(100), nullable=False),
        sa.Column("is_granted", sa.Boolean(), nullable=False),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_user_permission_overrides_user", "user_permission_overrides", ["user_id"])
    op.create_unique_constraint(
        "uq_user_permission_overrides_user_perm",
        "user_permission_overrides",
        ["user_id", "permission_key"],
    )


def downgrade() -> None:
    op.drop_table("user_permission_overrides")
