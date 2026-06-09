# Requirements Document — Staff Timesheets

## Introduction

The Staff Timesheets module is an **integration, computation, and configuration layer** built on top of the existing time-clock, scheduling, leave, and payslips subsystems. It does not duplicate `TimeClockEntry`, `ScheduleEntry`, `PayPeriod`, `Payslip`, or any other existing entity — instead it introduces a `Timesheet` aggregation row that brings together rostered hours (from `schedule_entries`), actual hours (from approved `time_clock_entries`), and an optional adjusted-hours override into a single per-staff per-pay-period record.

This module serves New Zealand–based multi-branch workshop organisations that need to:

1. **See who is clocked in right now** — a real-time view filtered by branch.
2. **Review and approve timesheets per pay period** — matching clock data against the roster, applying rounding/grace rules, and signing off before payroll.
3. **Configure clock-in rules** — rounding intervals, grace windows, and match-to-roster policies that determine how raw clock minutes become payable hours.
4. **Lock timesheets** — preventing further edits once payslips have been generated, with a corrections-to-next-run mechanism for post-lock adjustments.
5. **Enforce branch-level data isolation** — branch admins see only their branch's clock and timesheet data; org admins see all branches.

The module is phased to manage complexity:

- **Phase A** (this spec, full detail): Timesheet entity + aggregation service; Tab 1 Clocked In; Tab 2 Timesheets; Settings; clock immutability; branch query scoping; `timesheet.approve` permission grant; match-to-roster policy engine.
- **Phase B** (outline): Clock→payslip hour mapping, locked state, corrections-to-next-run, pay cycle groups, Tab 3 Pay Runs.
- **Phase C** (outline): Overtime auto-detect, break enforcement, regional public holiday calendar integration, leave accrual trigger + versioned rules engine.
- **Phase D** (out of scope — do NOT spec): PAYE calc engine, IRD payday filing, bank-file export.

### NZ Compliance Context

- **Holidays Act 2003** — requires accurate recording of hours worked for leave-entitlement calculations. The Timesheet entity provides an auditable per-period hour record that feeds the leave engine.
- **Employment Relations Act 2000** — employers must keep wage and time records for seven years. The immutability controls and append-only audit trail support this retention obligation.
- **Minimum Wage Act 1983** — actual hours worked must be accurately tracked so the payroll system can verify minimum wage compliance at payslip generation time.

## Glossary

- **Timesheet** — A per-staff, per-pay-period aggregation row that combines rostered minutes, actual clocked minutes, and an optional adjusted-minutes override. The authoritative source of hours flowing into the payslip.
- **Pay Period** — An existing `pay_periods` row (weekly, fortnightly, or monthly) defining the date window for hour aggregation. Managed by the payslips module.
- **Rostered Minutes** — The sum of `(end_time - start_time)` across all `schedule_entries` for a staff member within the pay period.
- **Actual Minutes** — The sum of `worked_minutes` across all approved `time_clock_entries` for a staff member within the pay period, scoped by `clock_in_at` falling inside the period.
- **Adjusted Minutes** — A nullable override on the Timesheet. When set, this is the source of truth for payable hours. When NULL, `actual_minutes` is used.
- **Match-to-Roster** — A configurable policy that determines how raw clock data is reconciled against the schedule: pay actual, round to roster, or round to nearest interval.
- **Clock Rounding** — Rounding clock-in/out times to the nearest X-minute interval (e.g., nearest 5, 10, or 15 minutes) for payroll purposes.
- **Grace Window** — A configurable number of minutes before/after a shift's scheduled start/end within which a clock event is considered "on time".
- **Branch Query Scoping** — A FastAPI dependency that automatically filters timesheet/clock/leave queries to `branch_id ∈ user.branch_ids` for branch_admin users.
- **Approver** — Any user holding the `timesheet.approve` permission grant (attached via `custom_role_permissions`). Can approve/reject timesheets but cannot lock periods or issue payslips unless also holding `payrun.lock`.
- **Clock Immutability** — A database-level enforcement (BEFORE UPDATE/DELETE trigger on `clock_in_at`, `clock_out_at` columns) ensuring raw clock data is never mutated after the fact. Override requires superuser to disable the trigger.
- **Kiosk Credential** — A `users` row with `role='kiosk'` and `branch_ids = [branch_id]`, binding the kiosk device to a specific branch so clock entries inherit trustworthy branch attribution via the JWT's `branch_ids[0]` claim.
- **Exception Flag** — A JSONB field on the Timesheet recording anomalies (e.g., "missed clock-out", "shift without clock-in", "unmatched clock entry") for manager review.

