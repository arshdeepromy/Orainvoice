# Implementation Plan: Reports Remediation

## Overview

This plan converts the approved design (`design.md`) and requirements (`requirements.md`, R1–R21) into an incremental, backward-compatible implementation. Work is sequenced so that every backend field/endpoint lands (with pytest coverage) **before** the frontend mapping that consumes it, keeping backend and frontend coherent at each step.

The design uses concrete Python (backend) and TypeScript (frontend), so no implementation-language selection is required. The design includes a **Correctness Properties** section (P1–P6), so property-based test sub-tasks are included using **Hypothesis** (Python backend) and **fast-check** (TypeScript frontend), each annotated with its property number and the requirement clause it validates.

### Standing constraints (apply to EVERY task)

- **Backend changes are additive + backward-compatible.** Never remove or rename an existing response field; add aliases alongside (R18.2–18.4). With no `export` param, every `/reports/*` endpoint returns the same JSON shape as before (R18.5). No DB migration (R18.6).
- **Frontend work is `frontend-v2/` only.** NEVER touch `frontend/`, `docker-compose*` files, or nginx (R18.1, R18.7, R21.2). Build/test commands MUST run with `cwd` set to `frontend-v2` — never use `cd`.
- **Safe API consumption is mandatory** on all new/edited frontend code: typed generics on every `apiClient.get`, `?.` on nested reads, `?? []` on arrays, `?? 0` on numbers, `AbortController` in every fetching effect (R14, R19; steering `safe-api-consumption.md`).
- **v2 design tokens** for all new/rebuilt UI (R21.1; steering `frontend-redesign.md`).
- **Backend patterns:** async SQLAlchemy, `org_id` + optional `branch_id` scoping, RLS-aware, retain `require_role` guards, all list responses wrapped in objects, WeasyPrint via `asyncio.to_thread` (R20).
- Tasks marked with `*` are optional (tests) and can be skipped for a faster MVP. Top-level tasks are never optional.

---

## Tasks

- [ ] 1. Backend A1 — Revenue `monthly_breakdown` + `total_invoices` alias
  - [ ] 1.1 Add nested schema + fields to `RevenueSummaryResponse`
    - In `app/modules/reports/schemas.py`, add `class RevenueMonthPoint(BaseModel)` with `month: str` and `revenue: Decimal`.
    - Add `total_invoices: int = Field(0, ...)` and `monthly_breakdown: list[RevenueMonthPoint] = Field(default_factory=list)` to `RevenueSummaryResponse`, keeping all existing fields (`invoice_count` retained).
    - _Requirements: 1.1, 1.2, 1.3, 18.2, 18.4_
    - _Design: §"Data Models & Schema Changes" rows 1–2, §"A1 — Revenue"_
  - [ ] 1.2 Compute `monthly_breakdown` + `total_invoices` in `get_revenue_summary`
    - In `app/modules/reports/service.py :: get_revenue_summary`, add the monthly grouped aggregate (`func.to_char(Invoice.issue_date, "YYYY-MM")`, GST-inclusive `total * exchange_rate_to_nzd`), reusing the existing filters (non-voided, non-draft, issue_date in range) and branch scoping; sort ascending by month.
    - Add `"total_invoices": count` and `"monthly_breakdown": monthly_breakdown` to the returned dict; leave all existing keys unchanged.
    - _Requirements: 1.1, 1.2, 1.3, 20.1, 20.2, 20.3_
    - _Design: §"A1 — Revenue" backend pseudocode_
  - [ ]* 1.3 Write property test for revenue monthly breakdown (Hypothesis)
    - **Property 1: Revenue monthly breakdown sums to the period total and the alias mirrors the count**
    - Assert `Σ monthly_breakdown[i].revenue == total_inclusive` (±0.01) and `total_invoices == invoice_count` over arbitrary invoice datasets.
    - **Validates: Requirements 1.1, 1.2, 1.3**
  - [ ]* 1.4 Write unit/integration test for revenue endpoint
    - Assert `monthly_breakdown` present, sorted ascending; `total_invoices == invoice_count`; with no `export` param the response shape is otherwise unchanged.
    - _Requirements: 1.1, 1.3, 18.5_

