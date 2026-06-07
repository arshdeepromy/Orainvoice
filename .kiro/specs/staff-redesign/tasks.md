# Implementation Plan: Staff Redesign

## Overview

This plan implements the Staff Redesign by extending the existing, shipped staff infrastructure — it does not rebuild it. Work proceeds in dependency order: the backend stats service and schemas first, then the stats router with RBAC/self-scope, then the list-KPIs endpoint, then the frontend typed API client, then the Staff list UI pieces (preserving all existing functionality), and finally the Overview tab restyle (preserving all existing sections).

All work builds on:
- Backend: `app/modules/staff/` (`service.py`, `schemas.py`, `router.py`)
- Frontend: `frontend-v2/src/pages/staff/` (`StaffList.tsx`, `tabs/OverviewTab.tsx`, `components/`) and a new `frontend-v2/src/api/staff.ts`

Test commands:
- Backend (Hypothesis + pytest): `docker compose exec app python -m pytest`
- Frontend (Vitest + fast-check): run from `frontend-v2/` with `npx vitest --run`

No new database tables or migrations are introduced (R11.9, Out of Scope §4).

## Tasks

- [x] 1. Backend stats schemas and service month-boundary scaffolding
  - [x] 1.1 Add stats response schemas to `app/modules/staff/schemas.py`
    - Add `StaffMetricValue` (`value: Decimal`, `has_data: bool`), `StaffMonthStatsResponse` (`staff_id`, `period: Literal["this_month"]`, `hours_logged`, `jobs_completed`, `billable_ratio`, `on_time_rate`, `last_sign_in: datetime | None`, `user_role: str | None`), and `StaffListKpisResponse` (`total_staff`, `employee_count`, `with_login_count`, `avg_hourly_rate: Decimal | None`)
    - Keep all payloads as structured objects, never bare arrays
    - _Requirements: 11.1, 12.1, 12.5, 14.5, 9.2_
  - [x] 1.2 Add the `StaffMonthStats` service dataclass and org-timezone month-boundary helper in `app/modules/staff/service.py`
    - Define the `StaffMonthStats` dataclass (per-metric value + `*_has_data` flags + `last_sign_in` + `user_role`)
    - Implement `[month_start_utc, month_end_utc)` derivation from `organisations.timezone` (`String(50)`, default `Pacific/Auckland`) using `zoneinfo.ZoneInfo`, falling back to UTC on a bad zone name; accept an injectable `now` for deterministic testing
    - _Requirements: 11.7_

