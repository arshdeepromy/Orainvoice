# Staff Management Phase 2 — Tasks

## Workstream A — Migrations

- [ ] **A1. `alembic/versions/0205_leave_schema.py`**
  - Tables: `leave_types`, `leave_balances`, `leave_requests`, `leave_ledger`. All `CREATE TABLE IF NOT EXISTS`.
  - RLS + tenant_isolation policy on all four.
  - CHECK constraints on accrual_method, accrual_unit, leave_request.status, leave_ledger.reason enums.
  - `staff_members.average_daily_pay_snapshot` column.
  - `organisations.overtime_handling` column with CHECK enum.
  - Backfill statutory leave_types for every existing org (6 types).
  - Backfill `leave_balances` for every active staff × statutory type (zero balances + anniversary date set to staff.employment_start_date).
  - Idempotent throughout.
  - Downgrade drops every new table + column.
  - **Verify:** `alembic upgrade head`; `SELECT count(*) FROM leave_types WHERE org_id=<test_org>` returns 6; `SELECT count(*) FROM leave_balances WHERE org_id=<test_org>` returns staff_count × 6.

- [ ] **A2. `alembic/versions/0206_leave_indexes.py`**
  - 8 indexes via CREATE INDEX CONCURRENTLY inside autocommit_block.
  - Mirrors 0202 template.
  - **Verify:** `SELECT indexname FROM pg_indexes WHERE tablename IN ('leave_types','leave_balances','leave_requests','leave_ledger')`.

## Workstream B — Backend module

- [ ] **B1. `app/modules/leave/models.py`** — `LeaveType`, `LeaveBalance`, `LeaveRequest`, `LeaveLedger` ORM.
- [ ] **B2. `app/modules/leave/schemas.py`** — Pydantic for create/update/response, `{ items, total }` list shapes.
- [ ] **B3. `app/modules/leave/service.py`**
  - `submit_request`, `approve_request`, `reject_request`, `cancel_request`.
  - `adjust_balance`.
  - `list_balances`, `list_ledger`.
  - All methods write `audit_logs` rows.
  - All methods use `await db.refresh(obj)` after `db.flush()`.
  - **Verify:** `pytest tests/unit/test_leave_request_workflow.py -v` green.

- [ ] **B4. `app/modules/leave/accrual.py`**
  - `accrue_for_staff`, `_process_anniversary`, `_process_sick_yearly`, `_process_family_violence_yearly`.
  - Idempotency guard (existing-row SELECT).
  - SAVEPOINT per staff in the batch caller.
  - **Verify:** unit test runs accrual twice on the same day → only one ledger row.

- [ ] **B5. `app/modules/leave/public_holidays.py`**
  - `is_otherwise_working_day` with Redis cache.
  - `process_holiday_for_org` + `_grant_alt_day` + `_mark_entries_time_and_a_half`.
  - `s40a_extension`.
  - **Verify:** unit test grants alt-day when staff scheduled on OWD holiday; extends leave by one day when public holiday inside annual-leave window.

- [ ] **B6. `app/modules/leave/router.py`**
  - All endpoints from design §5.
  - Module-gated by `staff_management`.
- Approval-queue endpoint scoped by role (org_admin sees all; branch_admin scoped via `staff_location_assignments`; manager via `reporting_to`).
  - Confidential-visibility filter for family_violence requests.
  - **Verify:** browser test — submit request as staff, see in approval queue as admin, approve, balance updates.

- [ ] **B7. Register router in `app/main.py`**.

## Workstream C — Scheduled tasks

- [ ] **C1. Register `accrue_leave` daily task** in `app/tasks/scheduled.py`.
  - Runs once per UTC day at 00:30.
  - Iterates all active orgs with `staff_management` enabled.
  - For each, iterates active staff, calls `accrue_for_staff`.
  - SAVEPOINT per staff.
  - Logs summary.
  - **Verify:** force-run; query ledger.

