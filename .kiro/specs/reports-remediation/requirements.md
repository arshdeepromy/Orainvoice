# Requirements Document

## Introduction

The redesigned Reports hub (`frontend-v2/src/pages/reports/*`) renders, but most tabs silently show wrong or empty data because the frontend reads field names the backend never returns, several filters are dead, PDF/CSV export is non-functional, the redesign's report-library landing is missing, and 12 routed report pages are unreachable. This feature fixes every issue documented in `docs/REPORTS_AUDIT.md` (sections A–E).

These requirements are derived from the approved design at `.kiro/specs/reports-remediation/design.md`. Each requirement is traced back to its audit ID (A1–A6, B1–B3, C1–C4, D1–D3, E1–E3) and to the design sections that specify the implementation. All backend changes are additive and backward-compatible with the legacy `frontend/` application, which consumes the same `/reports/*` endpoints. No database migration is introduced, and `?export=` is the only behavioural switch on existing endpoints.

## Glossary

- **Reports_Hub**: The redesigned Reports user interface in `frontend-v2/src/pages/reports/*`.
- **Reports_API**: The backend reports layer (`app/modules/reports/router.py`, `app/modules/reports/service.py`, `app/modules/reports/schemas.py`).
- **Revenue_Report**: The Revenue tab component and the data returned by `GET /reports/revenue`.
- **Invoice_Status_Report**: The Invoice Status tab component and the data returned by `GET /reports/invoices/status`.
- **Top_Services_Report**: The Top Services tab component and the data returned by `GET /reports/top-services`.
- **Outstanding_Report**: The Outstanding Invoices tab component and the data returned by `GET /reports/outstanding`.
- **Fleet_Report**: The Fleet tab component and the data returned by `GET /reports/fleet/{id}`.
- **Storage_Report**: The Storage Usage tab component and the data returned by `GET /reports/storage`.
- **SMS_Report**: The SMS Usage tab component and the data returned by `GET /reports/sms-usage`.
- **Export_Service**: The server-side CSV/PDF export layer (`app/modules/reports/export.py`) plus the `ExportButtons` component (`frontend-v2/src/pages/reports/ExportButtons.tsx`).
- **Date_Range_Filter**: The `DateRangeFilter` component (`frontend-v2/src/pages/reports/DateRangeFilter.tsx`).
- **Report_Library**: The grouped report-library component (`frontend-v2/src/pages/reports/ReportLibrary.tsx`).
- **Reports_Landing**: The rebuilt landing page (`frontend-v2/src/pages/reports/ReportsPage.tsx`).
- **Plan_SMS_Pricing_Endpoint**: The new `GET /org/plan-sms-pricing` endpoint in `app/modules/organisations/router.py`.
- **Reminder_Endpoint**: The existing `POST /invoices/{invoice_id}/send-reminder` endpoint.
- **Old_Frontend**: The legacy `frontend/` application, untouched by this feature.
- **monthly_breakdown**: A list of `{month: "YYYY-MM", revenue}` points where `revenue` is the GST-inclusive total for that calendar month in NZD.
- **total_inclusive**: The GST-inclusive total revenue for the selected period in the Revenue response.
- **total_invoices** (Revenue): An alias field equal to `invoice_count` in the Revenue response.
- **breakdown** (Invoice Status): A list of `{status, count, total}` rows in the Invoice Status response.
- **daily_breakdown**: A list of `{date, sms_count}` points in the SMS Usage response.
- **total_sent**: The total count of SMS messages sent in the selected period.
- **days_overdue**: The integer number of days an outstanding invoice is past its due date.
- **v2_Design_Tokens**: The design-token classes defined in `OraInvoice_Handoff/app/ds.css` and governed by `.kiro/steering/frontend-redesign.md`.

## Requirements

### Requirement 1: Revenue Report Data

**User Story:** As an organisation user, I want the Revenue tab to show the invoice count and a monthly revenue chart, so that I can understand revenue trends for a period.

#### Acceptance Criteria

1. THE Reports_API SHALL include a `monthly_breakdown` list of `{month, revenue}` points, sorted in ascending month order, in the `GET /reports/revenue` response.
2. THE Reports_API SHALL set each `monthly_breakdown[i].revenue` to the GST-inclusive revenue total for that calendar month in NZD, computed with the same filters as the period total.
3. THE Reports_API SHALL include a `total_invoices` field equal to `invoice_count` in the `GET /reports/revenue` response.
4. WHEN the Revenue_Report receives the response, THE Revenue_Report SHALL display the invoice count read as `total_invoices ?? invoice_count ?? 0`.
5. WHEN `monthly_breakdown` contains at least one point, THE Revenue_Report SHALL render the monthly revenue chart from `monthly_breakdown`.
6. IF `monthly_breakdown` is absent or empty, THEN THE Revenue_Report SHALL display an empty-state message in place of the monthly revenue chart.

