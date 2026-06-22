# Implementation Plan: Per-Staff Pay Cycle

## Overview

This plan wires the existing pay-cycle data model and services together so an
Org_User can assign a pay cycle per staff member and the timesheet/pay-run
pipeline respects it. Work proceeds backend-first: schema migration → resolver
and assignment services → staff CRUD surface → materialisation/pay-run scoping →
period payload → frontend selector and period labelling. Tests live alongside
the code they cover, with Hypothesis property tests (≥100 iterations) mapped to
design Properties 1–10.

Language: Python 3.11 (FastAPI/SQLAlchemy/Alembic) backend, TypeScript/React
(`frontend-v2`) frontend — both fixed by the design (no pseudocode), so no
language choice is required.

## Tasks

- [x] 1. Migration 0225 — relax `pay_periods` unique constraint
  - Create `alembic/versions/2026_06_13_0002-0225_pay_periods_cycle_unique.py`
    chaining `down_revision = "0224"` (head is `2026_06_13_0001-0224_employee_portal.py`).
  - Upgrade: `ALTER TABLE pay_periods DROP CONSTRAINT IF EXISTS uq_pay_periods_org_start;`
    then `CREATE UNIQUE INDEX IF NOT EXISTS uq_pay_periods_org_cycle_start ON pay_periods (org_id, pay_cycle_id, start_date);` (idempotent).
  - Downgrade: `DROP INDEX IF EXISTS uq_pay_periods_org_cycle_start;` and recreate
    `uq_pay_periods_org_start` as `UNIQUE(org_id, start_date)`.
  - _Design: Decision 5; Requirements 8.3_

  - [x] 1.1 Write migration test for the constraint change
    - In `tests/test_pay_periods_cycle_unique_migration.py`: after upgrade, two
      active cycles can each hold a period with the same `start_date`; a single
      cycle still cannot duplicate a `(org_id, pay_cycle_id, start_date)` key;
      assert the migration is idempotent (re-run is a no-op).
    - _Design: Testing Strategy → Migration test; Requirements 8.3, 9.2_

- [x] 2. Pay-cycle service: validation error, employment-type encoding, set/replace
  - In `app/modules/timesheets/pay_cycles.py` add `PayCycleValidationError(Exception)`
    carrying a machine `code` (`pay_cycle_not_found` | `pay_cycle_inactive`),
    mirroring the existing staff service error pattern.
  - Add `EMPLOYMENT_TYPE_NS = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")`
    and `employment_type_target_id(employment_type: str) -> uuid.UUID` (uuid5).
  - Add `set_staff_pay_cycle(db, *, org_id, staff_id, pay_cycle_id)` with
    delete-then-insert replace semantics: delete all `target_type='staff'` rows
    for the staff first; `None` → leave zero rows (flush, return None); else
    validate the cycle is org-scoped and active (raise `PayCycleValidationError`
    otherwise) and insert exactly one assignment.
  - _Design: Components → pay_cycles.py, Decision 2, Decision 3; Requirements 2.1–2.5, 3.1–3.4_

  - [x] 2.1 Write property test for the exactly-one-assignment invariant
    - **Property 4: Exactly-one-staff-assignment invariant under set/replace**
    - **Validates: Requirements 3.1, 3.2, 3.4 (REQ 10.5)**
    - Randomised sequences of `set_staff_pay_cycle` calls (distinct/repeated
      cycles + clears); assert staff-level row count ≤ 1 after each call and
      exactly 1 iff the last call supplied a non-null cycle id. ≥100 iterations.

  - [x] 2.2 Write unit tests for `set_staff_pay_cycle` and `employment_type_target_id`
    - Switch A→B leaves one row; re-assign A→A succeeds; clear removes the row;
      wrong-org id raises `pay_cycle_not_found`; inactive id raises
      `pay_cycle_inactive`. `employment_type_target_id` is stable/deterministic.
    - _Design: Testing Strategy → Example/unit tests; Requirements 2.4, 2.5, 3.1–3.3_

