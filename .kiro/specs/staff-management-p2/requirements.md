# Staff Management — Phase 2: Leave Engine + Holidays Act Compliance

## Overview

Phase 2 of the Staff & Contractor Management System. Builds the leave system: configurable leave types, per-staff balances, request workflow, append-only ledger, anniversary-based annual-leave accrual, the 6-month sick-leave gate, casual 8% pay-as-you-go support, public-holiday "otherwise working day" engine, and the Holidays Act s40A auto-extension when a public holiday falls inside annual leave.

**Source:** `docs/future/staff-management-system.md` §6 Phase 2, §4 (NZ employment law specifics), §7A categories D and E (Holidays Act edges + TOIL).

**Trade-family scope:** Universal across all 16 trade families. Module gate via `staff_management`.

**Status:** Draft, depends on Phase 1.

**Prerequisites:** Phase 1 must be shipped (employment record fields + module registration are the foundation Phase 2 builds on).

## Steering compliance

Inherits all Phase 1 steering compliance bullets. Additions specific to this phase:

- Leave-accrual engine wraps each per-staff body in `db.begin_nested()` SAVEPOINT (per `performance-and-resilience.md`).
- Idempotency: leave-accrual job is idempotent — running twice in the same day must not double-grant entitlement.
- Public-holiday list (org × upcoming-window of `public_holidays` rows) cached in Redis for 1 hour. Per-staff OWD computations cached separately for 24 h (R8.3 + design §4.2) — they're stable for the holiday's lifetime so a longer TTL is safe. (P2-N9: clarified the two caches are distinct; not a 1h-vs-24h contradiction.)
- Append-only `leave_ledger` table — service code never UPDATEs or DELETEs ledger rows; corrections write a new compensating row.
- Family-violence-leave records visible to approver only (per-org permission flag, not a new role).

## Requirements

### R1. Configurable Leave Types

**User story:** As an org admin, I want NZ statutory leave types pre-seeded for my org plus the ability to add custom types like "Study leave", so the leave system maps to my real policies.

**Acceptance criteria:**

