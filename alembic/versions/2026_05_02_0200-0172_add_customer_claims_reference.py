"""Add reference column to customer_claims table.

The dashboard widget query (get_recent_claims) selects cc.reference but
the column was never created. This migration adds it and backfills
existing claims with CLM-NNNNN references (org-scoped, ordered by
created_at).

Revision ID: 0172
Revises: 0171
Create Date: 2026-05-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0172"
down_revision: str = "0171"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # 1. Add the column (nullable so existing rows don't break)
    op.add_column(
        "customer_claims",
        sa.Column("reference", sa.String(50), nullable=True),
    )

    # 2. Backfill existing claims with CLM-NNNNN per org
    op.execute(
        """
        WITH numbered AS (
            SELECT id, org_id,
                   ROW_NUMBER() OVER (PARTITION BY org_id ORDER BY created_at) AS rn
            FROM customer_claims
            WHERE reference IS NULL
        )
        UPDATE customer_claims cc
        SET reference = 'CLM-' || LPAD(n.rn::text, 5, '0')
        FROM numbered n
        WHERE cc.id = n.id
        """
    )


def downgrade() -> None:
    op.drop_column("customer_claims", "reference")
