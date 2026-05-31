"""Staff Management Phase 1 — expanded employment record + pay rate history
+ roster view tokens + module registration.

Schema-additive migration that:
  - Adds 23 new columns to ``staff_members`` (employment dates, employment
    type, NZ tax fields, KiwiSaver, encrypted IRD + bank account, probation
    + visa fields, residency_type, on-file photo, emergency contact,
    roster delivery opt-ins, last pay review, employment agreement upload).
  - Adds CHECK constraints for ``employment_type``, ``tax_code``, and
    ``residency_type`` enums (drop+recreate idempotent).
  - Creates ``staff_pay_rates`` (pay-rate audit ledger) with RLS +
    ``tenant_isolation`` policy.
  - Creates ``staff_roster_view_tokens`` (public read-only roster viewer
    tokens — used by the SMS-roster delivery flow) with RLS,
    ``tenant_isolation`` policy, and ``ON DELETE CASCADE`` on both
    ``org_id`` and ``staff_id`` FKs (G8) so hard-deleting a staff or org
    sweeps the tokens automatically.
  - Inserts ``module_registry`` rows for ``staff_management`` and
    ``payroll`` (idempotent ON CONFLICT (slug)).
  - Inserts mirror ``feature_flags`` rows with the actual column shape
    — id, key, display_name, description, category, access_level,
    dependencies, default_value, is_active, targeting_rules — and
    ``default_value=true`` per the policy from migration ``0171``
    (module gate is the real lever; the flag mirror is passive).
    Pattern matches ``2025_01_15_0067-0067_seed_comprehensive_feature_flags.py``.
  - Updates ``subscription_plans.enabled_modules`` JSONB to include both
    new slugs ``WHERE is_archived = false`` (P1-N2 — STAFF-001 resolved:
    all unarchived plans, not a name-ILIKE heuristic).

Index DDL is split into the next migration ``0204_staff_phase1_indexes``
because ``CREATE INDEX CONCURRENTLY`` cannot run inside the alembic
transactional wrapper.

Refs: requirements R2 (incl. residency_type), R3, R11, gap-analysis G2 + G8.

Revision ID: 0203
Revises: 0202
Create Date: 2026-05-31
"""

from __future__ import annotations

from alembic import op

