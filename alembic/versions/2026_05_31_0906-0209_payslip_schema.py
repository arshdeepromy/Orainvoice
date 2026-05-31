"""Staff Management Phase 4 — payslip + allowances + recurring-allowance schema.

Schema-additive migration that:

  - **Creates seven new tables** for the payroll surface (design §3.1):
      * ``pay_periods`` — per-org pay-period state machine
        (``open``/``finalised``/``paid``). ``UNIQUE (org_id, start_date)``
        backs `roll_pay_periods` idempotency (R1.5).
      * ``allowance_types`` — per-org allowance catalogue with the
        three documented units (``shift``/``period``/``km``). Seeded
        with 6 default rows per existing org (R2.3).
      * ``payslips`` — core payslip row with separate hour bands for
        ordinary, overtime, and **public-holiday** (G2). ``pdf_file_key``
        is a path-style ``text`` column matching the
        ``invoice_attachments`` / ``job_card_attachments`` convention
        (N3 — NOT a UUID FK). ``UNIQUE (staff_id, pay_period_id)``
        prevents duplicate drafts per staff per period
        (P4-N28). ``gross_pay`` and ``net_pay`` are ``NOT NULL DEFAULT
        0`` so a draft row can be inserted before
        ``compute_payslip`` runs (P4-N29).
      * ``payslip_allowances`` — per-line allowance with
        ``quantity numeric(10,2) NOT NULL DEFAULT 1`` and
        ``unit text NOT NULL DEFAULT 'period'`` (G18). The unit is
        COPIED from ``allowance_types.unit`` at attach time so a
        retroactive edit to the catalogue doesn't change the
        interpretation of an already-finalised payslip line.
      * ``payslip_deductions`` — typed deductions (PAYE, ACC,
        KiwiSaver employee/employer split, student loan, child support,
        voluntary).
      * ``payslip_reimbursements`` — tax-free, never subtracted from
        gross.
      * ``payslip_leave_lines`` — Holidays Act s130A "leave taken in
        this period" + remaining-balance-after rows.
      * ``staff_recurring_allowances`` (G4) — per-staff recurring
        allowance rules. ``ON DELETE CASCADE`` from ``staff_members``
        (the recurring rule dies with the staff record), but
        ``ON DELETE RESTRICT`` from ``allowance_types`` because
        deactivating an allowance type while staff still depend on it
        is a user error that should surface as an FK violation rather
        than a silent dangling rule.

  - **Adds three columns to ``organisations``** for the pay-period
    rolling logic (G5):
      * ``pay_period_cadence text NOT NULL DEFAULT 'fortnightly'`` with
        a CHECK enum of ``('weekly','fortnightly','monthly')``.
      * ``pay_period_anchor_day int NOT NULL DEFAULT 1`` — day-of-week
        for weekly/fortnightly, day-of-month for monthly.
      * ``pay_date_offset_days int NOT NULL DEFAULT 3`` — days after
        ``end_date`` when payment goes out (rolls forward to the next
        weekday for Sat/Sun).

  - **Creates a partial UNIQUE index on ``staff_members.user_id``**
    (N1 + N6) — ``ux_staff_members_user_id ON staff_members (user_id)
    WHERE user_id IS NOT NULL``. Required for the G9 self-service
    payslip endpoints to deterministically resolve a logged-in user to
    their staff row. Partial because ``user_id`` is nullable for
    not-yet-linked staff records.

  - **Seeds 6 default allowance types per existing org** (R2.3):
    ``meal_allowance``, ``tool_allowance``, ``vehicle_allowance``,
    ``on_call_allowance``, ``travel_per_km``, ``uniform_laundering``.
    These are not statutory; admins can deactivate or rename them.
    The seed uses ``ON CONFLICT (org_id, code) DO NOTHING`` so it's
    safe to re-run.

  - **RLS + ``tenant_isolation`` policies** on every new table that
    has an ``org_id`` column. Pattern matches the rest of the codebase
    (``current_setting('app.current_org_id', true)::uuid``). The four
    payslip-line tables (``payslip_allowances``,
    ``payslip_deductions``, ``payslip_reimbursements``,
    ``payslip_leave_lines``) don't carry an ``org_id`` directly — they
    inherit tenant isolation through the ``payslip_id`` FK and the RLS
    policy on ``payslips``.

Idempotent throughout — every CREATE / ALTER uses IF [NOT] EXISTS,
every CHECK uses ``DROP CONSTRAINT IF EXISTS`` then ``ADD CONSTRAINT``,
every policy uses ``DROP POLICY IF EXISTS`` then ``CREATE POLICY``,
every seed uses ``ON CONFLICT DO NOTHING``.

Index DDL is split into the next migration ``0210_payslip_indexes``
because ``CREATE INDEX CONCURRENTLY`` cannot run inside the alembic
transactional wrapper (mirrors the 0205 → 0206 + 0207 → 0208 splits).
The ONE exception is ``ux_staff_members_user_id`` which is created
inline (non-CONCURRENTLY) in this migration because it's a UNIQUE
constraint required to be live before the G9 endpoints come online,
and the underlying ``staff_members`` row count is small enough that a
brief ``ACCESS EXCLUSIVE`` lock is acceptable.

Refs: requirements R1, R1a, R2, R3, R4, R7, R8a; tasks A1; design.md
       §3.1, §3.2, §4.2.

Revision ID: 0209
Revises: 0208
Create Date: 2026-05-31
"""

