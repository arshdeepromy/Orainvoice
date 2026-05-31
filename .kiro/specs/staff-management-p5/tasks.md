# Staff Management Phase 5 — Tasks

## Execution policy

This phase auto-advances from Phase 4 IF customer demand is recorded (P5 is optional/deferrable per Non-Goals). The full execution policy is documented at the top of `.kiro/specs/staff-management-p1/tasks.md` and applies verbatim here. Quick recap:

- **Scoped testing only** — run only the tests for the files each task touches; never the full suite.
- **No interactive prompts** — use `--yes`/`-y`/`--non-interactive` flags everywhere a tool would otherwise prompt.
- **Never stop for confirmation** — only stop on a verify failure or an explicit unresolved blocking open question (STAFF-011 is one such hard prereq; see PREREQ-1 below).
- **No watchers** — `vitest run`, `pytest`, `tsc --noEmit`; never `--watch` modes or dev servers.
- **End of chain** — Phase 5 is the LAST phase. When this phase's pre-merge gate is fully ticked, run the final `DONE` task at the bottom of this file (master plan + ISSUE_TRACKER cleanup) and STOP. There is no Phase 6.
- **Failure handling** — log the failure detail to this phase's `gap-analysis.md`, mark the task `[~]`, and continue with the next non-dependent task. Stop only after 3 consecutive failures.
- **Deferral path** — if customer demand for P5 is undocumented when the chain reaches it (no STAFF-011 resolution + no signal in `docs/ISSUE_TRACKER.md`), log "Phase 5 deferred — no customer demand recorded" to a new line in this file and stop cleanly without raising an error.

## Hard prerequisite (P5-N1 + P5-N8)

**STAFF-011 must be resolved before any A-task starts.** The dashboard `WidgetGrid` is currently rendered only for automotive-transport orgs (verified at `frontend/src/pages/dashboard/OrgAdminDashboard.tsx:346`); P5's payroll widgets apply to all 16 trade families.

- [ ] **PREREQ-1.** Resolve STAFF-011 (Option A: drop `tradeFamily` gate around `WidgetGrid`; Option B: build separate `/payroll/dashboard` surface). If Option A: this becomes a single `OrgAdminDashboard.tsx` patch. If Option B: add a new Workstream A0 building the payroll-dashboard route + page shell. Without this resolution, A1-A6 ship widgets that 15 of 16 trade families never see.

## Workstream A — Dashboard widgets (per dashboard-widget-gating.md 10-step process)

- [ ] **A1. `WIDGET_DEFINITIONS` entries (P5-N5 + P5-N6 + P5-N7)** — at `frontend/src/pages/dashboard/widgets/WidgetGrid.tsx`:
  - Entry 1: `{ id: 'labour-cost-vs-revenue', title: 'Labour cost vs revenue', module: 'payroll', defaultOrder: 11 }` — gate on `payroll` (NOT `staff_management`) because the widget reads `payslips.gross_pay`.
  - Entry 2: `{ id: 'wage-forecast', title: 'Wage forecast', module: 'staff_management', defaultOrder: 12 }` — gate on `staff_management` because the widget reads schedule/staff/leave/overtime, all of which exist before payroll ships.
  - Pre-flight: re-check the existing `WIDGET_DEFINITIONS` list for any entry already at `defaultOrder: 11` or `12` and bump P5's slots if needed.
  - **IDs are kebab-case** (existing convention); the corresponding **backend `DashboardWidgetData` field names are snake_case** (`labour_cost_vs_revenue`, `wage_forecast`).
