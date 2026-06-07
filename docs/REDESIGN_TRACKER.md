# OraInvoice Frontend Redesign Tracker

> **STATUS: CUT OVER (local dev) — 2026-06-05.** `frontend-v2/` is now the **live** frontend behind the local dev gateway: it is served under `/new/` and the gateway root `/` 302-redirects there. The legacy `frontend/` is **ARCHIVED** (`frontend/ARCHIVED.md`) — no further development. Cutover is wired via additive, reversible files only (`docker-compose.frontend-v2.yml`, `docker-compose.dev-v2.yml`, `nginx/nginx.dev-v2.conf`); the canonical `docker-compose.yml` and `nginx/nginx.conf` are untouched. Production / Pi cutover (a static build) is a separate future step.
>
> **Local dev run command:**
> ```
> docker compose -f docker-compose.yml -f docker-compose.dev.yml \
>   -f docker-compose.frontend-v2.yml -f docker-compose.dev-v2.yml \
>   up -d --remove-orphans postgres redis app mobile frontend-v2 nginx
> ```
> Then open http://localhost/ (redirects to http://localhost/new/).
>
> **Design source:** `OraInvoice_Handoff/` — contains 150+ high-fidelity HTML prototypes, `ds.css` (design system), `shell.js` (app shell), and full spec in `README.md`.
>
> **Rules for integration:**
> - Every page must preserve ALL existing functionality — buttons, rendering logic, calculations, API calls, state management
> - No feature regressions allowed — if the old page does it, the new page must do it
> - Design references are the `.html` files in `OraInvoice_Handoff/app/` — match them pixel-perfect
> - `frontend-v2/` is fully independent — no imports from `frontend/`, logic is copied verbatim
> - Steering rules: `.kiro/steering/frontend-redesign.md`

---

## Status Legend

| Symbol | Meaning |
|--------|---------|
| ⬜ | Not started |
| 🎨 | Design provided, awaiting implementation |
| 🔨 | In progress |
| ✅ | Complete and reviewed |
| 🚫 | Skipped / Not redesigning |

---

## Summary

| Category | Total Items | Completed | Remaining |
|----------|-------------|-----------|-----------|
| Pages | 294 | 294 | 0 |
| Modals/Popups | 48 | 48 | 0 |
| **Grand Total** | **342** | **342** | **0** |

> **STATUS: COMPLETE** — All 79 tasks done; all 342 pages/modals ported into `frontend-v2/`. Build passes (`npm run build` exit 0); 111 tests pass across 20 files. See `docs/REDESIGN_AUDIT.md` for the Task 79 final-audit findings.

---

## PAGES

### 1. Dashboard (4 pages + 12 widgets)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 1 | Dashboard | `pages/dashboard/Dashboard.tsx` | ✅ | Task 16 — role-dispatching entry (MainDashboard KPI row/revenue chart/recent invoices/activity/bookings); routed `/dashboard` |
| 2 | Global Admin Dashboard | `pages/dashboard/GlobalAdminDashboard.tsx` | ✅ | Task 17 — verbatim platform dashboard (MRR/errors/integration costs/HA/org-branch revenue); routed `/admin/dashboard` |
| 3 | Org Admin Dashboard | `pages/dashboard/OrgAdminDashboard.tsx` | ✅ | Task 17 — verbatim org-admin dashboard variant; dispatched by Dashboard |
| 4 | Salesperson Dashboard | `pages/dashboard/SalespersonDashboard.tsx` | ✅ | Task 17 — verbatim salesperson dashboard variant; dispatched by Dashboard |
| 5 | Active Staff Widget | `pages/dashboard/widgets/ActiveStaffWidget.tsx` | ✅ | Task 18 — logic verbatim; restyled to tokens (ok-soft count pill, accent avatar, .mono) |
| 6 | Cash Flow Chart Widget | `pages/dashboard/widgets/CashFlowChartWidget.tsx` | ✅ | Task 18 — recharts BarChart + self-fetch (`/dashboard/widgets/cash-flow`) verbatim; token chips/tooltip, bars ok/danger |
| 7 | Expiry Reminders Widget | `pages/dashboard/widgets/ExpiryRemindersWidget.tsx` | ✅ | Task 18 — dismiss/mark_sent POST + local Sets verbatim; token table, accent/purple type pills |
| 8 | Inventory Overview Widget | `pages/dashboard/widgets/InventoryOverviewWidget.tsx` | ✅ | Task 18 — category tiles + `/inventory?category=` links verbatim; low-stock uses text-warn |
| 9 | Public Holidays Widget | `pages/dashboard/widgets/PublicHolidaysWidget.tsx` | ✅ | Task 18 — logic verbatim; restyled to tokens |
| 10 | Recent Claims Widget | `pages/dashboard/widgets/RecentClaimsWidget.tsx` | ✅ | Task 18 — status map + `/claims/:id` link verbatim; token soft-tone status pills |
| 11 | Recent Customers Widget | `pages/dashboard/widgets/RecentCustomersWidget.tsx` | ✅ | Task 18 — logic verbatim; token dividers, .mono rego chip |
| 12 | Recent Invoices Widget | `pages/dashboard/widgets/RecentInvoicesWidget.tsx` | ✅ | Task 18 — self-fetch + margin role-gate + View All modal verbatim; uses new token Modal primitive |
| 13 | Reminder Config Widget | `pages/dashboard/widgets/ReminderConfigWidget.tsx` | ✅ | Task 18 — isValidThreshold + PUT `/dashboard/reminder-config` verbatim; token inputs w/ accent focus ring |
| 14 | Todays Bookings Widget | `pages/dashboard/widgets/TodaysBookingsWidget.tsx` | ✅ | Task 18 — logic + `/bookings/:id` link verbatim; accent time, .mono rego chip |
| 15 | Widget Card | `pages/dashboard/widgets/WidgetCard.tsx` | ✅ | Task 18 — same WidgetCardProps contract; restyled to `.card`/`.card-head`/`.card-body` token language |
| 16 | Widget Grid | `pages/dashboard/widgets/WidgetGrid.tsx` | ✅ | Task 18 — WIDGET_DEFINITIONS gating, @dnd-kit reorder, localStorage persistence, renderWidget switch verbatim; replaces Task 17 stub |

### 2. Auth (12 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 17 | Login | `pages/auth/Login.tsx` | ✅ | Task 13 — ported verbatim logic, AuthLayout, MfaModal + NodeStatusIndicator, /login route wired |
| 18 | Signup | `pages/auth/Signup.tsx` | ✅ | Task 13 — single-page variant ported (logic verbatim); /signup uses SignupWizard |
| 19 | Signup Wizard | `pages/auth/SignupWizard.tsx` | ✅ | Task 13 — 4-card wizard ported verbatim, wired to /signup (lazy, Stripe chunk) |
| 20 | Signup Form | `pages/auth/SignupForm.tsx` | ✅ | Task 13 — reusable form component ported verbatim |
| 21 | Confirmation Step | `pages/auth/ConfirmationStep.tsx` | ✅ | Task 13 — ported, design-token restyle |
| 22 | Payment Step | `pages/auth/PaymentStep.tsx` | ✅ | Task 13 — Stripe Elements flow ported verbatim |
| 23 | MFA Challenge | `pages/auth/MfaChallenge.tsx` | ✅ | Task 14 — re-exports MfaVerify (verbatim) |
| 24 | MFA Verify | `pages/auth/MfaVerify.tsx` | ✅ | Task 14 — verbatim logic (OTP/method switch/resend/Firebase phone-auth/passkey/completeMfa+completeFirebaseMfa, mfaPending gating), MfaVerify.html design, /mfa-verify wired |
| 25 | Passkey Setup | `pages/auth/PasskeySetup.tsx` | ✅ | Task 14 — verbatim WebAuthn register flow, PasskeySetup.html design, /passkey-setup wired (RequireAuth) |
| 26 | Password Reset Request | `pages/auth/PasswordResetRequest.tsx` | ✅ | Task 14 — verbatim (anti-enumeration Req 4.4), PasswordReset.html design, /forgot-password wired |
| 27 | Password Reset Complete | `pages/auth/PasswordResetComplete.tsx` | ✅ | Task 14 — verbatim (≥12-char + match validation, token from URL), PasswordReset.html design + strength meter (FR-2b), /reset-password wired |
| 28 | Verify Email | `pages/auth/VerifyEmail.tsx` | ✅ | Task 14 — verbatim (signup auto-verify + invitation set-password + resend), reuses PasswordRequirements, VerifyEmail.html design, /verify-email wired |

### 3. Invoices (4 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 29 | Invoice List | `pages/invoices/InvoiceList.tsx` | ✅ | Task 19 — split-panel list+detail+create ported verbatim (all handlers, all API calls, search/status-filter/offset-limit pagination, status badges, role/module gating, share→`/api/v1/public/invoice/{token}` view link). Invoices.html design; designed-on-the-fly: detail toolbar dropdowns (Send/Reminder/PDF/More), invoice + POS receipt previews, payment-history/credit-note tables, draft/voided banners. Ported deps: CreditNoteModal, RefundModal, AttachmentList, POSReceiptPreview, QrPaymentAmountModal, QrPaymentWaitingPopup + utils (refund-credit-note, invoiceReceiptMapper, escpos, invoiceTemplateStyles, buildVehicleDisplayFields, vehicleHelpers, navigationGuard) + ui FormField/Toast |
| 30 | Invoice Create | `pages/invoices/InvoiceCreate.tsx` | ✅ | Task 20 — full create/edit form ported verbatim. ALL money math byte-identical (calcLineAmount, GST inclusive back-calc + per-line GST-from-inclusive-price, gst-exempt, %/fixed discount, subtotal/gst/total). All API calls, validation, autosave dirty-guard (navigationGuard), prefill (customer_id/vehicle_rego/vehicle_regos), edit-mode load, line-item lock on issued, attachments, fluid-usage tracking, role/module/trade-family gating preserved. InvoiceCreate.html framing (canvas/card/sticky header). Ported deps: IssueInvoiceModal, CustomerCreateModal, VehicleLiveSearch, AddToStockModal+InlineCreateForm, Select, PhoneInput, ModuleGate. Tests: InvoiceCreate.qr (ported) + new calculations.test (11 pass) |
| 31 | Invoice Detail | `pages/invoices/InvoiceDetail.tsx` | ✅ | Task 20 — read-only detail + all actions ported verbatim (edit, credit note, refund, payment link gen/regen/send, QR payment, duplicate, void, email, reminder email/SMS, print, POS print, receipt preview, download PDF, report issue). Payment-summary/GST/profit-margin maths byte-identical. Ported deps: posReceiptPrinter + printer drivers (browser/star/epson/genericHTTP/connection), PrinterErrorModal, LinkedComplianceDocs. NOTE: original router sends /invoices/:id to the InvoiceList split-panel, NOT this page — wired to mirror exactly; this page ported for parity + reachable design |
| 32 | Recurring Invoices | `pages/invoices/RecurringInvoices.tsx` | ✅ | Task 79 audit — verbatim standalone recurring-schedule manager (create/edit/pause/cancel, line-item math); routed `/invoices/recurring` (FR-2b); token restyle |

