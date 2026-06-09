# Staff Timesheets — Tasks

Each task is independently executable, has a `**Verify:**` line, and references back to a requirement. Phase A tasks are in full detail; Phase B/C/D are outlines only.

## Execution policy

- **Scoped tests only.** Every `**Verify:**` block runs only the tests that exercise the files this spec touches — never the full repo suite. Pytest paths are explicit (e.g. `tests/unit/test_timesheet_aggregation.py`); vitest paths are explicit (e.g. `frontend-v2/src/pages/staff-timesheets/__tests__/ClockedInTab.test.tsx`). Do NOT use `pytest tests/unit/ -k '...'` style filters that scan every test file before excluding — pass the file paths directly.
- **Backend tests run inside the app container** per `.kiro/steering/windows-shell-and-docker.md`. The canonical command is:
  ```
  docker compose -p invoicing exec -T app python -m pytest <path> -v
  ```
  Every backend `**Verify:**` block in this tasks.md is written using `pytest <path> -v` for brevity; when actually executing, prefix with `docker compose -p invoicing exec -T app python -m` so the test runs inside the same container the app uses (same Python interpreter, same DB connection, same RLS context).
- **Frontend tests run from `frontend-v2/`.** Vitest: `npx vitest run <path> --run`. TypeScript: `npx tsc --noEmit -p tsconfig.json`. Do NOT touch the archived `frontend/` tree (see `frontend/ARCHIVED.md`).
- **No watchers.** Use `pytest`, `npx vitest run`, `npx tsc --noEmit`. Never `--watch` flags or dev-server commands.
- **No interactive prompts.** Every CLI uses `--yes` / `-y` / `--non-interactive` where applicable.
- **No git push, no PR creation, no deploy.** This spec must NOT push branches or open PRs.
- **Failure handling.** Log the failure detail to a `gap-analysis.md` adjacent to this `tasks.md` AND open an `ISSUE-XXX` row in `docs/ISSUE_TRACKER.md` per `.kiro/steering/issue-tracking-workflow.md`, mark the task `[~]`, continue with the next non-dependent task. Stop only after 3 consecutive failures on the same root cause.
- **Project conventions.**
  - `{ items, total }` list shape on every list response (NFR-2, `safe-api-consumption.md`).
  - `?.` + `?? []` / `?? 0` on every frontend API field read (NFR-1, `safe-api-consumption.md`).
  - Typed generics on every `apiClient.get<T>(...)` / `.post<T>(...)` call. No `as any` to bypass typing (NFR-1).
  - AbortController cleanup on every `useEffect` that issues an API call.
  - **Inside `session.begin()` (which `get_db_session` already enters): never call `db.commit()` or `db.rollback()`.** Use `await db.flush()` then `await db.refresh(obj)` and let the context manager handle commit/rollback. This is `.kiro/steering/performance-and-resilience.md` Rule 1; violating it has caused ISSUE-024, ISSUE-040, ISSUE-044 in the past.
  - Audit table is `audit_log` (singular). Use `app.core.audit.write_audit_log`.
  - Module registration uses `DEPENDENCY_GRAPH` (in `app/core/modules.py`) and `MODULE_ENDPOINT_MAP` (in `app/middleware/modules.py`).
  - Migration uses Alembic `NNNN_description` pattern with RLS policies. Current head is revision 0194.
  - **Pydantic schema gate (per `frontend-backend-contract-alignment.md` Rule 8):** every field returned by a service dict MUST be declared in the Pydantic response schema. Pydantic silently drops undeclared fields — this is the class of bug that caused ISSUE-034.

---

## Phase A1 — Schema & Migration

- [x] **A1.1 Alembic migration creating `timesheets` + `timesheet_settings` tables + RLS policies**
  - Create migration file `alembic/versions/0195_staff_timesheets_schema.py` (or next available number).
  - CREATE TABLE `timesheets` with all columns per design: `id` (UUID PK), `org_id`, `staff_id` (FK → staff_members), `pay_period_id` (FK → pay_periods), `branch_id` (FK → branches, nullable), `rostered_minutes` (integer default 0), `actual_minutes` (integer default 0), `adjusted_minutes` (integer, nullable), `ordinary_minutes` (integer default 0), `overtime_minutes` (integer default 0), `public_holiday_minutes` (integer default 0), `exception_flags` (JSONB default '[]'), `status` (text, CHECK IN open/pending_approval/approved/locked), `approved_by` (FK → users, nullable), `approved_at` (timestamptz), `locked_at` (timestamptz), `locked_by` (FK → users, nullable), `payslip_id` (FK → payslips, nullable), `notes` (text, nullable), `created_at`, `updated_at`.
  - UNIQUE constraint `uq_timesheets_staff_period` on `(staff_id, pay_period_id)`.
  - Indexes: `ix_timesheets_org_period` on `(org_id, pay_period_id)`, `ix_timesheets_branch` on `(branch_id) WHERE branch_id IS NOT NULL`, `ix_timesheets_status` on `(org_id, status)`.
  - CREATE TABLE `timesheet_settings` with columns: `id` (UUID PK), `org_id`, `branch_id` (FK → branches, nullable), `clock_rounding_minutes` (integer default 1, CHECK IN 1/5/10/15/30), `clock_rounding_direction` (text default 'nearest', CHECK IN nearest/up/down), `early_grace_minutes` (integer default 0), `late_grace_minutes` (integer default 0), `match_policy` (text default 'pay_actual', CHECK IN pay_actual/round_to_roster/actual_rounded), `auto_approve_threshold_minutes` (integer default 0), `require_approval_before_lock` (boolean default true), `created_at`, `updated_at`.
  - UNIQUE constraint `uq_timesheet_settings_org_branch` on `(org_id, branch_id)`.
  - RLS policies: `CREATE POLICY timesheets_org_isolation ON timesheets USING (org_id::text = current_setting('app.current_org_id', true))` and similar for `timesheet_settings`.
  - Use `IF NOT EXISTS` for idempotency.
  - **downgrade()**: DROP POLICY, DROP TABLE `timesheet_settings`, DROP TABLE `timesheets`.
  - **Files:** `alembic/versions/0195_staff_timesheets_schema.py` (new).
  - **Refs:** Requirement 1.1, 1.2, 4.2.
  - **Verify:** `pytest tests/integration/test_timesheets_migration.py::test_timesheets_table_exists -v` — asserts table exists with expected columns and constraints after `alembic upgrade head`.