- [ ] **A2. `dashboard_service.get_labour_cost_vs_revenue`** with SAVEPOINT per-widget try/except. **Verify (P5-N2):** the SQL query uses `Invoice.total` (NOT `total_amount` — column doesn't exist; verified at `app/modules/invoices/models.py:184`). Status filter uses values from the actual `ck_invoices_status` CHECK constraint enum at `models.py:238`.
- [ ] **A3. `dashboard_service.get_wage_forecast`** same pattern. **Verify (P5-N3):** the schedule_entries filter uses `status IN ('scheduled','completed')` — the actual `ENTRY_STATUSES` enum at `app/modules/scheduling_v2/models.py:21`. The earlier draft said "published" — that status value does not exist.
- [ ] **A4. Pydantic schemas** added to `DashboardWidgetsResponse` at `app/modules/organisations/schemas.py`. New fields: `labour_cost_vs_revenue: WidgetDataSection[LabourCostItem]` and `wage_forecast: WidgetDataSection[WageForecastItem]`. Plus the two new item schemas (`LabourCostItem` with `period: str, labour: Decimal, revenue: Decimal, pct: Decimal | None` and `WageForecastItem` with `label: str, forecast: Decimal`). Wire each into `get_all_widget_data()` aggregator with try/except per the existing `_safe_call()` pattern at `dashboard_service.py:847`.
- [ ] **A5. `useDashboardWidgets.ts`** normalisation entries — add `labour_cost_vs_revenue: { items: raw.labour_cost_vs_revenue?.items ?? [], total: raw.labour_cost_vs_revenue?.total ?? 0 }` and equivalent for `wage_forecast`. Plus the two new TypeScript interfaces in `types.ts` and the new fields on `DashboardWidgetData`.
- [ ] **A6. `LabourCostVsRevenueWidget.tsx` + `WageForecastWidget.tsx`** with `WidgetCard` wrapper + empty state INSIDE children (P5-N4: `WidgetCard` does NOT accept `empty`/`emptyText` props — verified at `WidgetCard.tsx:14-21`; the empty state is conditional rendering inside `children`, matching all 9 existing widgets).
- [ ] **A6a. `renderWidget()` switch case (dashboard-widget-gating step 9c)** — add cases in `WidgetGrid.tsx::renderWidget()` for `'labour-cost-vs-revenue'` and `'wage-forecast'` returning the widget components with `data={data?.labour_cost_vs_revenue}` / `data={data?.wage_forecast}` plus `isLoading` and `error` props.
- [ ] **A7. Property test** in `tests/test_dashboard_widgets.py` covering both calcs. **Plus:** P5 introduces NO new module slugs (uses existing `staff_management` and `payroll`), so `frontend/src/pages/dashboard/widgets/__tests__/moduleGating.property.test.ts` only needs the new widget IDs added to its mirror `WIDGET_DEFINITIONS` constant — no new module slug needs registering in the test.

## Workstream B — Reports backend

- [ ] **B1. `app/modules/payroll_reports/service.py`** — attendance_patterns, leave_projection, staff_calendar functions.
- [ ] **B2. `app/modules/payroll_reports/bank_files.py`** — start with BNZ Multi-Pay; framework supports adding others. **(P5-N10) Schema lookup is BLOCKING:** before writing `format_row(BNZ_MULTIPAY, ...)`, fetch the BNZ Multi-Pay batch-credit CSV specification from BNZ's developer/business banking docs. Document the column list + sample row + delimiter convention in a code comment at the top of the module. Verify: end-to-end test exports a CSV and a unit test diffs it byte-for-byte against a fixture file containing a known-good BNZ-format example.
- [ ] **B3. `app/modules/payroll_reports/ird_export.py`** — streaming CSV.
- [ ] **B4. Router** with all 5 endpoints. IRD-export gated by org_admin.
- [ ] **B5. Register in `app/main.py`**.

## Workstream C — Frontend

- [ ] **C1. `AttendancePatternsPage.tsx`, `LeaveProjectionPage.tsx`, `StaffCalendarPage.tsx`, `BankFileExportPage.tsx`, `IRDExportPage.tsx`**.
- [ ] **C2. Sidebar entries** under Reports.
- [ ] **C3. Format-picker + ExportConfirmModal** on bank file page.
- [ ] **C4. Route guard** for IRD export (org_admin only).

## Workstream D — Tests

- [ ] **D1. Unit tests** — bank file CSV format matches BNZ spec; IRD export shape.
- [ ] **D2. Property test** — labour_cost_vs_revenue calc invariants.
- [ ] **D3. E2E** `scripts/test_staff_reporting_e2e.py` per source plan.

## Workstream E — Versioning + docs

- [ ] **E1. Bump 1.17.0 → 1.18.0**.
- [ ] **E2. CHANGELOG `## [1.18.0]`** — labour cost / wage forecast widgets, attendance patterns, leave projection, staff calendar, bank file export (BNZ first), IRD export.
- [ ] **E3. STAFF-004** in ISSUE_TRACKER closed (BNZ chosen first; expansion logged separately).

## Pre-merge gate

Per source plan §12. Specifically:
- **STAFF-011 resolved (P5-N1 + P5-N8)** — trade-family gating decision applied; payroll widgets visible to all 16 trade families.
- BNZ Multi-Pay CSV diffs 100% against BNZ's spec (P5-N10).
- IRD export columns match myIR upload shape.
- **Each widget passes the dashboard-widget-gating 10-step checklist (P5-N12):**
  1. Backend service function with branch scoping + try/except per-widget.
  2. Pydantic schema added (`LabourCostItem`, `WageForecastItem`).
  3. Wired into `get_all_widget_data()` aggregator with `_safe_call()` per-widget pattern.
  4. Field on `DashboardWidgetsResponse` (`labour_cost_vs_revenue`, `wage_forecast`).
  5. TypeScript type in `types.ts` (matches Pydantic shape exactly).
  6. Field on `DashboardWidgetData`.
  7. Normalisation in `useDashboardWidgets.ts` (`?.items ?? []`, `?.total ?? 0`).
  8. Component file with `WidgetCard` wrapper + `?.`/`?? []` patterns + empty state inside children (NOT a `WidgetCard` prop — P5-N4).
  9. Registered in `WIDGET_DEFINITIONS` (kebab-case `id`, snake_case backend field) AND case in `renderWidget()` switch.
  10. Tests: backend property test + frontend empty-state test + `moduleGating.property.test.ts` mirror updated for the two new IDs (no new module slug for P5).
- Bank export decrypts only inside the generator; never returned in any other API response. Listed in P4 design §10's authorised-decryption-paths registry (cross-phase X6).
- IRD export restricted to org_admin via `dependencies=[require_role("org_admin")]` (matches existing `app/modules/reports/router.py` convention).
- Streaming response (no in-memory build) — uses `fastapi.responses.StreamingResponse` with `AsyncIterator[bytes]` per the existing `data_io/router.py` pattern.
- Audit rows for `bank_file.exported` and `ird_export.generated` written to the `audit_log` table (singular per cross-phase convention).
- **Per-widget module gate is correct (P5-N7):** `labour-cost-vs-revenue` gates on `payroll`; `wage-forecast` gates on `staff_management`.
- **Backend SQL uses `Invoice.total` (P5-N2)** — not `total_amount` (column doesn't exist).
- **Schedule filter uses `status IN ('scheduled','completed')` (P5-N3)** — not the non-existent `'published'`.

**P5-N1–P5-N12 closure ticks (added 2026-05-31 code-vs-spec + internal-alignment audit)**
- [ ] P5-N1: STAFF-011 resolved; widgets visible to all trade families (Option A removes `tradeFamily` gate around `WidgetGrid`).
- [ ] P5-N2: SQL queries `invoices.total` (NOT `total_amount`); verified at `app/modules/invoices/models.py:184`.
- [ ] P5-N3: Wage-forecast filter uses `status IN ('scheduled','completed')` per actual `ENTRY_STATUSES` enum.
- [ ] P5-N4: `WidgetCard` rendered with only its actual props (`title, icon, actionLink, children, isLoading, error`); empty state inside `children`.
- [ ] P5-N5: Frontend uses kebab-case IDs (`'labour-cost-vs-revenue'`, `'wage-forecast'`); backend uses snake_case field names.
- [ ] P5-N6: `defaultOrder: 11` and `12` checked for collisions before merge.
- [ ] P5-N7: `labour-cost-vs-revenue` gates on `payroll`; `wage-forecast` gates on `staff_management`.
- [ ] P5-N8: STAFF-011 hard prereq satisfied before A1 starts.
- [ ] P5-N9: All audit table refs use `audit_log` singular (verified — no fix needed).
- [ ] P5-N10: BNZ Multi-Pay CSV format documented from BNZ's spec sheet before B2 implementation.
- [ ] P5-N11: dashboard-widget-gating 10-step checklist applied; A6a renderWidget() switch case added; A7 covers moduleGating.property.test.ts mirror update.
- [ ] P5-N12: Pre-merge gate explicitly enumerates all 10 widget-gating steps.

## Auto-advance — end of staff-management spec series

Phase 5 is the final phase in the staff-management spec series (P1 → P2 → P3 → P4 → P5). When every checkbox above is ticked, the entire staff-management initiative is complete.

- [ ] **DONE. All five staff-management phases shipped.** Final state: alembic head at 0210, app version 1.18.0, full NZ-employment-law-compliant staff/payroll surface deployed (employment record + roster delivery → leave engine + Holidays Act compliance → clock-in/out + hours approval + operational layer → payslips + termination payouts → reporting + bank export). Update `docs/future/staff-management-system.md` master plan with `Status: shipped — see CHANGELOG [1.14.0] through [1.18.0]`. Close STAFF-001 through STAFF-010 in `docs/ISSUE_TRACKER.md`.

There is no next phase to advance to — the auto-advance chain ends here.


---

## Deferral log

**2026-06-01 — Phase 5 deferred — no customer demand recorded.**

Reached the auto-advance entrypoint at the close of Phase 4. Per the Execution policy "Deferral path" rule above:

- STAFF-011 has not been resolved. The dashboard `WidgetGrid` remains automotive-transport-gated; the cross-trade-family decision (Option A drop-the-gate vs Option B build-separate-payroll-dashboard) is still open and requires product input.
- `docs/ISSUE_TRACKER.md` shows no signal of customer demand for Phase 5 features (reports / bank-file export / IRD export / dashboard widgets).
- Phase 4 (production payroll engine) ships standalone with no Phase 5 dependency. Deferring Phase 5 has no functional impact on the deployed payroll surface.

When customer demand surfaces — either as a STAFF-011 resolution or an issue tracker entry asking for any of the Phase 5 deliverables — re-open this file and start at PREREQ-1.