*Traceability: Audit A1; Design §"A1 — Revenue", §"Request / Response Contracts", §"Data Models & Schema Changes" rows 1–2, Testing Strategy P1.*

### Requirement 2: Invoice Status Report Data

**User Story:** As an organisation user, I want the Invoice Status tab to show counts and totals per status, so that I can see my invoice pipeline.

#### Acceptance Criteria

1. WHEN the Invoice_Status_Report receives the `GET /reports/invoices/status` response, THE Invoice_Status_Report SHALL read the status rows from `breakdown ?? []`.
2. WHEN the Invoice_Status_Report renders a status row, THE Invoice_Status_Report SHALL display the amount from the row field `total`.
3. WHEN the Invoice_Status_Report renders the total-invoices summary, THE Invoice_Status_Report SHALL compute the total as the sum of `count` across all `breakdown` rows.
4. IF `breakdown` is absent or empty, THEN THE Invoice_Status_Report SHALL display an empty-state message.

*Traceability: Audit A2; Design §"A2 — Invoice Status", §"Request / Response Contracts", Testing Strategy P2.*

### Requirement 3: Top Services Report Data

**User Story:** As an organisation user, I want the Top Services tab to show each service description and its revenue, so that I can identify best-selling services.

#### Acceptance Criteria

1. WHEN the Top_Services_Report receives the `GET /reports/top-services` response, THE Top_Services_Report SHALL read the service rows from `services ?? []`.
2. WHEN the Top_Services_Report renders a service row, THE Top_Services_Report SHALL display the service name from the row field `description`.
3. WHEN the Top_Services_Report renders a service row, THE Top_Services_Report SHALL display the revenue from the row field `total_revenue`.
4. IF `services` is absent or empty, THEN THE Top_Services_Report SHALL display an empty-state message.

*Traceability: Audit A3; Design §"A3 — Top Services", §"Request / Response Contracts".*

### Requirement 4: Outstanding Invoices Report Data

**User Story:** As an organisation user, I want the Outstanding Invoices tab to show each invoice's identity, vehicle, and overdue status, so that I can chase unpaid invoices.

#### Acceptance Criteria

1. WHEN the Outstanding_Report renders an invoice row, THE Outstanding_Report SHALL use the row field `invoice_id` as the React key, falling back to the row index when `invoice_id` is absent.
2. WHEN the Outstanding_Report renders an invoice row, THE Outstanding_Report SHALL display the vehicle registration from the row field `vehicle_rego`, falling back to a dash when `vehicle_rego` is absent.
3. WHEN an invoice row has `days_overdue` greater than zero, THE Outstanding_Report SHALL display an "Overdue" status with the danger variant.
4. WHEN an invoice row has `days_overdue` of zero or less, THE Outstanding_Report SHALL display an "Outstanding" status with the warning variant.
5. IF the outstanding invoices list is absent or empty, THEN THE Outstanding_Report SHALL display an empty-state message.

*Traceability: Audit A4; Design §"A4 + C2 — Outstanding", §"Request / Response Contracts".*

### Requirement 5: Send Payment Reminder

**User Story:** As an organisation user, I want to send a payment reminder for an outstanding invoice, so that I can prompt customers to pay.

#### Acceptance Criteria

1. WHEN a user triggers a reminder for an outstanding invoice, THE Outstanding_Report SHALL send `POST /invoices/{invoice_id}/send-reminder` where `invoice_id` is the non-empty identifier of that invoice.
2. WHEN a user triggers a reminder, THE Outstanding_Report SHALL include a request body containing a `channel` value of `email`.
3. WHEN the Reminder_Endpoint returns success, THE Outstanding_Report SHALL display a success message.
4. IF the reminder request fails, THEN THE Outstanding_Report SHALL display an error message that uses the backend error detail when present.

*Traceability: Audit C2; Design §"A4 + C2 — Outstanding", §"Send Reminder (C2)" sequence diagram, §"Request / Response Contracts".*

### Requirement 6: Fleet Report Vehicles and Account Picker

**User Story:** As an organisation user, I want the Fleet tab to list serviced vehicles and let me pick a fleet account from a list, so that I can review fleet spend without entering a raw identifier.

#### Acceptance Criteria

