"""Create retention_releases table for construction retention tracking module.

Revision ID: 0049
Revises: 0048
Create Date: 2025-01-15

Requirements: Retention Module — Task 37.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0049"
down_revision: str = "0048"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "retention_releases",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("release_date", sa.Date(), nullable=False),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("amount > 0", name="ck_retention_releases_positive_amount"),
    )
    op.create_index("idx_retention_releases_project", "retention_releases", ["project_id"])


def downgrade() -> None:
    op.drop_index("idx_retention_releases_project", table_name="retention_releases")
    op.drop_table("retention_releases")
