# Staff Management Phase 4 — Tasks

## Workstream A — Migrations

- [ ] **A1. `0209_payslip_schema.py`** — pay_periods, allowance_types (+ defaults seed), payslips, payslip_allowances, payslip_deductions, payslip_reimbursements, payslip_leave_lines. RLS + tenant_isolation on all. CHECK constraints. Idempotent.
  - Add `organisations.pay_period_cadence`, `pay_period_anchor_day`, **and `pay_date_offset_days int default 3` (G5)**.
  - **Add `payslips.public_holiday_rate numeric(10,2)` (G2)** — defaulted to `ordinary_rate × 1.5` by `compute_payslip`; admin overridable.
  - **Add `payslip_allowances.quantity numeric(10,2) NOT NULL DEFAULT 1` and `unit text NOT NULL DEFAULT 'period' CHECK IN ('shift','period','km')` (G18)** — quantity is shifts/km/1; unit is COPIED from `allowance_types.unit` at attach time so retroactive edits to the type don't mutate finalised payslips.
  - **Create `staff_recurring_allowances` table (G4)** with FK to `staff_members` ON DELETE CASCADE + FK to `allowance_types` ON DELETE RESTRICT, columns `amount`, `quantity`, `active`, `notes`, UNIQUE on `(staff_id, allowance_type_id)`. RLS + tenant_isolation policy.
  - **Verify:** alembic upgrade head clean. `\d+ payslips` shows columns + RLS + the new `public_holiday_rate` column. `\d+ payslip_allowances` shows `quantity`, `unit`. `SELECT count(*) FROM allowance_types WHERE org_id=<test>` returns 6 defaults. `\d+ staff_recurring_allowances` shows the table with RLS and ON DELETE CASCADE on staff_id FK. `SELECT pay_date_offset_days FROM organisations LIMIT 1` returns 3 default.

- [ ] **A2. `0210_payslip_indexes.py`** — 9 indexes via CONCURRENTLY (per design §3.2).
  - Includes `idx_payslips_staff_status_finalised_desc` (G9 self-service list query).
  - Includes `idx_pay_periods_org_dates` (G25 termination period selection).
  - Includes `idx_staff_recurring_allowances_staff` partial (G4 attach lookup).
  - **Verify:** `EXPLAIN SELECT FROM payslips WHERE staff_id=$1 AND status='finalised' ORDER BY finalised_at DESC LIMIT 20` uses the new index. `EXPLAIN SELECT FROM pay_periods WHERE org_id=$1 AND :end_date BETWEEN start_date AND end_date` uses the new dates index.

## Workstream B — Backend

- [ ] **B1. ORM models** for all new tables (incl. `StaffRecurringAllowance`, plus `quantity`/`unit` on `PayslipAllowance`, plus `public_holiday_rate` on `Payslip`).

