# Changelog

All notable changes to OraInvoice are documented in this file.

---

## [1.18.0]

### Added — Roster Grid Editor

**Roster grid at `/staff-schedule/grid`.** New desktop-first 14-day roster grid editor (≥1024px viewport; mobile users see a fallback banner linking to the day/week view). Staff rows × 14 day columns with a vertical separator between week 1 and week 2. Toolbar carries Today / prev-fortnight / next-fortnight, branch + position filters, template palette toggle, "Apply template" multi-select, "Copy Week 1 → Week 2", "Export CSV", and "Print".

- **Paint mode** — pick a shift template, drag a rectangle, releases a single bulk_create with one entry per cell. 200-cell cap per action, idempotent re-paint of identical cells, leave-shaded cells skipped unless Alt is held (with confirmation modal).
- **Multi-select rows + columns** — click row / column headers (Shift+click for range), then "Apply template" emits the same bulk_create across the (staff × day) matrix.
- **Copy Week 1 → Week 2** — confirmation dialog with source / target counts, optional `overwrite_existing`.
- **Keyboard nav** — arrow keys move focus, Enter opens the create/edit modal, Delete removes the focused entry, Shift+Arrow extends a multi-cell selection, Ctrl+C / Ctrl+V copy / paste cells (in-memory clipboard, never `navigator.clipboard`).
- **Drag-resize handle** — 6-px grab handle on every entry block, snaps to 15-min increments via PUT `/api/v2/schedule/{id}/reschedule`.
- **CSV export** — RFC 4180 compliant; landscape A3 print stylesheet hides toolbar / palette / filters.
- **Conflict banner** — persistent banner lists every conflict from the most recent bulk submit; clicking a row scrolls the grid + outlines the conflicting cell red.
- **Optimistic UI** — paint / apply / copy-week placeholders render with `opacity-60 animate-pulse` and resolve to created entries (or roll back on conflict / network failure).

**New backend endpoints (org_admin / salesperson only):**

- `POST /api/v2/schedule/bulk` — accepts up to 200 entries with per-entry SAVEPOINT rollback. Returns `{ created, conflicts }` where each conflict carries the input index, the attempted payload, and the overlapping existing entries. Per-entry conflicts never abort the batch.
- `POST /api/v2/schedule/copy-week` — shifts a 7-day window into another 7-day window. Refuses 422 unless `target_week_start - source_week_start` is a non-zero multiple of 7 days. Forces `recurrence_group_id = NULL` and `status = 'scheduled'` on every copy. `overwrite_existing` deletes overlapping target entries before insert.
- Both endpoints write a single `audit_log` row per call with summary counts only — never per-entry payloads (R17.3).

**`/api/v2/leave/approvals` extension.** Added optional `start_lte` and `end_gte` query params so the grid can fetch only the leave requests overlapping the visible 14-day window. Backwards-compatible — existing callers passing only `status` / `offset` / `limit` are unaffected.

### Migrations

None — this feature reuses `schedule_entries` and `shift_templates`.

### Tests

- Unit + integration: `tests/unit/test_scheduling_v2_bulk.py`, `test_scheduling_v2_copy_week.py`, `tests/integration/test_scheduling_v2_audit.py`, `test_scheduling_v2_routes.py`, `test_leave_approvals_dates.py`.
- Property-based (Hypothesis): `tests/test_scheduling_v2_bulk_property.py` — bulk_create cardinality + copy_week duration / metadata invariants.
- Frontend property + render tests: `frontend/src/pages/staff-schedule/__tests__/properties.test.ts`, `RosterGrid.test.tsx`, `virtualisation.test.tsx`, plus per-task suites for B6–B20.
- E2E: `scripts/test_roster_grid_editor_e2e.py` covers login → list → bulk → re-bulk-idempotence → copy-week → cross-org payload safety, with `TEST_E2E_RosterGrid_*` cleanup in `finally`.
- Performance (RUN_PERF gated): `tests/integration/test_scheduling_v2_bulk_perf.py` and `frontend/src/pages/staff-schedule/__tests__/perf.test.ts`.

---

## [1.17.0] — 2026-06-01

### Added — Staff Management Phase 4 (Payslips + Allowances + Termination + Wage Variance)

**Payslips engine.** New `app/modules/payslips/` module ships the full payroll surface:
- Pay-period CRUD with weekly / fortnightly / monthly cadences. Daily `roll_pay_periods` task ensures the next 4 periods exist for every org with `payroll` enabled (idempotent via UNIQUE `(org_id, start_date)`); cadence change is non-retroactive (G14).
- Draft generation per active staff with auto-attached recurring allowance rules (G4 — `staff_recurring_allowances` table), KiwiSaver employee + employer auto-deductions (employer informational only, NEVER subtracted from gross — R6.2), and casual 8% holiday pay-as-you-go (R5; line OMITTED entirely when wages are zero per N17).
- Public-holiday band rendered as a separate row on the payslip with rate defaulting to ordinary × 1.5 (Holidays Act s50, G2). Admin-overridable per draft.
- Allowance rows carry `quantity` + `unit` columns (`shift` / `period` / `km`) — derived shift count from approved timesheets for `unit='shift'`, admin-entered for `km`, fixed at 1 for `period` (G18).
- Bulk-finalise console with SAVEPOINT-per-payslip resilience (R9) and email-all option routed through the existing DLQ.
- Pay-period reopen flow (G21) — refuses 409 on `paid`, 422 on already-`open`, allows new compensating drafts alongside the existing locked finalised payslips.
- Finalised-payslip immutability via column allowlist (P4-N26) — only `emailed_at` is mutable post-finalise.

**Termination workflow (R10).** New `terminate_employment` flow:
- Step 0 — `SELECT … FOR UPDATE` row lock on `staff_members` (N19) — concurrent terminate calls serialise; the second sees `is_active=false` and returns 409 `already_terminated`.
- Step 1 — reconciles future-dated approved leave (G16) — cancels the request, writes a compensating leave-ledger row that restores hours, marks future `schedule_entries.status='cancelled'` (NOT hard-delete — preserves the P3 SMS hook + audit history per X8).
- Step 2 — Holidays Act s27 annual-leave payout = greater of (ordinary weekly pay, 52-week average); alt-day payout via ADP snapshot; casual 8% remainder true-up against YTD.
- Step 3 — pay-period selection state machine (G25 + G6): open → use; finalised → reopen + audit `pay_period.reopened_for_termination`; paid → 409; missing → roll forward synchronously.
- Step 4a — KiwiSaver carve-out (N15): KiwiSaver employee + employer apply to the non-s27 portion only.
- Step 5 — flips `is_active=false`, zeros remaining accruing leave balances with compensating ledger rows, writes redacted `staff.terminated` audit row with `payout_summary` (counts only — no dollar amounts per R14 + G12).

**PDF rendering.** New WeasyPrint payslip PDF includes every Wages Protection Act + Holidays Act s130A field — masked bank account `**-****-****NN-**` (G1) or "Cash payment / no bank account on file" fallback when the encrypted column is NULL (N18); masked IRD `***NNN`; tax code; all hour bands incl. public-holiday rate (G2); allowance qty × unit × amount for shift/km units (G18); KiwiSaver employer informational line; leave-taken with rates + balance-after; remaining leave balances; YTD totals (gross, PAYE, KiwiSaver-employee, KiwiSaver-employer — three computed at render time per P4-N25 with NZ tax-year boundary per N16); anniversary date. Multi-page A4 print CSS (G20) with running header/footer and page-break-inside on every table.

**PDF storage.** `app/modules/payslips/pdf_storage.py` mirrors the attachment helper convention — `envelope_encrypt` + zlib + path-style `pdf_file_key` (N3 — replaces the earlier `pdf_upload_id uuid`). `read_payslip_pdf` validates `file_key.startswith(f"payslips/{org_id}/")` to prevent cross-tenant access and path traversal.

**Self-service payslips (G9).** `/api/v2/staff/me/payslips` + web page at `/staff/me/payslips` + mobile screen at `/payslips`. Server-side ownership check via the `staff_members.user_id` partial UNIQUE index `ux_staff_members_user_id` (N1); cross-staff lookups return 404 (NOT 403 — no existence leak). Terminated staff retain access for record retention (N2). Mobile uses Capacitor `Share` plugin with `isNativePlatform()` guard for the PDF download.

