"""Create compliance_documents table for compliance and certifications module.

Revision ID: 0050
Revises: 0049
Create Date: 2025-01-15

Requirements: Compliance Module — Task 38.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0050"
down_revision: str = "0049"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "compliance_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_type", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("file_key", sa.String(500), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_compliance_docs_org", "compliance_documents", ["org_id"])
    op.create_index("idx_compliance_docs_expiry", "compliance_documents", ["expiry_date"])


def downgrade() -> None:
    op.drop_index("idx_compliance_docs_expiry", table_name="compliance_documents")
    op.drop_index("idx_compliance_docs_org", table_name="compliance_documents")
    op.drop_table("compliance_documents")
