# Reports Page Audit — frontend-v2 (`/new/reports`)

**Date:** 2026-06-04
**Scope:** `frontend-v2/src/pages/reports/*` (the redesigned Reports hub) and the backend it talks to (`app/modules/reports/router.py`, `service.py`, `schemas.py`, plus the org SMS endpoints).
**How this was found:** every tab component was read and its field names / query params / endpoints were diffed against the actual backend Pydantic response schemas and router signatures.

## TL;DR

The Reports hub renders, but **most tabs silently show wrong/empty data because the frontend reads field names the backend never returns**. The screenshot symptom ("Invoices" card blank + "No monthly data available" on the Revenue tab) is one instance of a pattern that repeats across Invoice Status, Top Services, Outstanding, Fleet, SMS, and Storage. On top of that, **PDF/CSV export is completely non-functional** (downloads a renamed JSON blob), several **filters are dead** (ignored by the backend), and the **redesign's "report library" landing + 12 routed report pages are unreachable** from the UI.

Severity legend: 🔴 Critical (visibly broken/wrong data or crash risk) · 🟠 Major (feature dead / misleading) · 🟡 Minor (polish / consistency).

---

## A. Field-contract mismatches (frontend reads a field the backend doesn't send)

These are the root cause of the screenshot. The backend returns one name, the frontend reads another, so the value is `undefined` → blank cell / empty chart / `$0.00`.

### 🔴 A1 — Revenue: `total_invoices` and `monthly_breakdown` don't exist
- **File:** `frontend-v2/src/pages/reports/RevenueSummary.tsx`
- **Endpoint:** `GET /reports/revenue` → `RevenueSummaryResponse`
- **Mismatch:**
  - FE reads `data.total_invoices` → backend field is **`invoice_count`**. → the "Invoices" KPI card renders blank (screenshot).
  - FE reads `data.monthly_breakdown[]` → **backend returns no such field at all**. → "Monthly Revenue" chart always shows *"No monthly data available for this period."* (screenshot).
- **Fix (one of):**
  1. Backend: add `monthly_breakdown: list[{month, revenue}]` to `get_revenue_summary` + `RevenueSummaryResponse`, and either rename `invoice_count`→`total_invoices` or have the FE read `invoice_count`. (Preferred — matches the original `frontend/` contract, which also expected these fields.)
  2. FE-only: read `invoice_count`, and drop the monthly chart until the backend provides the series.
- **Note:** the *original* `frontend/src/pages/reports/RevenueSummary.tsx` reads the exact same (wrong) names, so this bug pre-exists the redesign — the backend `revenue` endpoint was changed to the dashboard shape and the report was never reconciled.

### 🔴 A2 — Invoice Status: reads `statuses`/`total_amount`/`total_invoices`, backend sends `breakdown`/`total`
- **File:** `frontend-v2/src/pages/reports/InvoiceStatus.tsx`
- **Endpoint:** `GET /reports/invoices/status` → `InvoiceStatusReportResponse` = `{ breakdown: [{status, count, total}], period_start, period_end }`
- **Mismatch:**
  - FE reads `data.statuses` → backend key is **`breakdown`**. → table + chart always render "No invoice data for this period."
  - FE reads `s.total_amount` → backend field is **`total`**. → amount column would be `$0.00` even after fixing the array.
  - FE reads `data.total_invoices` (top "Total Invoices" card) → **not returned**. → blank.
- **Fix:** FE: map `data.breakdown`, read `s.total`, and compute `total_invoices = sum(breakdown.count)`. (Or add `statuses`/`total_amount`/`total_invoices` to the backend.)

### 🔴 A3 — Top Services: reads `service_name`/`revenue`, backend sends `description`/`total_revenue`
- **File:** `frontend-v2/src/pages/reports/TopServices.tsx`
- **Endpoint:** `GET /reports/top-services` → `{ services: [{description, catalogue_item_id, count, total_revenue}] }`
- **Mismatch:** FE reads `s.service_name` (→ blank Service column) and `s.revenue` (→ `$0.00` + empty chart). Backend fields are `description` and `total_revenue`.
- **Fix:** FE: read `s.description` and `s.total_revenue`.