**Wage variance report (R12).** `/reports/wage-variance` — per-staff this-period vs previous-period gross with delta and percentage change. Threshold filter highlights flagged rows.

**Settings → People → Pay Periods + Allowance Types.** CRUD UIs with the G21 Reopen button and "Already paid — contact support" tooltip on paid periods.

**Audit redaction enforced (G12).** Every `write_audit_log` call site in `app/modules/payslips/` constructs an explicit redacted `after_value` excluding the forbidden-key set (`gross_pay`, `net_pay`, `amount`, `ird_number`, `bank_account_number`, `paye`, `s27_lump_sum`, `annual_payout_dollars`, `alt_day_total_dollars`, `casual_8pct_remainder_dollars`, `recipient_email`). Lint test `tests/unit/test_payslip_audit_redaction.py` walks the AST and rejects regressions. Self-service GET endpoints do NOT emit audit rows (N2).

### Migrations

- `alembic 0209_payslip_schema.py` — pay_periods, allowance_types (+ 6 default seeds), payslips (with `pdf_file_key text`, `public_holiday_rate`, UNIQUE `(staff_id, pay_period_id)`, `gross_pay`/`net_pay` NOT NULL DEFAULT 0), payslip_allowances (+ `quantity`, `unit`), payslip_deductions, payslip_reimbursements, payslip_leave_lines, staff_recurring_allowances. Added `organisations.pay_period_cadence`, `pay_period_anchor_day`, `pay_date_offset_days`. RLS + `tenant_isolation` policies on every new table. Partial UNIQUE index `ux_staff_members_user_id` (N1).
- `alembic 0210_payslip_indexes.py` — 9 CONCURRENTLY indexes including the G9 self-service list path and G25 termination period-selection path.

### Scheduled tasks

- `roll_pay_periods` — daily, registered in `WRITE_TASKS` + `_DAILY_TASKS` (N10 + C1a).
- `update_adp_snapshots` — switched to use real finalised-payslip data (R13) when available, falls back to the Phase 2 placeholder formula for new hires.

### Module middleware

- New entries in `MODULE_ENDPOINT_MAP` (B11 + N8): `/api/v2/pay-periods`, `/api/v2/payslips`, `/api/v2/allowance-types` → `payroll`. Module-disabled response is **403** (not 404), with `{"detail": …, "module": "payroll"}` body.

### G1–G25 closures

Recurring allowances (G4), public-holiday band (G2), period rolling (G5), period reopen (G21), future-leave reconciliation (G16), allowance quantity semantics (G18), self-service payslips (G9), audit redaction (G12), termination period selection (G25), masked bank account on PDF (G1), cash-payment fallback (N18), bulk-finalise SLO (G24), multi-page header/footer (G20), termination synchronous period roll (G6), cadence non-retroactivity (G14).

### Tests

- `tests/unit/test_payslip_calc.py`, `test_payslip_service.py`, `test_payslip_termination.py`, `test_payslip_pdf.py`, `test_period_rolling.py`, `test_payslip_audit_redaction.py` — 79 unit tests covering every G1–G25 + N1–N20 + P4-N21–N32 closure.
- `tests/property/test_payslip_invariants.py` — Hypothesis-based gross/net + KiwiSaver invariants, casual 8% idempotency, G2 + G18 fuzzed math.
- `tests/integration/test_payslip_pdf_integration.py` — real WeasyPrint render + PDF parse (skips when WeasyPrint native deps absent).
- `scripts/test_staff_payslip_e2e.py` — gap-path end-to-end harness (gated by `RUN_E2E=1`).

### Known deferrals

- STAFF-004 (annual-leave anniversary detection for staff with multiple stints): bank-format choice for the rehire scenario remains deferred to Phase 5 / payroll re-hire flow. No customer impact in production today.

---

## [1.16.0] — 2026-05-31

### Added — Staff Management Phase 3 (Clock-in/Out + Hours Approval + Operational Layer)

- **Kiosk clock-in surface.** New `/api/v1/kiosk/clock/lookup` and
  `/api/v1/kiosk/clock/action` routes use the existing kiosk-role JWT
  pattern — no per-staff login at the device. Staff types employee_id,
  takes a photo, and is shown side-by-side with the on-file photo for
  buddy-punch verification (G10). G12 inline rate limit (10/min per
  hashed `(org_id, employee_id)`, distinct `Retry-After: 60` body) layers
  on top of the existing 30/min/kiosk-user dependency cap (P3-N9).
- **Self-service clock-in (mobile + web).** New `/api/v2/staff/me/clock-action`
  endpoint, gated server-side by `self_service_clock_enabled`. Web at
  `/staff/me/clock`, mobile at `/clock` (lazy-loaded, ModuleGate, Capacitor
  camera + geolocation guarded by `isNativePlatform()`).
- **Break compliance recording (ERA s69ZD).** New `break_records` table.
  Suggested-break windows for 4h / 6h / 10h shifts. `meal_unpaid` breaks
  deduct from `worked_minutes` on clock-out close. Compliance chip on
  Hours tab when a shift has less than the legally required break time.
- **Hours tab + week approval.** New Staff Detail "Hours" tab with week
  selector, scheduled vs actual table, drill-down list, photo thumbnails
  (RBAC-gated to org_admin / branch_admin / location_manager), and
  side-by-side buddy-punch comparison modal. Approve button locks
  `time_clock_entries` against further edit.
- **Overtime split + pre-approval.** New `organisations.overtime_policy`
  JSONB with weekly + daily thresholds; `compute_week_totals` splits
  ordinary vs overtime via both thresholds with double-count guard.
  When `require_pre_approval=true`, the timesheet carries an
  `unapproved_overtime` warning chip in `notes` (G1.5).
- **TOIL accrual round-trip.** When `overtime_handling='toil'` (or
  `'employee_chooses'+'toil'`), week approval writes a `leave_ledger`
  row `reason='toil_accrual'` and bumps the staff's TOIL balance —
  idempotent so re-approve doesn't write duplicates.
- **Time-clock entry locking (G7 scope).** Approved weeks lock
  `time_clock_entries` only — the `time_tracking_v2.time_entries`
  billable timer keeps its own `is_invoiced` lock and is not touched
  by Phase 3.
- **Edited-after-approval flow (G16).** Manual edits on entries inside
  an approved week flip the row to `status='edited_after_approval'`
  + recompute totals + write audit row.
- **Flag-for-review (G10).** New `flags jsonb` column on
  `time_clock_entries`. Manager flags a row from the Hours tab; weekly
  approval requires explicit acknowledgement when there are flagged
  entries. RBAC-gated to org_admin / branch_admin / location_manager.
- **Shift-swap workflow with optional manager approval (G8 + G13).**
  New `shift_swap_requests` table with 5-state machine (`pending`,
  `awaiting_manager`, `accepted`, `rejected`, `cancelled`).
  `clock_in_policy.shift_swap_requires_manager_approval` toggles
  auto-approve vs manager-approval flow. Per-event SMS notification
  matrix per R12.5 — sends to requester, target, and manager based
  on event. Eligibility re-checked at the flip moment with documented
  409 codes (`scheduling_conflict_at_accept`,
  `scheduling_conflict_at_manager_approval`).
- **Open-shift cover broadcast (G6).** New `shift_cover_requests` table.
  Eligibility filter at broadcast time excludes already-scheduled
  staff in `[shift.start - 30min, shift.end + 30min]`. Eligibility
  re-checked at claim — 409 `scheduling_conflict_at_claim` on race.
- **Late-arrival + missed-clock-out alerts (G3).** New scheduled tasks
  `check_late_arrivals` (300s) and `check_missed_clock_outs` (3600s)
  added to `WRITE_TASKS` so they're skipped on standby HA nodes.
  Per-shift Redis dedupe via `late:{shift_id}` (8h TTL).
- **Staff-initiated running-late report (G3).** New
  `/api/v2/staff/me/running-late` endpoint. Finds in-window shift
  in `[now-60m, now+120m]`, sends manager SMS, snoozes
  `late:{shift_id}` Redis key for `(minutes_late + 30) * 60` seconds
  so the automated alert is suppressed. Per-shift rate limit (3 reports
  in 4h) → 429 `too_many_late_reports`. Resolves manager via
  `staff.reporting_to` chain with org_admin fallback (X7).
