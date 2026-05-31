# Staff Management Phase 4 — Spec vs Code Gap Analysis

Date: 2026-05-31
Reviewed against: workspace HEAD (alembic at 0202, app version 1.13.0).
Spec scope: P4 = Payslips + Allowances + Termination Payouts (Wages Protection Act + Holidays Act s130A + s27).

## Executive summary

The Phase 4 spec is design-complete for its own surface (the `payslips` module) but assumes a long chain of Phase 1, 2, 3 building blocks that **do not exist in code yet**. None of `staff-management-p1` through `staff-management-p5` have shipped: no migrations 0203–0208, no `app/modules/payslips/` or `app/modules/time_clock/`, no `staff_pay_rates` / `leave_*` / `time_clock_*` / `staff_recurring_allowances` tables, and the `staff_members` table is still the original 16-column shape from migration 0036 (no `employment_type`, `tax_code`, `kiwisaver_*`, `student_loan`, `employment_start_date`, `employment_end_date`, `standard_hours_per_week`, `bank_account_number_encrypted`, `ird_number_encrypted`, `average_daily_pay_snapshot`, `self_service_clock_enabled`, `residency_type`).

In addition, there are five spec-internal inconsistencies and assumptions that will fail at implementation time even after P1–P3 land. Each is enumerated below with a concrete fix that has been applied to `requirements.md`, `design.md`, and `tasks.md`.

The 14 design-level gap-closure tags (G1, G2, G4, G5, G6, G9, G12, G14, G16, G18, G20, G21, G24, G25) all hold up — those are tracked correctly. The gaps below are NEW issues uncovered by checking the spec against the actual codebase.

## Verification methodology

For every external reference in `design.md` §11 ("Verified-against-code addendum") and every cross-phase prerequisite in `requirements.md`, I:

1. Located the cited file/symbol in the workspace.
2. Confirmed the API shape the spec relies on.
3. Flagged any reference that pointed to code that doesn't exist, an outdated path, or an assumption about a column/table that wasn't present.

I also re-read `requirements.md` end-to-end against `design.md` to find internal contradictions.

---

## REAL GAPS (code or spec-internal mismatches)

### N1. Spec assumes `users.staff_id` reverse-link; the actual link is `staff_members.user_id`

**Where it bites:** R8a (G9) self-service endpoints and the `staff_id_from_user(current_user.id)` resolution rule.

**Spec says (R8a.2 + design §5):**

> "resolve `staff_id` from `current_user.id` via the existing `users.staff_id` (or equivalent) link"
> "Server-side ownership is checked at every endpoint via `payslip.staff_id == staff_id_from_user(current_user.id)`"

**Reality (`app/modules/auth/models.py` + `app/modules/staff/models.py`):** the `users` table has NO `staff_id` column. The link is the other way around — `staff_members.user_id` is a nullable column referencing `users.id`. Multiple staff records could in theory point to the same user (duplicates would have to be guarded explicitly). There is no DB-level UNIQUE on `staff_members.user_id`.

**Fix applied:**

- Added a precondition in R8a: a UNIQUE INDEX `ux_staff_members_user_id` (partial: `WHERE user_id IS NOT NULL`) must be created in migration `0209_payslip_schema.py` so the staff↔user lookup is deterministic.
- Documented the resolver as `SELECT id FROM staff_members WHERE user_id = :current_user_id AND is_active=true` (active filter prevents terminated staff from continuing to see their old payslips after their `is_active` flips false — but they should still see them per Wages Protection Act s4 record-retention rules; see N2).
- Updated design §5 to reference the new index + resolver, not a fictional `users.staff_id` column.

### N2. Self-service ownership filter contradicts staff-record-retention obligations

**Where it bites:** R8a (G9). Once a staff member terminates, their `is_active` is set to `false` (R10 step 5). If the resolver requires `is_active=true`, terminated staff lose access to their own historical payslips immediately — but the Wages Protection Act 1983 s4 + Holidays Act 2003 s81 require the **employer** to keep wage records for 6 years; nothing requires us to grant the ex-employee a portal, but our spec implicitly does (R8a says "see my own past payslips").

