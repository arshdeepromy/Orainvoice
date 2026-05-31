"""Staff Management Phase 2 — leave engine schema.

Schema-additive migration that:
  - Creates four new tables (``leave_types``, ``leave_balances``,
    ``leave_requests``, ``leave_ledger``) with RLS + ``tenant_isolation``
    policies, CHECK constraints on enum-like text columns, and the
    ``confidential_visibility`` / ``requires_doctor_note`` flags
    needed for family-violence + sick-leave gating (D1, D2 back-ports).
  - Adds two columns:
      * ``staff_members.average_daily_pay_snapshot numeric(10,2)`` — the
        Phase-2 placeholder ADP figure refreshed nightly by the
        ``update_adp_snapshots`` task.
      * ``organisations.overtime_handling text`` (typed column, NOT a
        JSONB key — P2-N5) with CHECK enum
        ``('pay_cash','toil','employee_chooses')``.
  - Backfills **7 statutory leave_types per existing organisation**
    (cross-phase X2 fix — 6 statutory + 1 universally-seeded TOIL so
    Phase 3's overtime-toil flow can write into ``leave_ledger`` without
    FK violations even when the org hasn't enabled TOIL):
      ``annual``, ``sick``, ``bereavement``, ``family_violence``,
      ``public_holiday_alt``, ``unpaid``, ``toil``.
    Per-type flags applied at backfill time:
      * ``sick.requires_doctor_note = true``
      * ``family_violence.confidential_visibility = true``
  - Seeds zero-balance rows in ``leave_balances`` for every active staff
    × every active leave_type (cross-phase X2 — covers the new TOIL row
    too) with ``anniversary_date = staff.employment_start_date``.
  - Backfills the ``leave.fv_view`` permission into
    ``user_permission_overrides`` for every current ``org_admin`` user
    (R4.9). The ``ON CONFLICT (user_id, permission_key)`` clause leans on
    the existing ``uq_user_permission_overrides_user_perm`` constraint
    from migration 0023 — no pre-step needed (P2-N3).

Idempotent throughout — every CREATE / ALTER uses IF [NOT] EXISTS, and
the backfills use ``ON CONFLICT DO NOTHING``.

Index DDL is split into the next migration ``0206_leave_indexes`` because
``CREATE INDEX CONCURRENTLY`` cannot run inside the alembic transactional
wrapper (mirrors the 0203 → 0204 split).

Refs: requirements R3, R4.5, R4.6, R4.7, R4.9, R6, R10.2;
       design.md §3.1, §3.2, §4.4, §9.1.

Revision ID: 0205
Revises: 0204
Create Date: 2026-05-31
"""

from __future__ import annotations

from alembic import op