- **Roster-change SMS hook (G2).** Hooks into `scheduling_v2.update_entry`,
  `reschedule`, plus shift-swap and cover accept paths. Detects
  in-window changes (start_time/end_time/staff_id within 48h),
  Redis-dedupes via `roster_change:{schedule_entry_id}` (1h TTL),
  composes per-template SMS, honours `staff.weekly_roster_sms_enabled`
  opt-out. Skips cancelled entries (P3-N10).
- **Per-branch geofence (G17 + cross-phase X5).** New `branches.lat`,
  `branches.lng`, `branches.geofence_radius_metres` columns. Migration
  backfills existing branches from each org's
  `clock_in_policy.branch_radius_metres` default. New branches inherit
  the org default at creation but the per-branch column is the source
  of truth at clock-in time.
- **Default-channel propagation (G9 + cross-phase X3).** Phase 1's
  `StaffService.create_staff` reads `clock_in_policy.default_channel`
  when caller omits `self_service_clock_enabled` —
  `kiosk_and_self_service` → True; `kiosk_only` → False. Existing
  staff are never mutated by policy changes.
- **Manager-fallback warning chip (cross-phase X7 / D9).** Staff
  Detail Overview tab surfaces an amber chip when the staff's
  `reporting_to` chain doesn't lead to a manager with a `user_id`
  (running-late SMS would fall back to org_admin).
- **Settings page.** New "Clock-in Policy" tab in Settings → People
  surfaces clock-in policy + overtime policy + `overtime_handling`
  enum + `shift_swap_requires_manager_approval` toggle.
- **Sidebar.** "Open shifts" → `/shift-cover` and "Shift swaps" →
  `/shift-swaps`. Shift-swaps badge counter shows red dot when
  managers have `awaiting_manager` rows.
- **Photo upload endpoint.** New `POST /api/v2/uploads/clock-photos`
  multipart endpoint mirrors `/receipts` and `/attachments`. Returns
  `{ file_key, file_name, file_size }` — `file_key` is what the
  clock-action endpoints accept as `photo_file_key` (P3-N1).
- **Photo retention default 6 years (G15).** Photos retained for the
  Holidays Act s81 retention window. No deletion job ships in Phase 3
  — design §3.1 + Non-Goals documented.

### Database

- New tables: `time_clock_entries`, `break_records`,
  `timesheet_approvals`, `overtime_requests`, `shift_swap_requests`,
  `shift_cover_requests`. All RLS-enabled with `tenant_isolation`
  policy.
- New columns: `organisations.clock_in_policy` JSONB,
  `organisations.overtime_policy` JSONB, `branches.lat`,
  `branches.lng`, `branches.geofence_radius_metres`.
- Alembic head moves to **0208** (`0207_time_clock_schema` +
  `0208_time_clock_indexes`). Indexes via CONCURRENTLY: 9 base +
  1 partial for the flagged-for-review query (G10).

### Tests

- 143 new unit tests covering: kiosk lookup + clock action + admin
  manual + worked_minutes + lock check (B3), break round-trip + ERA
  s69ZD compliance (B4), week totals + overtime split + TOIL accrual
  + lock check + recompute_after_edit (B5), swap state machine + cover
  eligibility + claim conflict (B6), overtime request workflow (B6),
  default-channel propagation (B3a), roster-change SMS hook (B7a),
  G12 kiosk lookup rate limit (B9), running-late report (G3),
  branches geofence default (B12).
- New property test `test_clock_calc_invariants.py` — Hypothesis
  invariants on worked_minutes formula and overtime split.
- New E2E script `scripts/test_staff_clock_in_out_e2e.py` covering
  the 10 documented gap paths.

---

## [1.15.0] — 2026-05-31

### Added — Staff Management Phase 2 (Leave Engine)

- **Leave types catalogue.** New `leave_types` table per org with seven
  statutory + custom rows seeded by migration: annual, sick (with
  `requires_doctor_note=true`), bereavement, family violence (with
  `confidential_visibility=true`), public holiday, alternative day, and
  TOIL. Manage via `/settings?tab=leave-types` — list, edit, deactivate
  (statutory delete blocked).
- **Per-staff leave balances + append-only ledger.** New `leave_balances`
  and `leave_ledger` tables. Every accrual, request, approval, cancellation,
  and manual adjustment writes a new ledger row; the balance row is a
  pre-aggregated view. Surfaced on the new Leave tab on each staff record.
- **Daily accrual engine.** New `accrue_leave` scheduled task fires every
  UTC day at 00:30. Anniversary grants for annual leave (Holidays Act 2003),
  yearly grants for sick + family violence, leap-year safe via
  `anniversary_in_year(...)`, days→hours conversion via `days_to_hours(...)`
  for custom days-unit types. Idempotent — same-day re-runs are no-ops.
- **Leave request workflow.** Full submit → approve → reject → cancel
  lifecycle with a partial-day capture branch (single date, hours <
  std_daily), bereavement gate (3 working days for close family, 1 for
  other), TOIL Phase 2 guard (insufficient_toil_balance → 422), and
  compensating ledger rows for cancel-after-approval. Approval queue at
  `/leave/approvals` is role-scoped — org_admin all, branch_admin via
  staff_location_assignments, manager via reporting_to.
- **Public holiday engine.** New `process_public_holidays` scheduled task
  runs after accrual. Implements Holidays Act s12 (Otherwise Working Day
  detection with 24h Redis cache), s40 (alternative-day grant when staff
  scheduled on OWD holiday), and s40A (auto-extend annual leave by one day
  when a public holiday falls inside the leave window).
- **Casual employee handling.** Annual-leave card hidden on the Leave tab
  for `employment_type='casual'` staff (8% holiday-pay-as-you-go shown
  via banner). Sick + family violence still accrue pro-rata.
- **Average Daily Pay snapshot.** New `staff_members.average_daily_pay_snapshot`
  column, refreshed daily by the new `update_adp_snapshots` task.
  Phase 2 placeholder formula (`hourly_rate × standard_hours_per_week ÷
  weekday_count_in_schedule`) — Phase 4 will swap in real payslip data.
- **Family Violence Leave confidential visibility.** New `leave.fv_view`
  permission via `user_permission_overrides`. Confidential leave requests
  (`leave_type.confidential_visibility=true`) are filtered at every list
  endpoint by the synchronous `_apply_confidential_filter` helper that
  reads `request.state.permission_overrides`. Subject access keyed to
  `staff_id` (not `requested_by`) so a staff member submitted on behalf
  by a manager still sees their own request. Migration backfills the
  permission for current org_admins; new `/settings?tab=people-permissions`
  page lets the org owner grant/revoke per-user with optimistic toggle +
  30-day post-migration nag banner.
- **Audit log redaction for confidential leave.** Audit `after_value`
  payloads strip `reason`, `decision_notes`, `relationship_to_subject`,
  and `attachment_upload_id` for `family_violence` requests. Centralised
  via `_audit_after_value(...)` helper; lint test asserts every call site.
- **Approval / rejection notifications.** New `leave_decision_email`
  (DLQ-protected via `send_email`) and SMS (Phase 1 helper, opt-in via
  `weekly_roster_sms_enabled`). Confidential leave types use generic
  body text — never leaks reason, dates, or hours.

### Changed

- `organisations.overtime_handling` — new typed enum column (pay_cash /
  accrue_toil / pay_or_accrue / pay_higher_rate). Phase 4 reads this for
  the overtime → TOIL flow.
- Approval queue endpoint scoped per role — org_admin sees all, branch_admin
  via `staff_location_assignments.location_id IN request.state.branch_ids`,
  manager via `staff_members.reporting_to`.
- New scheduled tasks added to `WRITE_TASKS` so they skip on standby nodes
  (ISSUE-147 standby-write protection).

### Migrations

- `0205_leave_schema.py` — `leave_types`, `leave_balances`, `leave_requests`,
  `leave_ledger` tables; `staff_members.average_daily_pay_snapshot` column;
  `organisations.overtime_handling` column; statutory leave-type backfill
  per org; `leave.fv_view` permission backfill for current org_admins.
- `0206_leave_indexes.py` — 8 indexes via `CREATE INDEX CONCURRENTLY`.

---

## [1.14.0] — 2026-05-31

### Added — Staff Management Phase 1

- **Tabbed Staff Detail page** (Overview / Roster / Documents). Replaces the
  single-form view with a module-gated tabbed shell at `/staff/:id#<tab>`. The
  legacy single-form view still renders for orgs without the `staff_management`
  module enabled.
