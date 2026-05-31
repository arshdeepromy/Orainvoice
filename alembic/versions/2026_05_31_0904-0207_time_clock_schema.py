"""Staff Management Phase 3 — time-clock + scheduling-ops schema.

Schema-additive migration that:

  - **Adds three geofence columns to ``branches``** (``lat``, ``lng``,
    ``geofence_radius_metres``) so the self-service clock-in geofence
    policy in design §R4 has a per-branch anchor. The radius column is
    backfilled once from each org's
    ``clock_in_policy.branch_radius_metres`` (G17) so existing branches
    inherit whatever the org admin set in the policy block, falling back
    to 200m when no policy exists.
  - **Creates six new tables** for the time-clock + scheduling-ops
    surface (design §3.1):
      * ``time_clock_entries`` — kiosk / self-service / admin-manual
        in/out events. Includes a ``flags jsonb`` column (G10) for
        ``flagged_for_review`` markers (NOT named ``metadata`` —
        SQLAlchemy ``DeclarativeBase`` reserves that attribute name and
        a column literal called ``metadata`` raises
        ``InvalidRequestError`` at startup — see P3-N3 + tasks A1).
        CHECK constraints enforce the 4-value ``source`` enum and
        require ``clock_in_photo_url`` whenever ``source = 'kiosk'``.
      * ``break_records`` — per-entry break log; ``ON DELETE CASCADE``
        when the parent clock entry is hard-deleted.
      * ``timesheet_approvals`` — week-level approval state machine.
        ``status`` enum includes ``'edited_after_approval'`` (G16) so
        admin manual edits inside an already-approved week can flip the
        row without losing its approval lineage. ``UNIQUE (staff_id,
        week_start)`` because a staff member has at most one approval
        row per week.
      * ``overtime_requests`` — pre-approval request flow. 3-state
        machine (``pending``, ``approved``, ``rejected``).
      * ``shift_swap_requests`` — 5-state machine including the new
        ``'awaiting_manager'`` state (G8) needed when the org's
        ``clock_in_policy.shift_swap_requires_manager_approval`` toggle
        is on.
      * ``shift_cover_requests`` — open-broadcast cover model with a
        4-state machine (``open``, ``accepted``, ``cancelled``,
        ``expired``).
  - **Adds ``clock_in_policy jsonb`` to ``organisations``** with the
    documented default block (design §3.1). The block includes
    ``shift_swap_requires_manager_approval`` (G8) and
    ``branch_radius_metres`` (G17) — both consumed elsewhere in this
    migration's branch backfill and at runtime by the swap workflow.
  - **Adds ``overtime_policy jsonb`` to ``organisations``** (G1) with
    defaults ``{ weekly_threshold_minutes: 2400, daily_threshold_minutes:
    480, require_pre_approval: false }``. Phase 3's
    ``approvals.compute_week_totals`` reads this column to split
    ordinary vs overtime minutes.
  - **Defensively re-asserts the ``organisations.overtime_handling``
    typed column** that Phase 2's ``0205_leave_schema`` already added
    (P3-N4). This is a belt-and-braces guard: if 0205 ever gets
    re-ordered or rolled back independently, Phase 3's read paths still
    work. ``IF NOT EXISTS`` makes the re-assertion a no-op on the
    happy path.
  - **RLS + ``tenant_isolation`` policies** on every new table. Pattern
    matches the rest of the codebase — ``ENABLE ROW LEVEL SECURITY``
    then ``DROP POLICY IF EXISTS`` then ``CREATE POLICY`` using
    ``current_setting('app.current_org_id', true)::uuid``.

Idempotent throughout — every CREATE / ALTER uses IF [NOT] EXISTS, every
CHECK uses ``DROP CONSTRAINT IF EXISTS`` then ``ADD CONSTRAINT``, every
policy uses ``DROP POLICY IF EXISTS`` then ``CREATE POLICY``.

Index DDL is split into the next migration ``0208_time_clock_indexes``
because ``CREATE INDEX CONCURRENTLY`` cannot run inside the alembic
transactional wrapper (mirrors the 0205 → 0206 split).

**Photos persist regardless of downgrade (design §3.1, G15).** The
downgrade path drops the new tables + new columns + policies, but does
NOT touch the ``uploads`` table. ``time_clock_entries.clock_in_photo_url``
/ ``clock_out_photo_url`` are nullable text columns referencing
``uploads.file_key`` strings — not FKs — so downgrade is loss-bounded
to the time-clock tables themselves; the underlying photo files remain
on disk under ``/app/uploads/clock_photos/`` for the documented 6-year
Holidays Act s81 retention.

Refs: requirements R3, R4, R6, R12, R14; tasks A1; design.md §3.1, §3.2,
       §4.7, §4.8, §6.4.

Revision ID: 0207
Revises: 0206
Create Date: 2026-05-31
"""

