# Staff Management — Cross-Phase Spec Audit (P1 → P5)

Date: 2026-05-31
Reviewed: `.kiro/specs/staff-management-p{1,2,3,4,5}/{requirements,design,tasks}.md` against each other for:
1. Contradictions between phases.
2. Missing pieces — features that one phase adds but no phase consumes (dead code) or that one phase consumes but no phase adds (broken workflow).
3. Conflicting steps where two phases prescribe incompatible behaviour.

The single-phase audits (P1's P1-N1..P1-N15, P2's P2-N1..P2-N12, P3's P3-N1..P3-N12, P4's N1-N20 + P4-N21..P4-N32) all hold up internally. The findings below (X1...X10) are the NEW cross-phase issues uncovered by checking the five specs against each other.

## Cross-phase finding tagging

Tagged `X#` to keep them distinct from per-phase tags.

---

## CRITICAL — workflow breaks

### X1. P4 SQL joins on a non-existent `timesheet_approvals.time_clock_entry_id` column

**Where it bites:** P4 design §4.2 `_resolve_allowance_quantity` SQL:

```sql
SELECT COUNT(DISTINCT se.id)
FROM schedule_entries se
JOIN time_clock_entries tce ON tce.scheduled_entry_id = se.id
JOIN timesheet_approvals ta ON ta.time_clock_entry_id = tce.id   -- ← BREAKS HERE
WHERE se.staff_id = :staff_id
  ...
  AND ta.status = 'approved'
```

**Reality (P3 design §3.1 SQL):** `timesheet_approvals` is week-based:

```sql
CREATE TABLE timesheet_approvals (
    id, org_id, staff_id, week_start date, week_end date,
    status text, total_worked_minutes, total_overtime_minutes, ...,
    UNIQUE (staff_id, week_start)
);
```

There is **no `time_clock_entry_id` column** on `timesheet_approvals` — it summarises a whole week, not individual clock entries. The P4 N20 fix introduced this join when re-writing the shift-count query, but never cross-checked against P3's actual schema. P4's `_resolve_allowance_quantity` will raise a SQL parse error at runtime: `column ta.time_clock_entry_id does not exist`.

The semantic fix is to join on the **week** that contains the schedule entry's `start_time`:

```sql
JOIN timesheet_approvals ta
  ON ta.staff_id = se.staff_id
 AND se.start_time::date BETWEEN ta.week_start AND ta.week_end
WHERE ...
  AND ta.status = 'approved'
```

This says "count shifts that fall inside an approved week" — which matches the spirit of N20 ("admin signed off the timesheet covering this shift").

**Fix applied:**
- P4 design.md §4.2 — rewrote the SQL to join on the week range instead of the non-existent FK.
- P4 tasks.md B3 — same correction in the verify text.
- P4 requirements.md R4.6 — clarified "drawn from `timesheet_approvals` covering the period" (not "linked `time_clock_entries`").

### X2. TOIL leave type is referenced by P3 but never seeded by any migration

**Where it bites:** P3 R10.2 + R11 references the staff's `toil` leave balance:

> "WHEN `timesheet_approvals` is approved AND org policy `overtime_handling='toil'` THE SYSTEM SHALL grant the overtime hours to the staff's `toil` leave balance via `leave_ledger` row..."

**Reality:** P2 R1.3 says it ships **6 statutory leave types** (`annual, sick, bereavement, family_violence, public_holiday_alt, unpaid`) and P2 tasks A1 Verify says `SELECT count(*) FROM leave_types WHERE org_id=<test_org>` returns 6. P2 R10.1 separately says "THE SYSTEM SHALL add a 7th leave type `toil` ... Seeded for orgs that select `overtime_handling='toil'` or `'employee_chooses'`" — but no migration step seeds it when the column flips. P3 also doesn't seed it. P4 doesn't seed it.

So when an org sets `overtime_handling='toil'` in P3 settings, the timesheet-approval flow tries to write a `leave_ledger` row pointing at a `leave_type_id` that doesn't exist for that org → FK violation.

**Two acceptable fixes:**
1. **P2 always seeds toil for every org** (whether or not overtime_handling='toil'). Cost: one extra leave_types row per org. P3 can then just lookup-or-fail.
2. **P3 seeds toil JIT** when an org first flips `overtime_handling` to `toil` or `employee_chooses` in the Settings → People → Clock-in Policy page.