- **Expanded employment record** on `staff_members` — 22 new columns covering
  employment dates and type, NZ tax code, IRD number (envelope-encrypted),
  KiwiSaver enrolment + employee/employer rates, bank account number
  (envelope-encrypted), probation end date (auto-set to start + 90 days),
  residency type (citizen / permanent_resident / work_visa / student_visa /
  other), visa expiry date (conditionally rendered for visa-holders), opt-ins
  for self-service kiosk clock-in and weekly roster delivery, on-file photo,
  emergency contact, last pay review date, employment agreement upload id.
- **Pay rate history audit ledger.** New `staff_pay_rates` table records every
  rate change with `effective_from`, change reason, and the user who made the
  change. Surfaces on the Overview tab via a collapsible
  `PayRateHistoryPanel`. New endpoint `GET /api/v2/staff/:id/pay-rates`
  returns the paginated history.
- **Minimum-wage warning** on save. When `hourly_rate < threshold` (default
  NZD 23.15, configurable per-org via `minimum_wage_threshold_nzd` in the
  Settings UI), POST/PUT returns HTTP 422 with
  `{detail: 'minimum_wage_below_threshold', threshold: 23.15}`. Resubmitting
  with `minimum_wage_override: true` accepts the rate and writes an
  `audit_log` row with `action='staff.minimum_wage_override'`.
- **Compliance counters** on the Staff List. New `compliance_summary` field on
  `GET /api/v2/staff` carries seven integer counters
  (`probation_ending_soon`, `visa_expiring_soon`, `pay_review_due`,
  `below_minimum_wage`, `missing_agreement`, `missing_employee_id`,
  `missing_start_date`) computed in a single SELECT via `COUNT(*) FILTER`
  aggregates backed by partial indexes. Frontend `ComplianceBanner` renders
  clickable counters that toggle URL filter chips, with a persistent
  non-dismissible banner above the counter row when missing-start-date count
  is non-zero (drives the Phase 2 leave-accrual backfill).
- **Roster delivery — email** via `POST /api/v2/staff/:id/email-roster`.
  Renders `app/templates/email/staff_roster.html`, dispatches via the unified
  `send_email` with `dlq_task_name='roster_email'`, and writes an
  `audit_log` row with `action='roster.emailed'`. Refusal reasons:
  `no_email`, `opt_out`, `no_shifts_in_week`.
- **Roster delivery — SMS** via `POST /api/v2/staff/:id/sms-roster`.
  Composes a 160-char body (downgrades to UCS-2 multi-part when the staff
  first name contains Māori macrons — never transliterated, per G7),
  dispatches via the new `app/integrations/sms_sender.py::send_sms` thin
  wrapper, and writes an `audit_log` row with `action='roster.sms_sent'` and
  `after_value` carrying `encoding`, `segments`, and `phone_number_masked`.
- **Public roster viewer** at `GET /api/v2/public/staff-roster/:token` (no
  auth, token-gated). Mints/reuses one-per-(staff, week) tokens via
  `get_or_create_viewer_token`. Distinguishes 404 `token_not_found` from
  410 `token_expired_staff_deactivated` (G4) and 410 `token_expired`
  (natural 30-day TTL). Per-IP rate-limited at 30 req/min (G5) via the
  rate-limit middleware.
- **Token revocation on staff deactivation/termination** (G4). The deactivate
  and terminate flows expire all of a staff's roster tokens by setting
  `expires_at = now()` in the same transaction and write an `audit_log` row
  with `action='roster.tokens_revoked'`. Reactivation does not un-revoke;
  the staff must receive a fresh roster send to get a new viewer link.
- **Friday-afternoon roster broadcast** scheduled task
  (`weekly_roster_broadcast`, runs every 30 minutes via the existing
  scheduler tick). Body short-circuits unless the org-local time is
  Friday 16:00–16:29; per-staff sends wrapped in `db.begin_nested()`
  SAVEPOINTs so a single failure does not poison the batch.
- **Employment agreement attach** via
  `POST /api/v2/staff/:id/employment-agreement`. Accepts an `upload_id`
  pointing at a previously-uploaded file under the org's
  `attachments/{org_id}/` namespace, sets
  `staff_members.employment_agreement_upload_id`, and writes an
  `audit_log` row with `action='staff.employment_agreement_uploaded'`.
- **Module registration.** New entries in `module_registry` for
  `staff_management` and `payroll` (with `staff_management` as a dependency)
  including setup-question prompts. Mirror rows in `feature_flags` with
  `default_value=true`. Updates `subscription_plans.enabled_modules` for all
  unarchived plans to include both slugs.
- **G1 inline warning** on the Overview tab when `employee_id` is null —
  amber banner with quick-set input that PUTs the new code immediately.
  Phase 3 kiosk clock-in depends on the code, so the prompt surfaces early.
- **G3 inline warning** on the Overview tab when `employment_start_date`
  is null — amber banner with date picker that PUTs the date immediately.
  Phase 2 leave accrual depends on the start date.
- **MinimumWageWarningModal** confirmation dialog on save. Re-submits with
  `minimum_wage_override: true` on confirm.
- **`useTabHash` hook** at `frontend/src/hooks/useTabHash.ts` — syncs the
  active tab with `window.location.hash` so refreshing the page or using
  browser back/forward lands on the same tab.

### Database

- Migration `0203_staff_phase1_schema.py` adds the 22 new columns on
  `staff_members`, the new `staff_pay_rates` (audit ledger) and
  `staff_roster_view_tokens` (public viewer) tables — both with RLS +
  `tenant_isolation` policy and `ON DELETE CASCADE` on FKs (G8). Inserts
  module_registry + feature_flags rows; updates subscription plan enabled
  modules.
- Migration `0204_staff_phase1_indexes.py` adds 10 `CREATE INDEX
  CONCURRENTLY` indexes covering pay rate history access, the five
  `staff_members` compliance counters (anniversary review, probation,
  visa, roster-email/sms opt-in scans), the two G1/G3 missing-field
  partials (`idx_staff_missing_employee_id`, `idx_staff_missing_start_date`),
  and the unique index on `staff_roster_view_tokens(token)` for O(1)
  public viewer lookups.

### API contract

- `GET /api/v2/staff` adds a top-level `compliance_summary` field. The
  legacy `staff` array key is preserved (NOT renamed to `items`) for
  backward compatibility with existing consumers.
- `POST /api/v2/staff` and `PUT /api/v2/staff/:id` accept the 22 new
  fields plus the request-only `minimum_wage_override` flag. Below-min-wage
  saves return HTTP 422 with `{detail: 'minimum_wage_below_threshold',
  threshold}` unless override is set.
- `GET /api/v2/staff/:id/pay-rates` — paginated `{items, total}` shape.
- `POST /api/v2/staff/:id/email-roster` and `/sms-roster` — accept
  `{week_start: 'YYYY-MM-DD'}`, return `{ok, message_id, reason}`.
- `POST /api/v2/staff/:id/employment-agreement` — accepts `{upload_id}`,
  returns the updated staff record with masked PII.
- `GET /api/v2/public/staff-roster/:token` — public viewer (no auth),
  returns `{staff_name, week_start, week_end, entries}` on success.
- New sub-feature endpoints return HTTP 404 `{detail: 'not_enabled',
  module: 'staff_management'}` when the module is disabled (the legacy
  staff route stays accessible — frontend renders the legacy form).

---

## [1.13.0] — 2026-05-30

### Added

- **"Issue Quote" button on the customer profile.** Mirrors the existing
  "Issue Invoice" button. Lands on `/quotes/new` with the customer and
  primary vehicle already pre-filled (rego, make, model, year, odometer,
  WOF / COF expiry, inspection_type).
- **Multi-vehicle picker on customer profile.** When a customer has more
  than one linked vehicle, "Issue Invoice" / "Issue Quote" open a modal
  letting the user select one or several vehicles. The first selected
  vehicle becomes the form's primary; the rest land as additional
  vehicles. Behaviour is unchanged for customers with 0 or 1 linked
  vehicles. New URL contract: `?vehicle_regos=A,B,C` for multi-pick;
  `?vehicle_rego=A` retained for back-compat.
- **`LinkedVehicleResponse` schema now carries the Customer Driven Field
  set** (`odometer`, `service_due_date`, `wof_expiry`, `cof_expiry`,
  `inspection_type`). Previously the schema dropped them silently on
  serialisation, which caused the new-invoice form to receive `undefined`
  for those fields and leave them blank — even though
  `get_customer_profile` was emitting them all along.

