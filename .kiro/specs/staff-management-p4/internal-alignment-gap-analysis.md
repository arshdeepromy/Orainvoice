# Staff Management Phase 4 — Internal Spec Alignment Gap Analysis

Date: 2026-05-31
Reviewed: `requirements.md`, `design.md`, `tasks.md` (Phase 4) cross-checked for internal consistency between the three docs (post the prior `gap-analysis.md` N1-N20 fixes).

The G1-G25 closure tags and N1-N20 closure tags from prior reviews all stand. The findings below (P4-N21...P4-N32) are NEW alignment gaps where the three Phase 4 docs disagree with each other (not with code — that was the prior audit).

## Alignment gap tagging

Tagged `P4-N21+` to keep them distinct from prior `N1-N20` (code-vs-spec) and `G1-G25` (design-level) tags. Numbers continue from N20 since both audits are about Phase 4.

---

## REAL INTERNAL ALIGNMENT GAPS

### P4-N21. R10 Step 5 says `audit_logs` (plural); rest of spec says `audit_log` (singular)

**Where it bites:** requirements.md R10 step 5: *"Write `audit_logs` action='staff.terminated' with full breakdown JSON."*

**Reality:** R14 audit-logging requirement, design §4.5, design §11, and the prior N11 fix all standardised on `audit_log` (singular — verified at `app/modules/admin/models.py:318`). R10 step 5 is the lone straggler.

**Fix applied:**
- requirements.md R10 step 5 — `audit_logs` → `audit_log`.

### P4-N22. R10 Step 5 audit phrasing contradicts R14 redaction rule

**Where it bites:** R10 step 5: *"Write `audit_logs` action='staff.terminated' with **full breakdown JSON**."* But R14 explicitly says: *"`staff.terminated` → `{ staff_id, end_date, payout_summary: { annual_hours, alt_days, casual_8pct_remaining } }` — **counts only, no dollar amounts**."*

**Reality:** "Full breakdown JSON" would be interpreted by an implementer as "serialise the whole termination payload", which leaks the s27 payout dollars, alt-day RDP rate, casual 8% balance amount — exactly what R14 forbids. The two clauses contradict each other.

**Fix applied:**
- requirements.md R10 step 5 — replace "with full breakdown JSON" with "with the redacted `after_value` shape per R14 (`{ staff_id, end_date, payout_summary: { annual_hours, alt_days, casual_8pct_remaining } }` — counts only, no dollar amounts)".

### P4-N23. Wage Variance Report endpoint name disagrees: `wages-variance` vs `wage-variance`

**Where it bites:** requirements.md R12 says `/reports/wages-variance` (plural `wages`). Design §5 says `/api/v2/reports/wage-variance` (singular `wage`). Tasks D6 component is `WageVariancePage.tsx` (singular).

**Reality:** two of three docs use singular. The plural form is just R12. Pick one.

**Fix applied:**
- requirements.md R12.1 — `/reports/wages-variance` → `/api/v2/reports/wage-variance` (singular, matching design + tasks).

### P4-N24. R11 references a non-existent column `staff_pay_rates.last_change`

**Where it bites:** requirements.md R11.1: *"per Phase 1 R6 already implements the column; Phase 4 ensures the trigger fires when `staff_pay_rates.last_change > 12 months`."*

**Reality:** Phase 1 R6.3 adds `staff_members.last_pay_review_date` (date column on `staff_members`). The `staff_pay_rates` audit table uses `effective_from` for the date of each rate change (per Phase 1 R3.1), and there is no `last_change` column on it. The R6 banner counter in Phase 1 reads `last_pay_review_date < (now() - interval '12 months')`. P4-N24 is the typo `staff_pay_rates.last_change` — should be `staff_members.last_pay_review_date`.

**Fix applied:**
- requirements.md R11.1 — replaced `staff_pay_rates.last_change > 12 months` with `staff_members.last_pay_review_date < (now() - interval '12 months')` (matching Phase 1 R6.3).

