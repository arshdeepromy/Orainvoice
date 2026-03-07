"""Create setup_wizard_progress table.

Revision ID: 0014
Revises: 0013
Create Date: 2025-01-15

Requirements: 5.8
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str = "0013"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # -- setup_wizard_progress -----------------------------------------------
    op.create_table(
        "setup_wizard_progress",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_1_complete", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("step_2_complete", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("step_3_complete", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("step_4_complete", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("step_5_complete", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("step_6_complete", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("step_7_complete", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("wizard_completed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", name="uq_setup_wizard_progress_org_id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_setup_wizard_progress_org_id"),
    )


def downgrade() -> None:
    op.drop_table("setup_wizard_progress")
