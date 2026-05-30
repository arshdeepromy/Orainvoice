# Staff Management — Phase 4: Payslips + Allowances + Termination Payouts

## Overview

Phase 4 generates Wages-Protection-Act + Holidays-Act-s130A-compliant payslips. Includes typed allowances and reimbursements, KiwiSaver auto-calc, casual 8% holiday-pay-as-you-go line, and the Holidays Act s27 termination payout (greater of ordinary weekly pay vs 52-week average).

**Source:** `docs/future/staff-management-system.md` §6 Phase 4, §4.6, §4.7, §7A.

**Status:** Draft, depends on Phases 1, 2, 3.

## Steering compliance

- WeasyPrint PDF rendering wrapped in `await asyncio.to_thread(...)` per PERFORMANCE_AUDIT B-H1 (already applied across the codebase post-quick-win #2).
- Bulk pay-run dispatched via existing background-task path, not request worker.
- IRD + bank account ciphertext only decrypted inside the payslip-rendering service path; never returned in any other API response.
- All PDFs stored in `app/modules/uploads/` infrastructure.
- Payslip rows are immutable post-finalisation (status='finalised'); UPDATE/DELETE refused at app level.
- Allowances + deductions + reimbursements typed (separate tables), not free-form JSONB.
- Email sender + DLQ wired for payslip emails per existing `dlq_task_name` pattern.

## Requirements

### R1. `pay_periods` Table

**Acceptance criteria:**

1. THE SYSTEM SHALL create `pay_periods`: `id, org_id, start_date, end_date, pay_date, status text default 'open' CHECK IN ('open','finalised','paid'), created_at, finalised_at, paid_at. Unique on (org_id, start_date)`.
2. RLS + tenant_isolation policy.
3. THE SYSTEM SHALL allow admin to configure pay-period cadence: `weekly | fortnightly | monthly` (Settings → People → Pay Periods). Stored on `organisations.pay_period_cadence` (added in this phase per design §3.1). Anchor day stored on `organisations.pay_period_anchor_day` (default 1).
4. A daily scheduled task `roll_pay_periods` ensures the next-4 pay-periods exist for every org with `payroll` module enabled.

5. **Pay-period rolling algorithm (G5).** `roll_pay_periods` computes the next period's `(start_date, end_date, pay_date)` as follows:
   - **Anchor:** `latest_end = MAX(pay_periods.end_date WHERE org_id=:org)` — `NULL` for orgs with no history.
   - For `cadence='weekly'`:
     - If `latest_end IS NULL`: `start = today's week's day_of_week == anchor_day` (e.g., anchor=1 → Monday this week, anchor=7 → Sunday this week).
     - Else: `start = latest_end + 1 day`.
     - `end = start + 6 days`.
   - For `cadence='fortnightly'`:
     - If `latest_end IS NULL`: same anchor logic as weekly.
     - Else: `start = latest_end + 1 day`.
     - `end = start + 13 days`.
   - For `cadence='monthly'`:
     - `start = anchor_day` of the next month (e.g., anchor=1 → 1st of next month; anchor=25 → 25th of next month).
     - `end = day before next anchor` (handles 28/29/30/31 month-end variation by clamping).
   - `pay_date = end + organisations.pay_date_offset_days` (new column, default 3). Falls forward to next business day if pay_date lands on a weekend.
   - Idempotency: a period with the same `(org_id, start_date)` is silently skipped (relies on the existing UNIQUE constraint).

6. **Cadence change behaviour (G14).** Changing `organisations.pay_period_cadence` does NOT retroactively modify existing pay_periods. The next `roll_pay_periods` tick simply resumes from `latest_end + 1` with the new cadence rules. Existing finalised/paid periods stay as-is. An audit row `org.pay_period_cadence_changed` is written with `{ from, to, effective_from }` so payroll history remains explainable.

### R1a. Pay-Period Reopen (G21)

**User story:** As an org admin, I need to reopen a finalised pay period when a payslip needs correction (e.g., I entered the wrong PAYE figure), so I can void + regenerate without dead-ending.

**Acceptance criteria:**

1. THE SYSTEM SHALL expose `POST /api/v2/pay-periods/:id/reopen` (org_admin only).
2. THE SYSTEM SHALL refuse with HTTP 409 `{"detail": "period_already_paid"}` when `pay_periods.status='paid'` — money's already out the door, voiding-with-regen is the only path.
3. THE SYSTEM SHALL refuse with HTTP 422 when the period is already `'open'`.
4. WHEN status is `'finalised'` THE SYSTEM SHALL:
   - Set `pay_periods.status='open'`, `finalised_at=NULL`.
   - Leave existing finalised payslips intact — they remain immutable per R3.4 (the reopen only allows NEW drafts or compensating-void flows to proceed in the same period).
   - Write audit row `pay_period.reopened` with `{ reopened_by, reason, originally_finalised_at }`.
5. The Settings → People → Pay Periods page surfaces a "Reopen" button next to finalised periods with a confirmation modal asking for a `reason` text.

### R2. Allowance Types Configuration

**Acceptance criteria:**

1. THE SYSTEM SHALL create `allowance_types`: `id, org_id, code (UNIQUE per org), name, taxable boolean, default_amount numeric(10,2), unit text CHECK IN ('shift','period','km'), active boolean, display_order int, created_at, updated_at`.
2. RLS + tenant_isolation policy.
3. Migration seeds defaults for every existing org: `meal_allowance`, `tool_allowance`, `vehicle_allowance`, `on_call_allowance`, `travel_per_km`, `uniform_laundering`. These are not statutory — admin can edit/deactivate.
4. THE SYSTEM SHALL render Settings → People → Allowance Types (CRUD).

### R3. `payslips` Table + Lines

**Acceptance criteria:**

1. THE SYSTEM SHALL create `payslips`:
   ```sql
   id, org_id, staff_id, pay_period_id, status text default 'draft' CHECK IN ('draft','finalised','voided'),
   ordinary_hours numeric(8,2) NOT NULL DEFAULT 0,
   overtime_hours numeric(8,2) NOT NULL DEFAULT 0,
   public_holiday_hours numeric(8,2) NOT NULL DEFAULT 0,
   ordinary_rate numeric(10,2),
   overtime_rate numeric(10,2),
   public_holiday_rate numeric(10,2),       -- G2: typically ordinary_rate × 1.5 (Holidays Act s50)
   gross_pay numeric(12,2) NOT NULL,
   gross_ytd numeric(12,2) NOT NULL DEFAULT 0,
   net_pay numeric(12,2) NOT NULL,
   pdf_upload_id uuid,
   emailed_at timestamptz,
   finalised_at timestamptz,
   notes text,
   created_at, updated_at
   ```
2. THE SYSTEM SHALL create normalised lines tables:
   - `payslip_allowances (id, payslip_id, allowance_type_id, label, quantity numeric(10,2) NOT NULL DEFAULT 1, unit text NOT NULL DEFAULT 'period', amount numeric(12,2), taxable boolean)` — G18: `quantity` × the unit price renders correctly on the PDF; for `unit='km'`, quantity is km claimed; for `unit='shift'`, quantity is shifts worked; for `unit='period'`, quantity is always 1.
   - `payslip_deductions (id, payslip_id, kind, label, amount)` where `kind` enum: `paye | acc_levy | kiwisaver_employee | kiwisaver_employer | student_loan | child_support | voluntary`. (KiwiSaver employer kind tracked but NOT subtracted from gross — informational on the payslip.)
   - `payslip_reimbursements (id, payslip_id, label, amount)` (tax-free, separate from wages)
   - `payslip_leave_lines (id, payslip_id, leave_type_id, hours, rate, amount, balance_after)` (Holidays Act s130A: "leave taken in this period" + "remaining balance").
3. RLS + tenant_isolation policy on all four.
4. THE SYSTEM SHALL refuse UPDATE/DELETE on `payslips WHERE status='finalised'` at the application level (raise 409 conflict). Only voiding (writing a new compensating payslip) is allowed. Reopening the parent `pay_period` (R1a / G21) does NOT unlock finalised payslips inside — it only allows new drafts alongside.

5. **Recurring per-staff allowances (G4).** THE SYSTEM SHALL create `staff_recurring_allowances`:
   ```sql
   id uuid PK, org_id, staff_id REFERENCES staff_members(id) ON DELETE CASCADE,
   allowance_type_id uuid NOT NULL REFERENCES allowance_types(id) ON DELETE RESTRICT,
   amount numeric(10,2),     -- override for this staff; NULL = use allowance_types.default_amount
   quantity numeric(10,2),   -- recurring quantity override (NULL = derive from unit per G18)
   active boolean NOT NULL DEFAULT true,
   notes text,
   created_at, updated_at,
   UNIQUE (staff_id, allowance_type_id)
   ```
   - RLS + tenant_isolation.
   - WHEN `generate_for_period` creates a draft payslip THE SYSTEM SHALL look up `staff_recurring_allowances WHERE staff_id=:s AND active=true` and auto-attach a `payslip_allowances` row per match, using the override `amount`/`quantity` when set, else falling back to `allowance_types.default_amount` × unit-derived quantity (per G18 semantics in R4.6).
   - WHEN admin edits a draft, they can remove or override the auto-attached lines for that specific payslip — the recurring rule itself isn't mutated.
   - UI lives on the Staff Detail Overview tab in a collapsible "Recurring allowances" section (Phase 1's expanded record is the host; Phase 4 ships the form). Add as a new task in Workstream D.

### R4. Generate-Payslip Flow

**User story:** As an org admin at end-of-pay-period, I generate one payslip per active staff, review them, finalise, and optionally bulk-email.

**Acceptance criteria:**

1. THE SYSTEM SHALL expose `POST /api/v2/pay-periods/:id/payslips/generate` — for the pay period, creates one DRAFT payslip per active staff. Source data:
   - Approved `timesheet_approvals` rows in the period → ordinary, overtime, public-holiday hours.
   - Approved `leave_requests` overlapping the period → `payslip_leave_lines` at appropriate rate (relevant daily pay for OWD-PH leave; ordinary for annual; etc.).
   - Casual employees → automatic 8% holiday-pay-as-you-go line on gross earnings (R5).
   - **Recurring allowances (G4)** — `staff_recurring_allowances` rows auto-attached per R3.5; admin can override per draft.
   - Allowances manually added on draft (in addition to recurring).
   - Reimbursements (manually entered on draft).
   - Deductions: PAYE + ACC entered manually; KiwiSaver auto-computed from `staff.kiwisaver_*_rate × gross`; student_loan visible only when `staff.student_loan=true`.
2. THE SYSTEM SHALL compute `gross_pay = (ordinary_hours × ordinary_rate) + (overtime_hours × overtime_rate) + (public_holiday_hours × public_holiday_rate) + sum(taxable allowances) + casual 8% line if applicable`. (G2: explicit public_holiday band.)
3. THE SYSTEM SHALL compute `net_pay = gross_pay - sum(deductions where kind != 'kiwisaver_employer') + sum(reimbursements)`.
4. THE SYSTEM SHALL allow admin to edit a draft payslip, save, regenerate.
5. WHEN admin clicks "Finalise" THE SYSTEM SHALL:
   - Render PDF (R7).
   - Set `status='finalised'`, `finalised_at=now()`.
   - Lock further edits.
   - Optionally email if "send email" checkbox ticked.

6. **Allowance `unit` semantics (G18) — auto-quantity derivation:**
   - `unit='period'` → `quantity = 1`; `amount = default_amount` (or staff-recurring override).
   - `unit='shift'` → `quantity = count_of_approved_shifts(staff_id, pay_period)` (drawn from `timesheet_approvals`-linked `time_clock_entries` joined to `schedule_entries` where `entry_type IN ('job','booking','other')`); `amount = quantity × default_amount`.
   - `unit='km'` → `quantity = 0` by default (admin enters km claimed on the draft); `amount = quantity × default_amount` recomputed on every save.
   - The PDF row renders as `{label}: {quantity} {unit} × ${unit_price} = ${amount}` for shift/km units, and just `{label}: ${amount}` for period.

### R4a. Public-Holiday Rate Default (G2)

**Acceptance criteria:**

1. WHEN `compute_payslip` runs THE SYSTEM SHALL default `public_holiday_rate = ordinary_rate × Decimal('1.5')` per Holidays Act s50 (time-and-a-half).
2. THE SYSTEM SHALL allow admin to override `public_holiday_rate` on a draft (for the rare orgs paying double-time or otherwise different multipliers).
3. THE SYSTEM SHALL store the actual rate that paid out on the `payslips` row (not just the multiplier), so PDF + future audits show the exact amount.

### R5. Casual 8% Holiday-Pay Line

**Acceptance criteria:**

1. WHEN generating a payslip for a casual employee THE SYSTEM SHALL automatically attach an allowance line with `code='casual_8pct_holiday'` (auto-created if missing), `amount = gross_taxable_earnings × 0.08`, `taxable=true`. Gross figure for the calc is wages-only (excluding the 8% line itself, to avoid recursion).
2. THE SYSTEM SHALL NOT accrue annual leave for casuals per Phase 2 rules.

### R6. KiwiSaver Auto-Calculation

**Acceptance criteria:**

1. WHEN `staff.kiwisaver_enrolled=true` THE SYSTEM SHALL auto-add two deduction lines on draft generation:
   - `kiwisaver_employee` = `gross × employee_rate / 100`
   - `kiwisaver_employer` = `gross × employer_rate / 100`
2. The employer line is informational on the payslip and is NOT subtracted from gross when computing net_pay.
3. THE SYSTEM SHALL recalculate these on every save when gross changes.

### R7. PDF Rendering (Wages Protection Act + Holidays Act s130A)

**User story:** Every payslip PDF must include every Wages Protection Act + s130A field.

**Acceptance criteria:**

1. THE SYSTEM SHALL render the payslip PDF with WeasyPrint via `await asyncio.to_thread(lambda: HTML(string=html).write_pdf())`.
2. PDF content must include:
   - Org logo, name, address (from `org_settings`).
   - Employee name, tax_code, IRD number masked (`***123`).
   - **Masked bank account (G1)** — `**-****-****NN-**` last 2 digits visible — for the employee to verify the payment destination. Decryption happens only inside `pdf.render_pdf` per existing PII-safety policy.
   - Pay period start/end + pay date.
   - Ordinary / overtime / public-holiday hours and rates (incl. the computed `public_holiday_rate` per R4a / G2).
   - Each allowance line with quantity + unit + amount per R4.6 (G18).
   - Gross pay.
   - Each deduction line and amount (PAYE, ACC, KiwiSaver employee, KiwiSaver employer separately, student loan, child support, voluntary).
   - Each reimbursement line.
   - Net pay.
   - **Leave taken in this period** (per leave type, with hours).
   - **Remaining balances** for every accruing leave type (s130A — most-missed requirement).
   - Year-to-date totals: gross, PAYE, KiwiSaver employee, KiwiSaver employer.
   - Anniversary date for annual leave.
3. PDF stored via `app/modules/uploads/` infrastructure; `pdf_upload_id` populated on the payslip row.
4. PDF immutable post-finalisation.

5. **Print-CSS basics (G20).** The accompanying stylesheet `app/templates/payslips/payslip.css` MUST specify:
   - Page size A4 portrait, `@page` margins 15mm top/bottom, 12mm left/right.
   - Body font 10pt Inter or system-default sans-serif fallback; section headers 12pt bold; org name in header 14pt.
   - `page-break-inside: avoid` on every line-item table (allowances, deductions, leave_lines) so a section never splits across a page boundary.
   - Header (org logo + name) and footer (legal disclaimer + page X of N) printed via `@page` rules so they repeat on every page when the payslip spans more than one.
   - Tabular numerics right-aligned; currency formatted with NZD locale (e.g. `$1,234.50`).
   - High-contrast black-on-white default; no background images that increase printer ink usage.

### R8. Email Payslip

**Acceptance criteria:**

1. THE SYSTEM SHALL expose `POST /api/v2/payslips/:id/email` — sends payslip PDF as email attachment via `send_email` with `dlq_task_name='payslip_email'`.
2. Refuses 422 when `staff.email IS NULL` or when payslip is still draft.
3. Updates `payslips.emailed_at`.
4. Audit `payslip.emailed`.

### R8a. Staff Self-Service Payslip Access (G9)

**User story:** As a staff member with a linked user account, I want to see my own past payslips and download the PDFs without admin involvement (matches the `Staff member (linked user): own data only ... Payslips (read own)` rule in the master plan §8.1).

**Acceptance criteria:**

1. THE SYSTEM SHALL expose three new endpoints (all behind existing `RequireAuth`, NO admin gate):
   - `GET /api/v2/staff/me/payslips` — list own finalised payslips, returns `{ items: [...], total: N }`. Drafts and voided are NOT visible to the staff (only their admin sees those).
   - `GET /api/v2/staff/me/payslips/:id` — own detail with full breakdown (allowance lines, deductions, leave lines, YTD).
   - `GET /api/v2/staff/me/payslips/:id/pdf` — own PDF download.
2. Server-side ownership check at every endpoint: resolve `staff_id` from `current_user.id` via the existing `users.staff_id` (or equivalent) link; refuse with HTTP 404 when the requested `:id` doesn't belong to the resolved staff (404 not 403 — don't leak existence).
3. THE SYSTEM SHALL gate the endpoints behind `payroll` module enablement; when disabled, return 404 `not_enabled` (same pattern as the rest of P4).
4. **Frontend (web):** add `/staff/me/payslips` route lazy-loaded in `App.tsx`, rendering a list + drawer detail.
5. **Frontend (mobile):** add `mobile/src/screens/payslips/PayslipsScreen.tsx`, lazy-loaded in `StackRoutes.tsx`, behind `ModuleGate moduleSlug="payroll"`. Renders a list of past payslips with download/share buttons (Capacitor share sheet for native).
6. The IRD + bank decryption rule still holds: PDF rendering is the only path that touches encrypted fields, even on the self-service surface.

### R9. Bulk Pay Run

**Acceptance criteria:**

1. THE SYSTEM SHALL expose `POST /api/v2/pay-periods/:id/finalise` — finalises every draft payslip in the period in one call.
2. Optional `email_all=true` query param triggers bulk email after finalise.
3. Each payslip's PDF render dispatched via background-task path (not request worker), to avoid blocking the request.
4. Each per-staff finalise wrapped in `db.begin_nested()` SAVEPOINT so one failure doesn't abort the batch.
5. Returns `{ finalised: N, failed: [ {staff_id, reason} ], emailed: M }`.

### R10. Termination Workflow + s27 Final Payslip

**User story:** As an org admin, when staff leaves I want to "End employment", which closes leave balances correctly per Holidays Act s27 and produces a final payslip with the payout breakdown.

**Acceptance criteria:**

1. THE SYSTEM SHALL expose `POST /api/v2/staff/:id/terminate` accepting `{ end_date, reason, final_pay_options }`.
2. THE SYSTEM SHALL execute the following sequence in a single DB transaction:

   **Step 1 — Reconcile future-dated approved leave (G16).** Find every `leave_requests WHERE staff_id=:id AND status='approved' AND start_date > :end_date`. For each:
   - Set `status='cancelled'`, `decided_by=current_user`, `decided_at=now()`, `decision_notes='auto-cancelled at termination'`.
   - Write a compensating `leave_ledger` row with `reason='request_cancelled_after_approval'`, `delta_hours = +request.hours_requested` (restores hours to the balance so the s27 payout includes them).
   - Mark the corresponding future `schedule_entries` rows (`entry_type='leave'` within the cancelled range) as cancelled or delete them, depending on whichever the scheduling_v2 module supports.
   - Write audit row `staff.termination_cancelled_future_leave` with `{ cancelled_request_ids: [...], total_hours_restored: N }`.

   **Step 2 — Compute payouts** (now operating on the corrected balances):
   - Annual-leave payout = remaining annual `accrued - used` × **greater of ordinary weekly pay or 52-week average weekly earnings**:
     - "Ordinary weekly" = `standard_hours_per_week × hourly_rate`.
     - "52-week avg" = `gross_paid_in_last_52_weeks / 52` (sourced from finalised `payslips.gross_pay` per R13).
   - Unused `public_holiday_alt` balance → days × relevant daily pay (using ADP snapshot from Phase 2 + R13 refresh).
   - For casuals: remaining 8% obligation = `(YTD gross × 0.08) - (sum of 8% lines paid YTD)`.

   **Step 3 — Pick the final-payslip pay period (G25):**
   - Find the pay_period whose `[start_date, end_date]` interval contains `:end_date`. If found and status is `'open'` → use it.
   - If found but status is `'finalised'` → invoke the R1a reopen flow (audit row `pay_period.reopened_for_termination`) and use it.
   - If found but status is `'paid'` → refuse with HTTP 409 `{"detail": "pay_period_already_paid", "pay_period_id": ...}` — admin must wait for next period or issue a manual adjustment.
   - If no pay_period covers `:end_date` (G6 — `roll_pay_periods` hasn't created it yet) → synchronously invoke `roll_pay_periods` for the org, then re-check. If still no match (e.g., termination dated weeks in advance), create periods iteratively until one covers `:end_date`. Audit row `pay_period.rolled_for_termination` records the auto-creation.

   **Step 4 — Generate the final payslip in the chosen period** with the s27 + alt-day + casual-8% breakdown lines and a `notes` field marking it as a termination payslip.

   **Step 5 — Update staff:**
   - Set `staff_members.employment_end_date = :end_date`, `is_active=false`.
   - Flip leave balances for accruing types to zero (write `leave_ledger` rows reason='termination_payout' with `delta_hours = -(remaining_accrued - used)`).
   - Write `audit_logs` action='staff.terminated' with full breakdown JSON.
3. WHEN any step fails, the entire transaction rolls back; the staff stays active, balances unchanged.

### R11. Pay-rate Review Reminder

**Acceptance criteria:**

1. THE SYSTEM SHALL surface a banner on Staff List "5 staff are due a pay review this month" (per Phase 1 R6 already implements the column; Phase 4 ensures the trigger fires when `staff_pay_rates.last_change > 12 months`).

### R12. Wage Variance Report

**Acceptance criteria:**

1. THE SYSTEM SHALL add `/reports/wages-variance?from=&to=` showing per-staff this-period vs last-period comparison with delta + % change. Surfaces unexplained jumps (e.g. someone got 20h extra without comment).

### R13. ADP Snapshot Data Refresh

**Acceptance criteria:**

1. THE SYSTEM SHALL update the ADP snapshot daily task (Phase 2 placeholder calc) to use real payslip data: `sum(gross) over last 52 weeks of payslips / count(distinct days_worked)`.
2. Falls back to Phase 2 calc when no payslips exist yet.

### R14. Audit Logging

THE SYSTEM SHALL call `write_audit_log(...)` (writing to the `audit_log` table) for:

- `payslip.generated`
- `payslip.updated` (draft only)
- `payslip.finalised`
- `payslip.emailed`
- `payslip.voided`
- `pay_period.created`
- `pay_period.finalised`
- `pay_period.paid`
- `pay_period.reopened` (G21)
- `pay_period.reopened_for_termination` (G25)
- `pay_period.rolled_for_termination` (G6)
- `staff.terminated`
- `staff.termination_cancelled_future_leave` (G16)
- `staff_recurring_allowance.added` / `staff_recurring_allowance.updated` / `staff_recurring_allowance.deactivated` (G4)
- `allowance_type.created`, `allowance_type.updated`, `allowance_type.deactivated`
- `org.pay_period_cadence_changed` (G14)

**Audit redaction rule (G12).** Payslip-related audit rows MUST NOT contain raw monetary amounts or decrypted PII in `before_value` / `after_value`. The default `after_value` for payslip events is `{ payslip_id, staff_id, pay_period_id, status, finalised_at, emailed_at }` only. Specifically:

- `payslip.generated` → `{ payslip_id, staff_id, pay_period_id, source: 'auto' | 'manual' }`
- `payslip.finalised` → `{ payslip_id, staff_id, pay_period_id, finalised_at, pdf_upload_id }`
- `payslip.emailed` → `{ payslip_id, staff_id, recipient_email_domain_only }` (e.g. `@example.com`, not the full address)
- `payslip.voided` → `{ payslip_id, staff_id, reason }`
- `staff.terminated` → `{ staff_id, end_date, payout_summary: { annual_hours, alt_days, casual_8pct_remaining } }` — counts only, no dollar amounts.

Implementation: the `write_audit_log` callsites in `app/modules/payslips/` build these redacted dicts explicitly, not by serialising the full row.

### R15. E2E Test Script

**Acceptance criteria:**

1. THE SYSTEM SHALL ship `scripts/test_staff_payslip_e2e.py`.
2. Flow per source plan: set deductions; add allowance + reimbursement; generate payslip from approved week; verify all Wages Protection + s130A fields in JSON response; render PDF and check it contains every required field; email payslip; terminate employment; verify final payslip with 52-week-avg payout; verify casual 8% line; cleanup.

### R16. Versioning

THE SYSTEM SHALL bump 1.16.0 → 1.17.0.

## Non-Goals

- PAYE/ACC tax calculation (admin enters; we don't calculate).
- IRD myIR filing automation.
- Bank-file CSV export (Phase 5).
- Performance reviews, recruitment, LMS.

## Open Questions

- **STAFF-004:** Bank-file format priority — defers to Phase 5; Phase 4 does NOT block on bank-file decisions.
