"""Create progress_claims table for construction progress claims module.

Revision ID: 0047
Revises: 0046
Create Date: 2025-01-15

Requirements: ProgressClaim Module — Task 35.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0047"
down_revision: str = "0046"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "progress_claims",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_number", sa.Integer(), nullable=False),
        sa.Column("contract_value", sa.Numeric(14, 2), nullable=False),
        sa.Column("variations_to_date", sa.Numeric(14, 2), server_default=sa.text("0"), nullable=False),
        sa.Column("revised_contract_value", sa.Numeric(14, 2), nullable=False),
        sa.Column("work_completed_to_date", sa.Numeric(14, 2), nullable=False),
        sa.Column("work_completed_previous", sa.Numeric(14, 2), server_default=sa.text("0"), nullable=False),
        sa.Column("work_completed_this_period", sa.Numeric(14, 2), nullable=False),
        sa.Column("materials_on_site", sa.Numeric(14, 2), server_default=sa.text("0"), nullable=False),
        sa.Column("retention_withheld", sa.Numeric(14, 2), server_default=sa.text("0"), nullable=False),
        sa.Column("amount_due", sa.Numeric(14, 2), nullable=False),
        sa.Column("completion_percentage", sa.Numeric(5, 2), nullable=False),
        sa.Column("status", sa.String(20), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_progress_claims_org_id"),
        sa.CheckConstraint("status IN ('draft', 'submitted', 'approved', 'rejected')", name="ck_progress_claims_status"),
        sa.CheckConstraint("work_completed_to_date <= revised_contract_value", name="ck_progress_claims_work_within_contract"),
        sa.UniqueConstraint("org_id", "project_id", "claim_number", name="uq_progress_claims_org_project_claim"),
    )
    op.create_index("idx_progress_claims_org", "progress_claims", ["org_id"])
    op.create_index("idx_progress_claims_project", "progress_claims", ["project_id"])
    op.create_index("idx_progress_claims_status", "progress_claims", ["org_id", "status"])


def downgrade() -> None:
    op.drop_index("idx_progress_claims_status", table_name="progress_claims")
    op.drop_index("idx_progress_claims_project", table_name="progress_claims")
    op.drop_index("idx_progress_claims_org", table_name="progress_claims")
    op.drop_table("progress_claims")