### Fixed

- **Invoice edit-mode now persists WOF / COF / odometer / service-due
  changes onto the rendered invoice and PDF.**
  - `update_invoice` now resolves `global_vehicle_id` from `vehicle_rego`
    when the caller didn't supply one (covers quote-converted invoices,
    kiosk-driven invoices, mobile minimal-create) — without this the
    OrgVehicle writeback gate skipped silently.
  - `update_invoice` now refreshes
    `invoice_data_json.vehicle_display` after the OrgVehicle writeback
    so the InvoiceDetail tile and PDF inspection-expiry gate read the
    just-edited value. Mirrors `create_invoice`'s vehicle_display block.
- **`get_invoice` now exposes `vehicle.id` and `vehicle.inspection_type`.**
  The InvoiceCreate edit form's `loadInvoice` reads `inv.vehicle.id` to
  thread `global_vehicle_id` back through the edit save. The last-resort
  fallback branch additionally surfaces WOF / COF / service-due from the
  invoice's own `vehicle_display` snapshot.
- **InvoiceDetail vehicle tile renders WOF / COF for invoices without a
  linked global vehicle record** — falls back to
  `invoice.vehicle_display.wof_expiry` / `cof_expiry` when
  `invoice.vehicle` is null.
- **Quote → Invoice convert carries every vehicle field.**
  `convert_quote_to_invoice` now hands `vehicle_odometer`,
  `vehicle_wof_expiry`, `vehicle_cof_expiry`, plus the full
  `additional_vehicles` shape (incl. WOF / COF / inspection_type / id)
  through to `create_invoice`. Previously these fields were dropped.
- **QuoteCreate "Auto-fill linked vehicle" effect was hitting a
  non-existent `/customers/{id}/vehicles` endpoint** (404 → silent
  no-op). Redirected to `/customers/{id}` and extended the mapping to
  carry the Customer Driven Fields, so any flow that selects a customer
  on QuoteCreate gets the same vehicle data as the URL-prefilled paths.
- **Backend regression tests** in `tests/quotes/` cover:
  - WOF edit refreshes `vehicle_display` and writes OrgVehicle.
  - COF edit re-derives `inspection_type='cof'`.
  - Non-vehicle updates leave `vehicle_display` untouched.
  - `LinkedVehicleResponse` carries the new fields (and back-compat for
    callers without them).

## [1.12.0] — 2026-05-30

### Added

- **Quote ↔ Invoice settings parity.** Notes pre-fill on QuoteCreate, typed
  Payment Terms / Terms & Conditions resolution on the quote response,
  resolved fields surfaced on QuoteDetail, and a single
  `_resolve_document_settings` helper that keeps `GET /quotes/{id}` and
  `generate_quote_pdf` in lock-step. Backed by 22 new tests (PBT for
  resolution precedence, helper purity, API/PDF non-divergence; render
  gates on QuoteDetail; integration tests for the response shape and PDF
  Jinja). No new settings keys, no new endpoints, no migration.
- **Rich-text Notes & T&C on QuoteCreate.** ContentEditable editors for both
  fields preserve formatting (line breaks, bold) when pre-filled from org
  defaults — mirrors InvoiceCreate's existing T&C pattern. Tags no longer
  leak as plain text in the form, the saved quote's detail page, or the PDF.

### Fixed

- **Quote → Invoice convert now carries vehicle metadata.**
  `convert_quote_to_invoice` previously dropped `vehicle_odometer`,
  `vehicle_wof_expiry`, `vehicle_cof_expiry`, and additional-vehicle
  WOF/COF/inspection_type fields when handing off to `create_invoice`.
  All four are now passed through.
- **InvoiceDetail vehicle tile renders WOF/COF for invoices without a
  linked global vehicle record.** When `invoice.vehicle` is null but
  `invoice_data_json.vehicle_display.wof_expiry` is set (common for
  quote-converted invoices, kiosk-driven flows, manual-entry rego), the
  tile now reads the snapshot. Frontend gains a typed `vehicle_display`
  field on `InvoiceDetail`.
- **Editing WOF / COF / odometer / service-due on an invoice now persists
  to the rendered invoice and PDF.** `update_invoice` now (a) resolves
  `global_vehicle_id` from rego when the caller didn't supply one — fixes
  silent edits on quote-converted, kiosk, and mobile-create invoices, and
  (b) refreshes `invoice_data_json.vehicle_display` after the OrgVehicle
  writeback so the InvoiceDetail tile and PDF inspection-expiry gate read
  the just-edited value. Three new regression tests guard the round-trip.
- **`get_invoice` now exposes `vehicle.id` and `vehicle.inspection_type`.**
  Without these fields the InvoiceCreate edit form's `loadInvoice` couldn't
  thread `global_vehicle_id` back through the edit save, breaking the
  edit→read→edit round-trip on every flow that didn't go through the rego
  search dropdown.

## [1.11.1] — 2026-05-26

### Added

- **Multi-provider email failover.** The unified email sender at
  `app/integrations/email_sender.py` reads the `email_providers`
  table, attempts each active provider in `priority ASC` order,
  classifies failures as hard or soft, and falls over to the next
  provider on retryable errors. Replaces 14 hand-rolled `smtplib`
  loops and 18 `send_email_task` callers that previously had zero
  failover. Bounded by per-attempt (15s) and total (45s) time budgets.
- **All scheduled email types now have multi-provider failover** —
  subscription invoices, dunning, portal links, fleet invites,
  compliance reminders, scheduled WOF/rego notifications, all 18
  callers route through the unified sender via the rewritten
  `_send_email_async` (Phase 2). No per-site code changes required;
  failover comes for free.
- **`notification_log` provider columns** — `provider_key`,
  `provider_message_id`, `bounced_at`, `bounce_reason`, `delivered_at`
  (all nullable). Populated on every successful send and on bounce
  webhook events. Migration `0195`. Admin notification log frontend
  shows a Provider column and distinct status badges (sent / delivered
  / bounced / failed) with bounce reason as a hover tooltip.
- **Bounce correlation** — Brevo and SendGrid bounce webhooks now
  match the originating `notification_log` row by
  `provider_message_id` and flip its status to `bounced` with the
  reason. The Brevo `delivered` event sets `delivered_at`. Webhook
  signature verification reads the secret from
  `email_providers.config` first, env-var fallback for one release.
- **`bounced_addresses` blocklist** — recipients with a hard bounce
  on file are short-circuited before any provider is tried. Soft
  bounces log a warning and proceed. Daily cleanup task drops expired
  soft-bounce rows. Admins can clear a bounce row through the new
  Delivery Health view to retry an address. Migration creates the
  `bounced_addresses` table with RLS enabled and a functional unique
  index on `(COALESCE(org_id, ''), LOWER(email_address))`.
- **Delivery Health admin UI** — new tab inside Admin → Email
  Providers showing 24h / 7d / 30d bounce stats by provider plus a
  recent-bounces table with a per-row Clear action. Endpoints:
  `GET /api/v2/admin/email-providers/delivery-health` and
  `DELETE /api/v2/admin/email-providers/bounced-addresses/{id}`.
  Accessible to global_admin and org_admin.
- **Multi-active provider support on the activate endpoint** —
  `POST /api/v2/admin/email-providers/{id}/activate` now flips only
  the named row to `is_active=true` instead of deactivating every
  other provider. The list endpoint response gains
  `active_providers: list[str]` (priority order); the singular
  `active_provider` is preserved for backwards compatibility.
- **Last-active deactivation guard.** `POST
  /api/v2/admin/email-providers/{id}/deactivate` acquires a
  row-level lock on the active set and returns HTTP 409 if
  deactivating the named row would leave zero active providers,
  with the message `"Activate another provider before deactivating
  this one — at least one active email provider is required for
  outbound mail."`. The Email Providers admin page disables the
  Deactivate button on the last active row.
- **Failover preview line** on the Email Providers admin page
  ("Send order: 1. X → 2. Y → 3. Z") when more than one provider
  is active. Priority slider visible whenever credentials are saved
  (with "Will apply when activated" helper text on inactive rows).
- **No-providers and all-auth-fail in-app alerts** — global admins
  get a critical-severity in-app notification when an outbound send
  finds zero active providers (deduped to once per hour) or when
  every active provider returns `SOFT_AUTH` (deduped once per day).
  Alerts include a deep link to the admin Email Providers page.
