"""Create pending_qr_sessions table for kiosk QR payment flow.

Stores the active Stripe Checkout Session per org so the kiosk can
discover and display the QR code without requiring Redis.

- One active session per org (UNIQUE on org_id)
- UNIQUE on session_id for webhook-based cleanup
- Index on org_id for fast kiosk polling lookups
- RLS enabled with org-scoped policy
- HA publication membership for standby parity

Revision ID: 0190
Revises: 0189
Create Date: 2026-05-17

Requirements: 3.1, 3.2, 3.4
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "0190"
down_revision: str = "0189"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_TABLE = "pending_qr_sessions"

_HA_ADD = """
DO $ha_block$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'ora_publication') THEN
        ALTER PUBLICATION ora_publication ADD TABLE pending_qr_sessions;
    END IF;
END
$ha_block$
"""

_HA_DROP = """
DO $ha_block$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_publication_tables
        WHERE pubname = 'ora_publication' AND tablename = 'pending_qr_sessions'
    ) THEN
        ALTER PUBLICATION ora_publication DROP TABLE pending_qr_sessions;
    END IF;
END
$ha_block$
"""


def upgrade() -> None:
    # ── 1. Create pending_qr_sessions table (idempotent) ──────────────────
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = 'pending_qr_sessions'"
    ))
    if not result.scalar():
        op.create_table(
            _TABLE,
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("org_id", UUID(as_uuid=True), nullable=False),
            sa.Column("session_id", sa.String(255), nullable=False),
            sa.Column("checkout_url", sa.Text(), nullable=False),
            sa.Column("amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("invoice_number", sa.String(50), nullable=False),
            sa.Column("invoice_id", UUID(as_uuid=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            # Foreign keys
            sa.ForeignKeyConstraint(
                ["org_id"],
                ["organisations.id"],
                name="fk_pending_qr_sessions_org_id",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["invoice_id"],
                ["invoices.id"],
                name="fk_pending_qr_sessions_invoice_id",
                ondelete="CASCADE",
            ),
            # Unique constraints
            sa.UniqueConstraint("org_id", name="uq_pending_qr_sessions_org_id"),
            sa.UniqueConstraint("session_id", name="uq_pending_qr_sessions_session_id"),
        )

        # Index on org_id for fast kiosk polling lookups
        op.create_index(
            "idx_pending_qr_sessions_org_id",
            _TABLE,
            ["org_id"],
        )

    # ── 2. Enable RLS ─────────────────────────────────────────────────────
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {_TABLE}_org_isolation ON {_TABLE} "
        "USING (org_id = current_setting('app.current_org_id')::uuid)"
    )

    # ── 3. Add to HA replication publication ──────────────────────────────
    op.execute(sa.text(_HA_ADD))


def downgrade() -> None:
    # ── 1. Drop HA publication membership ─────────────────────────────────
    op.execute(sa.text(_HA_DROP))

    # ── 2. Drop RLS policy ────────────────────────────────────────────────
    op.execute(f"DROP POLICY IF EXISTS {_TABLE}_org_isolation ON {_TABLE}")

    # ── 3. Drop index ────────────────────────────────────────────────────
    op.execute("DROP INDEX IF EXISTS idx_pending_qr_sessions_org_id")

    # ── 4. Drop table ────────────────────────────────────────────────────
    op.execute(f"DROP TABLE IF EXISTS {_TABLE}")
