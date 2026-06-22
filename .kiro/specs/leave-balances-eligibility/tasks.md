# Implementation Plan: Leave Balances & Eligibility

## Overview

This plan implements the org-wide Leave Balances view and the versioned eligibility / accrual rules engine that drives statutory leave under the NZ Holidays Act 2003. It is a gaps-only build: the per-staff leave plumbing (`leave_types`, `leave_balances`, append-only `leave_ledger`, the adjust endpoint, the module gate, in-app notifications, the scheduler) already exists and is reused unchanged. Work proceeds foundation-first, bottom-up: migrations → ORM/schemas → pure rules core (registry → service period → hours test → eligibility → termination) → idempotent vesting applier → scheduled sweep + on-demand trigger → RBAC/module map → org-wide list endpoint → reused per-staff endpoints + reference guide → frontend → cross-cutting integration/e2e → version bump. Each terminal step wires its new code into the routers, middleware, scheduler, and sidebar so nothing is left orphaned.

Backend is Python 3.11 / FastAPI / SQLAlchemy (async) / Alembic; frontend is the active `frontend-v2/` React 18 + TypeScript + Vite + Tailwind SPA. The two migrations chain on head `0225`: Migration A `0226` (transactional — `leave_eligibility_notes` table + RLS `tenant_isolation` + `staff_members.holiday_pay_method` column + casual backfill, fully idempotent) and Migration B `0227` (CONCURRENTLY perf indexes inside an `autocommit_block`, separate file). The rules core (`registry.py`, `service_period.py`, `hours_test.py`, `eligibility.py`, `termination.py`) is pure and side-effect-free so the 29 correctness properties are property-testable without a DB where possible; the DB-touching applier/RLS/idempotency properties use the existing async transactional fixtures.

Property tests use **Hypothesis** (minimum 100 examples each via `@settings(max_examples=100)` / the shared `PBT_SETTINGS` profile), each tagged `# Feature: leave-balances-eligibility, Property {n}: {property_text}` and citing the design property number. Example/integration tests (module gating, RBAC 403s, org isolation, reference-guide content, reused-endpoint side effects) use pytest; frontend tests use Vitest + React Testing Library. Requirement references map to `requirements.md` sub-clauses; property references map to the Correctness Properties in `design.md`. All 29 properties are covered exactly once across the test sub-tasks.

## Tasks

- [x] 1. Database migrations — eligibility notes table, holiday-pay-method column, perf indexes
  - [x] 1.1 Create Alembic revision `0226` (transactional) off head `0225`
    - New file `alembic/versions/..._0226_leave_eligibility.py` with `revision="0226"`, `down_revision="0225"`.
    - `ALTER TABLE staff_members ADD COLUMN IF NOT EXISTS holiday_pay_method text NOT NULL DEFAULT 'accrued'`; add CHECK `holiday_pay_method IN ('accrued','casual_payg')` guarded by an `information_schema` existence check before adding the constraint (re-runnable).
    - `CREATE TABLE IF NOT EXISTS leave_eligibility_notes (...)` exactly per design §Data Models: `id uuid PK`, `org_id uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE`, `staff_id uuid NOT NULL REFERENCES staff_members(id) ON DELETE CASCADE`, mod`leave_type_id uuid NOT NULL REFERENCES leave_types(id) ON DELETE RESTRICT`, `rule_set_version text NOT NULL`, `milestone_key text NOT NULL`, `hours_test_met boolean NULL`, `condition_text text NOT NULL`, `vested_on date NOT NULL`, `created_at timestamptz NOT NULL DEFAULT now()`, plus `CONSTRAINT uq_leave_eligibility_notes_staff_type UNIQUE (staff_id, leave_type_id)`.
    - `ALTER TABLE leave_eligibility_notes ENABLE ROW LEVEL SECURITY` (not FORCE) + `DROP POLICY IF EXISTS tenant_isolation` + `CREATE POLICY tenant_isolation ... USING (org_id = current_setting('app.current_org_id', true)::uuid)` — mirrors migration `0224`.
    - Backfill: idempotent `UPDATE staff_members SET holiday_pay_method='casual_payg' WHERE employment_type='casual' AND holiday_pay_method <> 'casual_payg'`.
    - `downgrade()` drops the table then the column. `IF NOT EXISTS` / `IF EXISTS` / `information_schema` guards on every statement; no `CONCURRENTLY` in this file (transactional). Follows the **database-migration-checklist** steering.
    - _Requirements: 11.1, 11.6, 13.1, 13.4, 16.6, 6.6_

  - [x] 1.2 Create Alembic revision `0227` (autocommit perf indexes) off `0226`
    - Separate file `alembic/versions/..._0227_leave_perf_indexes.py` with `revision="0227"`, `down_revision="0226"` — separate because mixing `CONCURRENTLY` with transactional DDL is a banned pattern (mirrors `0202_add_perf_indexes.py` / the `0224` autocommit phase).
    - Inside `op.get_context().autocommit_block()`: `CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_leave_balances_org ON leave_balances (org_id)` and `CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_leave_elig_notes_staff_type ON leave_eligibility_notes (staff_id, leave_type_id)`.
    - `downgrade()` drops both with `DROP INDEX CONCURRENTLY IF EXISTS` inside the same `autocommit_block()`. `IF NOT EXISTS` / `IF EXISTS` guards for retry-safety (a failed CONCURRENTLY build leaves an INVALID index).
    - _Requirements: 1.3, 1.4_

  - [x] 1.3 Post-migration verification (mandatory)
    - Run `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head` inside the dev app container; confirm output shows `0225 -> 0226 -> 0227` applying cleanly.
    - Verify the `holiday_pay_method` CHECK constraint exists and rejects out-of-domain values, the `staff_members.holiday_pay_method` column defaults to `'accrued'`, the `uq_leave_eligibility_notes_staff_type` UNIQUE constraint exists, RLS `tenant_isolation` is enabled on `leave_eligibility_notes`, both indexes are present and VALID, and the casual backfill set `holiday_pay_method='casual_payg'` for existing casual staff.
    - Confirm re-running `alembic upgrade head` is a no-op (idempotency) and `alembic downgrade -1` twice then `upgrade head` round-trips cleanly.
    - _Requirements: 11.1, 11.6, 13.1, 16.6_