- **Group C stub emails finally deliver.** `_send_anomalous_login_alert`,
  `_send_token_reuse_alert`, and `_send_org_admin_invitation_email`
  previously logged-and-returned without sending. They now build a
  real message and dispatch through the unified sender. Forgot
  Password (1.11.1 hotfix) is rewritten to use the unified sender
  too.
- **Brevo setup guide on the Email Providers admin page** explains
  the two key types (REST API key vs SMTP key + SMTP login) and
  where to find each in the Brevo admin UI.

### Changed

- **Legacy admin SMTP page deprecated.** `PUT
  /api/v1/admin/integrations/smtp` and `POST
  /api/v1/admin/integrations/smtp/test` returned HTTP 410 Gone with
  a `Location` header for one release. Configuration is exclusively
  through `/api/v2/admin/email-providers`. **Phase 9 has now removed
  the 410 endpoints entirely** following telemetry-confirmed zero
  callers across one full release window.
- **`send_org_email` shim retired.** The `send_org_email` /
  `get_email_client` / `load_smtp_config_from_db` / `SmtpConfig` /
  `EmailClient` exports in `app/integrations/brevo.py` were retained
  as deprecated shims through one release window so existing tests
  kept passing during the Phase 2 cutover. Phase 9 now deletes them
  entirely (file kept as an empty deprecation stub). Anything still
  importing these symbols from `app.integrations.brevo` will fail
  loudly rather than silently dispatch through a stale path.
- **Notification retry constants removed.** `RETRY_DELAYS`,
  `MAX_RETRIES`, and `_get_retry_delay` are gone from
  `app/tasks/notifications.py` — they were dead code post-Phase 2
  (provider failover handles transient failures by trying the next
  provider rather than retrying the same provider after a delay).
  The DB-backed retry path in `app/tasks/scheduled.py`, which is a
  separate machine, is unchanged and still live.
- **Activate audit-log action renamed** from `set_as_only_active` to
  `email_provider_activated` to reflect the multi-active reality.

### Migrated

- **Legacy `integration_configs[smtp]` row migrated automatically**
  into the matching `email_providers` row via alembic `0198`. The
  migration sets `is_active=true`, `priority=1`, `credentials_set=true`,
  re-encrypts credentials under the same master key, and acquires
  `pg_advisory_lock(hashtext('email_provider_rotate'))` to serialise
  with `app/cli/rotate_keys.py`. **No-clobber rule:** rows that an
  admin has already configured through the new UI are preserved
  untouched. The legacy `is_verified` flag does NOT carry over —
  see the post-deploy advisory below.

### Operational

- **Post-deploy advisory (one-shot in-app notification to global
  admins):** "Your SMTP configuration has been migrated to the new
  Email Providers page. Please open Admin → Email Providers and
  click Test on each provider to confirm credentials carried across.
  The legacy `is_verified` flag is not carried across."
- See [`docs/RUNBOOKS/email-provider-unification.md`](docs/RUNBOOKS/email-provider-unification.md)
  for the Phase 8b maintenance-window prerequisites and per-phase
  rollback steps.

---

## [1.11.1] — 2026-05-26

### Fixed

- **Forgot Password emails now actually deliver.** The auth service
  generated and persisted the reset URL and emitted the audit log
  entry, but ``_send_password_reset_email`` was never implemented, so
  the message never left the app. Implemented using the same raw
  ``smtplib`` + ``EmailProvider`` priority loop already used by the
  lockout and invitation emails (open its own ``async_session_factory``
  when called outside a request, walk active providers in
  priority order, fall through on per-provider failure). The API
  response stays the generic "if your email is registered..." either
  way, so the contract is unchanged for callers.

### Security

- Closes a security gap where users locked out of their accounts could
  not actually recover access via the documented Forgot Password flow.

---

## [1.11.0] — 2026-05-26

### Added

- **QR partial-payment flow** — org users now see a small modal between
  the QR Payment button and the existing kiosk waiting popup that lets
  them pick Full (default) or Partial. Choosing Partial reveals an
  amount input pre-populated with `balance_due`; the typed amount is
  validated against the per-currency Stripe minimum ($0.50 NZD) and
  the invoice's outstanding balance, then sent to
  `POST /api/v1/payments/qr-session/existing` as the new optional
  `amount` field. Existing callers that omit `amount` get the
  pre-feature full-balance behaviour byte-for-byte. Implemented across
  `QrPaymentAmountModal`, `InvoiceList`, `InvoiceDetail`,
  `create_qr_session_for_existing_invoice`, and the public payment
  page (web + mobile).
- **`payment_tokens.amount_override` and `payment_tokens.last_pi_amount_cents`
  columns** — the per-token override carries the partial amount through
  to the public payment page and the surcharge recompute; the cached PI
  cents lets the reuse-branch decision skip a synchronous Stripe API
  call without sacrificing accuracy. Both are nullable so existing
  rows remain unaffected. Added in alembic revision `0193`.
