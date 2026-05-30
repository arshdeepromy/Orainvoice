# Staff Management Phase 5 — Tasks

## Workstream A — Dashboard widgets (per dashboard-widget-gating.md 10-step process)

- [ ] **A1. `WIDGET_DEFINITIONS` entries** — `labour_cost_vs_revenue` + `wage_forecast`. `module: 'staff_management'`.
- [ ] **A2. `dashboard_service.get_labour_cost_vs_revenue`** with SAVEPOINT per-widget try/except.
- [ ] **A3. `dashboard_service.get_wage_forecast`** same pattern.
- [ ] **A4. Pydantic schemas** added to `DashboardWidgetsResponse`.
- [ ] **A5. `useDashboardWidgets.ts`** normalisation entries.
- [ ] **A6. `LabourCostVsRevenueWidget.tsx` + `WageForecastWidget.tsx`** with WidgetCard + empty state.
- [ ] **A7. Property test** in `tests/test_dashboard_widgets.py` covering both calcs.

## Workstream B — Reports backend

- [ ] **B1. `app/modules/payroll_reports/service.py`** — attendance_patterns, leave_projection, staff_calendar functions.
- [ ] **B2. `app/modules/payroll_reports/bank_files.py`** — start with BNZ Multi-Pay; framework supports adding others.
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
- BNZ Multi-Pay CSV diffs 100% against BNZ's spec.
- IRD export columns match myIR upload shape.
- Both new widgets follow all 10 steps of dashboard-widget-gating.
- Bank export decrypts only inside the generator; never returned in any other API response.
- IRD export restricted to org_admin.
- Streaming response (no in-memory build).
- Audit rows for `bank_file.exported` and `ird_export.generated`.