### 4. Quotes (3 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 33 | Quote List | `pages/quotes/QuoteList.tsx` | ✅ | Task 21 — split-panel list+detail, ModuleRoute('quotes') gated |
| 34 | Quote Create | `pages/quotes/QuoteCreate.tsx` | ✅ | Task 21 — full form, GST/discount math verbatim; wired source's built-but-unwired Parts picker |
| 35 | Quote Detail | `pages/quotes/QuoteDetail.tsx` | ✅ | Task 21 — ported for parity (router uses split-panel) |

### 5. Customers (5 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 36 | Customer List | `pages/customers/CustomerList.tsx` | ✅ | Task 23 |
| 37 | Customer Create | `pages/customers/CustomerCreate.tsx` | ✅ | Task 23 |
| 38 | Customer Profile | `pages/customers/CustomerProfile.tsx` | ✅ | Task 23 |
| 39 | Discount Rules | `pages/customers/DiscountRules.tsx` | ✅ | Task 24 — verbatim CRUD; designed on tokens (no own prototype); routed `/customers/discount-rules` (FR-2b) |
| 40 | Fleet Accounts | `pages/customers/FleetAccounts.tsx` | ✅ | Task 24 — verbatim CRUD; styled per FleetAccounts.html language; routed `/customers/fleet-accounts` (FR-2b) |

### 6. Jobs (5 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 41 | Job Board | `pages/jobs/JobBoard.tsx` | ✅ | Task 26 — verbatim kanban DnD + status-transition validation + project hierarchy + resource timeline (conflict detection); styled per JobBoard.html. Deps ported: useModuleGuard, TerminologyContext, jobCalcs |
| 42 | Job Detail | `pages/jobs/JobDetail.tsx` | ✅ | Task 26 — verbatim detail/create + 5 tabs (Details/Profitability/Checklist/Attachments/Timeline) + convert-to-invoice; embeds LinkedComplianceDocs; routed `/jobs/:id` via JobDetailRoute |
| 43 | Job List | `pages/jobs/JobList.tsx` | ✅ | Task 26 — verbatim filterable list + project grouping + template create; routed `/jobs/list` (FR-2b; not in original router) |
| 44 | Jobs Page | `pages/jobs/JobsPage.tsx` | ✅ | Task 26 — verbatim active job-card list w/ live JobTimer, confirm-done+invoice (500 retry), assign/take-over; exports sortJobCards/filterActiveJobs; routed `/jobs` |
| 45 | Job Timer | `pages/jobs/JobTimer.tsx` | ✅ | Task 26 — verbatim live timer (start/stop/assign, tab-wake refetch, accumulated total); exports formatElapsedTime/calculateAccumulatedMinutes |

### 7. Job Cards (3 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 46 | Job Card List | `pages/job-cards/JobCardList.tsx` | ✅ | Task 27 — verbatim list w/ per-row live timers, inline StaffPicker assignee, Start/Stop/Cancel(405→complete); module-gated `jobs` |
| 47 | Job Card Create | `pages/job-cards/JobCardCreate.tsx` | ✅ | Task 27 — verbatim customer search+create / vehicle lookup / plumbing ServiceTypeSelector / optional line-items+catalogue / create-then-attach. Deps ported: StaffPicker, AttachmentUploader, AttachmentList, ServiceTypeSelector |
| 48 | Job Card Detail | `pages/job-cards/JobCardDetail.tsx` | ✅ | Task 27 — verbatim status workflow (auto-stop timer on complete), live timer, convert-to-invoice, attachments+lightbox, service-type/line-items/time-tracking sections |

### 8. Inventory (16 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 49 | Inventory Page | `pages/inventory/InventoryPage.tsx` | ✅ | Task 35 — verbatim tabbed container (Stock Levels/Usage History/Stock Update Log/Reorder Alerts/Suppliers), urlPersist; routed `/inventory` gated `inventory` |
| 50 | Product List | `pages/inventory/ProductList.tsx` | ✅ | Task 35 — verbatim products/low-stock/supplier-catalogue views, barcode scan, PO create; routed `/inventory/products` (FR-2b); dep barcodeScanner util |
| 51 | Product Detail | `pages/inventory/ProductDetail.tsx` | ✅ | Task 35 — verbatim Details/Stock History/Pricing Rules tabs, create+edit, image upload, barcode scan; routed `/inventory/products/:id` via ProductDetailRoute |
| 52 | Stock Levels | `pages/inventory/StockLevels.tsx` | ✅ | Task 35 — verbatim dashboard, Add-to-Stock + Adjust-Stock modals, threshold edits; dep inventoryCalcs util |
| 53 | Stock Movements | `pages/inventory/StockMovements.tsx` | ✅ | Task 35 — verbatim paginated movements + batch adjustment modal; routed `/inventory/movements` (FR-2b) |
| 54 | Stock Adjustment | `pages/inventory/StockAdjustment.tsx` | ✅ | Task 36 — verbatim parts/fluids adjust (PUT /inventory/stock & /fluid-stock); routed `/inventory/adjustment` (FR-2b) |
| 55 | Stock Take | `pages/inventory/StockTake.tsx` | ✅ | Task 36 — verbatim count/variance/commit + barcode scan; routed `/inventory/stocktake` (FR-2b) |
| 56 | Stock Transfers | `pages/inventory/StockTransfers.tsx` | ✅ | Task 36 — verbatim inter-branch transfers (create + approve/ship/receive/cancel); routed `/branch-transfers` gated `branch_management` (mirrors original) |
| 57 | Stock Update Log | `pages/inventory/StockUpdateLog.tsx` | ✅ | Ported in Task 35 (InventoryPage tab) — verbatim + token restyle |
| 58 | Purchase Orders | `pages/inventory/PurchaseOrders.tsx` | ✅ | Task 36 — verbatim PO builder + blob PDF download; routed `/inventory/purchase-orders` (FR-2b) |
| 59 | Supplier List | `pages/inventory/SupplierList.tsx` | ✅ | Ported in Task 35 (InventoryPage tab) — verbatim + token restyle |
| 60 | Reorder Alerts | `pages/inventory/ReorderAlerts.tsx` | ✅ | Ported in Task 35 (InventoryPage tab) — verbatim + token restyle |
| 61 | Pricing Rules | `pages/inventory/PricingRules.tsx` | ✅ | Task 36 — verbatim CRUD + overlap detection; routed `/inventory/pricing-rules` (FR-2b) |
| 62 | Category Tree | `pages/inventory/CategoryTree.tsx` | ✅ | Task 36 — verbatim tree + drag-drop re-parent + CRUD; routed `/inventory/categories` (FR-2b) |
| 63 | CSV Import | `pages/inventory/CSVImport.tsx` | ✅ | Task 36 — verbatim 3-step upload/preview/results + auto field-map; routed `/inventory/csv-import` (FR-2b) |
| 64 | Usage History | `pages/inventory/UsageHistory.tsx` | ✅ | Ported in Task 35 (InventoryPage tab) — verbatim + token restyle |

### 9. Items & Catalogue (10 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 65 | Items Page | `pages/items/ItemsPage.tsx` | ✅ | Task 37 — verbatim tabbed container (Items/Labour Rates/Service Types), plumbing trade-family gate; routed `/items` gated `inventory` |
| 66 | Items Catalogue | `pages/items/ItemsCatalogue.tsx` | ✅ | Task 37 — verbatim catalogue list + create/edit modal + PackageBuilder + GST tri-toggle + role-gated Cost/Profit |
| 67 | Labour Rates | `pages/items/LabourRates.tsx` | ✅ | Task 37 — verbatim `/catalogue/labour-rates` CRUD (safe-consumption hardened) |
| 68 | Service Types Tab | `pages/items/ServiceTypesTab.tsx` | ✅ | Task 37 — verbatim `/service-types` list + toggle + ServiceTypeModal field builder |
| 69 | Package Builder | `pages/items/components/PackageBuilder.tsx` | ✅ | Task 37 — verbatim cost roll-ups (byte-identical), parts/tyre/fluid selectors; module-gated vehicles+inventory |
| 70 | Package Preview | `pages/items/components/PackagePreview.tsx` | ✅ | Task 37 — verbatim cost summary roll-up |
| 71 | Catalogue Page | `pages/catalogue/CataloguePage.tsx` | ✅ | Task 38 — verbatim tabbed container (Parts / Fluids-Oils), automotive trade-family gated within page; routed `/catalogue` gated `inventory` (mirrors original) |
| 72 | Parts Catalogue | `pages/catalogue/PartsCatalogue.tsx` | ✅ | Task 38 — verbatim parts list + create/edit + StockSourceModal link + role-gated cost/margin; token restyle |
| 73 | Service Catalogue | `pages/catalogue/ServiceCatalogue.tsx` | ✅ | Task 38 — verbatim service list/CRUD; retained in barrel for parity (CataloguePage no longer renders a Services tab) |
| 74 | Fluid Oil Form | `pages/catalogue/FluidOilForm.tsx` | ✅ | Task 38 — verbatim fluid/oil create/edit form (viscosity/spec/volume + pricing); token restyle |