## Requirements

### Requirement 1 — Timesheet Entity

**User Story:** As a payroll manager, I want a single per-staff per-pay-period record that aggregates rostered, actual, and adjusted hours with hour-band breakdowns, so that I have one authoritative source feeding payslip generation.

#### Acceptance Criteria

1. THE system SHALL create a `timesheets` table with columns: `id` (UUID PK), `org_id`, `staff_id` (FK → staff_members), `pay_period_id` (FK → pay_periods), `branch_id` (FK → branches, nullable for multi-branch staff), `rostered_minutes` (integer), `actual_minutes` (integer), `adjusted_minutes` (integer, nullable), `ordinary_minutes` (integer), `overtime_minutes` (integer), `public_holiday_minutes` (integer), `exception_flags` (JSONB), `status` (text, CHECK IN open/pending_approval/approved/locked), `approved_by` (FK → users, nullable), `approved_at` (timestamptz, nullable), `locked_at` (timestamptz, nullable), `locked_by` (FK → users, nullable), `payslip_id` (FK → payslips, nullable), `notes` (text, nullable), `created_at` (timestamptz), `updated_at` (timestamptz).
2. THE system SHALL enforce UNIQUE constraint on `(staff_id, pay_period_id)` — one timesheet per staff per period. Required by NZ employment law (one employment relationship → one Payslip per period). Per-branch attribution is preserved inside the timesheet via `clock_in_branch_id`/`clock_out_branch_id` but the unit of approval and pay is the single aggregated row. Overtime/leave/public-holiday thresholds are computed per-person per-period, never per-branch.
2a. THE system SHALL create a Timesheet row LAZILY via the following triggers: (i) on first clock-in (`TimeClockEntry` insert) for that staff in the period; (ii) when an approved `LeaveRequest`'s dates overlap the period; (iii) when a `ScheduleEntry` exists for that staff in the period.
2b. THE system SHALL run a scheduled sweep (`materialise_missing_timesheets`) before pay-run cutoff that materialises Timesheet rows for any staff member who is rostered or on approved leave in the period but still lacks a Timesheet row.
2c. THE system SHALL flag staff with NO clock activity, NO approved leave, and NO scheduled shifts as a "no_activity" EXCEPTION (logged/alerted by the sweep) rather than creating a blank Timesheet row for them.
3. WHEN `adjusted_minutes` is NOT NULL, THE system SHALL use `adjusted_minutes` as the source of truth for payable hours flowing into payslip generation.
4. WHEN `adjusted_minutes` is NULL, THE system SHALL use `actual_minutes` as the source of truth for payable hours flowing into payslip generation.
5. THE system SHALL NEVER mutate `time_clock_entries` rows as part of timesheet adjustments. All corrections are expressed via `adjusted_minutes` on the Timesheet entity.
6. THE system SHALL support the following status transitions: `open` → `pending_approval` → `approved` → `locked`. Reverse transitions `approved` → `open` (reject/reopen) and `pending_approval` → `open` (withdraw) are also permitted.
7. THE status `locked` is terminal for Phase A. Once locked, no field on the Timesheet may be modified (Phase B introduces corrections-to-next-run).
8. THE `exception_flags` JSONB column SHALL store an array of anomaly objects, each with fields `type` (string enum), `detail` (string), and `clock_entry_id` (UUID, nullable).
9. THE system SHALL populate `rostered_minutes` by summing `(end_time - start_time)` in minutes across all `schedule_entries` WHERE `staff_id = timesheet.staff_id` AND `start_time >= pay_period.start_date` AND `end_time <= pay_period.end_date + 1 day` AND `status = 'scheduled'` AND `entry_type NOT IN ('break', 'leave')`.
10. THE system SHALL populate `actual_minutes` by summing `worked_minutes` across all `time_clock_entries` WHERE `staff_id = timesheet.staff_id` AND `clock_in_at >= pay_period.start_date` AND `clock_in_at < pay_period.end_date + 1 day` AND `worked_minutes IS NOT NULL`.

### Requirement 2 — Tab 1: Clocked In (Real-time View)

**User Story:** As a branch manager, I want to see which staff are currently clocked in at my branch right now, including their clock-in time, elapsed duration, break status, and which branch they clocked in/out at, so that I have real-time workforce visibility.

