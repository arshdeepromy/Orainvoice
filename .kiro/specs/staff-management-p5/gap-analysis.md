# Staff Management Phase 5 — Gap Analysis (code + internal alignment)

Date: 2026-05-31
Reviewed: `.kiro/specs/staff-management-p5/{requirements,design,tasks}.md` cross-checked against actual code at `app/modules/organisations/dashboard_service.py`, `app/modules/organisations/schemas.py`, `app/modules/invoices/models.py`, `app/modules/scheduling_v2/models.py`, `app/modules/reports/router.py`, `frontend/src/pages/dashboard/widgets/WidgetGrid.tsx`, `frontend/src/pages/dashboard/widgets/WidgetCard.tsx`, `frontend/src/pages/dashboard/OrgAdminDashboard.tsx`. No assumptions; every reference verified.

P5 has the smallest spec surface of all five phases (no migrations, 5 reports + 2 widgets). But because it touches `dashboard_service.py` and `dashboard_router.py` — both already-shipped surfaces with tight conventions — the fact-checking turns up real gaps. 12 findings (P5-N1 to P5-N12), of which 4 are critical (broken at first run).

## Tagging

`P5-N#` to keep distinct from prior phase tags.

---

## CRITICAL (broken at runtime / would block a non-trivial subset of orgs)

### P5-N1. Widgets are invisible to non-automotive orgs (the dashboard `WidgetGrid` itself is gated by trade family)

**Where it bites:** P5 R1 + R2 (dashboard widgets `labour_cost_vs_revenue` + `wage_forecast`).

**Spec says (R1.1, R2.1):** add `WIDGET_DEFINITIONS` entries with `module: 'staff_management'`. The widgets appear when the `staff_management` module is enabled.

**Reality (verified at `frontend/src/pages/dashboard/OrgAdminDashboard.tsx:346`):**

```tsx
{(tradeFamily ?? 'automotive-transport') === 'automotive-transport' && user?.id && (
  <WidgetGrid userId={user.id} branchId={selectedBranchId ?? null} />
)}
```

The entire `WidgetGrid` only renders for `automotive-transport` orgs. Tests at `frontend/src/pages/dashboard/__tests__/OrgAdminDashboard.test.tsx:167-180` verify it's HIDDEN for `plumbing-gas` and `electrical` orgs. The dashboard-widget-gating steering doc (`.kiro/steering/dashboard-widget-gating.md`) says this explicitly: "Trade-family gating — The entire WidgetGrid only renders for automotive-transport orgs."

**Impact:** P5's two widgets gated only by `module: 'staff_management'` will be **completely invisible** to plumbing, electrical, construction, hospitality, and 11 other trade families — even when payroll is fully running for those orgs. Project-overview.md states the platform supports 16 trade families; restricting payroll widgets to 1/16 of the customer base is almost certainly NOT the intent.

**Fix applied (one of two paths needs picking; spec now gates on the choice):**

Option A — **drop the trade-family gate around `WidgetGrid`** and let module + role gating do the work. This is the cleanest fix but touches the existing dashboard architecture and needs a separate decision.

Option B — **render P5 widgets in a different surface**, not the `WidgetGrid`. E.g., a dedicated "Payroll Dashboard" page at `/payroll/dashboard` that shows the two widgets without the trade-family gate.

**Resolution applied to spec:** chose Option A as a recommendation but added an explicit Open Question (STAFF-011) asking the team to settle before P5 implementation. Updated R1, R2, and design §2 to acknowledge the gate and require the resolution to land before widget code is written.

### P5-N2. P5 design SQL queries `invoices.total_amount` — column doesn't exist; the column is `total`

**Where it bites:** P5 design §3.1 SQL:

```sql
revenue = await db.scalar(sa_text("""
    SELECT COALESCE(SUM(total_amount),0) FROM invoices
    WHERE org_id=:org AND status IN ('issued','partially_paid','paid')
          AND created_at >= :since
"""), ...)
```

**Reality (verified at `app/modules/invoices/models.py:184-187`):**

```python
total: Mapped[Decimal] = mapped_column(
    Numeric(12, 2), nullable=False, server_default="0"
)
```

The column is `total`, not `total_amount`. There's no `total_amount` column on `invoices`. The SQL would error: `column "total_amount" does not exist`. The existing `dashboard_service.py::get_branch_metrics` queries `Invoice.total` correctly — P5 mis-copied the column name.

