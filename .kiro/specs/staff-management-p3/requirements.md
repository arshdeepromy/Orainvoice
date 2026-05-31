# Staff Management — Phase 3: Clock-in/Out + Hours Approval + Operational Layer

## Overview

Phase 3 captures actual hours worked, compares them to scheduled hours, supports week-end approval with locked timesheets, and adds the day-to-day operational features hourly-staff workshops actually run on: shift swaps, open-shift cover broadcasts, break recording, missed-clock-out alerts, late-arrival SMS, overtime pre-approval, and TOIL banking.

**Source:** `docs/future/staff-management-system.md` §6 Phase 3, §7A categories B and E (TOIL).

**Trade-family scope:** Universal across all 16 trade families.

**Status:** Draft, depends on Phases 1 + 2.

## Steering compliance

Inherits Phase 1 + 2 compliance. Additions:

- Kiosk surface uses the existing `/api/v1/kiosk/*` route family pattern from `app/modules/kiosk/router.py` (verified at `app/main.py:364`). New clock routes mount at `/api/v1/kiosk/clock/lookup` and `/api/v1/kiosk/clock/action` and use the SAME `dependencies=[require_role("kiosk"), Depends(_check_kiosk_rate_limit)]` pattern as the existing `POST /api/v1/kiosk/check-in`. The kiosk tablet's pre-existing role-`kiosk` JWT (30-day refresh) is the auth surface — no separate per-staff login. STAFF-006 settled.
- All Capacitor calls (mobile photo capture, geolocation) guarded by `isNativePlatform()`.
- Photo storage uses encrypted uploads via a new `clock_photos` category in `app/modules/uploads/router.py` (alongside the existing `receipts` and `attachments` endpoints) — never raw S3.
- Buddy-punch defence is photo + on-file comparison, not PIN.
- Self-service clock-in is opt-in per staff via Phase 1's `self_service_clock_enabled` flag.
- Break records back-deduct from worked time per ERA s69ZD.
- Approved week locks **only `time_clock_entries`** (G7) — the existing `time_tracking_v2.time_entries` billable timer has its own `is_invoiced` lock (verified at `app/modules/time_tracking_v2/service.py:172-184`) and is not modified by Phase 3.
- The `flags jsonb` column on `time_clock_entries` (NOT `metadata` — that name is reserved by SQLAlchemy DeclarativeBase) holds review/audit metadata.
- API path drift note: kiosk endpoints retain the `/api/v1/kiosk/*` prefix to coexist with the existing customer-facing kiosk module (which has a frontend mobile app already calling `/api/v1/kiosk/check-in`). All other new P3 endpoints use `/api/v2/...` per the project mobile-app steering rule.

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

**User story:** As a staff member arriving at work, I tap the kiosk "Clock in / Clock out" button on the on-site kiosk tablet, enter my employee_id, take a photo, and I'm clocked in. No staff-specific login required at the device — the kiosk tablet's role-`kiosk` JWT serves the surface (the same auth model as the existing customer-facing kiosk flow).

**Acceptance criteria:**

1. THE SYSTEM SHALL register routes under the existing kiosk surface using the SAME `dependencies=[require_role("kiosk")]` pattern as the existing `POST /api/v1/kiosk/check-in` endpoint:
   - `POST /api/v1/kiosk/clock/lookup` — employee_id lookup
   - `POST /api/v1/kiosk/clock/action` — clock-in or clock-out + photo upload
   The kiosk tablet logs in once with a kiosk-role JWT (existing 30-day refresh model per `tests/properties/test_kiosk_properties.py`); any walk-in staff uses that device's session — no per-staff JWT involved. Routes are NOT in `PUBLIC_PATHS` / `PUBLIC_PREFIXES`; they require the kiosk JWT just like the existing kiosk endpoints.