### P4-N25. R7.2 PDF includes 4 YTD figures but `payslips` table stores only `gross_ytd`

**Where it bites:** R7.2 PDF content list: *"Year-to-date totals: gross, PAYE, KiwiSaver employee, KiwiSaver employer."* But R3.1 stores only `gross_ytd numeric(12,2)` on `payslips`. The other three YTD figures (PAYE, KiwiSaver employee, KiwiSaver employer) are not stored anywhere.

**Reality:** at PDF render time, the renderer must compute the three missing YTDs from `payslip_deductions` joined to `payslips` joined to `pay_periods` filtered by `staff_id` and `pay_periods.pay_date BETWEEN tax_year_start AND this_pay.pay_date AND status='finalised'`. The spec never specifies this derivation — an implementer might:
- Quietly stub them out as zero in the PDF.
- Add three more `*_ytd` columns to `payslips` (over-engineered but workable).
- Compute on the fly each render.

The third option matches the N16 rule for `gross_ytd` (recompute every draft, never cache forever) so it's the natural choice.

**Fix applied:**
- requirements.md R7.2 — added a sub-bullet: *"YTD figures are computed at PDF-render time from `payslip_deductions` joined to `payslips` × `pay_periods.pay_date BETWEEN :tax_year_start AND :this_pay_date AND status='finalised'` (same tax-year window as `gross_ytd` per N16). Specifically: `paye_ytd = SUM(amount) WHERE kind='paye'`; `kiwisaver_employee_ytd = SUM(amount) WHERE kind='kiwisaver_employee'`; `kiwisaver_employer_ytd = SUM(amount) WHERE kind='kiwisaver_employer'`. Only `gross_ytd` is stored on the `payslips` row (per R3.1)."*
- design.md §4.4 PDF renderer — added a "YTD aggregation helper" docstring noting the three runtime-computed figures.
- tasks.md B5 verify step — added "PDF YTD figures: query `payslip_deductions` for the tax year and assert the rendered PAYE/KiwiSaver-employee/KiwiSaver-employer YTD numbers match the SUM(amount) per kind."

### P4-N26. R3.4 forbids UPDATE on finalised payslips but R8 `emailed_at` update is an UPDATE on finalised

**Where it bites:** R3.4: *"Refuse UPDATE/DELETE on `payslips WHERE status='finalised'` at the application level (raise 409 conflict). Only voiding (writing a new compensating payslip) is allowed."* But R8.3: *"Updates `payslips.emailed_at`."* — and emailing is only allowed on finalised payslips (R8.2).

**Reality:** the email-payslip endpoint is the ONE legitimate UPDATE path on a finalised payslip. The spec lacks an explicit carve-out, so a future implementer who literally enforces R3.4 at the SQL level (e.g., a row-level trigger or a guard on the `update_payslip` service path) would block emailing too.

**Fix applied:**
- requirements.md R3.4 — appended: *"The single allowed mutation on a finalised payslip is `emailed_at = now()` via the email-payslip endpoint (R8.3). All other column updates remain refused. The service-layer guard MUST be a column-allowlist check rather than a blanket `WHERE status='finalised' RAISE 409`."*
- tasks.md B8 — added: *"The guard is a column-allowlist: only `emailed_at` may be updated on a finalised payslip (per R3.4 + R8.3). All other columns refused."*

### P4-N27. Tasks Workstream B numbering is out of order (B10 listed AFTER B11)

**Where it bites:** tasks.md Workstream B physical order: B0, B1, B2, B3, B4, B4a, B5, B5a, B5b, B6, B7, B8, B9, B11, B10.

**Reality:** the renumbering happened during the prior gap analysis when B11 (module-middleware path entries) was added late. B10 (audit redaction enforcement) was already in place but ended up after B11 because the new bullet was inserted between B9 and B10. Cosmetic but confusing — a reviewer scanning workstream B in order would see B11 before B10.

