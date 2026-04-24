"""Create compliance_notification_log table.

Tracks which expiry notifications have been sent for compliance documents
to prevent duplicate emails at each threshold (30-day, 7-day, day-of).

Revision ID: 0155
Revises: 0154
Create Date: 2026-04-19

Requirements: 13.1, 13.3
"""
from __future__ import annotations

from alembic import op


revision: str = "0155"
down_revision: str = "0154"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS compliance_notification_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id UUID NOT NULL
                REFERENCES compliance_documents(id) ON DELETE CASCADE,
            org_id UUID NOT NULL
                REFERENCES organisations(id) ON DELETE CASCADE,
            threshold VARCHAR(10) NOT NULL,
            sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT uq_compliance_notif_doc_threshold
                UNIQUE (document_id, threshold)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_compliance_notif_log_doc_id
        ON compliance_notification_log (document_id)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_compliance_notif_log_org_id
        ON compliance_notification_log (org_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_compliance_notif_log_org_id")
    op.execute("DROP INDEX IF EXISTS ix_compliance_notif_log_doc_id")
    op.execute("DROP TABLE IF EXISTS compliance_notification_log")
