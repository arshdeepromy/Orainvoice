"""Staff Timesheets — timesheets + timesheet_settings tables + RLS.

Schema-additive migration that:

  - **Creates ``timesheets``** — per-staff per-pay-period aggregated
    timesheet row with status state machine
    (open/pending_approval/approved/locked), rostered vs actual minute
    breakdowns, exception flags JSONB, and FK links to staff_members,
    pay_periods, branches, users (approved_by/locked_by), and payslips.
    UNIQUE constraint ``(staff_id, pay_period_id)`` prevents duplicates.

  - **Creates ``timesheet_settings``** — per-org (optionally per-branch
    override) configuration for clock rounding, grace windows, match
    policy, auto-approve thresholds, and approval-before-lock toggle.
    UNIQUE constraint ``(org_id, branch_id)`` prevents duplicate
    settings per org+branch combination.

  - **RLS + ``tenant_isolation`` policies** on both new tables using
    the standard ``current_setting('app.current_org_id', true)::uuid``
    pattern.

  - **Indexes** on timesheets: ``ix_timesheets_org_period``,
    ``ix_timesheets_branch`` (partial), ``ix_timesheets_status``.

Idempotent throughout — every CREATE uses IF NOT EXISTS, every policy
uses DROP POLICY IF EXISTS then CREATE POLICY, every index uses
IF NOT EXISTS.

NOTE: Tasks A1.2, A1.3, A1.4 will add ALTER TABLE statements to this
same file in subsequent task executions.

Refs: requirements 1.1, 1.2, 4.2; design §3.1.

Revision ID: 0218
Revises: 0217
Create Date: 2026-06-08
"""

from __future__ import annotations

from alembic import op

