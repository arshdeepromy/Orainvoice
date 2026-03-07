"""Create print_jobs table.

Revision ID: 0042
Revises: 0041
Create Date: 2025-01-15

Requirements: POS Module — Task 27.4
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0042"
down_revision: str = "0041"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "print_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("printer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("job_type", sa.String(20), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_print_jobs_org_id"),
        sa.ForeignKeyConstraint(["printer_id"], ["printer_configs.id"], name="fk_print_jobs_printer_id"),
    )
    op.create_index(
        "idx_print_jobs_pending",
        "print_jobs",
        ["status", "created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("idx_print_jobs_pending", table_name="print_jobs")
    op.drop_table("print_jobs")
