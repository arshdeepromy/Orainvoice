"""Create printer_configs table.

Revision ID: 0041
Revises: 0040
Create Date: 2025-01-15

Requirements: POS Module — Task 27.3
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0041"
down_revision: str = "0040"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "printer_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("connection_type", sa.String(20), nullable=False),
        sa.Column("address", sa.String(255), nullable=True),
        sa.Column("paper_width", sa.Integer(), server_default=sa.text("80"), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_kitchen_printer", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_printer_configs_org_id"),
        # NOTE: location_id FK to locations is omitted — that table is created in Task 43.
    )
    op.create_index("idx_printer_configs_org", "printer_configs", ["org_id"])


def downgrade() -> None:
    op.drop_index("idx_printer_configs_org", table_name="printer_configs")
    op.drop_table("printer_configs")