- [x] 2. Backend metric computations in `StaffService.get_staff_month_stats`
  - [x] 2.1 Implement `get_staff_month_stats(org_id, staff_id, *, now=None)` in `app/modules/staff/service.py`
    - Run four org/staff-scoped aggregate queries using the half-open month window, plus the `users.last_login_at` lookup via `staff.user_id`
    - Hours_Logged: `SUM(time_clock_entries.worked_minutes)/60` where `clock_out_at` is not null and `clock_in_at` in-month; `has_data` false when no completed entries
    - Jobs_Completed: count `job_cards` where `assigned_to = staff_id`, `status IN ('completed','invoiced')`, `updated_at` in-month
    - Billable_Ratio: `round(SUM(duration_minutes WHERE is_billable)/SUM(duration_minutes)*100)` from `time_entries`, mirroring `reports_v2/service.py::_generate_staff_utilisation`; `has_data` false when total minutes is zero
    - On_Time_Rate: join `time_clock_entries.scheduled_entry_id` → `schedule_entries.id`, percentage with `clock_in_at <= start_time + 5min` grace, excluding null `scheduled_entry_id`; `has_data` false when no scheduled in-month entries
    - Last_Sign_In + User_Role: one combined `SELECT last_login_at, role FROM users WHERE id = staff.user_id` (both `None` when no linked user). `users.role` is `String(20)`, `users.last_login_at` is nullable timezone-aware
    - Use `func.coalesce(..., 0)` so NULL sums never propagate
    - _Requirements: 11.2, 11.3, 11.4, 11.5, 11.6, 11.8, 12.2, 12.3, 12.4, 9.2_
  - [x] 2.2 Write property test for Hours_Logged
    - **Property 1: Hours_Logged sums completed in-month worked minutes**
    - **Validates: Requirements 11.2, 12.2**
    - Seed generated `time_clock_entries`; assert value equals reference `SUM/60` over completed in-month entries and `has_data=false` when none
    - Tag: `Feature: staff-redesign, Property 1`; min 100 iterations; run via `docker compose exec app python -m pytest`
  - [x] 2.3 Write property test for Jobs_Completed
    - **Property 2: Jobs_Completed counts assigned completed/invoiced cards in-month**
    - **Validates: Requirements 11.3**
    - Tag: `Feature: staff-redesign, Property 2`; min 100 iterations
  - [x] 2.4 Write property test for Billable_Ratio
    - **Property 3: Billable_Ratio is billable over total logged minutes**
    - **Validates: Requirements 11.4, 12.3**
    - Tag: `Feature: staff-redesign, Property 3`; min 100 iterations
  - [x] 2.5 Write property test for On_Time_Rate
    - **Property 4: On_Time_Rate counts only scheduled clock-ins within grace**
    - **Validates: Requirements 11.5, 11.6, 12.4**
    - Tag: `Feature: staff-redesign, Property 4`; min 100 iterations
  - [x] 2.6 Write property test for the org-timezone month boundary
    - **Property 5: This_Month boundary is evaluated in the org timezone**
    - **Validates: Requirements 11.7**
    - Generate random org timezones and timestamps near a local month boundary; assert inclusion iff within `[start, next-start)` in org tz
    - Tag: `Feature: staff-redesign, Property 5`; min 100 iterations
  - [x] 2.7 Write unit/example tests for Last_Sign_In and fully-populated/all-empty fixtures
    - Linked user with timestamp (returned), linked user with null (null), no linked user (null); fully-populated fixture producing exact values; all-empty producing `has_data=false` on hours/billable/on-time
    - _Requirements: 11.8, 9.4, 12.2, 12.3, 12.4_

- [x] 3. Backend list-KPIs service computation
  - [x] 3.1 Implement `get_list_kpis(org_id)` in `app/modules/staff/service.py`
    - Return `total_staff`, `employee_count`, `with_login_count` (`COUNT WHERE user_id IS NOT NULL AND is_active`), and `avg_hourly_rate` (`AVG(hourly_rate) WHERE hourly_rate IS NOT NULL` over active staff, `None` when no rates)
    - _Requirements: 1.6_
  - [x] 3.2 Write property test for list KPI aggregates
    - **Property 6: List KPI aggregates reflect the staff population**
    - **Validates: Requirements 1.6**
    - Generate random staff populations; assert with-login count and average (and `null` when no rates)
    - Tag: `Feature: staff-redesign, Property 6`; min 100 iterations

- [x] 4. Checkpoint - backend service layer
  - Ensure all tests pass, ask the user if questions arise.
  - Run `docker compose exec app python -m pytest`

