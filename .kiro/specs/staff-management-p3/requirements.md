# Staff Management — Phase 3: Clock-in/Out + Hours Approval + Operational Layer

## Overview

Phase 3 captures actual hours worked, compares them to scheduled hours, supports week-end approval with locked timesheets, and adds the day-to-day operational features hourly-staff workshops actually run on: shift swaps, open-shift cover broadcasts, break recording, missed-clock-out alerts, late-arrival SMS, overtime pre-approval, and TOIL banking.

**Source:** `docs/future/staff-management-system.md` §6 Phase 3, §7A categories B and E (TOIL).

**Trade-family scope:** Universal across all 16 trade families.

**Status:** Draft, depends on Phases 1 + 2.

## Steering compliance

Inherits Phase 1 + 2 compliance. Additions:

- Kiosk surface uses the existing `/kiosk/*` route family pattern from `app/modules/kiosk/router.py` — STAFF-006 settles whether shared or dedicated path.
- All Capacitor calls (mobile photo capture, geolocation) guarded by `isNativePlatform()`.
- Photo storage uses encrypted uploads (`app/modules/uploads/`) — never raw S3.
- Buddy-punch defence is photo + on-file comparison, not PIN.
- Self-service clock-in is opt-in per staff via Phase 1's `self_service_clock_enabled` flag.
- Break records back-deduct from worked time per ERA s69ZD.
- Approved week locks all `time_clock_entries` and any in-period `time_entries` (existing billable timer); edits create an `edited_after_approval` audit record.

## Requirements

### R1. `time_clock_entries` Table + Photo + Source Audit

**Acceptance criteria:**

1. THE SYSTEM SHALL create `time_clock_entries`: `id, org_id, staff_id (FK staff_members), clock_in_at timestamptz NOT NULL, clock_out_at timestamptz NULL, source text NOT NULL CHECK IN ('kiosk','self_service_mobile','self_service_web','admin_manual'), clock_in_photo_url text, clock_out_photo_url text, clock_in_lat numeric(9,6), clock_in_lng numeric(9,6), clock_out_lat numeric(9,6), clock_out_lng numeric(9,6), scheduled_entry_id uuid (FK schedule_entries), break_minutes int NOT NULL DEFAULT 0, notes text, created_by uuid (FK users), worked_minutes int, created_at timestamptz NOT NULL DEFAULT now()`.
2. CHECK constraint: `source <> 'kiosk' OR clock_in_photo_url IS NOT NULL` — kiosk entries MUST have a clock-in photo (data-integrity backstop).
3. RLS + tenant_isolation policy.
4. Indexes (CONCURRENTLY): `(org_id, staff_id, clock_in_at DESC)`, `(staff_id) WHERE clock_out_at IS NULL` (open-clock-in lookup), `(org_id, clock_in_at) WHERE clock_out_at IS NULL` (missed-clock-out alerts).

### R2. `break_records` Table

**Acceptance criteria:**

1. `break_records`: `id, org_id, time_clock_entry_id (FK), break_type text CHECK IN ('rest_paid','meal_unpaid'), start_at timestamptz NOT NULL, end_at timestamptz NULL, minutes int, created_at`.
2. RLS + tenant_isolation policy.
3. Indexes: `(time_clock_entry_id)`, `(org_id, start_at)`.

### R3. Kiosk Clock-in Flow (the primary channel)

**User story:** As a staff member arriving at work, I tap the kiosk "Clock in / Clock out" button, enter my employee_id, take a photo, and I'm clocked in. No login required.

**Acceptance criteria:**