### 🔴 A4 — Outstanding: reads `id`/`rego`/`status`, backend sends `invoice_id`/`vehicle_rego` (+ no `status`)
- **File:** `frontend-v2/src/pages/reports/OutstandingInvoices.tsx`
- **Endpoint:** `GET /reports/outstanding` → `OutstandingInvoiceRow` = `{invoice_id, invoice_number, customer_name, customer_id, vehicle_rego, issue_date, due_date, total, balance_due, days_overdue}`
- **Mismatch:**
  - FE reads `inv.id` → backend is **`invoice_id`**. → row `key` is undefined **and the "Send Reminder" button POSTs to `/invoices/undefined/email`** (see A5/C-section too).
  - FE reads `inv.rego` → backend is **`vehicle_rego`**. → Rego column always "—".
  - FE reads `inv.status` → **not returned**. → status badge always falls back to "warn"; should derive from `days_overdue` (>0 = overdue).
- **Fix:** FE: read `invoice_id`, `vehicle_rego`, and derive status from `days_overdue`. (Backend already has `days_overdue`.)

### 🟠 A5 — Fleet: backend returns no `vehicles[]`
- **File:** `frontend-v2/src/pages/reports/FleetReport.tsx`
- **Endpoint:** `GET /reports/fleet/{id}` → `FleetReportResponse` = `{fleet_account_id, fleet_name, total_spend, vehicles_serviced, outstanding_balance, period_start, period_end}`
- **Mismatch:** FE renders a per-vehicle table from `data.vehicles[]`, but **`get_fleet_report` never returns a `vehicles` list**. → table always "No vehicles serviced in this period."
- **Fix (one of):** add a `vehicles` breakdown to `get_fleet_report` + `FleetReportResponse`, OR remove the vehicle table and keep just the 3 summary cards.

### 🟠 A6 — Storage: backend `breakdown` is hard-coded `[]`
- **File:** `frontend-v2/src/pages/reports/StorageUsage.tsx` ; **Backend:** `get_storage_usage` returns `"breakdown": []` always.
- **Symptom:** the "Storage breakdown by category" table always shows "No storage data available."
- **Fix (one of):** implement a real per-category breakdown server-side (receipts/attachments/logos/etc.), OR remove the breakdown table and keep the usage bar.

---

## B. Dead / non-functional filters

### 🟠 B1 — Outstanding tab date filter does nothing
- **File:** `OutstandingInvoices.tsx` sends `start_date`/`end_date`, but `GET /reports/outstanding` **only accepts `branch_id`** — it ignores any date range and always returns *all* open invoices.
- **Symptom:** changing the period has zero effect; misleading to the user.
- **Fix (one of):** remove the `DateRangeFilter` from this tab (outstanding is point-in-time), OR add real `start_date`/`end_date` filtering (e.g. by `issue_date`/`due_date`) to the backend.

### 🟡 B2 — `DateRangeFilter` label desyncs from the actual queried range
- **File:** `frontend-v2/src/pages/reports/DateRangeFilter.tsx`
- **Issue:** the dropdown's internal `preset` state defaults to `'month'` and **never fires `onChange` on mount**, while each tab seeds its own different `defaultRange()` (last 1 / 2 / 3 months). So the control says "Last month" while the data shown is for a different window. It's also uncontrolled — it can't reflect a range set elsewhere.
- **Fix:** derive `preset` from the `value` prop (controlled), or have the tabs initialise their range from `presetRange('month')` so the label and data agree.

### 🟡 B3 — Inconsistent branch sourcing
- **File:** `CustomerStatement.tsx` reads the branch from `localStorage.getItem('selected_branch_id')`, whereas every other tab uses `useBranch().selectedBranchId`. Brittle and can disagree with the active branch.
- **Fix:** use `useBranch()` everywhere.

---

## C. Broken actions

### 🔴 C1 — Export (PDF/CSV) is completely non-functional, app-wide on Reports
- **Files:** `frontend-v2/src/pages/reports/ExportButtons.tsx` (used by every tab).
- **Issues:**
  1. **Backend implements no export.** Every `/reports/*` endpoint declares `export: ExportFormat` but **never branches on it** — it always returns the JSON `response_model`. There is no `StreamingResponse`, no CSV writer, no WeasyPrint PDF. So the blob downloaded is JSON.
  2. **Param name is wrong anyway.** `ExportButtons` sends `params: { format }`, but the backend param is **`export`**. Even if export were implemented, the FE wouldn't trigger it.
  3. **Downloaded file is mislabeled/corrupt.** `new Blob([res.data])` with `responseType: 'blob'` saves the JSON body as `report.pdf` / `report.csv` → opens as garbage.
  4. **Errors are swallowed** (`catch {}`) → no user feedback on failure.