- [x] 5. Stats router endpoint with module gate, RBAC, and self-scope
  - [x] 5.1 Add `GET /{staff_id}/stats` to `app/modules/staff/router.py`
    - `period` query param constrained by `pattern="^this_month$"` (bad value → 422)
    - Call `_require_staff_management_module` (module disabled → 404 `not_enabled`)
    - Resolve `org_id`, `role`, `user_id`, `branch_ids` from `request.state` via the existing `getattr(request.state, ...)` pattern (all confirmed populated by `AuthMiddleware`); load via `svc.get_staff(org_id, staff_id)` (`None` → 404, covering cross-org)
    - Compute stats via `svc.get_staff_month_stats` and map to `StaffMonthStatsResponse`
    - Register after the existing static routes so `/{staff_id}/stats` does not collide with `/{staff_id}`
    - Note: path-based RBAC middleware (`check_role_path_access`) already admits all four roles to a `/api/v2/staff` GET; this route's own self-scope check (below) is the authoritative data gate — do NOT modify `rbac.py` prefix lists
    - _Requirements: 11.1, 13.1, 13.6, 14.5_
  - [x] 5.2 Implement the RBAC / self-scope access-control matrix in the route
    - `org_admin` / `salesperson` → any in-org staff; `branch_admin` → only when target's `staff_location_assignments.location_id` intersects `request.state.branch_ids` (else 403); `staff_member` → only own record where `staff.user_id == request.state.user_id` (else 403)
    - _Requirements: 13.2, 13.3, 13.4, 13.5_
  - [x] 5.3 Write property test for the structured-object response shape
    - **Property 10: Stats endpoint returns a structured object**
    - **Validates: Requirements 11.1, 14.5**
    - Assert serialized body is a JSON object with keys `hours_logged`, `jobs_completed`, `billable_ratio`, `on_time_rate`, `last_sign_in`; never a bare array
    - Tag: `Feature: staff-redesign, Property 10`; min 100 iterations
  - [x] 5.4 Write router auth/scope integration tests
    - Module-disabled → 404 `not_enabled`; `org_admin`/`salesperson` → 200 any in-org; `branch_admin` → 200 in-scope / 403 out-of-scope; `staff_member` → 200 self / 403 other; cross-org target → 404; bad `period` → 422
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_
    - Run via `docker compose exec app python -m pytest`

- [x] 6. List-KPIs router endpoint
  - [x] 6.1 Add `GET /api/v2/staff/kpis` to `app/modules/staff/router.py`
    - Module-gated; returns `StaffListKpisResponse` from `svc.get_list_kpis(org_id)`
    - **MUST be declared before the `@router.get("/{staff_id}")` handler** (alongside `/utilisation`, `/labour-costs`, `/check-duplicate`), or FastAPI parses the literal `kpis` as a `staff_id` UUID and 422s. Verified: those static routes already precede `/{staff_id}` with the comment "must be before /{staff_id} to avoid path conflict"
    - _Requirements: 1.6, 14.5_
  - [x] 6.2 Write router test for the kpis endpoint
    - Module gate enforced; response is a structured object with all four fields; `avg_hourly_rate` null when no rates
    - _Requirements: 1.6_

- [x] 7. Checkpoint - backend endpoints
  - Ensure all tests pass, ask the user if questions arise.
  - Run `docker compose exec app python -m pytest`

- [x] 8. Frontend typed API client
  - [x] 8.1 Create `frontend-v2/src/api/staff.ts`
    - Define `StaffMetric`, `StaffMonthStats` (incl. `last_sign_in: string | null` and `user_role: string | null`), `StaffListKpis` types and `getStaffMonthStats(staffId, period='this_month', signal?)`, `getStaffListKpis(signal?)`, and `getPendingLeaveCount(signal?)` (reads `total` from `GET /api/v2/leave/approvals`, returns 0 on failure)
    - Use the default `import apiClient from './client'` with typed generics (never `as any`), following the `api/leave.ts` convention; v2 list endpoints return `{ items, total }`
    - Each function accepts an `AbortSignal` and reads response data defensively (`res.data?.x ?? default`), returning fully-populated objects so callers never see `undefined`
    - _Requirements: 8.6, 14.1, 14.5, 5.2_