- [x] 3. Fix and batch the resolution service
  - In `app/modules/timesheets/pay_cycles.py` fix `resolve_pay_cycle_for_staff`:
    implement the `employment_type` level via `employment_type_target_id`,
    replace every `scalar_one_or_none()` with ordered `.limit(1)` +
    `.scalars().first()` (order by `created_at` then `PayCycle.id`), and require
    `PayCycle.active == True` at every level. Priority: staff → employment_type
    → branch → all → default; return first active match or `None`.
  - Add `ResolvedCycle` dataclass `(cycle: PayCycle, is_default: bool)`.
  - Add `resolve_pay_cycles_for_staff_batch(db, *, org_id, staff_members)` that
    builds the org's assignment maps (active cycles, staff/employment_type/branch
    maps, `all` cycle, default cycle, and `staff_branch` from
    `StaffLocationAssignment`) in a fixed number of queries and resolves each
    staff in memory. Re-express `resolve_pay_cycle_for_staff` as a thin wrapper
    over the same priority logic.
  - _Design: Decision 3, Decision 4, Resolution Algorithm; Requirements 4.1–4.6, 5.2, 5.3, 9.1_

  - [x] 3.1 Write property test for resolution priority order
    - **Property 1: Resolution honours the priority order**
    - **Validates: Requirements 4.1, 4.2, 4.4, 9.1**
    - ≥100 iterations over random active assignments across levels.

  - [x] 3.2 Write property test for inactive-cycle exclusion
    - **Property 2: Inactive cycles are excluded at every level**
    - **Validates: Requirements 4.5**
    - ≥100 iterations; assert resolution skips inactive matches and falls through.

  - [x] 3.3 Write property test for default fallback
    - **Property 3: Fallback to default when no specific match**
    - **Validates: Requirements 4.3, 4.6, 5.2, 5.3, 9.1, 9.3**
    - ≥100 iterations; default returned with `is_default=True`, else `None`.

- [x] 4. Cycle-scoped pay-period generation and assignment encoding
  - Update `assign_pay_cycle()` in `app/modules/timesheets/pay_cycles.py` so that
    when `target_type='employment_type'` it stores
    `target_id = employment_type_target_id(<string>)` (route passes the raw
    employment-type string).
  - Update `auto_generate_pay_periods()` existence check to be cycle-scoped:
    `WHERE org_id = :org AND pay_cycle_id = :cycle AND start_date = :start`.
  - Update `roll_pay_periods` idempotency/UNIQUE-hit recovery in
    `app/modules/payslips/period_rolling.py` (and/or its caller) to look up the
    existing row by `(org_id, pay_cycle_id, start_date)`.
  - _Design: Decision 3, Decision 5; Requirements 8.1, 8.3_

  - [x] 4.1 Write unit test for cycle-scoped generation + employment-type encoding
    - Two active cycles generate independent periods (incl. same start_date);
      an `employment_type` assignment written via the encoding path resolves.
    - _Design: Testing Strategy → Example/unit tests; Requirements 8.1, 8.3_

- [x] 5. Checkpoint — backend resolver/assignment layer
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Staff schema, service, and router integration
  - In `app/modules/staff/schemas.py`: add request-only
    `pay_cycle_id: UUID | None = None` to `StaffMemberCreate` and
    `StaffMemberUpdate`; add `pay_cycle_id`, `pay_cycle_name`,
    `pay_cycle_is_default: bool = False` (read-only) to `StaffMemberResponse`.
  - In `app/modules/staff/service.py`: `create_staff` flushes the staff row then,
    if `payload.pay_cycle_id` is set, calls `set_staff_pay_cycle` in-transaction;
    `update_staff` pops `pay_cycle_id` from the generic setattr dict and, when the
    field was present (tri-state via `model_dump(exclude_unset=True)`), calls
    `set_staff_pay_cycle` (uuid → set/replace, `None` → clear).
  - Populate the three response fields via `resolve_pay_cycles_for_staff_batch`:
    `get_staff` uses a one-element batch; `list_staff` resolves the whole page in
    one batch (no N+1).
  - In `app/modules/staff/router.py`: map `PayCycleValidationError` → HTTP 422 in
    the `POST /api/v2/staff` and `PUT /api/v2/staff/{id}` handlers.
  - _Design: Components → staff (schemas/service/router), Decision 2; Requirements 2.1–2.5, 3.3, 5.1–5.3_

  - [x] 6.1 Write property test for atomic rejection of invalid/inactive cycle
    - **Property 6: Invalid or inactive cycle is rejected atomically**
    - **Validates: Requirements 2.4, 2.5**
    - ≥100 iterations; assert no staff row and no assignment persist on rejection.

  - [x] 6.2 Write property test for clear→default resolution
    - **Property 5: Clearing the cycle resolves to default**
    - **Validates: Requirements 3.3, 2.3**
    - ≥100 iterations.

  - [x] 6.3 Write property test for persisted-assignment round-trip
    - **Property 7: Persisted assignment round-trips to the response**
    - **Validates: Requirements 2.1, 2.2, 5.1**
    - ≥100 iterations; created/updated staff response `pay_cycle_id` equals the
      chosen cycle with `pay_cycle_is_default=false`; re-read yields the same.

  - [x] 6.4 Write route tests for staff create/update (422 + rollback)
    - In `tests/test_staff_router.py` (or a new `tests/test_staff_pay_cycle_router.py`):
      `POST`/`PUT /api/v2/staff` with valid `pay_cycle_id` returns 201/200 with
      the resolved cycle; invalid/inactive id returns 422 and persists nothing.
    - _Design: Testing Strategy → Route tests; Requirements 2.1, 2.2, 2.4, 2.5, 5.1_