**Fix applied:**
- tasks.md — reorder the two so B10 precedes B11. Both bullets keep their existing numbers; only the physical order in the file changes.

### P4-N28. R3.1 omits the `UNIQUE (staff_id, pay_period_id)` constraint that design §3.1 + tasks A1 include

**Where it bites:** requirements.md R3.1 column list (the `payslips` table) doesn't mention any UNIQUE constraint. Design §3.1 SQL has `UNIQUE (staff_id, pay_period_id)`. Tasks A1 doesn't explicitly call it out either.

**Reality:** the unique constraint is essential — without it, `generate_for_period` could insert two drafts for the same staff in the same period (e.g., admin clicks "Generate drafts" twice, race conditions during bulk generation). The design has it; requirements doesn't. The migration-implementer reading only requirements would miss it.

**Fix applied:**
- requirements.md R3.1 — added a final bullet: *"Unique constraint on `(staff_id, pay_period_id)` so `generate_for_period` is naturally idempotent — re-running on existing drafts UPDATEs them rather than inserting duplicates (per the design §4.2 docstring)."*
- tasks.md A1 — added: *"`payslips` includes `UNIQUE (staff_id, pay_period_id)` — supports `generate_for_period` idempotency."*

### P4-N29. R3.1 NOT NULL columns disagree with design.md §3.1 (DEFAULT 0 vs NOT NULL only)

**Where it bites:** requirements.md R3.1 lists `gross_pay numeric(12,2) NOT NULL` and `net_pay numeric(12,2) NOT NULL` (no defaults). Design §3.1 SQL has `gross_pay numeric(12,2) NOT NULL DEFAULT 0` and `net_pay numeric(12,2) NOT NULL DEFAULT 0`.

**Reality:** without `DEFAULT 0`, `INSERT INTO payslips (...)` from `generate_for_period` would have to compute gross/net before the row exists, or include them explicitly in every INSERT. The design's `DEFAULT 0` allows draft creation with computed-later values. Requirements should match.

**Fix applied:**
- requirements.md R3.1 — `gross_pay numeric(12,2) NOT NULL DEFAULT 0`, `net_pay numeric(12,2) NOT NULL DEFAULT 0`. Aligned to design.

### P4-N30. R10 Step 4 + Step 4a casual-8% reference two different things conflated

**Where it bites:** R10 Step 4: *"Generate the final payslip in the chosen period with the s27 + alt-day + **casual-8% breakdown lines**"* — refers to the casual-8% remainder true-up (`(YTD gross × 0.08) - sum(8% lines paid YTD)` per Step 2). Step 4a (N15): *"The casual 8% line (R5) ALSO skips the lump-sum portion."* — refers to the IN-PERIOD R5 casual-8% accrual that fires on every casual payslip.

**Reality:** these are TWO different casual-8% concepts:
- **In-period 8% (R5):** for casuals, every payslip auto-attaches an allowance line `casual_8pct_holiday = gross_taxable_earnings × 0.08`. This is wages-as-you-go.
- **Termination remainder (R10 Step 2 + Step 4):** at termination, compute `(YTD gross × 0.08) - sum(8% lines paid YTD)` to true-up any under-payment. This is a one-time settlement.

The R10 wording fuses them. Step 4 mentions "casual-8% breakdown lines" (the remainder), then Step 4a says "the casual 8% line (R5)" — referring back to R5's per-period accrual, but qualifying it with "skips the lump-sum portion" which only makes sense for the per-period accrual. An implementer reading R10 cold would not know which 8% concept Step 4a is qualifying.