### 10. Bookings (6 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 75 | Booking Page | `pages/bookings/BookingPage.tsx` | ✅ | Task 28 — verbatim public booking page (org branding, date/slot picker, submit); routed `/book/:orgSlug` (FR-2b) |
| 76 | Booking Calendar | `pages/bookings/BookingCalendar.tsx` | ✅ | Task 28 — verbatim day/week/month grid, holiday overlay, slot-click create, convert actions; tokens for today/holiday |
| 77 | Booking Calendar Page | `pages/bookings/BookingCalendarPage.tsx` | ✅ | Task 28 — verbatim orchestrator (calendar + list panel + form + job-convert modal + markConverted ref); routed `/bookings`, module-gated `bookings` |
| 78 | Booking Form | `pages/bookings/BookingForm.tsx` | ✅ | Task 28 — verbatim create/edit (customer+vehicle+service typeahead, inline create, parts/fluids pickers, reminders); reuses VehicleLiveSearch + CustomerCreateModal |
| 79 | Booking List | `pages/bookings/BookingList.tsx` | ✅ | Task 28 — verbatim paginated v2 bookings list (status/date filters, cancel); routed `/bookings/list` (FR-2b) |
| 80 | Booking List Panel | `pages/bookings/BookingListPanel.tsx` | ✅ | Task 28 — verbatim scheduled/completed tabs, cancel/create-job/confirm-invoice, ConfirmDialog, markConverted ref handle |

### 11. Schedule & Staff Schedule (4 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 81 | Schedule Calendar | `pages/schedule/ScheduleCalendar.tsx` | ✅ | Ported in Task 30 (RosterTab dep) — @dnd-kit roster grid + ScheduleEntryModal + ShiftTemplates verbatim; Task 32 will reconcile/route |
| 82 | Shift Templates | `pages/schedule/ShiftTemplates.tsx` | ✅ | Ported in Task 30 (ScheduleCalendar dep); Task 32 will reconcile |
| 83 | Staff Schedule | `pages/scheduling/StaffSchedule.tsx` | ✅ | Task 32 — verbatim branch-grouped table + add-shift form (availability prefill, 409 overlap) + delete; routed `/staff-schedule` gated `branch_management` |
| 84 | Roster Grid Page | `pages/staff-schedule/RosterGridPage.tsx` | ✅ | Task 32 — verbatim grid editor (paint/resize/clipboard/keyboard/copy-week/apply-template/conflict-banner/CSV/print/mobile-fallback); 8 utils byte-identical + useRosterGridData hook + 7 grid components; routed `/staff-schedule/grid` gated `scheduling` |

### 12. Staff (12 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 85 | Staff List | `pages/staff/StaffList.tsx` | ✅ | Task 30 — verbatim CRUD (`/api/v2` staff, check-duplicate, also-create-as-user invite+branch, permanent delete+user delete), search/filters/pagination, WorkSchedule modal; routed `/staff` module-gated `staff` |
| 86 | Staff Detail | `pages/staff/StaffDetail.tsx` | ✅ | Task 30 — verbatim tabbed shell (Overview/Roster/Payslips/Documents), useTabHash, dirty-guard, legacy fallback when `staff_management` off; routed `/staff/:id` via StaffDetailRoute |
| 87 | Overview Tab | `pages/staff/tabs/OverviewTab.tsx` | ✅ | Task 30 — verbatim view/edit, min-wage 422 modal, IRD/bank masking, pay-rate + recurring-allowance panels |
| 88 | Hours Tab | `pages/staff/tabs/HoursTab.tsx` | ✅ | Task 30 — verbatim week navigator, scheduled-vs-actual, flag/approve/buddy-punch, RBAC photo gating |
| 89 | Roster Tab | `pages/staff/tabs/RosterTab.tsx` | ✅ | Task 30 — verbatim ScheduleCalendar(focusStaffId) + email/SMS roster toolbar |
| 90 | Payslips Tab | `pages/staff/tabs/PayslipsTab.tsx` | ✅ | Task 30 — verbatim payslip list + void modal; Badge warning→warn/error→danger, Button secondary→ghost |
| 91 | Documents Tab | `pages/staff/tabs/DocumentsTab.tsx` | ✅ | Task 30 — verbatim drag-drop upload → employment-agreement attach |
| 92 | Leave Tab | `pages/staff/leave/LeaveTab.tsx` | ✅ | Task 31 — verbatim useStaffLeave data + BalanceCardsRow/CasualLeaveBanner/LedgerTable composition + request/adjust modals; rendered by StaffDetail leave tab |
| 93 | Balance Cards Row | `pages/staff/leave/BalanceCardsRow.tsx` | ✅ | Task 31 — verbatim per-type cards (casual hides annual), confidential chip→accent-soft, .mono hours |
| 94 | Ledger Table | `pages/staff/leave/LedgerTable.tsx` | ✅ | Task 31 — verbatim filtered/sorted ledger; green/red deltas→ok/danger, .mono dates/hours |
| 95 | My Payslips Page | `pages/staff/me/MyPayslipsPage.tsx` | ✅ | Task 31 — verbatim listMyPayslips + finalised-only filter + PDF link; ModuleGate payroll; routed `/staff/me/payslips` |
| 96 | Self Service Clock | `pages/staff/me/SelfServiceClockScreen.tsx` | ✅ | Task 31 — verbatim getUserMedia/geo capture, clock in/out, running-late sheet; routed `/staff/me/clock` gated `staff_management`. Deps ported: useStaffLeave, RunningLateSheet, CasualLeaveBanner |

### 13. Swaps & Leave (3 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 97 | Shift Swap Page | `pages/swaps/ShiftSwapPage.tsx` | ✅ | Task 33 — verbatim 5-state swap machine + manager approve/reject + target accept/reject + 409 handling; routed `/shift-swaps` gated `staff_management` |
| 98 | Shift Cover Page | `pages/swaps/ShiftCoverPage.tsx` | ✅ | Task 33 — verbatim open-shift cover list + claim flow (G6 conflict/403/not-eligible); routed `/shift-cover` gated `staff_management` |
| 99 | Approval Queue | `pages/leave/ApprovalQueue.tsx` | ✅ | Task 33 — verbatim tabbed leave queue + inline approve + reject modal + confidential family_violence handling; routed `/leave/approvals` gated `staff_management` |

### 14. Time Tracking & Expenses (2 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 100 | Time Sheet | `pages/time-tracking/TimeSheet.tsx` | ✅ | Task 33 — verbatim 3 views (timesheet/project-report/weekly-grid) + overlap detection + project aggregation + convert-to-invoice; routed `/time-tracking` gated `time_tracking`; deps: timeTrackingCalcs util |
| 101 | Expense List | `pages/expenses/ExpenseList.tsx` | ✅ | Task 51 — verbatim expense list/CRUD; routed `/expenses` gated `expenses`; token restyle |

### 15. Payroll (2 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 102 | Pay Run Page | `pages/payroll/PayRunPage.tsx` | ✅ | Task 69 — verbatim bulk pay-run console (generate/finalise/reopen, lazy PayslipDetail drawer); routed `/payroll/run` gated `payroll`; token restyle |
| 103 | Payslip Detail | `pages/payroll/PayslipDetail.tsx` | ✅ | Task 69 — verbatim payslip detail (hours/allowances/deductions/leave + PDF preview); routed `/payroll/payslips/:id` gated `payroll`; token restyle |

### 16. Vehicles (2 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 104 | Vehicle List | `pages/vehicles/VehicleList.tsx` | ✅ | Task 25 — verbatim list/bulk-refresh/manual-entry/CarJam-onboard; styled per Vehicles.html (rego ink chip, traffic-light pills on ok/warn/danger); automotive + `vehicles` module gated |
| 105 | Vehicle Profile | `pages/vehicles/VehicleProfile.tsx` | ✅ | Task 25 — verbatim detail/refresh/expiry-indicators/3 tabs/print+email service report; module-gated PpsrCard ported (`pages/vehicles/components/PpsrCard.tsx`); designed on tokens (FR-2b) |

### 17. PPSR (1 page)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 106 | PPSR Search Page | `pages/ppsr/PPSRSearchPage.tsx` | ✅ | Task 71 — verbatim PPSR search (quota strip + form + result panel + history + detail drawer); routed `/ppsr/search` gated `ppsr`; token restyle |

### 18. Claims (4 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 107 | Claims List | `pages/claims/ClaimsList.tsx` | ✅ | Task 64 — verbatim filterable claims list (useClaimsList); routed `/claims` gated `customer_claims`; token restyle |
| 108 | Claim Create Form | `pages/claims/ClaimCreateForm.tsx` | ✅ | Task 64 — verbatim create (useCreateClaim); routed `/claims/new`; token restyle |
| 109 | Claim Detail | `pages/claims/ClaimDetail.tsx` | ✅ | Task 64 — verbatim detail + status/resolve/note modals; routed `/claims/:id`; token restyle |
| 110 | Claims Reports | `pages/claims/ClaimsReports.tsx` | ✅ | Task 64 — verbatim 4-report tabs (ported useClaimsReports); routed `/claims/reports`; token restyle |

### 19. Compliance (5 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 111 | Compliance Dashboard | `pages/compliance/ComplianceDashboard.tsx` | ✅ | Task 65 — verbatim compliance dashboard (composes table/summary/upload); routed `/compliance` gated `compliance_docs`; token restyle |
| 112 | Document Table | `pages/compliance/DocumentTable.tsx` | ✅ | Task 65 — verbatim document table (expiry status tones); token restyle |
| 113 | File Preview | `pages/compliance/FilePreview.tsx` | ✅ | Task 65 — verbatim file preview; token restyle |
| 114 | Summary Cards | `pages/compliance/SummaryCards.tsx` | ✅ | Task 65 — verbatim summary cards; token restyle |
| 115 | Upload Form | `pages/compliance/UploadForm.tsx` | ✅ | Task 65 — verbatim camera/file upload form; token restyle |

### 20. Construction (5 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 116 | Progress Claim Form | `pages/construction/ProgressClaimForm.tsx` | ✅ | Task 63 — verbatim (inline form embedded in list); ported progressClaimCalcs; token restyle |
| 117 | Progress Claim List | `pages/construction/ProgressClaimList.tsx` | ✅ | Task 63 — verbatim list + inline create; routed `/progress-claims` gated `progress_claims`; token restyle |
| 118 | Retention Summary | `pages/construction/RetentionSummary.tsx` | ✅ | Task 63 — verbatim retention summary (ported retentionCalcs); routed `/retentions` gated `retentions`; token restyle |
| 119 | Variation Form | `pages/construction/VariationForm.tsx` | ✅ | Task 63 — verbatim (inline form embedded in list); ported variationCalcs; token restyle |
| 120 | Variation List | `pages/construction/VariationList.tsx` | ✅ | Task 63 — verbatim list + inline create; routed `/variations` gated `variations`; token restyle |

