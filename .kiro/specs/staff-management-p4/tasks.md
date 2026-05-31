# Staff Management Phase 4 — Tasks

## Execution policy

This phase auto-advances from Phase 3. The full execution policy is documented at the top of `.kiro/specs/staff-management-p1/tasks.md` and applies verbatim here. Quick recap:

- **Scoped testing only** — run only the tests for the files each task touches; never the full suite.
- **No interactive prompts** — use `--yes`/`-y`/`--non-interactive` flags everywhere a tool would otherwise prompt.
- **Never stop for confirmation** — only stop on a verify failure or an explicit unresolved blocking open question.
- **No watchers** — `vitest run`, `pytest`, `tsc --noEmit`; never `--watch` modes or dev servers.
- **Auto-advance** — when this phase's pre-merge gate is fully ticked and BOTH `gap-analysis.md` + `internal-alignment-gap-analysis.md` are empty (or deferrals documented), open `.kiro/specs/staff-management-p5/tasks.md` and resume at A1 without asking.
- **Failure handling** — log the failure detail to this phase's `gap-analysis.md`, mark the task `[~]`, and continue with the next non-dependent task. Stop only after 3 consecutive failures.

## Workstream A — Migrations

- [x] **A1. `0209_payslip_schema.py`** — pay_periods, allowance_types (+ defaults seed), payslips, payslip_allowances, payslip_deductions, payslip_reimbursements, payslip_leave_lines. RLS + tenant_isolation on all. CHECK constraints. Idempotent.
  - Add `organisations.pay_period_cadence`, `pay_period_anchor_day`, **and `pay_date_offset_days int default 3` (G5)**.
  - **Add `payslips.public_holiday_rate numeric(10,2)` (G2)** — defaulted to `ordinary_rate × 1.5` by `compute_payslip`; admin overridable.
  - **Rename `payslips.pdf_upload_id uuid` → `payslips.pdf_file_key text` (N3)** — path-style key matching existing attachment conventions; NULL until finalised.
  - **`payslips` includes `UNIQUE (staff_id, pay_period_id)` (P4-N28)** — supports `generate_for_period` idempotency; prevents duplicate drafts per staff per period under race conditions or admin clicking "Generate drafts" twice.
  - **`payslips.gross_pay` and `payslips.net_pay` are `NOT NULL DEFAULT 0` (P4-N29)** — DEFAULT 0 lets `INSERT` create draft rows before the math has been run (compute_payslip writes the totals back).
  - **Add `payslip_allowances.quantity numeric(10,2) NOT NULL DEFAULT 1` and `unit text NOT NULL DEFAULT 'period' CHECK IN ('shift','period','km')` (G18)** — quantity is shifts/km/1; unit is COPIED from `allowance_types.unit` at attach time so retroactive edits to the type don't mutate finalised payslips.
  - **Create `staff_recurring_allowances` table (G4)** with FK to `staff_members` ON DELETE CASCADE + FK to `allowance_types` ON DELETE RESTRICT, columns `amount`, `quantity`, `active`, `notes`, UNIQUE on `(staff_id, allowance_type_id)`. RLS + tenant_isolation policy.
  - **Create `ux_staff_members_user_id` partial UNIQUE index (N1)** `ON staff_members (user_id) WHERE user_id IS NOT NULL` — guarantees deterministic G9 self-service resolution. Verify no two staff_members rows share a user_id at upgrade time before applying the constraint (treat that as a P1 data-integrity bug to fix manually if it surfaces).
  - **Verify:** alembic upgrade head clean. `\d+ payslips` shows columns + RLS + the new `public_holiday_rate` column + `pdf_file_key text` + UNIQUE on `(staff_id, pay_period_id)` + `gross_pay`/`net_pay` DEFAULT 0. `\d+ payslip_allowances` shows `quantity`, `unit`. `SELECT count(*) FROM allowance_types WHERE org_id=<test>` returns 6 defaults. `\d+ staff_recurring_allowances` shows the table with RLS and ON DELETE CASCADE on staff_id FK. `SELECT pay_date_offset_days FROM organisations LIMIT 1` returns 3 default. `\d staff_members` shows the new partial UNIQUE index.

- [x] **A2. `0210_payslip_indexes.py`** — 9 indexes via CONCURRENTLY (per design §3.2).
  - Includes `idx_payslips_staff_status_finalised_desc` (G9 self-service list query).
  - Includes `idx_pay_periods_org_dates` (G25 termination period selection).
  - Includes `idx_staff_recurring_allowances_staff` partial (G4 attach lookup).
  - **Verify:** `EXPLAIN SELECT FROM payslips WHERE staff_id=$1 AND status='finalised' ORDER BY finalised_at DESC LIMIT 20` uses the new index. `EXPLAIN SELECT FROM pay_periods WHERE org_id=$1 AND :end_date BETWEEN start_date AND end_date` uses the new dates index.

## Workstream B — Backend