- [x] 7. Cycle-scoped materialisation
  - In `app/modules/timesheets/service.py` make `materialise_missing_timesheets`
    cycle-scoped: load the `PayPeriod` and read `period.pay_cycle_id`; if `NULL`
    (legacy period) preserve existing behaviour. Otherwise gather candidate
    active staff as today (clock/fixed sources, and all active when
    `include_all_active`), batch-resolve via `resolve_pay_cycles_for_staff_batch`,
    and create a timesheet only when the staff's resolved cycle id equals
    `period.pay_cycle_id`. Preserve fixed-staff rostered-minute seeding; excluded
    staff are out of scope (not reported as `no_activity`).
  - _Design: Components → service.py (materialisation), Decision 6; Requirements 6.1–6.4, 9.2_

  - [x] 7.1 Write property test for cycle-scoped materialisation membership
    - **Property 8: Cycle-scoped materialisation membership**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 7.1, 7.2**
    - ≥100 iterations; single- and multi-cycle generators; materialised set
      equals the resolved-matching set exactly (REQ 10.4).

  - [x] 7.2 Write property test for single-cycle regression equivalence
    - **Property 9: Single-cycle regression equivalence**
    - **Validates: Requirements 9.1, 9.2, 9.3 (REQ 10.6)**
    - ≥100 iterations; materialised set equals a pre-feature reference
      computation (clock + fixed + include_all_active).

- [x] 8. Pay-run null-cycle guard
  - In `app/modules/timesheets/payrun.py` add `PayRunScopingError` and guard at
    the top of `run_pay_period`: load the `PayPeriod`; if missing or
    `pay_cycle_id is None`, raise `PayRunScopingError("pay_period_missing_cycle")`.
    Map it to HTTP 422 in the pay-run route. No per-staff filtering needed —
    timesheets are already cycle-scoped by materialisation.
  - _Design: Decision 6, Components → payrun.py; Requirements 7.1–7.3, 8.5_

  - [x] 8.1 Write property test for independent per-cycle pay runs
    - **Property 10: Independent per-cycle pay runs**
    - **Validates: Requirements 7.3**
    - ≥100 iterations; two-cycle generator; per-period pay-run staff sets are
      disjoint by cycle.

  - [x] 8.2 Write unit test for the run_pay_period null-cycle guard
    - A period with `pay_cycle_id=NULL` is refused (422); a scoped period runs.
    - _Design: Testing Strategy → Example/unit tests; Requirements 8.5_

- [x] 9. Pay-period payload carries the cycle name
  - In `app/modules/payslips/schemas.py` add `pay_cycle_name: str | None = None`
    to `PayPeriodResponse`.
  - In `app/modules/payslips/router.py` `list_pay_periods` left-joins `PayCycle`
    (`outerjoin(PayCycle, PayCycle.id == PayPeriod.pay_cycle_id)`) and populates
    `pay_cycle_name`.
  - _Design: Components → period generation + cycle name; Requirements 8.2, 8.3_

  - [x] 9.1 Write unit test for `list_pay_periods` cycle name + two-cycle same-date
    - Response carries `pay_cycle_name`; two cycles sharing a date range are both
      present and distinguishable by name (after the 0225 migration).
    - _Design: Testing Strategy → Example/unit tests; Requirements 8.2, 8.3_

- [x] 10. Checkpoint — backend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Frontend API types
  - In `frontend-v2/src/api/staff.ts` extend the staff create/update payload type
    with optional `pay_cycle_id` and the staff response type with `pay_cycle_id`,
    `pay_cycle_name`, `pay_cycle_is_default`. Confirm the pay-periods type used by
    timesheets carries `pay_cycle_name` (extend `api/payslips.ts` if needed).
  - _Design: Components → Frontend (api/staff.ts); Requirements 1.1, 5.1, 8.2_