1. THE SYSTEM SHALL create a `leave_types` table with columns: `id` (uuid PK), `org_id` (uuid FK organisations, NOT NULL), `code` (text, NOT NULL — e.g. `annual`, `sick`, `bereavement`, `family_violence`, `public_holiday_alt`, `unpaid`, `toil`, `custom_*`), `name` (text), `is_paid` (boolean), `accrual_method` (text, CHECK in `'anniversary','fixed_annual','per_period','unaccrued','event_based'`), `accrual_amount` (numeric), `accrual_unit` (text default `'hours'` — values `'hours'|'days'`), `carry_over_max` (numeric, NULL = unlimited), `is_statutory` (boolean default false), `requires_doctor_note` (boolean default false), `confidential_visibility` (boolean default false), `active` (boolean default true), `display_order` (int default 0), `created_at`, `updated_at`. Unique on `(org_id, code)`.
2. THE SYSTEM SHALL enable RLS + tenant_isolation policy.
3. THE SYSTEM SHALL ship a one-off backfill migration that inserts **7 leave types** per existing org (cross-phase X2 fix — TOIL added so P3's overtime-handling flow has a target leave_type to write to without an FK violation):
   - `annual` — anniversary, 4 weeks/year (= `standard_hours_per_week × 4` granted on each anniversary). `is_statutory=true`.
   - `sick` — per_period, 80 hours/year (10 days × 8 hours by default; pro-rata for variable hours), gated to first accrual after 6 months. `requires_doctor_note=true`. `is_statutory=true`.
   - `bereavement` — event_based, balance always 0; per-event cap (3 days for close family, 1 day for others) enforced server-side via `leave_requests.relationship_to_subject` field — see R4.7. `is_statutory=true`.
   - `family_violence` — per_period, 80 hours/year, gated to 6 months. `confidential_visibility=true` — see R4.6 for the visibility-permission mechanism. `is_statutory=true`.
   - `public_holiday_alt` — event_based; balance grows when staff actually works an OWD public holiday. `is_statutory=true`.
   - `unpaid` — unaccrued, balance always 0; requests don't decrement anything. `is_statutory=true`.
   - **`toil`** — event_based, `is_paid=true`, balance always 0 by default; written to by P3's timesheet-approval flow when `overtime_handling='toil'` or `'employee_chooses'` (per P3 R10/R11). `is_statutory=false` because TOIL is a contractual choice rather than a statutory entitlement, but pre-seeded for every org as universal infrastructure so P3's accrual writes don't FK-violate.
4. THE SYSTEM SHALL allow `is_statutory=true` rows to be edited (rates can go ABOVE the legal floor) but not deleted; DELETE returns HTTP 403 with reason.
5. THE SYSTEM SHALL allow custom leave types to be created, renamed, deactivated.
6. THE SYSTEM SHALL gate the entire surface behind `ModuleService.is_enabled(org_id, 'staff_management')`.

### R2. Leave Balances Per Staff

**Acceptance criteria:**

1. THE SYSTEM SHALL create a `leave_balances` table: `id, org_id, staff_id (FK, ON DELETE CASCADE), leave_type_id (FK, ON DELETE RESTRICT), accrued_hours numeric(8,2) default 0, used_hours numeric(8,2) default 0, pending_hours numeric(8,2) default 0, anniversary_date date, last_accrual_at timestamptz, updated_at timestamptz default now(). Unique on (staff_id, leave_type_id)`.
2. RLS + tenant_isolation policy.
3. WHEN a staff member is created with `employment_start_date` THE SYSTEM SHALL insert one `leave_balances` row per active `leave_types` row for that org, with `anniversary_date = employment_start_date` for `accrual_method='anniversary'` types.
4. WHEN an existing org first gets the leave system enabled (via the post-Phase-2 backfill migration) THE SYSTEM SHALL insert balance rows for every active staff × every active leave_type combination.

### R3. Leave Ledger (append-only)

**Acceptance criteria:**

1. THE SYSTEM SHALL create a `leave_ledger` table: `id, org_id, staff_id, leave_type_id, delta_hours numeric(8,2), reason text (CHECK enum), request_id uuid (FK leave_requests, nullable), occurred_at date, created_by uuid (FK users, nullable), created_at timestamptz default now()`. Reason enum: `'accrual', 'request_approved', 'request_cancelled_after_approval', 'manual_adjustment', 'opening_balance', 'termination_payout', 'public_holiday_extension', 'public_holiday_worked', 'pay_run_payout', 'toil_accrual'` (cross-phase X3 fix — `'toil_accrual'` added forward-compatibly so P3's TOIL write is unambiguous and doesn't require a P3-time enum amendment).
2. RLS + tenant_isolation policy.
3. THE SYSTEM SHALL never UPDATE or DELETE ledger rows from application code. Corrections write a new row with the inverse `delta_hours` and `reason='manual_adjustment'`.
4. THE SYSTEM SHALL surface the ledger via `GET /api/v2/staff/:id/leave/ledger?leave_type_id=...` with `{ items, total }` shape. **(P2-N10)** When `leave_type_id` filters to a leave type with per-event semantics (e.g., bereavement), each ledger item additionally surfaces `request_relationship_to_subject` (resolved via JOIN to `leave_requests.relationship_to_subject` when `request_id IS NOT NULL`). For other leave types this field is `null` so consumers can render or hide the column conditionally.

### R4. Leave Requests

**Acceptance criteria:**

1. THE SYSTEM SHALL create a `leave_requests` table: `id, org_id, staff_id, leave_type_id, start_date date, end_date date, hours_requested numeric(6,2), status text default 'pending' (CHECK in `'pending','approved','rejected','cancelled'`), reason text, relationship_to_subject text (CHECK in `'close_family','other'` when set; nullable for non-bereavement), partial_day_start_time time (nullable; populated when `hours_requested < standard_daily_hours` AND `start_date == end_date` — see G5/G7 future enhancements), attachment_upload_id uuid, requested_by uuid, decided_by uuid, decided_at timestamptz, decision_notes text, created_at, updated_at`.
2. RLS + tenant_isolation policy.
3. THE SYSTEM SHALL expose endpoints:
   - `POST /api/v2/staff/:id/leave/requests` — submit request (writes pending; increments `pending_hours` on balance).
   - `GET /api/v2/staff/:id/leave/requests` — list, filter by status.
   - `GET /api/v2/leave/requests` — org-wide approval queue (admin/manager only).
   - `POST /api/v2/leave/requests/:request_id/approve` — moves pending → approved, decrements `pending_hours`, increments `used_hours`, writes ledger row, creates `schedule_entries` rows for each affected day with `entry_type='leave'`.
   - `POST /api/v2/leave/requests/:request_id/reject` — moves pending → rejected, decrements `pending_hours`, no ledger row.
   - `POST /api/v2/leave/requests/:request_id/cancel` — staff cancels own pending; or admin cancels approved (writes inverse ledger row).
4. THE SYSTEM SHALL refuse submissions where `hours_requested > balance.accrued_hours - balance.used_hours - balance.pending_hours` UNLESS the leave type is `event_based` or `unaccrued`. Returns HTTP 422 with reason `insufficient_balance` and the available figure.
5. WHEN approval succeeds for a leave type with `requires_doctor_note=true` (sick) AND `attachment_upload_id IS NULL` AND request is more than 3 consecutive working days THE SYSTEM SHALL show a warning to the approver (not a block) — Holidays Act s68.
6. WHEN a leave_type has `confidential_visibility=true` (family_violence) THE SYSTEM SHALL only return the request to (a) the requesting staff member, OR (b) users who hold the `leave.fv_view` permission via the existing `user_permission_overrides` table. See R4.9 for the mechanism.

7. **Bereavement per-event cap (Holidays Act s70).** WHEN `leave_type.code='bereavement'`:
   - THE SYSTEM SHALL require `leave_requests.relationship_to_subject IN ('close_family','other')` at submission. Server returns HTTP 422 with reason `relationship_required` if missing.
   - THE SYSTEM SHALL enforce the per-event cap at `submit_request` time:
     - `close_family` → cap at `3 × standard_daily_hours` (typically 24h)
     - `other` → cap at `1 × standard_daily_hours` (typically 8h)
   - Where `standard_daily_hours = staff.standard_hours_per_week / 5` (rounded to 2dp).
   - If `hours_requested > cap`, return HTTP 422 with reason `bereavement_cap_exceeded` and the cap figure in the error body.
   - No running balance is held; each new bereavement request is independent (the cap applies per request, not per year).
   - Approval writes a `leave_ledger` row with `reason='request_approved'`, `delta_hours = -hours_requested`. The ledger remains the audit trail for who took how much per-event.

8. **Leave in advance (informational).** Phase 2 does NOT support "in advance" annual-leave requests directly. Admins who wish to grant leave before anniversary use the `Adjust balance` workflow (R12.5) to pre-fund the staff's annual-leave `accrued_hours`. The resulting `leave_ledger` row carries `reason='manual_adjustment'` with the admin's explanatory text. This is a deliberate Phase 2 simplification; a first-class in-advance flow is reserved for a Phase 2.5 enhancement if customer feedback demands it.

9. **Confidential-leave visibility mechanism.** THE SYSTEM SHALL:
   - Reuse the existing `user_permission_overrides` table (already wired through `app/middleware/rbac.py:_load_permission_overrides_cached`). The table's actual columns (verified at `app/modules/auth/permission_overrides.py`) are: `id, user_id, permission_key, is_granted, granted_by, created_at`. There is NO `org_id` column — tenant scoping comes from joining `users.org_id`.
   - Introduce a permission key `leave.fv_view` (dot-separated, two-part — matches the `module.action` convention used throughout `app/modules/auth/rbac.py::ROLE_PERMISSIONS`). **(P2-N1)** This permission is granted **always explicitly per-user** via a `user_permission_overrides` row; there is no role-level shortcut. The earlier draft claimed a `leave.*` wildcard would auto-grant the permission to roles configured for full leave-module access — that was incorrect: no role currently has `leave.*` in its permissions list.
   - On the Phase 2 migration backfill, grant `leave.fv_view` to every user with role `org_admin` at the moment of migration by inserting `user_permission_overrides` rows with `permission_key='leave.fv_view'` and `is_granted=true` (with a Settings nag banner asking the org owner to review and revoke from anyone who shouldn't have it).
   - Provide a Settings UI at `Settings?tab=people-permissions` listing org users with on/off checkboxes; toggling calls `create_or_update_permission_override` / `delete_permission_override` (existing helpers at `app/modules/auth/permission_overrides.py`) which handle audit logging automatically.
   - At the API layer, every endpoint that returns `leave_requests` for any leave_type with `confidential_visibility=true` SHALL filter to rows where `requested_by = current_user` OR the current user holds the permission. The check uses the synchronous `app/modules/auth/rbac.py::has_permission(role, permission_key, overrides=request.state.permission_overrides)` helper — the overrides list is already loaded by `RBACMiddleware`, so no additional DB call is needed.
   - The RBAC middleware cache TTL (currently 60s per [security-hardening-checklist.md §1](../../.kiro/steering/security-hardening-checklist.md)) is acceptable for this permission; revocation takes effect within one minute.

### R5. Anniversary Annual-Leave Accrual

**Acceptance criteria:**

1. THE SYSTEM SHALL add a daily scheduled task `accrue_annual_leave` (registered in `app/tasks/scheduled.py`).
2. Task runs once per UTC day, scoped to the existing scheduler Redis SETNX lock.
3. For each active staff with `employment_type='permanent'` and `accrual_method='anniversary'` annual-leave row:
   - Compute `next_accrual = anniversary_date + N years` where N is years since start.
   - If `next_accrual <= today`:
     - Grant `standard_hours_per_week × 4` hours to `leave_balances.accrued_hours`.
     - Update `last_accrual_at = now()`.
     - Insert `leave_ledger` row with `reason='accrual'`, `occurred_at=next_accrual`, `delta_hours=+granted`.
     - Apply `carry_over_max` cap: if `accrued_hours - used_hours > carry_over_max`, write a compensating ledger row reducing accrued back to cap (use-or-lose policy).
4. THE SYSTEM SHALL be idempotent — running twice on the same UTC day with no time change MUST NOT double-grant. Idempotency guard: SELECT existing ledger row for `(staff_id, leave_type_id, occurred_at, reason='accrual')` before insert; skip if found.
5. Each per-staff iteration wraps in `db.begin_nested()` SAVEPOINT; one staff's failure does not abort the batch.
6. Logs per-staff outcome.

### R6. Sick + Family-Violence 6-Month Gate

**Statutory basis:** Holidays Act 2003 s63 (sick leave) + Domestic Violence — Victims' Protection Act 2018 (family violence leave). Both unlock after 6 months of continuous employment.

**Acceptance criteria:**

1. THE SYSTEM SHALL add per_period accrual jobs (sub-tasks of `accrue_annual_leave` or their own daily task) — **one for sick leave, one for family-violence leave**. Both share the same 6-month gate and pro-rata logic.

2. **Sick leave** (Holidays Act s63):
   - Skip until `now() - employment_start_date >= 6 months`.
   - On first day past the 6-month mark, grant `(staff.standard_hours_per_week or 40) × 2` hours (P2-N8: 80 h for a standard 40 h/week worker, 60 h for a 30 h/week part-timer, etc. — keeps the rule referenced to a single source-of-truth column rather than a literal).
   - On each subsequent anniversary (yearly) grant the same again, with `(staff.standard_hours_per_week or 40) × 4`-hour `carry_over_max` cap (Holidays Act s67 — max 20 days at any one time).

3. **Family-violence leave** (Domestic Violence — Victims' Protection Act 2018):
   - Same 6-month gate as sick leave.
   - On first day past the 6-month mark, grant `(staff.standard_hours_per_week or 40) × 2` hours (P2-N8). Pro-rata for variable hours flows from the same formula.
   - On each subsequent anniversary, grant the same.
   - `carry_over_max = (staff.standard_hours_per_week or 40) × 2` (statute does not allow carry-over of family-violence leave; unused hours expire at anniversary).

4. **Idempotency:** Same guard as R5.4 — each `_process_*_yearly` function does `SELECT 1 FROM leave_ledger WHERE staff_id=? AND leave_type_id=? AND reason='accrual' AND occurred_at=?` before insert; skips on existing row.

5. **Casual employees** (cross-reference R7): sick + family_violence still accrue, pro-rata by `standard_hours_per_week`.

6. Each per-staff iteration wraps in `db.begin_nested()` SAVEPOINT.

### R7. Casual Employees + 8% Holiday Pay-as-you-go

**Acceptance criteria:**

1. THE SYSTEM SHALL detect `employment_type='casual'` staff and skip annual-leave accrual entirely (no ledger rows).
2. THE SYSTEM SHALL still accrue sick + family_violence pro-rata (per R6).
3. THE SYSTEM SHALL store the casual 8% obligation as a payslip line in Phase 4 — Phase 2 only ensures balance + ledger semantics are correct (no annual balance card displayed for casual staff).
4. WHEN viewing Leave tab for a casual staff THE SYSTEM SHALL render banner "Casual — 8% pay-as-you-go on each pay run" instead of an annual-leave balance card.

### R8. Public Holiday Engine (s49–s50, s40A)

**Acceptance criteria:**

1. THE SYSTEM SHALL add a daily task `process_public_holidays` that runs after `accrue_annual_leave`:
   - For each `public_holidays` row in the next 14 days for country='NZ':
     - For each active staff in each org:
       - Compute `is_owd` (otherwise-working-day) — 4-week pattern from `time_clock_entries` if it exists yet (Phase 3); else fall back to `availability_schedule` template (`monday`/`tuesday`/... weekday key set).
       - If `is_owd` and a `schedule_entries` row exists with `entry_type='job'|'booking'|'other'` covering the holiday → flag the entry with `metadata.public_holiday_pay='time_and_a_half'` and grant 1 alt-day to `public_holiday_alt` balance via ledger row `reason='public_holiday_worked'`.
       - If `is_owd` and no work scheduled → flag for "relevant daily pay" calculation in Phase 4.
       - If not OWD → no entitlement.
2. THE SYSTEM SHALL implement Holidays Act s40A: when an approved annual-leave request includes a public-holiday date that's an OWD for the staff:
   - On approval → automatically extend the request by adding a `schedule_entries` row with `entry_type='leave'` covering one extra working day immediately after the original `end_date` (skipping weekends and other public holidays).
   - Write a `leave_ledger` row with `reason='public_holiday_extension'` and `delta_hours=+standard_daily_hours`.
3. THE SYSTEM SHALL cache OWD computations in Redis keyed `staff:owd:{staff_id}:{holiday_date}` with 24h TTL.
4. Idempotency: same date for same staff cannot trigger two ledger rows. Guard via existing-row SELECT.

### R9. Average Daily Pay snapshot

**User story:** Required for public-holiday pay where ordinary daily pay can't be determined. Phase 2 stores the snapshot; Phase 4 uses it on payslips.

**Acceptance criteria:**

1. THE SYSTEM SHALL add a column `staff_members.average_daily_pay_snapshot numeric(10,2)`.
2. THE SYSTEM SHALL add a daily task `update_adp_snapshots` that for each active staff:
   - Sum gross earnings over last 52 weeks (placeholder — this requires Phase 4 payslips; until then, falls back to `hourly_rate × standard_hours_per_week × 52`).
   - Count days worked over last 52 weeks (until Phase 3 clock-in data exists, fall back to `availability_schedule` weekday count × 52).
   - Compute `gross / days_worked`.
   - Save to column.
3. Phase 2 ships the column + scheduled task with the placeholder calc; Phase 4 swaps the calc to use real payslip data.

### R10. TOIL (Time Off In Lieu) Storage

Acceptance criteria:

1. THE SYSTEM SHALL include the `toil` leave type as one of the **7 pre-seeded leave types** that ship for every org (per R1.3 — cross-phase X2 fix). `is_statutory=false` because it's a contractual choice; but seeded for every org regardless of `overtime_handling` value so P3's overtime-toil flow can write to a guaranteed-existent leave_type_id without FK violations.
2. THE SYSTEM SHALL add `organisations.overtime_handling` enum column (`pay_cash` default, `toil`, `employee_chooses`). (P2-N5: typed column on `organisations`, NOT a key in any `org_settings` JSONB blob — settled here so Phase 4's helper reads the typed column directly.)
3. Phase 3 will write to TOIL balance from approved overtime hours via `leave_ledger` row `reason='toil_accrual'` (per cross-phase X3 — `'toil_accrual'` added to the leave_ledger.reason CHECK enum below); Phase 2 only ensures the leave type and balance row exist.

### R11. Settings → People → Leave Types Page

**User story:** As an org admin, I need a CRUD UI for leave types in Settings, where I can edit accrual rates, deactivate custom types, and review which types are statutory.

**Acceptance criteria:**

1. THE SYSTEM SHALL add a sub-route in Settings → People → Leave Types.
2. THE SYSTEM SHALL list all `leave_types` for the org, sortable by `display_order`.
3. THE SYSTEM SHALL allow creating, editing (rate, name, carry-over), deactivating custom types.
4. THE SYSTEM SHALL block deletion of statutory types (server-side enforced in R1.4).
5. THE SYSTEM SHALL allow editing accrual rates ABOVE statutory minimums (e.g. annual = 5 weeks instead of 4); the UI flags the value with a green "above minimum" badge.

### R12. Leave Tab on Staff Detail

**Acceptance criteria:**

1. THE SYSTEM SHALL add a Leave tab to the tabbed Staff Detail introduced in Phase 1.
2. THE SYSTEM SHALL render a balance card per active leave type for that staff:
   - Name, Available (= `accrued_hours - used_hours - pending_hours`), Used, Pending, Anniversary date.
   - For casual: replace card with "8% pay-as-you-go" banner.
3. THE SYSTEM SHALL render a ledger history table (filterable by leave_type).
4. THE SYSTEM SHALL render "Request leave" button → modal with leave_type select, date range, reason, optional doctor's note upload.
5. THE SYSTEM SHALL render "Adjust balance" button (admin only) → modal with leave_type, +/- hours, reason text. Writes ledger row with `reason='manual_adjustment'`.

### R13. Leave Approval Queue

**Acceptance criteria:**

1. THE SYSTEM SHALL add a global page `/leave/approvals` (sidebar item under "People" or "Operations").
2. Queue shows all pending requests for the org (or for the manager's reports if `branch_admin`/`reporting_to`-scoped).
3. Each row: staff name + photo, leave type, dates, hours, reason, doctor's-note attachment, balance preview ("Available 64 → 56 if approved").
4. Inline Approve / Reject buttons; Reject prompts for decision_notes.
5. Approval workflow per R4.3.

### R14. Notifications

**Acceptance criteria:**

1. WHEN a leave request is approved THE SYSTEM SHALL send an email to the staff member: "Your annual leave from 12-19 June has been approved." Routes through `send_email` with `dlq_task_name='leave_decision_email'`.
2. WHEN rejected THE SYSTEM SHALL send a similar email including `decision_notes`.
3. WHEN approved AND `weekly_roster_sms_enabled` is true on the staff record THE SYSTEM SHALL also send an SMS confirmation.

### R15. Audit Logging

THE SYSTEM SHALL call `write_audit_log(...)` (writing to the `audit_log` table) for:

- `leave_type.created`, `leave_type.updated`, `leave_type.deactivated`
- `leave_balance.adjusted`
- `leave_request.submitted`, `leave_request.approved`, `leave_request.rejected`, `leave_request.cancelled`
- `leave_accrual.batch_run` (one row per task run, with summary counters)
- `public_holiday.alt_granted`
- `public_holiday.s40a_extension`

### R16. E2E Test Script

**Acceptance criteria:**

1. THE SYSTEM SHALL ship `scripts/test_staff_leave_e2e.py`.
2. Script flow per source plan: configure leave types, set casual employee 8% flag, advance time to anniversary via mock, verify accrual ledger row, submit leave request, approve, verify balance decrement, verify schedule_entries row created, verify s40A extension fires for public holiday inside leave window, cleanup.

### R17. Versioning

THE SYSTEM SHALL bump 1.14.0 → 1.15.0 across `pyproject.toml`, `frontend/package.json`, `mobile/package.json`. CHANGELOG entry under `## [1.15.0]`.

## Non-Goals (Phase 2)

- Clock-in/clock-out (Phase 3)
- TOIL accrual from approved overtime (Phase 3 — Phase 2 only ships the leave type + setting hook)
- Payslips (Phase 4)
- Casual 8% line ON the payslip (Phase 4 — Phase 2 only enforces the no-accrual rule)
- Bank export, IRD export (Phase 5)

## Open Questions

- **STAFF-002 (resolved):** Family-violence-leave visibility uses the existing `user_permission_overrides` table with permission key `leave.fv_view` (P2-N1: dot-separated, matching the rbac.py convention; this entry previously used the inconsistent `leave:family_violence:view` form) — see R4.9. Backfill grants the permission to current org_admins; ongoing administration via Settings → People → Permissions. Decision based on: (a) reuses existing RBAC infrastructure already cached by [`app/middleware/rbac.py`](../../app/middleware/rbac.py), (b) scales to N approvers without schema change, (c) audit trail comes for free.
- **STAFF-003:** Confirm Nager.Date NZ public-holiday observed dates match Holidays Act observed dates (Monday-isation of public holidays falling on Saturday/Sunday). Settle before R8 lands in production. Suggested check: pull 2024+2025 NZ public-holiday list from Nager.Date and compare against [employment.govt.nz/public-holidays](https://employment.govt.nz/leave-and-holidays/public-holidays/public-holidays-and-anniversary-dates/) — line up dates including any Monday-ised observances.
- **STAFF-009 (new, deferrable):** Half-day / partial-day leave UX. Phase 2 schema supports `leave_requests.partial_day_start_time` but the frontend doesn't expose a partial-day toggle. Resolution deferred to Phase 2.5 — see Non-Goals.
- **STAFF-010 (new, deferrable):** Leap-year anniversary edge case (employees with `employment_start_date = Feb 29`). Use the helper rule "same `MMDD` or last day of February in non-leap years". Phase 2 ships the rule in `accrue_for_staff` per design §4.1.

## Verification Gates

All checkboxes in source plan §12 pre-merge gate must be ticked.