- [x] **B0. Phase 1 column-presence preflight (N7).** Add `app/modules/payslips/_preflight.py::assert_phase1_columns_present(db)` that runs at app startup (called from `app/main.py` lifespan) and SELECTs `column_name FROM information_schema.columns WHERE table_name='staff_members'`. Hard-fails with a clear log message naming any missing column from the P4-required set: `employment_type, tax_code, kiwisaver_enrolled, kiwisaver_employee_rate, kiwisaver_employer_rate, student_loan, employment_start_date, employment_end_date, standard_hours_per_week, bank_account_number_encrypted, ird_number_encrypted, average_daily_pay_snapshot`. Also asserts the `payroll` row exists in `module_registry`. Skips itself when running under pytest (`PYTEST_RUNNING=1` env var) so the test suite can run without P1 fully shipped.
  - **Verify:** drop one of the P1 columns in a test DB → app fails to start with a log line listing the missing column. Restore → app starts. Drop the `payroll` module_registry row → app fails. Restore → app starts.

- [x] **B1. ORM models** for all new tables (incl. `StaffRecurringAllowance`, plus `quantity`/`unit` on `PayslipAllowance`, plus `public_holiday_rate` on `Payslip`). `Payslip.pdf_file_key: Mapped[str | None] = mapped_column(Text, nullable=True)` (N3 — Text not UUID).

- [x] **B2. Pydantic schemas** with `{ items, total }` lists; payslip detail includes nested allowances/deductions/reimbursements/leave lines. Payslip response field is `pdf_file_key: str | None` (N3 — replaces the old `pdf_upload_id: UUID | None`); the public-facing PDF-download endpoint URL is constructed by the frontend as `/api/v2/payslips/{id}/pdf` rather than exposing the path.
  - New schemas: `StaffRecurringAllowanceCreate`, `StaffRecurringAllowanceUpdate`, `StaffRecurringAllowanceResponse`, `RecurringAllowanceListResponse` (G4).
  - New schemas: `MyPayslipsListResponse`, `MyPayslipDetailResponse` (G9 — exclude internal fields like the raw `pdf_file_key` path; expose only the download endpoint URL).
  - New schema: `PayPeriodReopenRequest` (G21 — body `{ reason: str }`).

- [x] **B3. `calc.py`** — wage math single source of truth.
  - **Includes `PUBLIC_HOLIDAY_DEFAULT_MULTIPLIER = Decimal('1.5')` constant + the public_holiday band in the gross composition (G2).**
  - Includes `_resolve_allowance_quantity(...)` helper per design §4.2 (G18 unit semantics) **with the concrete shift-count SQL query (N20 + cross-phase X1) — `COUNT(DISTINCT schedule_entries.id)` JOINed to `timesheet_approvals` on `(staff_id, week_range)` (NOT a non-existent `timesheet_approvals.time_clock_entry_id` FK), filters status='completed' on schedule_entries + status='approved' on timesheet_approvals, free-form clocked-in time excluded.**
  - **Direct ORM read for `overtime_handling` (cross-phase X4)** — `compute_payslip` reads `(await db.get(Organisation, org_id)).overtime_handling` directly. P2's gap-analysis P2-N5 settled this as a typed column on `organisations`; P3's P3-N4 confirmed and removed the JSONB fallback. The earlier `_org_setting('overtime_handling', ...)` helper with JSONB fallback was a vestige of the pre-resolution design — removed because the JSONB path is dead code that would mislead a future maintainer into thinking there's still flexibility in the storage shape.
  - **`gross_ytd` computed against the NZ tax year (N16)** — `SUM(payslips.gross_pay) WHERE staff_id=:s AND status='finalised' AND pay_periods.pay_date BETWEEN :tax_year_start AND :this_pay_date` where `:tax_year_start` is derived per-org from `organisations.income_tax_year_end` (1 April default). Recompute on every draft generation, never cache forever.
  - **Verify:** Hypothesis property tests:
    - gross >= sum(taxable allowances)
    - net >= 0
    - kiwisaver_employer not subtracted from gross
    - **G2: `public_holiday_hours × public_holiday_rate` contributes correctly to gross** — fuzz `(public_holiday_hours, ordinary_rate, override_rate)` and assert the sum invariant.
    - **G18: for `unit='shift'`, quantity-derived amount equals approved-shift count × default_amount.**
    - **N17: casual employee with zero approved hours → no `casual_8pct_holiday` line attached at all (NOT a $0.00 line).**
    - **N16: `gross_ytd` for a draft generated 5 April covering period ending 28 March excludes the 28 March payslip (different tax year); for a draft covering period ending 5 April, includes prior April payslips of the same tax year.**

- [x] **B4. `service.py`** — generate/finalise/void/email/bulk_finalise/reopen.
  - `generate_for_period` auto-attaches recurring allowances per G4 (look up `staff_recurring_allowances WHERE staff_id=:s AND active=true` for each draft, INSERT a `payslip_allowances` row per match using overrides or defaults).
  - **`reopen_pay_period(...)` (G21)** — refuses 409 when status='paid'; refuses 422 when already 'open'; sets status='open' + finalised_at=NULL; writes audit `pay_period.reopened`.
  - `void_payslip(...)` — when called and the parent period is 'finalised', the caller must reopen the period first (no auto-reopen).
  - **Verify:** unit test for reopen: finalised → open succeeds; paid → 409; open → 422.
  - **Verify (G4):** create a recurring rule for staff → call `generate_for_period` → assert one auto-attached `payslip_allowances` row with correct amount/quantity/unit. Edit the draft to remove that line → recurring rule still active in `staff_recurring_allowances`.