**Fix applied:** explicit clarification in R8a that the ownership check is `staff_members.user_id = :current_user_id` regardless of `is_active`, but module-gate still applies (so if the org disables payroll, no one sees them). Added the matching note to the audit-log redaction in R14 — terminated-staff self-service reads do not emit audit rows (read-only PII access by the data subject).

### N3. `app/modules/uploads/` does NOT expose a `pdf_upload_id` model — design §11 misclaims it

**Where it bites:** R3.1 (`payslips.pdf_upload_id uuid`), §4.4 PDF storage, §11 ("PDFs stored under category `payslips/` per the existing `_store(category=...)` helper").

**Reality:** `app/modules/uploads/router.py` exposes a `_store(content, filename, org_id, cat, db)` helper, but it is **module-private** and **does not return a UUID** — it returns `{"file_key": ..., "file_name": ..., "file_size": ...}`. There is no `uploads` table; there is no canonical `Upload` model. Other modules (job_cards, quotes, invoices) each define their own `*_attachments` table and store the encrypted blob's `file_key` (a string path) on it. There is no global `pdf_upload_id` UUID convention.

**Fix applied:**

- Renamed `payslips.pdf_upload_id uuid` to **`pdf_file_key text`** in R3.1 + design §3.1 — matching the convention used by `invoice_attachments`, `quote_attachments`, `job_card_attachments`.
- Added a new design §4.4 sub-section that documents the storage path: payroll PDFs go to `UPLOAD_BASE / "payslips" / org_id / payslip_id / <uuid>.pdf` via a new `app/modules/payslips/pdf_storage.py::store_payslip_pdf(...)` helper modelled on `app/modules/job_cards/attachment_service.py::_store_file`. The helper returns the `file_key` string. Existing `envelope_encrypt` + zlib compression flag conventions are reused.
- Updated all four `payslip.*` audit row schemas in R14 + §4.5 to drop `pdf_upload_id` and emit `pdf_file_key` instead (still PII-safe — the key is a path, not the encrypted bytes).
- Added a B5b task: write `pdf_storage.py` with download helper that validates the org_id prefix on the file_key (mirroring `download_attachment` in `app/modules/quotes/attachment_service.py`) so a path-traversal or cross-tenant access can't leak a payslip PDF.

### N4. WeasyPrint pattern reference cited at the wrong line number

**Where it bites:** §1 Architecture overview ("`app/modules/invoices/service.py:4446`") and §11 Verified-against-code addendum.

**Reality:** the actual WeasyPrint async pattern in `app/modules/invoices/service.py` is at **lines 4449–4452** (off by 3). Same pattern also exists in `app/modules/quotes/service.py:1162-1165`, `app/modules/inventory/service.py:701-704`, `app/modules/vehicles/report_service.py:283-286` — four canonical reference points, not one.

**Fix applied:** updated §1 and §11 to point at `app/modules/quotes/service.py:1162` as the most-similar pattern (single template, no attachments), and listed the other three as additional examples. Also updated B5 verify step to cite the real line numbers.

### N5. `organisations.overtime_handling` is assumed by Phase 4 but is owned by Phase 2

**Where it bites:** Phase 4 calc + payslip generation reads `organisations.overtime_handling` to decide whether overtime hours flow into the cash band or into a TOIL ledger. Phase 4 design references Phase 2 R-something for this, but the actual location is Phase 2 migration `0205_leave_schema.py` which adds `organisations.overtime_handling` as a typed column (per `staff-management-p2/tasks.md` A1). However, Phase 3 `tasks.md` A1 says the same field lives in `organisations.settings` JSONB with key `'overtime_handling'`. The two phases disagree.

**Fix applied:** added a precondition statement in the Phase 4 requirements R4 ("Pre-condition") that resolves the disagreement — Phase 4 reads the field from wherever Phase 2 ships it, and the Phase 4 `compute_payslip` uses an `_org_setting('overtime_handling', default='pay_cash')` helper that tries the typed column first, then falls back to `settings JSONB`. This decouples Phase 4 from Phase 2's column-vs-JSONB choice. A small note was added to design §11 acknowledging the resolution.

### N6. No `users.staff_id` UNIQUE means a single user could have multiple `staff_members` rows

**Where it bites:** R8a self-service. If org_admin creates two staff records that both link to the same user (e.g. by accident, or because the same person works at two branches via two staff rows), `GET /staff/me/payslips` returns payslips for whichever row the resolver picks first — non-deterministic.

