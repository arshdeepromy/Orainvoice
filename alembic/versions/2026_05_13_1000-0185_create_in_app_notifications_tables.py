"""Create app_notifications and notification_reads tables for in-app
notification inbox.

- app_notifications: stores org-scoped notifications (email failures,
  stock alerts, system events)
- notification_reads: per-user read/dismiss state (lazy-created on
  first interaction)
- RLS enabled on both tables with org-scoped policy
- HA publication membership for standby parity
- Indexes for org listing and per-user inbox scans

Revision ID: 0185
Revises: 0184
Create Date: 2026-05-13

Requirements: 4.1, 4.2, 8.1, 8.2
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision: str = "0185"
down_revision: str = "0184"
branch_labels = None
depends_on = None

_NOTIF_TABLE = "app_notifications"
_READS_TABLE = "notification_reads"

_HA_ADD_TPL = """
DO $ha_block$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'ora_publication') THEN
        ALTER PUBLICATION ora_publication ADD TABLE {table};
    END IF;
END
$ha_block$
"""

_HA_DROP_TPL = """
DO $ha_block$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_publication_tables
        WHERE pubname = 'ora_publication' AND tablename = '{table}'
    ) THEN
        ALTER PUBLICATION ora_publication DROP TABLE {table};
    END IF;
END
$ha_block$
"""


def upgrade() -> None:
    # ── 1. Create app_notifications table ─────────────────────────────────
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = 'app_notifications'"
    ))
    if not result.scalar():
        op.create_table(
            _NOTIF_TABLE,
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("org_id", UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", UUID(as_uuid=True), nullable=True),
            sa.Column("category", sa.String(50), nullable=False),
            sa.Column("severity", sa.String(20), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("link_url", sa.String(500), nullable=True),
            sa.Column("entity_type", sa.String(50), nullable=True),
            sa.Column("entity_id", UUID(as_uuid=True), nullable=True),
            sa.Column("audience_roles", JSONB(), nullable=False, server_default=sa.text("'[\"org_admin\"]'::jsonb")),
            sa.Column("metadata", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            # Foreign keys
            sa.ForeignKeyConstraint(
                ["org_id"],
                ["organisations.id"],
                name="fk_app_notifications_org_id",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                name="fk_app_notifications_user_id",
                ondelete="CASCADE",
            ),
            # CHECK constraint for severity
            sa.CheckConstraint(
                "severity IN ('info', 'success', 'warning', 'error')",
                name="ck_app_notifications_severity",
            ),
        )

        # Indexes per design §2
        op.create_index(
            "idx_app_notifications_org_created",
            _NOTIF_TABLE,
            ["org_id", sa.text("created_at DESC")],
        )
        op.create_index(
            "idx_app_notifications_org_category",
            _NOTIF_TABLE,
            ["org_id", "category"],
        )
        op.create_index(
            "idx_app_notifications_user_created",
            _NOTIF_TABLE,
            ["user_id", sa.text("created_at DESC")],
            postgresql_where=sa.text("user_id IS NOT NULL"),
        )

    # ── 2. Create notification_reads table ────────────────────────────────
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = 'notification_reads'"
    ))
    if not result.scalar():
        op.create_table(
            _READS_TABLE,
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("org_id", UUID(as_uuid=True), nullable=False),
            sa.Column("notification_id", UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", UUID(as_uuid=True), nullable=False),
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            # Foreign keys
            sa.ForeignKeyConstraint(
                ["notification_id"],
                ["app_notifications.id"],
                name="fk_notification_reads_notification_id",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                name="fk_notification_reads_user_id",
                ondelete="CASCADE",
            ),
            # Unique constraint: one row per user per notification
            sa.UniqueConstraint(
                "notification_id", "user_id",
                name="uq_notification_reads_notification_user",
            ),
        )

        # Index for per-user inbox scans
        op.create_index(
            "idx_notification_reads_user",
            _READS_TABLE,
            ["user_id", "dismissed_at"],
        )

    # ── 3. Enable RLS on both tables ──────────────────────────────────────
    for tbl in (_NOTIF_TABLE, _READS_TABLE):
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {tbl}_org_isolation ON {tbl} "
            "USING (org_id = current_setting('app.current_org_id')::uuid)"
        )

    # ── 4. Add both tables to HA replication publication ──────────────────
    op.execute(sa.text(_HA_ADD_TPL.format(table=_NOTIF_TABLE)))
    op.execute(sa.text(_HA_ADD_TPL.format(table=_READS_TABLE)))


def downgrade() -> None:
    # ── 1. Drop HA publication membership (guarded) ───────────────────────
    op.execute(sa.text(_HA_DROP_TPL.format(table=_READS_TABLE)))
    op.execute(sa.text(_HA_DROP_TPL.format(table=_NOTIF_TABLE)))

    # ── 2. Drop RLS policies ─────────────────────────────────────────────
    op.execute(f"DROP POLICY IF EXISTS {_READS_TABLE}_org_isolation ON {_READS_TABLE}")
    op.execute(f"DROP POLICY IF EXISTS {_NOTIF_TABLE}_org_isolation ON {_NOTIF_TABLE}")

    # ── 3. Drop indexes ──────────────────────────────────────────────────
    op.execute("DROP INDEX IF EXISTS idx_notification_reads_user")
    op.execute("DROP INDEX IF EXISTS idx_app_notifications_user_created")
    op.execute("DROP INDEX IF EXISTS idx_app_notifications_org_category")
    op.execute("DROP INDEX IF EXISTS idx_app_notifications_org_created")

    # ── 4. Drop tables ───────────────────────────────────────────────────
    op.execute(f"DROP TABLE IF EXISTS {_READS_TABLE}")
    op.execute(f"DROP TABLE IF EXISTS {_NOTIF_TABLE}")
