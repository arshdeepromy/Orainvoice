"""Phase B: Pay Cycles, Adjustments, and Timesheet Settings Extensions.

Creates:
  - ``pay_cycles`` — org-level pay cycle definitions (frequency, anchor, pay offset).
  - ``pay_cycle_assignments`` — target assignments (all/branch/employment_type/staff).
  - ``timesheet_adjustments`` — corrections-to-next-run for locked periods.

Alters:
  - ``pay_periods`` — adds ``pay_cycle_id`` FK (nullable for backwards compat).
  - ``timesheet_settings`` — adds overtime/break/holiday columns for Phase C.

Idempotent: uses IF NOT EXISTS / DROP IF EXISTS throughout.

Revision ID: 0219
Revises: 0218
Create Date: 2026-06-09
"""

from __future__ import annotations

from alembic import op

revision: str = "0219"
down_revision: str = "0218"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. pay_cycles — org-level pay cycle definitions.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pay_cycles (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id          uuid NOT NULL,
            name            text NOT NULL,
            frequency       text NOT NULL DEFAULT 'fortnightly',
            anchor_date     date NOT NULL,
            pay_date_offset_days integer NOT NULL DEFAULT 3,
            is_default      boolean NOT NULL DEFAULT false,
            active          boolean NOT NULL DEFAULT true,
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_pay_cycles_frequency
                CHECK (frequency IN ('weekly','fortnightly','monthly')),
            CONSTRAINT uq_pay_cycles_org_name UNIQUE (org_id, name)
        )
        """
    )

    # RLS
    op.execute("ALTER TABLE pay_cycles ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON pay_cycles")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON pay_cycles
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # Indexes
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pay_cycles_org ON pay_cycles(org_id)"
    )

    # ------------------------------------------------------------------
    # 2. pay_cycle_assignments — target assignments for pay cycles.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pay_cycle_assignments (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            pay_cycle_id    uuid NOT NULL REFERENCES pay_cycles(id) ON DELETE CASCADE,
            org_id          uuid NOT NULL,
            target_type     text NOT NULL DEFAULT 'all',
            target_id       uuid,
            created_at      timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_pay_cycle_assignments_target_type
                CHECK (target_type IN ('all','branch','employment_type','staff')),
            CONSTRAINT uq_pay_cycle_assignments_cycle_target
                UNIQUE (pay_cycle_id, target_type, target_id)
        )
        """
    )

    # RLS
    op.execute("ALTER TABLE pay_cycle_assignments ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON pay_cycle_assignments")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON pay_cycle_assignments
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pay_cycle_assignments_cycle "
        "ON pay_cycle_assignments(pay_cycle_id)"
    )

    # ------------------------------------------------------------------
    # 3. ALTER pay_periods — add pay_cycle_id FK.
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE pay_periods ADD COLUMN IF NOT EXISTS "
        "pay_cycle_id uuid REFERENCES pay_cycles(id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pay_periods_cycle "
        "ON pay_periods(pay_cycle_id) WHERE pay_cycle_id IS NOT NULL"
    )

    # ------------------------------------------------------------------
    # 4. timesheet_adjustments — corrections applied to next open period.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS timesheet_adjustments (
            id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id                  uuid NOT NULL,
            original_timesheet_id   uuid NOT NULL REFERENCES timesheets(id),
            correction_period_id    uuid NOT NULL REFERENCES pay_periods(id),
            adjustment_minutes      integer NOT NULL,
            reason                  text NOT NULL,
            category                text NOT NULL DEFAULT 'correction',
            created_by              uuid NOT NULL REFERENCES users(id),
            created_at              timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_timesheet_adjustments_category
                CHECK (category IN ('correction','error_fix','leave_adjustment','other'))
        )
        """
    )

    # RLS
    op.execute("ALTER TABLE timesheet_adjustments ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON timesheet_adjustments")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON timesheet_adjustments
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_timesheet_adjustments_original "
        "ON timesheet_adjustments(original_timesheet_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_timesheet_adjustments_correction_period "
        "ON timesheet_adjustments(correction_period_id)"
    )

    # ------------------------------------------------------------------
    # 5. ALTER timesheet_settings — add Phase C columns.
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE timesheet_settings "
        "ADD COLUMN IF NOT EXISTS daily_overtime_threshold_minutes integer NOT NULL DEFAULT 480"
    )
    op.execute(
        "ALTER TABLE timesheet_settings "
        "ADD COLUMN IF NOT EXISTS weekly_overtime_threshold_minutes integer NOT NULL DEFAULT 2400"
    )
    op.execute(
        "ALTER TABLE timesheet_settings "
        "ADD COLUMN IF NOT EXISTS overtime_rate_multiplier numeric(4,2) NOT NULL DEFAULT 1.50"
    )
    op.execute(
        "ALTER TABLE timesheet_settings "
        "ADD COLUMN IF NOT EXISTS break_rules jsonb NOT NULL DEFAULT '[]'::jsonb"
    )
    op.execute(
        "ALTER TABLE timesheet_settings "
        "ADD COLUMN IF NOT EXISTS public_holiday_rate_multiplier numeric(4,2) NOT NULL DEFAULT 1.50"
    )


def downgrade() -> None:
    # Remove Phase C columns from timesheet_settings
    op.execute(
        "ALTER TABLE timesheet_settings "
        "DROP COLUMN IF EXISTS public_holiday_rate_multiplier"
    )
    op.execute(
        "ALTER TABLE timesheet_settings "
        "DROP COLUMN IF EXISTS break_rules"
    )
    op.execute(
        "ALTER TABLE timesheet_settings "
        "DROP COLUMN IF EXISTS overtime_rate_multiplier"
    )
    op.execute(
        "ALTER TABLE timesheet_settings "
        "DROP COLUMN IF EXISTS weekly_overtime_threshold_minutes"
    )
    op.execute(
        "ALTER TABLE timesheet_settings "
        "DROP COLUMN IF EXISTS daily_overtime_threshold_minutes"
    )

    # Drop adjustments table
    op.execute("DROP TABLE IF EXISTS timesheet_adjustments")

    # Remove pay_cycle_id from pay_periods
    op.execute("ALTER TABLE pay_periods DROP COLUMN IF EXISTS pay_cycle_id")

    # Drop assignment + cycles tables
    op.execute("DROP TABLE IF EXISTS pay_cycle_assignments")
    op.execute("DROP TABLE IF EXISTS pay_cycles")
