"""Extend branches table and add branch_id FK to entity tables.

Adds columns to branches: email, logo_url, operating_hours (JSONB),
timezone, is_hq, notification_preferences (JSONB), updated_at.

Adds nullable branch_id UUID FK + index to: quotes, job_cards,
customers, expenses, purchase_orders, projects, stock_items.
All FKs use ON DELETE SET NULL. Existing records keep branch_id = NULL.

Data migration: sets is_hq = True on the earliest branch per org.

Revision ID: 0129
Revises: 0128
Create Date: 2026-04-02

Requirements: 1.5, 2.1, 3.1, 6.1, 11.1, 12.1, 13.1, 14.1, 14.2, 14.3, 18.1, 22.4, 23.1, 23.2, 23.5, 23.6
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0129"
down_revision: str = "0128"
branch_labels = None
depends_on = None

# Tables that need a nullable branch_id FK column + index.
# Invoices and bookings already have branch_id — skip them.
_FK_TABLES = [
    "quotes",
    "job_cards",
    "customers",
    "expenses",
    "purchase_orders",
    "projects",
    "stock_items",
]


def upgrade() -> None:
    # ── 1. Extend branches table ──────────────────────────────────────────
    op.add_column("branches", sa.Column("email", sa.String(255), nullable=True))
    op.add_column("branches", sa.Column("logo_url", sa.Text(), nullable=True))
    op.add_column(
        "branches",
        sa.Column("operating_hours", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "branches",
        sa.Column(
            "timezone",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'Pacific/Auckland'"),
        ),
    )
    op.add_column(
        "branches",
        sa.Column("is_hq", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "branches",
        sa.Column(
            "notification_preferences", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
    )
    op.add_column(
        "branches",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ── 2. Add nullable branch_id FK + index to entity tables ─────────────
    for table in _FK_TABLES:
        op.add_column(
            table,
            sa.Column("branch_id", UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            f"fk_{table}_branch_id",
            table,
            "branches",
            ["branch_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(f"ix_{table}_branch_id", table, ["branch_id"])

    # ── 3. Data migration: mark earliest branch per org as HQ ─────────────
    op.execute(
        """
        UPDATE branches
        SET is_hq = true
        WHERE id IN (
            SELECT DISTINCT ON (org_id) id
            FROM branches
            ORDER BY org_id, created_at ASC, id ASC
        )
        """
    )


def downgrade() -> None:
    # ── Reverse entity FK columns ─────────────────────────────────────────
    for table in reversed(_FK_TABLES):
        op.drop_index(f"ix_{table}_branch_id", table_name=table)
        op.drop_constraint(f"fk_{table}_branch_id", table, type_="foreignkey")
        op.drop_column(table, "branch_id")

    # ── Remove branches extension columns ─────────────────────────────────
    op.drop_column("branches", "updated_at")
    op.drop_column("branches", "notification_preferences")
    op.drop_column("branches", "is_hq")
    op.drop_column("branches", "timezone")
    op.drop_column("branches", "operating_hours")
    op.drop_column("branches", "logo_url")
    op.drop_column("branches", "email")