#### Acceptance Criteria

1. THE system SHALL provide a "Clocked In" tab showing all `time_clock_entries` WHERE `clock_out_at IS NULL` AND `org_id = current_org`, scoped by branch per Requirement 6.
2. EACH row in the Clocked In list SHALL display: staff name, position, clock-in time (in branch timezone), elapsed duration (auto-refreshing), current break status (on break / not on break), clock-in branch name, and clock-in source icon (kiosk / self-service / admin).
3. WHEN a staff member clocks out at a different branch than they clocked in, THE system SHALL display both branches: "In: Branch A / Out: Branch B".
4. THE system SHALL display the `clock_out_branch_id` alongside the existing `branch_id` (clock-in branch) to support cross-branch clock-out visibility.
5. THE system SHALL auto-refresh the Clocked In list every 30 seconds via polling or server-sent events.
6. THE system SHALL display a total count badge showing the number of currently clocked-in staff for the selected branch scope.
7. THE system SHALL allow org_admin and users with `timesheet.approve` permission to manually clock out a staff member from the Clocked In tab, recording the manual clock-out with source `admin_manual`.

### Requirement 3 — Tab 2: Timesheets

**User Story:** As a payroll manager, I want to view, review, and approve timesheets for a selected pay period with per-staff detail rows showing rostered vs actual vs adjusted hours and any exception flags, so that I can efficiently process the pay run.

#### Acceptance Criteria

1. THE system SHALL provide a "Timesheets" tab showing all Timesheet rows for the selected pay period, scoped by branch per Requirement 6.
2. THE system SHALL display a pay-period selector defaulting to the current open pay period, with the ability to navigate to previous periods.
3. EACH timesheet row SHALL display: staff name, status badge (open/pending/approved/locked), rostered hours, actual hours, adjusted hours (if set), variance (actual − rostered), exception flag count with warning icon, and approval info.
4. THE system SHALL allow inline expansion of a timesheet row to show the per-day breakdown of clock entries with clock-in time, clock-out time, breaks, worked minutes, and matched schedule entry (if any).
5. THE system SHALL allow users with `timesheet.approve` permission or org_admin to set `adjusted_minutes` on an open or pending_approval timesheet, with a required `notes` field explaining the adjustment reason.
6. THE system SHALL allow users with `timesheet.approve` permission or org_admin to transition a timesheet from `open` → `pending_approval` → `approved` individually or in bulk ("Approve all clean lines" — timesheets with no exception flags and variance within tolerance).
7. THE system SHALL allow the org_admin to transition an approved timesheet to `locked` (individually or in bulk for the entire period).
8. WHEN a timesheet is locked, THE system SHALL record `locked_at` and `locked_by` and prevent any further modifications.
9. THE system SHALL display a period summary header showing: total staff count, approved count, pending count, total ordinary/overtime/public-holiday hours across the period.
10. THE system SHALL support filtering timesheets by status, branch, and staff name search.

### Requirement 4 — Settings (Clock & Match Policy)

**User Story:** As an org admin, I want to configure clock rounding intervals, grace windows, and match-to-roster policy per branch or org-wide, so that the timesheet computation rules match our pay agreement with staff.

#### Acceptance Criteria

1. THE system SHALL provide a Timesheet Settings page accessible to `org_admin` role (full read/write) under the Staff section. Users with `timesheet.approve` permission SHALL have read-only access to calculation-affecting settings via a separate GET endpoint.
2. THE system SHALL store settings in a new `timesheet_settings` table with columns: `id` (UUID PK), `org_id`, `branch_id` (nullable — NULL means org-wide default), `clock_rounding_minutes` (integer, default 1 = no rounding), `clock_rounding_direction` (text: nearest/up/down, default 'nearest'), `early_grace_minutes` (integer, default 0), `late_grace_minutes` (integer, default 0), `match_policy` (text: pay_actual/round_to_roster/actual_rounded, default 'pay_actual'), `auto_approve_threshold_minutes` (integer, default 0 = disabled), `require_approval_before_lock` (boolean, default true), `created_at`, `updated_at`.
3. WHEN both org-wide and branch-specific settings exist, THE system SHALL apply branch-specific settings for that branch's staff, falling back to org-wide for branches without overrides.
4. THE `clock_rounding_minutes` setting SHALL accept values: 1, 5, 10, 15, 30. Value 1 means no rounding.
5. THE `early_grace_minutes` setting SHALL define how many minutes before the scheduled start a clock-in is treated as "on time" (not early).
6. THE `late_grace_minutes` setting SHALL define how many minutes after the scheduled start a clock-in is treated as "on time" (not late).
7. THE `match_policy` setting SHALL control the match-to-roster computation per Requirement 8.
8. THE `auto_approve_threshold_minutes` setting SHALL define the maximum absolute variance (|actual − rostered|) below which a timesheet can be auto-approved. Value 0 disables auto-approval.
9. THE `require_approval_before_lock` setting SHALL determine whether timesheets must be in `approved` status before they can be transitioned to `locked`. When false, timesheets can go directly `open` → `locked`.
10. Users with `timesheet.approve` permission SHALL have READ-ONLY access to calculation-affecting settings (clock rounding, grace window, match-to-roster policy, overtime thresholds, break rules). They SHALL NOT have write access. They SHALL NOT see financial/PII settings (pay rates, bank/IRD config). Write access remains exclusive to `org_admin`.