Option 1 is simpler and matches how P2 already seeds the other 6 types. Option 2 introduces a "Settings save handler that writes to a different table" pattern.

**Fix applied (option 1):**
- P2 R1.3 — extended the statutory list to 7 types: add `toil` with `is_paid=true, accrual_method='event_based', is_statutory=false, active=true, display_order=7`. Note: `is_statutory=false` because TOIL is not a statutory entitlement (it's a contractual choice), but ship it pre-seeded for every org because it's universal infrastructure.
- P2 R10.1 — replaced "Seeded for orgs that select..." with "Seeded for every existing org during the P2 backfill (regardless of `overtime_handling` value)."
- P2 tasks A1 Verify — `SELECT count(*) FROM leave_types WHERE org_id=<test_org>` returns **7** (was 6).
- P2 tasks A1 — backfill statutory list grows to 7 entries.
- P3 R11 — added an explicit statement: "TOIL leave_types row is guaranteed to exist for every org per P2 R1.3 — this requirement is the lookup, not the seed."

### X3. P3 R11.1 leaves `leave_ledger.reason='toil_accrual'` decision deferred — P2's CHECK enum doesn't include it

**Where it bites:** P3 R11.1: "...via `leave_ledger` row `reason='request_approved'` (or new reason `'toil_accrual'` — design picks)."

**Reality:** P2 R3.1 fixes the `leave_ledger.reason` CHECK enum at:
```
'accrual', 'request_approved', 'request_cancelled_after_approval',
'manual_adjustment', 'opening_balance', 'termination_payout',
'public_holiday_extension', 'public_holiday_worked', 'pay_run_payout'
```

If P3 design picks `'toil_accrual'` (the cleaner option for filtering ledger rows by reason), P2's CHECK constraint must be amended. But P2 ships first; amending its CHECK from P3 means a P3 migration that runs `ALTER TABLE leave_ledger DROP CONSTRAINT ...; ADD CONSTRAINT ...`.

**Two acceptable fixes:**
1. **P2 pre-includes `'toil_accrual'` in the enum** even though P2 doesn't write it. Costs nothing.
2. **P3 amends the enum** with a constraint-drop-and-recreate at migration 0207.

Option 1 is cleaner — it's a forward-compatible enum that costs nothing. P3's design is then unambiguous.

**Fix applied (option 1):**
- P2 R3.1 — extended the reason enum to include `'toil_accrual'`. Updated P2 design.md §3.1 SQL CHECK to match.
- P2 tasks A1 — same enum update in the migration template.
- P3 R11.1 — replaced "`reason='request_approved'` (or new reason `'toil_accrual'` — design picks)" with the unambiguous "`reason='toil_accrual'` (added to P2's leave_ledger.reason CHECK enum per cross-phase X3 fix)".
- P3 design.md §4 service-layer notes — same.

### X4. P4's `_org_setting('overtime_handling', ...)` helper allows JSONB fallback that P2 + P3 both rejected

**Where it bites:** P4 tasks B3:

> "**`_org_setting('overtime_handling', default='pay_cash')` helper (N5)** — tries the typed column first, then falls back to `organisations.settings ->> 'overtime_handling'` so P4 isn't coupled to whichever shape P2 chooses."

**Reality:** P2's gap-analysis P2-N5 explicitly committed to a typed column. P3's gap-analysis P3-N4 confirmed and removed the JSONB fallback. P4 still has the fallback "just in case P2 chooses differently" — but P2 has chosen.

The fallback is dead code. Worse, it's actively harmful: a future maintainer looking at P4 might think there's flexibility when there isn't, and might write JSONB shim code in another path that reads the wrong location.

**Fix applied:**
- P4 tasks B3 — removed the `_org_setting` fallback wording: "Phase 4 reads `org.overtime_handling` directly via the ORM (`(await db.get(Organisation, org_id)).overtime_handling`). The typed column is settled by P2's P2-N5 fix and confirmed by P3's P3-N4 fix; no JSONB fallback is needed or wanted."
- P4 design.md §11 verified-against-code addendum — same simplification.
- P4 requirements.md R4 pre-condition — replaced the `_org_setting` reference with direct ORM read.

---

## HIGH — feature dead-ends and missed integrations

### X5. P3 ships `clock_in_policy.shift_swap_requires_manager_approval` toggle but `clock_in_policy.branch_radius_metres` becomes dead after P3-G17

**Where it bites:** P3 R6.1 lists the org-level `clock_in_policy` JSONB defaults including `branch_radius_metres: 200`. P3 R6.4 (G17 fix) clarifies that **per-branch** `branches.geofence_radius_metres` is authoritative — the org-level `branch_radius_metres` is used **only as the default when a new branch row is INSERTed**.

**Reality:** P3 design §3.1 + R6.4 say the migration backfills existing branches' `geofence_radius_metres` from this org-level default once at upgrade. After that, the org-level value sits in JSONB serving no purpose — every branch has its own column. New branches created via the Branches CRUD UI don't currently read from the org-level default (Branches CRUD is owned by an earlier feature; P3 doesn't extend it).

So `clock_in_policy.branch_radius_metres` becomes vestigial after migration — nobody reads it after the one-time backfill.

**Fix applied:**
- P3 R6.4 — explicit clarification: "After the one-time backfill, `clock_in_policy.branch_radius_metres` is a 'default-for-new-branches' value that the existing Branches CRUD MUST read when inserting a new branch row. Phase 3 ships a small Branches CRUD patch in tasks.md B-NEW (added below): when `INSERT INTO branches (...)` lacks a `geofence_radius_metres`, the service reads the org's `clock_in_policy.branch_radius_metres` and uses that as the default."
- P3 tasks.md — added a new task **B12 (Branches CRUD patch for new-branch geofence default)**: "Touch `app/modules/organisations/service.py::create_branch` (existing) so when payload omits `geofence_radius_metres`, the service reads `org.clock_in_policy.branch_radius_metres` (or 200 if missing) and writes it. Without this, new branches created post-P3 would get the column-default 200 even if the org admin set a different value in `clock_in_policy.branch_radius_metres`. Verify: change `clock_in_policy.branch_radius_metres` to 500 → create a new branch with no explicit radius → assert `branches.geofence_radius_metres = 500`."

### X6. P5 R7 IRD export decrypts `staff.ird_number_encrypted` but P4's "decryption only inside pdf.render_pdf" rule forbids it

**Where it bites:** P4 §10 Security:

> "IRD + bank account decryption ONLY happens inside `pdf.render_pdf` and `termination.terminate_employment` calls."

But P5 R7.1: "returning CSV with columns: employee_name, ird_number (full, decrypted server-side), ..."

**Reality:** P5's IRD export is a legitimate decryption path for tax filing (org admin pastes the CSV into myIR). P4's "decryption only in pdf + termination" rule was written before P5 existed — P5 adds IRD export and bank-file export, which BOTH need to decrypt.

If P4's rule is enforced literally (e.g., a lint test that grep-fails on `envelope_decrypt_str` outside those two paths), P5 lands and breaks the lint. If P5 is allowed to decrypt, P4's rule needs amendment.

**Fix applied:**
- P4 §10 Security — extended the rule to explicitly enumerate the legitimate decryption paths (forward-looking to P5):
  > "IRD + bank-account decryption is permitted in the following service paths only:
  > 1. `app/modules/payslips/pdf.py::render_pdf` (P4)
  > 2. `app/modules/payslips/termination.py::terminate_employment` (P4 — bank-account masked in PDF; IRD not decrypted)
  > 3. `app/modules/payroll_reports/bank_files.py::generate_bank_file` (P5 — bank account decrypted to write CSV)
  > 4. `app/modules/payroll_reports/ird_export.py::generate_ird_export` (P5 — IRD decrypted to write CSV)
  >
  > Any other path that imports `envelope_decrypt` / `envelope_decrypt_str` against an `staff_members` encrypted column is a leak and must be flagged in code review."
- P5 design §3.2/3.3 — added a back-reference to P4 §10 confirming the decryption paths are authorised.
- P5 tasks.md — added a verify step: "the bank-files and ird-export modules are listed in P4's §10 authorised-decryption-paths registry."

### X7. P3 G3 running-late SMS goes to manager via `resolve_manager(staff)` walking `reporting_to` chain — but P1 doesn't add `reporting_to.user_id` resolver

**Where it bites:** P3 design §4.7 `resolve_manager(db, staff)` walks `staff.reporting_to` and returns the first manager **with a `user_id`**.

**Reality:** P1 R2 lists 23 columns added to `staff_members`. `reporting_to` already exists (Phase 0) — Phase 1 doesn't change it. The chain navigation is fine. But the helper relies on `staff_members.user_id` being populated for whichever manager in the chain has logged in — which means workshops with manager-staff who don't have `user_id` set will silently fall back to "first org_admin", which might surprise the org owner.

This isn't a contradiction or dead code — it's a workflow gap that surfaces under operational conditions. The spec acknowledges the fallback ("falls back to first org_admin if no chain leads to a user") but doesn't tell the org admin which manager will receive the SMS.

**Fix applied:**
- P3 design §4.7 — added a UI nag: "When viewing a staff record on the Overview tab, if `staff.reporting_to` is set but the chain doesn't lead to a manager with a `user_id`, the Overview tab shows an amber chip 'Manager has no app login — running-late SMS will go to org owner instead'."
- P3 tasks.md E3 → D-something — added a D-NEW task: "When loading staff detail, compute `chain_resolves_to` (manager user_id or org_admin fallback) and surface the chip when fallback is in effect."

(Marked as P3 follow-up rather than P1 — P1 has already shipped its scope; P3 is the consumer.)

### X8. P3 cancels `schedule_entries` rows for terminated future leave but P3 + P4 disagree on the API

**Where it bites:** P4 R10 Step 1: "Mark the corresponding future `schedule_entries` rows (`entry_type='leave'` within the cancelled range) as cancelled or delete them, depending on whichever the scheduling_v2 module supports."

**Reality:** P3 R6 + R12 + R14a/G2 all reference `schedule_entries.status='cancelled'` as the canonical state for "this entry is no longer happening" (verified at `app/modules/scheduling_v2/models.py:21` `ENTRY_STATUSES = ['scheduled', 'completed', 'cancelled']`). P4 says "as cancelled or delete them" — leaves the implementation ambiguous, then admits "depending on whichever the scheduling_v2 module supports". scheduling_v2 supports `status='cancelled'` and DOES NOT support hard-delete via the standard service — so the only correct path is `status='cancelled'`.

The "or delete them" language is a footgun. An implementer might choose hard-delete and break P3's roster-change SMS hook (which depends on the row continuing to exist for audit purposes, just with `status='cancelled'`).

**Fix applied:**
- P4 R10 Step 1 — replaced "as cancelled or delete them, depending on whichever the scheduling_v2 module supports" with "by setting `schedule_entries.status='cancelled'` (the canonical 'no longer happening' state per P3 + scheduling_v2 model). Hard-delete is forbidden — P3's roster-change SMS hook relies on the row continuing to exist with the cancelled status so the audit row + history queries are coherent."
- P4 design §4.3 termination service — same correction.
- P4 tasks B6 — same correction.

---

## MEDIUM — module slug + audit-log hygiene

### X9. Module slug `staff_management` vs `staff` is inconsistent across phase consumers

**Where it bites:** Multiple phases reference module gates with different slugs.

**Inventory across phases:**
- P1 R11.1 introduces `staff_management` module slug (the new one).
- P1 design §2 acknowledges the legacy `staff` module slug already gates `/api/v2/staff` paths via path-prefix middleware.
- P1 says the two coexist: legacy `staff` controls path access (403); new `staff_management` controls sub-feature surface (404 for new endpoints, legacy view for `is_enabled('staff_management')=false`).
- P2 R1.6 + R11 module-gates leave routes behind `staff_management`. ✅ Consistent.
- P3 module-gates time-clock + swaps + cover behind `staff_management`. ✅ Consistent.
- P4 module-gates payslip surface behind `payroll`. The `payroll` module declares `dependencies=["staff_management"]`. ✅ Consistent.
- **P5 R1.1 + R2.1**: dashboard widgets gated by `module: 'staff_management'`. ✅
- **P5 design §2**: "All widgets module-gated by `staff_management`; bank/IRD export gated by `payroll`." ✅
- **P5 design §2**: "Dashboard widgets auto-appear when `staff_management` module enabled and the user hasn't reordered them lower." ✅

Good news: P2-P5 are consistent on `staff_management`. **But** the legacy `staff` slug at the path-prefix middleware level still gates ALL `/api/v2/staff/*` endpoints — and Phase 4 introduces `/api/v2/staff/me/payslips` (subject to that gate) plus `/api/v2/staff/:id/payslips/recurring-allowances`. P4 R8a.4 acknowledges this dual gating but doesn't tell P5's audit team that the same dual gate applies to P5's report endpoints under `/api/v2/reports/staff-calendar` etc.

P5 endpoints don't sit under `/api/v2/staff/*` — they're at `/api/v2/reports/...`. So the legacy `staff` gate doesn't apply. P5 widgets explicitly gate on `staff_management`. **No actual contradiction.** This is verified-clean.

**Fix applied:** logged here as verified-no-fix-needed for the audit trail. No spec changes.

### X10. Audit-log singular vs plural — final cross-phase sweep

**Where it bites:** Each phase audit found stragglers. Doing a final cross-phase sweep:

**Inventory:**
- P1 (post P1-N11): all uses `audit_log` ✅
- P2 (post P2-N2): all uses `audit_log` ✅
- P3 (post P3-N2): all uses `audit_log` ✅
- P4 (post P4-N21): all uses `audit_log` ✅
- **P5 audit logging** — P5 tasks.md mentions "Audit rows for `bank_file.exported` and `ird_export.generated`" but never explicitly says singular `audit_log`. P5 design §6.1 trace says "Audit row written" without table reference. **Not a contradiction**, but P5 hasn't been audit-swept like P1-P4 were. Search confirms P5 doesn't use `audit_logs` plural anywhere. ✅

**Fix applied:** logged as verified-no-fix-needed. P5 doesn't have the audit_logs/audit_log issue because it didn't write the spec text that P1-P4 had inherited from a prior draft.

---

## ALSO VERIFIED (no fix needed)

These cross-phase items were checked and ARE coherent across all five phase specs:

- ✅ Phase numbering: 0203/0204 (P1) → 0205/0206 (P2) → 0207/0208 (P3) → 0209/0210 (P4) → no migrations in P5. No collisions.
- ✅ Version bumps: 1.13 → 1.14 (P1) → 1.15 (P2) → 1.16 (P3) → 1.17 (P4) → 1.18 (P5). Sequential.
- ✅ `staff_members.average_daily_pay_snapshot` — added by P2 (R9.1), placeholder calc by P2 task C3, refreshed by P4 R13's `update_adp_snapshots` swap. No phase tries to add the column twice.
- ✅ `staff_members.bank_account_number_encrypted` + `ird_number_encrypted` — added by P1 R2, encrypted by P1 service-layer envelope_encrypt, decrypted only in P4 (pdf + termination) and P5 (bank-files + ird-export per X6 fix). All phases agree on `bytea` + `envelope_encrypt(...)`.
- ✅ `module_registry` rows for `staff_management` + `payroll` — inserted by P1 R11. P4 reads `payroll`. P5 widgets gate on `staff_management`. No duplicate inserts.
- ✅ `staff_pay_rates` table — P1 owns it. P4 R10 Step 2 reads it for "ordinary_weekly" baseline. No conflicts.
- ✅ `leave_types`, `leave_balances`, `leave_requests`, `leave_ledger` — all owned by P2. P3 R11 writes to `leave_ledger` for TOIL accrual. P4 R10 Step 1 + Step 5 writes to `leave_ledger` for termination. P4 R7 reads `leave_balances` for s130A "remaining balance" PDF section. All consumers consistent with P2's schema.
- ✅ `time_clock_entries`, `break_records`, `timesheet_approvals`, `overtime_requests`, `shift_swap_requests`, `shift_cover_requests` — all owned by P3. P4 R4 reads `timesheet_approvals` for hours; P5 R3 reads them for attendance metrics; P5 R6 streams `payslips` (P4) joined to `staff_members` (P1). All consumers consistent (post X1 fix).
- ✅ `pay_periods`, `payslips`, `payslip_*` lines, `staff_recurring_allowances` — all owned by P4. P5 widgets read `payslips.gross_pay`; P5 bank export reads `payslips.id`/`net_pay`/`staff.bank_account_number_encrypted`. All consumers consistent.
- ✅ `WIDGET_DEFINITIONS` + `dashboard-widget-gating.md` — P5 follows the existing pattern from earlier features. P1-P4 don't define dashboard widgets (P5 is the only widget producer), so no conflict.
- ✅ Public-holiday data: P2 R8 owns the `public_holidays` table reads + `process_public_holidays` task. P4 R13 ADP refresh and P5 R3 attendance reports query the same table. All consistent.
- ✅ Email + SMS dispatch: P1 introduces `app/integrations/sms_sender.py`. P2 R14 + P3 R12.5 + R14a + R14b + P4 R8 all reuse it via `send_sms(..., dlq_task_name=...)`. Consistent across phases.
- ✅ `audit_log` event names — distinct namespaces per phase (`staff.*`, `roster.*`, `leave_*`, `time_clock.*`, `shift_swap.*`, `shift_cover.*`, `payslip.*`, `pay_period.*`, `bank_file.exported`, `ird_export.generated`). No collisions.
- ✅ Phase 1's `weekly_roster_email_enabled` + `weekly_roster_sms_enabled` opt-out flags consumed by P3's roster-change SMS hook (G2) AND P3's running-late SMS (G3) AND P4's payslip email (R8). Each consumer correctly reads the right flag.
- ✅ Self-service surface: P3 ships `/api/v2/staff/me/clock-action` + `/api/v2/staff/me/running-late`. P4 ships `/api/v2/staff/me/payslips` (G9). The two share the `/api/v2/staff/me/*` namespace; routing tree clean. The `staff_members.user_id` partial UNIQUE index from P4 N1 supports both.
- ✅ Mobile screens: P3 owns `mobile/src/screens/clock/ClockScreen.tsx` (R15). P4 owns `mobile/src/screens/payslips/PayslipsScreen.tsx` (G9). Each lazy-imported in `StackRoutes.tsx`. No path collision.

---

## Summary of fixes applied

| # | Cross-phase break | File touched | Section |
|---|---|---|---|
| X1 | P4 SQL joins on non-existent `timesheet_approvals.time_clock_entry_id` | P4 design.md, requirements.md, tasks.md | §4.2, R4.6, B3 |
| X2 | TOIL leave_type referenced by P3, never seeded by any migration | P2 requirements.md, tasks.md; P3 requirements.md | R1.3, R10.1, A1, R11 |
| X3 | `'toil_accrual'` reason missing from P2's `leave_ledger.reason` enum | P2 requirements.md, design.md, tasks.md; P3 requirements.md, design.md | R3.1, §3.1, A1, R11.1 |
| X4 | P4's overtime_handling JSONB fallback is dead code (P2/P3 settled on typed column) | P4 tasks.md, design.md, requirements.md | B3, §11, R4 pre-cond |
| X5 | `clock_in_policy.branch_radius_metres` becomes vestigial post-migration | P3 requirements.md, tasks.md | R6.4, B12 (new) |
| X6 | P4 §10 decryption rule forbids P5 bank-files + IRD-export | P4 design.md, P5 design.md, tasks.md | §10, §3.2/3.3 |
| X7 | running-late SMS fallback to org_admin is silent | P3 design.md, tasks.md | §4.7, D-NEW |
| X8 | P4 R10 Step 1 "cancel or delete" is a footgun | P4 requirements.md, design.md, tasks.md | R10 step 1, §4.3, B6 |
| X9 | Module slug `staff_management` vs legacy `staff` consistency | (verified, no fix) | — |
| X10 | Audit-log singular sweep across P5 | (verified, no fix) | — |

All actionable fixes (X1-X8) applied in this commit alongside this audit.

## Recommendation

The single-phase audits caught the precision gaps within each phase. This cross-phase audit catches the integration breaks: 4 critical (workflow-stopping at runtime — X1 SQL parse error, X2 FK violation, X3 enum mismatch, X4 dead-code leak) plus 4 high-severity workflow gaps (X5-X8).

The most dangerous is **X1** (P4 SQL join on a non-existent column) — this would have surfaced as a runtime error during the very first payslip generation involving a `unit='shift'` allowance. Caught before implementation.

After applying X1-X8 fixes, the five-phase staff management spec set is cross-phase coherent. Phase 1 ships, then 2, then 3, then 4, then 5 (optional) without any spec consumer reading data the previous phase didn't write, or any spec writer producing data the next phase doesn't expect.