1. THE SYSTEM SHALL register routes under the existing kiosk surface: `GET /kiosk/clock` (welcome screen) → `POST /kiosk/clock/lookup` (employee_id lookup) → `POST /kiosk/clock/action` (clock-in or clock-out + photo upload).
2. THE SYSTEM SHALL refuse the lookup with HTTP 422 when no active staff matches `employee_id`. Generic error: "Employee code not recognised. Please see your manager." (Don't enumerate IDs.)
3. THE SYSTEM SHALL rate-limit lookups to 10 per minute per `(org_id, employee_id)` to prevent enumeration. Rate-limit storage: existing rate-limit Redis pattern.
4. WHEN lookup matches THE SYSTEM SHALL return `{ staff_id, first_name, on_file_photo_url, currently_clocked_in: bool }`.
5. THE SYSTEM SHALL require a captured photo on every kiosk action: the request payload must include a `photo_upload_id` (reference to a successful POST to `/api/v2/uploads`); the endpoint refuses with 422 `photo_required` otherwise.
6. THE SYSTEM SHALL create a `time_clock_entries` row with `source='kiosk'` on clock-in OR update the open row's `clock_out_at` + photo + worked_minutes calc on clock-out.
7. THE SYSTEM SHALL compute `worked_minutes = (clock_out_at - clock_in_at) - break_minutes` on close.
8. THE SYSTEM SHALL match `scheduled_entry_id` automatically: pick the staff's `schedule_entries` row whose `(start_time, end_time)` window the clock-in falls within (closest match if multiple).
9. THE SYSTEM SHALL render the confirmation screen showing on-file photo + just-taken photo side-by-side for visual comparison (kiosk operator/queue can challenge mismatches in person).

### R4. Self-Service Clock-in (Mobile + Web)

**User story:** As a staff member with `self_service_clock_enabled=true`, I can clock in/out from my mobile or my own login.

**Acceptance criteria:**

1. THE SYSTEM SHALL add `POST /api/v2/staff/me/clock-action` accepting `{ action: 'in'|'out', photo_upload_id, lat?, lng? }`.
2. THE SYSTEM SHALL refuse with 403 when the staff record's `self_service_clock_enabled=false` (error body: `"Self-service clock-in not enabled — please use the kiosk."`).
3. THE SYSTEM SHALL require a photo when the org-level setting `self_service_require_photo=true` (default true).
4. THE SYSTEM SHALL enforce geofence when `self_service_require_geofence=true`: refuses with 422 when `(lat, lng)` is more than `branch.radius_metres` from the branch's configured `(lat, lng)`.
5. THE SYSTEM SHALL set `source='self_service_mobile'` or `'self_service_web'` based on user-agent.
6. Mobile screen at `/clock` (lazy-loaded in `mobile/src/StackRoutes.tsx`) — single big "Clock in"/"Clock out" button, opens Capacitor camera (guarded by `isNativePlatform()`) + Geolocation.
7. Web screen at `/staff/me/clock` — same UX, uses `getUserMedia` for photo capture; falls back with helpful error if browser denies camera.

### R5. Admin-Manual Clock Entry

**Acceptance criteria:**

1. THE SYSTEM SHALL allow org_admin / branch_admin to insert/edit `time_clock_entries` rows from the Hours tab.
2. Manual entries set `source='admin_manual'` and `created_by=user_id`.
3. Manual entries don't require a photo.
4. Every manual edit writes `audit_logs` action='time_clock.edited' with before/after JSON.

### R6. Org-level Clock-in Policy Settings

**Acceptance criteria:**

1. THE SYSTEM SHALL add `org_settings.clock_in_policy` JSONB block with defaults:
   - `default_channel: 'kiosk_only'` (enum: `kiosk_only | kiosk_and_self_service`)
   - `self_service_require_photo: true`
   - `self_service_require_geofence: false`
   - `branch_radius_metres: 200`
   - `allow_late_clock_out_edits: true`
   - `kiosk_employee_id_rate_limit: 10` (per minute)
2. THE SYSTEM SHALL render Settings → People → Clock-in Policy page with all toggles + numeric inputs.
3. WHEN `default_channel` is changed THE SYSTEM SHALL NOT mass-update existing staff's `self_service_clock_enabled` flag — the flag is the source of truth at clock-in time. Setting only controls the default value on staff-creation going forward.

### R7. Break Compliance Recording (ERA s69ZD)

**Acceptance criteria:**

1. THE SYSTEM SHALL allow staff (or admin on their behalf) to record breaks via `POST /api/v2/staff/:id/clock/break-start` and `POST /api/v2/staff/:id/clock/break-end` (writes to `break_records`).
2. THE SYSTEM SHALL auto-suggest break windows when a shift is created in `schedule_entries` with `entry_type='job'|'booking'|'other'`:
   - Shift ≥ 4h → suggest 1 paid 10-min rest at midpoint.
   - Shift ≥ 6h → suggest 1 paid rest + 1 unpaid 30-min meal.
   - Shift ≥ 10h → suggest 2 paid rests + 1 unpaid meal.
3. THE SYSTEM SHALL deduct `break_records` rows with `break_type='meal_unpaid'` from worked_minutes on clock-out close.
4. THE SYSTEM SHALL flag any approved-week's shifts that had less than the legally required break time recorded — surfaces as a warning chip on the timesheet approval UI.

### R8. Hours Tab on Staff Detail

**Acceptance criteria:**

1. THE SYSTEM SHALL add an "Hours" tab to Staff Detail (between Roster and Leave).
2. THE SYSTEM SHALL render a week selector + two stacked rows per day:
   - **Scheduled** (from `schedule_entries`) — minutes per day.
   - **Actual** (from `time_clock_entries`) — minutes per day after break deduction.
   - **Variance** column — actual - scheduled.
3. THE SYSTEM SHALL render a drill-down list of `time_clock_entries` for the week with clock-in / clock-out / break records inline.
4. WHEN admin THE SYSTEM SHALL render an "Approve hours" button at the week-end (visible Sunday onward).

### R9. `timesheet_approvals` Table + Locking

**Acceptance criteria:**

1. THE SYSTEM SHALL create `timesheet_approvals`: `id, org_id, staff_id (FK), week_start date, week_end date, status text default 'pending' CHECK IN ('pending','approved','rejected','edited_after_approval'), total_worked_minutes int, total_scheduled_minutes int, total_overtime_minutes int default 0, total_break_minutes int default 0, ordinary_minutes int default 0, public_holiday_minutes int default 0, toil_choice text CHECK IN ('pay_cash','toil') NULL, approved_by uuid (FK users), approved_at timestamptz, notes text. Unique on (staff_id, week_start)`.
2. RLS + tenant_isolation policy.
3. WHEN admin clicks Approve THE SYSTEM SHALL:
   - Compute totals from `time_clock_entries` + `break_records` + `schedule_entries` overlap with public holidays.
   - Insert/upsert `timesheet_approvals` row status=approved.
   - Lock all `time_clock_entries` for that staff in `[week_start, week_end]` against further edit (server-side guard: refuses PUT/DELETE when an approved row exists).
   - Lock any `time_entries` (the existing billable-timer table) in the same window against being marked `is_invoiced` from the approval flow (separate concern; we don't change the existing time_entries module).
4. WHEN admin clicks "Re-open week" THE SYSTEM SHALL update status='edited_after_approval' (audit log) and unlock edits.
5. WHEN any underlying time_clock_entries row is edited (admin manual flow) AFTER approval THE SYSTEM SHALL flip status to `'edited_after_approval'` and re-compute totals.

### R10. Overtime Pre-approval Flow

**User story:** As a manager, I want to approve overtime BEFORE staff actually work it, so I'm not surprised at week-end.

**Acceptance criteria:**

1. THE SYSTEM SHALL add `overtime_requests` table: `id, org_id, staff_id, schedule_entry_id (nullable, links to specific shift), proposed_extra_minutes int, reason text, requested_by, status (pending|approved|rejected), decided_by, decided_at, created_at`.
2. THE SYSTEM SHALL allow staff or admin to submit a request when a shift is expected to run long.
3. WHEN week is approved AND staff has worked overtime AND no overtime_request was approved THE SYSTEM SHALL flag the timesheet with a warning chip "X hours of overtime — no pre-approval".

### R11. TOIL Accrual from Approved Overtime

**Acceptance criteria:**

1. WHEN `timesheet_approvals` is approved AND org policy `overtime_handling='toil'` THE SYSTEM SHALL grant the overtime hours to the staff's `toil` leave balance via `leave_ledger` row `reason='request_approved'` (or new reason `'toil_accrual'` — design picks).
2. WHEN policy is `'employee_chooses'` THE SYSTEM SHALL render a per-week choice on the approval UI ("Cash" or "TOIL") and write balance/payroll-side accordingly.
3. WHEN policy is `'pay_cash'` THE SYSTEM SHALL accumulate overtime into `total_overtime_minutes` for Phase 4 to pick up on the payslip.

### R12. Shift Swap Requests

**Acceptance criteria:**

1. THE SYSTEM SHALL add `shift_swap_requests` table: `id, org_id, requester_staff_id (FK), target_staff_id (FK, NULL = open), schedule_entry_id (FK), status (pending|accepted|rejected|cancelled), reason, created_at, decided_at`.
2. THE SYSTEM SHALL expose endpoints for staff to request swap, target staff to accept/reject.
3. WHEN accepted THE SYSTEM SHALL update the `schedule_entries.staff_id` to target_staff_id.
4. THE SYSTEM SHALL send SMS to target_staff_id when request is created.

### R13. Open-Shift Cover Broadcast

**Acceptance criteria:**

1. THE SYSTEM SHALL add `shift_cover_requests` table: `id, org_id, schedule_entry_id, requester_staff_id, status, accepted_by, broadcast_at, expires_at`.
2. THE SYSTEM SHALL allow admin/staff to mark a shift "open for cover" — on creation:
   - All other staff with the same `skills` overlap (or all active staff if no skill filter) receive an SMS: "Cover needed: {shift_summary}. Reply YES on the app to claim."
   - First responder via the app's Open Shifts page claims it; the SMS does not have a magic-link claim path in Phase 3 — that is a Phase 4+ enhancement.
3. THE SYSTEM SHALL update the schedule entry's staff_id to the accepting staff and notify the requester.

### R14. Late-Arrival + Missed-Clock-Out Alerts

**Acceptance criteria:**

1. THE SYSTEM SHALL add a 5-minutely scheduled task `check_late_arrivals`:
   - For each staff with a current-day `schedule_entries` row whose `start_time` was 15+ minutes ago AND no matching open `time_clock_entries.clock_in_at` exists:
     - Once-per-shift, send SMS to manager (`reporting_to`): "Late: {staff_name} hasn't clocked in for {shift_label} (started {start_time})."
     - Optionally SMS staff: "You're scheduled to clock in for {shift}."
   - Track sent state in a `late_arrival_alerts_sent` keyed cache (Redis 8h TTL) to prevent duplicate alerts.
2. THE SYSTEM SHALL add an hourly task `check_missed_clock_outs`:
   - For each `time_clock_entries WHERE clock_out_at IS NULL AND clock_in_at < now() - interval '12 hours'`:
     - Send SMS to staff: "Did you forget to clock out?"
     - Notify manager.

### R15. Mobile Clock-in Screen

**Acceptance criteria:**

1. THE SYSTEM SHALL add a `Clock` mobile screen at `mobile/src/screens/clock/ClockScreen.tsx`.
2. Lazy import in `StackRoutes.tsx`.
3. ModuleGate `staff_management`. Hidden when staff has `self_service_clock_enabled=false`.
4. Single big button "Clock in" (when not currently clocked) or "Clock out" (when clocked).
5. Tap → Capacitor camera capture → Geolocation (if required by org policy) → POST `/api/v2/staff/me/clock-action`.
6. Loading + error + success states; pull-to-refresh shows current status.

### R16. Audit Logging

THE SYSTEM SHALL call `write_audit_log(...)` (writing to the `audit_log` table) for:

- `time_clock.in`, `time_clock.out`, `time_clock.edited`, `time_clock.deleted`
- `break.started`, `break.ended`
- `timesheet.approved`, `timesheet.reopened`
- `overtime_request.submitted`, `overtime_request.approved`, `overtime_request.rejected`
- `shift_swap.requested`, `shift_swap.accepted`, `shift_swap.rejected`
- `shift_cover.requested`, `shift_cover.accepted`
- `clock_policy.updated`

### R17. E2E Test Script

**Acceptance criteria:**

1. THE SYSTEM SHALL ship `scripts/test_staff_clock_in_out_e2e.py`.
2. Flow: set up shift; clock in via mock kiosk POST; log break; clock out; verify worked_minutes calc with break deduction; attempt clock-in for non-existent employee_id (422); trigger missed-clock-out via time mock; approve week; verify lock prevents edit; cleanup.

### R18. Versioning

THE SYSTEM SHALL bump 1.15.0 → 1.16.0.

## Non-Goals

- Automated face-match (deferred — STAFF-008).
- Bank-file export (Phase 5).
- Payslips (Phase 4).
- Magic-link SMS shift-cover claim (Phase 4+).

## Open Questions

- **STAFF-005:** Whether `staff_member` role's permissions are sufficient for self-service or a more restricted "staff_self_service" role is needed.
- **STAFF-006:** Kiosk routing — shared `/kiosk` surface or dedicated `/staff-kiosk`. Settle in design (recommend shared with a "Staff" tile on the welcome screen).
- **STAFF-007:** Photo retention policy. Default: 6 years to match Holidays Act wage record retention.