- [ ] 2. Backend A5 — Fleet `vehicles[]` breakdown
  - [ ] 2.1 Add `FleetVehicleRow` + `vehicles` to `FleetReportResponse`
    - In `schemas.py`, add `class FleetVehicleRow(BaseModel)` with `rego: str`, `make: str | None`, `model: str | None`, `total_spend: Decimal`, `last_service_date: date | None`.
    - Add `vehicles: list[FleetVehicleRow] = Field(default_factory=list)` to `FleetReportResponse` (all existing fields retained).
    - _Requirements: 6.1, 6.2, 18.4_
    - _Design: §"Data Models & Schema Changes" row 3, §"A5 — Fleet"_
  - [ ] 2.2 Add per-vehicle aggregate to `get_fleet_report`
    - In `service.py :: get_fleet_report`, add a grouped query over the fleet's customers (`vehicle_rego`, `vehicle_make`, `vehicle_model`, `sum(total)`, `max(issue_date)`), non-voided/non-draft, rego not null, within the period; return `"vehicles": vehicles` (and `[]` on the empty-fleet branch).
    - _Requirements: 6.1, 6.2, 20.1, 20.2_
    - _Design: §"A5 — Fleet" backend pseudocode_
  - [ ]* 2.3 Write unit test for fleet vehicles aggregate
    - Assert `vehicles[]` present; `Σ vehicles[i].total_spend <= total_spend`; empty list when no qualifying vehicles.
    - _Requirements: 6.1, 6.2_

- [ ] 3. Backend A6 — Storage breakdown via `calculate_org_storage`
  - [ ] 3.1 Populate real `breakdown` in `get_storage_usage`
    - In `service.py :: get_storage_usage`, import and call `app.modules.storage.service.calculate_org_storage(db, org_id)` and return its per-category `breakdown` instead of the hard-coded `[]`. `StorageUsageResponse.breakdown` already exists — no schema change.
    - _Requirements: 7.1, 20.1_
    - _Design: §"Data Models & Schema Changes" row 4, §"A6 — Storage breakdown"_
  - [ ]* 3.2 Write unit test for storage breakdown
    - Assert `breakdown` is non-empty when the org has storage data; `{category, bytes}` shape.
    - _Requirements: 7.1_

- [ ] 4. Backend C4 — SMS `daily_breakdown`
  - [ ] 4.1 Add `SmsDailyPoint` + `daily_breakdown` to `SmsUsageResponse`
    - In `schemas.py`, add `class SmsDailyPoint(BaseModel)` with `date: date` and `sms_count: int`; add `daily_breakdown: list[SmsDailyPoint] = Field(default_factory=list)` to `SmsUsageResponse` (all existing fields retained).
    - _Requirements: 9.1, 18.4_
    - _Design: §"Data Models & Schema Changes" row 5, §"C4 — SMS daily breakdown"_
  - [ ] 4.2 Compute daily series in `get_sms_usage`
    - In `service.py :: get_sms_usage`, add a `generate_series` daily query summing outbound `sms_messages` + non-failed `notification_log` SMS per day within the period; return `"daily_breakdown": daily_breakdown`.
    - _Requirements: 9.1, 9.2, 20.1, 20.3_
    - _Design: §"C4 — SMS daily breakdown" backend pseudocode_
  - [ ]* 4.3 Write property test for SMS daily breakdown (Hypothesis)
    - **Property 6: SMS daily breakdown sums to the total sent**
    - Assert `Σ daily_breakdown[i].sms_count == total_sent` over arbitrary outbound-message datasets in range.
    - **Validates: Requirements 9.2**

- [ ] 5. Backend C3 — `GET /org/plan-sms-pricing` endpoint
  - [ ] 5.1 Add `PlanSmsPricingResponse` schema
    - Add `class PlanSmsPricingResponse(BaseModel)` with `sms_package_pricing: list[SmsPackageTierPricing]` (reuse the admin tier schema shape) in the appropriate org/reports schema module.
    - _Requirements: 8.1, 8.2_
    - _Design: §"Data Models & Schema Changes" row 7, §"C3 — SMS package tiers"_
  - [ ] 5.2 Add the `org_admin`-gated endpoint
    - In `app/modules/organisations/router.py`, add `GET /plan-sms-pricing` (`dependencies=[require_role("org_admin")]`) that reads the org plan's `sms_package_pricing` (join `Organisation` → `SubscriptionPlan`) and returns `PlanSmsPricingResponse(sms_package_pricing=row or [])`.
    - _Requirements: 8.1, 8.2, 20.4_
    - _Design: §"C3 — SMS package tiers" backend pseudocode_
  - [ ]* 5.3 Write unit test for plan-sms-pricing endpoint
    - Assert tiers returned for a plan that has them; `[]` when the plan has none; `org_admin` guard enforced.
    - _Requirements: 8.1, 8.2_