**Fix applied:**
- requirements.md R10 Step 4 — qualified the bullet: *"Generate the final payslip in the chosen period with the **s27 lump-sum, alt-day payout, and casual-8% remainder true-up** (per Step 2's `(YTD gross × 0.08) - sum(8% lines paid YTD)` calc) as breakdown lines. The standard R5 in-period 8% accrual STILL fires for the current pay period's wages-only earnings (it's just an additional allowance line, not the same as the remainder true-up)."*
- requirements.md R10 Step 4a — clarified scope: *"When generating the termination payslip, KiwiSaver employee + employer auto-deductions are calculated on the **non-lump-sum portion only** — i.e., the current-period gross MINUS (s27 lump-sum + alt-day payout + casual-8% remainder true-up). The R5 in-period 8% accrual on the current pay period's wages DOES count toward the KiwiSaver basis (it's regular pay, not extra-pay). The lump-sum components are extra-pay for PAYE purposes per IRD ESCT/PAYE-on-extra-pay rules; admin still enters the PAYE figure manually."*

### P4-N31. Design §6.7 says "Phase 1 reserved the slot" but Phase 1 spec does not actually reserve it

**Where it bites:** design.md §6.7: *"Lives under a collapsible "Recurring allowances" section on the Phase 1 Overview tab. **Phase 4 ships this surface; Phase 1 reserved the slot.**"*

**Reality:** Phase 1 R1.1 lists tabs Overview/Roster/Documents only. Phase 1 design §6.2 enumerates the Overview tab's 6 sections (Personal info, Employment, Tax & Pay, Schedule, Clock-in & roster delivery, Skills) — no recurring-allowances section reserved. The "Phase 1 reserved the slot" claim is wishful thinking; Phase 4 is actually ADDING a new collapsible section to Phase 1's Overview tab, not occupying a pre-allocated slot.

**Fix applied:**
- design.md §6.7 — rewrote the claim: *"Lives under a collapsible "Recurring allowances" section ADDED to the Phase 1 Overview tab. Phase 4 ships this surface as a new collapsible section appended below the existing Tax & Pay panel (where Phase 1's Pay Rate History panel sits). Phase 1 did not pre-allocate the slot — Phase 4 is the integration point."*
- tasks.md D10 — clarified: *"The new collapsible section is appended to the Phase 1 Overview tab (not a pre-allocated slot). Implementer touches `frontend/src/pages/staff/tabs/OverviewTab.tsx` to add the new section import + render."*

### P4-N32. Tasks B10 audit-redaction lint test set is incomplete — doesn't cover `staff.terminated`-specific keys

**Where it bites:** tasks.md B10: *"a unit test `tests/unit/test_payslip_audit_redaction.py` parses every `write_audit_log(...)` call site in the payslips module and asserts the after_value dict literal contains NONE of `{'gross_pay', 'net_pay', 'amount', 'ird_number', 'bank_account_number', 'paye'}` keys."*

**Reality:** R14 audit redaction rule applies to FIVE event types, not just payslip events:
- `payslip.generated`, `payslip.finalised`, `payslip.emailed`, `payslip.voided` — covered by the existing key set.
- **`staff.terminated`** — should be `{ staff_id, end_date, payout_summary: { annual_hours, alt_days, casual_8pct_remaining } }` (counts only). The lint test's forbidden-key set doesn't include the dollar-amount keys that a naïve implementer might use (e.g., `annual_payout_dollars`, `s27_lump_sum`, `alt_day_total_dollars`, `casual_8pct_remainder_dollars`).

If the lint only checks for `{'gross_pay', 'net_pay', 'amount', ...}`, an implementer could write `after_value={..., 's27_lump_sum': Decimal('6912.00')}` and the test would pass.

**Fix applied:**
- tasks.md B10 — extended the forbidden-keys set: *"The forbidden-key set is `{'gross_pay', 'net_pay', 'amount', 'ird_number', 'bank_account_number', 'paye', 's27_lump_sum', 'annual_payout_dollars', 'alt_day_total_dollars', 'casual_8pct_remainder_dollars', 'recipient_email'}` — covers payslip events AND `staff.terminated`. Plus a positive assertion: `staff.terminated` after_value MUST contain `payout_summary` (a dict) with keys `annual_hours`, `alt_days`, `casual_8pct_remaining` (per R14)."*
- tasks.md E1b — same expanded forbidden-key set.