**Fix applied:** see N1 — the same `ux_staff_members_user_id` partial-unique index covers this. Migration 0209 takes the index out of the way before any `staff_recurring_allowances` row could create a divergence. Verify step in A1 added: "no two staff_members rows share a user_id".

### N7. R10 (termination) reads `staff.standard_hours_per_week` but Phase 1 has not been verified to add it

**Where it bites:** s27 calc (R10 step 2 + design `s27_annual_leave_payout(...)`).

**Reality:** the spec lists `standard_hours_per_week` as one of the 23 columns Phase 1 adds (`staff-management-p1/tasks.md` A1) but the verify step there only spot-checks 3 of the 23 columns (`residency_type`, plus generic "23 new columns" count). If P1 ships with all-but-one columns, P4 silently breaks at termination time.

**Fix applied:** added a hard prerequisite check task **B0** to Phase 4: run a startup-time assertion `app/modules/payslips/_preflight.py::assert_phase1_columns_present(...)` that SELECTs `column_name FROM information_schema.columns WHERE table_name='staff_members'` and verifies every column the P4 calc depends on. Fail-fast with a clear error message naming the missing column. This is light-weight and runs once at app startup.

### N8. Module-disabled HTTP code: spec says 404 `not_enabled`, middleware returns 403

**Where it bites:** R8a says "when disabled, return 404 `not_enabled`"; design §5 repeats it. But `app/middleware/modules.py` (the canonical middleware) returns **HTTP 403** with body `{"detail": "Module 'payroll' is not enabled for your organisation.", "module": "payroll"}` — and the entire codebase uses 403 consistently for this case.

**Fix applied:** updated R8a and design §5 to align with the existing 403 response. The middleware does the gating for any path matching `/api/v2/staff` (already in `MODULE_ENDPOINT_MAP`), so we DON'T need to add per-route guards on the new self-service endpoints — they will be 403'd automatically when `staff` module is disabled. The `payroll` module gate, however, is NOT yet in `MODULE_ENDPOINT_MAP` — added a B11 task to add `"/api/v2/pay-periods": "payroll"`, `"/api/v2/payslips": "payroll"`, `"/api/v2/allowance-types": "payroll"` entries. Self-service `/api/v2/staff/me/payslips` paths will inherit the existing `staff` gate AND need a service-layer payroll-module check (because the path prefix is `/api/v2/staff`, not `/api/v2/payslips`).

### N9. Spec references `app/templates/payslips/` but no `app/templates/` directory exists

**Where it bites:** §3.1 design, R7.5, B5a, design §6.9 — all reference `app/templates/payslips/payslip.html` and `app/templates/payslips/payslip.css`.

**Reality:** there is no `app/templates/` directory. Existing PDF renderers each ship their template alongside their service.py — invoice PDF templates live under `app/modules/invoices/templates/`, quote templates under `app/modules/quotes/templates/`, etc.

**Fix applied:** updated all template paths to `app/modules/payslips/templates/payslip.html` and `app/modules/payslips/templates/payslip.css`. This matches the existing per-module template convention. Updated B5, B5a, and design §6.9.

### N10. Spec claims daily `roll_pay_periods` is registered in `app/tasks/scheduled.py` but doesn't show how

**Where it bites:** §1 Architecture overview, R1.4, C1 task.