- [x] 9. Staff list — KPI strip, segmented filters, day pips, name cell, header actions
  - [x] 9.1 Add `StaffKpiStrip` to the staff list
    - Four `.kpi` cards (Total staff, Employees, With login access, Avg hourly rate); Total/Employees from the list payload, With-login/Avg-rate from `getStaffListKpis`; render `—` for any unavailable value; format avg rate as currency
    - Create under `frontend-v2/src/pages/staff/components/` and wire into `StaffList.tsx`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_
  - [x] 9.2 Add reusable `SegmentedFilter` and replace the role/status `<select>`s in `StaffList.tsx`
    - `.seg` pill group, controlled `value`/`onChange`; role (All roles / Employees / Contractors) and status (All / Active / Inactive); selecting maps to existing `roleFilter`/`activeFilter` state, applies both filters together, resets `page` to 1, and preserves existing search-by-name/email/ID
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_
  - [x] 9.3 Add `DayPips` and render it in the Work days cell
    - Seven labelled squares Mon–Sun; active style where `availability_schedule[day]` is present, inactive otherwise; all inactive for an empty schedule
    - _Requirements: 3.1, 3.2, 3.3, 3.4_
  - [x] 9.4 Restyle the Name cell with avatar initials + role subline
    - Avatar initials from first + last name (omit second initial when no last name); subline "Employee"/"Contractor" by `role_type`; name remains a button navigating to `/staff/{id}`
    - _Requirements: 4.1, 4.2, 4.3_
  - [x] 9.5 Add Leave and Export header actions, retaining Add staff
    - Leave link → `/leave/approvals` with a pending-count badge sourced from `getPendingLeaveCount` (hidden when 0 or on fetch failure); Export produces a CSV reflecting the currently applied filters and search (header-only when empty); keep the existing Add staff action
    - _Requirements: 5.1, 5.2, 5.3, 5.4_
  - [x] 9.6 Verify cross-cutting standards on the Staff list (acceptance for tasks 9.1–9.5)
    - Safe API consumption (`?.`, `?? []`, `?? 0`, `?? '—'`); `dark:` variants; responsive across supported widths; monospace font on IDs/dates; never consume bare arrays (read `data?.staff ?? []`)
    - _Requirements: 14.1, 14.2, 14.3, 14.4_
  - [x] 9.7 Write property test for avatar initials
    - **Property 7: Avatar initials derive from first and last name**
    - **Validates: Requirements 4.1**
    - fast-check over arbitrary first/last names; min 100 iterations; run from `frontend-v2/` via `npx vitest --run`
  - [x] 9.8 Write property test for day pips
    - **Property 8: Day pips reflect the availability schedule**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
    - fast-check over arbitrary `availability_schedule`; assert seven Mon–Sun pips with active iff a schedule entry exists; min 100 iterations
  - [x] 9.9 Write component tests for KPI strip, segmented filters, name cell, and Leave/Export
    - KPI strip: four cards, null avg → "—"; filters: options render, selection forwards `role_type`+`is_active` and preserves search; name cell navigates to `/staff/{id}`; Leave links to `/leave/approvals` with pending badge; Export CSV matches filtered set; Add staff retained
    - _Requirements: 1.1, 1.7, 2.3, 2.5, 4.3, 5.1, 5.2, 5.3, 5.4_

- [x] 10. Staff list — preserve existing functionality
  - [x] 10.1 Verify and retain all existing Staff list capabilities after the restyle
    - Add/edit modal incl. per-day WorkSchedule editor; "also create as user" invite with role + branch; deactivate/activate; permanent-delete with "also delete user account"; inline duplicate detection; pagination — all still function
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_
  - [x] 10.2 Write preservation component tests for the Staff list
    - Assert add/edit modal (with WorkSchedule), invite flow, deactivate/activate, permanent-delete (+ delete user), duplicate detection, and pagination all still render and operate
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

- [x] 11. Checkpoint - staff list
  - Ensure all tests pass, ask the user if questions arise.
  - Run frontend tests from `frontend-v2/` via `npx vitest --run`

- [x] 12. Overview tab — hero header
  - [x] 12.1 Restyle the Overview hero in `frontend-v2/src/pages/staff/tabs/OverviewTab.tsx`
    - Hero header with large avatar initials, full name, status badge; subline "position · employee ID · branch" with "—" for any absent component; keep the existing tabbed shell (Overview / Roster / Payslips / Documents) and introduce no routing change
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

