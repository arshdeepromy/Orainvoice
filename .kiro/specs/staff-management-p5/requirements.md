# Staff Management — Phase 5: Reporting + Wage Forecasting + Bank Export

## Overview

Phase 5 surfaces the visibility owners actually use to run the business and produces the export their bank accepts in one try. Optional, fully-deferrable phase.

**Source:** `docs/future/staff-management-system.md` Phase 5.

**Status:** Draft, depends on Phases 1–4. **Optional / deferrable** — only implement when customer demand exists.

## Hard prerequisites (P5-N1 + P5-N8)

P5 cannot start widget implementation until **STAFF-011** is resolved (see Open Questions). The dashboard `WidgetGrid` is currently gated by the trade-family check `(tradeFamily ?? 'automotive-transport') === 'automotive-transport'` at `frontend/src/pages/dashboard/OrgAdminDashboard.tsx:346`. P5's two new widgets (labour cost + wage forecast) are payroll-related and apply to all 16 trade families — without resolving STAFF-011, the widgets ship invisible to 15 of 16 trade families even when payroll is fully running.

**Recommended resolution (Option A):** drop the `tradeFamily` gate around `WidgetGrid` since the dashboard infrastructure should be universal. The gate was added when the platform was automotive-only and is now obsolete. Each widget retains its own per-module gate via `WIDGET_DEFINITIONS`, which is the correct level for fine-grained visibility.

**Alternative (Option B):** ship the two payroll widgets in a NEW dedicated `/payroll/dashboard` surface, not the existing `WidgetGrid`. Adds a new task workstream.

## Steering compliance

- Dashboard widgets follow the 10-step process in `dashboard-widget-gating.md`.
- Bank-file CSVs render via streaming response (no big in-memory build).
- IRD-friendly export is CSV — we are not filing for the org.
- All reports respect RLS + branch-scope.

## Requirements

### R1. Labour Cost vs Revenue Dashboard Widget

**Acceptance criteria:**

1. THE SYSTEM SHALL add a `WIDGET_DEFINITIONS` entry per the dashboard-widget-gating convention (P5-N5):
   - **Frontend `WIDGET_DEFINITIONS.id`:** `'labour-cost-vs-revenue'` (kebab-case per existing convention).
   - **Backend `DashboardWidgetData` field:** `labour_cost_vs_revenue` (snake_case per existing Pydantic convention).
   - **Module gate (P5-N7):** `module: 'payroll'` — NOT `'staff_management'`. Reason: this widget reads `payslips.gross_pay` which only exists when P4's `payroll` module is enabled. Gating on `staff_management` would render the widget for orgs that have staff but no payroll, showing $0 / no-data perpetually.
   - `defaultOrder: 11` (P5-N6: re-check `WidgetGrid.tsx::WIDGET_DEFINITIONS` for collisions before merge — bump if 11 is taken).
2. Backend service function in `dashboard_service.py::get_labour_cost_vs_revenue(db, org_id, branch_id)` returns `WidgetDataSection[LabourCostItem]` with try/except per-widget (mirrors `get_recent_customers` + `get_public_holidays` SAVEPOINT pattern at `dashboard_service.py:184` and `:264`).
3. Computes: `labour_cost = SUM(payslips.gross_pay) over rolling 7d/30d/YTD`; `revenue = SUM(invoices.total) over same window` (P5-N2 fix: column is `total`, NOT `total_amount` — verified at `app/modules/invoices/models.py:184`). Joined on org_id; branch-filtered.
4. Returns `{ items: [{period:'7d',labour:X,revenue:Y,pct:X/Y}, ...], total: 3 }`.
5. Pydantic schema added to `DashboardWidgetsResponse`.
6. Normalisation in `useDashboardWidgets.ts`.
7. Property test in `tests/test_dashboard_widgets.py` covers the calc with synthetic data.

### R2. Wage Forecast Widget

**Acceptance criteria:**