- [ ] **B2. Pydantic schemas** with `{ items, total }` lists; payslip detail includes nested allowances/deductions/reimbursements/leave lines.
  - New schemas: `StaffRecurringAllowanceCreate`, `StaffRecurringAllowanceUpdate`, `StaffRecurringAllowanceResponse`, `RecurringAllowanceListResponse` (G4).
  - New schemas: `MyPayslipsListResponse`, `MyPayslipDetailResponse` (G9 — exclude internal fields like `pdf_upload_id`'s decrypted URL; expose only download endpoint URL).
  - New schema: `PayPeriodReopenRequest` (G21 — body `{ reason: str }`).

- [ ] **B3. `calc.py`** — wage math single source of truth.
  - **Includes `PUBLIC_HOLIDAY_DEFAULT_MULTIPLIER = Decimal('1.5')` constant + the public_holiday band in the gross composition (G2).**
  - Includes `_resolve_allowance_quantity(...)` helper per design §4.2 (G18 unit semantics).
  - **Verify:** Hypothesis property tests:
    - gross >= sum(taxable allowances)
    - net >= 0
    - kiwisaver_employer not subtracted from gross
    - **G2: `public_holiday_hours × public_holiday_rate` contributes correctly to gross** — fuzz `(public_holiday_hours, ordinary_rate, override_rate)` and assert the sum invariant.
    - **G18: for `unit='shift'`, quantity-derived amount equals approved-shift count × default_amount.**

- [ ] **B4. `service.py`** — generate/finalise/void/email/bulk_finalise/reopen.
  - `generate_for_period` auto-attaches recurring allowances per G4 (look up `staff_recurring_allowances WHERE staff_id=:s AND active=true` for each draft, INSERT a `payslip_allowances` row per match using overrides or defaults).
  - **`reopen_pay_period(...)` (G21)** — refuses 409 when status='paid'; refuses 422 when already 'open'; sets status='open' + finalised_at=NULL; writes audit `pay_period.reopened`.
  - `void_payslip(...)` — when called and the parent period is 'finalised', the caller must reopen the period first (no auto-reopen).
  - **Verify:** unit test for reopen: finalised → open succeeds; paid → 409; open → 422.
  - **Verify (G4):** create a recurring rule for staff → call `generate_for_period` → assert one auto-attached `payslip_allowances` row with correct amount/quantity/unit. Edit the draft to remove that line → recurring rule still active in `staff_recurring_allowances`.

- [ ] **B4a. `period_rolling.py` (G5 + G14)** — `compute_next_period_dates(...)` per design §4.2.1.
  - Pure-function: takes cadence + anchor_day + pay_date_offset_days + latest_end + today; returns `(start_date, end_date, pay_date)`.
  - Handles weekly/fortnightly/monthly with anchor-day rollover and month-end clamping (28/29/30/31).
  - Pay date rolls forward from Sat/Sun to next weekday.
  - **Verify:** unit test `tests/unit/test_period_rolling.py`:
    - Weekly with anchor=1 (Monday), latest_end=NULL, today=Wed → start=current Monday.
    - Fortnightly with latest_end=2026-06-07 → start=2026-06-08, end=2026-06-21.
    - Monthly with anchor=1, latest_end=2026-05-31 → start=2026-06-01, end=2026-06-30.
    - Monthly with anchor=29 in Feb 2027 (non-leap) → end clamps to 2027-02-28.
    - pay_date offset=3 lands on Sat → rolls forward to Mon.

- [ ] **B5. `pdf.py`** — Jinja template + WeasyPrint via asyncio.to_thread.
  - **PDF includes masked bank account (G1)** in the employee section per R7.2.
  - **PDF renders public-holiday band as a separate row** with hours × rate per R4a / G2.
  - **PDF renders allowance rows with `quantity unit × unit_price = amount`** when unit ∈ {'shift','km'}; just `amount` when unit='period' (G18).
  - **Verify:** integration test renders a sample payslip; PDF text contains tax_code, masked IRD, **masked bank account**, all hour bands incl. **public_holiday_rate**, gross, all deductions including KiwiSaver employer, net, leave_taken, every accruing leave balance, YTD totals, anniversary date, and **per-allowance quantity × unit × amount** for shift/km units.

- [ ] **B5a. Print CSS (G20)** — `app/templates/payslips/payslip.css` per design §6.9. A4 portrait, Inter font, page-break-inside on tables, running header/footer with page X of N.
  - **Verify:** render a 2-page payslip (lots of allowance lines + leave lines) → both pages have the org-logo header + page-counter footer; no table is split across page boundary.

- [ ] **B6. `termination.py`** — s27 calc, final payslip.
  - **Step 1 — reconcile future leave (G16):** SELECT approved leave_requests WHERE staff_id=:id AND start_date > :end_date; cancel each + write compensating leave_ledger row (reason='request_cancelled_after_approval'); cancel future schedule_entries; audit `staff.termination_cancelled_future_leave`.
  - **Step 3 — pick pay_period (G25 + G6):** find period containing :end_date; if 'finalised' → reopen via R1a (audit `pay_period.reopened_for_termination`); if 'paid' → 409; if missing → call `roll_pay_periods_task` synchronously until a period covers :end_date (audit `pay_period.rolled_for_termination` per created period).
  - **Verify:** unit test `s27_annual_leave_payout` returns greater of weekly vs 52-wk avg.
  - **Verify (G16):** create staff with 80h annual remaining + an approved 40h leave request for next month → terminate today → assert: (a) leave request is cancelled, (b) `accrued_hours` restored to 80 (was 40 after the use-flag), (c) final payslip s27 payout based on the corrected 80h, (d) audit row written.
  - **Verify (G25):** terminate when no period covers :end_date → roll_pay_periods invoked; assert period auto-created, audit `pay_period.rolled_for_termination` written.

- [ ] **B7. Router** — all endpoints from design §5 incl. the new ones:
  - `POST /api/v2/pay-periods/:id/reopen` (G21).
  - `GET/POST /api/v2/staff/:id/payslips/recurring-allowances` + PATCH/DELETE on `:rule_id` (G4).
  - `GET /api/v2/staff/me/payslips`, `:id`, `:id/pdf` (G9 — server-side ownership check; 404 not 403 on mismatch; module-gated by `payroll`).
  - All endpoints module-gated by `payroll`. Finalise endpoints reject 409 if already finalised.
  - **Verify:** test the ownership-leak guard: log in as staff A, `GET /staff/me/payslips/<staff_B_payslip_id>` → 404 (NOT 403 — no existence leak). Log in as admin, same call to `/staff/<id>/payslips/<id>` → 200.

- [ ] **B8. Refuse UPDATE/DELETE** on finalised payslips (service layer guard). Reopening the parent period (G21) does NOT unlock individual finalised payslips — only allows new compensating drafts alongside.

- [ ] **B9. Register router** in `app/main.py`.

- [ ] **B10. Audit redaction enforcement (G12)** — every `write_audit_log` call in `app/modules/payslips/` constructs an explicit redacted `after_value` per design §4.5. Lint: a unit test `tests/unit/test_payslip_audit_redaction.py` parses every `write_audit_log(...)` call site in the payslips module and asserts the after_value dict literal contains NONE of `{'gross_pay', 'net_pay', 'amount', 'ird_number', 'bank_account_number', 'paye'}` keys.
  - **Verify:** the redaction test passes; manually inspect a `payslip.emailed` audit row → `recipient_email_domain_only` field present, full email NOT present.

## Workstream C — Scheduled tasks

- [ ] **C1. `roll_pay_periods` daily task** — for each org with `payroll` enabled, ensure next 4 pay-periods exist. Uses `compute_next_period_dates` from B4a. Idempotent via UNIQUE (org_id, start_date).
  - **Verify:** force-run on a fresh org with no history → 4 periods created; force-run again → 0 created (idempotent); change cadence → next tick rolls forward without retroactive change (G14).

- [ ] **C2. Update `update_adp_snapshots`** to use real payslip data (R13). Falls back to Phase 2 calc when no payslips exist.

## Workstream D — Frontend

- [ ] **D1. `PayRunPage.tsx`** — period selector, generate, table, bulk finalise, progress bar.

- [ ] **D2. `PayslipDetail.tsx`** — drawer/modal editor.
  - Shows the public-holiday band as a separate row (G2) with editable rate.
  - Allowance rows render `quantity unit × unit_price = amount` for shift/km units (G18); admin can edit quantity for `unit='km'` directly.

- [ ] **D3. `PayslipsTab.tsx`** (Staff Detail, admin view).

- [ ] **D4. `TerminationModal.tsx`** with payout preview.
  - Shows the cancelled future-leave count (G16): "3 approved leave requests covering 32h will be cancelled and refunded to the balance before payout."
  - Shows the chosen final-payslip pay_period (G25): "Final payslip will land in pay period 8–14 July (will reopen the finalised period)" or "Final payslip will create a new pay period covering 1–7 July."

- [ ] **D5. Settings pages** — PayPeriodsPage (with **Reopen button per G21**), AllowanceTypesPage.

- [ ] **D6. `WageVariancePage.tsx`** (Reports).

- [ ] **D7. Sidebar** — "Payroll" entry under People.

- [ ] **D8. PDF preview iframe** in PayslipDetail when finalised.

- [ ] **D9. All API consumption**: `?.` + `?? []` + AbortController; typed clients in `frontend/src/api/payslips.ts`.

- [ ] **D10. Recurring Allowances panel (G4)** — `RecurringAllowancesPanel.tsx` per design §6.7. Lives in a new collapsible section on the Phase 1 Overview tab. Includes `AddRecurringAllowanceModal` for adding rules.
  - **Verify:** browser test — add a `meal_allowance @ $50/period` recurring rule for Jane → generate a draft payslip for Jane → assert the $50 line auto-attached. Remove the rule from the draft (admin override) → finalise → re-generate next period → $50 line auto-attached again (rule still active).

- [ ] **D11. Staff self-service Payslips (G9)**:
  - **Web** — `frontend/src/pages/staff/me/MyPayslipsPage.tsx` (lazy-loaded route `/staff/me/payslips` in App.tsx behind `RequireAuth` + payroll module gate).
  - **Mobile** — `mobile/src/screens/payslips/PayslipsScreen.tsx` (lazy import in `StackRoutes.tsx`, behind `ModuleGate moduleSlug="payroll"`). Capacitor share sheet on native via `isNativePlatform()` guard for the download button.
  - **Verify:** browser test as staff_member with linked user_id → `/staff/me/payslips` renders own list, drafts/voided not visible, click PDF → opens download. Same flow on mobile.

## Workstream E — Tests

- [ ] **E1. Unit tests** — `tests/unit/test_payslip_calc.py`, `_service.py`, `_termination.py`, `_pdf.py`.
  - `test_payslip_calc.py` includes G2 public-holiday-rate tests + G18 quantity/unit tests.
  - `test_payslip_service.py` includes G4 recurring-allowance auto-attach + G21 reopen.
  - `test_termination.py` includes G16 future-leave reconciliation + G25 period selection (open/finalised/paid/missing branches).

- [ ] **E1a. `tests/unit/test_period_rolling.py`** (G5) — unit tests for `compute_next_period_dates` covering weekly/fortnightly/monthly + month-end clamps + leap years + weekend-pay-date roll-forward.

- [ ] **E1b. `tests/unit/test_payslip_audit_redaction.py`** (G12) — asserts every `write_audit_log(...)` call site in `app/modules/payslips/` constructs an `after_value` that excludes `gross_pay`, `net_pay`, raw `amount`, decrypted `ird_number`, decrypted `bank_account_number`, raw `paye`.

- [ ] **E2. Property test** `tests/property/test_payslip_invariants.py` — gross/net invariants; kiwisaver math; casual 8% never recurses; public_holiday_rate × hours contributes correctly to gross (G2); auto-attached allowance amount = quantity × unit_price (G18).

- [ ] **E3. PDF integration** — render sample, parse PDF, assert every Wages Protection + s130A field present + the masked bank account (G1) + the public-holiday band rate row (G2) + per-allowance quantity rendering (G18) + multi-page header/footer (G20).

- [ ] **E4. E2E** `scripts/test_staff_payslip_e2e.py` per R15. **Extended to cover all 8 real gaps + 4 minor:**
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

- [ ] **F1. Bump 1.16.0 → 1.17.0** across pyproject.toml + frontend/package.json + mobile/package.json.
- [ ] **F2. CHANGELOG `## [1.17.0]`** — payslips, allowances, KiwiSaver auto, casual 8%, termination payouts (s27), wage variance report, **G1–G25 closures (recurring allowances, public-holiday band, period rolling, period reopen, future-leave reconciliation, allowance quantity semantics, self-service payslips, audit redaction)**.
- [ ] **F3. STAFF-004** in ISSUE_TRACKER updated (bank format choice deferred to Phase 5).

## Pre-merge gate

Tick everything in source plan §12. Specifically:
- PDF includes every Wages Protection Act + s130A field (verified by parsing) + **masked bank account (G1) + public-holiday band rate (G2) + allowance quantity/unit display (G18) + multi-page header/footer (G20)**.
- Casual 8% line auto-attached and equals 8% of taxable earnings.
- KiwiSaver employee deducted, employer informational (not subtracted).
- Termination payout uses greater-of formula AND **first reconciles future-dated approved leave (G16)** AND **picks the right pay_period including auto-roll-on-missing (G6) + reopen-on-finalised (G25)**.
- Finalised payslip immutable (409 on PUT).
- IRD/bank decryption only inside pdf.render path.
- Bulk finalise handles partial failure via SAVEPOINT.
- Bulk emails route through send_email + DLQ.
- **Pay period reopen flow works (G21) — refuses paid; allows new drafts in reopened periods.**
- **Audit redaction enforced (G12) — payslip events never leak raw amounts or PII.**
- **Self-service `/staff/me/payslips` endpoints work (G9) — own data only, 404 on cross-staff access, payroll module-gated.**
- **Recurring allowances auto-attach on draft (G4) — admin can override per-draft, rule survives.**
- **`compute_next_period_dates` covers weekly/fortnightly/monthly + month-end clamps + weekend pay-date roll (G5).**
- **Cadence change is non-retroactive (G14).**
- **Print CSS produces clean A4 multi-page payslips (G20).**
- **Bulk-finalise SLO met for 50-staff org (G24).**

**G1–G25 closure ticks (added during gap analysis):**
- [ ] G1: PDF includes masked bank account string.
- [ ] G2: `public_holiday_rate` column persists; default = ordinary × 1.5; Hypothesis test passes.
- [ ] G4: `staff_recurring_allowances` table exists with RLS; auto-attach in `generate_for_period`; UI panel on Overview tab.
- [ ] G5: `compute_next_period_dates` algorithm spec'd + unit-tested for all three cadences.
- [ ] G6: termination synchronously rolls periods if none covers `:end_date`; audit row written.
- [ ] G9: three `/staff/me/payslips/*` endpoints + web + mobile screens; ownership-leak guard returns 404.
- [ ] G12: every payslip-related audit row excludes raw amounts and decrypted PII; lint test passes.
- [ ] G14: changing cadence does not retroactively rewrite existing periods; audit row written on change.
- [ ] G16: termination cancels future-dated approved leave first; restores hours; audits.
- [ ] G18: `payslip_allowances` has `quantity` + `unit` columns; auto-derivation per unit; PDF renders quantity correctly.
- [ ] G20: payslip.css spec'd with @page rules, page-break-inside avoid, running header/footer.
- [ ] G21: `POST /pay-periods/:id/reopen` works; respects open/finalised/paid states; existing payslips stay locked.
- [ ] G24: bulk-finalise SLO documented + tested.
- [ ] G25: termination final-payslip pay_period selection rule applied (open / reopen-finalised / 409-paid / auto-roll-if-missing).