**Status check:** `subtotal` exists; `total` exists; `total_paid` and `balance_due` exist (visible in earlier grep). NO `total_amount`.

**Fix applied:**
- P5 design §3.1 SQL — corrected `SUM(total_amount)` → `SUM(total)`.
- P5 R1.3 — same correction in the spec text: `revenue = SUM(invoices.total)` not `SUM(invoices.total_amount)`.
- P5 tasks A2 verify — added "uses `Invoice.total`, not `total_amount`".

### P5-N3. P5 R2 says "published `schedule_entries`" — `published` is not a status that exists

**Where it bites:** P5 R2.2: "Computes Monday-morning view: published `schedule_entries` for the current week × ..."

**Reality (verified at `app/modules/scheduling_v2/models.py:21`):**

```python
ENTRY_STATUSES = ["scheduled", "completed", "cancelled"]
```

There is **no `'published'` status**. The wage-forecast logic must filter on something that exists. The natural choice for "shifts that are still going to happen this week" is `status IN ('scheduled', 'completed')` (excluding `'cancelled'`).

**Fix applied:**
- P5 R2.2 — replaced "published `schedule_entries`" with "non-cancelled `schedule_entries` (`status IN ('scheduled', 'completed')`)" (matches the actual enum).
- P5 design — added a note in §3.1 wage-forecast SQL clarifying the filter.
- P5 tasks A3 verify — "uses `status IN ('scheduled','completed')`, not the non-existent `'published'`".

### P5-N4. `WidgetCard` does not accept `empty` / `emptyText` props — the spec sample passes them

**Where it bites:** P5 design §5.1:

```tsx
<WidgetCard title="Labour cost vs revenue" empty={!data?.items?.length} emptyText="No staff payslips yet — generate your first pay run">
```

**Reality (verified at `frontend/src/pages/dashboard/widgets/WidgetCard.tsx:14-21`):**

```tsx
export function WidgetCard({
  title,
  icon: Icon,
  actionLink,
  children,
  isLoading = false,
  error = null,
}: WidgetCardProps) {
```

`WidgetCard` takes `title`, `icon`, `actionLink`, `children`, `isLoading`, `error` only. There are no `empty` or `emptyText` props. The empty state pattern across all 9 existing widgets is to render the empty-state message inside `children` conditionally:

```tsx
{items.length === 0 ? (
  <p className="text-sm text-gray-500">No data available</p>
) : (
  // populated render
)}
```

This is also what dashboard-widget-gating.md step 8 says explicitly. P5's design contradicts the established pattern AND won't compile (TypeScript will reject `empty`/`emptyText` not being in `WidgetCardProps`).

**Fix applied:**
- P5 design §5.1 — rewrote the JSX to use the canonical pattern: `{(data?.items?.length ?? 0) === 0 ? <p>...</p> : (data?.items ?? []).map(...)}` inside `<WidgetCard>`. Also added the required `icon` prop (which the design didn't include — it's not optional in `WidgetCardProps`).
- P5 design §5.1 sample — added an `icon: BanknotesIcon` import and pass it through.
- P5 tasks A6 verify — added "follows existing widget pattern: WidgetCard wraps children, empty state message is conditional inside children, NOT a WidgetCard prop".

---

## HIGH (workflow gaps, not runtime crashes)

### P5-N5. Backend field naming convention vs frontend ID convention is mixed inconsistently

**Where it bites:** P5 R1.1 says "WIDGET_DEFINITIONS entry `labour_cost_vs_revenue`" (snake_case) but the existing convention has TWO different naming styles:
- **Frontend WIDGET_DEFINITIONS `id` field** — kebab-case (`'recent-customers'`, `'todays-bookings'`, `'inventory-overview'`).
- **Backend `DashboardWidgetData` field name** — snake_case (`recent_customers`, `todays_bookings`).

The same widget is referenced by different identifiers on the two sides; the data hook normalisation in `useDashboardWidgets.ts` is what bridges them.

**Spec is ambiguous:** R1.1 + R2.1 say "WIDGET_DEFINITIONS entry `labour_cost_vs_revenue`" without saying which side. dashboard-widget-gating.md step 9b says `id: kebab-case` for the frontend definition.