- **Fix (one of):**
  - Implement server-side export: on `export=csv` return `text/csv` `StreamingResponse`; on `export=pdf` render via WeasyPrint (the app already uses it for invoices). Then fix `ExportButtons` to send `export` (not `format`), set the download filename per report + extension from `Content-Disposition`, and surface errors.
  - OR, short-term: remove the PDF/CSV buttons and rely on the existing `PrintButton` (which works via the `data-print-content` / `print.css` path), so we don't ship dead buttons.

### 🔴 C2 — Outstanding "Send Reminder" hits the wrong endpoint with the wrong id
- **File:** `OutstandingInvoices.tsx` → `sendReminder()` POSTs `\/invoices/${inv.id}/email` with `{ template: 'payment_reminder' }`.
- **Issues:**
  1. `inv.id` is `undefined` (see A4) → URL becomes `/invoices/undefined/email`.
  2. The real reminder endpoint is **`POST /invoices/{id}/send-reminder`**, not `/email`. The `/email` endpoint is the generic "email invoice" action with a different body contract.
  3. No success/error feedback (silent `catch {}`), and no AbortController.
- **Fix:** use `invoice_id`, POST to `/invoices/{invoice_id}/send-reminder` with the correct body, and show a success/error toast.

### 🟠 C3 — SMS "Purchase SMS Package" UI is permanently hidden (dead)
- **File:** `frontend-v2/src/pages/reports/SmsUsage.tsx` → `fetchTiers()` GETs `/org/sms-usage` and reads `sms_package_pricing`.
- **Issue:** `OrgSmsUsageResponse` (the schema for `/org/sms-usage`) **does not include `sms_package_pricing`** — those tiers live on the *plan*. So `tiers` is always `[]` and the entire "Purchase SMS Package" section never renders, even though `POST /org/sms-packages/purchase` and the confirm dialog are fully wired.
- **Fix:** fetch the tiers from the plan (e.g. an org-visible plan endpoint that exposes `sms_package_pricing`), or add `sms_package_pricing` to `OrgSmsUsageResponse`.

### 🟡 C4 — SMS daily breakdown chart is dead
- **File:** `SmsUsage.tsx` guards on `data.daily_breakdown`, but `/reports/sms-usage` never returns it. The "Daily SMS Sent" chart can never appear.
- **Fix:** add a daily breakdown to `get_sms_usage`, or drop the chart block.

---

## D. Safe-API-consumption violations (crash risk / steering rule)

Per `.kiro/steering/safe-api-consumption.md`:

### 🟠 D1 — No `AbortController` in tab fetches
- **Files:** `RevenueSummary`, `InvoiceStatus`, `OutstandingInvoices`, `TopServices`, `GstReturnSummary`, `CarjamUsage`, `SmsUsage`, `StorageUsage`, `CustomerStatement`, `FleetReport`.
- **Issue:** every tab's `useEffect`/`fetch` lacks an `AbortController`; rapid range changes or unmounts can land a stale response on state (Pattern 7).
- **Fix:** add `const controller = new AbortController()` + `signal` + `return () => controller.abort()` to each effect; guard `catch` with `if (!controller.signal.aborted)`.

### 🟡 D2 — Stale-closure dependency arrays
- **Files:** `OutstandingInvoices.tsx`, `GstReturnSummary.tsx` — `fetchData` `useCallback` deps are `[range]` but the body also reads `selectedBranchId`. Switching branch won't refetch.
- **Fix:** add `selectedBranchId` to the dependency array.

