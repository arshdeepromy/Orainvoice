"""Create suppliers table with org_id, name, contact details, active status.

Revision ID: 0026
Revises: 0025
Create Date: 2025-01-15

Requirements: 9.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0026"
down_revision: str = "0025"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # Table already created in migration 0004. Add missing columns.
    op.add_column("suppliers", sa.Column("notes", sa.Text(), nullable=True))
    op.add_column(
        "suppliers",
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_suppliers_org ON suppliers (org_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_suppliers_org_active ON suppliers (org_id, is_active)")


def downgrade() -> None:
    op.drop_index("idx_suppliers_org_active", table_name="suppliers")
    op.drop_index("idx_suppliers_org", table_name="suppliers")
    op.drop_column("suppliers", "is_active")
    op.drop_column("suppliers", "notes")