- [ ] 6. Backend C1 — Server-side export layer (`reports/export.py` + router wiring)
  - [ ] 6.1 Create the CSV registry + renderers in `app/modules/reports/export.py`
    - Add a `CSV_BUILDERS` registry mapping each report key (`revenue`, `invoice_status`, `top_services`, `outstanding`, `gst_return`, `fleet`, `storage`, `sms`, `carjam`, `customer_statement`) to a `(header, rows)` builder; numeric cells formatted to 2dp.
    - Add pure `render_report_csv(report_key, data) -> bytes` (UTF-8 CSV).
    - _Requirements: 10.3, 10.5_
    - _Design: §"C1 — Export layer" `export.py` pseudocode_
  - [ ] 6.2 Add the WeasyPrint PDF renderer (off-loop)
    - Add `async def render_report_pdf(report_key, data, org) -> bytes` that renders a Jinja template (with a generic fallback) and runs `await asyncio.to_thread(lambda: HTML(string=html).write_pdf())`. Create `app/modules/reports/templates/` with a `generic.html` (v2-styled) and per-report templates as needed.
    - _Requirements: 10.4, 20.5_
    - _Design: §"C1 — Export layer", §"Export flow (C1)" sequence diagram, §"Performance Considerations"_
  - [ ] 6.3 Add the `_maybe_export` router helper and wire it into every `/reports/*` endpoint
    - In `app/modules/reports/router.py`, add `async def _maybe_export(report_key, export, data, db, org_id)` returning a `StreamingResponse` (with `Content-Disposition: attachment; filename="{report_key}_{YYYY-MM-DD}.{ext}"` and correct media type) when `export` is set, else `None`.
    - In each report endpoint (revenue, invoices/status, outstanding, top-services, gst-return, customer-statement, carjam-usage, sms-usage, storage, fleet), after building `data`, call `_maybe_export(...)` and return it when non-None; otherwise return the existing `response_model`. Endpoints that lack an `export` Query param gain one.
    - _Requirements: 10.3, 10.4, 18.5, 20.6_
    - _Design: §"C1 — Export layer" router pseudocode, §"Request / Response Contracts"_
  - [ ]* 6.4 Write property test for CSV round-trip (Hypothesis)
    - **Property 3: CSV export round-trips the report figures**
    - Parse the CSV from `render_report_csv(key, data)` and assert each numeric figure equals the report dict figure to 2dp.
    - **Validates: Requirements 10.5**
  - [ ]* 6.5 Write integration tests for export endpoints
    - Assert `export=csv` → `text/csv` + `Content-Disposition` filename `{report_key}_{YYYY-MM-DD}.csv`; `export=pdf` → `application/pdf` + matching filename. Golden-file a representative CSV.
    - _Requirements: 10.3, 10.4_

- [ ] 7. Backend backward-compatibility checkpoint
  - [ ]* 7.1 Write backward-compat assertion tests
    - For every `/reports/*` endpoint: with no `export` param, the JSON response retains all pre-feature fields and shape (R18.5); `invoice_count` is present alongside `total_invoices` (R18.2); new fields are additive (R18.4); no migration involved (R18.6).
    - _Requirements: 18.2, 18.4, 18.5, 18.6_
  - [ ] 7.2 Checkpoint — run the full backend pytest suite
    - Ensure all backend tests pass, ask the user if questions arise.

- [ ] 8. Frontend A1 — Revenue tab field mapping + safety (`RevenueSummary.tsx`)
  - [ ] 8.1 Map corrected fields and add D1/D3 safety
    - Read `data.total_invoices ?? data.invoice_count ?? 0` and `data.monthly_breakdown ?? []`; render the monthly chart via `SimpleBarChart` when non-empty, else the empty-state message. Add `AbortController` + typed generic on the `apiClient.get`; seed range from `presetRange('month')`.
    - _Requirements: 1.4, 1.5, 1.6, 14.1, 14.2, 19.1, 19.2, 19.3, 19.5, 21.1_
    - _Design: §"A1 — Revenue" frontend snippet, §"D1 — AbortController", §"D3 — Safe reads"_
  - [ ]* 8.2 Write Vitest+RTL test for Revenue tab
    - Renders invoice count from `total_invoices`/`invoice_count`; renders monthly chart from `monthly_breakdown`; shows empty state when absent.
    - _Requirements: 1.4, 1.5, 1.6_