### 🟡 D3 — `setData(res.data)` then unguarded nested reads
- Several tabs assign the whole response and read `data.x` (e.g. `InvoiceStatus` `data.total_invoices`). If the backend returns `{}` the access is `undefined` (no crash here since they're scalars/guarded arrays, but inconsistent with Pattern 4/6).
- **Fix:** read with `?.` / `?? 0` / `?? []` consistently.

---

## E. Redesign gaps — missing landing + unreachable pages

### 🟠 E1 — The Reports landing doesn't match the redesign at all
- **Files:** `frontend-v2/src/pages/reports/ReportsPage.tsx` vs `OraInvoice_Handoff/app/Reports.html`.
- **Gap:** the prototype Reports page is a rich **overview**: a `7D/30D/QTR/YR` range seg, a KPI row (Revenue / Gross profit / Avg invoice / Jobs completed), a "Revenue by month" chart, a "Revenue by category" panel, and a **"Report library"** — grouped cards (Financial / Sales & ops / Tax / Payroll / Usage / Automation) linking to every report + a "Build custom report" entry. The v2 page is just a flat tab strip with none of this.
- **Fix:** rebuild `ReportsPage` to the prototype: KPI row + overview charts + a grouped report-library that links to the routed pages below. (Keep the current per-report views as their destinations.)

### 🟠 E2 — 12 report pages are routed but unreachable from the UI
- **File:** `frontend-v2/src/App.tsx` routes these, but **nothing links to them** (no nav item, no library, not in the tab bar):
  - `/reports/profit-loss`, `/reports/balance-sheet`, `/reports/aged-receivables` (accounting-gated)
  - `/reports/inventory`, `/reports/jobs`, `/reports/hospitality`, `/reports/pos`, `/reports/projects`, `/reports/tax-return`, `/reports/scheduled`
  - `/reports/wage-variance` (payroll-gated), `/reports/builder`
- **Symptom:** effectively dead code — only reachable by typing the URL. The redesign intends them to be linked from the report library (E1).
- **Fix:** link all of them from the rebuilt report library (E1), with the same module gating the routes use (`accounting`, `payroll`, etc.).

### 🟡 E3 — Tab set doesn't include the financial/accounting reports
- Even without the full library, the tab bar omits P&L / Balance Sheet / Aged Receivables / Tax — the financially important ones. Consider surfacing them (gated) once E1/E2 are addressed.

---

## F. Suggested fix order (one-by-one)

1. **A1** Revenue field fix (`invoice_count` + monthly_breakdown) — fixes the screenshot. 🔴
2. **A2** Invoice Status (`breakdown`/`total` + computed total). 🔴
3. **A3** Top Services (`description`/`total_revenue`). 🔴
4. **A4 + C2** Outstanding fields (`invoice_id`/`vehicle_rego`, derived status) + Send Reminder endpoint. 🔴
5. **C1** Export: implement server-side CSV/PDF (or remove buttons) + fix `export` param + filename + error surfacing. 🔴
6. **A5** Fleet vehicles[] (add backend list or remove table) + fleet account **picker** instead of raw-UUID input. 🟠
7. **A6** Storage breakdown (populate or remove). 🟠
8. **C3 + C4** SMS package tiers source + daily breakdown. 🟠
9. **B1** Outstanding date filter (remove or implement). 🟠
10. **E1 + E2** Rebuild Reports landing to the prototype + link the 12 orphan pages. 🟠
11. **D1–D3** AbortController + dependency arrays + safe reads across all tabs. 🟠/🟡
12. **B2 / B3 / E3** DateRangeFilter sync, branch sourcing, financial tabs. 🟡

---

## G. Tabs that are actually OK (verified, no field bug)

- **GST Return** (`GstReturnSummary.tsx`) — all fields (`total_sales`, `standard_rated_sales`, `zero_rated_sales`, `total_gst_collected`, `net_gst`, refund/adjusted fields) match `GSTReturnResponse`. Branch filter honored. ✅ (still wants D1 AbortController.)
- **Carjam Usage** (`CarjamUsage.tsx`) — fields + `from`/`to` aliases all match the backend. ✅
- **Customer Statement** (`CustomerStatement.tsx`) — field shapes match `CustomerStatementResponse`; only B3 (branch source) + D1 apply. ✅
- **SMS summary cards** + **active packages table** — match the backend; only the *purchase tiers* (C3) and *daily chart* (C4) are dead.
- **Storage usage bar** — matches; only the breakdown table (A6) is dead.

> Note: PDF/CSV export (C1) is broken on **all** of the above too, since it's the shared `ExportButtons`.
