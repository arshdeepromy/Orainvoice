"""Create expenses table.

Revision ID: 0034
Revises: 0033
Create Date: 2025-01-15

Requirements: Expense Module — Task 22.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0034"
down_revision: str = "0033"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "expenses",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(12, 2), server_default=sa.text("0"), nullable=False),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("receipt_file_key", sa.String(500), nullable=True),
        sa.Column("is_pass_through", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_invoiced", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_expenses_org_id"),
    )
    op.create_index("idx_expenses_org", "expenses", ["org_id"])
    op.create_index("idx_expenses_job", "expenses", ["job_id"])
    op.create_index("idx_expenses_project", "expenses", ["project_id"])
    op.create_index("idx_expenses_category", "expenses", ["org_id", "category"])
    op.create_index("idx_expenses_date", "expenses", ["org_id", "date"])


def downgrade() -> None:
    op.drop_index("idx_expenses_date", table_name="expenses")
    op.drop_index("idx_expenses_category", table_name="expenses")
    op.drop_index("idx_expenses_project", table_name="expenses")
    op.drop_index("idx_expenses_job", table_name="expenses")
    op.drop_index("idx_expenses_org", table_name="expenses")
    op.drop_table("expenses")