- **`is_partial_payment` field on `PaymentPageResponse`** — `GET
  /api/v1/public/pay/{token}` now returns a boolean flag the public
  payment page consumes to display an informational banner ("You are
  paying a partial amount of $X. Please contact the business if you
  intended to pay the full balance.") and switch the payment-summary
  label from "Amount Due" to "Amount Due (Partial)". Defaults to
  `false` so older frontends ignore it cleanly.
- **Partial-payment-aware receipt emails** — when `email_invoice` fires
  after a partial payment is recorded (most recent Payment row exists,
  `balance_due > 0`, status in `partially_paid`/`overdue`), the
  hardcoded fallback subject becomes "Partial payment received for
  invoice {N} — ${X}" and the body is prefixed with "Payment
  received: $X.XX / Remaining balance: $Y.YY". Custom `invoice_send`
  templates pass through unchanged, preserving existing
  template-customisation semantics.
- **Audit log entries `payment.qr_session_created` and
  `payment.qr_session_superseded`** — fire on every new-PI path and
  whenever an old PaymentIntent is cancelled because the requested
  amount changed. Skipped on the reuse-branch path so duplicate audit
  entries are not emitted.
- **`expired` state on `QrPaymentWaitingPopup`** — when the polled
  status returns `expired` (e.g. the session was superseded by a
  newer payment attempt from another tab), the popup transitions to
  a "QR session superseded" state instead of polling forever.

### Changed

- **`create_payment_intent` accepts an `extra_metadata: dict[str, str]
  | None` parameter** — appended to the Stripe payload as
  `metadata[KEY]` form fields before the POST. Backwards-compatible:
  existing callers continue to work unchanged.

### Fixed

- **PI metadata now set at creation time** — `source: "kiosk_qr"`,
  `original_amount`, and `is_partial_payment` are written into
  `metadata` when the PaymentIntent is first created instead of
  waiting for the customer to reach `update-surcharge`. Closes a
  pre-existing detection-bug gap where `is_qr_payment` in the
  webhook handler was always `false` if the customer skipped
  payment-method selection. Applies to both new-invoice
  (`create_qr_payment_session`) and existing-invoice
  (`create_qr_session_for_existing_invoice`) paths.
- **Stale invoice PI fields cleared after the webhook records a
  payment** — `invoice.stripe_payment_intent_id`,
  `invoice.payment_page_url`, and the `stripe_client_secret` entry on
  `invoice.invoice_data_json` are reset on the success path. Without
  this, a second-partial QR click on the same invoice was entering
  the reuse-branch with a non-null PI ID that had already moved to a
  terminal state on Stripe, breaking the next surcharge update.
  Regression-fix discovered during the qr-partial-payment audit; the
  existing webhook handler is otherwise unchanged — partial payments
  record correctly via the existing `metadata.original_amount`
  plumbing.
- **Active payment_tokens deactivated in the webhook on payment
  completion** — closes a re-scan gap on the just-paid URL: the URL
  no longer stays active for its 72-hour TTL, so re-scans between
  payment-completion and the next partial-initiation now return a
  clean HTTP 404 ("Invalid payment link") instead of `is_payable=true`
  with a null `client_secret`.

### Compliance

- The 1.10.5 surcharge gross-up continues to apply to the partial
  amount, so the merchant nets exactly the typed partial. Stripe's
  per-currency minimum charge amounts are sourced from
  `STRIPE_MIN_BY_CURRENCY` so multi-currency invoicing (future work)
  needs only an entry in this dict — no code change.

### Tests

- 21 integration tests in `tests/test_qr_partial_payment_integration.py`
  including the highest-value `test_webhook_duplicate_event_for_partial_pi_idempotent`
  guarding against silent double-debits on Stripe at-least-once
  webhook delivery.
- 5 Hypothesis property tests in
  `tests/properties/test_qr_partial_properties.py` (cents round-trip,
  validation envelope inside/outside, webhook records exactly the
  partial within 1¢ regardless of surcharge configuration).
- 4 partial-receipt email tests in `tests/test_email_invoice_partial.py`.
- Updated frontend Vitest coverage for `QrPaymentAmountModal`,
  `QrPaymentWaitingPopup` (`expired` branch), `InvoiceList`,
  `InvoiceDetail`, the public payment page, and the mobile public
  payment screen.

### Migration

- Alembic revision `0193_payment_tokens_amount_override` — adds two
  nullable columns to `payment_tokens` (`amount_override NUMERIC(12,2)
  NULL` and `last_pi_amount_cents BIGINT NULL`). Idempotent
  (no backfill required), no table rewrite.

---

## [1.10.5] — 2026-05-26

### Fixed

- **Stripe surcharge undercollected on every payment** — the in-app
  Stripe payment page computed the surcharge as ``balance × p + fixed``
  and charged Stripe ``balance + surcharge``. Stripe then deducted its
  fee on the gross (which it computes as ``gross × p + fixed``), so
  the merchant absorbed a small shortfall on every transaction
  approximately equal to ``balance × p²``. For Afterpay (6%) on $240
  the merchant lost $0.88 per transaction; for card (2.9%) on $1000
  it was $0.84. The fix replaces the formula with the gross-up
  ``(balance × p + fixed) / (1 − p)`` so the gross charge fully
  covers Stripe's fee and the merchant nets exactly the invoice
  balance. Implemented in ``app/modules/payments/surcharge.py`` with
  matching client-side instant-display calculations in
  ``frontend/src/pages/public/InvoicePaymentPage.tsx`` and
  ``mobile/src/screens/auth/PublicPaymentScreen.tsx``. The frontend
  now also adopts the backend response's ``surcharge_amount`` as
  authoritative once available, eliminating any tiny float drift on
  the displayed value. Property tests in
  ``tests/properties/test_surcharge_properties.py`` were rewritten
  to assert the new formula and added a 200-example invariant
  verifying the merchant nets ≥ ``balance_due − $0.01`` after
  Stripe's fee on the gross charge for any combination of
  ``(balance, percentage, fixed)``. NZ Commerce Commission's
  May 2026 surcharge rules require surcharges to not exceed actual
  cost of acceptance — the gross-up is exactly cost recovery, no
  markup, so it remains compliant.

---

## [1.10.4] — 2026-05-26

### Fixed

- **Customer profile vehicle "Source" badge mislabelled CarJam as Manual** —
  the `LinkedVehicleResponse.source` field carries storage location
  (`'global'` vs `'org'`), but the customer profile UI rendered it as data
  origin, so every newly-promoted org-scoped vehicle (per the 1.10.3 isolation
  rollout) showed as "Manual" even when its data came from CarJam. Backend
  now also returns an explicit `origin` field (`'carjam'` / `'manual'`)
  derived from `org_vehicles.is_manual_entry` for org rows and always
  `'carjam'` for global rows. The customer profile badge uses the new field
  with a fallback to the old heuristic for backwards compatibility.
- **Invoice odometer edits silently dropped after first issue** — editing
  `vehicle_odometer` on an issued invoice (or duplicate-then-edit) updated
  the invoice row but did not propagate to `org_vehicles.odometer_last_recorded`
  or insert an `odometer_readings` history row. The vehicle profile and
  service-history aggregations stayed stale until a future invoice. The
  resolution gate in `update_invoice` now includes `vehicle_odometer`, and
  a write block mirroring `create_invoice` records the reading via the
  unified `record_odometer_reading` helper (with the manual-entry-only
  fallback to a direct write).
- **Kiosk existing-customer field updates emitted no audit row** — when a
  walk-in check-in updated `first_name` / `last_name` / `phone` / `email`
  on an existing customer (`existing_customer_id` payload branch), the
  edit landed silently with no `customer.updated` audit log entry, so the
  change was invisible on the merge/audit history. The kiosk service now
  captures per-field before/after values and writes a `customer.updated`
  row matching the standard customer update service shape, with
  `entity_type=customer`, `org_id`, `user_id`, and `ip_address`.

---

## [1.10.3] — 2026-05-25

### Fixed

- **Vehicle data isolation** — customer-driven vehicle fields (odometer,
  service-due date, WOF expiry, COF expiry, inspection type) are now
  strictly per-organisation. Previously every org's writes landed on the
  shared `global_vehicles` cache, so workshop A's odometer reading was
  immediately visible to workshop B as soon as B looked up the same rego.
  Customer-driven flows (invoice create/update, kiosk check-in, fleet portal
  odometer/service-due updates, customer-vehicle link creation) now lazily
  promote the rego for the calling org on first touch — copying the row
  into `org_vehicles` and migrating any existing `customer_vehicles` link
  to `org_vehicle_id`. Subsequent customer-driven writes target the per-org
  snapshot. CarJam refresh continues to write the spec cache on
  `global_vehicles`. Read paths fall back to `global_vehicles` until the
  org is promoted, so existing data and existing workflows continue to
  function unchanged.
- **Fleet portal odometer log raised AttributeError on every call** — the
  helper at `app/modules/fleet_portal/services/vehicle_service.py::log_odometer_reading`
  referenced a non-existent `OdometerReading.odometer_km` column. The
  actual column on the model is `reading_km`. Both the `select(func.max(...))`
  aggregation and the `OdometerReading(...)` constructor are now corrected.
  The helper also writes `source="manual"` so the inserted row satisfies
  the `ck_odometer_readings_source` CHECK constraint.
- **Invoice update silently dropped `vehicle_cof_expiry_date`** — the field
  was missing from `UpdateInvoiceRequest` in `app/modules/invoices/schemas.py`,
  and `update_invoice` had no COF write branch. The schema now accepts the
  field, the resolution gate includes it, and the COF write branch mirrors
  the existing WOF branch.
- **`PUT /api/v1/customers/{id}/vehicle-dates` silently dropped `cof_expiry`** —
  the endpoint only handled `service_due_date` and `wof_expiry`. Now also
  handles `cof_expiry`. Writes target `org_vehicles` (after lazy promotion)
  rather than `global_vehicles`.
- **Dashboard expiry-reminders widget queried a non-existent column** — the
  widget joined `org_vehicles ov ON ov.global_vehicle_id = gv.id`, but
  `org_vehicles.global_vehicle_id` is not a column on the model. The widget
  now reads from `org_vehicles` directly for promoted vehicles and from
  `global_vehicles` via `customer_vehicles` for un-promoted links. The
  customer-name lookup now accepts either link type.
- **Invoice display leaked cross-tenant `global_vehicles` Customer_Driven_Fields** —
  `get_invoice` and `view_shared_invoice` (the public portal-token endpoint)
  looked up `GlobalVehicle` by rego first. Inverted to prefer `OrgVehicle`
  scoped to the invoice's `org_id`, falling back to `GlobalVehicle` only
  when the org has no row for that rego.
- **Notification/reminder services dropped reminders for promoted vehicles** —
  three call sites in `notifications/service.py` and
  `reminder_queue_service.py` did inner joins against `global_vehicles`,
  silently excluding every link migrated to `org_vehicle_id`. Replaced with
  two-pass queries covering both link types. Dedup keys standardised on
  `customer_vehicles.id` so they survive the link migration.
- **Data export CSV mislabelled promoted vehicles as `manual`** —
  `data_io/service.py::export_vehicles_csv` hardcoded `"manual"` for every
  `org_vehicles` row, but promoted rows have `is_manual_entry=False` and
  were originally CarJam-sourced. The label is now
  `("manual" if v.is_manual_entry else "carjam")`.

### Security

- **Closed multi-tenant data-leakage defect** — customer-driven vehicle
  fields are now strictly isolated per organisation. One workshop's
  odometer / WOF / COF / service-due / inspection-type writes are no
  longer visible to other workshops via the shared `global_vehicles`
  CarJam cache. RLS policies on `org_vehicles` and `customer_vehicles`
  remain unchanged; the fix is a behavioural redirect that targets the
  org-scoped table on every customer-driven write.
- New audit-log actions: `vehicle.promote` (emitted on first promotion
  of a rego per org, with `trigger_site` carried in `after_value`) and
  `vehicle.manual_refresh` (emitted by the explicit "Refresh from CarJam"
  action). Concurrent promotions for the same `(org_id, rego)` converge
  on a single row via PostgreSQL advisory transaction lock
  (`pg_advisory_xact_lock(hashtext(org_id), hashtext(rego))`); no schema
  change required.

### Notes

- **One-time reminder duplication** — reminder dedup keys were migrated
  from a vehicle-id-based scheme to a link-id-based scheme so dedup
  survives the new vehicle isolation. As a one-time consequence,
  reminders that fall within the lookahead window (≤ 30 days for
  service-due, ≤ 14 days for WOF/COF) and were already sent before this
  release may be sent a second time on the next scheduler run.
  Subsequent runs dedup correctly.

---

## [1.10.2] — 2026-05-25

### Added

- **Send Payment Link from invoice list** — new `Send` dropdown entry on the
  invoice list/detail panel that emails the customer the on-domain payment
  page URL (the same token-based page used by QR Payment, backed by a
  Stripe PaymentIntent — not a Stripe-hosted Checkout Session). Visible
  only when Stripe is connected and the invoice is in
  `issued`/`partially_paid`/`overdue` with a balance due. Reuses the org's
  active `invoice_issued` notification template (with a Pay Now button by
  default; user-customised templates honoured automatically) and the
  existing email provider chain. New endpoint:
  `POST /api/v1/payments/invoice/{id}/send-payment-link`.
- **Edit issued invoices (limited correction edit)** — the Edit button now
  appears on `issued`/`partially_paid`/`overdue` invoices. Only safe
  metadata can change: notes, due date, branch, vehicle metadata, payment
  terms, T&Cs. Line items, totals, customer, currency, and discount stay
  locked to keep GST/Xero/payments consistent. Voided/paid/refunded stay
  uneditable — use a credit note. Backend silently drops any non-editable
  fields and writes an audit log entry.

### Fixed

- **Vehicle details missing on invoice when only rego was supplied** — when
  converting a job card to an invoice (or any flow where only
  `vehicle_rego` reaches the backend, e.g. mobile minimal create or
  kiosk-registered customer picked in the new-invoice form), the invoice
  now backfills make/model/year/odometer from the org's `OrgVehicle` (or
  `GlobalVehicle` as fallback) keyed by rego. The existing
  `_resolve_vehicle_type` and `vehicle_display` snapshot then pick up
  inspection_type/WOF/COF/service-due automatically, matching the New
  Invoice form's display rules.