from __future__ import annotations

from alembic import op

revision: str = "0207"
down_revision: str = "0206"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


# ---------------------------------------------------------------------------
# Default JSONB blocks — kept as Python module constants so the values are
# documented in one place and the inline DDL stays scannable.
# ---------------------------------------------------------------------------
_CLOCK_IN_POLICY_DEFAULT = """{
    "default_channel": "kiosk_only",
    "self_service_require_photo": true,
    "self_service_require_geofence": false,
    "branch_radius_metres": 200,
    "allow_late_clock_out_edits": true,
    "kiosk_employee_id_rate_limit": 10,
    "shift_swap_requires_manager_approval": false
}"""

_OVERTIME_POLICY_DEFAULT = """{
    "weekly_threshold_minutes": 2400,
    "daily_threshold_minutes": 480,
    "require_pre_approval": false
}"""


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. branches geofence columns — new lat/lng + radius. Radius is
    #    backfilled from each org's clock_in_policy.branch_radius_metres
    #    AFTER the policy column is added (step 3 below). The
    #    column-level default of 200 makes the schema sane on its own
    #    even if the backfill is skipped.
    # ------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE branches
            ADD COLUMN IF NOT EXISTS lat numeric(9,6)
        """
    )
    op.execute(
        """
        ALTER TABLE branches
            ADD COLUMN IF NOT EXISTS lng numeric(9,6)
        """
    )
    op.execute(
        """
        ALTER TABLE branches
            ADD COLUMN IF NOT EXISTS geofence_radius_metres int NOT NULL DEFAULT 200
        """
    )

    # ------------------------------------------------------------------
    # 2. time_clock_entries — kiosk / self-service / admin-manual in-out
    #    events. ``flags`` JSONB column intentionally NOT named
    #    ``metadata`` (P3-N3 / tasks A1).
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS time_clock_entries (
            id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id              uuid NOT NULL,
            staff_id            uuid NOT NULL REFERENCES staff_members(id),
            clock_in_at         timestamptz NOT NULL,
            clock_out_at        timestamptz,
            source              text NOT NULL,
            clock_in_photo_url  text,
            clock_out_photo_url text,
            clock_in_lat        numeric(9,6),
            clock_in_lng        numeric(9,6),
            clock_out_lat       numeric(9,6),
            clock_out_lng       numeric(9,6),
            scheduled_entry_id  uuid REFERENCES schedule_entries(id),
            break_minutes       int NOT NULL DEFAULT 0,
            notes               text,
            created_by          uuid REFERENCES users(id),
            worked_minutes      int,
            flags               jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at          timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "ALTER TABLE time_clock_entries DROP CONSTRAINT IF EXISTS ck_time_clock_entries_source"
    )
    op.execute(
        """
        ALTER TABLE time_clock_entries ADD CONSTRAINT ck_time_clock_entries_source
            CHECK (source IN ('kiosk','self_service_mobile','self_service_web','admin_manual'))
        """
    )
    op.execute(
        "ALTER TABLE time_clock_entries DROP CONSTRAINT IF EXISTS ck_time_clock_entries_kiosk_photo"
    )
    op.execute(
        """
        ALTER TABLE time_clock_entries ADD CONSTRAINT ck_time_clock_entries_kiosk_photo
            CHECK (source <> 'kiosk' OR clock_in_photo_url IS NOT NULL)
        """
    )
    op.execute("ALTER TABLE time_clock_entries ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON time_clock_entries")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON time_clock_entries
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # 3. break_records — child of time_clock_entries. ON DELETE CASCADE
    #    so admin hard-deletes of a clock entry don't leave orphan
    #    break rows.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS break_records (
            id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id              uuid NOT NULL,
            time_clock_entry_id uuid NOT NULL REFERENCES time_clock_entries(id) ON DELETE CASCADE,
            break_type          text NOT NULL,
            start_at            timestamptz NOT NULL,
            end_at              timestamptz,
            minutes             int,
            created_at          timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "ALTER TABLE break_records DROP CONSTRAINT IF EXISTS ck_break_records_break_type"
    )
    op.execute(
        """
        ALTER TABLE break_records ADD CONSTRAINT ck_break_records_break_type
            CHECK (break_type IN ('rest_paid','meal_unpaid'))
        """
    )
    op.execute("ALTER TABLE break_records ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON break_records")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON break_records
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # 4. timesheet_approvals — week-level approval state machine.
    #    ``edited_after_approval`` (G16) is a fourth state that lets
    #    admin manual edits inside an approved week flip the row
    #    without losing its approval lineage. UNIQUE (staff_id,
    #    week_start) enforces one approval row per staff per week.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS timesheet_approvals (
            id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id                   uuid NOT NULL,
            staff_id                 uuid NOT NULL REFERENCES staff_members(id),
            week_start               date NOT NULL,
            week_end                 date NOT NULL,
            status                   text NOT NULL DEFAULT 'pending',
            total_worked_minutes     int,
            total_scheduled_minutes  int,
            total_overtime_minutes   int NOT NULL DEFAULT 0,
            total_break_minutes      int NOT NULL DEFAULT 0,
            ordinary_minutes         int NOT NULL DEFAULT 0,
            public_holiday_minutes   int NOT NULL DEFAULT 0,
            toil_choice              text,
            approved_by              uuid REFERENCES users(id),
            approved_at              timestamptz,
            notes                    text,
            created_at               timestamptz NOT NULL DEFAULT now(),
            updated_at               timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_timesheet_approvals_staff_week UNIQUE (staff_id, week_start)
        )
        """
    )
    op.execute(
        "ALTER TABLE timesheet_approvals DROP CONSTRAINT IF EXISTS ck_timesheet_approvals_status"
    )
    op.execute(
        """
        ALTER TABLE timesheet_approvals ADD CONSTRAINT ck_timesheet_approvals_status
            CHECK (status IN ('pending','approved','rejected','edited_after_approval'))
        """
    )
    op.execute(
        "ALTER TABLE timesheet_approvals DROP CONSTRAINT IF EXISTS ck_timesheet_approvals_toil_choice"
    )
    op.execute(
        """
        ALTER TABLE timesheet_approvals ADD CONSTRAINT ck_timesheet_approvals_toil_choice
            CHECK (toil_choice IS NULL OR toil_choice IN ('pay_cash','toil'))
        """
    )
    op.execute("ALTER TABLE timesheet_approvals ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON timesheet_approvals")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON timesheet_approvals
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # 5. overtime_requests — 3-state pre-approval request flow.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS overtime_requests (
            id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id                  uuid NOT NULL,
            staff_id                uuid NOT NULL REFERENCES staff_members(id),
            schedule_entry_id       uuid REFERENCES schedule_entries(id),
            proposed_extra_minutes  int NOT NULL,
            reason                  text,
            requested_by            uuid NOT NULL REFERENCES users(id),
            status                  text NOT NULL DEFAULT 'pending',
            decided_by              uuid REFERENCES users(id),
            decided_at              timestamptz,
            decision_notes          text,
            created_at              timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "ALTER TABLE overtime_requests DROP CONSTRAINT IF EXISTS ck_overtime_requests_status"
    )
    op.execute(
        """
        ALTER TABLE overtime_requests ADD CONSTRAINT ck_overtime_requests_status
            CHECK (status IN ('pending','approved','rejected'))
        """
    )
    op.execute("ALTER TABLE overtime_requests ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON overtime_requests")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON overtime_requests
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # 6. shift_swap_requests — 5-state machine. ``awaiting_manager``
    #    (G8) is reachable only when the org's
    #    clock_in_policy.shift_swap_requires_manager_approval toggle is
    #    on; otherwise the auto-approve path skips straight from
    #    ``pending`` to ``accepted``.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS shift_swap_requests (
            id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id               uuid NOT NULL,
            requester_staff_id   uuid NOT NULL REFERENCES staff_members(id),
            target_staff_id      uuid REFERENCES staff_members(id),
            schedule_entry_id    uuid NOT NULL REFERENCES schedule_entries(id),
            status               text NOT NULL DEFAULT 'pending',
            reason               text,
            decided_by           uuid REFERENCES users(id),
            created_at           timestamptz NOT NULL DEFAULT now(),
            decided_at           timestamptz
        )
        """
    )
    op.execute(
        "ALTER TABLE shift_swap_requests DROP CONSTRAINT IF EXISTS ck_shift_swap_requests_status"
    )
    op.execute(
        """
        ALTER TABLE shift_swap_requests ADD CONSTRAINT ck_shift_swap_requests_status
            CHECK (status IN ('pending','awaiting_manager','accepted','rejected','cancelled'))
        """
    )
    op.execute("ALTER TABLE shift_swap_requests ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON shift_swap_requests")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON shift_swap_requests
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # 7. shift_cover_requests — 4-state open-broadcast cover model.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS shift_cover_requests (
            id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id              uuid NOT NULL,
            schedule_entry_id   uuid NOT NULL REFERENCES schedule_entries(id),
            requester_staff_id  uuid NOT NULL REFERENCES staff_members(id),
            status              text NOT NULL DEFAULT 'open',
            accepted_by         uuid REFERENCES staff_members(id),
            broadcast_at        timestamptz NOT NULL DEFAULT now(),
            expires_at          timestamptz,
            accepted_at         timestamptz,
            created_at          timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "ALTER TABLE shift_cover_requests DROP CONSTRAINT IF EXISTS ck_shift_cover_requests_status"
    )
    op.execute(
        """
        ALTER TABLE shift_cover_requests ADD CONSTRAINT ck_shift_cover_requests_status
            CHECK (status IN ('open','accepted','cancelled','expired'))
        """
    )
    op.execute("ALTER TABLE shift_cover_requests ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON shift_cover_requests")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON shift_cover_requests
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # 8. organisations.clock_in_policy — JSONB column with the
    #    documented default block (design §3.1).
    # ------------------------------------------------------------------
    op.execute(
        f"""
        ALTER TABLE organisations
            ADD COLUMN IF NOT EXISTS clock_in_policy jsonb NOT NULL DEFAULT '{_CLOCK_IN_POLICY_DEFAULT}'::jsonb
        """
    )

    # ------------------------------------------------------------------
    # 9. organisations.overtime_policy — JSONB column with the
    #    documented default block (G1, design §3.1).
    # ------------------------------------------------------------------
    op.execute(
        f"""
        ALTER TABLE organisations
            ADD COLUMN IF NOT EXISTS overtime_policy jsonb NOT NULL DEFAULT '{_OVERTIME_POLICY_DEFAULT}'::jsonb
        """
    )

    # ------------------------------------------------------------------
    # 10. organisations.overtime_handling — defensive re-assert
    #     (P3-N4). Phase 2's 0205_leave_schema already adds this; the
    #     IF NOT EXISTS guard makes this a no-op on the happy path
    #     while still protecting Phase 3's read paths if 0205 ever
    #     gets re-ordered or rolled back independently.
    # ------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE organisations
            ADD COLUMN IF NOT EXISTS overtime_handling text NOT NULL DEFAULT 'pay_cash'
        """
    )
    op.execute(
        "ALTER TABLE organisations DROP CONSTRAINT IF EXISTS ck_org_overtime_handling"
    )
    op.execute(
        """
        ALTER TABLE organisations ADD CONSTRAINT ck_org_overtime_handling
            CHECK (overtime_handling IN ('pay_cash','toil','employee_chooses'))
        """
    )

    # ------------------------------------------------------------------
    # 11. Backfill branches.geofence_radius_metres from each org's
    #     clock_in_policy.branch_radius_metres (G17). Runs AFTER the
    #     policy column is added so the SELECT can read it.
    #
    #     Only touches rows that still hold the column-default 200 —
    #     this keeps the backfill safe to re-run after a partial
    #     downgrade (the migration is idempotent).
    # ------------------------------------------------------------------
    op.execute(
        """
        UPDATE branches
        SET geofence_radius_metres = COALESCE(
            (SELECT (clock_in_policy->>'branch_radius_metres')::int
             FROM organisations
             WHERE organisations.id = branches.org_id),
            200
        )
        WHERE geofence_radius_metres = 200
        """
    )