- [x] 12. Staff form pay-cycle selector (Add + Edit)
  - [x] 12.1 Add the selector to the StaffList Add modal
    - In `frontend-v2/src/pages/staff/StaffList.tsx`: fetch
      `GET /api/v2/pay-cycles/` on mount (consume safely with `?.`/`?? []`);
      render the `<select>` only when active cycles exist, otherwise hide it and
      show the "configure under Timesheets → Settings" hint; include a "Use
      organisation default" empty option; submit `pay_cycle_id` in the payload.
    - _Design: Components → Frontend (StaffList); Requirements 1.1, 1.2, 1.4, 1.5, 1.6, 2.1_

  - [x] 12.2 Add the selector to the OverviewTab Edit form
    - In `frontend-v2/src/pages/staff/tabs/OverviewTab.tsx`: same fetch + hidden
      selector behaviour; prefill from `staff.pay_cycle_id` when
      `pay_cycle_is_default` is false; "Use organisation default" sends `null` to
      clear an existing assignment; submit `pay_cycle_id`.
    - _Design: Components → Frontend (OverviewTab); Requirements 1.3, 1.4, 1.5, 1.6, 2.2, 3.3_

  - [x] 12.3 Write frontend tests for the selector
    - Selector hidden + configure hint when no active cycles (REQ 1.5, 1.6);
      populated and prefilled from the staff response (REQ 1.3); submit includes
      `pay_cycle_id`; "Use organisation default" sends `null`. Safe API
      consumption throughout.
    - _Design: Testing Strategy → Frontend tests; Requirements 1.3, 1.5, 1.6, 2.1, 2.2_

- [x] 13. Multi-cycle period generation and labelling in timesheets UI
  - [x] 13.1 Generate periods for all active cycles and label by cycle
    - In `frontend-v2/src/pages/staff-timesheets/TimesheetsTab.tsx`: replace the
      "use first cycle" bootstrap with a loop over all active cycles calling
      `POST /api/v2/pay-cycles/{id}/generate-periods/`; fetch
      `/api/v2/pay-periods` and group/label period options by `pay_cycle_name`
      (e.g. `optgroup` per cycle); the selected period id drives materialise.
    - _Design: Components → Frontend (TimesheetsTab); Requirements 8.1, 8.2, 8.3, 8.4_

  - [x] 13.2 Apply the same generation + labelling to PayRunsTab
    - In `frontend-v2/src/pages/staff-timesheets/PayRunsTab.tsx`: same multi-cycle
      generation and cycle-name grouping; the selected period drives the pay run.
    - _Design: Components → Frontend (PayRunsTab); Requirements 8.1, 8.2, 8.3, 8.4_

  - [x] 13.3 Write frontend tests for period grouping
    - Periods grouped/labelled by cycle name; periods sharing a date range across
      cycles are distinguishable; selecting a period drives the
      materialise/pay-run call with that period id. Safe API consumption.
    - _Design: Testing Strategy → Frontend tests; Requirements 8.2, 8.3, 8.4_

- [x] 14. Final verification
  - Run backend tests including property tests: `pytest tests/ -q` (and the
    per-staff-pay-cycle property/unit tests specifically).
  - Run `npx tsc --noEmit` and frontend vitest in `frontend-v2`.
  - Run `alembic upgrade head` against a test DB to confirm migration 0225 applies
    cleanly and is idempotent.
  - Manual end-to-end smoke (document steps; not automated): assign a weekly cycle
    to one staff member and a fortnightly to another, generate periods for both
    cycles, confirm materialisation and pay runs are cycle-scoped and separated.
  - _Design: Testing Strategy; Requirements 6.x, 7.x, 8.x, 9.x, 10.x_

## Notes

- Tasks marked with `*` are optional (tests) and can be skipped for a faster MVP,
  but they encode design Properties 1–10 and the regression guarantees in REQ 10.
- Each task references specific requirements and/or design decisions/properties
  for traceability.
- Checkpoints (tasks 5, 10) ensure incremental backend validation before the
  frontend work begins.
- Property tests use Hypothesis with ≥100 iterations and tag each with
  `# Feature: per-staff-pay-cycle, Property {n}` per the Testing Strategy.
- No new tables; the only schema change is the `pay_periods` unique-constraint
  relaxation (Decision 5). Decision 1 (no `staff_members` migration) stands.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "2"] },
    { "id": 1, "tasks": ["1.1", "2.1", "2.2", "3"] },
    { "id": 2, "tasks": ["3.1", "3.2", "3.3", "4"] },
    { "id": 3, "tasks": ["4.1", "6", "11"] },
    { "id": 4, "tasks": ["6.1", "6.2", "6.3", "6.4", "7", "8", "9"] },
    { "id": 5, "tasks": ["7.1", "7.2", "8.1", "8.2", "9.1", "12.1", "12.2", "13.1", "13.2"] },
    { "id": 6, "tasks": ["12.3", "13.3"] }
  ]
}
```