### 21. Accounting (4 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 121 | Accounting Periods | `pages/accounting/AccountingPeriods.tsx` | ✅ | Task 49 — verbatim period close/lock; routed `/accounting/periods` gated `accounting`; token restyle |
| 122 | Chart Of Accounts | `pages/accounting/ChartOfAccounts.tsx` | ✅ | Task 49 — verbatim COA tree/CRUD; routed `/accounting` gated `accounting`; token restyle |
| 123 | Journal Entries | `pages/accounting/JournalEntries.tsx` | ✅ | Task 49 — verbatim journal list/create; routed `/accounting/journal-entries` gated `accounting`; token restyle |
| 124 | Journal Entry Detail | `pages/accounting/JournalEntryDetail.tsx` | ✅ | Task 49 — verbatim journal detail (useParams :id); routed `/accounting/journal-entries/:id` gated `accounting`; token restyle |

### 22. Banking (3 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 125 | Bank Accounts | `pages/banking/BankAccounts.tsx` | ✅ | Task 50 — verbatim bank account CRUD; routed `/banking/accounts` gated `accounting`; token restyle |
| 126 | Bank Transactions | `pages/banking/BankTransactions.tsx` | ✅ | Task 50 — verbatim transaction list/import; routed `/banking/transactions` gated `accounting`; token restyle |
| 127 | Reconciliation Dashboard | `pages/banking/ReconciliationDashboard.tsx` | ✅ | Task 50 — verbatim reconciliation matching; routed `/banking/reconciliation` gated `accounting`; token restyle |

### 23. Tax (4 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 128 | GST Periods | `pages/tax/GstPeriods.tsx` | ✅ | Task 51 — verbatim GST period list; routed `/tax/gst-periods` gated `accounting`; token restyle |
| 129 | GST Filing Detail | `pages/tax/GstFilingDetail.tsx` | ✅ | Task 51 — verbatim GST filing detail (useParams :id); routed `/tax/gst-periods/:id` gated `accounting`; token restyle |
| 130 | Tax Position | `pages/tax/TaxPosition.tsx` | ✅ | Task 51 — verbatim tax position; routed `/tax/position` gated `accounting`; token restyle |
| 131 | Tax Wallets | `pages/tax/TaxWallets.tsx` | ✅ | Task 51 — verbatim tax wallets; routed `/tax/wallets` gated `accounting`; token restyle |

### 24. Reports (23 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 132 | Reports Page | `pages/reports/ReportsPage.tsx` | ✅ | Task 46 — verbatim Tabs container (10 tabs, vehicles-gated Carjam/Fleet, urlPersist); routed `/reports`; ported PrintButton + print.css; token restyle |
| 133 | Report Builder | `pages/reports/ReportBuilder.tsx` | ✅ | Task 46 — verbatim custom report builder; routed `/reports/builder` (FR-2b); token restyle |
| 134 | Revenue Summary | `pages/reports/RevenueSummary.tsx` | ✅ | Task 46 — verbatim revenue report (ReportsPage tab); token restyle |
| 135 | Profit And Loss | `pages/reports/ProfitAndLoss.tsx` | ✅ | Task 46 — verbatim P&L; routed `/reports/profit-loss` gated `accounting`; token restyle |
| 136 | Balance Sheet | `pages/reports/BalanceSheet.tsx` | ✅ | Task 46 — verbatim balance sheet; routed `/reports/balance-sheet` gated `accounting`; token restyle |
| 137 | Aged Receivables | `pages/reports/AgedReceivables.tsx` | ✅ | Task 46 — verbatim aged receivables; routed `/reports/aged-receivables` gated `accounting`; token restyle |
| 138 | Outstanding Invoices | `pages/reports/OutstandingInvoices.tsx` | ✅ | Task 46 — verbatim (ReportsPage tab); token restyle |
| 139 | Customer Statement | `pages/reports/CustomerStatement.tsx` | ✅ | Task 46 — verbatim (ReportsPage tab, inline CustomerSearchInput); token restyle |
| 140 | GST Return Summary | `pages/reports/GstReturnSummary.tsx` | ✅ | Ported in Task 46 (ReportsPage tab dep) — verbatim; token restyle |
| 141 | Invoice Status | `pages/reports/InvoiceStatus.tsx` | ✅ | Ported in Task 46 (ReportsPage tab dep) — verbatim; token restyle |
| 142 | Inventory Report | `pages/reports/InventoryReport.tsx` | ✅ | Task 47 — verbatim (stock valuation/movement/low/dead sub-reports); routed `/reports/inventory` (FR-2b); token restyle |
| 143 | Job Report | `pages/reports/JobReport.tsx` | ✅ | Task 47 — verbatim (profitability/status/completion/utilisation); routed `/reports/jobs` (FR-2b); token restyle |
| 144 | Fleet Report | `pages/reports/FleetReport.tsx` | ✅ | Ported in Task 46 (ReportsPage tab dep, vehicles-gated) — verbatim; token restyle |
| 145 | Hospitality Report | `pages/reports/HospitalityReport.tsx` | ✅ | Task 47 — verbatim (turnover/AOV/prep/tips); routed `/reports/hospitality` (FR-2b); token restyle |
| 146 | POS Report | `pages/reports/POSReport.tsx` | ✅ | Task 47 — verbatim (daily sales/session recon/hourly heatmap); routed `/reports/pos` (FR-2b); token restyle |
| 147 | Project Report | `pages/reports/ProjectReport.tsx` | ✅ | Task 47 — verbatim (profitability/claims/variations/retentions); routed `/reports/projects` (FR-2b); token restyle |
| 148 | CarJam Usage | `pages/reports/CarjamUsage.tsx` | ✅ | Ported in Task 46 (ReportsPage tab dep, vehicles-gated) — verbatim; token restyle |
| 149 | SMS Usage | `pages/reports/SmsUsage.tsx` | ✅ | Ported in Task 46 (ReportsPage tab dep, purchase-confirm modal) — verbatim; token restyle |
| 150 | Storage Usage | `pages/reports/StorageUsage.tsx` | ✅ | Ported in Task 46 (ReportsPage tab dep) — verbatim; token restyle |
| 151 | Tax Return Report | `pages/reports/TaxReturnReport.tsx` | ✅ | Task 48 — verbatim GST(NZ)/BAS(AU)/VAT(UK) returns; routed `/reports/tax-return` (FR-2b); token restyle |
| 152 | Scheduled Reports | `pages/reports/ScheduledReports.tsx` | ✅ | Task 48 — verbatim schedule create/list/delete; routed `/reports/scheduled` (FR-2b); token restyle |
| 153 | Wage Variance Page | `pages/reports/WageVariancePage.tsx` | ✅ | Task 48 — verbatim wage-variance report (period selector + % threshold, flagged rows); routed `/reports/wage-variance` gated `payroll` (mirrors original); token restyle |
| 154 | Top Services | `pages/reports/TopServices.tsx` | ✅ | Ported in Task 46 (ReportsPage tab dep) — verbatim; token restyle |

### 25. Notifications (8 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 155 | Notifications Page | `pages/notifications/NotificationsPage.tsx` | ✅ | Ported in Task 41 (Settings `notifications` tab dep) — verbatim Tabs container (Preferences/Templates/Log/Reminders/Overdue Rules) |
| 156 | Inbox Page | `pages/notifications/InboxPage.tsx` | ✅ | Task 52 — verbatim in-app inbox (filters/pagination/mark-read, ported InboxItemCard); routed `/notifications/inbox`; token restyle |
| 157 | Notification Log | `pages/notifications/NotificationLog.tsx` | ✅ | Ported in Task 41 (NotificationsPage dep) — verbatim delivery log (filters/pagination/status badges); token restyle |
| 158 | Notification Preferences | `pages/notifications/NotificationPreferences.tsx` | ✅ | Ported in Task 41 (NotificationsPage dep) — verbatim per-type toggles + channel + module-gated category hiding; token restyle |
| 159 | Overdue Rules | `pages/notifications/OverdueRules.tsx` | ✅ | Ported in Task 41 (NotificationsPage dep) — verbatim up-to-3 rules + master toggle + channel map; token restyle |
| 160 | Reminders | `pages/notifications/Reminders.tsx` | ✅ | Ported in Task 41 (NotificationsPage dep) — verbatim manual + automated reminder CRUD grouped by reference date; token restyle |
| 161 | Template Editor | `pages/notifications/TemplateEditor.tsx` | ✅ | Ported in Task 41 (NotificationsPage dep) — verbatim email block editor (drag-drop) + SMS editor + variables + preview; token restyle |
| 162 | WOF Rego Reminders | `pages/notifications/WofRegoReminders.tsx` | ✅ | Task 52 — verbatim WOF/rego reminder settings; routed `/notifications/wof-rego-reminders` (FR-2b); token restyle |

### 26. SMS (2 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 163 | SMS Chat | `pages/sms/SmsChat.tsx` | ✅ | Task 53 — verbatim 2-way SMS chat (conversations, 15s polling, optimistic send, mobile back); routed `/sms` gated `sms`; token restyle |
| 164 | SMS Usage Summary | `pages/sms/SmsUsageSummary.tsx` | ✅ | Task 53 — verbatim SMS usage summary (progress bar, stat cards); routed `/sms/usage` gated `sms` (FR-2b); token restyle |