1. THE Reports_API SHALL include a `vehicles` list of `{rego, make, model, total_spend, last_service_date}` rows in the `GET /reports/fleet/{id}` response.
2. WHEN no qualifying vehicles exist for the fleet account in the period, THE Reports_API SHALL return an empty `vehicles` list.
3. WHEN the Fleet_Report loads, THE Fleet_Report SHALL present a fleet-account selection control populated from `GET /customers/fleet-accounts`.
4. WHEN a user selects a fleet account, THE Fleet_Report SHALL request `GET /reports/fleet/{selectedFleetId}` for the selected account.
5. WHEN the Fleet_Report receives the response, THE Fleet_Report SHALL render the per-vehicle table from `vehicles ?? []`.
6. IF the `vehicles` list is absent or empty, THEN THE Fleet_Report SHALL display an empty-state message.

*Traceability: Audit A5; Design §"A5 — Fleet", §"Data Models & Schema Changes" row 3, §"Request / Response Contracts".*

### Requirement 7: Storage Usage Breakdown

**User Story:** As an organisation administrator, I want the Storage tab to show real per-category storage usage, so that I can see what is consuming storage.

#### Acceptance Criteria

1. THE Reports_API SHALL populate the `breakdown` list in the `GET /reports/storage` response with per-category `{category, bytes}` rows sourced from the existing storage calculation.
2. WHEN the Storage_Report receives the response, THE Storage_Report SHALL render the breakdown table from `breakdown ?? []`.
3. IF the `breakdown` list is absent or empty, THEN THE Storage_Report SHALL display an empty-state message.

*Traceability: Audit A6; Design §"A6 — Storage breakdown", §"Data Models & Schema Changes" row 4, §"Request / Response Contracts".*

### Requirement 8: SMS Package Tiers

**User Story:** As an organisation administrator, I want to see available SMS package tiers, so that I can purchase additional SMS capacity.

#### Acceptance Criteria

1. WHERE the requesting user holds the `org_admin` role, THE Plan_SMS_Pricing_Endpoint SHALL return the organisation plan's `sms_package_pricing` tiers in the `GET /org/plan-sms-pricing` response.
2. WHEN the organisation plan has no SMS package tiers, THE Plan_SMS_Pricing_Endpoint SHALL return an empty `sms_package_pricing` list.
3. WHEN the SMS_Report loads its tiers, THE SMS_Report SHALL request `GET /org/plan-sms-pricing` and read `sms_package_pricing ?? []`.
4. WHEN at least one SMS package tier is returned, THE SMS_Report SHALL render the SMS package purchase section.

*Traceability: Audit C3; Design §"C3 — SMS package tiers", §"Data Models & Schema Changes" row 7, §"Request / Response Contracts".*

### Requirement 9: SMS Daily Breakdown

**User Story:** As an organisation administrator, I want the SMS tab to show a daily SMS chart, so that I can see SMS sending patterns over the period.

#### Acceptance Criteria

1. THE Reports_API SHALL include a `daily_breakdown` list of `{date, sms_count}` points in the `GET /reports/sms-usage` response.
2. THE Reports_API SHALL compute each `daily_breakdown[i].sms_count` from outbound `sms_messages` plus non-failed `notification_log` SMS entries for that date within the selected period.
3. WHEN the SMS_Report receives the response, THE SMS_Report SHALL render the daily SMS chart from `daily_breakdown ?? []`.
4. IF the `daily_breakdown` list is absent or empty, THEN THE SMS_Report SHALL display an empty-state message in place of the daily SMS chart.

*Traceability: Audit C4; Design §"C4 — SMS daily breakdown", §"Data Models & Schema Changes" row 5, §"Request / Response Contracts", Testing Strategy P6.*

### Requirement 10: Report Export to CSV and PDF

**User Story:** As an organisation user, I want to export any report to CSV or PDF, so that I can save and share report data.

#### Acceptance Criteria

1. WHEN a user triggers a CSV export on a report tab, THE Export_Service SHALL request the report endpoint with the parameter `export=csv` and a blob response type.
2. WHEN a user triggers a PDF export on a report tab, THE Export_Service SHALL request the report endpoint with the parameter `export=pdf` and a blob response type.
3. WHEN a `GET /reports/*` request includes `export=csv`, THE Reports_API SHALL return a `text/csv` response with a `Content-Disposition` attachment header whose filename has the form `{report_key}_{YYYY-MM-DD}.csv`.
4. WHEN a `GET /reports/*` request includes `export=pdf`, THE Reports_API SHALL return an `application/pdf` response with a `Content-Disposition` attachment header whose filename has the form `{report_key}_{YYYY-MM-DD}.pdf`.
5. THE Export_Service SHALL render the CSV content for a report such that each numeric figure in the CSV equals the corresponding numeric figure in the report data to two decimal places.
6. WHEN the Export_Service receives an export response, THE Export_Service SHALL save the file using the filename from the `Content-Disposition` header and the MIME type matching the requested format.
7. IF an export request fails, THEN THE Export_Service SHALL display an error message to the user.

