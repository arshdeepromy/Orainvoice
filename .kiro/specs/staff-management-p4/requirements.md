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
3. THE SYSTEM SHALL allow admin to configure pay-period cadence: `weekly | fortnightly | monthly` (Settings → People → Pay Periods).
4. A daily scheduled task `roll_pay_periods` ensures the next-N pay-periods exist for every org with `payroll` module enabled.

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
   - `payslip_allowances (id, payslip_id, allowance_type_id, label, amount, taxable)`
   - `payslip_deductions (id, payslip_id, kind, label, amount)` where `kind` enum: `paye | acc_levy | kiwisaver_employee | kiwisaver_employer | student_loan | child_support | voluntary`. (KiwiSaver employer kind tracked but NOT subtracted from gross — informational on the payslip.)
   - `payslip_reimbursements (id, payslip_id, label, amount)` (tax-free, separate from wages)
   - `payslip_leave_lines (id, payslip_id, leave_type_id, hours, rate, amount, balance_after)` (Holidays Act s130A: "leave taken in this period" + "remaining balance").
3. RLS + tenant_isolation policy on all four.
4. THE SYSTEM SHALL refuse UPDATE/DELETE on `payslips WHERE status='finalised'` at the application level (raise 409 conflict). Only voiding (writing a new compensating payslip) is allowed.

### R4. Generate-Payslip Flow

**User story:** As an org admin at end-of-pay-period, I generate one payslip per active staff, review them, finalise, and optionally bulk-email.

**Acceptance criteria:**

1. THE SYSTEM SHALL expose `POST /api/v2/pay-periods/:id/payslips/generate` — for the pay period, creates one DRAFT payslip per active staff. Source data:
   - Approved `timesheet_approvals` rows in the period → ordinary, overtime, public-holiday hours.
   - Approved `leave_requests` overlapping the period → `payslip_leave_lines` at appropriate rate (relevant daily pay for OWD-PH leave; ordinary for annual; etc.).
   - Casual employees → automatic 8% holiday-pay-as-you-go line on gross earnings (R5).
   - Allowances assigned to the staff (manually entered on draft).
   - Reimbursements (manually entered on draft).
   - Deductions: PAYE + ACC entered manually; KiwiSaver auto-computed from `staff.kiwisaver_*_rate × gross`; student_loan visible only when `staff.student_loan=true`.
2. THE SYSTEM SHALL compute `gross_pay = sum(hours × rate per band) + sum(taxable allowances) + casual 8% line if applicable`.
3. THE SYSTEM SHALL compute `net_pay = gross_pay - sum(deductions where kind != 'kiwisaver_employer') + sum(reimbursements)`.
4. THE SYSTEM SHALL allow admin to edit a draft payslip, save, regenerate.
5. WHEN admin clicks "Finalise" THE SYSTEM SHALL:
   - Render PDF (R7).
   - Set `status='finalised'`, `finalised_at=now()`.
   - Lock further edits.
   - Optionally email if "send email" checkbox ticked.

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
   - Pay period start/end + pay date.
   - Ordinary / overtime / public-holiday hours and rates.
   - Each allowance line.
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

### R8. Email Payslip

**Acceptance criteria:**

1. THE SYSTEM SHALL expose `POST /api/v2/payslips/:id/email` — sends payslip PDF as email attachment via `send_email` with `dlq_task_name='payslip_email'`.
2. Refuses 422 when `staff.email IS NULL` or when payslip is still draft.
3. Updates `payslips.emailed_at`.
4. Audit `payslip.emailed`.

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
2. THE SYSTEM SHALL:
   - Set `staff_members.employment_end_date = end_date` and `is_active=false`.
   - Compute annual-leave payout = remaining annual `accrued - used` × **greater of ordinary weekly pay or 52-week average weekly earnings**.
     - "Ordinary weekly" = `standard_hours_per_week × hourly_rate`.
     - "52-week avg" = `gross_paid_in_last_52_weeks / 52`.
   - Convert unused `public_holiday_alt` balance to days × relevant daily pay (using the ADP snapshot from Phase 2, refreshed from real payslip data in this phase).
   - For casuals: any remaining 8% obligation = `(YTD gross × 0.08) - (sum of 8% lines paid YTD)`.
   - Generate a final payslip in the next open pay_period with the termination payout breakdown lines.
   - Write `audit_logs` action='staff.terminated' with full breakdown JSON.
3. THE SYSTEM SHALL flip leave balances to zero (write compensating leave_ledger rows reason='termination_payout').

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
- `staff.terminated`
- `allowance_type.created`, `allowance_type.updated`, `allowance_type.deactivated`

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