### 27. Settings (25 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 165 | Settings | `pages/settings/Settings.tsx` | ✅ | Task 41 — verbatim tabbed container (NAV_ITEMS + SECTION_COMPONENTS + adminOnly/module gating + urlPersist); nav restyled to accent-soft active; routed `/settings` gated RequireOrgAdmin (mirrors original) |
| 166 | Org Settings | `pages/settings/OrgSettings.tsx` | ✅ | Task 39 — verbatim 7-tab page (Branding/BusinessType/GST/Invoice/Inventory/Terms/Portal); token restyle |
| 167 | Business Settings | `pages/settings/BusinessSettings.tsx` | ✅ | Task 39 — verbatim entity-type/NZBN/GST-registration/tax settings; token restyle |
| 168 | Branch Management | `pages/settings/BranchManagement.tsx` | ✅ | Task 39 — verbatim branch CRUD + staff-invite flow (inline helpers); token restyle |
| 169 | Branch Settings | `pages/settings/BranchSettings.tsx` | ✅ | Task 39 — verbatim per-branch settings (self-gates `branch_management`); token restyle |
| 170 | Billing | `pages/settings/Billing.tsx` | ✅ | Task 39 — verbatim (1787 lines): trial/plan/storage/CarJam/SMS/branch-cost cards + plan/interval/storage modals + PaymentMethodManager/CardForm; token restyle |
| 171 | Profile | `pages/settings/Profile.tsx` | ✅ | Task 39 — verbatim profile edit + password change + embedded MfaSettings; reuses PasswordRequirements; token restyle |
| 172 | Security Settings | `pages/settings/SecuritySettings.tsx` | ✅ | Task 39 — verbatim org security sections (MFA enforcement/password policy/lockout/roles/session/audit log); token restyle |
| 173 | MFA Settings | `pages/settings/MfaSettings.tsx` | ✅ | Task 39 — verbatim TOTP/SMS/email/passkey enrol wizards + backup codes + PasswordConfirmModal; token restyle |
| 174 | User Management | `pages/settings/UserManagement.tsx` | ✅ | Task 40 — verbatim org-user CRUD + invite/role/branch assignment; token restyle |
| 175 | Module Configuration | `pages/settings/ModuleConfiguration.tsx` | ✅ | Task 40 — verbatim module enable/disable grid (cascadeDisable/autoEnableDependencies/isComingSoon via ported moduleCalcs util); token restyle |
| 176 | Invoice Template Tab | `pages/settings/InvoiceTemplateTab.tsx` | ✅ | Task 40 — verbatim invoice template config + live preview; token restyle |
| 177 | Currency Settings | `pages/settings/CurrencySettings.tsx` | ✅ | Task 40 — verbatim multi-currency + exchange-rate CRUD (ported currencyCalcs util, ISO-4217 list byte-preserved); token restyle |
| 178 | Language Switcher | `pages/settings/LanguageSwitcher.tsx` | ✅ | Task 40 — verbatim locale switcher (i18n keys confirmed in v2 en.json); token restyle |
| 179 | Online Payments Settings | `pages/settings/OnlinePaymentsSettings.tsx` | ✅ | Task 40 — verbatim (1091 lines) Stripe Connect onboarding/status + inline brand SVGs; token restyle |
| 180 | Integrations Settings | `pages/settings/IntegrationsSettings.tsx` | ✅ | Task 40 — verbatim integrations list/config; token restyle |
| 181 | Accounting Integrations | `pages/settings/AccountingIntegrations.tsx` | ✅ | Task 40 — verbatim Xero connect/sync/webhook config; token restyle |
| 182 | Webhook Management | `pages/settings/WebhookManagement.tsx` | ✅ | Task 41 — verbatim outbound webhook CRUD + test + delivery log + health/auto-disable (ported webhookUtils); Settings tab |
| 183 | Webhook Settings | `pages/settings/WebhookSettings.tsx` | ✅ | Task 41 — verbatim webhook CRUD + delivery log (v1 `/webhooks`); token restyle |
| 184 | Feature Flag Settings | `pages/settings/FeatureFlagSettings.tsx` | ✅ | Task 41 — verbatim flag grid + category sections + global-admin rollout monitoring (ported featureFlagCalcs); Settings tab |
| 185 | Printer Settings | `pages/settings/PrinterSettings.tsx` | ✅ | Task 41 — verbatim printer CRUD + protocol auto-detect + test print (ported protocolDetector; reused printerConnection/drivers); Settings tab |
| 186 | Allowance Types | `pages/settings/people/AllowanceTypesPage.tsx` | ✅ | Task 41 — verbatim CRUD (`@/api/payslips`); routed `/settings/people/allowance-types` gated `payroll` (mirrors original) |
| 187 | Clock In Policy | `pages/settings/people/ClockInPolicyPage.tsx` | ✅ | Task 41 — verbatim clock-in + overtime policy cards (G1/G8/G17); Settings tab |
| 188 | Leave Types | `pages/settings/people/LeaveTypesPage.tsx` | ✅ | Task 41 — verbatim leave-type CRUD + statutory floors + above-minimum badge (`@/api/leave`); Settings tab |
| 189 | Pay Periods | `pages/settings/people/PayPeriodsPage.tsx` | ✅ | Task 41 — verbatim pay-period CRUD + reopen (G21) (`@/api/payslips`); routed `/settings/people/pay-periods` gated `payroll` (mirrors original) |
| 190 | Permissions | `pages/settings/people/PermissionsPage.tsx` | ✅ | Task 41 — verbatim FV-leave-view permission manager + 30-day nag (`@/api/leave`); Settings tab |


### 28. Admin (25 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 191 | Organisations | `pages/admin/Organisations.tsx` | ✅ | Task 42 — verbatim org list/search/suspend/delete; AdminLayout shell + `/admin/*` route tree wired; ported usePageMeta + GlobalSearchBar deps; token restyle |
| 192 | Organisation Detail | `pages/admin/OrganisationDetail.tsx` | ✅ | Task 42 — verbatim (1443 lines) org detail (plan/usage/branches/users/coupons + suspend/move-plan/delete modals); routed `/admin/organisations/:orgId`; token restyle |
| 193 | User Management | `pages/admin/UserManagement.tsx` | ✅ | Task 42 — verbatim platform user management (distinct from settings UserManagement); routed `/admin/users`; token restyle |
| 194 | Subscription Plans | `pages/admin/SubscriptionPlans.tsx` | ✅ | Task 42 — verbatim (1841 lines) plan/storage-package/coupon CRUD (4-tab form, coupon-utils); routed `/admin/plans`; token restyle |
| 195 | Trade Families | `pages/admin/TradeFamilies.tsx` | ✅ | Task 42 — verbatim trade-family CRUD + edit modal; routed `/admin/trade-families`; token restyle |
| 196 | Feature Flags | `pages/admin/FeatureFlags.tsx` | ✅ | Task 43 — verbatim platform flag toggles + dependency-warning modal + category sections; routed `/admin/feature-flags`; token restyle |
| 197 | Analytics Dashboard | `pages/admin/AnalyticsDashboard.tsx` | ✅ | Task 43 — verbatim analytics (inline bar/heatmap/funnel charts retinted to tokens); routed `/admin/analytics`; safe-API hardened |
| 198 | Audit Log | `pages/admin/AuditLog.tsx` | ✅ | Task 43 — verbatim audit log (filters + detail modal); routed `/admin/audit-log`; token restyle + AbortController |
| 199 | Error Log | `pages/admin/ErrorLog.tsx` | ✅ | Task 43 — verbatim error log (summary cards, severity rows, status/notes modal); routed `/admin/errors`; token restyle |
| 200 | Admin Settings | `pages/admin/Settings.tsx` | ✅ | Task 43 — verbatim platform settings (Vehicle DB / T&C / Privacy / Announcements / Signup Billing tabs); routed `/admin/settings`; token restyle |
| 201 | Admin Security | `pages/admin/AdminSecurityPage.tsx` | ✅ | Task 43 — verbatim MFA/sessions/change-password/audit-log collapsibles (ported PlatformSecurityAuditLogSection); routed `/admin/security`; token restyle |
| 202 | Branding Config | `pages/admin/BrandingConfig.tsx` | ✅ | Task 44 — verbatim platform branding form + preview (THEMES registry); routed `/admin/branding`; token restyle |
| 203 | Calendar Sync | `pages/admin/CalendarSync.tsx` | ✅ | Task 44 — verbatim public-holiday calendar sync; Integrations tab; token restyle |
| 204 | Email Delivery Health | `pages/admin/EmailDeliveryHealth.tsx` | ✅ | Task 44 — verbatim delivery health stats + bounce table; EmailProviders tab; token restyle |
| 205 | Email Providers | `pages/admin/EmailProviders.tsx` | ✅ | Task 44 — verbatim multi-active email provider config + delivery-health tab; Integrations tab; token restyle |
| 206 | SMS Providers | `pages/admin/SmsProviders.tsx` | ✅ | Task 44 — verbatim (934 lines) SMS provider config + fallback chain; Integrations tab; token restyle |
| 207 | Global Admin Profile | `pages/admin/GlobalAdminProfile.tsx` | ✅ | Task 44 — verbatim profile + password + MfaSettings; routed `/admin/profile`; token restyle |
| 208 | Global Branch Overview | `pages/admin/GlobalBranchOverview.tsx` | ✅ | Task 44 — verbatim cross-org branch overview (search/pagination); routed `/admin/branches`; token restyle |
| 209 | HA Replication | `pages/admin/HAReplication.tsx` | ✅ | Task 44 — verbatim (3252 lines) HA node status/failover/config; routed `/admin/ha-replication`; ok/warn/danger status tokens |
| 210 | Integrations | `pages/admin/Integrations.tsx` | ✅ | Task 44 — verbatim (847 lines) integrations hub (Stripe setup/test + SMS/Email/Calendar/Xero tabs); routed `/admin/integrations`; ported StripeSetupGuide/StripeTestSuite |
| 211 | Live Migration Tool | `pages/admin/LiveMigrationTool.tsx` | ✅ | Task 44 — verbatim (1107 lines) live migration; routed `/admin/live-migration`; token restyle |
| 212 | Migration Tool | `pages/admin/MigrationTool.tsx` | ✅ | Task 44 — verbatim migration tool (restyled unstyled semantic classes to tokens); routed `/admin/migration` |
| 213 | Notification Manager | `pages/admin/NotificationManager.tsx` | ✅ | Task 44 — verbatim platform notification CRUD + maintenance countdown; routed `/admin/notifications`; token restyle |
| 214 | Admin Reports | `pages/admin/Reports.tsx` | ✅ | Task 44 — verbatim platform reports (MRR/orgs/churn); routed `/admin/reports`; ported DateRangeFilter/ExportButtons/SimpleBarChart |
| 215 | Xero Credentials | `pages/admin/XeroCredentialsSettings.tsx` | ✅ | Task 44 — verbatim Xero credential config; Integrations tab; token restyle |