- [ ] 9. Frontend A2 — Invoice Status tab (`InvoiceStatus.tsx`)
  - [ ] 9.1 Map `breakdown`/`total`, compute total, add safety
    - Read rows from `data.breakdown ?? []`; render amount from `r.total`; compute total-invoices as `Σ (r.count ?? 0)`; empty state when no rows. Add `AbortController`, typed generic, safe reads.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 14.1, 14.2, 19.1, 19.2, 19.3, 19.5, 21.1_
    - _Design: §"A2 — Invoice Status", §"Request / Response Contracts"_
  - [ ]* 9.2 Write property test for invoice-status total (fast-check)
    - **Property 2: Invoice-status counts sum to the total invoice count**
    - For arbitrary breakdowns, `Σ breakdown[i].count` equals the displayed total-invoices figure.
    - **Validates: Requirements 2.3**

- [ ] 10. Frontend A3 — Top Services tab (`TopServices.tsx`)
  - [ ] 10.1 Map `description`/`total_revenue`, add safety
    - Read rows from `data.services ?? []`; render name from `s.description` and revenue from `s.total_revenue`; empty state when none. Add `AbortController`, typed generic, safe reads.
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 14.1, 14.2, 19.1, 19.2, 19.3, 19.5, 21.1_
    - _Design: §"A3 — Top Services", §"Request / Response Contracts"_
  - [ ]* 10.2 Write Vitest+RTL test for Top Services tab
    - Renders `description` + `total_revenue`; empty state when `services` absent/empty.
    - _Requirements: 3.2, 3.3, 3.4_

- [ ] 11. Frontend A4 + C2 + B1 — Outstanding tab (`OutstandingInvoices.tsx`)
  - [ ] 11.1 Map fields, derive status, remove date filter
    - Use `inv.invoice_id ?? i` as key; show `inv.vehicle_rego ?? '—'`; derive status from `days_overdue` (`> 0` → "Overdue"/danger, else "Outstanding"/warn); empty state when no invoices. Remove the `DateRangeFilter` and omit `start_date`/`end_date` from fetch + export params (B1).
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 11.1, 11.2, 11.3, 19.1, 19.5, 21.1_
    - _Design: §"A4 + C2 — Outstanding", §"B1 — Outstanding date filter"_
  - [ ] 11.2 Fix Send Reminder + add D1/D2 safety
    - POST `/invoices/${invoice_id}/send-reminder` with body `{ channel: 'email' }` for a non-empty `invoice_id`; success toast on 200; error toast using backend `detail` on failure. Add `AbortController`, include `selectedBranchId` in the fetch `useCallback` deps (D2).
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 14.1, 14.3_
    - _Design: §"A4 + C2 — Outstanding" send-reminder snippet, §"Send Reminder (C2)" sequence diagram, §"D2 — Dependency arrays"_
  - [ ]* 11.3 Write Vitest+RTL test for Outstanding tab + reminder
    - Status derived from `days_overdue`; rego/key mapping; reminder POSTs to `/invoices/{invoice_id}/send-reminder` (never `undefined`); no date filter rendered.
    - _Requirements: 4.1, 4.2, 4.3, 5.1, 5.2, 11.1_

- [ ] 12. Frontend A5 — Fleet tab + account picker (`FleetReport.tsx`)
  - [ ] 12.1 Add fleet-account picker and render `vehicles[]`
    - Replace the raw-UUID input with a fleet-account `Select` populated from `GET /customers/fleet-accounts` (`res.data?.fleet_accounts ?? []`); request `GET /reports/fleet/{selectedFleetId}` on selection; render the per-vehicle table from `data?.vehicles ?? []`; empty state when absent. Add `AbortController`, typed generics, safe reads.
    - _Requirements: 6.3, 6.4, 6.5, 6.6, 14.1, 14.2, 19.1, 19.3, 19.4, 21.1_
    - _Design: §"A5 — Fleet" frontend snippet, §"Request / Response Contracts"_
  - [ ]* 12.2 Write Vitest+RTL test for Fleet tab
    - Account picker loads from `/customers/fleet-accounts`; selecting an account fetches `/reports/fleet/{id}`; vehicles table renders from `vehicles`; empty state when none.
    - _Requirements: 6.3, 6.4, 6.5, 6.6_

