"""Create projects table.

Revision ID: 0033
Revises: 0032
Create Date: 2025-01-15

Requirements: 14.1 (Project Module)
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0033"
down_revision: str = "0032"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("budget_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("contract_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("revised_contract_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("retention_percentage", sa.Numeric(5, 2), server_default=sa.text("0"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("target_end_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(20), server_default=sa.text("'active'"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_projects_org_id"),
    )
    op.create_index("idx_projects_org", "projects", ["org_id"])
    op.create_index("idx_projects_customer", "projects", ["customer_id"])


def downgrade() -> None:
    op.drop_index("idx_projects_customer", table_name="projects")
    op.drop_index("idx_projects_org", table_name="projects")
    op.drop_table("projects")