revision: str = "0205"
down_revision: str = "0204"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. leave_types — per-org leave type catalogue.
    #    is_statutory + display_order let the settings UI lock down the
    #    7 statutory types and order them consistently.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_types (
            id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id                   uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            code                     text NOT NULL,
            name                     text NOT NULL,
            is_paid                  boolean NOT NULL DEFAULT true,
            accrual_method           text NOT NULL,
            accrual_amount           numeric(8,2),
            accrual_unit             text NOT NULL DEFAULT 'hours',
            carry_over_max           numeric(8,2),
            is_statutory             boolean NOT NULL DEFAULT false,
            requires_doctor_note     boolean NOT NULL DEFAULT false,
            confidential_visibility  boolean NOT NULL DEFAULT false,
            active                   boolean NOT NULL DEFAULT true,
            display_order            int NOT NULL DEFAULT 0,
            created_at               timestamptz NOT NULL DEFAULT now(),
            updated_at               timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_leave_types_org_code UNIQUE (org_id, code)
        )
        """
    )
    # Drop+recreate CHECKs so the migration is idempotent if the enum
    # membership changes later.
    op.execute("ALTER TABLE leave_types DROP CONSTRAINT IF EXISTS ck_leave_types_accrual_method")
    op.execute(
        """
        ALTER TABLE leave_types ADD CONSTRAINT ck_leave_types_accrual_method
            CHECK (accrual_method IN ('anniversary','fixed_annual','per_period','unaccrued','event_based'))
        """
    )
    op.execute("ALTER TABLE leave_types DROP CONSTRAINT IF EXISTS ck_leave_types_accrual_unit")
    op.execute(
        """
        ALTER TABLE leave_types ADD CONSTRAINT ck_leave_types_accrual_unit
            CHECK (accrual_unit IN ('hours','days'))
        """
    )
    op.execute("ALTER TABLE leave_types ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON leave_types")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON leave_types
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # 2. leave_balances — per-staff × per-type rolling balance.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_balances (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id            uuid NOT NULL,
            staff_id          uuid NOT NULL REFERENCES staff_members(id) ON DELETE CASCADE,
            leave_type_id     uuid NOT NULL REFERENCES leave_types(id) ON DELETE RESTRICT,
            accrued_hours     numeric(8,2) NOT NULL DEFAULT 0,
            used_hours        numeric(8,2) NOT NULL DEFAULT 0,
            pending_hours     numeric(8,2) NOT NULL DEFAULT 0,
            anniversary_date  date,
            last_accrual_at   timestamptz,
            updated_at        timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_leave_balances_staff_type UNIQUE (staff_id, leave_type_id)
        )
        """
    )
    op.execute("ALTER TABLE leave_balances ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON leave_balances")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON leave_balances
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # 3. leave_requests — submission / approval state machine.
    #    relationship_to_subject + partial_day_start_time are nullable
    #    columns populated only for bereavement and partial-day cases
    #    respectively (design §4.3 step 3 + step 6).
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_requests (
            id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id                   uuid NOT NULL,
            staff_id                 uuid NOT NULL REFERENCES staff_members(id),
            leave_type_id            uuid NOT NULL REFERENCES leave_types(id),
            start_date               date NOT NULL,
            end_date                 date NOT NULL,
            hours_requested          numeric(6,2) NOT NULL,
            status                   text NOT NULL DEFAULT 'pending',
            reason                   text,
            relationship_to_subject  text,
            partial_day_start_time   time,
            attachment_upload_id     uuid,
            requested_by             uuid NOT NULL REFERENCES users(id),
            decided_by               uuid REFERENCES users(id),
            decided_at               timestamptz,
            decision_notes           text,
            created_at               timestamptz NOT NULL DEFAULT now(),
            updated_at               timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("ALTER TABLE leave_requests DROP CONSTRAINT IF EXISTS ck_leave_requests_status")
    op.execute(
        """
        ALTER TABLE leave_requests ADD CONSTRAINT ck_leave_requests_status
            CHECK (status IN ('pending','approved','rejected','cancelled'))
        """
    )
    op.execute("ALTER TABLE leave_requests DROP CONSTRAINT IF EXISTS ck_leave_requests_relationship")
    op.execute(
        """
        ALTER TABLE leave_requests ADD CONSTRAINT ck_leave_requests_relationship
            CHECK (relationship_to_subject IS NULL OR relationship_to_subject IN ('close_family','other'))
        """
    )
    op.execute("ALTER TABLE leave_requests ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON leave_requests")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON leave_requests
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # 4. leave_ledger — append-only accrual + adjustment history.
    #    'toil_accrual' is included in the reason enum so Phase 3's
    #    overtime-toil writer doesn't need a follow-up enum amendment
    #    (cross-phase X3).
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_ledger (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id         uuid NOT NULL,
            staff_id       uuid NOT NULL,
            leave_type_id  uuid NOT NULL,
            delta_hours    numeric(8,2) NOT NULL,
            reason         text NOT NULL,
            request_id     uuid REFERENCES leave_requests(id),
            occurred_at    date NOT NULL,
            created_by     uuid REFERENCES users(id),
            created_at     timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("ALTER TABLE leave_ledger DROP CONSTRAINT IF EXISTS ck_leave_ledger_reason")
    op.execute(
        """
        ALTER TABLE leave_ledger ADD CONSTRAINT ck_leave_ledger_reason
            CHECK (reason IN (
                'accrual',
                'request_approved',
                'request_cancelled_after_approval',
                'manual_adjustment',
                'opening_balance',
                'termination_payout',
                'public_holiday_extension',
                'public_holiday_worked',
                'pay_run_payout',
                'toil_accrual'
            ))
        """
    )
    op.execute("ALTER TABLE leave_ledger ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON leave_ledger")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON leave_ledger
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # 5. staff_members.average_daily_pay_snapshot — Phase-2 placeholder
    #    refreshed nightly; Phase 4 swaps in real payslip-derived values.
    # ------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE staff_members
            ADD COLUMN IF NOT EXISTS average_daily_pay_snapshot numeric(10,2)
        """
    )

    # ------------------------------------------------------------------
    # 6. organisations.overtime_handling — typed column (P2-N5: NOT a
    #    JSONB key). Phase 4's _org_setting('overtime_handling', ...)
    #    helper resolves directly from this column.
    # ------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE organisations
            ADD COLUMN IF NOT EXISTS overtime_handling text NOT NULL DEFAULT 'pay_cash'
        """
    )
    op.execute("ALTER TABLE organisations DROP CONSTRAINT IF EXISTS ck_org_overtime_handling")
    op.execute(
        """
        ALTER TABLE organisations ADD CONSTRAINT ck_org_overtime_handling
            CHECK (overtime_handling IN ('pay_cash','toil','employee_chooses'))
        """
    )

    # ------------------------------------------------------------------
    # 7. Statutory backfill — 7 leave_types per org (cross-phase X2:
    #    6 statutory + 1 universally-seeded TOIL).
    #
    #    Per-type flags applied here:
    #      * sick.requires_doctor_note    = true   (D1 back-port)
    #      * family_violence.confidential_visibility = true (D2 back-port)
    #
    #    is_statutory:
    #      * true for the 6 NZ statutory types.
    #      * false for TOIL — it's a contractual choice, not a statute,
    #        but ship a row for every org so Phase 3's overtime-toil
    #        write doesn't FK-violate when the org hasn't yet picked
    #        TOIL as its overtime_handling mode.
    # ------------------------------------------------------------------
    op.execute(
        """
        INSERT INTO leave_types (
            id, org_id, code, name, is_paid, accrual_method, accrual_amount, accrual_unit,
            carry_over_max, is_statutory, requires_doctor_note, confidential_visibility,
            active, display_order
        )
        SELECT
            gen_random_uuid(),
            o.id,
            t.code,
            t.name,
            t.is_paid,
            t.accrual_method,
            t.accrual_amount,
            t.accrual_unit,
            t.carry_over_max,
            t.is_statutory,
            t.requires_doctor_note,
            t.confidential_visibility,
            true,
            t.display_order
        FROM organisations o
        CROSS JOIN (VALUES
            ('annual',             'Annual leave',         true,  'anniversary',  NULL,  'hours', NULL,  true,  false, false, 1),
            ('sick',               'Sick leave',           true,  'per_period',   80.0,  'hours', 160.0, true,  true,  false, 2),
            ('bereavement',        'Bereavement leave',    true,  'event_based',  NULL,  'days',  NULL,  true,  false, false, 3),
            ('family_violence',    'Family violence leave',true,  'per_period',   80.0,  'hours', 80.0,  true,  false, true,  4),
            ('public_holiday_alt', 'Alternative holiday',  true,  'event_based',  NULL,  'days',  NULL,  true,  false, false, 5),
            ('unpaid',             'Unpaid leave',         false, 'unaccrued',    NULL,  'hours', NULL,  true,  false, false, 6),
            ('toil',               'Time off in lieu',     true,  'event_based',  NULL,  'hours', NULL,  false, false, false, 7)
        ) AS t(
            code, name, is_paid, accrual_method, accrual_amount, accrual_unit, carry_over_max,
            is_statutory, requires_doctor_note, confidential_visibility, display_order
        )
        ON CONFLICT (org_id, code) DO NOTHING
        """
    )

    # ------------------------------------------------------------------
    # 8. Seed leave_balances for every active staff × active leave_type
    #    in their org. anniversary_date defaults to the staff member's
    #    employment_start_date so the accrual engine has a stable
    #    reference point from day one.
    # ------------------------------------------------------------------
    op.execute(
        """
        INSERT INTO leave_balances (
            id, org_id, staff_id, leave_type_id, accrued_hours, used_hours, pending_hours,
            anniversary_date
        )
        SELECT
            gen_random_uuid(),
            s.org_id,
            s.id,
            lt.id,
            0,
            0,
            0,
            s.employment_start_date
        FROM staff_members s
        JOIN leave_types lt
            ON lt.org_id = s.org_id
           AND lt.active = true
        WHERE s.is_active = true
        ON CONFLICT (staff_id, leave_type_id) DO NOTHING
        """
    )

    # ------------------------------------------------------------------
    # 9. Family-violence permission backfill (R4.9).
    #
    #    One ``leave.fv_view`` override row per existing org_admin so
    #    today's admins can keep approving family-violence requests
    #    after Phase 2 ships. Org owners are expected to review the
    #    grant within 30 days (Settings → People → Permissions banner).
    #
    #    The existing ``uq_user_permission_overrides_user_perm`` from
    #    migration 0023 covers the ON CONFLICT — no pre-step required
    #    (P2-N3). granted_by NULL signals "system backfill".
    # ------------------------------------------------------------------
    op.execute(
        """
        INSERT INTO user_permission_overrides (id, user_id, permission_key, is_granted, granted_by, created_at)
        SELECT gen_random_uuid(), u.id, 'leave.fv_view', true, NULL, now()
        FROM users u
        WHERE u.role = 'org_admin'
        ON CONFLICT (user_id, permission_key) DO NOTHING
        """
    )


def downgrade() -> None:
    # ------------------------------------------------------------------
    # Reverse order: backfill data → tables → columns → constraints.
    # ------------------------------------------------------------------

    # 9. FV-permission backfill rows.
    op.execute(
        """
        DELETE FROM user_permission_overrides
        WHERE permission_key = 'leave.fv_view'
        """
    )

    # 4. leave_ledger references leave_requests; drop ledger first so
    #    the requests table can go cleanly.
    op.execute("DROP TABLE IF EXISTS leave_ledger")
    # 3. leave_requests references leave_types and staff_members.
    op.execute("DROP TABLE IF EXISTS leave_requests")
    # 2. leave_balances references leave_types (RESTRICT) — must drop
    #    before leave_types.
    op.execute("DROP TABLE IF EXISTS leave_balances")
    # 1. leave_types last.
    op.execute("DROP TABLE IF EXISTS leave_types")

    # 6. organisations.overtime_handling (drop constraint + column).
    op.execute("ALTER TABLE organisations DROP CONSTRAINT IF EXISTS ck_org_overtime_handling")
    op.execute("ALTER TABLE organisations DROP COLUMN IF EXISTS overtime_handling")

    # 5. staff_members.average_daily_pay_snapshot.
    op.execute(
        """
        ALTER TABLE staff_members
            DROP COLUMN IF EXISTS average_daily_pay_snapshot
        """
    )