- [ ] 13. Frontend A6 — Storage tab (`StorageUsage.tsx`)
  - [ ] 13.1 Render real breakdown + add AbortController
    - Render the breakdown table from `data?.breakdown ?? []`; empty state when absent. Add `AbortController`, typed generic, safe reads.
    - _Requirements: 7.2, 7.3, 14.1, 14.2, 19.1, 19.3, 21.1_
    - _Design: §"A6 — Storage breakdown" frontend note, §"D1 — AbortController"_
  - [ ]* 13.2 Write Vitest+RTL test for Storage tab
    - Renders breakdown rows; empty state when `breakdown` absent/empty.
    - _Requirements: 7.2, 7.3_

- [ ] 14. Frontend C3 + C4 — SMS tab (`SmsUsage.tsx`)
  - [ ] 14.1 Source tiers from plan endpoint + render daily chart
    - Fetch tiers via `GET /org/plan-sms-pricing` and read `res.data?.sms_package_pricing ?? []`; render the purchase section when ≥1 tier. Render the daily chart from `data?.daily_breakdown ?? []`; empty state when absent. Add `AbortController`, typed generics, safe reads.
    - _Requirements: 8.3, 8.4, 9.3, 9.4, 14.1, 14.2, 19.1, 19.3, 21.1_
    - _Design: §"C3 — SMS package tiers" frontend snippet, §"C4 — SMS daily breakdown" frontend note_
  - [ ]* 14.2 Write Vitest+RTL test for SMS tab
    - Tiers read from `/org/plan-sms-pricing`; purchase section gated on tier presence; daily chart renders from `daily_breakdown`; empty states honoured.
    - _Requirements: 8.3, 8.4, 9.3, 9.4_

- [ ] 15. Frontend B2 — Controlled `DateRangeFilter.tsx`
  - [ ] 15.1 Derive preset from `value` + add `presetFromValue`
    - Make the control controlled: derive the displayed preset from the `value` prop via a new `presetFromValue(value)` (matching `presetRange(p)`), showing custom state on no match. Ensure `presetRange(p)` yields `start <= end`.
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 21.1_
    - _Design: §"B2 — DateRangeFilter controlled"_
  - [ ]* 15.2 Write property test for date presets (fast-check)
    - **Property 4: Date-range presets are ordered and round-trip**
    - For every non-custom preset `p`: `presetRange(p).start <= presetRange(p).end` and `presetFromValue(presetRange(p)) === p`.
    - **Validates: Requirements 12.4, 12.5**

- [ ] 16. Frontend B3 + D1/D2/D3 — Branch sourcing + remaining-tab safety pass
  - [ ] 16.1 Fix branch sourcing in Customer Statement and verify all tabs
    - In `CustomerStatement.tsx`, replace `localStorage.getItem('selected_branch_id')` with `useBranch().selectedBranchId`; include it in params and the fetch deps; refetch on branch change. Add `AbortController` to `CustomerStatement`, `GstReturnSummary`, and `CarjamUsage`; add `selectedBranchId` to `GstReturnSummary`'s fetch deps (D2). Confirm every tab reads scalars with `?? 0`, arrays with `?? []`, nested values with `?.`, and uses typed generics (no `as any`).
    - _Requirements: 13.1, 13.2, 13.3, 14.1, 14.2, 14.3, 14.4, 19.1, 19.2, 19.3, 19.4, 19.5_
    - _Design: §"B3 — Branch sourcing", §"D1 — AbortController", §"D2 — Dependency arrays", §"D3 — Safe reads"_
  - [ ]* 16.2 Write property test for safe consumption (fast-check)
    - **Property 5: Report tabs never crash on empty, null, or partial responses**
    - Feed arbitrary `{}`, `null`, and partial payloads to each tab render and assert no throw.
    - **Validates: Requirements 14.4**

- [ ] 17. Frontend C1 — Fixed `ExportButtons.tsx`
  - [ ] 17.1 Send `export` param, parse filename, surface errors
    - Send `params: { ...params, export: fmt }` (not `format`) with `responseType: 'blob'` and an `AbortController` signal; derive the filename from the `Content-Disposition` header; build the Blob with the correct MIME (`application/pdf` / `text/csv`); trigger download; on failure show an error toast (no silent `catch {}`).
    - _Requirements: 10.1, 10.2, 10.6, 10.7, 21.1_
    - _Design: §"C1 — Export layer" `ExportButtons.tsx` snippet, §"Export flow (C1)" sequence diagram_
  - [ ]* 17.2 Write Vitest+RTL test for ExportButtons
    - Sends `export` param for CSV and PDF; downloads using the `Content-Disposition` filename and correct MIME; shows error toast on failure.
    - _Requirements: 10.1, 10.2, 10.6, 10.7_

