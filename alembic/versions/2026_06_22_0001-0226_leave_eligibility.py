"""Leave balances & eligibility — eligibility-notes table + holiday-pay-method column.

Adds the schema gaps for the Leave Balances & Eligibility feature (a gaps-only
build on top of the existing leave engine):

  1. ``staff_members.holiday_pay_method`` — a ``text NOT NULL DEFAULT 'accrued'``
     column with a CHECK restricting the value domain to
     ``('accrued','casual_payg')`` (R11.6 single-active-pay-method invariant).
     Casual staff are backfilled to ``'casual_payg'``.
  2. ``leave_eligibility_notes`` — a lightweight, append-only vesting record +
     Eligibility_Note store, org-scoped with the standard ``tenant_isolation``
     RLS policy. ``UNIQUE(staff_id, leave_type_id)`` enforces one onset note ever
     (R12.4 / R13.1) and underpins notification de-dup.

This is an ordinary transactional, fully idempotent migration — every statement
carries ``IF NOT EXISTS`` / ``IF EXISTS`` / ``information_schema`` guards so a
re-run is a safe no-op. No ``CONCURRENTLY`` DDL here (the performance indexes
live in the separate revision ``0227`` because mixing ``CONCURRENTLY`` with
transactional DDL is a banned pattern). RLS posture mirrors migration ``0224``:
``ENABLE`` (not FORCE) + a ``tenant_isolation`` policy keyed on
``current_setting('app.current_org_id', true)::uuid``.

Refs: requirements 6.6, 11.1, 11.6, 13.1, 13.4, 16.6.

Revision ID: 0226
Revises: 0225
Create Date: 2026-06-22
"""

from __future__ import annotations

import logging

from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

revision: str = "0226"
down_revision: str = "0225"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # --- Step 1: staff_members.holiday_pay_method column (additive) ----------
    # ADD COLUMN ... IF NOT EXISTS with a constant default is a fast metadata
    # change on Postgres 11+; safe inside the transaction.
    op.execute(
        "ALTER TABLE staff_members "
        "ADD COLUMN IF NOT EXISTS holiday_pay_method text NOT NULL DEFAULT 'accrued'"
    )
    # CHECK constraint, guarded by information_schema so the migration is
    # re-runnable (ADD CONSTRAINT has no IF NOT EXISTS form).
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_staff_holiday_pay_method'
                  AND conrelid = 'staff_members'::regclass
            ) THEN
                ALTER TABLE staff_members
                    ADD CONSTRAINT ck_staff_holiday_pay_method
                    CHECK (holiday_pay_method IN ('accrued', 'casual_payg'));
            END IF;
        END $$;
        """
    )

    # --- Step 2: leave_eligibility_notes table (new, empty) -----------------
    # PK / FK / UNIQUE indexes are declared inline at CREATE TABLE time — the
    # table is brand-new and empty so they take no meaningful lock. No
    # performance index belongs here (those are in 0227, CONCURRENTLY).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_eligibility_notes (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id            uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            staff_id          uuid NOT NULL REFERENCES staff_members(id) ON DELETE CASCADE,
            leave_type_id     uuid NOT NULL REFERENCES leave_types(id)   ON DELETE RESTRICT,
            rule_set_version  text NOT NULL,
            milestone_key     text NOT NULL,
            hours_test_met    boolean NULL,
            condition_text    text NOT NULL,
            vested_on         date NOT NULL,
            created_at        timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_leave_eligibility_notes_staff_type UNIQUE (staff_id, leave_type_id)
        )
        """
    )
    op.execute("ALTER TABLE leave_eligibility_notes ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON leave_eligibility_notes")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON leave_eligibility_notes
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # --- Step 3: backfill casual staff to casual_payg (idempotent) ----------
    op.execute(
        "UPDATE staff_members SET holiday_pay_method = 'casual_payg' "
        "WHERE employment_type = 'casual' AND holiday_pay_method <> 'casual_payg'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS leave_eligibility_notes")
    op.execute(
        "ALTER TABLE staff_members DROP CONSTRAINT IF EXISTS ck_staff_holiday_pay_method"
    )
    op.execute("ALTER TABLE staff_members DROP COLUMN IF EXISTS holiday_pay_method")
