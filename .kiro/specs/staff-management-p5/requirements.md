# Staff Management — Phase 5: Reporting + Wage Forecasting + Bank Export

## Overview

Phase 5 surfaces the visibility owners actually use to run the business and produces the export their bank accepts in one try. Optional, fully-deferrable phase.

**Source:** `docs/future/staff-management-system.md` Phase 5.

**Status:** Draft, depends on Phases 1–4. **Optional / deferrable** — only implement when customer demand exists.

## Steering compliance

- Dashboard widgets follow the 10-step process in `dashboard-widget-gating.md`.
- Bank-file CSVs render via streaming response (no big in-memory build).
- IRD-friendly export is CSV — we are not filing for the org.
- All reports respect RLS + branch-scope.

## Requirements

### R1. Labour Cost vs Revenue Dashboard Widget

**Acceptance criteria:**

1. THE SYSTEM SHALL add `WIDGET_DEFINITIONS` entry `labour_cost_vs_revenue` with `module: 'staff_management'`, `defaultOrder: 11`.
2. Backend service function in `dashboard_service.py::get_labour_cost_vs_revenue(db, org_id, branch_id)` returns `WidgetDataSection[LabourCostItem]` with try/except per-widget.
3. Computes: `labour_cost = SUM(payslips.gross_pay) over rolling 7d/30d/YTD`; `revenue = SUM(invoices.total_amount) over same window` (joined on org_id; branch-filtered).
4. Returns `{ items: [{period:'7d',labour:X,revenue:Y,pct:X/Y}, ...], total: 3 }`.
5. Pydantic schema added to `DashboardWidgetsResponse`.
6. Normalisation in `useDashboardWidgets.ts`.
7. Property test in `tests/test_dashboard_widgets.py` covers the calc with synthetic data.

### R2. Wage Forecast Widget

**Acceptance criteria:**

1. Add `WIDGET_DEFINITIONS` entry `wage_forecast` with `module: 'staff_management'`, `defaultOrder: 12`.
2. Computes Monday-morning view: published `schedule_entries` for the current week × `staff_members.hourly_rate` × expected leave (approved leave_requests in week) × overtime estimate (sum of approved overtime_requests).
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