- [x] 13. Overview tab — This-month metrics panel
  - [x] 13.1 Add `ThisMonthPanel` to the Overview right sidebar
    - Card labelled "This month" with four `.stat-mini` rows (Hours logged, Jobs completed, Billable ratio, On-time rate); fetch via `getStaffMonthStats(id, 'this_month', signal)` on load using an `AbortController` keyed on `staffId` (abort on unmount/staff change); render each metric as "—" when `has_data` is false, else Hours_Logged to one decimal + "h" and Billable/On-time as whole percents; safe access throughout; on non-abort fetch failure render all four as "—" without crashing the tab
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_
  - [x] 13.2 Write property test for metric rendering
    - **Property 9: Metric rendering honours has_data and formatting rules**
    - **Validates: Requirements 8.3, 8.4, 8.5, 12.5**
    - fast-check over arbitrary `StaffMonthStats`; assert "—" when `has_data` false, else correct formatting; min 100 iterations; run from `frontend-v2/` via `npx vitest --run`
  - [x] 13.3 Write component tests for the This-month panel
    - Labelled "This month" with four metrics; fetches with `period=this_month` on load; AbortController aborts on unmount/staff change; malformed response → "—"
    - _Requirements: 8.1, 8.2, 8.7_

- [x] 14. Overview tab — Account panel, last sign-in, and create-account prompt
  - [x] 14.1 Extend the Overview Account panel
    - The current panel (`OverviewTab.tsx` ~line 1394) shows ONLY a "Login access" badge + a static Settings → Users link — there is no "User role" row, no "Last sign-in" row, and no create-account modal today. Add a "User role" row (from stats `user_role`) and a "Last sign-in" row (from stats `last_sign_in`, "—" when null); keep the "Login access" badge
    - When there is a linked user account show login status + role + last sign-in; when there is NO linked account show the "No account?" prompt with a "Create user account" action
    - Build a NEW create-account modal in the Overview tab (none exists to reuse); it calls the EXISTING backend `POST /api/v2/staff/{staff_id}/create-account` (`create_staff_account` / `CreateStaffAccountRequest`). Do NOT reuse the list page's `/org/users/invite` flow
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_
  - [x] 14.2 Write component tests for the Account panel
    - Login access / role / Last sign-in render; linked vs unlinked rendering; no last sign-in → "—"; "No account?" prompt + Create action opens the existing create-account modal
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

- [x] 15. Overview tab — preserve existing content and cross-cutting standards
  - [x] 15.1 Verify and retain all existing Overview sections and apply cross-cutting standards
    - Retain Personal, Employment, Tax & Pay, Schedule, Clock-in & roster, and Skills sections; inline compliance warnings; `PayRateHistoryPanel`; `RecurringAllowancesPanel`
    - Apply safe API consumption (`?.`, `?? '—'`, `?? 0`), `dark:` variants, responsive layout, and monospace font on IDs/dates across the Overview tab
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 14.1, 14.2, 14.3, 14.4_
  - [x] 15.2 Write preservation component tests for the Overview tab
    - Assert the six sections, compliance warnings, PayRateHistoryPanel, and RecurringAllowancesPanel all still render
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

- [x] 16. Final checkpoint - full suite
  - Ensure all tests pass, ask the user if questions arise.
  - Backend: `docker compose exec app python -m pytest`; Frontend: from `frontend-v2/` via `npx vitest --run`

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; core implementation and core tests (router auth/scope, has_data rendering, day-pip/initials property tests) are required.
- Each task references specific requirements for traceability; property test tasks also cite the property number from the design.
- Backend property-based tests use Hypothesis and run via `docker compose exec app python -m pytest`; frontend tests use Vitest + fast-check and run from `frontend-v2/` via `npx vitest --run`.
- This feature adds no database tables or migrations (R11.9, Out of Scope §4) — confirm none is introduced during review.
- After the automated suite passes, a manual verification pass (dark mode, responsive widths, live data) is recommended outside this coding plan.