2. THE SYSTEM SHALL refuse the lookup with HTTP 422 when no active staff matches `employee_id`. Generic error: "Employee code not recognised. Please see your manager." (Don't enumerate IDs.)
3. THE SYSTEM SHALL rate-limit lookups to 10 per minute per `(org_id, employee_id)` to prevent enumeration (G12). Concrete implementation:
   - **Redis key shape:** `kiosk_lookup:{org_id}:{sha256(employee_id)[:16]}` — the `employee_id` is SHA-256-hashed (truncated to 16 hex chars) so the raw code never lands in Redis logs or scans.
   - **Counter:** Redis `INCR` with `EXPIRE 60` on first hit; reject when counter > 10.
   - **Implementation site:** inline check in `app/modules/kiosk/router.py` at the top of the `/api/v1/kiosk/clock/lookup` handler — does NOT add a policy entry to the global `app/middleware/rate_limit.py` policy map because that middleware is per-IP/per-user and doesn't support compound keys. This is on TOP OF the existing `_check_kiosk_rate_limit` (30/min/kiosk-user) — both apply.
   - **Two-layer interaction (P3-N9):** the limiters layer cleanly. `_check_kiosk_rate_limit` runs as a FastAPI dependency BEFORE the route body and rejects with `{"detail":"Too many requests"}` (HTTP 429) when the kiosk-user is over the global 30/min budget. The G12 inline check runs INSIDE the route body and rejects with `{"detail":"kiosk_lookup_rate_limited"}` (HTTP 429) when a specific `(org_id, employee_id)` pair has been queried > 10 times in the last 60s. A real attacker hitting the kiosk endpoint generally trips the global limit first; a buggy retry loop on a single `employee_id` trips G12 second. Distinct response bodies tell ops which limit was hit.
   - **On limit hit:** return HTTP 429 with `Retry-After: 60` header and body `{ "detail": "kiosk_lookup_rate_limited" }`. Audit row `kiosk.lookup_rate_limited` with `{ org_id, employee_id_hash, retry_after }` (note: hashed employee_id in audit too).
   - Lookup that succeeds (200) resets nothing — successful kiosk staff hitting the right code 30× a day are not the threat model; this is purely against enumeration.
4. WHEN lookup matches THE SYSTEM SHALL return `{ staff_id, first_name, on_file_photo_url, currently_clocked_in: bool }`.
5. THE SYSTEM SHALL require a captured photo on every kiosk action: the request payload must include a `photo_file_key` (returned by a prior successful POST to `/api/v2/uploads/clock-photos`); the endpoint refuses with 422 `photo_required` otherwise. **A new upload category `clock_photos` is added to `app/modules/uploads/router.py` (mirrors `/receipts` and `/attachments`); files land at `/app/uploads/clock_photos/<org_id>/<uuid>.{jpg,png}` per the existing `_store(category=...)` helper.**
6. THE SYSTEM SHALL create a `time_clock_entries` row with `source='kiosk'` on clock-in OR update the open row's `clock_out_at` + photo + worked_minutes calc on clock-out.
7. THE SYSTEM SHALL compute `worked_minutes = (clock_out_at - clock_in_at) - break_minutes` on close.
8. THE SYSTEM SHALL match `scheduled_entry_id` automatically: pick the staff's `schedule_entries` row whose `(start_time, end_time)` window the clock-in falls within (closest match if multiple).
9. THE SYSTEM SHALL render the confirmation screen showing on-file photo + just-taken photo side-by-side for visual comparison (kiosk operator/queue can challenge mismatches in person).

### R4. Self-Service Clock-in (Mobile + Web)

**User story:** As a staff member with `self_service_clock_enabled=true`, I can clock in/out from my mobile or my own login.

**Acceptance criteria:**

1. THE SYSTEM SHALL add `POST /api/v2/staff/me/clock-action` accepting `{ action: 'in'|'out', photo_file_key, lat?, lng? }`. (P3-N1: parameter renamed from `photo_upload_id` to match the kiosk action's R3.5 + the canonical `_store(...)` return shape `file_key`.)
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
4. Every manual edit writes an `audit_log` row with `action='time_clock.edited'`, `before_value` capturing the pre-edit ORM dict, `after_value` capturing post-edit values. (P3-N2 + P3-N5: table is `audit_log` singular per `app/modules/admin/models.py:318`; columns are `before_value`/`after_value` JSONB per `app/core/audit.py:35-47`, NOT `before`/`after`.)

### R6. Org-level Clock-in Policy Settings

**Acceptance criteria:**

1. THE SYSTEM SHALL add `organisations.clock_in_policy` JSONB block with defaults:
   - `default_channel: 'kiosk_only'` (enum: `kiosk_only | kiosk_and_self_service`)
   - `self_service_require_photo: true`
   - `self_service_require_geofence: false`
   - `branch_radius_metres: 200` (org-level default for newly-created branches; see G17 resolution below)
   - `allow_late_clock_out_edits: true`
   - `kiosk_employee_id_rate_limit: 10` (per minute)
2. THE SYSTEM SHALL render Settings → People → Clock-in Policy page with all toggles + numeric inputs. The page also surfaces the overtime policy from R6a as a separate card on the same page.
3. WHEN `default_channel` is changed THE SYSTEM SHALL NOT mass-update existing staff's `self_service_clock_enabled` flag — the flag is the source of truth at clock-in time. Setting only controls the default value on staff-creation going forward (see R6b/G9 for the create-staff integration).
4. **Per-branch vs org-default geofence radius (G17 + cross-phase X5):** the authoritative value at clock-in time is `branches.geofence_radius_metres` (the column added in design §3.1). The org-level `clock_in_policy.branch_radius_metres` value is used as the default in two places: (a) the migration populates the column from this org-level default if available, else 200; (b) the Branches CRUD service `create_branch` reads it as the default when a new branch is INSERTed without an explicit radius (per task B12). Once a branch row exists, the column is the source of truth — editing the org-level default does NOT mass-update existing branches.

### R6a. Overtime Policy Settings (G1)

**User story:** As an org admin, I want to configure when overtime kicks in (weekly threshold, daily threshold) and how it's paid (cash, TOIL, or employee chooses), so the timesheet approval flow can correctly split ordinary vs overtime minutes for each staff.

**Acceptance criteria:**

1. THE SYSTEM SHALL add `organisations.overtime_policy` JSONB column with defaults:
   ```json
   {
       "weekly_threshold_minutes": 2400,
       "daily_threshold_minutes": 480,
       "require_pre_approval": false
   }
   ```
   - `weekly_threshold_minutes` — anything above this in a single week is overtime (default 2400 = 40h).
   - `daily_threshold_minutes` — anything above this in a single day is overtime (default 480 = 8h; common in trades). Daily threshold applies in addition to weekly: if a staff works 9h on Monday + 9h Tue + 9h Wed + 9h Thu = 36h total but each day is 1h over the daily threshold → 4h overtime even though weekly total is under 40h.
   - `require_pre_approval` — if true, the timesheet-approval flow refuses to count any overtime minutes that don't have an approved `overtime_requests` row covering them; instead they're flagged as "unapproved overtime" with a warning chip (per R10.3).
2. THE SYSTEM SHALL re-use Phase 2's `organisations.overtime_handling` typed text column (`pay_cash | toil | employee_chooses`, default `'pay_cash'`, CHECK enum). (P3-N4: Phase 2's gap-analysis P2-N5 settled this as a typed column on `organisations`, NOT a JSONB key under `organisations.settings`. Phase 3 reads it directly via `org.overtime_handling` (or `(await db.get(Organisation, org_id)).overtime_handling`) — does NOT use `get_org_settings()` for this particular field. Phase 3 also does NOT add a duplicate definition; the column lives once on `organisations` and Phase 4 reads it via the same direct ORM access.)
3. THE SYSTEM SHALL render the overtime card in Settings → People → Clock-in Policy below the clock-in settings, with the three policy fields + the existing `overtime_handling` enum from Phase 2.
4. WHEN `compute_week_totals` runs (R9.3) THE SYSTEM SHALL split `total_worked_minutes` into `ordinary_minutes` + `total_overtime_minutes` using BOTH thresholds:
   - Compute daily overtime: for each day, `max(0, day_worked_minutes - daily_threshold_minutes)`. Sum across the week → daily_overtime.
   - Compute weekly overtime: `max(0, week_worked_minutes - weekly_threshold_minutes)` — but cap so total isn't double-counted: `weekly_overtime = max(0, weekly_overtime - daily_overtime_already_counted)`.
   - `total_overtime_minutes = daily_overtime + weekly_overtime`.
   - `ordinary_minutes = total_worked_minutes - total_overtime_minutes - public_holiday_minutes`.
5. WHEN `require_pre_approval=true` AND staff worked overtime AND no approved `overtime_requests` row covers it THE SYSTEM SHALL still populate `total_overtime_minutes` BUT also write `timesheet_approvals.notes` with `"unapproved_overtime: {minutes}min — no overtime_request was approved"` so Phase 4 payroll can decide whether to pay or hold it. The approval-queue UI surfaces this with a warning chip.

### R6b. Default-channel propagation to staff creation (G9)

**Acceptance criteria:**

1. THE SYSTEM SHALL extend `app/modules/staff/service.py::StaffService.create_staff` (added in Phase 1) so that when the caller does NOT explicitly supply `self_service_clock_enabled` in the create payload, the service reads `organisations.clock_in_policy.default_channel` and sets:
   - `self_service_clock_enabled = true` when `default_channel == 'kiosk_and_self_service'`
   - `self_service_clock_enabled = false` when `default_channel == 'kiosk_only'` (the system default)
2. WHEN the caller explicitly supplies `self_service_clock_enabled` (any boolean) in the create payload THE SYSTEM SHALL respect it as-is, regardless of org policy.
3. Existing staff records' `self_service_clock_enabled` value is NEVER mutated by changes to `clock_in_policy.default_channel` (per R6.3) — the policy only applies on NEW staff insertion.
4. This task touches the Phase 1 staff module — explicit cross-phase change. Phase 3 owns the patch to Phase 1's `StaffService.create_staff`. The change MUST be guarded by Phase 1's existing `await db.refresh(obj)` pattern.

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
3. THE SYSTEM SHALL render a drill-down list of `time_clock_entries` for the week with clock-in / clock-out / break records inline. Each row SHALL include (G10):
   - Thumbnail of `clock_in_photo_url` and `clock_out_photo_url` (when present) — clickable to expand.
   - When expanded, the photo opens in a side-by-side panel alongside the staff's `on_file_photo_url` (from Phase 1 R2) for **buddy-punch visual verification by the manager**.
   - A "Flag for follow-up" button on each row that writes a flag (`time_clock_entries.flags->>'flagged_for_review'='true'` plus optional reason text in `flags->>'review_reason'`); flagged rows surface a 🚩 chip in the row and in the weekly approval summary at the top of the tab. Note: column is named `flags` not `metadata` — `metadata` is reserved by SQLAlchemy's `DeclarativeBase`.
   - Photo visibility is gated by RBAC — only `org_admin`, `branch_admin`, and `location_manager` can see thumbnails; lower roles see "[photo]" placeholders.
4. WHEN admin THE SYSTEM SHALL render an "Approve hours" button at the week-end (visible Sunday onward). The approval modal SHALL show a count of flagged-for-review entries and require explicit acknowledgement ("3 entries flagged — review before approving?") before allowing the approve action to proceed.

### R9. `timesheet_approvals` Table + Locking

**Acceptance criteria:**

1. THE SYSTEM SHALL create `timesheet_approvals`: `id, org_id, staff_id (FK), week_start date, week_end date, status text default 'pending' CHECK IN ('pending','approved','rejected','edited_after_approval'), total_worked_minutes int, total_scheduled_minutes int, total_overtime_minutes int default 0, total_break_minutes int default 0, ordinary_minutes int default 0, public_holiday_minutes int default 0, toil_choice text CHECK IN ('pay_cash','toil') NULL, approved_by uuid (FK users), approved_at timestamptz, notes text. Unique on (staff_id, week_start)`.
2. RLS + tenant_isolation policy.
3. WHEN admin clicks Approve THE SYSTEM SHALL:
   - Compute totals from `time_clock_entries` + `break_records` + `schedule_entries` overlap with public holidays — and apply the daily + weekly thresholds from R6a to split `ordinary_minutes` vs `total_overtime_minutes`.
   - Insert/upsert `timesheet_approvals` row status=approved.
   - Lock all `time_clock_entries` for that staff in `[week_start, week_end]` against further edit (server-side guard: refuses PUT/DELETE when an approved row exists).
   - **`time_entries` locking is out of scope for Phase 3 (G7).** The existing `time_tracking_v2` module (billable customer-work timer) is a separate concern from attendance. Phase 3 does NOT modify that module's edit/invoice paths. Phase 4 payslip generation will handle the interaction with billable time_entries separately. The pre-existing R9.3 bullet about locking `time_entries` is dropped — when Phase 3 says "lock approved-week edits", it means `time_clock_entries` only.
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

1. WHEN `timesheet_approvals` is approved AND org policy `overtime_handling='toil'` THE SYSTEM SHALL grant the overtime hours to the staff's `toil` leave balance via `leave_ledger` row `reason='toil_accrual'` (cross-phase X3 fix — `'toil_accrual'` is forward-pre-included in P2's leave_ledger.reason CHECK enum, so P3's write does not require an enum amendment). The `toil` leave_type_id is guaranteed to exist for every org per P2 R1.3 + R10.1 (cross-phase X2 fix).
2. WHEN policy is `'employee_chooses'` THE SYSTEM SHALL render a per-week choice on the approval UI ("Cash" or "TOIL") and write balance/payroll-side accordingly.
3. WHEN policy is `'pay_cash'` THE SYSTEM SHALL accumulate overtime into `total_overtime_minutes` for Phase 4 to pick up on the payslip.

### R12. Shift Swap Requests

**Acceptance criteria:**

1. THE SYSTEM SHALL add `shift_swap_requests` table: `id, org_id, requester_staff_id (FK), target_staff_id (FK, NULL = open), schedule_entry_id (FK), status, reason, decided_by uuid (FK users, nullable), created_at, decided_at`. Status CHECK enum: `'pending' | 'awaiting_manager' | 'accepted' | 'rejected' | 'cancelled'` (G8 — the `awaiting_manager` state is new).
2. THE SYSTEM SHALL add a new org-level setting `shift_swap_requires_manager_approval` boolean (default `false`) inside `clock_in_policy` JSONB. Configurable via Settings → People → Clock-in Policy.
3. THE SYSTEM SHALL expose endpoints for:
   - Requester staff: submit swap request (POST → status='pending').
   - Target staff: accept (POST → see workflow below) or reject (POST → status='rejected'+decided_at).
   - Manager (org_admin / branch_admin / requester's `reporting_to`): approve from awaiting_manager (POST → status='accepted') or reject (POST → status='rejected').
   - Requester: cancel own pending request (POST → status='cancelled').
4. **Workflow with configurable manager approval (G8):**
   - Auto-approve mode (`shift_swap_requires_manager_approval=false`, default):
     - Target accepts → status='accepted' → `schedule_entries.staff_id` flips immediately → both staff notified.
   - Manager-approval mode (`shift_swap_requires_manager_approval=true`):
     - Target accepts → status='awaiting_manager' → manager-approval queue notified (no schedule change yet).
     - Manager approves → status='accepted' → `schedule_entries.staff_id` flips → both staff notified.
     - Manager rejects → status='rejected' → both staff notified (no schedule change).
5. **Notification matrix (G13):**
   | Event | SMS to requester | SMS to target | SMS to manager |
   |---|---|---|---|
   | Request created | — | "Bob asked you to take their Sat 10–4 shift. Open the app to accept or reject." | — |
   | Target accepts (auto-approve) | "Alice took your Sat 10–4 shift — it's now hers." | "You're now on the Sat 10–4 shift." | — |
   | Target accepts (manager-approval mode) | "Alice accepted your swap — pending manager approval." | "Pending manager approval — you're not on the shift yet." | "Shift-swap request needs your approval: Bob ↔ Alice on Sat 10–4." |
   | Target rejects | "Alice can't take your Sat 10–4 shift." | — | — |
   | Manager approves | "Manager approved: Sat 10–4 is now Alice's shift." | "Manager approved — you're now on the Sat 10–4 shift." | — |
   | Manager rejects | "Swap rejected by manager — you're still on Sat 10–4." | "Swap rejected by manager." | — |
   | Requester cancels | — | "Bob cancelled the swap request for Sat 10–4." | — |
   - All SMS sends go through Phase 1's `send_sms` helper; each writes an audit row `shift_swap.sms_sent` with `{ event, recipient_staff_id, swap_request_id }`.
   - SMS skipped (with audit row `shift_swap.sms_skipped` and `reason='no_phone'`) when the recipient has no `phone` set.

### R13. Open-Shift Cover Broadcast

**Acceptance criteria:**

1. THE SYSTEM SHALL add `shift_cover_requests` table: `id, org_id, schedule_entry_id, requester_staff_id, status, accepted_by, broadcast_at, expires_at`.
2. THE SYSTEM SHALL allow admin/staff to mark a shift "open for cover" — on creation:
   - SMS broadcast to all staff matching the **eligibility filter** below (G6):
     ```
     1. is_active = true
     2. employee_id IS NOT NULL OR user_id IS NOT NULL
        (must have at least one channel to clock in — kiosk needs employee_id,
        self-service needs user_id)
     3. NOT already scheduled in the window
        [shift.start_time - 30min, shift.end_time + 30min]
        (queries schedule_entries for entry_type IN ('job','booking','other')
        belonging to this candidate)
     4. skills overlap when the shift has any required skills
        (P3-N8: skills overlap is keyed off `schedule_entries.required_skills`,
         a JSONB array column NOT YET PRESENT in the schema. For Phase 3,
         since no such column exists, this step is currently a NO-OP and
         ALL otherwise-eligible staff receive the broadcast SMS. The filter
         is included so a future schema addition flips it on without code
         changes — added if/when shift-skill-tagging ships in a later phase.)
     5. NOT the requester_staff_id themselves
     ```
   - SMS body: "Cover needed: {shift_summary}. Open the app to claim."
   - First responder via the app's Open Shifts page claims it; the SMS does NOT have a magic-link claim path in Phase 3 — that is a Phase 4+ enhancement.
   - The previous wording referenced `clock_pin_hash` as an eligibility check — that was stale (no PIN exists in this system). Replaced with the `employee_id OR user_id` check above.
3. THE SYSTEM SHALL update the schedule entry's staff_id to the accepting staff and notify the requester.
4. THE SYSTEM SHALL re-check eligibility at claim time too — if the claiming staff has since been scheduled into a conflicting shift (race), refuse with HTTP 409 `{"detail": "scheduling_conflict_at_claim"}` and the cover request stays open.

### R14. Late-Arrival + Missed-Clock-Out Alerts

**Acceptance criteria:**

1. THE SYSTEM SHALL add a 5-minutely scheduled task `check_late_arrivals`:
   - For each staff with a current-day `schedule_entries` row whose `start_time` was 15+ minutes ago AND no matching open `time_clock_entries.clock_in_at` exists:
     - Once-per-shift, send SMS to manager (`reporting_to`): "Late: {staff_name} hasn't clocked in for {shift_label} (started {start_time})."
     - Optionally SMS staff: "You're scheduled to clock in for {shift}."
   - Track sent state in a `late_arrival_alerts_sent` keyed cache (Redis 8h TTL) to prevent duplicate alerts. Redis key: `late:{schedule_entry_id}`.
2. THE SYSTEM SHALL add an hourly task `check_missed_clock_outs`:
   - For each `time_clock_entries WHERE clock_out_at IS NULL AND clock_in_at < now() - interval '12 hours'`:
     - Send SMS to staff: "Did you forget to clock out?"
     - Notify manager.

### R14a. Roster-change SMS within 48h (G2)

**User story:** As a staff member, when my upcoming shift's time or assignment changes within the next 48 hours, I want to be notified by SMS so I don't show up at the wrong time.

**Acceptance criteria:**

1. THE SYSTEM SHALL hook into the existing `app/modules/scheduling_v2/service.py::update_entry` (and any other schedule_entries write path — `reschedule` (P3-N11: real method name verified at `service.py:215`, NOT `reschedule_entry`), swap acceptance, cover acceptance) to detect changes to `start_time`, `end_time`, or `staff_id` on a `schedule_entries` row whose `start_time` falls within `now() + 48 hours`.
2. WHEN detected THE SYSTEM SHALL enqueue an SMS to the affected staff:
   - On `staff_id` change → SMS to BOTH the previous staff ("Your Sat 10–4 shift has been reassigned.") and the new staff ("You're now on the Sat 10–4 shift.").
   - On `start_time` / `end_time` change with same staff → SMS to that staff: "Your shift on {day} {date} changed: now {new_start}–{new_end} (was {old_start}–{old_end})."
3. THE SYSTEM SHALL dedupe via Redis `SET NX EX 3600` key `roster_change:{schedule_entry_id}` so multiple edits in quick succession produce one SMS per hour per entry.
4. THE SYSTEM SHALL skip the SMS when:
   - The affected staff has `weekly_roster_sms_enabled=false` (Phase 1 opt-in flag).
   - The affected staff has no `phone` set.
   - Either skip writes an audit row `roster.change_sms_skipped` with `reason='opt_out'` or `reason='no_phone'`.
5. WHEN the SMS is sent successfully THE SYSTEM SHALL write audit row `roster.change_sms_sent` with `{ schedule_entry_id, staff_id, change_type }` in `after_value`.
6. THE SYSTEM SHALL NOT fire for shifts more than 48 hours away (those will be picked up by the Friday auto-roster broadcast from Phase 1 R10).

### R14b. "I'm running late" upward message (G3)

**User story:** As a staff member who's running late, I want to flag this from my phone so my manager knows before I show up, and so the automated "no clock-in yet" alert doesn't also fire.

**Acceptance criteria:**

1. THE SYSTEM SHALL add `POST /api/v2/staff/me/running-late` accepting body `{ minutes_late: int (1-180), reason: text (optional, 200 chars) }`.
2. THE SYSTEM SHALL require the staff to have a `schedule_entries` row today whose `start_time` is in `[now() - 60min, now() + 120min]` — otherwise return HTTP 422 `{ "detail": "no_upcoming_shift" }`.
3. THE SYSTEM SHALL send SMS to the staff's manager (`reporting_to` chain, or org owner if none) via `send_sms`: `"Heads up: {first_name} expects to be {minutes} min late for {shift_label}."` Reason text appended when present.
4. THE SYSTEM SHALL snooze the automated `check_late_arrivals` task's Redis dedupe key (`late:{schedule_entry_id}` SET with TTL extended to `minutes_late + 30`) so the staff-initiated report suppresses the automated alert for that shift.
5. THE SYSTEM SHALL write audit row `staff.reported_late` with `{ schedule_entry_id, minutes_late, reason }` in `after_value`.
6. **Mobile UI:** the `Clock` mobile screen renders a "I'm running late" button below the main Clock In button when (a) staff is NOT currently clocked in AND (b) staff has an in-window scheduled shift per criterion 2 above. Tapping opens a sheet with a minutes slider + reason input + Send button.
7. **Web UI:** the staff self-service `/staff/me/clock` screen renders the same button + sheet.
8. Rate limit: max 3 running-late reports per staff per shift (to prevent abuse / spam to manager).

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

- `time_clock.in`, `time_clock.out`, `time_clock.edited`, `time_clock.deleted`, `time_clock.flagged_for_review` (G10)
- `break.started`, `break.ended`
- `timesheet.approved`, `timesheet.reopened`
- `overtime_request.submitted`, `overtime_request.approved`, `overtime_request.rejected`
- `shift_swap.requested`, `shift_swap.target_accepted`, `shift_swap.target_rejected`, `shift_swap.manager_approved`, `shift_swap.manager_rejected`, `shift_swap.cancelled`, `shift_swap.sms_sent`, `shift_swap.sms_skipped` (G8 + G13)
- `shift_cover.requested`, `shift_cover.accepted`, `shift_cover.claim_conflict` (G6 — race-at-claim)
- `clock_policy.updated`, `overtime_policy.updated` (G1)
- `roster.change_sms_sent`, `roster.change_sms_skipped` (G2)
- `staff.reported_late` (G3)
- `kiosk.lookup_rate_limited` (G12)

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
- **Photo orphan cleanup job (G15).** Phase 3 does NOT ship a scheduled deletion task for clock-in/out photos. The default policy is **retain for 6 years** to match Holidays Act s81 wage-record retention requirement (resolves STAFF-007 in favour of retention). When a `time_clock_entries` row is hard-deleted via admin manual flow, the associated `clock_in_photo_url` / `clock_out_photo_url` upload rows are NOT cascade-deleted from `uploads` — they remain accessible to forensic queries. A future phase may add a scheduled "delete uploads orphaned for > 6 years" job; for now, storage cost is acceptable (one photo ≈ 50–200 KB; ~500 staff × ~250 working days/year × 6 years ≈ 750 k photos ≈ 75–300 GB total, manageable on the existing uploads volume).
- **Modifying the existing `time_tracking_v2` billable-timer module (G7).** Phase 3 introduces `time_clock_entries` as a separate concern from the existing `time_entries` table. Approvals lock `time_clock_entries` only; the billable timer is untouched. Phase 4 payroll generation will address any interaction.

## Open Questions

- **STAFF-005:** Whether `staff_member` role's permissions are sufficient for self-service or a more restricted "staff_self_service" role is needed.
- **STAFF-006:** Kiosk routing — shared `/kiosk` surface or dedicated `/staff-kiosk`. Settle in design (recommend shared with a "Staff" tile on the welcome screen).
- **STAFF-007:** Photo retention policy. Default: 6 years to match Holidays Act wage record retention.