**Fix applied:**
- P5 R1.1 — clarified: "Frontend `WIDGET_DEFINITIONS` `id`: `'labour-cost-vs-revenue'` (kebab-case per existing convention). Backend `DashboardWidgetData.labour_cost_vs_revenue` (snake_case per existing Pydantic convention). Hook normalisation in `useDashboardWidgets.ts` reads `raw.labour_cost_vs_revenue` and exposes it as the `data.labour_cost_vs_revenue` key."
- P5 R2.1 — same clarification for `wage_forecast` / `'wage-forecast'`.
- P5 design §5.1 — reworded the example accordingly.

### P5-N6. P5 references widgets by IDs `labour_cost_vs_revenue` and `wage_forecast` but `defaultOrder: 11/12` collides with existing slots

**Where it bites:** P5 R1.1 says `defaultOrder: 11`, R2.1 says `defaultOrder: 12`.

**Reality (verified at `WidgetGrid.tsx:63-79`):** existing widgets occupy `defaultOrder: 1` through `10`. Position 11 + 12 are correctly unallocated, so this is technically fine — but the "Recent Invoices" widget at position 6 was added between earlier insertions and that position is now in-use. The risk is silent collision if any other in-flight feature also adds widgets at positions 11+ before P5 ships.

**Fix applied:**
- P5 R1.1 + R2.1 — added a verify step: "Before merge, re-check `WidgetGrid.tsx::WIDGET_DEFINITIONS` for any widget already at `defaultOrder: 11` or `defaultOrder: 12`. If a collision exists, bump P5's widgets to the next free slot."

### P5-N7. P5 spec talks about "module-gated by `staff_management`" but P4 ships the actual payroll-data-producing module as `payroll`

**Where it bites:** P5 R1.1 says `module: 'staff_management'` for `labour_cost_vs_revenue` (which reads `payslips.gross_pay`). But payslips are produced by P4's `payroll` module, not the `staff_management` module. If an org enables `staff_management` but disables `payroll`, the widget would render but show zero data (no payslips).

**Reality (cross-phase X9 in earlier audit):** `payroll` module's `dependencies=["staff_management"]` per P1 R11.2 — so `payroll` enabled implies `staff_management` enabled, but NOT the reverse. The widget gate should be `payroll`, not `staff_management`, to avoid empty rendering.

Same logic for `wage_forecast`: it reads `staff_members.hourly_rate` (P1) + `schedule_entries` (existing) + `leave_requests` (P2) + `overtime_requests` (P3). The data source is broad; technically `staff_management` is correct here because the widget can produce useful output even without payroll. So `wage_forecast` legitimately gates on `staff_management`.

**Fix applied:**
- P5 R1.1 — gate `labour_cost_vs_revenue` on `module: 'payroll'` (NOT `'staff_management'`) because the widget reads `payslips`.
- P5 R2.1 — keep `wage_forecast` on `module: 'staff_management'` because it reads schedule + staff data, which works even without payroll shipped.
- P5 design §2 — corrected the bullet "All widgets module-gated by `staff_management`" to differentiate per widget.

### P5-N8. `tradeFamily` Open Question (STAFF-011) means the spec has a hard prereq to settle before A1 starts

**Where it bites:** P5-N1's resolution. If chosen as Option A (drop trade-family gate), that's a separate decision affecting the OrgAdminDashboard surface and requires its own audit. If chosen as Option B (separate Payroll Dashboard page), P5 needs an additional task to build that page.

**Fix applied:**
- P5 R0 (new) — added an Open Question section: "STAFF-011: Resolve trade-family gating of payroll widgets. P5 cannot ship widgets until this is resolved. Recommend Option A — drop the `tradeFamily` gate around `WidgetGrid` since it's now obsolete (the platform supports 16 trade families and the dashboard infrastructure should be universal)."
- P5 tasks — added a hard prereq at top: "**STAFF-011 must be resolved** before A1 starts. If Option A: separate task to remove the trade-family gate in `OrgAdminDashboard.tsx:346`. If Option B: separate workstream to build the Payroll Dashboard surface."

---

## MEDIUM (precision, no runtime impact)

### P5-N9. P5 has no `audit_log` reference — spec just says "Audit row written"

**Where it bites:** P5 R6.6 ("Audit: `bank_file.exported`"), R7.4 ("Audit: `ird_export.generated`"). Both bare action names; no reference to the table.