### Requirement 5 — Clock Immutability

**User Story:** As a compliance officer, I want raw clock-in and clock-out timestamps to be immutable at the database level (not just application-level), so that we can prove the integrity of attendance records for seven years as required by the Employment Relations Act.

#### Acceptance Criteria

1. THE system SHALL apply a PostgreSQL-level BEFORE UPDATE/DELETE trigger (`tce_immutability_guard`) on the `time_clock_entries` table that raises an EXCEPTION (errcode `restrict_violation`) when any attempt is made to UPDATE `clock_in_at`/`clock_out_at` or DELETE a row.
2. THE trigger SHALL fire for ALL database roles including the `postgres` superuser role used by the application, effectively making the columns immutable at the application level.
3. THE migration implementing immutability SHALL be forward-only — it does NOT backfill, modify, or delete any existing rows.
4. THE system SHALL provide a superuser-only override mechanism: `ALTER TABLE time_clock_entries DISABLE TRIGGER trg_tce_immutability` (requires superuser), for data-recovery scenarios. This must be documented but never used by the application.
5. ALL corrections to worked hours SHALL be expressed through `Timesheet.adjusted_minutes`, never through modification of `time_clock_entries` rows.
6. THE system SHALL raise a PostgreSQL EXCEPTION (not just WARNING) on any attempted violation of immutability, ensuring the transaction is rolled back and the violation is visible in application logs.

### Requirement 6 — Branch Query Scoping

**User Story:** As a branch admin, I want to see only the clock entries, timesheets, and leave data for staff at my assigned branch(es), enforced at the API layer so that branch isolation is a security boundary — not just a UI filter.

#### Acceptance Criteria

1. THE system SHALL implement a FastAPI dependency `BranchScopedTimesheets` that reads `request.state.branch_ids` (populated by `BranchContextMiddleware`) and auto-filters all timesheet/clock/leave queries to `branch_id ∈ branch_ids` for users with role `branch_admin`.
2. FOR users with role `org_admin` or `global_admin`, THE dependency SHALL NOT apply any branch filter (full org visibility).
3. FOR users with `timesheet.approve` permission (who are not org_admin), THE dependency SHALL filter to `branch_id ∈ branch_ids` (approval permission holders are branch-scoped unless they are org_admin).
4. THE branch scoping dependency SHALL be applied to ALL read endpoints in the timesheets module: GET /timesheets, GET /timesheets/{id}, GET /clocked-in, GET /timesheet-settings.
5. THE branch scoping dependency SHALL also apply to write endpoints for `branch_admin` and users with `timesheet.approve` permission — they can only approve/reject timesheets for their branch(es).
6. THE dependency SHALL use the existing `BranchContextMiddleware` pattern (validates `X-Branch-Id` header) as its input source.
7. WHEN `TimeClockEntry.branch_id` is NULL (legacy entries before branch requirement), THE dependency SHALL include those entries in org_admin/global_admin views but EXCLUDE them from branch_admin/`timesheet.approve` permission holder views (they cannot be attributed).

### Requirement 7 — RBAC / Permissions

**User Story:** As an org admin, I want to grant timesheet-approval permission to shift supervisors without creating a new standalone role, so that I can delegate approval to any existing role via the custom_role_permissions mechanism.

#### Acceptance Criteria