### 29. Kiosk (7 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 216 | Kiosk Page | `pages/kiosk/KioskPage.tsx` | ✅ | Task 60 — verbatim multi-step orchestrator (welcome→rego→summary→form→success + QR popup poll + long-press logout); routed `/kiosk` (RequireAuth); self-contained full-screen chrome; token restyle |
| 217 | Kiosk Welcome | `pages/kiosk/KioskWelcome.tsx` | ✅ | Task 60 — verbatim org-branding welcome; KioskPage step; token restyle |
| 218 | Kiosk Rego Entry | `pages/kiosk/KioskRegoEntry.tsx` | ✅ | Task 60 — verbatim rego lookup (404/429 handling, AbortController); KioskPage step; token restyle |
| 219 | Kiosk Vehicle Summary | `pages/kiosk/KioskVehicleSummary.tsx` | ✅ | Task 60 — verbatim vehicle confirm + odometer + add-another (WOF/COF via vehicleHelpers); KioskPage step; token restyle |
| 220 | Kiosk Check-In Form | `pages/kiosk/KioskCheckInForm.tsx` | ✅ | Task 60 — verbatim debounced auto-fill + confirm-email + check-in submit (validateKioskForm); KioskPage step; token restyle |
| 221 | Kiosk Clock Screen | `pages/kiosk/KioskClockScreen.tsx` | ✅ | Task 60 — verbatim staff clock-in/out (keypad→identity→camera getUserMedia→confirmation, 8s auto-return); routed `/kiosk/clock` (FR-2b); token restyle |
| 222 | Kiosk Success | `pages/kiosk/KioskSuccess.tsx` | ✅ | Task 60 — verbatim 10s countdown ring confirmation; KioskPage step; token restyle |

### 30. POS (6 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 223 | POS Screen | `pages/pos/POSScreen.tsx` | ✅ | Task 54 — verbatim touch POS (offline store/sync, barcode, payment+print); routed `/pos` gated `pos`; token restyle |
| 224 | Order Panel | `pages/pos/OrderPanel.tsx` | ✅ | Task 54 — verbatim (calculateOrderTotals byte-identical); POSScreen sub-component |
| 225 | Payment Panel | `pages/pos/PaymentPanel.tsx` | ✅ | Task 54 — verbatim cash/card/split; POSScreen sub-component |
| 226 | Product Grid | `pages/pos/ProductGrid.tsx` | ✅ | Task 54 — verbatim category/search tiles; POSScreen sub-component |
| 227 | Sync Status | `pages/pos/SyncStatus.tsx` | ✅ | Task 54 — verbatim pending/synced/failed dashboard; POSScreen sub-component |
| 228 | Tip Prompt | `pages/pos/TipPrompt.tsx` | ✅ | Task 54 — verbatim tip prompt + management (distributeTips); ported tippingCalcs |

### 31. Portal (20 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 229 | Portal Page | `pages/portal/PortalPage.tsx` | ✅ | Task 57 — verbatim self-contained portal (branded header/summary cards/13 tabs/footer, referrer-meta, history.replaceState, sign-out); routed `/portal/:token` (public); token restyle |
| 230 | My Details | `pages/portal/MyDetails.tsx` | ✅ | Task 57 — verbatim contact-detail edit; PortalPage section; token restyle |
| 231 | My Privacy | `pages/portal/MyPrivacy.tsx` | ✅ | Task 57 — verbatim privacy/data-request controls; PortalPage section; token restyle |
| 232 | Invoice History | `pages/portal/InvoiceHistory.tsx` | ✅ | Task 57 — verbatim invoice list + Pay Now (→PaymentPage); PortalPage tab; token restyle |
| 233 | Vehicle History | `pages/portal/VehicleHistory.tsx` | ✅ | Task 57 — verbatim vehicle/service history + expiry badges; PortalPage tab; token restyle |
| 234 | Asset History | `pages/portal/AssetHistory.tsx` | ✅ | Task 57 — verbatim asset history; PortalPage tab; token restyle |
| 235 | Booking Manager | `pages/portal/BookingManager.tsx` | ✅ | Task 57 — verbatim customer booking manager; PortalPage tab; token restyle |
| 236 | Claims Tab | `pages/portal/ClaimsTab.tsx` | ✅ | Task 57 — verbatim claims list; PortalPage tab; token restyle |
| 237 | Documents Tab | `pages/portal/DocumentsTab.tsx` | ✅ | Task 57 — verbatim document list/download; PortalPage tab; token restyle |
| 238 | Jobs Tab | `pages/portal/JobsTab.tsx` | ✅ | Task 57 — verbatim jobs list; PortalPage tab; token restyle |
| 239 | Loyalty Balance | `pages/portal/LoyaltyBalance.tsx` | ✅ | Task 58 — verbatim loyalty balance/history; PortalPage tab; token restyle |
| 240 | Messages Tab | `pages/portal/MessagesTab.tsx` | ✅ | Task 58 — verbatim message thread; PortalPage tab; token restyle |
| 241 | Payment Page | `pages/portal/PaymentPage.tsx` | ✅ | Task 58 — verbatim pay flow (POST→Stripe-hosted redirect); used by InvoiceHistory (prop-driven, not routed); token restyle |
| 242 | Payment Success | `pages/portal/PaymentSuccess.tsx` | ✅ | Task 58 — verbatim post-payment confirmation; routed `/portal/:token/payment-success` (public); token restyle |
| 243 | Projects Tab | `pages/portal/ProjectsTab.tsx` | ✅ | Task 58 — verbatim projects list; PortalPage tab; token restyle |
| 244 | Progress Claims Tab | `pages/portal/ProgressClaimsTab.tsx` | ✅ | Task 58 — verbatim progress claims; PortalPage tab; token restyle |
| 245 | Quote Acceptance | `pages/portal/QuoteAcceptance.tsx` | ✅ | Task 58 — verbatim quote accept/decline; PortalPage tab; token restyle |
| 246 | Recurring Tab | `pages/portal/RecurringTab.tsx` | ✅ | Task 58 — verbatim recurring schedules; PortalPage tab; token restyle |
| 247 | Portal Recover | `pages/portal/PortalRecover.tsx` | ✅ | Task 58 — verbatim "forgot link" recovery; routed `/portal/recover` (public); token restyle |
| 248 | Portal Signed Out | `pages/portal/PortalSignedOut.tsx` | ✅ | Task 58 — verbatim post-logout confirmation; routed `/portal/signed-out` (public); token restyle |

### 32. Public Pages (9 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 249 | Landing Page | `pages/public/LandingPage.tsx` | ✅ | Task 61 — verbatim marketing landing (hero/features/JSON-LD, DemoRequestModal); routed `/` GuestOnly via ManagedPage; bespoke marketing styling preserved |
| 250 | Invoice Payment Page | `pages/public/InvoicePaymentPage.tsx` | ✅ | Task 62 — verbatim public Stripe Elements invoice payment; routed `/pay/:token`; token restyle |
| 251 | Managed Page | `pages/public/ManagedPage.tsx` | ✅ | Task 61 — verbatim Puck content-swap wrapper (registry + fallback); wraps landing/privacy/trades/workshop |
| 252 | Page Shell | `pages/public/PageShell.tsx` | ✅ | Task 62 — verbatim public page shell (LandingHeader/Footer + resetH1Counter) |
| 253 | Privacy Page | `pages/public/PrivacyPage.tsx` | ✅ | Task 61 — verbatim NZ Privacy Act content + JSON-LD; routed `/privacy` via ManagedPage |
| 254 | Public Page Renderer | `pages/public/PublicPageRenderer.tsx` | ✅ | Task 62 — verbatim Puck slug-resolver catch-all; routed `*` (ported puckConfig + 19 render blocks) |
| 255 | Staff Roster Public View | `pages/public/StaffRosterPublicView.tsx` | ✅ | Task 62 — verbatim token-gated public roster; routed `/public/staff-roster/:token` |
| 256 | Trades Page | `pages/public/TradesPage.tsx` | ✅ | Task 61 — verbatim trades marketing + JSON-LD breadcrumbs; routed `/trades` via ManagedPage |
| 257 | Workshop Page | `pages/public/WorkshopPage.tsx` | ✅ | Task 61 — verbatim workshop marketing + 3-entity JSON-LD; routed `/workshop` (+ /mechanics, /garage redirects) via ManagedPage |

### 33. Purchase Orders (2 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 258 | PO List | `pages/purchase-orders/POList.tsx` | ✅ | Task 70 — verbatim PO list + create/supplier/part modals; routed `/purchase-orders` gated `purchase_orders`; token restyle |
| 259 | PO Detail | `pages/purchase-orders/PODetail.tsx` | ✅ | Task 70 — verbatim PO detail (receive-goods/send/cancel); routed `/purchase-orders/:id`; token restyle |

### 34. Recurring (1 page)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 260 | Recurring List | `pages/recurring/RecurringList.tsx` | ✅ | Task 70 — verbatim recurring schedule list/CRUD; routed `/recurring` gated `recurring_invoices`; token restyle |

### 35. Franchise (5 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 261 | Franchise Dashboard | `pages/franchise/FranchiseDashboard.tsx` | ✅ | Task 66 — verbatim franchise dashboard (ported franchiseUtils); routed `/franchise` gated `franchise`; token restyle |
| 262 | Location List | `pages/franchise/LocationList.tsx` | ✅ | Task 66 — verbatim location list; routed `/locations` gated `franchise`; token restyle |
| 263 | Location Detail | `pages/franchise/LocationDetail.tsx` | ✅ | Task 66 — verbatim location detail (locationId prop via LocationDetailRoute); routed `/locations/:id`; token restyle |
| 264 | Stock Transfers | `pages/franchise/StockTransfers.tsx` | ✅ | Task 66 — verbatim franchise stock transfers; routed `/stock-transfers` gated `franchise`; token restyle |
| 265 | Transfer Detail | `pages/franchise/TransferDetail.tsx` | ✅ | Task 66 — verbatim transfer detail (transferId prop via TransferDetailRoute); routed `/stock-transfers/:id`; token restyle |

### 36. Projects (2 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 266 | Project Dashboard | `pages/projects/ProjectDashboard.tsx` | ✅ | Task 67 — verbatim project detail (projectId prop via ProjectDashboardRoute); routed `/projects/:id` gated `projects`; token restyle |
| 267 | Project List | `pages/projects/ProjectList.tsx` | ✅ | Task 67 — verbatim project list; routed `/projects` gated `projects`; token restyle |

### 37. Floor Plan (2 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 268 | Floor Plan | `pages/floor-plan/FloorPlan.tsx` | ✅ | Task 55 — verbatim drag/resize/merge/split + pinch-zoom + 10s polling (ported tableCalcs); routed `/floor-plan` gated `tables`; token restyle |
| 269 | Reservation List | `pages/floor-plan/ReservationList.tsx` | ✅ | Task 55 — verbatim list/calendar + create form; routed `/reservations` gated `tables` (FR-2b); token restyle |