---

## ALSO VERIFIED (no fix needed)

These were checked across the three docs and ARE consistent:

- ✅ R3.1 column list matches design §3.1 SQL (modulo P4-N28, P4-N29 fixes above).
- ✅ R3.5 `staff_recurring_allowances` schema matches design §3.1 SQL.
- ✅ R8a self-service endpoints, ownership rule, 404-not-403, payroll module gate all match between requirements + design + tasks (post N1-N20 fixes).
- ✅ R10 Step 0-3 termination flow matches design §4.3 termination service docstring.
- ✅ R14 audit-event list matches design §4.5 redaction rules (modulo P4-N22, P4-N32 fixes above).
- ✅ G1-G25 closure tags from prior reviews remain valid.
- ✅ N1-N20 closure tags from prior reviews remain valid.
- ✅ Tasks A1, A2 column/index lists match design §3.1, §3.2.
- ✅ Tasks B0 preflight column set matches the "Hard prerequisites" list at the top of requirements.md.
- ✅ All `pdf_file_key` references aligned (no stragglers — verified post N3 fix).
- ✅ All `audit_log` references singular (modulo P4-N21 fix above).
- ✅ All template paths use `app/modules/payslips/templates/` (no `app/templates/` references — N9 fix held).
- ✅ Module-disabled response is HTTP 403 throughout (N8 fix held).

---

## Summary of fixes applied

| # | Gap | File touched | Section |
|---|---|---|---|
| P4-N21 | R10 step 5 `audit_logs` plural | requirements.md | R10 step 5 |
| P4-N22 | R10 step 5 "full breakdown JSON" leaks dollar amounts | requirements.md | R10 step 5 |
| P4-N23 | Wage variance endpoint plural vs singular | requirements.md | R12 |
| P4-N24 | R11 references non-existent `staff_pay_rates.last_change` | requirements.md | R11 |
| P4-N25 | R7.2 lists 4 YTD figures but only `gross_ytd` is stored | requirements.md, design.md, tasks.md | R7.2, §4.4, B5 |
| P4-N26 | R3.4 finalised-immutability missing `emailed_at` carve-out | requirements.md, tasks.md | R3.4, B8 |
| P4-N27 | tasks.md Workstream B order wrong (B10 after B11) | tasks.md | Workstream B |
| P4-N28 | R3.1 omits `UNIQUE (staff_id, pay_period_id)` | requirements.md, tasks.md | R3.1, A1 |
| P4-N29 | R3.1 vs design §3.1 NOT NULL/DEFAULT mismatch | requirements.md | R3.1 |
| P4-N30 | R10 Step 4/4a fuses two casual-8% concepts | requirements.md | R10 step 4, 4a |
| P4-N31 | Design §6.7 wrongly claims Phase 1 "reserved the slot" | design.md, tasks.md | §6.7, D10 |
| P4-N32 | B10 audit-redaction lint set incomplete | tasks.md | B10, E1b |

All fixes applied in this commit alongside this gap analysis.

## Recommendation

Phase 4 is now well-aligned across its three docs. The G1-G25 design-level closures and N1-N20 code-vs-spec closures from prior reviews remain valid. The 12 P4-N# tags from this internal-alignment audit are precision issues (typos, contradictory wording, missing carve-outs, ordering) — none affect the architecture or feature scope. The most substantive ones are P4-N22 (R10 audit phrasing leaking PII), P4-N25 (PDF YTD derivation rule), and P4-N32 (audit-redaction lint coverage gap). Each has a concrete fix applied.

Phase 4 implementation can proceed as soon as P1-P3 land.