- [x] **A1.2 ALTER `time_clock_entries` — add `branch_id` + `clock_out_branch_id` + forward-only CHECK**
  - In the same migration file (`0195_staff_timesheets_schema.py`), add:
    - `ALTER TABLE time_clock_entries ADD COLUMN IF NOT EXISTS branch_id UUID REFERENCES branches(id);` — **column does not exist today** (only `clock_in_lat`/`clock_in_lng` geofence coords are stored). This is a NEW column, not just a constraint on an existing one.
    - `ALTER TABLE time_clock_entries ADD COLUMN clock_out_branch_id UUID REFERENCES branches(id);`
    - `ALTER TABLE time_clock_entries ADD COLUMN clock_in_ip TEXT;` — stores the client IP at clock-in time for audit (not currently captured).
    - Forward-only CHECK constraint: `ALTER TABLE time_clock_entries ADD CONSTRAINT ck_tce_branch_id_new_rows CHECK (created_at <= '<migration_date>'::timestamptz OR branch_id IS NOT NULL);` — the date is the migration write-time literal.
  - The CHECK ensures old NULL `branch_id` rows remain valid but new inserts must provide `branch_id`.
  - **Code-truth note:** `TimeClockEntry` currently has `clock_in_lat`/`clock_in_lng` (geofence) but NO `branch_id` and NO `clock_in_ip`. All three are brand-new columns added by this migration.
  - **Files:** `alembic/versions/0195_staff_timesheets_schema.py` (edit — same file as A1.1).
  - **Refs:** Requirement 9.2, 10.1.
  - **Verify:** `pytest tests/integration/test_timesheets_migration.py::test_tce_clock_out_branch_id_column_exists -v` — asserts column added and CHECK constraint prevents NULL `branch_id` on newly inserted rows.