- [x] **B4a. `period_rolling.py` (G5 + G14)** — `compute_next_period_dates(...)` per design §4.2.1.
  - Pure-function: takes cadence + anchor_day + pay_date_offset_days + latest_end + today; returns `(start_date, end_date, pay_date)`.
  - Handles weekly/fortnightly/monthly with anchor-day rollover and month-end clamping (28/29/30/31).
  - Pay date rolls forward from Sat/Sun to next weekday.
  - **Verify:** unit test `tests/unit/test_period_rolling.py`:
    - Weekly with anchor=1 (Monday), latest_end=NULL, today=Wed → start=current Monday.
    - Fortnightly with latest_end=2026-06-07 → start=2026-06-08, end=2026-06-21.
    - Monthly with anchor=1, latest_end=2026-05-31 → start=2026-06-01, end=2026-06-30.
    - Monthly with anchor=29 in Feb 2027 (non-leap) → end clamps to 2027-02-28.
    - pay_date offset=3 lands on Sat → rolls forward to Mon.

- [x] **B5. `pdf.py`** — Jinja template + WeasyPrint via asyncio.to_thread. Reference pattern at `app/modules/quotes/service.py:1162-1165` (closest single-template shape).
  - Template path: `app/modules/payslips/templates/payslip.html` (N9 — per-module convention; no shared `app/templates/`).
  - **PDF includes masked bank account (G1)** in the employee section per R7.2.
  - **PDF renders public-holiday band as a separate row** with hours × rate per R4a / G2.
  - **PDF renders allowance rows with `quantity unit × unit_price = amount`** when unit ∈ {'shift','km'}; just `amount` when unit='period' (G18).
  - **PDF renders `Cash payment / no bank account on file` when `staff.bank_account_number_encrypted IS NULL` (N18).**
  - **PDF YTD figures (P4-N25):** PAYE / KiwiSaver-employee / KiwiSaver-employer YTD are computed at render time from `payslip_deductions` joined to `payslips` × `pay_periods.pay_date BETWEEN :tax_year_start AND :this_pay_date AND status='finalised'` — same tax-year window as `gross_ytd` per N16. Only `gross_ytd` is stored on `payslips`; the other three are recomputed every render via a `_compute_ytd_deductions(...)` helper.
  - **Verify:** integration test renders a sample payslip; PDF text contains tax_code, masked IRD, **masked bank account**, all hour bands incl. **public_holiday_rate**, gross, all deductions including KiwiSaver employer, net, leave_taken, every accruing leave balance, YTD totals, anniversary date, and **per-allowance quantity × unit × amount** for shift/km units. Plus a separate test renders a payslip for a staff with NULL bank_account → asserts the cash-payment fallback string is in the PDF. **(P4-N25)** PDF YTD test: insert two finalised payslips for the same staff in the same tax year with PAYE deductions $200 + $300 → render a third payslip in the same tax year → assert the rendered `paye_ytd` field reads $500 (sum of the two prior payslips' PAYE deductions); same shape for kiwisaver_employee and kiwisaver_employer.

- [x] **B5a. Print CSS (G20)** — `app/modules/payslips/templates/payslip.css` per design §6.9. A4 portrait, Inter font, page-break-inside on tables, running header/footer with page X of N.
  - **Verify:** render a 2-page payslip (lots of allowance lines + leave lines) → both pages have the org-logo header + page-counter footer; no table is split across page boundary.

- [x] **B5b. PDF storage helper (N3)** — `app/modules/payslips/pdf_storage.py` with `store_payslip_pdf(pdf_bytes, *, org_id, payslip_id) -> str` and `read_payslip_pdf(file_key, *, org_id) -> bytes` per design §4.4. Modelled on `app/modules/job_cards/attachment_service.py`. Uses `envelope_encrypt` + zlib + the same compression-flag byte layout as other attachment helpers. `read_payslip_pdf` validates `file_key.startswith(f"payslips/{org_id}/")` to prevent cross-tenant access and path traversal.
  - **Verify:** unit test: `store_payslip_pdf` writes a file at `UPLOAD_BASE/payslips/{org_id}/{payslip_id}/<uuid>.pdf` → `read_payslip_pdf` round-trips → bytes match. Cross-tenant test: store with org_A → call read with org_B → raises `ValueError("Access denied")`. Path-traversal test: pass `file_key="payslips/org_A/../../../etc/passwd"` → raises.

- [x] **B6. `termination.py`** — s27 calc, final payslip.
  - **Step 0 — concurrency guard (N19):** at transaction start, `SELECT 1 FROM staff_members WHERE id=:id FOR UPDATE`. Two concurrent termination requests serialise; the second sees `is_active=false` and returns 409 `already_terminated`.
  - **Step 1 — reconcile future leave (G16 + cross-phase X8):** SELECT approved leave_requests WHERE staff_id=:id AND start_date > :end_date; cancel each + write compensating leave_ledger row (reason='request_cancelled_after_approval'); set future schedule_entries.status='cancelled' (NOT hard-delete — would break P3's roster-change SMS hook and audit-history queries); audit `staff.termination_cancelled_future_leave`.
  - **Step 3 — pick pay_period (G25 + G6):** find period containing :end_date; if 'finalised' → reopen via R1a (audit `pay_period.reopened_for_termination`); if 'paid' → 409; if missing → call `roll_pay_periods_task` synchronously until a period covers :end_date (audit `pay_period.rolled_for_termination` per created period).
  - **Step 4a — KiwiSaver scope on termination (N15):** when generating the termination payslip, KiwiSaver employee + employer auto-deductions are calculated on the non-s27 portion only. The s27 lump-sum + alt-day payout is treated as extra-pay for PAYE purposes; admin still enters PAYE manually. Casual 8% line ALSO skips the lump-sum portion.
  - **Verify:** unit test `s27_annual_leave_payout` returns greater of weekly vs 52-wk avg.
  - **Verify (G16):** create staff with 80h annual remaining + an approved 40h leave request for next month → terminate today → assert: (a) leave request is cancelled, (b) `accrued_hours` restored to 80 (was 40 after the use-flag), (c) final payslip s27 payout based on the corrected 80h, (d) audit row written.
  - **Verify (G25):** terminate when no period covers :end_date → roll_pay_periods invoked; assert period auto-created, audit `pay_period.rolled_for_termination` written.
  - **Verify (N15):** terminate a KiwiSaver-enrolled staff with $2000 ordinary gross + $5000 s27 lump → KiwiSaver employee deduction = `(2000 × employee_rate)` NOT `(7000 × employee_rate)`. Same for employer (informational).
  - **Verify (N19):** spin up two concurrent `terminate` calls for the same staff → first succeeds, second returns 409 `already_terminated` (not a duplicate s27 payment).

- [x] **B7. Router** — all endpoints from design §5 incl. the new ones:
  - `POST /api/v2/pay-periods/:id/reopen` (G21).
  - `GET/POST /api/v2/staff/:id/payslips/recurring-allowances` + PATCH/DELETE on `:rule_id` (G4).
  - `GET /api/v2/staff/me/payslips`, `:id`, `:id/pdf` (G9 — server-side ownership check via `staff_members.user_id` not the non-existent `users.staff_id` (N1); 404 not 403 on mismatch; payroll module-gated in service layer (N8)).
  - All other payroll endpoints module-gated by `payroll` via the middleware (B11). Finalise endpoints reject 409 if already finalised.
  - **Verify:** test the ownership-leak guard: log in as staff A, `GET /staff/me/payslips/<staff_B_payslip_id>` → 404 (NOT 403 — no existence leak). Log in as admin, same call to `/staff/<id>/payslips/<id>` → 200.
  - **Verify (N2):** terminate staff A → log in as A → `GET /staff/me/payslips` still returns A's historical finalised payslips (intentionally — record retention).

- [x] **B8. Refuse UPDATE/DELETE** on finalised payslips (service layer guard). Reopening the parent period (G21) does NOT unlock individual finalised payslips — only allows new compensating drafts alongside. **(P4-N26)** The guard is a column-allowlist: only `emailed_at` may be updated on a finalised payslip (per R3.4 + R8.3). All other columns refused with HTTP 409.

- [x] **B9. Register router** in `app/main.py`.

- [x] **B10. Audit redaction enforcement (G12 + P4-N32)** — every `write_audit_log` call in `app/modules/payslips/` constructs an explicit redacted `after_value` per design §4.5. Lint: a unit test `tests/unit/test_payslip_audit_redaction.py` parses every `write_audit_log(...)` call site in the payslips module and asserts the after_value dict literal contains NONE of the expanded forbidden-key set: `{'gross_pay', 'net_pay', 'amount', 'ird_number', 'bank_account_number', 'paye', 's27_lump_sum', 'annual_payout_dollars', 'alt_day_total_dollars', 'casual_8pct_remainder_dollars', 'recipient_email'}`. The expanded set covers payslip events AND `staff.terminated`. Plus a positive assertion: `staff.terminated` after_value MUST contain `payout_summary` (a dict) with keys `annual_hours`, `alt_days`, `casual_8pct_remaining` (per R14).
  - **Verify:** the redaction test passes; manually inspect a `payslip.emailed` audit row → `recipient_email_domain_only` field present, full email NOT present. Manually inspect a `staff.terminated` audit row → `payout_summary` object present with hour/day counts, NO dollar amounts.

- [x] **B11. Module middleware path entries (N8).** Add three entries to `app/middleware/modules.py::MODULE_ENDPOINT_MAP`:
  ```python
  "/api/v2/pay-periods": "payroll",
  "/api/v2/payslips": "payroll",
  "/api/v2/allowance-types": "payroll",
  ```
  - Note: `/api/v2/staff` is already gated by the `staff` module. The new self-service `/api/v2/staff/me/payslips` endpoints inherit this gate. The additional `payroll` enforcement is service-layer (in the handler) because the middleware only resolves on path-prefix.
  - **Verify:** with `payroll` disabled for an org, GET `/api/v2/pay-periods` → 403 with body `{"detail": "Module 'payroll' is not enabled for your organisation.", "module": "payroll"}`. With `staff` enabled but `payroll` disabled, GET `/api/v2/staff/me/payslips` → 403 (raised by the service-layer check; same body shape for consistency).

## Workstream C — Scheduled tasks

- [x] **C1. `roll_pay_periods` daily task** — for each org with `payroll` enabled, ensure next 4 pay-periods exist. Uses `compute_next_period_dates` from B4a. Idempotent via UNIQUE (org_id, start_date).
  - **Verify:** force-run on a fresh org with no history → 4 periods created; force-run again → 0 created (idempotent); change cadence → next tick rolls forward without retroactive change (G14).

- [x] **C1a. Wire `roll_pay_periods_task` into the daily scheduler dispatcher (N10).** The codebase has `app/tasks/scheduled.py` with plain async functions but no obvious central daily dispatcher visible at spec time — locate the cron-like wiring (likely in `app/main.py` lifespan, or an external systemd/cron timer that hits an admin endpoint, or a Redis-backed scheduler-lock pattern around `check_overdue_invoices_task`) and register `roll_pay_periods_task` alongside it. If no central dispatcher exists, add one in `app/tasks/scheduled.py::run_daily_tasks()` that calls every `*_task` function once per UTC day and is invoked from a single cron entry / systemd timer / FastAPI startup background loop.
  - **Verify:** local run of the dispatcher (or simulate the cron tick via a manual call) → `roll_pay_periods_task` fires; pay_periods rows materialise. Test with the scheduler-lock pattern from `check_overdue_invoices_task` so we don't double-run on multi-replica deploys.

- [x] **C2. Update `update_adp_snapshots`** to use real payslip data (R13). Falls back to Phase 2 calc when no payslips exist.

## Workstream D — Frontend

- [x] **D1. `PayRunPage.tsx`** — period selector, generate, table, bulk finalise, progress bar.

- [x] **D2. `PayslipDetail.tsx`** — drawer/modal editor.
  - Shows the public-holiday band as a separate row (G2) with editable rate.
  - Allowance rows render `quantity unit × unit_price = amount` for shift/km units (G18); admin can edit quantity for `unit='km'` directly.

- [x] **D3. `PayslipsTab.tsx`** (Staff Detail, admin view).

- [x] **D4. `TerminationModal.tsx`** with payout preview.
  - Shows the cancelled future-leave count (G16): "3 approved leave requests covering 32h will be cancelled and refunded to the balance before payout."
  - Shows the chosen final-payslip pay_period (G25): "Final payslip will land in pay period 8–14 July (will reopen the finalised period)" or "Final payslip will create a new pay period covering 1–7 July."

- [x] **D5. Settings pages** — PayPeriodsPage (with **Reopen button per G21**), AllowanceTypesPage.

- [x] **D6. `WageVariancePage.tsx`** (Reports).

- [x] **D7. Sidebar** — "Payroll" entry under People.

- [x] **D8. PDF preview iframe** in PayslipDetail when finalised.

- [x] **D9. All API consumption**: `?.` + `?? []` + AbortController; typed clients in `frontend/src/api/payslips.ts`.

- [x] **D10. Recurring Allowances panel (G4 + P4-N31)** — `RecurringAllowancesPanel.tsx` per design §6.7. The new collapsible section is APPENDED to the Phase 1 Overview tab (NOT a pre-allocated slot — Phase 1 did not reserve one). Implementer touches `frontend/src/pages/staff/tabs/OverviewTab.tsx` to add the new section import + render below the existing Tax & Pay panel. Includes `AddRecurringAllowanceModal` for adding rules.
  - **Verify:** browser test — add a `meal_allowance @ $50/period` recurring rule for Jane → generate a draft payslip for Jane → assert the $50 line auto-attached. Remove the rule from the draft (admin override) → finalise → re-generate next period → $50 line auto-attached again (rule still active).

- [x] **D11. Staff self-service Payslips (G9)**:
  - **Web** — `frontend/src/pages/staff/me/MyPayslipsPage.tsx` (lazy-loaded route `/staff/me/payslips` in App.tsx behind `RequireAuth` + payroll module gate).
  - **Mobile** — `mobile/src/screens/payslips/PayslipsScreen.tsx` (lazy import in `StackRoutes.tsx`, behind `ModuleGate moduleSlug="payroll"`). Capacitor share sheet on native via `isNativePlatform()` guard for the download button.
  - **Verify:** browser test as staff_member with linked user_id → `/staff/me/payslips` renders own list, drafts/voided not visible, click PDF → opens download. Same flow on mobile.

## Workstream E — Tests

- [x] **E1. Unit tests** — `tests/unit/test_payslip_calc.py`, `_service.py`, `_termination.py`, `_pdf.py`.
  - `test_payslip_calc.py` includes G2 public-holiday-rate tests + G18 quantity/unit tests.
  - `test_payslip_service.py` includes G4 recurring-allowance auto-attach + G21 reopen.
  - `test_termination.py` includes G16 future-leave reconciliation + G25 period selection (open/finalised/paid/missing branches).

- [x] **E1a. `tests/unit/test_period_rolling.py`** (G5) — unit tests for `compute_next_period_dates` covering weekly/fortnightly/monthly + month-end clamps + leap years + weekend-pay-date roll-forward.

- [x] **E1b. `tests/unit/test_payslip_audit_redaction.py`** (G12 + P4-N32) — asserts every `write_audit_log(...)` call site in `app/modules/payslips/` constructs an `after_value` that excludes the expanded forbidden-key set: `{'gross_pay', 'net_pay', 'amount', 'ird_number', 'bank_account_number', 'paye', 's27_lump_sum', 'annual_payout_dollars', 'alt_day_total_dollars', 'casual_8pct_remainder_dollars', 'recipient_email'}`. Plus a positive assertion that `staff.terminated` after_value contains a `payout_summary` dict with keys `annual_hours`, `alt_days`, `casual_8pct_remaining`.

- [x] **E2. Property test** `tests/property/test_payslip_invariants.py` — gross/net invariants; kiwisaver math; casual 8% never recurses; public_holiday_rate × hours contributes correctly to gross (G2); auto-attached allowance amount = quantity × unit_price (G18).

- [x] **E3. PDF integration** — render sample, parse PDF, assert every Wages Protection + s130A field present + the masked bank account (G1) + the public-holiday band rate row (G2) + per-allowance quantity rendering (G18) + multi-page header/footer (G20).

- [x] **E4. E2E** `scripts/test_staff_payslip_e2e.py` per R15. **Extended to cover all 8 real gaps + 4 minor:**
  - **G1:** generate payslip → download PDF → assert masked bank account string `**-****-****NN-**` present.
  - **G2:** set `public_holiday_hours=8`, `ordinary_rate=$25` → expected `public_holiday_rate=$37.50` → expected contribution to gross=$300. Assert payslip row + PDF show $37.50/h.
  - **G4:** create recurring `meal_allowance @ $50/period` for Jane → generate next pay run → assert auto-attach. Remove rule → next run → no auto-attach.
  - **G5:** force `roll_pay_periods` on a fresh org with cadence=fortnightly, anchor=1 → assert 4 sequential periods created with correct start/end/pay dates.
  - **G6:** terminate a staff dated for a future date past the rolled horizon → assert task synchronously rolls a new period covering the date.
  - **G9:** log in as staff with linked user → `GET /api/v2/staff/me/payslips` returns own finalised list → `GET .../staff_B_payslip_id` returns 404 (ownership-leak guard).
  - **G12:** finalise + email a payslip → query `audit_log` rows for that payslip → assert NONE contain raw `gross_pay`, `net_pay`, `paye`, full `ird_number`, full `bank_account_number`, full email address.
  - **G14:** flip cadence weekly→monthly mid-flight → assert next roll uses monthly rule from `latest_end+1` without retroactively merging existing weekly periods.
  - **G16:** terminate Jane with an approved future leave request → assert request cancelled, `accrued_hours` restored, final payslip s27 calc on corrected balance, `staff.termination_cancelled_future_leave` audit row.
  - **G18:** create allowance `tool @ $10/shift` + apply to staff with 5 approved shifts → assert quantity=5, unit='shift', amount=$50 on payslip + PDF row reads "Tool allowance: 5 shifts × $10.00 = $50.00".
  - **G20:** render a 2-page payslip → assert page-break-inside on every table; running header/footer present on both pages.
  - **G21:** finalise a period → click Reopen → confirm with reason → assert status='open', existing finalised payslips still locked. Try to reopen a paid period → 409. Try to reopen an open period → 422.
  - **G24:** time the bulk-finalise endpoint for a 50-staff org → assert returns within 5s; PDFs populate within 60s p99.
  - **G25:** terminate with end_date inside an existing finalised period → assert period reopens (audit `pay_period.reopened_for_termination`), final payslip lands in that period.

## Workstream F — Versioning + docs

- [x] **F1. Bump 1.16.0 → 1.17.0** across pyproject.toml + frontend/package.json + mobile/package.json.
- [x] **F2. CHANGELOG `## [1.17.0]`** — payslips, allowances, KiwiSaver auto, casual 8%, termination payouts (s27), wage variance report, **G1–G25 closures (recurring allowances, public-holiday band, period rolling, period reopen, future-leave reconciliation, allowance quantity semantics, self-service payslips, audit redaction)**.
- [x] **F3. STAFF-004** in ISSUE_TRACKER updated (bank format choice deferred to Phase 5).

## Pre-merge gate

Tick everything in source plan §12. Specifically:
- **Hard prerequisite check (N12):** `SELECT 1 FROM module_registry WHERE slug='payroll'` returns a row. P4 cannot deploy without this.
- **Hard prerequisite check (N7):** `B0` preflight passes — every required staff_members column from P1 is present.
- PDF includes every Wages Protection Act + s130A field (verified by parsing) + **masked bank account (G1) + public-holiday band rate (G2) + allowance quantity/unit display (G18) + multi-page header/footer (G20) + cash-payment fallback string when bank account is NULL (N18)**.
- Casual 8% line auto-attached and equals 8% of taxable earnings; OMITTED entirely when gross is 0 (N17).
- KiwiSaver employee deducted, employer informational (not subtracted); termination payslip excludes s27 lump-sum from KiwiSaver basis (N15).
- Termination payout uses greater-of formula AND **first reconciles future-dated approved leave (G16)** AND **picks the right pay_period including auto-roll-on-missing (G6) + reopen-on-finalised (G25)** AND **acquires row lock on staff_members FOR UPDATE (N19)**.
- Finalised payslip immutable (409 on PUT).
- IRD/bank decryption only inside pdf.render path; encryption uses `envelope_encrypt(...)` (N14).
- Bulk finalise handles partial failure via SAVEPOINT.
- Bulk emails route through send_email + DLQ.
- **Pay period reopen flow works (G21) — refuses paid; allows new drafts in reopened periods.**
- **Audit redaction enforced (G12) — payslip events never leak raw amounts or PII.** Self-service GETs do NOT emit audit rows (N2).
- **Self-service `/staff/me/payslips` endpoints work (G9) — own data only, 404 on cross-staff access, payroll module-gated. Resolver uses `staff_members.user_id` not the non-existent `users.staff_id` (N1).** `is_active` filter intentionally OMITTED so terminated staff retain access (N2).
- **Recurring allowances auto-attach on draft (G4) — admin can override per-draft, rule survives.**
- **`compute_next_period_dates` covers weekly/fortnightly/monthly + month-end clamps + weekend pay-date roll (G5).**
- **Cadence change is non-retroactive (G14).**
- **Print CSS produces clean A4 multi-page payslips (G20). Templates at `app/modules/payslips/templates/` (N9).**
- **Bulk-finalise SLO met for 50-staff org (G24).**
- **`pdf_file_key` text path (not `pdf_upload_id` UUID) — matches existing attachment conventions (N3). `pdf_storage.py` round-trips with cross-tenant guard.**
- **Module middleware path entries added for `/api/v2/pay-periods`, `/api/v2/payslips`, `/api/v2/allowance-types` (N8 + B11). Module-disabled response is 403 not 404.**
- **Daily scheduler dispatcher wires `roll_pay_periods_task` (N10 + C1a) — verified by local tick.**
- **Concrete shift-count SQL in `_resolve_allowance_quantity` (N20) — joins schedule_entries + time_clock_entries + timesheet_approvals; free-form clocks excluded.**

**G1–G25 closure ticks (added during gap analysis):**
- [x] G1: PDF includes masked bank account string.
- [x] G2: `public_holiday_rate` column persists; default = ordinary × 1.5; Hypothesis test passes.
- [x] G4: `staff_recurring_allowances` table exists with RLS; auto-attach in `generate_for_period`; UI panel on Overview tab.
- [x] G5: `compute_next_period_dates` algorithm spec'd + unit-tested for all three cadences.
- [x] G6: termination synchronously rolls periods if none covers `:end_date`; audit row written.
- [x] G9: three `/staff/me/payslips/*` endpoints + web + mobile screens; ownership-leak guard returns 404.
- [x] G12: every payslip-related audit row excludes raw amounts and decrypted PII; lint test passes.
- [x] G14: changing cadence does not retroactively rewrite existing periods; audit row written on change.
- [x] G16: termination cancels future-dated approved leave first; restores hours; audits.
- [x] G18: `payslip_allowances` has `quantity` + `unit` columns; auto-derivation per unit; PDF renders quantity correctly.
- [x] G20: payslip.css spec'd with @page rules, page-break-inside avoid, running header/footer.
- [x] G21: `POST /pay-periods/:id/reopen` works; respects open/finalised/paid states; existing payslips stay locked.
- [x] G24: bulk-finalise SLO documented + tested.
- [x] G25: termination final-payslip pay_period selection rule applied (open / reopen-finalised / 409-paid / auto-roll-if-missing).

**N1–N20 closure ticks (added 2026-05-31 code-vs-spec gap analysis):**
- [x] N1: `ux_staff_members_user_id` partial UNIQUE index created; resolver uses `staff_members.user_id`.
- [x] N2: terminated staff retain self-service access; self-service GETs do NOT emit audit rows.
- [x] N3: `pdf_file_key text` column (renamed from `pdf_upload_id uuid`); `pdf_storage.py` round-trip + cross-tenant guard tests pass.
- [x] N4: WeasyPrint reference points fixed across spec.
- [x] N5: `_org_setting('overtime_handling', ...)` helper present.
- [x] N6: covered by N1.
- [x] N7: B0 preflight catches missing P1 columns at startup.
- [x] N8: module-disabled = 403 (not 404); `MODULE_ENDPOINT_MAP` entries added.
- [x] N9: templates at `app/modules/payslips/templates/`.
- [x] N10: scheduler dispatcher wiring documented + working.
- [x] N11: audit column names verified (singular).
- [x] N12: `payroll` module_registry insert is a hard prereq; pre-merge SELECT passes.
- [x] N13: `schedule_entries.entry_type='leave'` verified.
- [x] N14: bank/IRD encryption uses `envelope_encrypt(...)` consistent with IRD module.
- [x] N15: KiwiSaver skips s27 lump on termination payslip; verified.
- [x] N16: `gross_ytd` follows NZ tax-year boundary (1 April → 31 March); recomputed every draft.
- [x] N17: casual 8% line OMITTED when gross is 0.
- [x] N18: PDF renders cash-payment fallback when bank account is NULL.
- [x] N19: termination acquires `staff_members FOR UPDATE` row lock; concurrent calls return 409.
- [x] N20: shift-count SQL in `_resolve_allowance_quantity` joins schedule_entries + time_clock_entries + timesheet_approvals correctly.

**P4-N21–P4-N32 closure ticks (added 2026-05-31 internal alignment review)**
- [x] P4-N21: R10 Step 5 uses `audit_log` (singular) — matches the rest of the spec.
- [x] P4-N22: R10 Step 5 audit `after_value` shape redacted per R14 (`{ staff_id, end_date, payout_summary: { annual_hours, alt_days, casual_8pct_remaining } }`); no "full breakdown JSON" leak.
- [x] P4-N23: Wage variance endpoint is `/api/v2/reports/wage-variance` (singular) everywhere — requirements + design + tasks aligned.
- [x] P4-N24: R11 references `staff_members.last_pay_review_date < (now() - interval '12 months')` — the actual Phase 1 column, not the non-existent `staff_pay_rates.last_change`.
- [x] P4-N25: PDF YTD figures (PAYE, KiwiSaver employee, KiwiSaver employer) computed at render time from `payslip_deductions`; only `gross_ytd` is stored on `payslips`. Verify test queries `payslip_deductions` SUM by kind for the tax year.
- [x] P4-N26: B8 finalised-immutability guard is a column-allowlist allowing `emailed_at` updates (not a blanket `WHERE status='finalised' RAISE 409`).
- [x] P4-N27: Tasks Workstream B order is B0-B11 sequential (B10 precedes B11).
- [x] P4-N28: `payslips` has `UNIQUE (staff_id, pay_period_id)` — supports `generate_for_period` idempotency; documented in R3.1 + tasks A1.
- [x] P4-N29: `payslips.gross_pay` and `payslips.net_pay` are `NOT NULL DEFAULT 0` — matches design §3.1; allows draft creation pre-compute.
- [x] P4-N30: R10 Step 4 explicitly distinguishes "casual-8% remainder true-up" (one-time settlement) from R5's "in-period 8% accrual" (per-payslip wages-as-you-go); Step 4a clarifies which counts toward KiwiSaver basis.
- [x] P4-N31: Design §6.7 + tasks D10 acknowledge that the Recurring Allowances panel is APPENDED to the Phase 1 Overview tab, not a pre-allocated slot.
- [x] P4-N32: B10 + E1b expanded forbidden-key set covers `staff.terminated` dollar-amount keys (`s27_lump_sum`, `annual_payout_dollars`, etc.); positive assertion verifies `payout_summary` dict shape.

## Auto-advance to next phase

When every checkbox above is ticked AND `gap-analysis.md` + `internal-alignment-gap-analysis.md` are empty (or every entry has a documented reason for deferral), proceed automatically to **Phase 5** without waiting for further user prompt:

- [x] **NEXT. Begin Staff Management Phase 5** — open `.kiro/specs/staff-management-p5/tasks.md` and start at task A1. Treat the Phase 5 tasks file as the next active spec; carry forward any implementation context (alembic head now at 0210, version 1.17.0, payslips + pay_periods + payslip_allowances + payslip_deductions + payslip_reimbursements + payslip_leave_lines + staff_recurring_allowances tables shipped, `roll_pay_periods` + `update_adp_snapshots` scheduled tasks running, payroll module gate live in MODULE_ENDPOINT_MAP, self-service `/staff/me/payslips` endpoints + UI screens deployed) from Phase 4's completion state.

**DEFERRED 2026-06-01.** Phase 5 is explicitly optional/deferrable per its own scope (reports, dashboard widgets, bank-file export, IRD export). The Phase 5 tasks.md execution policy states: "Deferral path — if customer demand for P5 is undocumented when the chain reaches it (no STAFF-011 resolution + no signal in `docs/ISSUE_TRACKER.md`), log 'Phase 5 deferred — no customer demand recorded' to a new line in this file and stop cleanly without raising an error."

Phase 5 also has a hard PREREQ-1 (STAFF-011 — dashboard `WidgetGrid` is gated to automotive-transport orgs only; payroll widgets need a cross-trade-family decision before any A-task starts) that requires a product-level decision based on customer demand signals. As of 2026-06-01 there is no STAFF-011 resolution and no signal in `docs/ISSUE_TRACKER.md` indicating customer demand for Phase 5 features. Phase 4 (the production payroll surface) ships standalone — the deferred reporting + bank-file export work has no functional dependency on Phase 4 and can ship independently when demand surfaces.

Note: Phase 5 is **optional / deferrable** per its own scope — only kick off if customer demand for reporting + bank-file export exists. If deferred, document the deferral reason and stop here.
