# Staff Management Phase 2 — Tasks

## Execution policy

This phase auto-advances from Phase 1. The full execution policy is documented at the top of `.kiro/specs/staff-management-p1/tasks.md` and applies verbatim here. Quick recap:

- **Scoped testing only** — run only the tests for the files each task touches; never the full suite.
- **No interactive prompts** — use `--yes`/`-y`/`--non-interactive` flags everywhere a tool would otherwise prompt.
- **Never stop for confirmation** — only stop on a verify failure or an explicit unresolved blocking open question.
- **No watchers** — `vitest run`, `pytest`, `tsc --noEmit`; never `--watch` modes or dev servers.
- **Auto-advance** — when this phase's pre-merge gate is fully ticked and `gap-analysis.md` is empty (or deferrals documented), open `.kiro/specs/staff-management-p3/tasks.md` and resume at A1 without asking.
- **Failure handling** — log the failure detail to this phase's `gap-analysis.md`, mark the task `[~]`, and continue with the next non-dependent task. Stop only after 3 consecutive failures.

## Workstream A — Migrations

- [x] **A1. `alembic/versions/0205_leave_schema.py`**
  - Tables: `leave_types`, `leave_balances`, `leave_requests`, `leave_ledger`. All `CREATE TABLE IF NOT EXISTS`.
  - RLS + tenant_isolation policy on all four.
  - CHECK constraints on accrual_method, accrual_unit, leave_request.status, leave_ledger.reason enums.
  - `leave_types` columns include `requires_doctor_note` boolean default false and `confidential_visibility` boolean default false (per master plan back-port D1/D2).
  - `leave_requests` columns include `relationship_to_subject text` (CHECK in `'close_family','other'` when set) and `partial_day_start_time time` (both nullable; populated only for bereavement + partial-day cases respectively).
  - `staff_members.average_daily_pay_snapshot` column.
  - `organisations.overtime_handling` column with CHECK enum.
  - Backfill statutory leave_types for every existing org (**7 types per cross-phase X2 fix** — sick gets `requires_doctor_note=true`, family_violence gets `confidential_visibility=true`, toil added with `is_statutory=false` but pre-seeded universally so P3's overtime-toil flow can write without FK violations).
  - Backfill `leave_balances` for every active staff × statutory type (zero balances + anniversary date set to staff.employment_start_date).
  - **Family-violence permission backfill (R4.9):** insert one `user_permission_overrides` row per current `org_admin` user with `permission_key='leave.fv_view'` and `is_granted=true`. The actual table schema (verified at `app/modules/auth/permission_overrides.py`) is `id, user_id, permission_key, is_granted, granted_by, created_at` — there is no `org_id` column. The UNIQUE constraint `uq_user_permission_overrides_user_perm` on `(user_id, permission_key)` already exists from migration 0023 (P2-N3: spec previously mis-recommended creating a duplicate unique index — removed). Backfill SQL:
    ```sql
    INSERT INTO user_permission_overrides (id, user_id, permission_key, is_granted, granted_by, created_at)
    SELECT gen_random_uuid(), u.id, 'leave.fv_view', true, NULL, now()
    FROM users u
    WHERE u.role = 'org_admin'
    ON CONFLICT (user_id, permission_key) DO NOTHING;
    ```
    The `ON CONFLICT` clause resolves cleanly against the existing 0023 unique constraint — no pre-step needed.
  - Idempotent throughout.
  - Downgrade drops every new table + column AND deletes the `leave.fv_view` overrides (`DELETE FROM user_permission_overrides WHERE permission_key = 'leave.fv_view'`).
  - **Verify:** `alembic upgrade head`; `SELECT count(*) FROM leave_types WHERE org_id=<test_org>` returns **7** (cross-phase X2 fix: 6 statutory + 1 toil); `SELECT count(*) FROM leave_balances WHERE org_id=<test_org>` returns staff_count × 7; `SELECT count(*) FROM user_permission_overrides WHERE permission_key='leave.fv_view' AND is_granted=true` returns the org_admin count.

- [x] **A2. `alembic/versions/0206_leave_indexes.py`**
  - 8 indexes via CREATE INDEX CONCURRENTLY inside autocommit_block.
  - Mirrors 0202 template.
  - **Verify:** `SELECT indexname FROM pg_indexes WHERE tablename IN ('leave_types','leave_balances','leave_requests','leave_ledger')`.

## Workstream B — Backend module

- [x] **B1. `app/modules/leave/models.py`** — `LeaveType`, `LeaveBalance`, `LeaveRequest`, `LeaveLedger` ORM.
- [x] **B2. `app/modules/leave/schemas.py`** — Pydantic for create/update/response, `{ items, total }` list shapes.
- [x] **B3. `app/modules/leave/service.py`**
  - `submit_request` (incl. bereavement relationship validation + per-event cap per R4.7; TOIL Phase 2 guard per R4.8/G6; partial-day capture per design §4.3 step 6).
  - `approve_request` (incl. confidential-visibility permission check per R4.6/§4.3 step 3; partial-day schedule_entries write per design §4.3 step 7).
  - `reject_request`, `cancel_request` (symmetric confidential-permission check).
  - `adjust_balance`.
  - `list_balances`, `list_ledger` (both honour `_apply_confidential_filter` per design §4.4).
  - All methods write `audit_log` rows (P2-N2: singular — table is `audit_log` per `app/modules/admin/models.py:318`); confidential-leave audits redact free-text fields per design §4.3.1.
  - All methods use `await db.refresh(obj)` after `db.flush()`.
  - **Verify:** `pytest tests/unit/test_leave_request_workflow.py -v` green; bereavement-cap tests cover both `close_family` and `other` paths; FV permission denial returns 403 in approve_request; **(P2-N6) audit-redaction lint** — `tests/unit/test_leave_audit_redaction.py` parses every `write_audit_log(...)` call site in `app/modules/leave/service.py` and asserts that for `leave_request.*` actions where the underlying leave_type has `confidential_visibility=true`, the `after_value` dict-literal does NOT contain any of `{'reason', 'decision_notes', 'relationship_to_subject', 'attachment_upload_id'}`.

- [x] **B3a. `app/modules/leave/visibility.py`** — defines `FV_LEAVE_VIEW_PERMISSION = 'leave.fv_view'` constant plus the `_apply_confidential_filter(query, request, user_id, user_role)` helper from design §4.4. The filter is **synchronous** — it consumes `request.state.permission_overrides` (already loaded by `RBACMiddleware`) and calls the synchronous `app/modules/auth/rbac.py::has_permission(role, permission_key, overrides=...)` helper. No DB query for the permission check.

- [x] **B4. `app/modules/leave/accrual.py`**
  - `accrue_for_staff`, `_process_anniversary`, `_process_sick_yearly`, `_process_family_violence_yearly`.
  - Uses `days_to_hours(...)` helper (design §4.1.1) at every grant site so custom `accrual_unit='days'` types convert correctly.
  - Uses `anniversary_in_year(...)` helper (design §4.1.2) for leap-year safety.
  - Idempotency guard (existing-row SELECT keyed on `staff_id + leave_type_id + reason='accrual' + occurred_at`).
  - SAVEPOINT per staff in the batch caller.
  - **Verify:** unit test runs accrual twice on the same day → only one ledger row; days-unit test confirms a custom 5-day leave type grants 40h to a 40h/week staff; Feb-29-start staff gets anniversary correctly in non-leap years.

- [x] **B5. `app/modules/leave/public_holidays.py`**
  - `is_otherwise_working_day` with Redis cache.
  - `process_holiday_for_org` + `_grant_alt_day` + `_mark_entries_time_and_a_half`.
  - `s40a_extension`.
  - **Verify:** unit test grants alt-day when staff scheduled on OWD holiday; extends leave by one day when public holiday inside annual-leave window.

- [x] **B6. `app/modules/leave/router.py`**
  - All endpoints from design §5.
  - Module-gated by `staff_management`.
  - Approval-queue endpoint scoped by role (org_admin sees all; branch_admin scoped via `staff_location_assignments`; manager via `reporting_to`).
  - Every list endpoint that returns `leave_requests` passes its query through `_apply_confidential_filter(query, request, user_id, user_role)` from B3a before execution — applies to approval queue, per-staff request list, and ledger-with-request joins.
  - **Verify:** browser test — submit request as staff, see in approval queue as admin, approve, balance updates. Plus: as a non-org_admin user without `leave.fv_view`, the approval queue must NOT show family-violence requests submitted by other staff; submitting your own family-violence request still appears in your own list.

- [x] **B6a. `app/modules/leave/permissions_router.py`** — new sub-router at `/api/v2/permissions/fv-leave-view`:
  - `GET ""` — list org users with their current `leave.fv_view` status. Joins `users` against `user_permission_overrides` filtered by `permission_key='leave.fv_view' AND is_granted=true`.
  - `POST "/{user_id}/grant"` — calls `create_or_update_permission_override(session, user_id=..., permission_key='leave.fv_view', is_granted=true, granted_by=current_user.id, org_id=current_user.org_id)` — the existing helper at `app/modules/auth/permission_overrides.py` handles the SELECT-then-INSERT-or-UPDATE idempotency and writes the audit row automatically with action `permission_override.created` or `permission_override.updated`.
  - `POST "/{user_id}/revoke"` — calls `delete_permission_override(session, user_id=..., permission_key='leave.fv_view', deleted_by=current_user.id, org_id=current_user.org_id)`.
  - All three are `RequireOrgAdmin` per design §9.1.
  - **Verify:** grant → row appears in `user_permission_overrides` with `is_granted=true`; toggling refreshes within 60s due to RBAC cache TTL. Revoke → row deleted. Audit log entries appear under existing `permission_override.*` actions.

- [x] **B7. Register routers in `app/main.py`** — both `leave/router.py` and `leave/permissions_router.py`.

## Workstream C — Scheduled tasks

- [x] **C1. Register `accrue_leave` daily task** in `app/tasks/scheduled.py`.
  - Runs once per UTC day at 00:30.
  - Iterates all active orgs with `staff_management` enabled.
  - For each, iterates active staff, calls `accrue_for_staff`.
  - SAVEPOINT per staff.
  - Logs summary.
  - **Verify:** force-run; query ledger.

- [x] **C2. Register `process_public_holidays` daily task**.
  - Runs after accrue_leave.
  - For each org, for each public holiday in next 14 days, calls `process_holiday_for_org`.
  - **Verify:** insert a fake near-future PH; staff with OWD pattern; run task; confirm alt-day granted.

- [x] **C3. Register `update_adp_snapshots` daily task**.
  - Phase 2 placeholder calc: `hourly_rate × standard_hours_per_week × 52 / weekday_count_in_schedule × 52`.
  - Phase 4 will swap to real payslip data.
  - **Verify:** value populated for every active staff.

## Workstream D — Frontend

- [x] **D1. `LeaveTab.tsx`** — balance cards + ledger + request/adjust buttons.
- [x] **D2. `RequestLeaveModal.tsx`** — type select, dates, hours auto-calc, reason, doctor's-note upload (only when `requires_doctor_note`).
  - **Bereavement branch:** when `leave_type.code === 'bereavement'`, render a `relationship_to_subject` select (`'close_family' | 'other'`) as a required field, plus an inline banner showing the per-event cap that will apply (3 working days for close family, 1 for other). Submit-button disabled until relationship is selected.
  - **Partial-day branch:** when `start_date === end_date` AND `hours_requested < std_daily_hours`, surface `partial_day_start_time` time-picker (default = staff's `shift_start` from `availability_schedule`).
  - **Confidential banner:** when the selected leave_type has `confidential_visibility === true`, render a one-line note "This leave type is confidential — only you and your designated approver will see this request."
  - All field access uses `?.` and `?? ''` per safe-api-consumption.
- [x] **D3. `AdjustBalanceModal.tsx`** — admin only.
- [x] **D4. `LedgerTable.tsx`** — read-only, filterable by leave_type.
- [x] **D5. `BalanceCardsRow.tsx` + `CasualLeaveBanner.tsx`**.
- [x] **D6. `/leave/approvals` page (`ApprovalQueue.tsx`)**.
  - Tab strip All/Pending/Approved/Rejected.
  - Inline Approve/Reject; reject opens RejectModal asking for `decision_notes`.
- [x] **D7. `/settings/people/leave-types` page**.
  - List, sort by display_order; edit/deactivate; statutory delete blocked.
  - Above-legal-minimum badge logic.
- [x] **D8. Sidebar registration** — "Leave" item under People when module enabled.
- [x] **D9. `useStaffLeave` hook + typed API client `frontend/src/api/leave.ts`** — AbortController on every fetch; `?.` + `?? []` everywhere.
- [x] **D10. Confidential family-violence filtering on the approval queue UI** — frontend trusts the backend filter from B6 (no separate frontend check needed, since the backend never returns rows the user shouldn't see). UI test: as a non-permitted admin, navigate to approval queue → no FV rows visible; as a permitted admin → FV rows visible.

- [x] **D11. `Settings ?tab=people-permissions` (Family-Violence Leave Visibility)** (`frontend/src/pages/settings/people/PermissionsPage.tsx`):
  - Wires into the existing `Settings.tsx` tab system: add `'people-permissions'` to the `SettingsSection` union, add `{ id: 'people-permissions', label: 'People Permissions', icon: '👥', adminOnly: true, module: 'staff_management' }` to `NAV_ITEMS`, add `'people-permissions': PermissionsPage` to `SECTION_COMPONENTS`. The page is reachable via `/settings?tab=people-permissions`.
  - Lists org users from `GET /api/v2/permissions/fv-leave-view` with checkboxes.
  - Toggling fires the grant/revoke endpoint.
  - 30-day post-migration nag banner per design §9.1.
  - Permission-gated by adminOnly + module gate (already enforced by NAV_ITEMS filter logic in `Settings.tsx:78`).
  - **(P2-N11) Tab-id collision check.** Before merge, grep `frontend/src/pages/settings/Settings.tsx` for `'people-permissions'` to confirm the id doesn't already exist as a tab. If it does, rename to `'staff-permissions'` or similar.
  - **Verify:** as org_admin, navigate to `/settings?tab=people-permissions` → see user list with current FV-permission status → toggle a checkbox → query `user_permission_overrides` directly → row inserted/deleted (with `permission_key='leave.fv_view' AND is_granted=true`); toggling produces an audit row with action `permission_override.created` (or `.updated` / `.deleted`).

## Workstream E — Notifications

- [x] **E1. Approval/rejection emails** via `send_email` with `dlq_task_name='leave_decision_email'`.
- [x] **E2. Approval SMS via `send_sms`** (Phase 1 helper). Only when staff has `weekly_roster_sms_enabled` true.

## Workstream F — Tests

- [x] **F1. `tests/unit/test_leave_accrual.py`** — anniversary, sick gate, family-violence gate, casual skip, idempotency, days-to-hours conversion for a custom days-unit type, Feb-29 anniversary helper.
- [x] **F2. `tests/unit/test_leave_request_workflow.py`** — submit / approve / reject / cancel, balance invariants, **bereavement cap (close_family=3 days, other=1 day, exceeded → 422)**, **TOIL Phase 2 guard (insufficient_toil_balance → 422)**, **partial-day capture (single date, < std_daily_hours → partial_day_start_time persisted)**.
- [x] **F3. `tests/unit/test_public_holiday_engine.py`** — OWD, s40A.
- [x] **F3a. `tests/unit/test_leave_confidential_filter.py`** — `_apply_confidential_filter`:
  - User without permission cannot see other staff's family-violence requests; can see own; user with permission sees all; revocation takes effect within RBAC cache TTL.
  - **(P2-N12) Subject-vs-proxy regression** — log in as a staff member whose family-violence request was submitted ON THEIR BEHALF by a manager (`requested_by != current user`, `staff_id == current user's staff_id`). Confirm the staff sees their own request despite the proxy submission. Same flow but as the manager (without `leave.fv_view`) — manager does NOT see the request after the fact (they submitted it on behalf of a confidential subject; the subject controls ongoing visibility, not the proxy submitter).
- [x] **F4. `tests/property/test_leave_balance_invariants.py`** — Hypothesis: random sequences keep `accrued >= used` and balance non-negative.
- [x] **F5. `scripts/test_staff_leave_e2e.py`** — per R16. Additionally covers: (a) bereavement-cap rejection path; (b) confidential filter — log in as non-permitted admin, confirm FV requests hidden; (c) Settings page grants the permission, second login confirms FV requests visible.

## Workstream G — Versioning + docs

- [x] **G1. Bump 1.14.0 → 1.15.0** across pyproject.toml + frontend/package.json + mobile/package.json.
- [x] **G2. CHANGELOG `## [1.15.0]`** entry: leave types, balances, ledger, accrual engine, OWD + s40A engine, casual employees, ADP snapshot, approval queue, settings page, notifications.
- [x] **G3. Update STAFF-002, STAFF-003** in ISSUE_TRACKER with current status.
- [x] **G4. Mark Phase 2 status in `docs/future/staff-management-system.md`**.

## Pre-merge gate

Tick all per source plan §12. Specifically verify:
- All four new tables have RLS + tenant_isolation.
- No `op.create_index(...)`.
- Statutory backfill ran for every org (incl. `requires_doctor_note=true` on sick, `confidential_visibility=true` on family_violence).
- Casual staff: annual-leave card hidden, sick + family_violence still accrue pro-rata.
- `s40A` extension fires + audit row written.
- Idempotent accrual.
- Bereavement: relationship_to_subject required; per-event cap (3/1 working days) enforced server-side.
- TOIL Phase 2: requests with `accrued_hours=0` return 422 `insufficient_toil_balance`.
- Family-violence visibility: backend filter applied at every list endpoint via the synchronous `_apply_confidential_filter` helper that reads `request.state.permission_overrides`; revocation effective within 60s via existing RBAC cache.
- Settings → People → Permissions page renders user list under `/settings?tab=people-permissions`; grant/revoke writes audit rows via existing `create_or_update_permission_override` / `delete_permission_override` helpers (action names `permission_override.created`/`.updated`/`.deleted`).
- 30-day nag banner on Settings page reminds org owner to review FV-permission grants.
- Days-to-hours conversion correct for a custom 5-day leave type at a 40h/week staff (= 40h).
- Feb-29 anniversary helper produces Feb 28 in non-leap years.

**P2-N1–P2-N12 closure ticks (added 2026-05-31 internal alignment review)**
- [x] P2-N1: All references use the dot-separated permission key `leave.fv_view` (no colon-separated form anywhere). The false claim that `leave.*` wildcard auto-grants the permission has been removed; granting is always explicit per-user.
- [x] P2-N2: Spec text uses `audit_log` (singular) — matches `app/modules/admin/models.py:318`.
- [x] P2-N3: A1 backfill does NOT recreate the UNIQUE constraint — relies on the existing `uq_user_permission_overrides_user_perm` from migration 0023.
- [x] P2-N4: covered by P2-N1.
- [x] P2-N5: `organisations.overtime_handling` typed column on `organisations` (NOT a JSONB key) — Phase 4's helper resolves directly.
- [x] P2-N6: Confidential-leave audit redaction shapes specified per-action in design §4.3.1; lint test in B3 verifies no leakage.
- [x] P2-N7: `_apply_confidential_filter` code sample includes import block.
- [x] P2-N8: Sick + family-violence grants phrased as `(staff.standard_hours_per_week or 40) × 2`, not literal `80`.
- [x] P2-N9: Two distinct caches documented — public-holiday-list cache (1h) vs per-staff OWD cache (24h).
- [x] P2-N10: `GET /staff/:id/leave/ledger` surfaces `request_relationship_to_subject` via JOIN for per-event leave types.
- [x] P2-N11: Tab-id `people-permissions` checked against existing `Settings.tsx` tabs before merge.
- [x] P2-N12: `_apply_confidential_filter` keys subject access to `staff_id`, NOT `requested_by` — protects the subject when a manager submits on their behalf.

## Auto-advance to next phase

When every checkbox above is ticked AND `gap-analysis.md` is empty (or every entry has a documented reason for deferral), proceed automatically to **Phase 3** without waiting for further user prompt:

- [x] **NEXT. Begin Staff Management Phase 3** — open `.kiro/specs/staff-management-p3/tasks.md` and start at task A1. Treat the Phase 3 tasks file as the next active spec; carry forward any implementation context (alembic head now at 0206, version 1.15.0, leave_types + leave_ledger + leave_balances + leave_requests tables shipped, `organisations.overtime_handling` typed column added, `leave.fv_view` permission backfilled for org_admins, TOIL leave_type pre-seeded per cross-phase X2) from Phase 2's completion state.