**Reality:** `app/tasks/scheduled.py` is a flat module of plain async functions — there is no central scheduler dispatcher in the codebase that automatically calls them daily. The scheduler is something else (haven't located a single canonical dispatcher; many tasks are called from various surfaces). This means C1's "daily scheduled task" needs explicit wiring.

**Fix applied:** clarified in C1 that the wiring lives in whatever scheduler-tick path runs the existing `check_overdue_invoices_task` etc. Added a sub-task C1a: "find the scheduler-tick dispatcher (currently invoked from `app/main.py` on a cron-like loop OR an external systemd timer — to be determined during implementation) and register `roll_pay_periods_task` alongside `check_overdue_invoices_task` in the same dispatch list. Verify by running the dispatcher locally and watching the task fire on the next tick." This unblocks the implementation without pretending the wiring is trivial.

### N11. `audit_log` table column is `before_value` / `after_value` (singular), not `before_values` / `after_values`

**Where it bites:** R14 audit redaction examples, design §4.5.

**Reality (`app/core/audit.py`):** the `write_audit_log` helper accepts `before_value` and `after_value` (singular). All examples in the spec already use the singular form, so this is consistent — but I want to call it out as **verified, not gap**. Added an explicit "Verified" line in §11 to lock the convention so a future edit doesn't accidentally pluralise it.

### N12. Spec assumes `payroll` module slug exists in `module_registry`

**Where it bites:** R1.4 ("for every org with `payroll` module enabled"), R4, R8a (module-gated by `payroll`).

**Reality:** Phase 1 task A1 inserts the `payroll` module into `module_registry` — but that migration (`0203_staff_phase1_schema.py`) doesn't exist yet. If P4 ships before P1, `is_module_enabled('payroll', ...)` returns `false` for every org and the entire P4 surface is invisible.

**Fix applied:** added a hard prerequisite statement at the top of `requirements.md`: **"P4 cannot be deployed until P1 ships migration 0203 with the `payroll` module_registry insert. The pre-merge gate now includes `SELECT 1 FROM module_registry WHERE slug='payroll'` returning a row."** Added a matching item to the pre-merge gate at the bottom of `tasks.md`.

### N13. Termination cancellation of future schedule_entries assumes `entry_type='leave'` exists

**Where it bites:** R10 step 1, B6 verify.

**Reality:** `app/modules/scheduling_v2/models.py` line 19 lists `ENTRY_TYPES = ["job", "booking", "break", "other", "leave"]` and `app/modules/scheduling_v2/schemas.py` repeats the pattern. ✅ verified — no fix needed. Added an explicit "Verified" line in §11.

### N14. PDF rendering audit — Bank account decryption pattern needs a concrete `EncryptedString` reference

**Where it bites:** R3.1 (bank-account encrypted column on `staff_members`), R7.2 (mask `**-****-****NN-**`), §10 Security.

**Reality:** there are two encryption patterns in the codebase:
- `EncryptedString` SQLAlchemy `TypeDecorator` (in `app/core/encrypted_field.py`) — encrypts at column level transparently.
- Manual `envelope_encrypt(...)` + `envelope_decrypt_str(...)` helpers — used by IRD module, file uploads.

Phase 1 doesn't specify which pattern to use for `staff_members.bank_account_number_encrypted` and `ird_number_encrypted`. The existing IRD module uses the manual pattern (encrypts on write, decrypts on read in service code). The platform_settings module uses `envelope_encrypt`. There's no `EncryptedString` consumer found in active modules.

**Fix applied:** added a precondition statement in design §10 — "Phase 1 must store `bank_account_number_encrypted` and `ird_number_encrypted` as `bytea` columns encrypted via `app.core.encryption.envelope_encrypt(...)` (consistent with IRD module). Phase 4 PDF rendering decrypts via `envelope_decrypt_str(...)` only inside `pdf.render_pdf` per existing PII-safety policy." This locks in the convention rather than letting P1 + P4 disagree.

### N15. R10 step 5 leaves `kiwisaver_employer` ambiguous on a termination payslip

**Where it bites:** R6 KiwiSaver auto-calc + R10 step 4 (final draft creation).

The spec is clear that `kiwisaver_employer` is informational and not subtracted from gross — but a termination payslip combines:
- normal current-period earnings (KiwiSaver should auto-add)
- s27 lump-sum (KiwiSaver does NOT apply to s27 payouts per IRD guidance — extra pay rules)

The spec doesn't distinguish between the two, so the auto-calc would over-deduct KiwiSaver from the s27 portion.

**Fix applied:** added explicit text in R10 step 4: "When generating the termination payslip, KiwiSaver employee + employer are calculated on the **non-s27 portion** only (current-period gross minus the s27 lump-sum). The s27 lump-sum is treated as an extra-pay component for PAYE purposes per IRD ESCT/PAYE on extra pay rules — admin still enters PAYE manually but the casual 8% line and KiwiSaver auto-attach skip the lump-sum." Added a B6 verify check.

### N16. `gross_ytd` cache is computed from finalised payslips but there's no rule for fiscal-year reset

**Where it bites:** R3.1 column + §9 performance, "`gross_ytd` cached on the row".

**Reality:** "Year to date" in NZ payroll runs 1 April → 31 March (tax year). There's no spec rule for when `gross_ytd` resets. If a draft is generated on 5 April for a period ending 28 March, does `gross_ytd` include or exclude the just-ended tax year?

**Fix applied:** added explicit rule in R3.1: "`gross_ytd` = sum of `payslips.gross_pay` WHERE `pay_periods.pay_date >= '<current_tax_year_start>' AND pay_periods.pay_date <= :this_pay_date AND status='finalised'`. Tax year is 1 April → 31 March, derived per-org from `organisations.income_tax_year_end` (already exists). The value is recomputed every time a draft is generated — not cached forever — to avoid drift across tax-year boundaries." Updated calc.py docstring + B3 verify step.

### N17. Spec doesn't cover what happens when an admin generates a draft for a casual employee who has zero approved hours

**Where it bites:** R5 casual 8%.

**Reality:** the spec says "WHEN generating a payslip for a casual employee THE SYSTEM SHALL automatically attach an allowance line ... `amount = gross_taxable_earnings × 0.08`". If the casual has no approved timesheet hours and no manual allowances, gross is $0, casual_8pct line is $0 → adds a zero line to the PDF. Cosmetic but ugly, and arguably wrong (the 8% line shouldn't appear at all if there's nothing to pay holiday on).

**Fix applied:** added a clause in R5: "If `gross_taxable_earnings == 0` (no approved hours, no taxable allowances) the casual 8% line is OMITTED from the payslip rather than attached at $0.00." Updated `compute_payslip` docstring + property test invariant.

### N18. Spec doesn't say what happens when a staff member is paid via direct deposit but bank account is missing on the row

**Where it bites:** R7.2 PDF rendering (masked bank account).

**Reality:** if `staff.bank_account_number_encrypted IS NULL` (e.g. cash-paid casual, or new staff whose bank-account is pending), the PDF would either crash on decrypt or print `**-****-****NN-**` with placeholder digits.

**Fix applied:** added a clause in R7.2: "When `bank_account_number_encrypted IS NULL`, the PDF renders the literal text `Cash payment / no bank account on file` in place of the masked account string. Audit logs MUST NOT note this fact (it's already implicit in the data state and reading the audit row to learn it would be a circular leak)."

### N19. Termination workflow doesn't lock concurrent `terminate` requests for the same staff

**Where it bites:** R10 — two admins simultaneously POSTing to `/staff/:id/terminate` could double-pay s27.

**Reality:** the spec has the entire termination wrapped in a single DB transaction (good) but doesn't explicitly take an advisory lock. Two concurrent transactions could each: SELECT remaining-balance → write leave_ledger → write payslip → COMMIT. PostgreSQL row-level locks on `staff_members` aren't taken implicitly during these reads.

**Fix applied:** added "Step 0" to R10: "Acquire a row-level lock with `SELECT 1 FROM staff_members WHERE id=:id FOR UPDATE` at the start of the transaction. The second concurrent request will block until the first commits, then sees `is_active=false` and returns 409 `already_terminated`."

### N20. The `_resolve_allowance_quantity` shift-counting query is under-specified

**Where it bites:** §4.2 helper docstring + R4.6 unit='shift'.

**Reality:** the helper says "`quantity = count_of_approved_shifts(staff_id, pay_period)` (drawn from `timesheet_approvals`-linked `time_clock_entries` joined to `schedule_entries` where `entry_type IN ('job','booking','other')`)". But:
- A shift could have multiple `time_clock_entries` (clock_in then break_in then break_out then clock_out — that's 4 entries for 1 shift).
- A `schedule_entries` row could have NO matching `time_clock_entries` (admin-entered; no kiosk clock).
- A `time_clock_entries` row might NOT be linked to any schedule_entry (free-form clock-in with no scheduled shift).

**Fix applied:** rewrote the helper rule in §4.2: "A shift = one `schedule_entries` row WHERE `start_time` falls inside `[period.start_date, period.end_date+1day]` AND `staff_id=:s` AND `entry_type IN ('job','booking','other')` AND `status='completed'` (matching at least one approved-timesheet `time_clock_entries` row via `scheduled_entry_id`). Count is `SELECT COUNT(DISTINCT schedule_entries.id) ...` to handle multi-entry shifts. Free-form (unscheduled) clocked-in time does NOT count toward shift-allowance — admins use a manual allowance line for those edge cases." Updated B3 + E1 verify steps.

---

## VERIFIED CLAIMS (no fix needed)

These were on the audit list but turn out to hold up against the codebase:

- ✅ `write_audit_log` signature in `app/core/audit.py` matches spec usage exactly.
- ✅ `send_email(..., dlq_task_name=...)` exists in `app/integrations/email_sender.py:1762` with correct signature; DLQ wiring goes through `app/core/dead_letter.py`.
- ✅ `schedule_entries.entry_type` enum includes `'leave'` (verified at `app/modules/scheduling_v2/models.py:19`).
- ✅ `module_registry` table exists; `ModuleRegistry` ORM model in `app/modules/module_management/models.py`. Phase 1 module-insert pattern is correct.
- ✅ `feature_flags` cache + middleware exists; spec's "mirror feature_flags rows" pattern lines up.
- ✅ `MODULE_ENDPOINT_MAP` in `app/middleware/modules.py` already gates `/api/v2/staff` to `staff` module — entries for new payroll paths still need to be added (see N8).
- ✅ The `_run_outside_tx` + `autocommit_block()` pattern from migration 0202 is the canonical CONCURRENT INDEX template — task A2 reference is correct.
- ✅ The encryption pattern: `envelope_encrypt(...)` + storing the bytes — consistent with IRD module's IRD-number storage. Confirmed in N14.
- ✅ `app/integrations/email_sender.py::send_email` returns a `SendResult` and writes a DLQ row when `dlq_task_name` is set — exactly what bulk payslip emailing needs.
- ✅ Staff list endpoint already paginated with `offset`/`limit` semantics (consistent with steering rule).

---

## Summary of fixes applied

| # | Gap | File touched | Section |
|---|---|---|---|
| N1 | `users.staff_id` doesn't exist; need partial-unique on `staff_members.user_id` | requirements.md, design.md, tasks.md | R8a, §5, A1 |
| N2 | Self-service must keep working post-termination | requirements.md, design.md | R8a, §10 |
| N3 | `pdf_upload_id` → `pdf_file_key`; storage helper details | requirements.md, design.md, tasks.md | R3.1, §3.1, §4.4, §4.5, R14, B5, B5b |
| N4 | Wrong WeasyPrint line numbers | design.md | §1, §11 |
| N5 | `overtime_handling` location ambiguity | requirements.md, design.md | R4 pre-condition, §11 |
| N6 | covered by N1 fix | — | — |
| N7 | Phase 1 column-presence preflight | tasks.md | new B0 |
| N8 | Module-gate is 403, not 404; add payroll path entries | requirements.md, design.md, tasks.md | R8a, §5, new B11 |
| N9 | Templates live under `app/modules/payslips/templates/` | requirements.md, design.md, tasks.md | R7, §3.1, §6.9, B5/B5a |
| N10 | scheduler dispatcher wiring caveat | tasks.md | C1, new C1a |
| N11 | audit column names verified | design.md | §11 |
| N12 | `payroll` module_registry insert is a hard P1 prereq | requirements.md, tasks.md | preamble, pre-merge gate |
| N13 | scheduling_v2 'leave' entry_type verified | design.md | §11 |
| N14 | encryption pattern locked to envelope_encrypt | design.md | §10 |
| N15 | KiwiSaver skips s27 portion on termination payslip | requirements.md, tasks.md | R10 step 4, B6 verify |
| N16 | YTD reset rule (NZ tax year) | requirements.md, tasks.md | R3.1, B3 verify |
| N17 | Casual 8% omits zero-amount line | requirements.md, tasks.md | R5, B3 property test |
| N18 | Cash-paid staff PDF text | requirements.md | R7.2 |
| N19 | Concurrent termination row lock | requirements.md | R10 step 0 |
| N20 | Shift-count query rule | design.md, tasks.md | §4.2, B3, E1 |

Each fix is a small, surgical edit to the existing spec — no architectural rewrites. The original 14 design-level gap-closure tags (G1–G25) all stand; these new findings (N1–N20) layer on top of them.

## Recommendation

Phase 4 cannot start implementation until P1 + P2 + P3 land. The spec is otherwise ready to go once these N1–N20 fixes are merged into `requirements.md` / `design.md` / `tasks.md`. I have applied all 20 fixes in the same commit as this gap analysis.


---

## Deferred verifications (E2/E3/E4 follow-up — 2026-05-31)

### E3. PDF integration test — runtime deferral

**File:** `tests/integration/test_payslip_pdf_integration.py`

**Status:** test file shipped; full execution deferred to a CI environment with WeasyPrint native dependencies (libpango, libcairo, libharfbuzz, libpangoft2) and a PDF parsing library (`pypdf` or `pdfminer.six`) installed.

**Reason for deferral:** the local dev environment used by the agent that landed Phase 4 does not have `weasyprint` (or a PDF parser) installed in the Python environment. The test file uses `pytest.importorskip('weasyprint')` at module load and a secondary skip when neither parser is present — so the test SKIPs rather than fails, and the deferred verification is recorded here.

**What CI will run:** `pytest tests/integration/test_payslip_pdf_integration.py -m integration -v` in the container that ships WeasyPrint + libpango. The test:

- builds an in-memory payslip with all P4 fields populated,
- calls `render_pdf(db, payslip_id)` to produce real PDF bytes,
- parses the bytes via `pypdf` (preferred) or `pdfminer.six`,
- asserts the extracted text contains `tax_code`, masked IRD, masked bank account `**-****-****NN-**`, all hour bands incl. `public_holiday_rate`, gross / deductions / net, leave-taken row, every accruing leave balance, YTD totals (gross / PAYE / KS-employee / KS-employer), anniversary date, and per-allowance `quantity × unit × amount` rendering,
- runs a separate "multi-page" assertion that renders 60 allowance rows and asserts the PDF has at least 2 pages with the running header (org name) appearing at least once per page (G20).

**Pre-merge gate:** the deferred run must pass before the Phase 4 release tag. The `@pytest.mark.integration` marker keeps the test out of the standard unit-test command.

**Local exercise (when libpango is installed):**

```bash
sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0
pip install weasyprint pypdf
PYTEST_RUNNING=1 pytest tests/integration/test_payslip_pdf_integration.py -m integration -v
```

### E4. E2E payslip script — runtime deferral

**File:** `scripts/test_staff_payslip_e2e.py`

**Status:** test file shipped; full execution deferred to a deploying engineer with a running dev backend at `localhost:8000` plus an admin JWT, a linked staff user JWT, and pre-seeded `STAFF_ID` + `ORG_ID` env vars.

**Reason for deferral:** the script is gated on `RUN_E2E=1` per the project convention so that CI does not auto-execute live-API tests. Without the env var, every test in the module is skipped at collection time via `pytestmark = pytest.mark.skipif(not _LIVE, reason=...)`. The agent that landed Phase 4 does not have a running backend in its environment.

**What the script covers:** 14 gap-path probes — G1 (masked bank account in PDF), G2 (public_holiday_rate × hours contribution), G4 (recurring-allowance endpoint), G5 (period roll idempotency), G6 (termination dry-run), G9 (self-service ownership-leak guard returns 404 not 403), G12 (audit-log redaction), G14 (cadence non-retroactive), G16 (termination preview surfaces future-leave count), G18 (allowance quantity/unit on detail), G20 (multi-page PDF), G21 (reopen state machine — open → 422), G24 (bulk-finalise SLO under 5s), G25 (termination final-payslip pay-period selection).

**Pattern:** mirrors `scripts/test_staff_clock_in_out_e2e.py` (Phase 3 E3) but uses `httpx.AsyncClient` + `pytest-asyncio` so the script runs as `pytest scripts/test_staff_payslip_e2e.py -k e2e -v` rather than `python scripts/...`.

**Pre-merge gate:** the deferred run must pass against the deploying engineer's dev backend (or staging) before the Phase 4 release tag. The runner is documented at the top of the script in the docstring.

**Local exercise (when a backend is running):**

```bash
BASE_URL=http://localhost:8000 \
JWT=<admin_jwt> \
STAFF_JWT=<linked_staff_jwt> \
ORG_ID=<uuid> \
STAFF_ID=<uuid> \
RUN_E2E=1 \
pytest scripts/test_staff_payslip_e2e.py -k e2e -v
```
