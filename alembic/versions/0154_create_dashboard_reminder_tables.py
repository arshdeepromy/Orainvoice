"""Create dashboard_reminder_dismissals and dashboard_reminder_config tables.

Adds two tables for the automotive dashboard widgets feature:
- dashboard_reminder_dismissals: tracks which WOF/service expiry reminders
  have been dismissed or marked as "reminder sent" by the user.
- dashboard_reminder_config: stores per-org reminder threshold configuration
  (how many days before expiry to surface reminders).

Revision ID: 0154
Revises: 0153
Create Date: 2026-04-18

Requirements: 11.4, 11.5, 11.6, 11.7, 12.1, 12.4
"""
from __future__ import annotations

from alembic import op


revision: str = "0154"
down_revision: str = "0153"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Create dashboard_reminder_dismissals table ─────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS dashboard_reminder_dismissals (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES organisations(id),
            vehicle_id UUID NOT NULL,
            reminder_type VARCHAR(20) NOT NULL
                CHECK (reminder_type IN ('wof', 'service')),
            action VARCHAR(20) NOT NULL
                CHECK (action IN ('dismissed', 'reminder_sent')),
            expiry_date DATE NOT NULL,
            dismissed_by UUID NOT NULL REFERENCES users(id),
            dismissed_at TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT uq_dismissal_org_vehicle_type_expiry
                UNIQUE (org_id, vehicle_id, reminder_type, expiry_date)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_dashboard_reminder_dismissals_org_id
        ON dashboard_reminder_dismissals (org_id)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_dashboard_reminder_dismissals_vehicle_id
        ON dashboard_reminder_dismissals (vehicle_id)
    """)

    # ── 2. Create dashboard_reminder_config table ─────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS dashboard_reminder_config (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES organisations(id) UNIQUE,
            wof_days INTEGER NOT NULL DEFAULT 30
                CHECK (wof_days >= 1 AND wof_days <= 365),
            service_days INTEGER NOT NULL DEFAULT 30
                CHECK (service_days >= 1 AND service_days <= 365),
            updated_by UUID NOT NULL REFERENCES users(id),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_dashboard_reminder_config_org_id
        ON dashboard_reminder_config (org_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_dashboard_reminder_config_org_id")
    op.execute("DROP TABLE IF EXISTS dashboard_reminder_config")
    op.execute("DROP INDEX IF EXISTS ix_dashboard_reminder_dismissals_vehicle_id")
    op.execute("DROP INDEX IF EXISTS ix_dashboard_reminder_dismissals_org_id")
    op.execute("DROP TABLE IF EXISTS dashboard_reminder_dismissals")