revision: str = "0218"
down_revision: str = "0217"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. timesheets — per-staff per-pay-period aggregated row.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS timesheets (
            id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id                  uuid NOT NULL,
            staff_id                uuid NOT NULL REFERENCES staff_members(id),
            pay_period_id           uuid NOT NULL REFERENCES pay_periods(id),
            branch_id               uuid REFERENCES branches(id),
            rostered_minutes        integer NOT NULL DEFAULT 0,
            actual_minutes          integer NOT NULL DEFAULT 0,
            adjusted_minutes        integer,
            ordinary_minutes        integer NOT NULL DEFAULT 0,
            overtime_minutes        integer NOT NULL DEFAULT 0,
            public_holiday_minutes  integer NOT NULL DEFAULT 0,
            exception_flags         jsonb NOT NULL DEFAULT '[]'::jsonb,
            status                  text NOT NULL DEFAULT 'open',
            approved_by             uuid REFERENCES users(id),
            approved_at             timestamptz,
            locked_at               timestamptz,
            locked_by               uuid REFERENCES users(id),
            payslip_id              uuid REFERENCES payslips(id),
            notes                   text,
            created_at              timestamptz NOT NULL DEFAULT now(),
            updated_at              timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_timesheets_staff_period UNIQUE (staff_id, pay_period_id)
        )
        """
    )
    op.execute(
        "ALTER TABLE timesheets DROP CONSTRAINT IF EXISTS ck_timesheets_status"
    )
    op.execute(
        """
        ALTER TABLE timesheets ADD CONSTRAINT ck_timesheets_status
            CHECK (status IN ('open','pending_approval','approved','locked'))
        """
    )

    # Indexes (inline, non-CONCURRENTLY — table is new/empty).
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_timesheets_org_period
            ON timesheets(org_id, pay_period_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_timesheets_branch
            ON timesheets(branch_id) WHERE branch_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_timesheets_status
            ON timesheets(org_id, status)
        """
    )

    # RLS policy.
    op.execute("ALTER TABLE timesheets ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON timesheets")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON timesheets
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # 2. timesheet_settings — per-org (optionally per-branch) config.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS timesheet_settings (
            id                              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id                          uuid NOT NULL,
            branch_id                       uuid REFERENCES branches(id),
            clock_rounding_minutes          integer NOT NULL DEFAULT 1,
            clock_rounding_direction        text NOT NULL DEFAULT 'nearest',
            early_grace_minutes             integer NOT NULL DEFAULT 0,
            late_grace_minutes              integer NOT NULL DEFAULT 0,
            match_policy                    text NOT NULL DEFAULT 'pay_actual',
            auto_approve_threshold_minutes  integer NOT NULL DEFAULT 0,
            require_approval_before_lock    boolean NOT NULL DEFAULT true,
            created_at                      timestamptz NOT NULL DEFAULT now(),
            updated_at                      timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_timesheet_settings_org_branch UNIQUE (org_id, branch_id)
        )
        """
    )
    op.execute(
        "ALTER TABLE timesheet_settings DROP CONSTRAINT IF EXISTS ck_timesheet_settings_rounding_minutes"
    )
    op.execute(
        """
        ALTER TABLE timesheet_settings ADD CONSTRAINT ck_timesheet_settings_rounding_minutes
            CHECK (clock_rounding_minutes IN (1, 5, 10, 15, 30))
        """
    )
    op.execute(
        "ALTER TABLE timesheet_settings DROP CONSTRAINT IF EXISTS ck_timesheet_settings_rounding_direction"
    )
    op.execute(
        """
        ALTER TABLE timesheet_settings ADD CONSTRAINT ck_timesheet_settings_rounding_direction
            CHECK (clock_rounding_direction IN ('nearest','up','down'))
        """
    )
    op.execute(
        "ALTER TABLE timesheet_settings DROP CONSTRAINT IF EXISTS ck_timesheet_settings_match_policy"
    )
    op.execute(
        """
        ALTER TABLE timesheet_settings ADD CONSTRAINT ck_timesheet_settings_match_policy
            CHECK (match_policy IN ('pay_actual','round_to_roster','actual_rounded'))
        """
    )

    # RLS policy.
    op.execute("ALTER TABLE timesheet_settings ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON timesheet_settings")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON timesheet_settings
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # 3. ALTER time_clock_entries — add branch_id, clock_out_branch_id, clock_in_ip.
    # Code-truth: these columns do NOT exist today. branch_id is brand new.
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE time_clock_entries ADD COLUMN IF NOT EXISTS branch_id UUID REFERENCES branches(id)"
    )
    op.execute(
        "ALTER TABLE time_clock_entries ADD COLUMN IF NOT EXISTS clock_out_branch_id UUID REFERENCES branches(id)"
    )
    op.execute(
        "ALTER TABLE time_clock_entries ADD COLUMN IF NOT EXISTS clock_in_ip TEXT"
    )
    # Forward-only NOT NULL on branch_id for rows created after this migration.
    # Old rows with branch_id=NULL remain valid.
    op.execute(
        "ALTER TABLE time_clock_entries DROP CONSTRAINT IF EXISTS ck_tce_branch_id_new_rows"
    )
    op.execute(
        """
        ALTER TABLE time_clock_entries ADD CONSTRAINT ck_tce_branch_id_new_rows
            CHECK (created_at <= '2026-06-08T00:00:00Z'::timestamptz OR branch_id IS NOT NULL)
        """
    )

    # ------------------------------------------------------------------
    # 4. Immutability trigger on time_clock_entries.
    # Allows NULL → value (normal clock-out) but blocks value → different value.
    # DELETE is unconditionally blocked.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION tce_immutability_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE' AND (
                (OLD.clock_in_at IS NOT NULL AND OLD.clock_in_at IS DISTINCT FROM NEW.clock_in_at) OR
                (OLD.clock_out_at IS NOT NULL AND OLD.clock_out_at IS DISTINCT FROM NEW.clock_out_at)
            ) THEN
                RAISE EXCEPTION 'Mutation of immutable clock columns on entry % is prohibited', OLD.id
                    USING ERRCODE = 'restrict_violation';
                RETURN OLD;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Deletion of time_clock_entry % is prohibited', OLD.id
                    USING ERRCODE = 'restrict_violation';
                RETURN NULL;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_tce_immutability ON time_clock_entries")
    op.execute(
        """
        CREATE TRIGGER trg_tce_immutability
            BEFORE UPDATE OR DELETE ON time_clock_entries
            FOR EACH ROW EXECUTE FUNCTION tce_immutability_guard()
        """
    )

    # ------------------------------------------------------------------
    # 5. ALTER timesheet_approvals — add timesheet_id FK for repurposing.
    # Existing rows remain with timesheet_id = NULL.
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE timesheet_approvals ADD COLUMN IF NOT EXISTS timesheet_id UUID REFERENCES timesheets(id)"
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_timesheet_approvals_timesheet
            ON timesheet_approvals(timesheet_id) WHERE timesheet_id IS NOT NULL
        """
    )

    # ------------------------------------------------------------------
    # 6. Register timesheets module in module_registry with setup_question.
    # ------------------------------------------------------------------
    op.execute(
        """
        INSERT INTO module_registry (id, slug, display_name, description, category, is_core, dependencies, incompatibilities, status, setup_question, setup_question_description)
        VALUES (
            gen_random_uuid(),
            'timesheets',
            'Staff Timesheets',
            'Clock-in/out tracking, timesheet approval, match-to-roster automation, and pay-run integration.',
            'staff',
            false,
            '["staff", "scheduling"]'::jsonb,
            '[]'::jsonb,
            'available',
            'Will you be tracking staff work hours, timesheets, and attendance?',
            'Clock-in/out tracking, timesheet approval, and match-to-roster automation for pay-run accuracy.'
        )
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    # Undo A1.5: remove module_registry row
    op.execute("DELETE FROM module_registry WHERE slug = 'timesheets'")
    # Undo A1.4: remove timesheet_id column from timesheet_approvals
    op.execute("DROP INDEX IF EXISTS ix_timesheet_approvals_timesheet")
    op.execute("ALTER TABLE timesheet_approvals DROP COLUMN IF EXISTS timesheet_id")

    # Undo A1.3: remove immutability trigger
    op.execute("DROP TRIGGER IF EXISTS trg_tce_immutability ON time_clock_entries")
    op.execute("DROP FUNCTION IF EXISTS tce_immutability_guard()")

    # Undo A1.2: remove added columns and constraint from time_clock_entries
    op.execute("ALTER TABLE time_clock_entries DROP CONSTRAINT IF EXISTS ck_tce_branch_id_new_rows")
    op.execute("ALTER TABLE time_clock_entries DROP COLUMN IF EXISTS clock_in_ip")
    op.execute("ALTER TABLE time_clock_entries DROP COLUMN IF EXISTS clock_out_branch_id")
    op.execute("ALTER TABLE time_clock_entries DROP COLUMN IF EXISTS branch_id")

    # Drop RLS policies first, then tables.
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON timesheet_settings")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON timesheets")

    op.execute("DROP TABLE IF EXISTS timesheet_settings")
    op.execute("DROP TABLE IF EXISTS timesheets")