from __future__ import annotations

from alembic import op

revision: str = "0209"
down_revision: str = "0208"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


# ---------------------------------------------------------------------------
# Default allowance-type seed payload — kept as a module constant so the list
# is documented in one place. Each tuple is (code, name, taxable, default_amount,
# unit, display_order). All defaults are non-statutory; admins are free to
# rename, deactivate, or change amounts.
# ---------------------------------------------------------------------------
_DEFAULT_ALLOWANCE_TYPES: list[tuple[str, str, bool, str, str, int]] = [
    ("meal_allowance",     "Meal allowance",      True,  "20.00", "shift",  10),
    ("tool_allowance",     "Tool allowance",      True,  "10.00", "period", 20),
    ("vehicle_allowance",  "Vehicle allowance",   True,  "50.00", "period", 30),
    ("on_call_allowance",  "On-call allowance",   True,  "25.00", "shift",  40),
    ("travel_per_km",      "Travel per km",       False, "0.83",  "km",     50),
    ("uniform_laundering", "Uniform laundering",  False, "5.00",  "period", 60),
]


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. pay_periods — per-org pay-period state machine.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pay_periods (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id        uuid NOT NULL,
            start_date    date NOT NULL,
            end_date      date NOT NULL,
            pay_date      date NOT NULL,
            status        text NOT NULL DEFAULT 'open',
            created_at    timestamptz NOT NULL DEFAULT now(),
            finalised_at  timestamptz,
            paid_at       timestamptz,
            CONSTRAINT uq_pay_periods_org_start UNIQUE (org_id, start_date)
        )
        """
    )
    op.execute(
        "ALTER TABLE pay_periods DROP CONSTRAINT IF EXISTS ck_pay_periods_status"
    )
    op.execute(
        """
        ALTER TABLE pay_periods ADD CONSTRAINT ck_pay_periods_status
            CHECK (status IN ('open','finalised','paid'))
        """
    )
    op.execute("ALTER TABLE pay_periods ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON pay_periods")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON pay_periods
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # 2. allowance_types — per-org allowance catalogue.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS allowance_types (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id          uuid NOT NULL,
            code            text NOT NULL,
            name            text NOT NULL,
            taxable         boolean NOT NULL DEFAULT true,
            default_amount  numeric(10,2),
            unit            text NOT NULL DEFAULT 'shift',
            active          boolean NOT NULL DEFAULT true,
            display_order   int NOT NULL DEFAULT 0,
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_allowance_types_org_code UNIQUE (org_id, code)
        )
        """
    )
    op.execute(
        "ALTER TABLE allowance_types DROP CONSTRAINT IF EXISTS ck_allowance_types_unit"
    )
    op.execute(
        """
        ALTER TABLE allowance_types ADD CONSTRAINT ck_allowance_types_unit
            CHECK (unit IN ('shift','period','km'))
        """
    )
    op.execute("ALTER TABLE allowance_types ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON allowance_types")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON allowance_types
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # 3. payslips — core payslip row.
    #    public_holiday_rate (G2), pdf_file_key (N3), UNIQUE (staff_id,
    #    pay_period_id) (P4-N28), gross_pay/net_pay NOT NULL DEFAULT 0
    #    (P4-N29).
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS payslips (
            id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id                uuid NOT NULL,
            staff_id              uuid NOT NULL REFERENCES staff_members(id),
            pay_period_id         uuid NOT NULL REFERENCES pay_periods(id),
            status                text NOT NULL DEFAULT 'draft',
            ordinary_hours        numeric(8,2) NOT NULL DEFAULT 0,
            overtime_hours        numeric(8,2) NOT NULL DEFAULT 0,
            public_holiday_hours  numeric(8,2) NOT NULL DEFAULT 0,
            ordinary_rate         numeric(10,2),
            overtime_rate         numeric(10,2),
            public_holiday_rate   numeric(10,2),
            gross_pay             numeric(12,2) NOT NULL DEFAULT 0,
            gross_ytd             numeric(12,2) NOT NULL DEFAULT 0,
            net_pay               numeric(12,2) NOT NULL DEFAULT 0,
            pdf_file_key          text,
            emailed_at            timestamptz,
            finalised_at          timestamptz,
            notes                 text,
            created_at            timestamptz NOT NULL DEFAULT now(),
            updated_at            timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_payslips_staff_period UNIQUE (staff_id, pay_period_id)
        )
        """
    )
    op.execute(
        "ALTER TABLE payslips DROP CONSTRAINT IF EXISTS ck_payslips_status"
    )
    op.execute(
        """
        ALTER TABLE payslips ADD CONSTRAINT ck_payslips_status
            CHECK (status IN ('draft','finalised','voided'))
        """
    )
    op.execute("ALTER TABLE payslips ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON payslips")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON payslips
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # 4. payslip_allowances — line items (G18 quantity + unit).
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS payslip_allowances (
            id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            payslip_id          uuid NOT NULL REFERENCES payslips(id) ON DELETE CASCADE,
            allowance_type_id   uuid REFERENCES allowance_types(id),
            label               text NOT NULL,
            quantity            numeric(10,2) NOT NULL DEFAULT 1,
            unit                text NOT NULL DEFAULT 'period',
            amount              numeric(12,2) NOT NULL,
            taxable             boolean NOT NULL DEFAULT true
        )
        """
    )
    op.execute(
        "ALTER TABLE payslip_allowances DROP CONSTRAINT IF EXISTS ck_payslip_allowances_unit"
    )
    op.execute(
        """
        ALTER TABLE payslip_allowances ADD CONSTRAINT ck_payslip_allowances_unit
            CHECK (unit IN ('shift','period','km'))
        """
    )
    op.execute("ALTER TABLE payslip_allowances ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON payslip_allowances")
    # Tenant isolation via the parent payslip — no org_id on this table.
    op.execute(
        """
        CREATE POLICY tenant_isolation ON payslip_allowances
            USING (
                payslip_id IN (
                    SELECT id FROM payslips
                    WHERE org_id = current_setting('app.current_org_id', true)::uuid
                )
            )
            WITH CHECK (
                payslip_id IN (
                    SELECT id FROM payslips
                    WHERE org_id = current_setting('app.current_org_id', true)::uuid
                )
            )
        """
    )

    # ------------------------------------------------------------------
    # 5. payslip_deductions — typed deductions.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS payslip_deductions (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            payslip_id  uuid NOT NULL REFERENCES payslips(id) ON DELETE CASCADE,
            kind        text NOT NULL,
            label       text NOT NULL,
            amount      numeric(12,2) NOT NULL
        )
        """
    )
    op.execute(
        "ALTER TABLE payslip_deductions DROP CONSTRAINT IF EXISTS ck_payslip_deductions_kind"
    )
    op.execute(
        """
        ALTER TABLE payslip_deductions ADD CONSTRAINT ck_payslip_deductions_kind
            CHECK (kind IN (
                'paye','acc_levy','kiwisaver_employee','kiwisaver_employer',
                'student_loan','child_support','voluntary'
            ))
        """
    )
    op.execute("ALTER TABLE payslip_deductions ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON payslip_deductions")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON payslip_deductions
            USING (
                payslip_id IN (
                    SELECT id FROM payslips
                    WHERE org_id = current_setting('app.current_org_id', true)::uuid
                )
            )
            WITH CHECK (
                payslip_id IN (
                    SELECT id FROM payslips
                    WHERE org_id = current_setting('app.current_org_id', true)::uuid
                )
            )
        """
    )

    # ------------------------------------------------------------------
    # 6. payslip_reimbursements — tax-free, separate from wages.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS payslip_reimbursements (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            payslip_id  uuid NOT NULL REFERENCES payslips(id) ON DELETE CASCADE,
            label       text NOT NULL,
            amount      numeric(12,2) NOT NULL
        )
        """
    )
    op.execute("ALTER TABLE payslip_reimbursements ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON payslip_reimbursements")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON payslip_reimbursements
            USING (
                payslip_id IN (
                    SELECT id FROM payslips
                    WHERE org_id = current_setting('app.current_org_id', true)::uuid
                )
            )
            WITH CHECK (
                payslip_id IN (
                    SELECT id FROM payslips
                    WHERE org_id = current_setting('app.current_org_id', true)::uuid
                )
            )
        """
    )

    # ------------------------------------------------------------------
    # 7. payslip_leave_lines — Holidays Act s130A "leave taken in this
    #    period" + remaining-balance-after rows.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS payslip_leave_lines (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            payslip_id      uuid NOT NULL REFERENCES payslips(id) ON DELETE CASCADE,
            leave_type_id   uuid NOT NULL REFERENCES leave_types(id),
            hours           numeric(8,2) NOT NULL,
            rate            numeric(10,2) NOT NULL,
            amount          numeric(12,2) NOT NULL,
            balance_after   numeric(8,2) NOT NULL
        )
        """
    )
    op.execute("ALTER TABLE payslip_leave_lines ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON payslip_leave_lines")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON payslip_leave_lines
            USING (
                payslip_id IN (
                    SELECT id FROM payslips
                    WHERE org_id = current_setting('app.current_org_id', true)::uuid
                )
            )
            WITH CHECK (
                payslip_id IN (
                    SELECT id FROM payslips
                    WHERE org_id = current_setting('app.current_org_id', true)::uuid
                )
            )
        """
    )

    # ------------------------------------------------------------------
    # 8. staff_recurring_allowances (G4) — per-staff recurring rules.
    #    ON DELETE CASCADE on staff_members (rule dies with the staff).
    #    ON DELETE RESTRICT on allowance_types (deactivating a type
    #    while staff still depend on it should fail loudly).
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS staff_recurring_allowances (
            id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id              uuid NOT NULL,
            staff_id            uuid NOT NULL REFERENCES staff_members(id) ON DELETE CASCADE,
            allowance_type_id   uuid NOT NULL REFERENCES allowance_types(id) ON DELETE RESTRICT,
            amount              numeric(10,2),
            quantity            numeric(10,2),
            active              boolean NOT NULL DEFAULT true,
            notes               text,
            created_at          timestamptz NOT NULL DEFAULT now(),
            updated_at          timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_staff_recurring_allowances_staff_type UNIQUE (staff_id, allowance_type_id)
        )
        """
    )
    op.execute("ALTER TABLE staff_recurring_allowances ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON staff_recurring_allowances")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON staff_recurring_allowances
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # 9. organisations.pay_period_cadence + pay_period_anchor_day +
    #    pay_date_offset_days (G5).
    # ------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE organisations
            ADD COLUMN IF NOT EXISTS pay_period_cadence text NOT NULL DEFAULT 'fortnightly'
        """
    )
    op.execute(
        "ALTER TABLE organisations DROP CONSTRAINT IF EXISTS ck_org_pay_period_cadence"
    )
    op.execute(
        """
        ALTER TABLE organisations ADD CONSTRAINT ck_org_pay_period_cadence
            CHECK (pay_period_cadence IN ('weekly','fortnightly','monthly'))
        """
    )
    op.execute(
        """
        ALTER TABLE organisations
            ADD COLUMN IF NOT EXISTS pay_period_anchor_day int NOT NULL DEFAULT 1
        """
    )
    op.execute(
        """
        ALTER TABLE organisations
            ADD COLUMN IF NOT EXISTS pay_date_offset_days int NOT NULL DEFAULT 3
        """
    )

    # ------------------------------------------------------------------
    # 10. staff_members.user_id partial UNIQUE index (N1 + N6).
    #     Required for the G9 self-service payslip endpoints to
    #     deterministically resolve a logged-in user to their staff
    #     row. Inline (non-CONCURRENTLY) because (a) it's a UNIQUE
    #     constraint that needs to be live before the G9 endpoints
    #     ship, and (b) staff_members is small enough that a brief
    #     ACCESS EXCLUSIVE lock is acceptable.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_staff_members_user_id
            ON staff_members (user_id)
            WHERE user_id IS NOT NULL
        """
    )

    # ------------------------------------------------------------------
    # 11. Seed 6 default allowance_types per existing org (R2.3).
    #     ON CONFLICT (org_id, code) DO NOTHING makes this safe to
    #     re-run after a partial migration.
    # ------------------------------------------------------------------
    for code, name, taxable, default_amount, unit, display_order in _DEFAULT_ALLOWANCE_TYPES:
        op.execute(
            f"""
            INSERT INTO allowance_types (
                org_id, code, name, taxable, default_amount, unit, display_order
            )
            SELECT
                organisations.id,
                '{code}',
                '{name}',
                {str(taxable).lower()},
                {default_amount},
                '{unit}',
                {display_order}
            FROM organisations
            ON CONFLICT (org_id, code) DO NOTHING
            """
        )


def downgrade() -> None:
    # ------------------------------------------------------------------
    # Reverse order: drop the partial index → drop org columns → drop
    # tables (child-first to respect FK + CASCADE rules). PDF files in
    # the upload-base folder are intentionally left in place — the
    # downgrade is loss-bounded to the payslip rows themselves; the
    # underlying encrypted PDFs remain on disk for the documented
    # 6-year Holidays Act s81 retention.
    # ------------------------------------------------------------------

    # Partial UNIQUE index on staff_members.user_id.
    op.execute("DROP INDEX IF EXISTS ux_staff_members_user_id")

    # organisations columns added in this migration.
    op.execute("ALTER TABLE organisations DROP CONSTRAINT IF EXISTS ck_org_pay_period_cadence")
    op.execute("ALTER TABLE organisations DROP COLUMN IF EXISTS pay_date_offset_days")
    op.execute("ALTER TABLE organisations DROP COLUMN IF EXISTS pay_period_anchor_day")
    op.execute("ALTER TABLE organisations DROP COLUMN IF EXISTS pay_period_cadence")

    # New tables — drop child-first to respect FK + CASCADE rules.
    op.execute("DROP TABLE IF EXISTS staff_recurring_allowances")
    op.execute("DROP TABLE IF EXISTS payslip_leave_lines")
    op.execute("DROP TABLE IF EXISTS payslip_reimbursements")
    op.execute("DROP TABLE IF EXISTS payslip_deductions")
    op.execute("DROP TABLE IF EXISTS payslip_allowances")
    op.execute("DROP TABLE IF EXISTS payslips")
    op.execute("DROP TABLE IF EXISTS allowance_types")
    op.execute("DROP TABLE IF EXISTS pay_periods")