1. THE system SHALL NOT create a new `approver` RBAC role. Instead, `timesheet.approve` SHALL be a permission grant attachable to any existing role via the `custom_role_permissions` mechanism.
2. THE system SHALL treat `timesheet.approve` (approve/reject hours) as SEPARATE from `payrun.lock` (lock period + issue payslips). A user can hold one permission without the other.
3. THE `org_admin` role SHALL inherit both `timesheet.approve` and `payrun.lock` via the existing org.* wildcard.
4. BRANCH SCOPING SHALL apply to `timesheet.approve` permission holders: a `branch_admin` with `timesheet.approve` granted can only approve timesheets for their branch(es), as enforced by Requirement 6.
5. THE system SHALL check `timesheet.approve` permission via `has_permission(request, 'timesheet.approve')` at the endpoint level — not via role-name checks.
6. THE system SHALL add `timesheet.approve` and `payrun.lock` to the available permission set in `custom_role_permissions`.
7. THE `payrun.lock` permission (locking periods + linking to payslips) SHALL remain exclusive to `org_admin` by default (grantable to other roles via custom_role_permissions only by org_admin).

### Requirement 8 — Match-to-Roster Policy Engine

**User Story:** As a payroll manager, I want the system to automatically reconcile each clock entry against the roster using configurable rules (pay actual, round to roster, or round to nearest interval), so that I don't have to manually adjust every timesheet line.

#### Acceptance Criteria

1. THE system SHALL implement a match-to-roster engine that, for each `time_clock_entry` in a pay period, attempts to find the corresponding `schedule_entry` by matching on `staff_id` and overlapping time window.
2. THE match-to-roster engine SHALL support three modes configurable via `timesheet_settings.match_policy`:
   - `pay_actual`: Use `time_clock_entry.worked_minutes` as-is. No rounding or roster alignment.
   - `round_to_roster`: If the clock entry matches a scheduled shift (within grace window), use the scheduled shift duration as the payable minutes. If no match, fall back to actual.
   - `actual_rounded`: Apply `clock_rounding_minutes` and `clock_rounding_direction` to the raw clock-in and clock-out times, then compute worked_minutes from the rounded times.
3. THE match engine SHALL apply the `early_grace_minutes` and `late_grace_minutes` windows when determining whether a clock entry "matches" a scheduled shift. A clock-in within `early_grace_minutes` before or `late_grace_minutes` after the scheduled start is considered a match.
4. THE match engine SHALL flag exception cases: clock entry with no matching shift ("unmatched"), shift with no clock entry ("missed shift"), clock-in more than grace window early/late ("early/late arrival").
5. THE system SHALL support per-row manual match override — a user with `timesheet.approve` permission can link a clock entry to a specific schedule entry or mark it as "intentionally unmatched".
6. THE system SHALL support bulk "Match All" action that runs the match engine across all unmatched entries in a pay period.
7. THE system SHALL support bulk "Approve All Clean" action that approves all timesheets where variance is within `auto_approve_threshold_minutes` and there are no exception flags.
8. THE match engine results SHALL be stored on the Timesheet's hour-band breakdown: matched minutes contribute to `ordinary_minutes`, overtime detection populates `overtime_minutes`, and public-holiday detection populates `public_holiday_minutes`.

### Requirement 9 — TimeClockEntry.branch_id Enforcement

**User Story:** As a system architect, I want all new clock entries to have a branch_id so that branch scoping works reliably going forward, without breaking existing data.

#### Acceptance Criteria

1. THE system SHALL enforce NOT NULL validation on `branch_id` for all NEW `time_clock_entries` at the application layer (service-level validation on insert).
2. THE system SHALL add a forward-only CHECK constraint on `time_clock_entries` that enforces `branch_id IS NOT NULL` for rows created after the migration date (using `created_at > migration_timestamp`).
3. THE system SHALL NOT backfill existing NULL `branch_id` rows — they remain as-is for historical accuracy.
4. THE `branch_id` on a kiosk-sourced clock entry SHALL be derived from the authenticated kiosk user's `branch_ids[0]` JWT claim — never free-entered by the clocking user.
5. THE `branch_id` on a self-service clock entry SHALL be derived from the user's session context (branch selector or primary branch assignment).
6. THE `branch_id` on an admin-manual clock entry SHALL be explicitly selected by the admin creating the entry.

### Requirement 10 — Cross-Branch Clock-Out