- [ ] **C2. Register `process_public_holidays` daily task**.
  - Runs after accrue_leave.
  - For each org, for each public holiday in next 14 days, calls `process_holiday_for_org`.
  - **Verify:** insert a fake near-future PH; staff with OWD pattern; run task; confirm alt-day granted.

- [ ] **C3. Register `update_adp_snapshots` daily task**.
  - Phase 2 placeholder calc: `hourly_rate × standard_hours_per_week × 52 / weekday_count_in_schedule × 52`.
  - Phase 4 will swap to real payslip data.
  - **Verify:** value populated for every active staff.

## Workstream D — Frontend

- [ ] **D1. `LeaveTab.tsx`** — balance cards + ledger + request/adjust buttons.
- [ ] **D2. `RequestLeaveModal.tsx`** — type select, dates, hours auto-calc, reason, doctor's-note upload (only when `requires_doctor_note`).
- [ ] **D3. `AdjustBalanceModal.tsx`** — admin only.
- [ ] **D4. `LedgerTable.tsx`** — read-only, filterable by leave_type.
- [ ] **D5. `BalanceCardsRow.tsx` + `CasualLeaveBanner.tsx`**.
- [ ] **D6. `/leave/approvals` page (`ApprovalQueue.tsx`)**.
  - Tab strip All/Pending/Approved/Rejected.
  - Inline Approve/Reject; reject opens RejectModal asking for `decision_notes`.
- [ ] **D7. `/settings/people/leave-types` page**.
  - List, sort by display_order; edit/deactivate; statutory delete blocked.
  - Above-legal-minimum badge logic.
- [ ] **D8. Sidebar registration** — "Leave" item under People when module enabled.
- [ ] **D9. `useStaffLeave` hook + typed API client `frontend/src/api/leave.ts`** — AbortController on every fetch; `?.` + `?? []` everywhere.
- [ ] **D10. Confidential family-violence filtering on the approval queue UI** — when staff has `confidential_visibility=true` and current admin lacks the per-org permission, hide the row.

## Workstream E — Notifications

- [ ] **E1. Approval/rejection emails** via `send_email` with `dlq_task_name='leave_decision_email'`.
- [ ] **E2. Approval SMS via `send_sms`** (Phase 1 helper). Only when staff has `weekly_roster_sms_enabled` true.

## Workstream F — Tests

- [ ] **F1. `tests/unit/test_leave_accrual.py`** — anniversary, sick gate, casual skip, idempotency.
- [ ] **F2. `tests/unit/test_leave_request_workflow.py`** — submit / approve / reject / cancel, balance invariants.
- [ ] **F3. `tests/unit/test_public_holiday_engine.py`** — OWD, s40A.
- [ ] **F4. `tests/property/test_leave_balance_invariants.py`** — Hypothesis: random sequences keep `accrued >= used` and balance non-negative.
- [ ] **F5. `scripts/test_staff_leave_e2e.py`** — per R16.

## Workstream G — Versioning + docs

- [ ] **G1. Bump 1.14.0 → 1.15.0** across pyproject.toml + frontend/package.json + mobile/package.json.
- [ ] **G2. CHANGELOG `## [1.15.0]`** entry: leave types, balances, ledger, accrual engine, OWD + s40A engine, casual employees, ADP snapshot, approval queue, settings page, notifications.
- [ ] **G3. Update STAFF-002, STAFF-003** in ISSUE_TRACKER with current status.
- [ ] **G4. Mark Phase 2 status in `docs/future/staff-management-system.md`**.

## Pre-merge gate

Tick all per source plan §12. Specifically verify:
- All four new tables have RLS + tenant_isolation.
- No `op.create_index(...)`.
- Statutory backfill ran for every org.
- Casual staff: annual-leave card hidden, sick still accrues pro-rata.
- `s40A` extension fires + audit row written.
- Idempotent accrual.
- Family-violence visibility honors per-org toggle.
