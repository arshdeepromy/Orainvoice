"""Create pos_sessions table.

Revision ID: 0039
Revises: 0038
Create Date: 2025-01-15

Requirements: POS Module — Task 27.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0039"
down_revision: str = "0038"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "pos_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opening_cash", sa.Numeric(12, 2), server_default=sa.text("0"), nullable=False),
        sa.Column("closing_cash", sa.Numeric(12, 2), nullable=True),
        sa.Column("status", sa.String(20), server_default=sa.text("'open'"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_pos_sessions_org_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_pos_sessions_user_id"),
    )
    op.create_index("idx_pos_sessions_org", "pos_sessions", ["org_id"])
    op.create_index("idx_pos_sessions_user", "pos_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_pos_sessions_user", table_name="pos_sessions")
    op.drop_index("idx_pos_sessions_org", table_name="pos_sessions")
    op.drop_table("pos_sessions")