**User Story:** As a staff member who clocked in at Branch A but is finishing their shift at Branch B, I want the system to record both branches so that payroll can attribute the hours correctly.

#### Acceptance Criteria

1. THE system SHALL add a `clock_out_branch_id` column to `time_clock_entries` (UUID, FK → branches, nullable).
2. WHEN a staff member clocks out at a branch different from their `branch_id` (clock-in branch), THE system SHALL store the clock-out branch in `clock_out_branch_id`.
3. FOR Phase A (v1), THE system SHALL attribute all `worked_minutes` to the clock-in branch (`branch_id`) for timesheet aggregation and branch scoping purposes.
4. THE Clocked In tab SHALL display "In: {clock_in_branch} / Out: {clock_out_branch}" when the two differ.
5. THE system SHALL leave an extension point (documented interface) for future proportional cost-splitting across branches. This is NOT built in Phase A.

### Requirement 11 — Kiosk Branch-Scoped Credentials

**User Story:** As a branch admin, I want each kiosk device at my branch to authenticate with a branch-bound credential so that clock entries from that kiosk are automatically and trustworthily attributed to my branch.

#### Acceptance Criteria

1. THE system SHALL use the existing `users.branch_ids` JSONB column on kiosk-role users to bind each kiosk to exactly one branch (stored as `branch_ids = [branch_id]`).
2. THE system SHALL derive `TimeClockEntry.branch_id` from the authenticated kiosk user's JWT `branch_ids[0]` claim on kiosk-sourced clock events.
3. THE system SHALL require exactly one `branch_id` when creating/inviting a kiosk user — enforced at the invite endpoint.
4. THE existing `kiosk` RBAC role SHALL be preserved. The `branch_ids` field carries branch attribution metadata; role permissions are unchanged.
5. THE system SHALL reject kiosk clock-in requests where the kiosk user's `branch_ids[0]` does not match any active branch in the org (stale/revoked credential scenario).
6. THE existing `BranchContextMiddleware` already reads `branch_ids` from JWT claims — kiosk users will be naturally branch-scoped without additional middleware changes.
7. No new `kiosk_credentials` table is needed for v1. Multi-device-per-branch or device-level revocation can be added in a future phase.

### Requirement 12 — TimesheetApproval Repurposing

**User Story:** As an architect, I want to repurpose the existing `timesheet_approvals` table as an approval-event audit record linked to the new Timesheet entity, preserving all existing data while adding forward-looking structure.

#### Acceptance Criteria

1. THE system SHALL add a `timesheet_id` FK column (nullable) to the existing `timesheet_approvals` table, referencing the new `timesheets` table.
2. THE existing `week_start`/`week_end` date range columns SHALL be demoted to informational metadata — no longer the primary key for approval lookup. The `timesheet_id` FK becomes the canonical link.
3. THE system SHALL preserve ALL existing `timesheet_approvals` rows unchanged. The migration is additive only (ADD COLUMN, not DROP/RENAME).
4. NEW approval events SHALL write a `timesheet_approvals` row with `timesheet_id` populated, recording the approval action, actor, and computed totals at approval time.
5. THE system SHALL treat `timesheet_approvals` as an append-only audit log of approval events — multiple rows may exist per timesheet (approve, reject, re-approve).

## Phase B Requirements (Outline)

### Requirement B1 — Clock-to-Payslip Hour Mapping

- When a Timesheet is locked, its hour breakdown (ordinary/overtime/public_holiday minutes) feeds directly into `Payslip.ordinary_hours`, `Payslip.overtime_hours`, `Payslip.public_holiday_hours` at draft generation time.
- The `Timesheet.payslip_id` FK links to the generated payslip for traceability.
- A locked timesheet cannot be modified; corrections create an adjustment line on the next open PayPeriod referencing the original timesheet.

### Requirement B2 — Pay Cycle Groups

- New `PayCycle` entity: `id`, `org_id`, `name`, `frequency` (weekly/fortnightly/monthly), `anchor_date`, `pay_date_offset_days`.
- New `PayCycleAssignment` entity: `id`, `pay_cycle_id`, `target_type` (all/branch/employment_type/staff), `target_id` (nullable — NULL for 'all').
- Add `pay_cycle_id` FK to `PayPeriod`; change UNIQUE to `(org_id, pay_cycle_id, start_date)`.
- Auto-generate `PayPeriod` rows per cycle on a scheduled task.

### Requirement B3 — Tab 3: Pay Runs