- [ ] 18. Frontend checkpoint
  - [ ] 18.1 Checkpoint — typecheck/build and run frontend tests so far
    - Run the frontend build and Vitest (cwd `frontend-v2`). Ensure all tests pass, ask the user if questions arise.

- [ ] 19. Frontend E1 — Rebuilt `ReportsPage` landing + overview hook
  - [ ] 19.1 Create `useReportsOverview.ts` hook
    - New `frontend-v2/src/pages/reports/useReportsOverview.ts` fetching KPI + monthly + category series for the selected range (7D/30D/QTR/YR), with `AbortController`, typed generics, and `?? []`/`?? 0` guards; refetch on range change.
    - _Requirements: 15.5, 19.1, 19.2, 19.3, 14.1_
    - _Design: §"E1 — Rebuilt ReportsPage landing", §"Component map"_
  - [ ] 19.2 Rebuild `ReportsPage.tsx` to the prototype
    - Add range segmented control (7D/30D/QTR/YR), KPI row (Revenue, Gross profit, Average invoice, Jobs completed — fallback placeholder when source unavailable), Revenue-by-month + Revenue-by-category panels (using `SimpleBarChart`/CSS progress bars), and render `ReportLibrary` beneath. Use v2 design tokens.
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 21.1_
    - _Design: §"E1 — Rebuilt ReportsPage landing" TSX skeleton_
  - [ ]* 19.3 Write Vitest+RTL test for ReportsPage landing
    - Range seg present with all options; KPI row shows fallback when a source is unavailable; both overview panels render; changing range refetches; library renders below.
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6_

- [ ] 20. Frontend E2 + E3 — `ReportLibrary` grouped, module-gated cards
  - [ ] 20.1 Create `ReportLibrary.tsx` wiring all routes + module gating
    - New `frontend-v2/src/pages/reports/ReportLibrary.tsx` with the grouped `GROUPS` from the design (Financial, Sales & operations, Tax & compliance, Payroll & people, Usage & system, Automation). Link all 12 orphan routes (profit-loss, balance-sheet, aged-receivables, inventory, jobs, hospitality, pos, projects, tax-return, scheduled, wage-variance, builder) and the in-hub tabs. Gate each card with `ModuleGate`/`useModules` (and trade family where relevant); surface P&L/Balance Sheet/Aged Receivables/Income Tax in the Financial + Tax groups (E3). Navigate on card activation. Use v2 design tokens.
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 17.1, 17.2, 17.3, 21.1_
    - _Design: §"E2 — ReportLibrary", §"E3 — Surface financial reports"_
  - [ ]* 20.2 Write Vitest+RTL test for ReportLibrary
    - All six groups render; the 12 routed pages are linked; a card hides when its module is disabled; activating a card navigates to its route.
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 17.2, 17.3_

- [ ] 21. Final verification
  - [ ] 21.1 Run full backend pytest suite
    - Run the backend test suite (including the new reports tests) and confirm green.
    - _Requirements: 1–10, 18, 20_
  - [ ] 21.2 Run frontend build + Vitest (cwd `frontend-v2`)
    - Run `npm run build` with `cwd` `frontend-v2` (expect exit 0) and `npx vitest run` with `cwd` `frontend-v2`; confirm both are green. NEVER use `cd`; never touch `frontend/`, docker-compose, or nginx.
    - _Requirements: 18.1, 18.7, 21.1, 21.2_

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; core implementation sub-tasks are never optional.
- PBT tasks: P1 (1.3), P2 (9.2), P3 (6.4), P4 (15.2), P5 (16.2), P6 (4.3) — Hypothesis for backend (P1, P3, P6), fast-check for frontend (P2, P4, P5).
- Every backend field/endpoint task precedes the frontend task that consumes it (A1→8, A5→12, A6→13, C4/C3→14, C1→17).
- Checkpoints at tasks 7.2, 18.1, and 21 provide incremental validation.
- This spec produces design + planning artifacts and the implementation tasks above; begin executing by opening `tasks.md` and clicking "Start task" next to a task item.