**Reality (P1-P4 cross-phase audits already standardised on `audit_log` singular):** P5 follows the convention by omission (doesn't say `audit_logs` plural anywhere). Verified-clean — no fix needed, but worth noting.

**Fix applied:** logged as verified-no-fix-needed.

### P5-N10. P5 design §3.2 `format_row` is bank-specific but spec doesn't define the BNZ Multi-Pay schema

**Where it bites:** P5 R6.3 says "Each format produces a CSV matching that bank's batch-credit schema (research before implementation; STAFF-004 settles which to ship first)." Tasks B2 says "start with BNZ Multi-Pay; framework supports adding others." Pre-merge gate says "BNZ Multi-Pay CSV diffs 100% against BNZ's spec."

**Reality:** the BNZ Multi-Pay format is a documented external standard. P5 doesn't enumerate its columns or sample row in the spec. An implementer would need to find BNZ's spec sheet and diff against it. This isn't strictly a gap (the spec is honest about the deferral), but it's worth elevating from "nice to have" to "BLOCKING for B2."

**Fix applied:**
- P5 tasks B2 — added: "Before writing `format_row(BNZ_MULTIPAY, ...)`, fetch the BNZ Multi-Pay batch-credit CSV specification (BNZ's developer/business banking docs). Document the column list + sample row + delimiter convention in a code comment. Verify: end-to-end test exports a CSV and a unit test diffs it byte-for-byte against a fixture file containing a known-good BNZ-format example."

### P5-N11. P5 tasks doesn't cover the dashboard-widget-gating.md 10-step checklist completely

**Where it bites:** dashboard-widget-gating.md enumerates 10 steps for adding a widget. P5 tasks A1-A7 cover most but skip:
- **Step 5** (add field to `DashboardWidgetsResponse`) is in A4.
- **Step 6** (add TypeScript type to `types.ts`) is bundled into A6 implicitly.
- **Step 9b** (kebab-case ID convention) — covered by P5-N5 fix above.
- **Step 9c** (add case to `renderWidget()` switch) is NOT explicitly mentioned in P5 tasks.
- **Step 10 — moduleGating.property.test.ts update** is NOT mentioned. New module-gated widgets MUST update that test (per the steering doc).

**Fix applied:**
- P5 tasks A6 — split into A6 + A6a: A6 component creation, A6a `renderWidget()` switch update.
- P5 tasks A7 — added: "Update `frontend/src/pages/dashboard/widgets/__tests__/moduleGating.property.test.ts` if a new module slug is introduced. P5 introduces NO new module slugs (uses existing `staff_management` and `payroll` per P5-N7), so this test only needs new widget IDs added to the mirror `WIDGET_DEFINITIONS` constant inside the test."

### P5-N12. P5 Pre-merge gate says "Both new widgets follow all 10 steps of dashboard-widget-gating" but the steps are not verified explicitly

**Where it bites:** P5 tasks Pre-merge gate.

**Fix applied:**
- P5 tasks Pre-merge gate — replaced the bullet with an explicit checklist: "Each widget passes the dashboard-widget-gating 10-step checklist:
  1. Backend service function with branch scoping + try/except per-widget.
  2. Pydantic schema added.
  3. Wired into `get_all_widget_data()` aggregator with try/except.
  4. Field on `DashboardWidgetsResponse`.
  5. TypeScript type in `types.ts`.
  6. Field on `DashboardWidgetData`.
  7. Normalisation in `useDashboardWidgets.ts`.
  8. Component file with `WidgetCard` wrapper + `?.`/`?? []` patterns + empty state inside children.
  9. Registered in `WIDGET_DEFINITIONS` (kebab-case ID, snake_case backend field) AND case in `renderWidget()` switch.
  10. Tests: backend property test + frontend empty-state test + `moduleGating.property.test.ts` mirror updated if new module slug (no new slug for P5)."

---

## ALSO VERIFIED (no fix needed)

These were checked and ARE consistent:

- ✅ `WidgetDataSection` exists at `app/modules/organisations/schemas.py:873` with `items: list, total: int = 0`.
- ✅ `DashboardWidgetsResponse` exists at `schemas.py:878` with the expected fields and `Field(default_factory=...)` pattern.
- ✅ `useDashboardWidgets` hook exists at `frontend/src/pages/dashboard/widgets/useDashboardWidgets.ts` with the expected `{ data, isLoading, error }` return shape.
- ✅ `get_recent_customers` exists at `dashboard_service.py:184`; `get_public_holidays` at `:264`. SAVEPOINT-per-widget pattern verified.
- ✅ `get_all_widget_data()` aggregator with `_safe_call()` per-widget pattern verified at `dashboard_service.py:847`.
- ✅ `app/core/encryption.py::envelope_decrypt_str` exists (verified in earlier audits).
- ✅ `StreamingResponse` from `fastapi.responses` is the canonical streaming pattern (verified at `app/modules/data_io/router.py:11`, used in 4+ places).
- ✅ `app/modules/reports/router.py` uses `dependencies=[require_role("org_admin")]` for restricted endpoints — P5's IRD-export route gate is consistent.
- ✅ Reports router mounted at both `/api/v1/reports` and `/api/v2/reports`. P5's spec uses `/api/v2/reports/...` consistently.
- ✅ Cross-phase X6 fix (P5 included in P4 §10's authorised-decryption-paths registry) verified in P5 design §9.
- ✅ Audit-log singular convention (`audit_log` not `audit_logs`) — P5 doesn't use the wrong form anywhere (P5-N9 verified).
- ✅ Bank-file Enum naming (`BankFileFormat.BNZ_MULTIPAY` etc.) is plain Python convention — fine.
- ✅ FastAPI `AsyncIterator[bytes]` streaming pattern is real and works with `StreamingResponse`.
- ✅ P5 R6.4 says "Includes only finalised payslips; excludes voided" — matches P4 R3.1 status enum (`'draft','finalised','voided'`).
- ✅ P5 R7.1 ESCT placeholder column matches IRD's actual employer-superannuation-contribution-tax column shape (out of scope for P5 calc per non-goals).

---

## Summary of fixes applied

| # | Gap | File touched | Section |
|---|---|---|---|
| P5-N1 | Widgets invisible to non-automotive orgs | requirements.md, design.md | Open Question STAFF-011, R1, R2, §2 |
| P5-N2 | `invoices.total_amount` doesn't exist; column is `total` | requirements.md, design.md, tasks.md | R1.3, §3.1, A2 verify |
| P5-N3 | `'published'` schedule_entries status doesn't exist | requirements.md, design.md, tasks.md | R2.2, §3.1, A3 verify |
| P5-N4 | `WidgetCard` doesn't accept `empty`/`emptyText` props | design.md, tasks.md | §5.1, A6 verify |
| P5-N5 | kebab-case ID vs snake_case backend field ambiguity | requirements.md, design.md | R1.1, R2.1, §5.1 |
| P5-N6 | `defaultOrder: 11/12` collision pre-flight | requirements.md | R1.1, R2.1 verify |
| P5-N7 | `labour_cost_vs_revenue` should gate on `payroll`, not `staff_management` | requirements.md, design.md | R1.1, §2 |
| P5-N8 | STAFF-011 is a hard prereq for any A-task | requirements.md, tasks.md | Open Questions, hard prereq block |
| P5-N9 | `audit_log` singular sweep | (verified, no fix) | — |
| P5-N10 | BNZ Multi-Pay schema lookup is BLOCKING for B2 | tasks.md | B2 verify |
| P5-N11 | dashboard-widget-gating 10-step checklist coverage | tasks.md | A6, A6a, A7 |
| P5-N12 | Pre-merge gate replaced with explicit 10-step | tasks.md | Pre-merge gate |

All actionable fixes (P5-N1..P5-N8, P5-N10..P5-N12) applied in this commit.

## Recommendation

Phase 5 is the smallest spec but had the most critical code-vs-spec breaks because two of its references (`invoices.total_amount`, `schedule_entries.status='published'`) literally don't exist in the codebase, and the `WidgetCard` API surface was wrongly specced. Each would have failed at first run.

The biggest non-runtime issue is **P5-N1** — the trade-family gate around `WidgetGrid` makes payroll widgets invisible to 15 of 16 trade families. This needs a product decision (STAFF-011) before any P5 widget work starts.

After applying these fixes, P5's spec is coherent across the three docs AND grounded in the actual code shapes it will touch. Implementation can proceed once STAFF-011 is resolved.