*Traceability: Audit C1; Design §"C1 — Export layer", §"Export flow (C1)" sequence diagram, Testing Strategy P3.*

### Requirement 11: Outstanding Tab Date Filter Removal

**User Story:** As an organisation user, I want the Outstanding tab to reflect that outstanding balances are point-in-time, so that I am not misled by a date filter that has no effect.

#### Acceptance Criteria

1. THE Outstanding_Report SHALL NOT present a date-range filter control.
2. WHEN the Outstanding_Report requests `GET /reports/outstanding`, THE Outstanding_Report SHALL omit `start_date` and `end_date` parameters.
3. WHEN the Outstanding_Report requests an export, THE Outstanding_Report SHALL omit `start_date` and `end_date` parameters.

*Traceability: Audit B1; Design §"B1 — Outstanding date filter".*

### Requirement 12: Controlled Date Range Filter

**User Story:** As an organisation user, I want the date-range dropdown label to match the data being shown, so that I can trust the selected period.

#### Acceptance Criteria

1. THE Date_Range_Filter SHALL derive its displayed preset from the `value` prop rather than from independent internal state.
2. WHEN the `value` prop matches a known preset range, THE Date_Range_Filter SHALL display that preset's label.
3. WHEN the `value` prop matches no known preset range, THE Date_Range_Filter SHALL display the custom-range state.
4. THE Date_Range_Filter SHALL produce date-range presets where the start date is less than or equal to the end date.
5. THE Date_Range_Filter SHALL satisfy `presetFromValue(presetRange(p)) == p` for every non-custom preset `p`.
6. WHEN a report tab initialises its range, THE report tab SHALL seed the range from `presetRange('month')` so the dropdown label and the queried data agree on mount.

*Traceability: Audit B2; Design §"B2 — DateRangeFilter controlled", Testing Strategy P4.*

### Requirement 13: Consistent Branch Sourcing

**User Story:** As an organisation user, I want every report tab to use the active branch selection, so that report data is scoped to the branch I have chosen.

#### Acceptance Criteria

1. THE Customer_Statement tab SHALL read the active branch from `useBranch().selectedBranchId`.
2. THE Reports_Hub SHALL NOT read the active branch from `localStorage` in any report tab.
3. WHEN the active branch changes, THE Reports_Hub SHALL refetch the affected report data for the newly selected branch.

*Traceability: Audit B3; Design §"B3 — Branch sourcing".*

### Requirement 14: Safe API Consumption in Report Tabs

**User Story:** As an organisation user, I want report tabs to remain stable during loading, branch changes, and malformed responses, so that the Reports hub never crashes.

#### Acceptance Criteria

1. WHEN a report tab issues an API request inside an effect, THE report tab SHALL provide an `AbortController` signal and abort the request on cleanup.
2. IF a fetch error occurs and the request was not aborted, THEN the report tab SHALL display an error state.
3. WHEN a report tab's fetch callback reads the selected branch, THE report tab SHALL include the selected branch identifier in the effect dependency array.
4. THE Reports_Hub SHALL render every report tab without throwing for response payloads that are `{}`, `null`, or partial.

*Traceability: Audit D1, D2, D3; Design §"D1 — AbortController", §"D2 — Dependency arrays", §"D3 — Safe reads", Testing Strategy P5.*

### Requirement 15: Reports Landing Page

**User Story:** As an organisation user, I want a Reports landing page with an overview and report library, so that I can see key metrics and navigate to any report.

#### Acceptance Criteria

1. THE Reports_Landing SHALL present a range segmented control with the options 7D, 30D, QTR, and YR.
2. THE Reports_Landing SHALL present a KPI row containing Revenue, Gross profit, Average invoice, and Jobs completed.
3. WHEN a KPI source value is unavailable, THE Reports_Landing SHALL display the KPI value as a fallback placeholder.
4. THE Reports_Landing SHALL present a revenue-by-month panel and a revenue-by-category panel.
5. WHEN a user changes the range segmented control, THE Reports_Landing SHALL fetch overview data for the selected range.
6. THE Reports_Landing SHALL render the Report_Library beneath the overview panels.

*Traceability: Audit E1; Design §"E1 — Rebuilt ReportsPage landing".*

### Requirement 16: Report Library and Orphan Page Wiring

**User Story:** As an organisation user, I want grouped links to every report, so that the routed report pages are reachable from the Reports hub.