- [x] 2. ORM models and schemas
  - [x] 2.1 Add the `holiday_pay_method` column and `LeaveEligibilityNote` model
    - Add `holiday_pay_method: Mapped[str]` (`server_default="accrued"`) to the `StaffMember` model.
    - Add `LeaveEligibilityNote` to `app/modules/leave/models.py` mirroring the migration exactly (org-scoped, FKs with the design's ON DELETE rules, `rule_set_version`, `milestone_key`, `hours_test_met: Mapped[bool | None]`, `condition_text`, `vested_on`, `created_at`, the `(staff_id, leave_type_id)` unique constraint); export it in the module `__all__`.
    - Service code must never UPDATE/DELETE this table (append-only, R13.4).
    - _Requirements: 11.1, 11.6, 13.1, 13.4, 6.6_

  - [x] 2.2 Add response/query schemas for the org-wide list and reference guide
    - Add `StaffLeaveBalances` (`staff_id`, `staff_name`, `employment_type`, `holiday_pay_method`, `balances: LeaveBalanceResponse[]`, `eligibility_notes: EligibilityNote[]`) and `EligibilityNote` response models in `app/modules/leave/schemas.py`; reuse the existing `LeaveBalanceResponse` (which already exposes the `available_hours = accrued − used − pending` computed field).
    - Add the list query params (`employment_type`, `group_by`, `offset`, `limit`) and the `{ items, total }` envelope model; add the reference-guide content schema (sections + hours-test + milestones + parental-leave-out-of-scope note).
    - _Requirements: 1.3, 1.5, 1.7, 2.1, 2.2, 13.3, 15.2, 15.3, 15.4_

- [x] 3. Rule-set registry and resolver — `app/modules/leave/rules/registry.py`
  - [x] 3.1 Implement the registry and strict resolver
    - Define frozen dataclasses `Milestone`, `HoursTestBounds`, `LeaveRule`, `RuleSet` exactly per design; encode `HOLIDAYS_ACT_2003` (milestones day_1/six_months/twelve_months; hours-test bounds 10/1/40; rules `annual` (twelve_months, no hours test, accrues, 4 weeks), `sick`/`bereavement`/`family_violence` (six_months + hours test, non-accruing gate); day-one entitlements `public_holiday`, `alternative_holiday`, `jury_service`).
    - Expose `RULE_SETS: tuple[RuleSet, ...] = (HOLIDAYS_ACT_2003,)` and `resolve_rule_set(evaluation_date, rule_sets=RULE_SETS)` returning the rule-set with the maximum `effective_from` whose `effective_from <= evaluation_date`; raise `NoApplicableRuleSet` when none apply. All thresholds live in the dataclasses (version-scoped config, never hard-coded), so a future `EMPLOYMENT_LEAVE_BILL` registers additively.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 17.1, 17.2, 17.3, 17.4_

  - [x]* 3.2 Write property test for the rule-set resolver
    - **Property 15: Rule-set resolver selects the latest applicable version** — for any registry and evaluation date, returns the max-`effective_from` version with `effective_from <= date`; raises `NoApplicableRuleSet` when none apply; returns `holidays_act_2003` for dates in `[2003.effective_from, bill.effective_from)`.
    - File `tests/properties/test_leave_rule_resolver.py`; Hypothesis ≥100 examples over `rule_set_registries()` + `evaluation_dates()`.
    - **Validates: Requirements 6.3, 6.4, 6.5, 17.4**

  - [x]* 3.3 Write property test for additive future-version registration
    - **Property 16: Future versions register additively** — for any date strictly before a newly registered later version's `effective_from`, resolving against the extended registry yields the same version as resolving without it.
    - File `tests/properties/test_leave_rule_resolver.py`; Hypothesis ≥100 examples.
    - **Validates: Requirements 17.1, 17.2**

- [x] 4. Continuous service and hours test (pure helpers)
  - [x] 4.1 Implement `service_period.py` — `StaffSnapshot` + `compute_continuous_service`
    - Define `StaffSnapshot` (incl. `employment_start_date: date | None`, `employment_type`, `standard_hours_per_week`, `holiday_pay_method`, `fixed_term_months`, `hours_test_input`) per design in `app/modules/leave/rules/service_period.py`.
    - `compute_continuous_service(start, evaluation_date) -> ServicePeriod | None` returns completed-months elapsed and the set of reached milestones (day_1 ≤ 0mo, six_months ≤ 6mo, twelve_months ≤ 12mo); returns `None` when `start` is `None`; a trial/probation period never delays or resets it.
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [x]* 4.2 Write property test for continuous-service computation
    - **Property 18: Continuous service computation** — equals completed months between start and evaluation date, monotonically non-decreasing in evaluation date, and the reached-milestone set is exactly those whose month threshold ≤ completed months.
    - File `tests/properties/test_leave_eligibility_engine.py`; Hypothesis ≥100 examples (incl. Feb-29 edges).
    - **Validates: Requirements 7.1, 7.2**

  - [x] 4.3 Implement `hours_test.py` — `HoursTestInput` + `evaluate_hours_test`
    - Define `HoursTestInput` / `HoursTestResult` and `evaluate_hours_test(inp, bounds) -> HoursTestResult` in `app/modules/leave/rules/hours_test.py`: met iff average ≥ 10 h/wk AND (every week ≥ 1h OR every month ≥ 40h); when `inp is None` return `met=False, reason='no_worked_hours_data'`; never raises.
    - Include the aggregator that sums `time_clock_entries.worked_minutes` over the qualifying period bucketed by ISO week and calendar month (returns `None` when no usable data).
    - _Requirements: 8.1, 8.5_

  - [x]* 4.4 Write property test for the hours-test predicate
    - **Property 22: Hours-test predicate** — met exactly when avg ≥ 10 h/wk AND (every week ≥ 1h OR every month ≥ 40h); unavailable input → not-met with a recorded reason, never raises.
    - File `tests/properties/test_leave_hours_test.py`; Hypothesis ≥100 examples over `hours_test_inputs()` (incl. empty/`None`, boundary buckets).
    - **Validates: Requirements 8.1, 8.5**

- [x] 5. Pure eligibility evaluator — `app/modules/leave/rules/eligibility.py`
  - [x] 5.1 Implement `evaluate_eligibility`
    - `evaluate_eligibility(snapshot, evaluation_date, rule_set) -> list[EligibilityResult]`, pure, keyed only on Continuous_Service + Hours_Test; one result per rule, each stamped with `rule_set.version`.
    - No `employment_start_date` → all results `eligible=False, reason="start_date_required"` (no partial calc). For each `LeaveRule`: eligible iff gating milestone reached AND (`requires_hours_test` False OR hours test met). Casual (`holiday_pay_method == "casual_payg"`) → annual rule reported `eligible=False, reason="casual_payg"`; casual still must meet the same milestones + hours test for other types (never day-1 statutory accrual). Reads thresholds only from `rule_set.*`.
    - _Requirements: 2.4, 7.4, 7.5, 7.6, 8.2, 8.3, 8.4, 9.1, 9.3, 9.5, 10.1, 10.4, 11.2_

  - [x]* 5.2 Write property test for employment-type independence
    - **Property 8: Eligibility is independent of employment type** — changing `employment_type` to any non-casual value leaves all statutory eligibility results unchanged; the only employment-type effect is casual selecting Casual_PAYG.
    - File `tests/properties/test_leave_eligibility_engine.py`; ≥100 examples over `staff_snapshots()`.
    - **Validates: Requirements 2.4, 7.5**

  - [x]* 5.3 Write property test for trial-period invariance
    - **Property 19: Trial period never affects service** — varying probation/trial data leaves computed continuous service and all eligibility results unchanged.
    - File `tests/properties/test_leave_eligibility_engine.py`; ≥100 examples.
    - **Validates: Requirements 7.3**

  - [x]* 5.4 Write property test for missing-start-date skip
    - **Property 20: Missing start date skips milestone processing** — for any snapshot with no `employment_start_date`, every result is `eligible=False` with reason `start_date_required` and no partial milestone calculation is performed.
    - File `tests/properties/test_leave_eligibility_engine.py`; ≥100 examples.
    - **Validates: Requirements 7.4**

  - [x]* 5.5 Write property test for the six-month + hours-test gate
    - **Property 23: Six-month + hours-test gate for sick, bereavement, and family-violence** — each of these types is eligible exactly when the six-month milestone is reached AND the Hours_Test is met.
    - File `tests/properties/test_leave_eligibility_engine.py`; ≥100 examples.
    - **Validates: Requirements 8.2, 8.3, 8.4**

  - [x]* 5.6 Write property test for day-one entitlements
    - **Property 25: Day-one entitlements** — for any snapshot with an `employment_start_date`, public-holiday and jury-service entitlements are available from day 1 (continuous service ≥ 0), independent of the accruing-leave milestone gates.
    - File `tests/properties/test_leave_eligibility_engine.py`; ≥100 examples.
    - **Validates: Requirements 10.1, 10.4**

  - [x]* 5.7 Write structural test for version-scoped configuration
    - Lint-style test asserting `evaluate_eligibility` reads thresholds only from `rule_set.*` (no hard-coded milestone-month or hours-test literals) — guards version-scoped configuration.
    - File `tests/properties/test_leave_eligibility_engine.py`.
    - _Requirements: 17.3_

- [x] 6. Termination payout (calculation only) — `app/modules/leave/rules/termination.py`
  - [x] 6.1 Implement `compute_termination_payout`
    - Pure `compute_termination_payout(...) -> TerminationPayout` per design: `casual_payg` → amount 0, rule `casual_payg_already_paid`; service < 12 months → 8% of gross, rule `pre_12mo_8pct`; on/after 12 months → remaining accrued hours converted to weeks × greater_of(OWP, AWE), rule `post_12mo_accrued`; `rule_applied` always matches the branch taken. Representation only (no payroll execution).
    - _Requirements: 14.1, 14.2, 14.3, 14.4_

  - [x]* 6.2 Write property test for the termination payout
    - **Property 29: Termination payout pre/post twelve months and casual** — returns the casual / pre-12mo-8% / post-12mo-accrued branch with the matching `rule_applied` for any inputs.
    - File `tests/properties/test_leave_termination_payout.py`; ≥100 examples.
    - **Validates: Requirements 14.1, 14.2, 14.3, 14.4**

- [x] 7. Checkpoint — foundation and pure-core tests pass
  - Run the pure-core property tests (`pytest tests/properties/test_leave_rule_resolver.py test_leave_eligibility_engine.py test_leave_hours_test.py test_leave_termination_payout.py`) and confirm migration `0226`/`0227` applied cleanly in 1.3.
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Idempotent vesting applier — `app/modules/leave/rules/vesting.py`
  - [x] 8.1 Implement `apply_vesting`
    - `apply_vesting(db, *, snapshot, results, evaluation_date, rule_set) -> list[VestingOutcome]` per design: for each newly-satisfied eligibility with no prior vesting record for `(staff_id, leave_type_id)` — (1) append a `leave_ledger` row `reason='accrual'` with the vested hours for accruing rules (annual = `standard_hours_per_week × 4`, 40h/wk fallback, matching `accrual.py::_process_anniversary`); non-accruing entitlements vest the note + notification only; (2) update `leave_balances.accrued_hours` + `last_accrual_at`; (3) insert a `leave_eligibility_notes` row stamping `rule_set_version`, `milestone_key`, hours-test condition, `vested_on`; (4) create the de-duped eligibility-onset in-app notification via `create_in_app_notification`.
    - Idempotency: a prior accrual ledger row for `(staff,type,occurred_at=vested_on)` OR a prior eligibility note short-circuits; the `UNIQUE(staff_id, leave_type_id)` note constraint enforces one onset note ever; notification de-dup keys on the existing note / deterministic entity id. Uses `await db.flush()` (+ `db.refresh()` before returning ORM), never `commit()`. `create_in_app_notification` is exception-safe so a notification failure never rolls back the vesting.
    - _Requirements: 6.6, 9.1, 9.2, 9.4, 11.2, 12.1, 12.2, 12.4, 13.1, 13.2, 13.4_

  - [ ]* 8.2 Write property test for version stamping
    - **Property 17: Vesting is stamped with the resolved version** — the recorded `leave_eligibility_notes.rule_set_version` equals `resolve_rule_set(evaluation_date).version`, and every rule evaluated is associated with that version.
    - File `tests/properties/test_leave_vesting.py`; ≥100 examples (async DB fixture, per-org RLS GUC).
    - **Validates: Requirements 6.1, 6.6**

  - [ ]* 8.3 Write property test for annual-holidays vesting at twelve months
    - **Property 24: Annual-holidays vesting at twelve months** — for any non-casual snapshot, an accruing annual entitlement vests iff the twelve-month milestone is reached; when vested the amount equals 4 × standard weekly hours, recorded as exactly one `leave_ledger` row `reason='accrual'` carrying those hours.
    - File `tests/properties/test_leave_vesting.py`; ≥100 examples (async DB fixture).
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.4**

  - [ ]* 8.4 Write property test for casual never accruing
    - **Property 21: Casual never accrues statutory annual holidays** — for any casual staff member, no accruing annual balance is ever vested regardless of service length; casual classification alone never grants day-one statutory accrual.
    - File `tests/properties/test_leave_vesting.py`; ≥100 examples (async DB fixture).
    - **Validates: Requirements 7.6, 9.5, 11.2**

  - [ ]* 8.5 Write property test for the single active pay method
    - **Property 26: Exactly one active annual pay method** — for any staff state/transition exactly one method is active (`casual_payg` xor accrued): a `casual_payg` member has no accruing annual balance vested, and an accrued member is not paid Casual_PAYG.
    - File `tests/properties/test_leave_vesting.py`; ≥100 examples (async DB fixture).
    - **Validates: Requirements 11.6**

  - [ ]* 8.6 Write property test for notification de-duplication
    - **Property 27: At most one eligibility-onset notification per staff and leave type** — at most one onset notification per `(staff_id, leave_type_id)` across any sequence of evaluations/vesting events, regardless of which event triggers it or when the prior one was created; the first includes staff, leave type, and vested date.
    - File `tests/properties/test_leave_vesting.py`; ≥100 examples (async DB fixture).
    - **Validates: Requirements 12.1, 12.2, 12.4**

  - [ ]* 8.7 Write property test for the eligibility note
    - **Property 28: Eligibility note created with triggering condition** — for any vesting event exactly one `leave_eligibility_notes` row is created for the `(staff, leave_type)` pair recording the leave type, the triggering Service_Milestone or Hours_Test condition, and the vested date.
    - File `tests/properties/test_leave_vesting.py`; ≥100 examples (async DB fixture).
    - **Validates: Requirements 13.1, 13.2**

  - [ ]* 8.8 Write property test for append-only history
    - **Property 12: Append-only history (ledger and notes)** — for any sequence of serving/adjusting/correcting/vesting operations, no existing `leave_ledger` or `leave_eligibility_notes` row is ever updated or deleted (row count non-decreasing, prior rows unchanged); corrections add new compensating rows.
    - File `tests/properties/test_leave_vesting.py`; ≥100 examples (async DB fixture).
    - **Validates: Requirements 3.6, 3.7, 13.4**

- [x] 9. Scheduled sweep and on-demand trigger — `app/modules/leave/rules/sweep.py` + wiring
  - [x] 9.1 Implement the sweep task and on-demand evaluator
    - In `app/modules/leave/rules/sweep.py`: `evaluate_leave_eligibility_task() -> dict` — daily sweep across all active staff in all orgs, setting the per-org RLS GUC per staff's org, then `snapshot → resolve_rule_set(today) → evaluate_eligibility → apply_vesting`; idempotent (repeat-day runs are no-ops); `NoApplicableRuleSet` logged and that staff skipped.
    - Add a thin `evaluate_one_staff(db, staff_id, today)` used by the on-demand path.
    - _Requirements: 6.3, 7.4, 8.5, 12.1, 13.1_

  - [x] 9.2 Wire the sweep into the scheduler — `app/tasks/scheduled.py`
    - Append `(evaluate_leave_eligibility_task, 86400, "evaluate_leave_eligibility")` to `_DAILY_TASKS` and add `"evaluate_leave_eligibility"` to `WRITE_TASKS` so it is skipped on standby and runs only under the Redis leader lock on the primary (mirrors the existing `accrue_leave` task).
    - _Requirements: 12.1, 13.1_

  - [x] 9.3 Wire on-demand evaluation into the staff service
    - When a staff member is created or their `employment_start_date` is set/changed, call `evaluate_one_staff(db, staff_id, today)` so day-one entitlements and any already-passed milestones vest immediately rather than waiting for the nightly tick; surface `start_date_required` when missing.
    - _Requirements: 7.4, 10.1, 10.4, 12.1, 12.3_

  - [ ]* 9.4 Write integration test for sweep + on-demand idempotency
    - Running the sweep twice in a day vests each `(staff, type)` at most once and notifies at most once; setting a staff start date triggers immediate vesting of day-one entitlements; standby/leader-lock gating respected (example/integration, not PBT).
    - File `tests/integration/test_leave_eligibility_sweep.py`.
    - _Requirements: 12.1, 12.3, 12.4_

- [x] 10. RBAC permissions and module endpoint map
  - [x] 10.1 Register permissions and the leave module prefix
    - Add `CUSTOM_PERMISSIONS["staff_management"] = [PermissionItem(key="leave.balance_view", ...), PermissionItem(key="leave.balance_adjust", ...)]` in `app/modules/auth/permission_registry.py`; ensure built-in `org_admin` retains both (back-compat with the current `_require_org_admin` adjust gate).
    - Add the prefix entry `"/api/v2/leave": "staff_management"` to `MODULE_ENDPOINT_MAP` in `app/middleware/modules.py` for defence-in-depth (router-level dependency remains the authoritative gate).
    - _Requirements: 16.1, 16.2, 16.4_

- [x] 11. Org-wide balances list endpoint — `GET /api/v2/leave/balances`
  - [x] 11.1 Implement the list endpoint
    - Add `GET /api/v2/leave/balances` to `app/modules/leave/router.py`, gated by `_require_staff_management_module` (404 `not_enabled`) AND a `leave.balance_view` permission check (403); module-enabled treated as a precondition in addition to the permission.
    - Org-scoped via RLS; return `{ items: StaffLeaveBalances[], total }` (empty `{ items: [], total: 0 }` when nothing in scope); include only vested leave types per staff row (an eligibility note or non-zero/created balance) with `available_hours = accrued − used − pending`; surface each vested type's `eligibility_notes`; support the `employment_type` filter and `group_by=employment_type` (applied after eligibility, preserving engine independence) and `offset`/`limit` pagination.
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 2.1, 2.2, 2.3, 13.3, 16.2, 16.3, 16.6_

  - [ ]* 11.2 Write property test for the available-hours invariant
    - **Property 1: Available-hours invariant** — displayed `available_hours` equals `accrued_hours − used_hours − pending_hours` for any balance.
    - File `tests/properties/test_leave_balances_api.py`; ≥100 examples (async DB fixture).
    - **Validates: Requirements 1.5**

  - [ ]* 11.3 Write property test for organisation isolation
    - **Property 2: Organisation isolation (RLS)** — a balances/ledger query in org A's context returns only org A rows, never another org's, over multiple randomly populated orgs.
    - File `tests/properties/test_leave_balances_api.py`; ≥100 examples over `multi_org_fixtures()`.
    - **Validates: Requirements 1.4, 16.6**

  - [ ]* 11.4 Write property test for the list envelope and total
    - **Property 3: List envelope and total** — response is `{ items, total }` where `total` equals the number of in-scope staff rows and `items` is a list (empty when nothing in scope).
    - File `tests/properties/test_leave_balances_api.py`; ≥100 examples.
    - **Validates: Requirements 1.3, 1.8**

  - [ ]* 11.5 Write property test for only-vested-types
    - **Property 4: Only vested types are shown** — the leave types in a staff row are exactly those with a vested entitlement; un-vested types are omitted and every vested type appears.
    - File `tests/properties/test_leave_balances_api.py`; ≥100 examples.
    - **Validates: Requirements 1.6, 12.3, 13.3**

  - [ ]* 11.6 Write property test for pagination
    - **Property 5: Pagination is a faithful slice** — for any `offset`/`limit`, the page equals the slice of the full ordered set, `total` is independent of pagination, and concatenating successive pages reproduces the full set with no overlap or omission.
    - File `tests/properties/test_leave_balances_api.py`; ≥100 examples.
    - **Validates: Requirements 1.7**

  - [ ]* 11.7 Write property test for the employment-type filter
    - **Property 6: Employment-type filter** — every staff member returned has the filtered employment type and no in-scope member of that type is omitted.
    - File `tests/properties/test_leave_balances_api.py`; ≥100 examples.
    - **Validates: Requirements 2.1**

  - [ ]* 11.8 Write property test for employment-type grouping
    - **Property 7: Employment-type grouping partitions the set** — groups form a partition of the filtered set; every member appears in exactly one group with no loss or duplication.
    - File `tests/properties/test_leave_balances_api.py`; ≥100 examples.
    - **Validates: Requirements 2.2**

  - [x]* 11.9 Write integration test for module gating and RBAC on the list endpoint
    - `staff_management` disabled → 404 `not_enabled`; caller without `leave.balance_view` → 403; authorised caller with the module enabled → 200 (example/integration, not PBT).
    - File `tests/integration/test_leave_balances_api.py`.
    - _Requirements: 1.2, 16.1, 16.2, 16.3_

- [x] 12. Reused per-staff endpoints and reference guide
  - [x] 12.1 Re-map the adjust endpoint to `leave.balance_adjust`
    - Re-gate `POST /api/v2/staff/{id}/leave/balances/{leave_type_id}/adjust` from `_require_org_admin` to a `leave.balance_adjust` permission check (403 otherwise), keeping the existing atomic ledger+balance write, `adjustment` ledger row, required `reason` (422 when missing), audit-log entry, and org scoping unchanged. The per-staff balances and ledger GET endpoints are reused unchanged.
    - _Requirements: 3.1, 3.2, 4.2, 4.4, 4.6, 4.7, 16.4, 16.5, 16.6_

  - [ ]* 12.2 Write property test for ledger ordering
    - **Property 9: Ledger is ordered by occurrence date** — served ledger history is sorted by `occurred_at`.
    - File `tests/properties/test_leave_balances_api.py`; ≥100 examples over `ledger_histories()`.
    - **Validates: Requirements 3.3**

  - [ ]* 12.3 Write property test for ledger entry fields
    - **Property 10: Ledger entries expose delta, reason, and occurrence** — each returned entry contains its `delta_hours`, `reason`, and `occurred_at`.
    - File `tests/properties/test_leave_balances_api.py`; ≥100 examples.
    - **Validates: Requirements 3.4**

  - [ ]* 12.4 Write property test for the single-leave-type ledger filter
    - **Property 11: Single-leave-type ledger filter** — for any `leave_type_id` filter, every returned ledger row has that `leave_type_id`.
    - File `tests/properties/test_leave_balances_api.py`; ≥100 examples.
    - **Validates: Requirements 3.5**

  - [ ]* 12.5 Write property test for the non-blank-reason guard
    - **Property 13: Adjustment requires a non-blank reason** — an adjustment whose reason is empty/all-whitespace is rejected with a validation error and the balance and ledger are unchanged.
    - File `tests/properties/test_leave_balances_api.py`; ≥100 examples (async DB fixture).
    - **Validates: Requirements 4.3**

  - [ ]* 12.6 Write property test for adjustment atomicity
    - **Property 14: Adjustment is atomic** — an adjustment that fails after the point a ledger row would be created rolls back so neither the ledger row nor the balance change persists.
    - File `tests/properties/test_leave_balances_api.py`; ≥100 examples (async DB fixture, inject a mid-write failure).
    - **Validates: Requirements 4.7**

  - [x] 12.7 Implement the reference-guide endpoint
    - Add `GET /api/v2/leave/reference-guide` returning the NZ Holidays Act 2003 content as structured JSON (annual/sick/bereavement/family-violence/public holidays/alternative holidays/jury service, the Hours_Test, the Service_Milestones, and the parental-leave-out-of-scope note); module-gated; available even when content is partially populated.
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.6_

  - [x]* 12.8 Write integration test for the reference guide
    - Returns available sections under the module gate; reachable when content is partially populated; module can still be enabled (example/integration).
    - File `tests/integration/test_leave_balances_api.py`.
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.6_

- [x] 13. Checkpoint — backend tests pass
  - Run the full backend suite (`pytest` incl. the Hypothesis property tests at ≥100 examples and the integration tests).
  - Ensure all tests pass, ask the user if questions arise.

- [x] 14. Frontend (frontend-v2)
  - [x] 14.1 Add the API client functions — `frontend-v2/src/api/leave.ts`
    - Add typed helpers (generics, never `as any`) for `GET /api/v2/leave/balances` (with `employment_type`/`group_by`/`offset`/`limit`), the reused per-staff balances/ledger/adjust calls, and `GET /api/v2/leave/reference-guide`, using the shared `apiClient` with absolute `/api/v2/...` paths, defensive consumption (`res.data?.items ?? []`, `res.data?.total ?? 0`), and an optional `AbortSignal`.
    - _Requirements: 1.3, 1.7, 2.1, 2.2, 3.1, 3.2, 4.2, 15.2_

  - [x] 14.2 Create `LeaveBalancesPage`, register its route, and add the sidebar entry
    - New `frontend-v2/src/pages/leave/LeaveBalancesPage.tsx` (mirrors `pages/staff-timesheets/TimesheetsPage.tsx` — a **standalone page**, not a tab): org-wide table of staff with their vested balances, an `employment_type` filter dropdown, a "group by employment type" toggle, and a persistent note "Employment type is a display convenience only — it does not change statutory leave eligibility." Loading/empty/error states with retry; `AbortController` in every `useEffect`; safe consumption.
    - Register the route in `App.tsx` with `<ModuleRoute moduleSlug="staff_management"><LeaveBalancesPage /></ModuleRoute>` at `/leave/balances` (mirrors the timesheets route).
    - **Sidebar (concrete):** add a new item to the existing `People` group in `NAV_GROUPS` (`components/shell/Sidebar.tsx`), placed immediately after the existing `leave-approvals` item: `{ id: 'leave-balances', to: '/leave/balances', label: 'Leave Balances', icon: ICON.staff, module: 'staff_management' }`. Reuse `ICON.staff` (no dedicated leave icon; the sibling `leave-approvals` reuses it too). Do **not** mark it `adminOnly` — visibility is module-gated and the endpoint enforces `leave.balance_view` (403). There is no "Staff/Leave" sub-nav; this is a flat People-group item.
    - _Requirements: 1.1, 1.2, 1.3, 1.5, 1.6, 1.7, 1.8, 2.1, 2.2, 2.3, 2.5, 5.1, 5.2, 5.3, 5.4_

  - [x] 14.3 Wire the drill-in, adjust modal, casual indicator, and config link
    - **Mount the currently-orphaned per-staff leave UI.** `pages/staff/leave/LeaveTab.tsx` and its children (`BalanceCardsRow`, `LedgerTable`, `AdjustBalanceModal`, `CasualLeaveBanner`) exist from Staff Phase 2 but are **not imported or rendered anywhere today** (`StaffDetail` tabs are only `overview | roster | payslips | documents`). This drill-in is the first place they are mounted — reuse them as components, but treat the wiring as real work, not "reuse unchanged."
    - Clicking a staff row opens the per-staff `LeaveTab` reusing `BalanceCardsRow`, `LedgerTable`, and `CasualLeaveBanner` (balances + ledger history; casual rows show the 8% pay-as-you-go indicator); surface each vested type's eligibility note (e.g. "Annual holidays vested — 12 months continuous service reached on 2026-03-01").
    - **Resolve the prop-shape gap:** `LeaveTab` requires a full `Staff` object (`pages/staff/leave/types.ts`) + an `isAdmin` prop and fetches via `useStaffLeave(staffId)`, but the org-wide list row is the lightweight `StaffLeaveBalances` (`staff_id`, `staff_name`, `employment_type`, …). Before mounting `LeaveTab`, either (a) fetch the full staff record using the row's `staff_id` — the backend `GET /api/v2/staff/{staff_id}` exists but **no** frontend `getStaff(id)` helper does, so add one to `api/staff.ts` — or (b) **preferred:** refactor `LeaveTab` to accept a `staffId` and load its own staff context (matches the existing `useStaffLeave(staffId)` flow, no new wrapper). Derive `isAdmin` from the user's `leave.balance_adjust` permission.
    - Reuse `AdjustBalanceModal.tsx` (posts to the existing adjust endpoint), shown only when the user holds `leave.balance_adjust`; on success show the updated balance and new ledger entry. Add the Settings → Leave Types config link, disabled/hidden when the user lacks leave-type config permission; on navigation failure show an error with a manual retry (no auto-retry).
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 11.3, 13.3_

  - [x] 14.4 Create the reference-guide page and link it
    - New `frontend-v2/src/pages/leave/LeaveReferenceGuidePage.tsx` at `/leave/reference-guide` (consumes `GET /api/v2/leave/reference-guide` or renders the static content), describing the eligibility rules, the Hours_Test, the Service_Milestones, and the parental-leave-out-of-scope note; register the route in `App.tsx` and add the link from the `LeaveBalancesPage` header.
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5_

  - [ ]* 14.5 Write frontend unit tests (Vitest + RTL)
    - `LeaveBalancesPage`: list rendering, empty state, employment-type filter + grouping, the display-convenience note, pagination, config-link disabled-when-unauthorised + navigation-failure retry; drill-in rendering of balances/ledger + eligibility note + casual indicator; `AdjustBalanceModal` shown only with `leave.balance_adjust`, reason-required validation, optimistic refresh; reference-guide page content + header link.
    - _Requirements: 1.5, 1.6, 1.8, 2.1, 2.2, 2.5, 4.1, 4.3, 4.4, 5.3, 5.4, 11.3, 13.3, 15.5_

- [x] 15. Checkpoint — full stack wired
  - Run backend (`pytest`) and frontend (`vitest --run` + `tsc --noEmit`) checks together.
  - Ensure all tests pass, ask the user if questions arise.

- [x] 16. Integration / end-to-end tests and final verification
  - [x] 16.1 Write the cross-cutting end-to-end integration test
    - Drive the full feature: module gate 404 (`not_enabled`) on the list and reference-guide endpoints when `staff_management` is disabled; RBAC 403s for callers lacking `leave.balance_view` (list) and `leave.balance_adjust` (adjust); and org isolation — a user in org A never sees org B's staff, balances, ledger rows, or eligibility notes through any endpoint.
    - File `tests/integration/test_leave_balances_api.py`.
    - _Requirements: 1.2, 1.4, 16.1, 16.2, 16.3, 16.5, 16.6_

  - [x] 16.2 Final verification
    - Run the backend suite (`pytest` incl. Hypothesis property tests at ≥100 examples) and frontend checks (`tsc --noEmit`, `vitest --run`); run `alembic upgrade head` in the dev container to confirm `0226`/`0227` apply cleanly; run `get_diagnostics` on the spec files and fix any reported issues.
    - _Requirements: all_

- [x] 17. Version bump and changelog
  - [x] 17.1 Bump version and add a CHANGELOG entry (MINOR feature)
    - Per the **versioning-and-changelog** steering, this is a new feature → MINOR bump (x.Y.0). Bump the backend version in `app/__init__.py` (`__version__`) and the frontend-v2 version in `frontend-v2/package.json` (`version`); reconcile with `pyproject.toml` if drifted.
    - Add a newest-first `CHANGELOG.md` entry under `### Added` describing the Leave Balances view + eligibility/accrual rules engine (org-wide balances list, versioned Holidays Act 2003 rule-set, milestone + hours-test eligibility, idempotent vesting with onset notifications + eligibility notes, casual 8% PAYG handling, termination-payout calculation, and the NZ Holidays Act reference guide).
    - _Requirements: all_

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; core implementation tasks are never optional.
- Each task references granular requirement sub-clauses for traceability; every property-test sub-task cites the exact design property number. All 29 correctness properties are covered exactly once (P1–P14 in `test_leave_balances_api.py`, P15–P16 in `test_leave_rule_resolver.py`, P18–P20/P23/P25 + the R17.3 structural test in `test_leave_eligibility_engine.py`, P22 in `test_leave_hours_test.py`, P29 in `test_leave_termination_payout.py`, and P12/P17/P21/P24/P26/P27/P28 in `test_leave_vesting.py`).
- Every Hypothesis property test runs a minimum of 100 examples and is tagged `# Feature: leave-balances-eligibility, Property {n}: {property_text}`.
- The pure rules core (`registry.py`, `service_period.py`, `hours_test.py`, `eligibility.py`, `termination.py`) is side-effect-free so it is property-tested without a DB; the applier/RLS/idempotency/adjust properties use the existing async transactional fixtures with the per-org RLS GUC (`app.current_org_id`).
- The feature is a gaps-only build on the **backend** (reuses `leave_types`, `leave_balances`, the append-only `leave_ledger`, the adjust endpoint, the per-staff balances/ledger endpoints, the module gate, `create_in_app_notification`, the scheduler). On the **frontend** it reuses the Phase-2 components `LeaveTab`/`BalanceCardsRow`/`LedgerTable`/`AdjustBalanceModal`/`CasualLeaveBanner`, but these are **currently orphaned** (not mounted anywhere; `StaffDetail` has no Leave tab) — this feature is the first surface to mount them, and the drill-in must bridge the `StaffLeaveBalances` → full `Staff` prop gap (task 14.3).
- Eligibility never branches on employment type — it keys only on Continuous_Service + Hours_Test; the only employment-type-specific path is casual selecting Casual_PAYG.
- Migration `0226` is transactional and idempotent; `0227` builds perf indexes `CONCURRENTLY` inside an `autocommit_block` in a separate file (mixing CONCURRENTLY with transactional DDL is banned). The mandatory post-migration verification is task 1.3.
- Services use `flush()` (never `commit()`) per project convention; `leave_ledger` and `leave_eligibility_notes` are append-only (corrections write compensating rows).
- Checkpoints provide incremental validation after the pure core (task 7), after the backend (task 13), and after full-stack wiring (task 15).
- This workflow produces planning artifacts only; implementation is performed when executing the tasks.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1", "2.2", "10.1"] },
    { "id": 2, "tasks": ["1.3", "3.1", "4.1", "4.3", "6.1"] },
    { "id": 3, "tasks": ["3.2", "3.3", "4.2", "4.4", "6.2", "5.1"] },
    { "id": 4, "tasks": ["5.2", "5.3", "5.4", "5.5", "5.6", "5.7", "8.1"] },
    { "id": 5, "tasks": ["8.2", "8.3", "8.4", "8.5", "8.6", "8.7", "8.8", "9.1", "11.1", "12.1", "12.7"] },
    { "id": 6, "tasks": ["9.2", "9.3", "9.4", "11.2", "11.3", "11.4", "11.5", "11.6", "11.7", "11.8", "11.9", "12.2", "12.3", "12.4", "12.5", "12.6", "12.8", "14.1"] },
    { "id": 7, "tasks": ["14.2"] },
    { "id": 8, "tasks": ["14.3", "14.4"] },
    { "id": 9, "tasks": ["14.5"] },
    { "id": 10, "tasks": ["16.1"] },
    { "id": 11, "tasks": ["16.2"] },
    { "id": 12, "tasks": ["17.1"] }
  ]
}
```