### 38. Kitchen (1 page)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 270 | Kitchen Display | `pages/kitchen/KitchenDisplay.tsx` | ✅ | Task 55 — verbatim WebSocket order tickets (urgency timer, backoff reconnect, mark-prepared); routed `/kitchen` gated `kitchen_display`; token restyle |

### 39. Loyalty (1 page)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 271 | Loyalty Config | `pages/loyalty/LoyaltyConfig.tsx` | ✅ | Task 71 — verbatim loyalty config (tiers/balance/analytics/adjust, ported loyaltyCalcs); routed `/loyalty` gated `loyalty`; token restyle |

### 40. E-commerce (3 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 272 | WooCommerce Setup | `pages/ecommerce/WooCommerceSetup.tsx` | ✅ | Task 68 — verbatim WooCommerce connect/sync; routed `/ecommerce` gated `ecommerce`; token restyle |
| 273 | SKU Mappings | `pages/ecommerce/SkuMappings.tsx` | ✅ | Task 68 — verbatim SKU mapping CRUD; routed `/ecommerce/sku-mappings` (FR-2b); token restyle |
| 274 | API Keys | `pages/ecommerce/ApiKeys.tsx` | ✅ | Task 68 — verbatim API key management; routed `/ecommerce/api-keys` (FR-2b); token restyle |

### 41. Data (4 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 275 | Data Page | `pages/data/DataPage.tsx` | ✅ | Task 68 — verbatim tabbed data hub (Export/Import/JSON); routed `/data`; token restyle |
| 276 | Data Export | `pages/data/DataExport.tsx` | ✅ | Task 68 — verbatim export (DataPage tab); token restyle |
| 277 | Data Import | `pages/data/DataImport.tsx` | ✅ | Task 68 — verbatim import (DataPage tab); token restyle |
| 278 | JSON Bulk Import | `pages/data/JsonBulkImport.tsx` | ✅ | Task 68 — verbatim JSON bulk import (DataPage tab); token restyle |

### 42. Onboarding & Setup (12 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 279 | Onboarding Wizard | `pages/onboarding/OnboardingWizard.tsx` | ✅ | Task 72 — verbatim 6-step onboarding wizard; routed `/onboarding`; token restyle |
| 280 | Setup Wizard | `pages/setup/SetupWizard.tsx` | ✅ | Task 72 — verbatim setup wizard (step state machine + API submission + StepIndicator/InvoicePreview); routed `/setup`; token restyle |
| 281 | Branding Step | `pages/setup/steps/BrandingStep.tsx` | ✅ | Task 72 — verbatim SetupWizard step; token restyle |
| 282 | Business Step | `pages/setup/steps/BusinessStep.tsx` | ✅ | Task 72 — verbatim SetupWizard step; token restyle |
| 283 | Catalogue Step | `pages/setup/steps/CatalogueStep.tsx` | ✅ | Task 72 — verbatim SetupWizard step; token restyle |
| 284 | Country Step | `pages/setup/steps/CountryStep.tsx` | ✅ | Task 72 — verbatim SetupWizard step; token restyle |
| 285 | Modules Step | `pages/setup/steps/ModulesStep.tsx` | ✅ | Task 72 — verbatim SetupWizard step (AbortController added); token restyle |
| 286 | Ready Step | `pages/setup/steps/ReadyStep.tsx` | ✅ | Task 72 — verbatim SetupWizard step; token restyle |
| 287 | Trade Step | `pages/setup/steps/TradeStep.tsx` | ✅ | Task 72 — verbatim SetupWizard step (AbortController added); token restyle |
| 288 | Setup Guide | `pages/setup-guide/SetupGuide.tsx` | ✅ | Task 72 — verbatim setup guide state machine; routed `/setup-guide`; token restyle |
| 289 | Welcome Screen | `pages/setup-guide/WelcomeScreen.tsx` | ✅ | Task 72 — verbatim SetupGuide screen; token restyle |
| 290 | Summary Screen | `pages/setup-guide/SummaryScreen.tsx` | ✅ | Task 72 — verbatim SetupGuide screen; token restyle |

### 43. Payments (2 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 291 | QR Payment Success | `pages/payments/QrPaymentSuccess.tsx` | ✅ | Task 62 — verbatim QR payment success result; routed `/payments/qr-success` (public) |
| 292 | QR Payment Cancel | `pages/payments/QrPaymentCancel.tsx` | ✅ | Task 62 — verbatim QR payment cancel result; routed `/payments/qr-cancel` (public) |

### 44. Assets (2 pages)

| # | Page | Source File | Status | Notes |
|---|------|-------------|--------|-------|
| 293 | Asset List | `pages/assets/AssetList.tsx` | ✅ | Task 71 — verbatim asset list (self-gates assets module); routed `/assets` gated `assets`; token restyle |
| 294 | Asset Detail | `pages/assets/AssetDetail.tsx` | ✅ | Task 71 — verbatim asset detail (assetId prop via AssetDetailRoute, CarJam JSON, service history); routed `/assets/:id`; token restyle |

---

## MODALS / POPUPS / DRAWERS

### Admin Modals (4)

| # | Modal | Source File | Status | Notes |
|---|-------|-------------|--------|-------|
| 1 | Apply Coupon Modal | `components/admin/ApplyCouponModal.tsx` | ✅ | Ported in Task 42 (Organisations/OrganisationDetail dep) — verbatim coupon apply; token restyle |
| 2 | Delete Modal | `components/admin/DeleteModal.tsx` | ✅ | Ported in Task 42 — verbatim confirm-delete; token restyle |
| 3 | Move Plan Modal | `components/admin/MovePlanModal.tsx` | ✅ | Ported in Task 42 — verbatim move-plan; token restyle |
| 4 | Suspend Modal | `components/admin/SuspendModal.tsx` | ✅ | Ported in Task 42 — verbatim suspend/reactivate; token restyle |

### Auth Modals (1)

| # | Modal | Source File | Status | Notes |
|---|-------|-------------|--------|-------|
| 5 | MFA Modal | `components/auth/MfaModal.tsx` | ✅ | Task 13 — verbatim MFA challenge modal (used by Login); token restyle |

### Billing Modals (2)

| # | Modal | Source File | Status | Notes |
|---|-------|-------------|--------|-------|
| 6 | Blocking Payment Modal | `components/billing/BlockingPaymentModal.tsx` | ✅ | Task 74 — verbatim non-dismissible Stripe add-payment modal; wired into OrgLayout via usePaymentMethodEnforcement; token restyle |
| 7 | Expiring Payment Warning | `components/billing/ExpiringPaymentWarningModal.tsx` | ✅ | Task 74 — verbatim dismissible expiry warning; wired into OrgLayout; token restyle |

### Claims Modals (2)

| # | Modal | Source File | Status | Notes |
|---|-------|-------------|--------|-------|
| 8 | Claim Note Modal | `components/claims/ClaimNoteModal.tsx` | ✅ | Task 64 — verbatim note modal; token restyle |
| 9 | Claim Resolve Modal | `components/claims/ClaimResolveModal.tsx` | ✅ | Task 64 — verbatim resolve modal (resolution type/amount); token restyle |

### Customer Modals (4)

