"""Create compliance_document_categories table with predefined seed data.

Stores predefined (system-wide) and custom (org-specific) document categories
for compliance documents.

Revision ID: 0156
Revises: 0155
Create Date: 2026-04-19

Requirements: 6.1, 6.4
"""
from __future__ import annotations

from alembic import op


revision: str = "0156"
down_revision: str = "0155"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS compliance_document_categories (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(100) NOT NULL,
            org_id UUID REFERENCES organisations(id) ON DELETE CASCADE,
            is_predefined BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT uq_compliance_cat_name_org
                UNIQUE (name, org_id)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_compliance_doc_categories_org_id
        ON compliance_document_categories (org_id)
    """)

    # Seed the 15 predefined categories (org_id = NULL, is_predefined = TRUE)
    # Use ON CONFLICT DO NOTHING for idempotency
    op.execute("""
        INSERT INTO compliance_document_categories (name, org_id, is_predefined)
        VALUES
            ('Business License', NULL, TRUE),
            ('Public Liability Insurance', NULL, TRUE),
            ('Professional Indemnity Insurance', NULL, TRUE),
            ('Trade Certification', NULL, TRUE),
            ('Health and Safety Certificate', NULL, TRUE),
            ('Vehicle Registration', NULL, TRUE),
            ('Equipment Certification', NULL, TRUE),
            ('Environmental Permit', NULL, TRUE),
            ('Food Safety Certificate', NULL, TRUE),
            ('Workers Compensation Insurance', NULL, TRUE),
            ('Building Permit', NULL, TRUE),
            ('Electrical Safety Certificate', NULL, TRUE),
            ('Gas Safety Certificate', NULL, TRUE),
            ('Asbestos License', NULL, TRUE),
            ('Fire Safety Certificate', NULL, TRUE)
        ON CONFLICT ON CONSTRAINT uq_compliance_cat_name_org DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_compliance_doc_categories_org_id")
    op.execute("DROP TABLE IF EXISTS compliance_document_categories")