def downgrade() -> None:
    # ------------------------------------------------------------------
    # Reverse order: tables → org columns → branches columns. Photos in
    # the ``uploads`` table are intentionally left in place per design
    # §3.1 + G15 (6-year Holidays Act s81 retention is the documented
    # default — clock-in/out photos persist independently of the
    # time_clock_entries row).
    # ------------------------------------------------------------------

    # New tables — drop child-first to respect FK + CASCADE rules.
    op.execute("DROP TABLE IF EXISTS shift_cover_requests")
    op.execute("DROP TABLE IF EXISTS shift_swap_requests")
    op.execute("DROP TABLE IF EXISTS overtime_requests")
    op.execute("DROP TABLE IF EXISTS timesheet_approvals")
    op.execute("DROP TABLE IF EXISTS break_records")
    op.execute("DROP TABLE IF EXISTS time_clock_entries")

    # organisations columns added in this migration. overtime_handling
    # is owned by 0205 — its constraint + column are NOT dropped here,
    # so a 0207 downgrade leaves Phase 2's typed column intact.
    op.execute("ALTER TABLE organisations DROP COLUMN IF EXISTS overtime_policy")
    op.execute("ALTER TABLE organisations DROP COLUMN IF EXISTS clock_in_policy")

    # branches columns.
    op.execute("ALTER TABLE branches DROP COLUMN IF EXISTS geofence_radius_metres")
    op.execute("ALTER TABLE branches DROP COLUMN IF EXISTS lng")
    op.execute("ALTER TABLE branches DROP COLUMN IF EXISTS lat")