- A pay-run view showing all timesheets for a pay period grouped by pay cycle.
- Actions: generate payslip drafts, finalise period, mark paid.
- Locked timesheets flow into payslips; unlocked timesheets block the finalise action.

### Requirement B4 — Corrections After Lock

- Correction creates an adjustment line on the next open PayPeriod with fields: `original_timesheet_id`, `adjustment_minutes`, `reason`, `created_by`.
- No edits to locked periods or already-finalised payslips.
- Adjustment lines are visible on both the original timesheet (as a note) and the correction period (as a line item).

## Phase C Requirements (Outline)

### Requirement C1 — Overtime Auto-Detect

- Configurable daily and weekly overtime thresholds per org/branch.
- The aggregation service automatically classifies minutes exceeding thresholds as `overtime_minutes`.
- Supports NZ Holidays Act time-and-a-half for overtime and alternative-day overtime.

### Requirement C2 — Break Enforcement

- Configurable mandatory break rules (e.g., 30-min meal break after 4 hours, 10-min rest break every 2 hours).
- Exception flags raised when break records don't satisfy the configured rules.
- Warning displayed on Timesheet tab for non-compliant entries.

### Requirement C3 — Regional Public Holiday Calendar

- Integration with the existing `public_holidays` table (`app/modules/admin/models.py`).
- Hours worked on a public holiday automatically classified as `public_holiday_minutes`.
- Branch timezone awareness — a holiday is determined by the branch's local date, not UTC.

### Requirement C4 — Leave Accrual Trigger + Versioned Engine

- New `LeaveRuleSet` provider pattern: `holidays_act_2003` (active), `employment_leave_act_2026` (stubbed).
- Single entrypoint: `resolve_ruleset(org, date)` returns the applicable rule set.
- Methods: `accrue(staff, period)`, `value_leave_taken(staff, leave_request)`, `otherwise_working_day(staff, date)`, `public_holiday(branch, date)`, `termination_payout(staff)`.
- Leave accrual triggered at period finalisation (when timesheets are locked).

## Non-Functional Requirements

### NFR-1 — Performance

1. THE Clocked In tab SHALL load in under 500ms for organisations with up to 200 concurrent clocked-in staff.
2. THE Timesheets tab SHALL load the full period list (up to 500 staff) in under 1 second.
3. THE aggregation service (computing rostered/actual for a full period) SHALL complete in under 5 seconds for 500 staff × 14-day period.
4. Branch query scoping SHALL add no more than 10ms latency to queries.

### NFR-2 — Data Retention

1. THE system SHALL retain all `time_clock_entries`, `timesheets`, and `timesheet_approvals` records for a minimum of seven years per the Employment Relations Act 2000.
2. Clock immutability (Requirement 5) supports the retention requirement by preventing deletion at the DB level.

### NFR-3 — Audit Trail

1. ALL timesheet status transitions SHALL be recorded in the `audit_log` table with action `timesheet.<transition>`, the actor user_id, and before/after state.
2. ALL adjustments to `adjusted_minutes` SHALL be recorded in the `audit_log` with the previous and new values.
3. THE audit trail SHALL be queryable by org_id, staff_id, and date range.

### NFR-4 — Module Registration

1. THE timesheets module SHALL be registered in `DEPENDENCY_GRAPH` with dependencies: `["staff", "scheduling"]`.
2. THE timesheets module SHALL be registered in `MODULE_ENDPOINT_MAP` with prefix `/api/v2/timesheets` → `"timesheets"`.
3. THE module SHALL be gatable — organisations can enable/disable it via the module management system.

## Out of Scope

1. **Phase D** — PAYE calculation engine, IRD payday filing, bank-file export. These are separate modules that consume Timesheet/Payslip data but are not part of this spec.
2. **Proportional cross-branch cost splitting** — Phase A attributes all hours to clock-in branch. Splitting is a future extension.
3. **Mobile app screens** — The timesheets UI is desktop/tablet first. Mobile views will be specced separately.
4. **GPS geofence enforcement on clock-in** — Already handled by the existing time_clock module's geofence logic. This spec does not modify it.
5. **Self-service timesheet submission by staff** — Phase A is manager-driven. Staff self-submission (requesting approval) is a Phase B extension.
6. **Overtime pre-approval workflow** — Already exists in `OvertimeRequest`. This spec reads approved overtime requests but does not modify the workflow.