revision: str = "0203"
down_revision: str = "0202"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Extend staff_members with the 23 employment + payroll columns.
    #    All ``ADD COLUMN IF NOT EXISTS`` so re-running is a no-op.
    # ------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE staff_members
            ADD COLUMN IF NOT EXISTS employment_start_date date,
            ADD COLUMN IF NOT EXISTS employment_end_date date,
            ADD COLUMN IF NOT EXISTS employment_type text NOT NULL DEFAULT 'permanent',
            ADD COLUMN IF NOT EXISTS standard_hours_per_week numeric(5,2),
            ADD COLUMN IF NOT EXISTS tax_code text,
            ADD COLUMN IF NOT EXISTS ird_number_encrypted bytea,
            ADD COLUMN IF NOT EXISTS student_loan boolean NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS kiwisaver_enrolled boolean NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS kiwisaver_employee_rate numeric(4,2),
            ADD COLUMN IF NOT EXISTS kiwisaver_employer_rate numeric(4,2) NOT NULL DEFAULT 3.00,
            ADD COLUMN IF NOT EXISTS bank_account_number_encrypted bytea,
            ADD COLUMN IF NOT EXISTS probation_end_date date,
            ADD COLUMN IF NOT EXISTS residency_type text NOT NULL DEFAULT 'citizen',
            ADD COLUMN IF NOT EXISTS visa_expiry_date date,
            ADD COLUMN IF NOT EXISTS self_service_clock_enabled boolean NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS on_file_photo_url text,
            ADD COLUMN IF NOT EXISTS emergency_contact_name text,
            ADD COLUMN IF NOT EXISTS emergency_contact_phone text,
            ADD COLUMN IF NOT EXISTS weekly_roster_email_enabled boolean NOT NULL DEFAULT true,
            ADD COLUMN IF NOT EXISTS weekly_roster_sms_enabled boolean NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS last_pay_review_date date,
            ADD COLUMN IF NOT EXISTS employment_agreement_upload_id uuid
        """
    )

    # ------------------------------------------------------------------
    # 2. CHECK constraints (drop+recreate so the migration is idempotent
    #    if we tweak the enum membership later).
    # ------------------------------------------------------------------
    op.execute("ALTER TABLE staff_members DROP CONSTRAINT IF EXISTS ck_staff_employment_type")
    op.execute(
        """
        ALTER TABLE staff_members ADD CONSTRAINT ck_staff_employment_type
            CHECK (employment_type IN ('permanent','casual','fixed_term'))
        """
    )

    op.execute("ALTER TABLE staff_members DROP CONSTRAINT IF EXISTS ck_staff_tax_code")
    op.execute(
        """
        ALTER TABLE staff_members ADD CONSTRAINT ck_staff_tax_code
            CHECK (tax_code IS NULL OR tax_code IN ('M','ME','S','SH','ST','SB','CAE','NSW','ND'))
        """
    )

    # G2 — residency_type drives visa_expiry_date visibility +
    #      compliance counter scope. NOT NULL with default 'citizen'.
    op.execute("ALTER TABLE staff_members DROP CONSTRAINT IF EXISTS ck_staff_residency_type")
    op.execute(
        """
        ALTER TABLE staff_members ADD CONSTRAINT ck_staff_residency_type
            CHECK (residency_type IN ('citizen','permanent_resident','work_visa','student_visa','other'))
        """
    )

    # ------------------------------------------------------------------
    # 3. staff_pay_rates — pay-rate audit ledger.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS staff_pay_rates (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id          uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            staff_id        uuid NOT NULL REFERENCES staff_members(id) ON DELETE CASCADE,
            hourly_rate     numeric(10,2),
            overtime_rate   numeric(10,2),
            effective_from  date NOT NULL,
            changed_by      uuid REFERENCES users(id),
            change_reason   text,
            created_at      timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("ALTER TABLE staff_pay_rates ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON staff_pay_rates")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON staff_pay_rates
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # 4. staff_roster_view_tokens — public read-only roster viewer tokens
    #    (G8 — ON DELETE CASCADE on both FKs so hard-deleting a staff or
    #    org sweeps tokens automatically; UNIQUE (staff_id, week_start)
    #    is the upsert key for ``get_or_create_viewer_token``).
    #    Inlined here per design §3.1.1 + P1-N3 — same migration as the
    #    pay-rates ledger so the schema is one atomic unit.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS staff_roster_view_tokens (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id      uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            staff_id    uuid NOT NULL REFERENCES staff_members(id) ON DELETE CASCADE,
            token       text NOT NULL,
            week_start  date NOT NULL,
            expires_at  timestamptz NOT NULL,
            created_at  timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_staff_roster_view_tokens_staff_week UNIQUE (staff_id, week_start)
        )
        """
    )
    op.execute("ALTER TABLE staff_roster_view_tokens ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON staff_roster_view_tokens")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON staff_roster_view_tokens
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # 5. module_registry inserts (idempotent ON CONFLICT (slug)).
    # ------------------------------------------------------------------
    op.execute(
        """
        INSERT INTO module_registry (
            id, slug, display_name, description, category, is_core,
            dependencies, incompatibilities, status,
            setup_question, setup_question_description
        )
        VALUES (
            gen_random_uuid(),
            'staff_management',
            'Staff Management',
            'Employee records, rosters, leave, time tracking, and hours approval.',
            'operations',
            false,
            '[]'::jsonb,
            '[]'::jsonb,
            'available',
            'Do you employ staff or contractors that you need to roster and pay?',
            'Manage employee records, rosters, leave balances, clock-in/out, and weekly hours approval — built to NZ employment law.'
        )
        ON CONFLICT (slug) DO NOTHING
        """
    )

    op.execute(
        """
        INSERT INTO module_registry (
            id, slug, display_name, description, category, is_core,
            dependencies, incompatibilities, status,
            setup_question, setup_question_description
        )
        VALUES (
            gen_random_uuid(),
            'payroll',
            'Payroll & Payslips',
            'Generate Wages-Protection-Act-compliant payslips, allowances, deductions, and termination payouts.',
            'operations',
            false,
            '["staff_management"]'::jsonb,
            '[]'::jsonb,
            'available',
            'Would you like to generate payslips for your staff inside this app?',
            'Produce payslips that meet the NZ Wages Protection Act + Holidays Act s130A, including leave balances, KiwiSaver, allowances, and termination payouts.'
        )
        ON CONFLICT (slug) DO NOTHING
        """
    )

    # ------------------------------------------------------------------
    # 6. Update unarchived subscription plans' ``enabled_modules`` JSONB
    #    so both new slugs ship enabled. Per-org disablement is the gate
    #    (P1-N2 — STAFF-001 resolved: every unarchived plan, not a
    #    name-ILIKE heuristic).
    # ------------------------------------------------------------------
    op.execute(
        """
        UPDATE subscription_plans
        SET enabled_modules = (
            SELECT jsonb_agg(DISTINCT m)
            FROM jsonb_array_elements_text(
                COALESCE(enabled_modules, '[]'::jsonb) || '["staff_management","payroll"]'::jsonb
            ) AS m
        )
        WHERE is_archived = false
        """
    )

    # ------------------------------------------------------------------
    # 7. feature_flags mirrors per implementation-completeness Rule 8.
    #
    #    P1-N1: real columns are (id, key, display_name [NOT NULL],
    #    description, category, access_level, dependencies, default_value,
    #    is_active, targeting_rules) — there is NO ``scope`` column and
    #    NO ``default_enabled`` column. Pattern matches alembic 0067.
    #
    #    P1-N14: default_value=true follows the policy set by migration
    #    0171_fix_feature_flag_defaults — module gate is the real lever;
    #    the flag is a passive mirror for the admin GUI.
    # ------------------------------------------------------------------
    op.execute(
        """
        INSERT INTO feature_flags (
            id, key, display_name, description, category,
            access_level, dependencies, default_value,
            is_active, targeting_rules, created_at, updated_at
        ) VALUES (
            gen_random_uuid(),
            'staff_management',
            'Staff Management',
            'Staff Management module — gates the tabbed staff record, pay rates, compliance counters, and roster delivery.',
            'operations',
            'all_users',
            '[]'::jsonb,
            true,
            true,
            '[]'::jsonb,
            now(),
            now()
        )
        ON CONFLICT (key) DO NOTHING
        """
    )

    op.execute(
        """
        INSERT INTO feature_flags (
            id, key, display_name, description, category,
            access_level, dependencies, default_value,
            is_active, targeting_rules, created_at, updated_at
        ) VALUES (
            gen_random_uuid(),
            'payroll',
            'Payroll & Payslips',
            'Payroll & Payslips module — gates payslip generation, allowances, KiwiSaver auto-calc, and termination payouts.',
            'operations',
            'all_users',
            '["staff_management"]'::jsonb,
            true,
            true,
            '[]'::jsonb,
            now(),
            now()
        )
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    # ------------------------------------------------------------------
    # Reverse order: feature_flag rows + module_registry rows + tables
    # + constraints + columns.  Subscription-plan enabled_modules is
    # left as-is — once the modules are out of the registry, the slug
    # is harmless residue inside the JSONB array.
    # ------------------------------------------------------------------
    op.execute("DELETE FROM feature_flags WHERE key IN ('staff_management','payroll')")
    op.execute("DELETE FROM module_registry WHERE slug IN ('staff_management','payroll')")

    op.execute("DROP TABLE IF EXISTS staff_roster_view_tokens")
    op.execute("DROP TABLE IF EXISTS staff_pay_rates")

    op.execute("ALTER TABLE staff_members DROP CONSTRAINT IF EXISTS ck_staff_residency_type")
    op.execute("ALTER TABLE staff_members DROP CONSTRAINT IF EXISTS ck_staff_tax_code")
    op.execute("ALTER TABLE staff_members DROP CONSTRAINT IF EXISTS ck_staff_employment_type")

    op.execute(
        """
        ALTER TABLE staff_members
            DROP COLUMN IF EXISTS employment_agreement_upload_id,
            DROP COLUMN IF EXISTS last_pay_review_date,
            DROP COLUMN IF EXISTS weekly_roster_sms_enabled,
            DROP COLUMN IF EXISTS weekly_roster_email_enabled,
            DROP COLUMN IF EXISTS emergency_contact_phone,
            DROP COLUMN IF EXISTS emergency_contact_name,
            DROP COLUMN IF EXISTS on_file_photo_url,
            DROP COLUMN IF EXISTS self_service_clock_enabled,
            DROP COLUMN IF EXISTS visa_expiry_date,
            DROP COLUMN IF EXISTS residency_type,
            DROP COLUMN IF EXISTS probation_end_date,
            DROP COLUMN IF EXISTS bank_account_number_encrypted,
            DROP COLUMN IF EXISTS kiwisaver_employer_rate,
            DROP COLUMN IF EXISTS kiwisaver_employee_rate,
            DROP COLUMN IF EXISTS kiwisaver_enrolled,
            DROP COLUMN IF EXISTS student_loan,
            DROP COLUMN IF EXISTS ird_number_encrypted,
            DROP COLUMN IF EXISTS tax_code,
            DROP COLUMN IF EXISTS standard_hours_per_week,
            DROP COLUMN IF EXISTS employment_type,
            DROP COLUMN IF EXISTS employment_end_date,
            DROP COLUMN IF EXISTS employment_start_date
        """
    )
