"""Add job_card_appendix_html column to invoices table.

Adds a nullable TEXT column to store the rendered HTML snapshot of job card
data for the PDF appendix. This column is populated during
convert_job_card_to_invoice() and used by generate_invoice_pdf() to append
a second page to the invoice PDF.

Revision ID: 0163
Revises: 0162
Create Date: 2026-04-27

Requirements: 1.1, 1.2, 1.3
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "0163"
down_revision: str = "0162"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column(
            "job_card_appendix_html",
            sa.Text(),
            nullable=True,
            comment="HTML snapshot of job card data for PDF appendix",
        ),
    )


def downgrade() -> None:
    op.drop_column("invoices", "job_card_appendix_html")