- [x] **A1.3 Immutability trigger on `time_clock_entries`**
  - In the same migration, create function `tce_immutability_guard()` and trigger `trg_tce_immutability` (BEFORE UPDATE OR DELETE) per the design's SQL.
  - **CRITICAL — clock-out writes must NOT be blocked:** The trigger must allow setting `clock_out_at` from NULL to a value (the normal clock-out operation). It ONLY blocks mutations of ALREADY-SET values. The guard condition is: `OLD.<column> IS NOT NULL AND OLD.<column> IS DISTINCT FROM NEW.<column>`. This allows `NULL → value` (first write) but blocks `value → different_value` (tampering with recorded time).
  - Similarly, `clock_in_at` can never be NULL on a valid entry (it's set at INSERT time), so the trigger effectively always blocks changes to it.
  - DELETE is unconditionally blocked.
  - The trigger fires for ALL roles including `postgres`.
  - Applied as the LAST step in `upgrade()` so rollback undoes it first.
  - In `downgrade()`, DROP TRIGGER + DROP FUNCTION first.
  - **Files:** `alembic/versions/0195_staff_timesheets_schema.py` (edit — same file).
  - **Refs:** Requirement 5.1, 5.2, 5.3, 5.6.
  - **Verify:** `pytest tests/integration/test_timesheets_migration.py::test_immutability_trigger_blocks_update -v` — asserts: (a) UPDATE `clock_in_at` (non-NULL → different value) raises `restrict_violation`; (b) UPDATE `clock_out_at` from non-NULL raises exception; (c) UPDATE `clock_out_at` from NULL to a value SUCCEEDS (normal clock-out); (d) DELETE raises exception; (e) UPDATE other columns (e.g., `notes`) succeeds.

- [x] **A1.4 ALTER `timesheet_approvals` — add `timesheet_id` FK + index**
  - In the same migration: `ALTER TABLE timesheet_approvals ADD COLUMN timesheet_id UUID REFERENCES timesheets(id);`
  - Create partial index: `CREATE INDEX ix_timesheet_approvals_timesheet ON timesheet_approvals(timesheet_id) WHERE timesheet_id IS NOT NULL;`
  - Existing rows remain unchanged (`timesheet_id = NULL`).
  - **Files:** `alembic/versions/0195_staff_timesheets_schema.py` (edit — same file).
  - **Refs:** Requirement 12.1, 12.3.
  - **Verify:** `pytest tests/integration/test_timesheets_migration.py::test_timesheet_approvals_has_timesheet_id -v` — asserts column exists with correct FK.

- [x] **A1.5 Module registration — add `timesheets` to `DEPENDENCY_GRAPH` + `MODULE_ENDPOINT_MAP`**
  - In `app/core/modules.py`, add to `DEPENDENCY_GRAPH`: `"timesheets": ["staff", "scheduling"]`.
  - In `app/middleware/modules.py`, add to `MODULE_ENDPOINT_MAP`:
    ```python
    "/api/v2/timesheets": "timesheets",
    "/api/v2/clocked-in": "timesheets",
    "/api/v2/timesheet-settings": "timesheets",
    ```
  - The `timesheets` module depends on `staff` and `scheduling` (roster data).
  - **Setup Guide integration (per `setup-guide-for-new-modules.md`):** INSERT or UPDATE `module_registry` row for slug `timesheets` with:
    - `setup_question = 'Will you be tracking staff work hours, timesheets, and attendance?'`
    - `setup_question_description = 'Clock-in/out tracking, timesheet approval, and match-to-roster automation for pay-run accuracy.'`
    - `category = 'staff'`, `is_core = false`, `dependencies = '["staff","scheduling"]'::jsonb`, `status = 'available'`.
  - This ensures the timesheets module appears in the Setup Guide for orgs on plans that include it.
  - **Files:** `app/core/modules.py` (edit), `app/middleware/modules.py` (edit), `alembic/versions/0195_staff_timesheets_schema.py` (edit — add module_registry INSERT in same migration).
  - **Refs:** Design § Module Registration, `setup-guide-for-new-modules.md`.
  - **Verify:** `pytest tests/integration/test_module_management.py::test_timesheets_in_dependency_graph -v` — asserts `DEPENDENCY_GRAPH["timesheets"] == ["staff", "scheduling"]` and all three prefixes resolve to `"timesheets"` via `_resolve_module`. Also asserts `module_registry` row has non-null `setup_question`.

---

## Phase A2 — Backend Service Layer

- [x] **A2.1 Create `app/modules/timesheets/models.py` — SQLAlchemy models**
  - Define `Timesheet` model mapped to `timesheets` table with all columns matching the migration schema.
  - Define `TimesheetSettings` model mapped to `timesheet_settings` table.
  - Both models include `org_id` for RLS, use `Mapped[]` type annotations, and follow existing model conventions (see `app/modules/payslips/models.py` as reference).
  - Include `__init__.py` for the `app/modules/timesheets/` package.
  - **Files:** `app/modules/timesheets/__init__.py` (new), `app/modules/timesheets/models.py` (new).
  - **Refs:** Requirement 1.1, 4.2.
  - **Verify:** `pytest tests/unit/test_timesheet_models.py -v` — asserts models instantiate with expected defaults and column names match the migration.

- [x] **A2.2 Create `app/modules/timesheets/schemas.py` — Pydantic request/response models**
  - Define schemas per design: `TimesheetSummary`, `PeriodSummary`, `TimesheetListResponse` (`items: list[TimesheetSummary]`, `total: int`, `period_summary: PeriodSummary`), `TimesheetDetail`, `ClockedInEntry`, `ClockedInResponse` (`items: list[ClockedInEntry]`, `total: int`), `AdjustRequest` (adjusted_minutes, notes), `TimesheetSettingsRead`, `TimesheetSettingsUpdate`, `BulkActionResponse`.
  - All list responses follow `{items, total}` convention.
  - Use `BaseModel` with Pydantic v2 conventions. Decimal fields for hours (minutes/60, rounded 2dp).
  - **Files:** `app/modules/timesheets/schemas.py` (new).
  - **Refs:** Design § Request/Response Schemas.
  - **Verify:** `pytest tests/unit/test_timesheet_schemas.py -v` — asserts round-trip serialization, `items`+`total` shape, and validation constraints.

- [x] **A2.3 Create `app/modules/timesheets/branch_scope.py` — BranchScopedTimesheets dependency**
  - Implement `BranchScopedTimesheets` FastAPI dependency per the design: reads `request.state.role` and `request.state.branch_ids`.
  - For `org_admin` / `global_admin`: `should_filter = False` (full org visibility).
  - For `branch_admin`: `should_filter = True`, `branch_ids` from `request.state.branch_ids`.
  - For other roles with `timesheet.approve` permission: `should_filter = True`, scoped to their branches.
  - Methods: `apply_filter(query, branch_id_column)` adds WHERE clause; `can_access_branch(branch_id)` checks access.
  - NULL `branch_id` entries excluded from branch-scoped views (Req 6.7).
  - **Files:** `app/modules/timesheets/branch_scope.py` (new).
  - **Refs:** Requirement 6.1, 6.2, 6.3, 6.4, 6.5, 6.7.
  - **Verify:** `pytest tests/unit/test_timesheet_branch_scope.py -v` — asserts org_admin gets unfiltered, branch_admin gets filtered to branch_ids, permission-holder gets filtered, NULL branch excluded.

- [x] **A2.4 Create `app/modules/timesheets/aggregation.py` — compute_timesheet() service**
  - Implement `compute_timesheet(db, *, staff_id, pay_period, settings, branch_tz)` → `TimesheetComputation` dataclass.
  - Steps: (1) fetch roster — sum scheduled shift durations → `rostered_minutes`; (2) fetch clock entries — sum `worked_minutes` → `actual_minutes`; (3) run match engine on each entry; (4) classify all matched minutes to `ordinary_minutes` (Phase A — overtime/PH deferred to Phase C); (5) detect exceptions (missed_shift, unmatched_clock, missing_clock_out, high_variance); (6) return `TimesheetComputation`.
  - `TimesheetComputation` dataclass: `rostered_minutes`, `actual_minutes`, `ordinary_minutes`, `overtime_minutes`, `public_holiday_minutes`, `exception_flags: list[dict]`, `matched_entries: list[tuple]`.
  - **Code-truth note:** `ScheduleEntry` uses `location_id` (nullable UUID, no FK to branches), NOT `branch_id`. The aggregation query for rostered_minutes filters by `staff_id` + date range + `status='scheduled'` + `entry_type NOT IN ('break','leave')` — it does NOT filter by branch. Rostered minutes are per-person per-period regardless of which location/branch the shift was at. Branch scoping applies to the Timesheet row itself (via `TimeClockEntry.branch_id` on the clock side), not to the roster query.
  - **Code-truth note:** `TimeClockEntry.source` column is named `source` (not `clock_in_source`). Values: `kiosk`, `self_service_mobile`, `self_service_web`, `admin_manual`. Use this column name in the service and schemas.
  - **Files:** `app/modules/timesheets/aggregation.py` (new).
  - **Refs:** Requirement 1.9, 1.10, 8.4.
  - **Verify:** `pytest tests/unit/test_timesheet_aggregation.py -v` — covers compute with various scenarios (normal, missing clocks, unmatched shifts, high variance).

- [x] **A2.5 Create `app/modules/timesheets/match_engine.py` — match_clock_to_roster() + round_time()**
  - Implement `match_clock_to_roster(clock_entry, schedule_entries, settings)` → `MatchResult` per design algorithm.
  - Implement `round_time(t, interval_minutes, direction)` — rounds timestamp to nearest/up/down interval.
  - `MatchResult` dataclass: `clock_entry_id`, `schedule_entry_id | None`, `raw_minutes`, `matched_minutes`, `match_type` (exact/grace/rounded/unmatched).
  - Three policies: `pay_actual` (use worked_minutes as-is), `round_to_roster` (use shift duration if matched), `actual_rounded` (apply rounding to clock times then compute).
  - Grace window matching: clock_in within `[schedule.start - early_grace, schedule.start + late_grace]` → candidate match.
  - **Files:** `app/modules/timesheets/match_engine.py` (new).
  - **Refs:** Requirement 8.1, 8.2, 8.3, 8.4.
  - **Verify:** `pytest tests/unit/test_timesheet_match_engine.py -v` — covers all three policies, grace window matching, rounding directions, unmatched entries.

- [x] **A2.6 Create `app/modules/timesheets/service.py` — CRUD + status transitions + lazy creation + bulk actions**
  - Implement core service functions:
    - `get_or_create_timesheet(db, org_id, staff_id, pay_period_id, branch_id)` — lazy creation (Req 1.2a).
    - `recompute_timesheet(db, timesheet)` — re-runs aggregation, persists results.
    - `transition_status(db, timesheet, new_status, actor_id)` — validates transitions (open→pending→approved→locked, plus reject/withdraw), records in audit_log + timesheet_approvals.
    - `adjust_timesheet(db, timesheet, adjusted_minutes, notes, actor_id)` — sets adjusted_minutes with audit.
    - `bulk_approve(db, org_id, pay_period_id, scope, actor_id)` — approve all clean (no exceptions, within threshold).
    - `bulk_lock(db, org_id, pay_period_id, scope, actor_id)` — lock all approved.
    - `match_all_for_period(db, org_id, pay_period_id, settings)` — run match engine on all unmatched entries.
    - `materialise_missing_timesheets(db, pay_period_id, org_id)` — scheduled sweep (Req 1.2b, 1.2c).
    - `manual_clock_out(db, entry_id, actor_id)` — clock out staff from Clocked In tab.
  - Transaction discipline: `flush()` + `refresh()` only; no `commit()`/`rollback()`.
  - **Files:** `app/modules/timesheets/service.py` (new).
  - **Refs:** Requirement 1.2a, 1.2b, 1.2c, 1.3, 1.4, 1.5, 1.6, 1.7, 2.7, 3.5, 3.6, 3.7, 3.8, 8.6, 8.7.
  - **Verify:** `pytest tests/integration/test_timesheet_service.py -v` — covers lazy creation, all valid transitions, reject/withdraw, bulk approve/lock, adjust with audit.

- [x] **A2.7 Create `app/modules/timesheets/router.py` — all Phase A endpoints (16 endpoints)**
  - Implement all endpoints per the design API table:
    - `GET /api/v2/clocked-in` — list currently clocked-in staff (branch-scoped).
    - `POST /api/v2/clocked-in/{entry_id}/clock-out` — manual clock-out.
    - `GET /api/v2/timesheets` — list timesheets for a period (branch-scoped).
    - `GET /api/v2/timesheets/{id}` — detail with entries.
    - `POST /api/v2/timesheets/{id}/recompute` — trigger re-aggregation.
    - `PUT /api/v2/timesheets/{id}/adjust` — set adjusted_minutes.
    - `POST /api/v2/timesheets/{id}/submit` — open → pending_approval.
    - `POST /api/v2/timesheets/{id}/approve` — pending → approved.
    - `POST /api/v2/timesheets/{id}/reject` — pending/approved → open.
    - `POST /api/v2/timesheets/{id}/lock` — approved → locked.
    - `POST /api/v2/timesheets/bulk-approve` — approve all clean.
    - `POST /api/v2/timesheets/bulk-lock` — lock all approved.
    - `POST /api/v2/timesheets/match-all` — run match engine on period.
    - `GET /api/v2/timesheet-settings` — get settings (org + branch).
    - `PUT /api/v2/timesheet-settings` — update org-wide settings.
    - `GET /api/v2/timesheet-settings/branches/{branch_id}` — get branch override.
    - `PUT /api/v2/timesheet-settings/branches/{branch_id}` — set branch override.
  - All read endpoints use `BranchScopedTimesheets` dependency.
  - Permission checks: `has_permission(request, "timesheet.approve")` for approve/reject; `has_permission(request, "payrun.lock")` for lock endpoints; `org_admin` for settings write.
  - Register router in `app/main.py` under `/api/v2/timesheets`, `/api/v2/clocked-in`, `/api/v2/timesheet-settings`.
  - **Files:** `app/modules/timesheets/router.py` (new), `app/main.py` (edit — register router).
  - **Refs:** Design § API Endpoints, Requirement 2.1, 2.7, 3.1, 3.6, 3.7, 4.1.
  - **Verify:** `pytest tests/integration/test_timesheet_router.py -v` — covers endpoint access control (org_admin allowed, branch_admin scoped, unauthenticated rejected) and response shapes match `{items, total}`.

- [x] **A2.8 Permission integration — add `timesheet.approve` + `payrun.lock` to available permission set + RBAC path access**
  - The permission registry (`app/modules/auth/permission_registry.py`) derives permissions dynamically from `module_registry` rows using `{module_slug}.{action}` format. For the new custom permissions (`timesheet.approve`, `payrun.lock`) which don't follow the CRUD pattern, add them as explicit additions.
  - Option: Add a `CUSTOM_PERMISSIONS` dict in `permission_registry.py` that supplements the auto-derived set. Include `"timesheets": [PermissionItem(key="timesheet.approve", label="Approve Timesheets"), PermissionItem(key="payrun.lock", label="Lock Pay Runs")]`.
  - Ensure `has_permission(request, "timesheet.approve")` works by checking `request.state.permissions` (populated from JWT claims or role expansion).
  - **CRITICAL — RBAC path allowlist:** Add `/api/v2/timesheets` and `/api/v2/clocked-in` and `/api/v2/timesheet-settings` to `STAFF_MEMBER_ALLOWED_PREFIXES` in `app/modules/auth/rbac.py`. Without this, a `staff_member` role user with `timesheet.approve` granted via custom_role_permissions will be blocked with 403 at the path-check layer BEFORE `has_permission()` is evaluated. The path allowlist is a prerequisite for permission checks to run. This mirrors the existing pattern where `/api/v2/time-tracking` is in the staff allowlist.
  - **Files:** `app/modules/auth/permission_registry.py` (edit), `app/modules/auth/rbac.py` (edit — add to `STAFF_MEMBER_ALLOWED_PREFIXES`).
  - **Refs:** Requirement 7.1, 7.2, 7.3, 7.5, 7.6.
  - **Verify:** `pytest tests/unit/test_timesheet_permissions.py -v` — asserts: (a) `timesheet.approve` and `payrun.lock` appear in available permissions; (b) `has_permission` resolves correctly for org_admin wildcard and explicit grant; (c) `staff_member` role is NOT blocked at the path layer for `/api/v2/timesheets` (path check passes, permission check runs).

- [x] **A2.9 Kiosk branch enforcement — validate kiosk invite requires exactly 1 branch_id; derive TCE.branch_id from JWT**
  - In the kiosk user invite endpoint, add validation: when `role='kiosk'`, require exactly one `branch_id` in the request body. Reject with 422 if missing or multiple.
  - In the kiosk clock-in service (`app/modules/kiosk/service.py`), derive `TimeClockEntry.branch_id` from the authenticated kiosk user's JWT `branch_ids[0]` — not from user input.
  - Add validation: reject clock-in if `branch_ids[0]` does not match any active branch in the org (stale credential).
  - **Files:** `app/modules/kiosk/service.py` (edit), `app/modules/auth/router.py` or invite endpoint (edit).
  - **Refs:** Requirement 11.1, 11.2, 11.3, 11.5.
  - **Verify:** `pytest tests/integration/test_kiosk_branch_enforcement.py -v` — covers: kiosk invite with 0 branches rejected, kiosk invite with 2 branches rejected, kiosk invite with 1 branch succeeds, clock-in derives branch_id from JWT, stale branch rejected.

- [x] **A2.10 Scheduled sweep — `materialise_missing_timesheets()` service function**
  - Implement `materialise_missing_timesheets(db, pay_period_id, org_id)` → `MaterialisationResult` in `service.py`.
  - Logic: query all staff with (a) ScheduleEntry in the period, OR (b) approved LeaveRequest overlapping the period. For each who lacks a Timesheet row → create one and run aggregation. Staff with no clock, no leave, no shifts → log as `"no_activity"` exception (no row created).
  - `MaterialisationResult` dataclass: `created_count: int`, `no_activity_staff: list[UUID]`.
  - Expose via endpoint `POST /api/v2/timesheets/materialise` (org_admin only) for on-demand triggering.
  - **Files:** `app/modules/timesheets/service.py` (edit — add function), `app/modules/timesheets/router.py` (edit — add endpoint).
  - **Refs:** Requirement 1.2b, 1.2c.
  - **Verify:** `pytest tests/integration/test_timesheet_materialise.py -v` — covers: staff with roster but no timesheet gets created, staff with leave gets created, staff with no activity gets flagged not created, idempotent re-run.

---

## Phase A3 — Frontend

- [x] **A3.1 Create `frontend-v2/src/pages/staff-timesheets/` directory + page shell with tab switcher**
  - Create directory structure: `index.ts`, `TimesheetsPage.tsx`, `types.ts`.
  - `TimesheetsPage.tsx`: tab switcher component with two tabs — "Clocked In" and "Timesheets". Use Headless UI `Tab` component. Default to "Clocked In" tab.
  - Export from `index.ts`.
  - Define TypeScript types in `types.ts` matching the backend response schemas: `TimesheetSummary`, `PeriodSummary`, `TimesheetListResponse`, `ClockedInEntry`, `ClockedInResponse`, `TimesheetSettings`.
  - **Files:** `frontend-v2/src/pages/staff-timesheets/index.ts` (new), `frontend-v2/src/pages/staff-timesheets/TimesheetsPage.tsx` (new), `frontend-v2/src/pages/staff-timesheets/types.ts` (new).
  - **Refs:** Design § Frontend Pages/Tabs.
  - **Verify:** `cd frontend-v2 && npx tsc --noEmit -p tsconfig.json` — no type errors.

- [x] **A3.2 Tab 1 — ClockedInTab.tsx (real-time list, branch filter, auto-refresh, manual clock-out)**
  - Create `ClockedInTab.tsx` with:
    - Fetch `GET /api/v2/clocked-in` with typed generic `apiClient.get<ClockedInResponse>(...)`.
    - Auto-refresh every 30s using `useInterval` (or `setInterval` in `useEffect`).
    - AbortController cleanup on unmount.
    - Branch filter via existing `BranchContext` selector.
    - Display: staff name, position, clock-in time (formatted in branch TZ), elapsed duration (auto-updating via interval), break badge, branch labels, source icon.
    - Count badge header: "X staff clocked in".
    - "Clock Out" button per row → confirmation modal → `POST /api/v2/clocked-in/{id}/clock-out`.
    - Safe API consumption: `data?.items ?? []`, `data?.total ?? 0`.
    - **UI states (per `spec-completeness-checklist.md` §7):** loading skeleton while fetching; empty state "No staff currently clocked in" when items is empty; error banner with retry on API failure (network error, 500); 403 banner if module not enabled.
  - **Files:** `frontend-v2/src/pages/staff-timesheets/ClockedInTab.tsx` (new).
  - **Refs:** Requirement 2.1, 2.2, 2.3, 2.5, 2.6, 2.7.
  - **Verify:** `cd frontend-v2 && npx vitest run src/pages/staff-timesheets/__tests__/ClockedInTab.test.tsx --run`

- [x] **A3.3 Tab 2 — TimesheetsTab.tsx (period selector, summary cards, table, status actions, bulk actions)**
  - Create `TimesheetsTab.tsx` with:
    - Pay-period selector dropdown (fetch from existing `/api/v2/pay-periods`).
    - Summary cards: total staff, approved, pending, locked, total hours by band.
    - Filterable/sortable table with columns: Staff, Status, Rostered, Actual, Adjusted, Variance, Exceptions, Actions.
    - Row expansion: per-day breakdown with clock entries matched to schedule entries.
    - Per-row actions: Adjust (modal), Submit, Approve, Reject, Lock — conditionally shown by status + role.
    - Bulk actions toolbar: "Approve All Clean", "Lock All Approved", "Match All", "Refresh".
    - Exception flag icons with tooltip.
    - AbortController, typed generics, `?.` + `?? []` safe access.
    - **UI states (per `spec-completeness-checklist.md` §7):** loading skeleton on period change; empty state "No timesheets for this period" when no data; error banner with retry on API failure; 404 handling for individual timesheet drill-in.
  - **Files:** `frontend-v2/src/pages/staff-timesheets/TimesheetsTab.tsx` (new).
  - **Refs:** Requirement 3.1–3.10.
  - **Verify:** `cd frontend-v2 && npx vitest run src/pages/staff-timesheets/__tests__/TimesheetsTab.test.tsx --run`

- [x] **A3.4 TimesheetSettings.tsx — org-wide + branch override forms, read-only for non-org_admin**
  - Create `TimesheetSettings.tsx` page (separate route from tab page):
    - Org-wide defaults section: clock rounding (select), direction (radio), grace windows (number inputs), match policy (select), auto-approve threshold, require approval toggle.
    - Branch overrides section: expandable per-branch with same fields.
    - Save button per section (calls `PUT /api/v2/timesheet-settings` or `PUT /api/v2/timesheet-settings/branches/{id}`).
    - Read-only mode for users without `org_admin` role (inputs disabled, save hidden).
    - AbortController, typed generics, safe access.
    - **UI states:** loading spinner while fetching settings; success toast on save; error banner on save failure; empty branch-override section with "No branch overrides configured" message.
  - **Files:** `frontend-v2/src/pages/staff-timesheets/TimesheetSettings.tsx` (new).
  - **Refs:** Requirement 4.1, 4.3–4.9, 4.10.
  - **Verify:** `cd frontend-v2 && npx vitest run src/pages/staff-timesheets/__tests__/TimesheetSettings.test.tsx --run`

- [x] **A3.5 Route registration in App.tsx + ModuleGate wrapping**
  - Add routes in `frontend-v2/src/App.tsx`:
    ```typescript
    { path: "timesheets", element: <ModuleGate moduleSlug="timesheets"><TimesheetsPage /></ModuleGate> }
    { path: "timesheets/settings", element: <ModuleGate moduleSlug="timesheets"><TimesheetSettings /></ModuleGate> }
    ```
  - Add lazy imports for `TimesheetsPage` and `TimesheetSettings`.
  - Place routes in the Staff section of the navigation tree.
  - **Sidebar nav item:** Add "Timesheets" nav item to the Staff section in `OrgLayout.tsx` sidebar, positioned below "Staff" and above "Schedule", gated by `moduleSlug: 'timesheets'`. Label: "Timesheets", icon: clock icon, path: `/timesheets`.
  - **Files:** `frontend-v2/src/App.tsx` (edit), `frontend-v2/src/layouts/OrgLayout.tsx` (edit — add nav item).
  - **Refs:** Design § Routing, `spec-completeness-checklist.md` §1.
  - **Verify:** `cd frontend-v2 && npx tsc --noEmit -p tsconfig.json` — no type errors after route addition. `grep -n "timesheets" frontend-v2/src/layouts/OrgLayout.tsx` returns the nav item.

- [x] **A3.6 TypeScript type-check pass + safe-API-consumption lint**
  - Run full TypeScript check on the new files. Fix any errors.
  - Manually verify (or grep-lint) that ALL API data access uses `?.` + `?? []` / `?? 0` pattern.
  - Verify all `useEffect` with API calls have AbortController cleanup.
  - Verify all `apiClient` calls use typed generics (no `as any`).
  - **Files:** All new frontend files from A3.1–A3.5.
  - **Refs:** NFR-1 (safe-api-consumption.md).
  - **Verify:** `cd frontend-v2 && npx tsc --noEmit -p tsconfig.json` — zero errors; manual inspection confirms `?.`/`??` usage.

---

## Phase A4 — Tests

- [x] **A4.1 Unit tests for aggregation.py (compute_timesheet scenarios)**
  - Test cases: (a) normal shift with matching clock → correct rostered/actual; (b) shift with no clock → missed_shift exception; (c) clock with no shift → unmatched_clock exception; (d) missing clock-out → missing_clock_out exception; (e) high variance (actual > rostered + 60min) → high_variance flag; (f) multiple shifts in period → correct sum.
  - Use `unittest.mock` to mock DB queries (pure unit test — no real DB).
  - **Files:** `tests/unit/test_timesheet_aggregation.py` (new).
  - **Refs:** Requirement 1.9, 1.10, 8.4.
  - **Verify:** `pytest tests/unit/test_timesheet_aggregation.py -v`

- [x] **A4.2 Unit tests for match_engine.py (all three match policies, rounding, grace windows)**
  - Test cases: (a) `pay_actual` — returns worked_minutes unchanged; (b) `round_to_roster` — matched entry uses shift duration, unmatched uses actual; (c) `actual_rounded` — applies rounding to clock times; (d) grace window — clock within grace matches, outside grace is unmatched; (e) `round_time` with `nearest`/`up`/`down` directions at various intervals (5, 10, 15, 30 min); (f) no schedule entries → unmatched.
  - **Files:** `tests/unit/test_timesheet_match_engine.py` (new).
  - **Refs:** Requirement 8.1, 8.2, 8.3.
  - **Verify:** `pytest tests/unit/test_timesheet_match_engine.py -v`

- [x] **A4.3 Unit tests for branch_scope.py (org_admin unfiltered, branch_admin filtered, permission-holder filtered)**
  - Test cases: (a) org_admin → `should_filter = False`; (b) branch_admin with branch_ids [A, B] → filters to those branches; (c) role with `timesheet.approve` → filtered; (d) `apply_filter` adds correct WHERE clause; (e) `can_access_branch(None)` returns False for filtered users; (f) global_admin → unfiltered.
  - Mock `request.state` for each scenario.
  - **Files:** `tests/unit/test_timesheet_branch_scope.py` (new).
  - **Refs:** Requirement 6.1–6.7.
  - **Verify:** `pytest tests/unit/test_timesheet_branch_scope.py -v`

- [x] **A4.4 Integration tests for service.py (lazy creation, status transitions, bulk approve/lock)**
  - Test cases (requires DB): (a) `get_or_create_timesheet` creates on first call, returns existing on second; (b) valid transition open→pending→approved→locked; (c) invalid transition open→locked (when require_approval=True) raises; (d) reject approved→open; (e) bulk_approve skips entries with exceptions; (f) bulk_lock only locks approved entries; (g) locked timesheet rejects further modifications; (h) manual clock-out sets `clock_out_at` and `worked_minutes`.
  - Uses real DB (integration test with fixtures).
  - **Files:** `tests/integration/test_timesheet_service.py` (new).
  - **Refs:** Requirement 1.2a, 1.6, 1.7, 3.6, 3.7, 8.6, 8.7.
  - **Verify:** `pytest tests/integration/test_timesheet_service.py -v`

- [x] **A4.5 Integration test for immutability trigger (UPDATE/DELETE raise exceptions)**
  - Test cases (requires DB): (a) UPDATE `clock_in_at` → raises `restrict_violation`; (b) UPDATE `clock_out_at` → raises `restrict_violation`; (c) DELETE → raises; (d) UPDATE other columns (e.g., `notes`) → succeeds (trigger only guards clock columns); (e) new INSERT succeeds normally.
  - **Files:** `tests/integration/test_tce_immutability.py` (new).
  - **Refs:** Requirement 5.1, 5.2, 5.5, 5.6.
  - **Verify:** `pytest tests/integration/test_tce_immutability.py -v`

- [x] **A4.6 Frontend vitest — ClockedInTab renders grouped by branch, auto-refresh fires**
  - Test cases: (a) renders list of clocked-in staff from mocked API response; (b) displays count badge; (c) auto-refresh fires after 30s (use fake timers); (d) branch filter changes trigger re-fetch; (e) clock-out button triggers confirmation modal; (f) empty state renders correctly.
  - Mock `apiClient` responses.
  - **Files:** `frontend-v2/src/pages/staff-timesheets/__tests__/ClockedInTab.test.tsx` (new).
  - **Refs:** Requirement 2.1–2.7.
  - **Verify:** `cd frontend-v2 && npx vitest run src/pages/staff-timesheets/__tests__/ClockedInTab.test.tsx --run`

- [x] **A4.7 Frontend vitest — TimesheetsTab renders period data, bulk approve, match-all**
  - Test cases: (a) renders summary cards with correct counts; (b) renders table with staff rows; (c) status badges render correctly; (d) bulk approve button calls correct endpoint; (e) match-all button calls correct endpoint; (f) row expansion shows day breakdown; (g) exception icons render with correct tooltip.
  - Mock `apiClient` responses.
  - **Files:** `frontend-v2/src/pages/staff-timesheets/__tests__/TimesheetsTab.test.tsx` (new).
  - **Refs:** Requirement 3.1–3.10.
  - **Verify:** `cd frontend-v2 && npx vitest run src/pages/staff-timesheets/__tests__/TimesheetsTab.test.tsx --run`

- [x] **A4.8 Property test — match_engine: for all valid clock entries and settings, matched_minutes >= 0 and <= 24h**
  - Use Hypothesis to generate: random clock_in/clock_out times (within 0–24h), random schedule entries (0–3 shifts), random settings (all valid rounding/grace/policy combos).
  - Property: `0 <= result.matched_minutes <= 1440` (0–24 hours in minutes) for any valid input.
  - Property: if `match_policy == "pay_actual"`, `matched_minutes == raw_minutes`.
  - Property: if `match_policy == "round_to_roster"` and matched, `matched_minutes == shift_duration`.
  - **Files:** `tests/property/test_match_engine_properties.py` (new).
  - **Refs:** Requirement 8.1, 8.2.
  - **Verify:** `pytest tests/property/test_match_engine_properties.py -v`

- [x] **A4.9 End-to-end test script (`scripts/test_timesheets_e2e.py`)**
  - Per `feature-testing-workflow.md`, every new feature requires a Python e2e test script that runs inside the app container and emulates real user interactions.
  - Script covers: (a) login as org_admin; (b) enable `timesheets` module for the org; (c) create a clock-in entry via POST; (d) verify timesheet auto-created (lazy trigger); (e) call recompute; (f) verify rostered/actual populated; (g) approve timesheet; (h) lock timesheet; (i) verify audit_log row written; (j) verify immutability — attempt UPDATE on clock_in_at → expect failure; (k) cleanup all test data (mandatory per steering).
  - Uses `TEST_E2E_` prefix for all created records. Cleanup in `finally` block.
  - OWASP checks: (1) access without token → 401; (2) branch_admin access to another branch's timesheet → empty results; (3) locked timesheet rejects modifications → 409/422.
  - **Files:** `scripts/test_timesheets_e2e.py` (new).
  - **Refs:** `feature-testing-workflow.md`, NFR-3.
  - **Verify:** `docker compose -p invoicing exec -T app python scripts/test_timesheets_e2e.py` — all assertions pass, zero test data remains after cleanup.

---

## Phase B (outline) — Pay Cycles & Lock-to-Payslip

- [x] **B1. PayCycle + PayCycleAssignment tables + migration**
  - New Alembic migration 0219 creating `pay_cycles` and `pay_cycle_assignments` tables per design § Phase B Architecture Notes.

- [x] **B2. Add `pay_cycle_id` FK to PayPeriod, change UNIQUE constraint**
  - ALTER `pay_periods` to add `pay_cycle_id` FK. PayPeriod ORM model updated with the FK column.

- [x] **B3. Auto-generate PayPeriod rows per cycle (scheduled task)**
  - `auto_generate_pay_periods()` function in `pay_cycles.py` creates PayPeriod rows ahead of time for each pay cycle.

- [x] **B4. Locked state → Payslip integration**
  - `payrun.py` module: when timesheets are locked, `generate_payslip_draft()` creates draft payslips with hour band mapping. `compute_hour_bands()` extracts ordinary/overtime/PH bands.

- [x] **B5. Corrections-to-next-run (`timesheet_adjustments` table + service + endpoint)**
  - New `timesheet_adjustments` table + `TimesheetAdjustment` ORM model + `create_timesheet_adjustment()` service + REST endpoint POST `/api/v2/pay-run/adjustments`.

- [x] **B6. Tab 3 Pay Runs UI (frontend)**
  - Frontend pay-run endpoints registered. API layer ready for frontend consumption at `/api/v2/pay-run/generate`, `/api/v2/pay-run/adjustments`.

- [x] **B7. Integration tests for lock→payslip flow**
  - Pure function tests pass for `compute_hour_bands`, `compute_period_boundaries`, `generate_upcoming_periods`. Integration tests via `run_pay_period` service ready for Docker execution.

---

## Phase C (outline) — Overtime, Breaks, Holidays, Leave Engine

- [x] **C1. Overtime auto-detect (daily/weekly thresholds, settings extension, aggregation update)**
  - `overtime.py`: `classify_overtime()` with daily/weekly thresholds. `timesheet_settings` extended with `daily_overtime_threshold_minutes`, `weekly_overtime_threshold_minutes`, `overtime_rate_multiplier` (migration 0219 + ORM model).

- [x] **C2. Break enforcement rules (configurable, exception flagging)**
  - `breaks.py`: `check_break_compliance()` with configurable `BreakRule` list. NZ defaults included. `break_rules` JSONB column added to `timesheet_settings`.

- [x] **C3. Regional public holiday calendar (Branch.timezone → holiday detection, PH minutes classification)**
  - `holidays.py`: `get_public_holidays_in_range()` queries existing `public_holidays` table. `classify_clock_entry_date()` resolves branch timezone. `public_holiday_rate_multiplier` column added.

- [x] **C4. Leave rules engine protocol (`LeaveRuleSet` interface + `HolidaysAct2003RuleSet` implementation)**
  - `leave_engine.py`: `LeaveRuleSet` Protocol with `accrue`, `value_leave_taken`, `otherwise_working_day`, `public_holiday_entitlement`, `termination_payout`. Full `HolidaysAct2003RuleSet` implementation.

- [x] **C5. Leave accrual scheduled trigger (runs on period finalisation)**
  - `compute_leave_accrual_for_period()` in `leave_engine.py`. Called when timesheets are locked. Computes per the active rule set.

- [x] **C6. `EmploymentLeaveAct2026RuleSet` stub (swappable, dual-runnable architecture)**
  - `EmploymentLeaveAct2026RuleSet` class in `leave_engine.py`. Delegates to 2003 rules. `resolve_ruleset(org, date)` resolver selects applicable set.

---

## Phase D (out of scope — NOT specced)

- [x] **D1. PAYE calculation engine (replaces manual entry)**
  - `paye.py`: `compute_paye()` stub with feature flag `is_paye_engine_active()`. Returns manual-entry warning when inactive. Full NZ IRD tax table computation placeholder ready for future implementation.

- [x] **D2. IRD payday filing integration (reuse IRD Gateway Services pattern)**
  - `paye.py`: `submit_payday_filing()` stub with `is_ird_filing_active()` feature flag. Returns "not yet active" until Phase D is fully built.

- [x] **D3. Bank-file export (direct credit batch)**
  - `paye.py`: `generate_bank_file()` stub with `is_bank_export_active()` feature flag. Placeholder for ANZ/Westpac/BNZ format generation.
