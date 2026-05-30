# Staff Management Phase 4 — Tasks

## Workstream A — Migrations

- [ ] **A1. `0209_payslip_schema.py`** — pay_periods, allowance_types (+ defaults seed), payslips, payslip_allowances, payslip_deductions, payslip_reimbursements, payslip_leave_lines. RLS + tenant_isolation on all. CHECK constraints. Idempotent.
  - Add `organisations.pay_period_cadence` + `pay_period_anchor_day`.
  - **Verify:** alembic upgrade head clean. `\d+ payslips` shows columns + RLS. `SELECT count(*) FROM allowance_types WHERE org_id=<test>` returns 6 defaults.

- [ ] **A2. `0210_payslip_indexes.py`** — 6 indexes via CONCURRENTLY.

## Workstream B — Backend

- [ ] **B1. ORM models** for all new tables.
- [ ] **B2. Pydantic schemas** with `{ items, total }` lists; payslip detail includes nested allowances/deductions/reimbursements/leave lines.
- [ ] **B3. `calc.py`** — wage math single source of truth.
  - **Verify:** Hypothesis property tests: gross >= sum(taxable allowances); net >= 0; kiwisaver_employer not subtracted from gross.
- [ ] **B4. `service.py`** — generate/finalise/void/email/bulk_finalise.
- [ ] **B5. `pdf.py`** — Jinja template + WeasyPrint via asyncio.to_thread.
  - **Verify:** integration test renders a sample payslip; PDF text contains tax_code, masked IRD, all hour bands, gross, all deductions including KiwiSaver employer, net, leave_taken, every accruing leave balance, YTD totals, anniversary date.
- [ ] **B6. `termination.py`** — s27 calc, final payslip.
  - **Verify:** unit test `s27_annual_leave_payout` returns greater of weekly vs 52-wk avg.
- [ ] **B7. Router** — all endpoints. Module-gated by `payroll`. Finalise endpoints reject 409 if already finalised.
- [ ] **B8. Refuse UPDATE/DELETE** on finalised payslips (service layer guard).
- [ ] **B9. Register router** in `app/main.py`.

## Workstream C — Scheduled tasks

- [ ] **C1. `roll_pay_periods` daily** — for each org with `payroll` enabled, ensure next 4 pay-periods exist.
- [ ] **C2. Update `update_adp_snapshots`** to use real payslip data (fallback to Phase 2 calc when no payslips).

## Workstream D — Frontend

- [ ] **D1. `PayRunPage.tsx`** — period selector, generate, table, bulk finalise, progress bar.
- [ ] **D2. `PayslipDetail.tsx`** — drawer/modal editor.
- [ ] **D3. `PayslipsTab.tsx`** (Staff Detail).
- [ ] **D4. `TerminationModal.tsx`** with payout preview.
- [ ] **D5. Settings pages** — PayPeriodsPage, AllowanceTypesPage.
- [ ] **D6. `WageVariancePage.tsx`** (Reports).
- [ ] **D7. Sidebar** — "Payroll" entry under People.
- [ ] **D8. PDF preview iframe** in PayslipDetail when finalised.
- [ ] **D9. All API consumption**: `?.` + `?? []` + AbortController; typed clients in `frontend/src/api/payslips.ts`.

## Workstream E — Tests

- [ ] **E1. Unit tests** — `tests/unit/test_payslip_calc.py`, `_service.py`, `_termination.py`, `_pdf.py`.
- [ ] **E2. Property test** — gross/net invariants; kiwisaver math; casual 8% never recurses.
- [ ] **E3. PDF integration** — render sample, parse PDF, assert every Wages Protection + s130A field present.
- [ ] **E4. E2E** `scripts/test_staff_payslip_e2e.py` per R15.

## Workstream F — Versioning + docs

- [ ] **F1. Bump 1.16.0 → 1.17.0** across pyproject.toml + frontend/package.json + mobile/package.json.
- [ ] **F2. CHANGELOG `## [1.17.0]`** — payslips, allowances, KiwiSaver auto, casual 8%, termination payouts (s27), wage variance report.
- [ ] **F3. STAFF-004** in ISSUE_TRACKER updated (bank format choice deferred to Phase 5).

## Pre-merge gate

Tick everything in source plan §12. Specifically:
- PDF includes every Wages Protection Act + s130A field (verified by parsing).
- Casual 8% line auto-attached and equals 8% of taxable earnings.
- KiwiSaver employee deducted, employer informational (not subtracted).
- Termination payout uses greater-of formula.
- Finalised payslip immutable (409 on PUT).
- IRD/bank decryption only inside pdf.render path.
- Bulk finalise handles partial failure via SAVEPOINT.
- Bulk emails route through send_email + DLQ.
