"""Create org_terminology_overrides table.

Revision ID: 0015
Revises: 0014
Create Date: 2025-01-15

Requirements: 4.4
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str = "0014"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # -- org_terminology_overrides -------------------------------------------
    op.create_table(
        "org_terminology_overrides",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("generic_key", sa.String(100), nullable=False),
        sa.Column("custom_label", sa.String(255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "generic_key", name="uq_org_terminology_overrides_org_key"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_org_terminology_overrides_org_id"),
    )


def downgrade() -> None:
    op.drop_table("org_terminology_overrides")