#### Acceptance Criteria

1. THE Report_Library SHALL present report links grouped into Financial, Sales & operations, Tax & compliance, Payroll & people, Usage & system, and Automation categories.
2. THE Report_Library SHALL provide a link to each of the 12 routed report pages: profit-loss, balance-sheet, aged-receivables, inventory, jobs, hospitality, pos, projects, tax-return, scheduled, wage-variance, and builder.
3. WHERE a report card is associated with a module, THE Report_Library SHALL display that card only when the associated module is enabled.
4. WHEN a user activates a report card, THE Report_Library SHALL navigate to that report's route.

*Traceability: Audit E2; Design §"E2 — ReportLibrary".*

### Requirement 17: Financial Reports Surfaced in Library

**User Story:** As an organisation user, I want financial and accounting reports listed in the report library, so that I can reach Profit & Loss, Balance Sheet, Aged Receivables, and Income Tax reports.

#### Acceptance Criteria

1. THE Report_Library SHALL list Profit & Loss, Balance Sheet, Aged Receivables, and Income Tax Summary within its Financial and Tax & compliance groups.
2. WHERE a financial report card requires the `accounting` module, THE Report_Library SHALL display that card only when the `accounting` module is enabled.
3. WHERE a report card requires the `payroll` module, THE Report_Library SHALL display that card only when the `payroll` module is enabled.

*Traceability: Audit E3; Design §"E2 — ReportLibrary", §"E3 — Surface financial reports".*

### Requirement 18: Backward Compatibility

**User Story:** As a platform maintainer, I want the changes to remain backward-compatible, so that the legacy frontend and existing deployment continue working unchanged.

#### Acceptance Criteria

1. THE reports-remediation changes SHALL NOT modify any file within the `frontend/` directory.
2. THE Reports_API SHALL retain the existing `invoice_count` field alongside the new `total_invoices` alias.
3. WHERE a response field is renamed, THE Reports_API SHALL return both the original field name and the new alias.
4. THE Reports_API SHALL add new response fields additively while retaining all existing response fields.
5. WHEN a `GET /reports/*` request omits the `export` parameter, THE Reports_API SHALL return the same JSON response shape returned before this feature.
6. THE reports-remediation changes SHALL operate without a database migration.
7. THE reports-remediation changes SHALL NOT modify `docker-compose` files or nginx configuration.

*Traceability: Design §"Backward-Compatibility Contract", §"Backward-Compatibility Summary".*

### Requirement 19: Safe-API-Consumption Compliance

**User Story:** As a platform maintainer, I want all new report frontend code to follow the safe-API-consumption steering rules, so that the class of crash bugs in the issue tracker does not recur.

#### Acceptance Criteria

1. THE Reports_Hub SHALL access every array from an API response using a `?? []` fallback.
2. THE Reports_Hub SHALL access every numeric value from an API response using a `?? 0` fallback before number formatting.
3. THE Reports_Hub SHALL declare a typed generic on every `apiClient.get` call.
4. THE Reports_Hub SHALL access nested response values using optional chaining.
5. THE Reports_Hub SHALL use field names that match the backend Pydantic response schema.

*Traceability: Design §"Low-Level Design" frontend note; steering `safe-api-consumption.md`; Audit D3.*

### Requirement 20: Backend Implementation Patterns

**User Story:** As a platform maintainer, I want the backend changes to follow established project patterns, so that data isolation, performance, and access control are preserved.

#### Acceptance Criteria

1. THE Reports_API SHALL execute report queries using async SQLAlchemy.
2. THE Reports_API SHALL scope every report query by `org_id` and, when a branch is provided, by `branch_id`.
3. THE Reports_API SHALL execute report queries under Row-Level Security.
4. THE Reports_API SHALL retain the existing `require_role` guards on every report endpoint.
5. WHERE the Export_Service renders a PDF, THE Export_Service SHALL run WeasyPrint via `asyncio.to_thread`.
6. THE Reports_API SHALL wrap every list response within an object.

*Traceability: Design §"Low-Level Design" backend note, §"Performance Considerations", §"Security Considerations".*

### Requirement 21: v2 Design Tokens for New UI

**User Story:** As a platform maintainer, I want all new and rebuilt report UI to use the v2 design tokens, so that the Reports hub matches the redesign system.

#### Acceptance Criteria

1. THE Reports_Hub SHALL style all new and rebuilt report UI using the v2_Design_Tokens.
2. THE Reports_Hub SHALL implement all new report UI exclusively within `frontend-v2/`.

*Traceability: Design §"Overview" design-tokens note; steering `frontend-redesign.md`.*