1. Add a `WIDGET_DEFINITIONS` entry per the dashboard-widget-gating convention (P5-N5):
   - **Frontend `WIDGET_DEFINITIONS.id`:** `'wage-forecast'` (kebab-case).
   - **Backend `DashboardWidgetData` field:** `wage_forecast` (snake_case).
   - **Module gate:** `module: 'staff_management'` (NOT `payroll` — this widget reads schedule_entries + staff_members + leave_requests + overtime_requests which all exist before payroll ships, so the widget produces useful output even without P4 deployed; per P5-N7 differentiation).
   - `defaultOrder: 12` (P5-N6 collision pre-flight applies).
2. Computes Monday-morning view: non-cancelled `schedule_entries` (`status IN ('scheduled', 'completed')` per the actual `ENTRY_STATUSES` enum at `app/modules/scheduling_v2/models.py:21` — P5-N3 fix: previously said "published" which doesn't exist) for the current week × `staff_members.hourly_rate` × expected leave (approved leave_requests in week) × overtime estimate (sum of approved overtime_requests).
3. Returns `{ items: [{label:'This week',forecast:X}, ...], total: 1 }`.

### R3. Attendance Patterns Report

**Acceptance criteria:**

1. THE SYSTEM SHALL add `/reports/attendance-patterns?from=&to=` returning per-staff:
   - Late-arrival count + average minutes late.
   - No-show count.
   - Missed-clock-out frequency.
   - Average hours per week, rolling.
2. Frontend renders sortable table; export CSV.

### R4. Leave Projection

**Acceptance criteria:**

1. THE SYSTEM SHALL add `/reports/leave-projection?days=30` returning approved leave_requests in next N days with hours per leave type.
2. Surfaces "in next 30 days, X staff have approved leave covering Y hours" — helps cover planning.

### R5. Anniversary / Probation / Visa Calendar

**Acceptance criteria:**

1. THE SYSTEM SHALL add `/reports/staff-calendar?from=&to=` listing upcoming pay-review anniversaries, probation end dates, employment-contract anniversaries, visa expiries.
2. Frontend renders calendar grid + list view toggle.

### R6. Bank-File Export (CSV)

**Acceptance criteria:**

1. THE SYSTEM SHALL add `/reports/bank-file?pay_period_id=:id&format=:bank` returning CSV.
2. `format` enum: `bnz_multipay | anz_direct_credit | asb | westpac | kiwibank`.
3. Each format produces a CSV matching that bank's batch-credit schema (research before implementation; STAFF-004 settles which to ship first).
4. Includes only finalised payslips; excludes voided.
5. Streams the response (chunked, low memory).
6. Audit: `bank_file.exported`.

### R7. IRD-Friendly Export

**Acceptance criteria:**

1. THE SYSTEM SHALL add `/reports/ird-export?pay_period_id=:id` returning CSV with columns: employee_name, ird_number (full, decrypted server-side), gross, paye, kiwisaver_employee, kiwisaver_employer, esct (placeholder column for future).
2. Restricted to `org_admin` only.
3. Shape that matches what orgs paste into myIR (we're not auto-filing).
4. Audit: `ird_export.generated`.

### R8. Versioning

THE SYSTEM SHALL bump 1.17.0 → 1.18.0.

## Non-Goals

- Auto-filing IRD employer information / IR348 (regulated; out of scope).
- Wage-cost forecasting machine-learning. Phase 5 forecasts are simple sum-times-rate math.
- Historical revenue + labour rebase (data already in place).

## Open Questions

- **STAFF-004:** Which bank format ships first. Recommend BNZ Multi-Pay (most common in NZ SME workshops). Settle before implementation; the framework supports adding more formats post-launch as plugins.
- **STAFF-011 (BLOCKING for P5 widget work):** Resolve trade-family gating of payroll widgets. The dashboard `WidgetGrid` is currently rendered only for automotive-transport orgs (verified at `frontend/src/pages/dashboard/OrgAdminDashboard.tsx:346`). P5's two new widgets are payroll-related and apply to all 16 trade families. **Recommend Option A**: drop the `tradeFamily` gate around `WidgetGrid` since the dashboard infrastructure should be universal; each widget retains its own per-module gate via `WIDGET_DEFINITIONS`. **Alternative Option B**: ship a separate `/payroll/dashboard` surface for payroll widgets (adds a new task workstream). Settle before P5 A1 starts.