| # | Modal | Source File | Status | Notes |
|---|-------|-------------|--------|-------|
| 10 | Customer Create Modal | `components/customers/CustomerCreateModal.tsx` | ✅ | Ported in Task 20 (needed by InvoiceCreate's customer search; shared with Tasks 23/25) — full tabs/address/contacts/kiosk-mode/display-name-suggester logic verbatim; needs PhoneInput + Select (also ported). Neutral palette kept; full token restyle owned by Tasks 23/25 |
| 11 | Customer Edit Modal | `components/customers/CustomerEditModal.tsx` | ✅ | Ported in Task 23 (shared with Task 25) — full edit form + token restyle |
| 12 | Customer View Modal | `components/customers/CustomerViewModal.tsx` | ✅ | Ported in Task 23 (shared with Task 25) — read-only detail + token restyle |
| 13 | Vehicle Picker Modal | `components/customers/VehiclePickerModal.tsx` | ✅ | Ported in Task 23 (shared with Task 25) — vehicle search/pick + token restyle |

### Inventory Modals (1)

| # | Modal | Source File | Status | Notes |
|---|-------|-------------|--------|-------|
| 14 | Add To Stock Modal | `components/inventory/AddToStockModal.tsx` | ✅ | Ported in Task 20 (needed by InvoiceCreate's "Quick Add Stock"; shared with Tasks 35-38) — 3-step wizard (category→catalogue→details) + InlineCreateForm + supplier/location create, pricing maths, trade-family category gating verbatim. Neutral palette kept; full token restyle owned by Tasks 35-38 |

### Invoice Modals (5)

| # | Modal | Source File | Status | Notes |
|---|-------|-------------|--------|-------|
| 15 | Credit Note Modal | `components/invoices/CreditNoteModal.tsx` | ✅ | Ported in Task 19 (shared with Task 22) — logic verbatim, restyled to tokens; uses ported FormField + Toast |
| 16 | Refund Modal | `components/invoices/RefundModal.tsx` | ✅ | Ported in Task 19 (shared with Task 22) — logic verbatim incl. confirm step + ISSUE-072 Stripe-disabled option |
| 17 | Issue Invoice Modal | `pages/invoices/IssueInvoiceModal.tsx` | ✅ | Ported in Task 20 (shared with Task 22) — payment-method radio group with Stripe gating + email-invoice checkbox, reset-on-open, onConfirm(method, shouldEmail) verbatim; restyled to tokens |
| 18 | QR Payment Amount Modal | `pages/invoices/QrPaymentAmountModal.tsx` | ✅ | Ported in Task 19 (shared with Task 22) — full/partial mode, sanitisation + Stripe $0.50/balance validation verbatim |
| 19 | QR Payment Waiting Popup | `pages/invoices/QrPaymentWaitingPopup.tsx` | ✅ | Ported in Task 19 (shared with Task 22) — 3s status polling + success/superseded states verbatim |

### MFA Modals (1)

| # | Modal | Source File | Status | Notes |
|---|-------|-------------|--------|-------|
| 20 | Password Confirm Modal | `components/mfa/PasswordConfirmModal.tsx` | ✅ | Ported in Task 39 (MfaSettings/SecuritySettings dep) — verbatim password re-auth modal; token restyle (full ownership Task 74) |

### Offline Modals (1)

| # | Modal | Source File | Status | Notes |
|---|-------|-------------|--------|-------|
| 21 | Conflict Resolution Modal | `components/offline/ConflictResolutionModal.tsx` | ✅ | Task 74 — verbatim sync-conflict resolution modal (+ ported OfflineContext/useOffline/offlineStorage/OfflineBanner); token restyle |

### POS Modals (1)

| # | Modal | Source File | Status | Notes |
|---|-------|-------------|--------|-------|
| 22 | Printer Error Modal | `components/pos/PrinterErrorModal.tsx` | ✅ | Ported earlier (InvoiceDetail/POSScreen dep) — verbatim printer-error retry/fallback modal; token restyle |

### Public Modals (1)

| # | Modal | Source File | Status | Notes |
|---|-------|-------------|--------|-------|
| 23 | Demo Request Modal | `components/public/DemoRequestModal.tsx` | ✅ | Task 61/62 — verbatim demo-request modal (LandingPage dep); ported with components/public |

### Quote Modals (2)

| # | Modal | Source File | Status | Notes |
|---|-------|-------------|--------|-------|
| 24 | Cancel Quote Modal | `components/quotes/CancelQuoteModal.tsx` | ✅ | Task 22 (ported in Task 21 quote work) |
| 25 | Inventory Picker Modal | `components/quotes/InventoryPickerModal.tsx` | ✅ | Task 22 (ported in Task 21 quote work) |

### UI Base Components (2)

| # | Modal | Source File | Status | Notes |
|---|-------|-------------|--------|-------|
| 26 | Confirm Dialog | `components/ui/ConfirmDialog.tsx` | ✅ | Task 73 — Headless UI dialog with design tokens; used across pages |
| 27 | Modal (base) | `components/ui/Modal.tsx` | ✅ | Task 73 — Headless UI base Modal (backdrop/transitions, design tokens); used by all modals |

### Bookings Modals (1)

| # | Modal | Source File | Status | Notes |
|---|-------|-------------|--------|-------|
| 28 | Job Creation Modal | `pages/bookings/JobCreationModal.tsx` | ✅ | Task 28/29 — verbatim booking→job-card convert w/ StaffPicker (admin) + success animation; exports mapBookingToJobPreFill |

### Compliance Modals (2)

| # | Modal | Source File | Status | Notes |
|---|-------|-------------|--------|-------|
| 29 | Delete Confirmation | `pages/compliance/DeleteConfirmation.tsx` | ✅ | Task 65 — verbatim delete-confirm modal; token restyle |
| 30 | Edit Modal | `pages/compliance/EditModal.tsx` | ✅ | Task 65 — verbatim compliance-doc edit modal; token restyle |

### Items Modals (2)

| # | Modal | Source File | Status | Notes |
|---|-------|-------------|--------|-------|
| 31 | Service Type Modal | `pages/items/ServiceTypeModal.tsx` | ✅ | Task 37 — verbatim service-type field builder modal (ItemsPage ServiceTypesTab dep); token restyle |
| 32 | Stock Source Modal | `pages/items/components/StockSourceModal.tsx` | ✅ | Task 38 — verbatim stock-source picker (existing/new) used by PartsCatalogue; shared Modal + token restyle |

### Jobs Modals (1)

| # | Modal | Source File | Status | Notes |
|---|-------|-------------|--------|-------|
| 33 | Take Over Dialog | `pages/jobs/TakeOverDialog.tsx` | ✅ | Ported in Task 26 (needed by JobsPage) — verbatim takeover-note → PUT assign + toasts; shared Modal + token textarea |

### Kiosk Modals (1)

| # | Modal | Source File | Status | Notes |
|---|-------|-------------|--------|-------|
| 34 | Kiosk QR Popup | `pages/kiosk/KioskQrPopup.tsx` | ✅ | Task 60 — verbatim QR payment popup (QRCodeSVG, 3s status poll, countdown, success state); token restyle |

### PPSR Modals (1)

| # | Modal | Source File | Status | Notes |
|---|-------|-------------|--------|-------|
| 35 | PPSR Detail Drawer | `pages/ppsr/components/PpsrDetailDrawer.tsx` | ✅ | Ported in Task 71 (PPSRSearchPage dep) — verbatim PPSR result detail drawer; token restyle |

### Schedule Modals (1)

| # | Modal | Source File | Status | Notes |
|---|-------|-------------|--------|-------|
| 36 | Schedule Entry Modal | `pages/schedule/ScheduleEntryModal.tsx` | ✅ | Ported in Task 30 (ScheduleCalendar dep), reconciled Task 32 |

### Staff Modals (10)

| # | Modal | Source File | Status | Notes |
|---|-------|-------------|--------|-------|
| 37 | Add Recurring Allowance | `pages/staff/components/AddRecurringAllowanceModal.tsx` | ✅ | Ported Task 30 (RecurringAllowancesPanel dep) |
| 38 | Approve Week Modal | `pages/staff/components/ApproveWeekModal.tsx` | ✅ | Task 34 — verbatim totals split + flagged ack + TOIL choice + approve POST; token restyle |
| 39 | Flag For Review Modal | `pages/staff/components/FlagForReviewModal.tsx` | ✅ | Task 34 — verbatim flag POST + 403/404 mapping; token restyle |
| 40 | Manual Entry Modal | `pages/staff/components/ManualEntryModal.tsx` | ✅ | Task 34 — verbatim create/edit clock entry (ISO↔local), week_locked/invalid_range; token restyle |
| 41 | Minimum Wage Warning | `pages/staff/components/MinimumWageWarningModal.tsx` | ✅ | Ported Task 30 (OverviewTab dep) |
| 42 | Overtime Request Modal | `pages/staff/components/OvertimeRequestModal.tsx` | ✅ | Task 34 — verbatim overtime-request POST + min/max validation; token restyle |
| 43 | Running Late Sheet | `pages/staff/components/RunningLateSheet.tsx` | ✅ | Ported Task 31 (SelfServiceClockScreen dep) |
| 44 | Termination Modal | `pages/staff/components/TerminationModal.tsx` | ✅ | Task 34 — verbatim termination workflow (end_date/reason/final-pay options, G16/G25 banners); shared Modal+AlertBanner |

### Staff Leave Modals (2)

| # | Modal | Source File | Status | Notes |
|---|-------|-------------|--------|-------|
| 45 | Adjust Balance Modal | `pages/staff/leave/AdjustBalanceModal.tsx` | ✅ | Ported in Task 31 (LeaveTab dep) — verbatim admin balance adjust (POST adjust → manual_adjustment ledger); token inputs |
| 46 | Request Leave Modal | `pages/staff/leave/RequestLeaveModal.tsx` | ✅ | Ported in Task 31 (LeaveTab dep) — verbatim auto-hours calc, bereavement/partial-day/confidential/doctor-note branches, 422 error mapping |

### Staff Schedule Modals (2)

| # | Modal | Source File | Status | Notes |
|---|-------|-------------|--------|-------|
| 47 | Copy Week Confirm | `pages/staff-schedule/components/CopyWeekConfirmModal.tsx` | ✅ | Ported in Task 32 (RosterGridPage dep) — verbatim + token restyle |
| 48 | Leave Overlap Confirmation | `pages/staff-schedule/components/LeaveOverlapConfirmationModal.tsx` | ✅ | Ported in Task 32 (RosterGridPage dep) — verbatim + token restyle |

---

## FINAL TOTALS

| Category | Count |
|----------|-------|
| **Pages (all screen-level files)** | 294 |
| **Modals / Popups / Drawers** | 48 |
| **GRAND TOTAL** | **342** |

---

## Workflow

1. Pick a page from the tracker
2. Find the design reference: `OraInvoice_Handoff/app/<PageName>.html`
3. Read the original source: `frontend/src/pages/<module>/<Page>.tsx`
4. Extract all logic (state, effects, handlers, API calls, calculations, gates)
5. Create the redesigned version in `frontend-v2/src/pages/<module>/<Page>.tsx`
6. Apply the new design from the HTML reference while keeping all logic intact
7. Mark the item as ✅ in this tracker
8. Repeat until all 342 items are done
9. Final cutover: archive `frontend/`, rename `frontend-v2/` → `frontend/`

---

## Design Reference Mapping

| Design HTML | Maps to |
|-------------|---------|
| `OraInvoice_Handoff/app/Dashboard.html` | Dashboard pages |
| `OraInvoice_Handoff/app/Invoices.html` | InvoiceList |
| `OraInvoice_Handoff/app/InvoiceCreate.html` | InvoiceCreate |
| `OraInvoice_Handoff/app/InvoiceDetail.html` | InvoiceDetail |
| `OraInvoice_Handoff/app/Quotes.html` | QuoteList + QuoteCreate + QuoteDetail |
| `OraInvoice_Handoff/app/Customers.html` | CustomerList |
| `OraInvoice_Handoff/app/CustomerDetail.html` | CustomerProfile |
| `OraInvoice_Handoff/app/Jobs.html` | JobList + JobBoard |
| `OraInvoice_Handoff/app/JobDetail.html` | JobDetail |
| `OraInvoice_Handoff/app/Staff.html` | StaffList |
| `OraInvoice_Handoff/app/StaffDetail.html` | StaffDetail + tabs |
| `OraInvoice_Handoff/app/StaffSchedule.html` | RosterGridPage |
| `OraInvoice_Handoff/app/Settings.html` | All settings pages |
| `OraInvoice_Handoff/app/Admin*.html` | All admin pages (24 screens) |
| `OraInvoice_Handoff/app/Login.html` | Login |
| `OraInvoice_Handoff/app/Signup.html` | Signup + wizard steps |
| `OraInvoice_Handoff/app/Kiosk.html` | All kiosk pages |
| `OraInvoice_Handoff/app/Portal.html` | All portal pages |
| `OraInvoice_Handoff/app/POS.html` | POS pages |
| `OraInvoice_Handoff/app/fleet/*.html` | Fleet portal pages (22 screens) |
| `OraInvoice_Handoff/app/ds.css` | Design system tokens → Tailwind theme |
| `OraInvoice_Handoff/app/shell.js` | OrgLayout component reference |

---

## Notes

- `frontend-v2/` is fully independent — own package.json, vite config, tailwind config
- Logic (hooks, utils, types, API client) is COPIED into frontend-v2, not imported from frontend/
- Calculations (GST, totals, discounts) are copied VERBATIM — never rewritten
- No deployment of `frontend-v2/` until full sign-off
- Steering rules: `.kiro/steering/frontend-redesign.md`