- **Fleet portal admin/reminders/accounts pages returned 500** —
  `/api/v2/fleet-portal/admin/accounts?limit=200` and
  `/fleet/api/reminders?limit=200` failed Pydantic validation because the
  shared `PaginatedResponse.limit` was capped at `le=100`. Lifted to
  `le=200` to match the admin views' actual page size.
- **Payment History columns visually joined on invoice list panel** — the
  Amount and Method cells touched on narrow widths. Both columns are now
  left-aligned with consistent right-padding so the values stay clearly
  separated.

---

## [1.10.0] — 2026-05-22

### Added — B2B Fleet Portal

A separate, password-based portal at `/fleet/*` (or `fleet.<domain>`)
for business customers (fleet operators) to manage their vehicle
fleets, drivers, NZTA pre-trip checklists, WOF/COF reminders,
service-booking and quote requests, and view invoices read-only. Gated
by the new `b2b-fleet-management` module (depends on `vehicles`,
restricted to the `automotive-transport` trade family).

- **Database**: migration `0191_b2b_fleet_portal.py` (head `0191`).
  16 new tables — `portal_accounts`, 5 portal-security tables, 9
  fleet-domain tables, plus `portal_account_devices`. Adds
  `customer_vehicles.fleet_checklist_template_id` and
  `portal_sessions.portal_account_id` discriminator. RLS policies on
  every new table; org + fleet account scoping via two parallel
  `set_config()` GUCs.
- **Backend module** at `app/modules/fleet_portal/`:
  - 16 SQLAlchemy ORM models, 56 Pydantic schemas
  - 13 portal API endpoints (`/fleet/api/*`) — auth, vehicles, hours,
    odometer, dashboard, version
  - 4 admin endpoints (`/api/v2/fleet-portal/admin/*`) — invite,
    revoke, resend-invite, list fleet accounts
  - URL resolver supporting subdomain, path, and single-tenant fallback
  - Module-disable cascade tears down active portal sessions
  - Security headers extended to `/fleet/api/*` (Cache-Control: no-store,
    Permissions-Policy with camera enabled, microphone/geolocation off)
- **Frontend SPA** at `frontend/src/fleet-portal/`:
  - Standalone provider tree mounted at `/fleet/*` — never shares
    chrome with `OrgLayout`
  - Login, forgot-password, dashboard, vehicle list pages
  - Fleet portal axios client with cookie auth + double-submit CSRF
  - Type-safe endpoint wrappers with `?? []` / `?? 0` consumption
- **Property tests**: 138 tests covering Properties 1–10, 12, 13, 16,
  17, 18, 22, 23, 24, 25, 26, 27, 30, 31, 33; auth state machine
  (lockout, password rules, bcrypt), URL resolution, CSRF,
  per-role field allowlist, odometer monotonicity, expiry badge,
  reminder predicate, NZTA seed, photo evidence at completion,
  booking and quote state machines, pagination shape.
- **Module registry**: `b2b-fleet-management` registered with
  `display_name = 'B2B Fleet Management'`, `dependencies = ['vehicles']`,
  setup question for the Setup Guide.
- **App version bumped** to 1.10.0; `/fleet/api/version` endpoint
  exposes version + build sha for the frontend version-refresh hook.

### Notes

The full mobile-app fleet portal flow (Capacitor 8 upgrade, native
auth screens, push notifications) and the workshop-admin SPA pages
under `frontend/src/fleet-portal-admin/` continue in subsequent
releases. The backend, property tests, and standalone fleet portal
SPA shell shipped in this release are complete and operational.

---

## [1.9.0] — 2026-05-15

### Added

- Invoice settings enable/disable toggles (email signature, default notes, payment terms, T&C)
- Email signature append on invoice and quote emails
- Default notes pre-fill on new invoices
- Payment terms and T&C sections in invoice web preview
- Toggle-aware PDF rendering for payment terms and T&C
- Rich text T&C field in invoice form (HTML preserved)

---

## [1.8.0] — 2026-05-08

### Added

- **Service Package Builder** — bundled service items that combine labour with inventory components (parts, fluids, tyres). Includes live cost calculation, profit tracking, invoice integration with automatic inventory deduction, and property-based test coverage.
  - Database: `is_package` and `package_components` JSONB columns on `items_catalogue`
  - Backend: package CRUD, cost resolution from live stock prices, component search endpoints, duplication support
  - Frontend: PackageBuilder component with inventory type selectors, fluid cascading dropdowns, cost summary (admin-only), package preview with stock warnings
  - Invoice integration: automatic inventory deduction on issue, fluid usage recording, snapshot cost fallback for unavailable components
  - Access control: cost/profit data restricted to admin roles
  - Module gating: requires both `vehicles` and `inventory` modules enabled
  - 18 property-based tests (Hypothesis) covering cost calculation, persistence, role gating, and inventory deduction correctness
  - Integration tests covering full lifecycle, invoice deduction, quote safety, and access control

---

## [1.7.0] — 2026-05-01

### Added

- Kiosk vehicle check-in multi-step flow (rego → vehicle summary → customer details)
- COF (Certificate of Fitness) expiry support alongside WOF

---

## [1.6.0] — 2026-04-15

### Added

- Xero accounting integration with webhooks and auto-sync
- Branch management and stock transfers

---

## [1.5.0] — 2026-04-01

### Added

- HA replication between Pi primary and local standby nodes
- Claims and scheduling modules

---

## [1.4.0] — 2026-03-15

### Added

- Initial production deployment
- Multi-tenant invoicing, quoting, customer management
- Role-based access control with JWT + Firebase auth
- Stripe billing integration
