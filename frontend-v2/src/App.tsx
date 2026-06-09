import { lazy, Suspense, type ReactNode } from 'react'
import { BrowserRouter, Routes, Route, Navigate, Outlet, useParams } from 'react-router-dom'

/* ============================================================
   App.tsx — provider tree + router skeleton (Tasks 4, 15)
   ------------------------------------------------------------
   Task 4 wired the structural backbone (BrowserRouter basename, lazy
   layout shells, single Suspense boundary). Task 15 wraps that backbone in
   the verbatim-copied provider tree + route guards so the shell renders
   against real session / tenant / module / flag / branch state.

   Provider nesting order is copied EXACTLY from frontend/src/App.tsx:
     ErrorBoundary(app)
       └ BrowserRouter
           └ LocaleProvider
               └ PlatformBrandingProvider
                   └ ThemeProvider
                       └ AuthProvider
                           └ TenantProvider
                               └ ModuleProvider
                                   └ FeatureFlagProvider
                                       └ BranchProvider
                                           └ AppRoutes

   The Fleet Portal short-circuit and the AdminLayout / NoIndexRoute /
   ManagedPage / ModuleRoute wrappers from the real App.tsx are intentionally
   NOT brought in here — those belong with the full route table (Task 77).
   This task keeps the skeleton route set, now guarded, so the OrgLayout shell
   renders behind RequireAuth and exercises the real contexts end to end.

   TODO(Task 77): wire the complete route table for every page in
     docs/REDESIGN_TRACKER.md with the correct layout wrapper + guards,
     plus the AdminLayout, NoIndexRoute, ManagedPage and ModuleRoute wrappers.
   ============================================================ */

import { AuthProvider, useAuth } from '@/contexts/AuthContext'
import { TenantProvider, useTenant } from '@/contexts/TenantContext'
import { ModuleProvider } from '@/contexts/ModuleContext'
import { FeatureFlagProvider } from '@/contexts/FeatureFlagContext'
import { BranchProvider } from '@/contexts/BranchContext'
import { LocaleProvider } from '@/contexts/LocaleContext'
import { PlatformBrandingProvider } from '@/contexts/PlatformBrandingContext'
import { ThemeProvider } from '@/contexts/ThemeContext'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { Spinner } from '@/components/ui'
import { ModuleRoute } from '@/components/common/ModuleRoute'

// Layout shells (Tasks 6, 12, 56).
const OrgLayout = lazy(() => import('@/layouts/OrgLayout'))
const AuthLayout = lazy(() => import('@/layouts/AuthLayout'))

// Placeholder page — every route points here until its real page is ported.
// TODO(Tasks 13-72): swap each placeholder for the ported page component.
const PlaceholderPage = lazy(() => import('@/pages/PlaceholderPage'))

// Auth pages (Task 13). Login is a light page; the signup wizard is
// lazy-loaded on its own so @stripe/stripe-js + @stripe/react-stripe-js only
// download when /signup is visited (and an ad-blocked Stripe script can't crash
// the rest of the app) — mirrors the original frontend's LazySignup.
const Login = lazy(() => import('@/pages/auth/Login').then((m) => ({ default: m.Login })))
const SignupWizard = lazy(() =>
  import('@/pages/auth/SignupWizard').then((m) => ({ default: m.SignupWizard })),
)

// Remaining auth pages (Task 14). MfaVerify pulls firebase/* dynamically inside
// the SMS challenge path, so lazy-loading keeps those bundles out of the main
// chunk; the rest are lazy too for per-route code-splitting consistency.
const MfaVerify = lazy(() => import('@/pages/auth/MfaVerify').then((m) => ({ default: m.MfaVerify })))
const PasswordResetRequest = lazy(() =>
  import('@/pages/auth/PasswordResetRequest').then((m) => ({ default: m.PasswordResetRequest })),
)
const PasswordResetComplete = lazy(() =>
  import('@/pages/auth/PasswordResetComplete').then((m) => ({ default: m.PasswordResetComplete })),
)
const VerifyEmail = lazy(() => import('@/pages/auth/VerifyEmail').then((m) => ({ default: m.VerifyEmail })))
const PasskeySetup = lazy(() => import('@/pages/auth/PasskeySetup').then((m) => ({ default: m.PasskeySetup })))

// Dashboard (Task 16) — role-dispatching entry. Lazy-loaded because it
// transitively pulls in recharts (~the chart card), keeping that chunk out of
// the main bundle for unauthenticated visitors (mirrors frontend/src/App.tsx).
const Dashboard = lazy(() => import('@/pages/dashboard').then((m) => ({ default: m.Dashboard })))

// Global-admin dashboard (Task 17) — the platform dashboard the global_admin
// lands on at /admin/dashboard (GuestOnly redirects global admins there).
// Lazy for the same recharts/HA reasons as the org Dashboard. In the original
// frontend the Dashboard dispatcher is mounted at BOTH /admin/dashboard and
// /dashboard and resolves to GlobalAdminDashboard for a global_admin session;
// Task 42 moves it to be the `dashboard` child inside the new /admin
// AdminLayout route (mirroring the original which renders Dashboard there).
const GlobalAdminDashboard = lazy(() =>
  import('@/pages/dashboard').then((m) => ({ default: m.GlobalAdminDashboard })),
)

// Admin Console (Task 42) — the AdminLayout sidebar+topbar shell wrapping the
// global-admin route tree, plus the five admin pages ported in this task.
// Organisations / OrganisationDetail / SubscriptionPlans / TradeFamilies are
// named/default exports; the admin UserManagement is imported as
// AdminUserManagement to avoid clashing with the settings UserManagement.
// The remaining admin pages (feature-flags, analytics, settings, security,
// errors, notifications, branding, migration, live-migration, ha-replication,
// audit-log, reports, integrations, branches, profile, page-editor*) are wired
// to PlaceholderPage until Tasks 43-45 port the real pages. Lazy-loaded for
// per-route code-splitting.
const AdminLayout = lazy(() => import('@/layouts/AdminLayout').then((m) => ({ default: m.AdminLayout })))
const Organisations = lazy(() => import('@/pages/admin/Organisations').then((m) => ({ default: m.Organisations })))
const OrganisationDetail = lazy(() => import('@/pages/admin/OrganisationDetail').then((m) => ({ default: m.OrganisationDetail })))
const AdminUserManagement = lazy(() => import('@/pages/admin/UserManagement').then((m) => ({ default: m.UserManagement })))
const SubscriptionPlans = lazy(() => import('@/pages/admin/SubscriptionPlans').then((m) => ({ default: m.SubscriptionPlans })))
const TradeFamilies = lazy(() => import('@/pages/admin/TradeFamilies'))

// Admin Console — part 2 (Task 43). The six remaining global-admin pages ported
// in this task: Feature Flags, Platform Analytics, Audit Log, Error Log, the
// platform Settings page (imported as AdminSettings to avoid clashing with the
// org settings Settings), and the platform Security page. Lazy-loaded for
// per-route code-splitting, mirroring the original frontend/src/App.tsx admin
// route tree.
const FeatureFlags = lazy(() => import('@/pages/admin/FeatureFlags').then((m) => ({ default: m.FeatureFlags })))
const AnalyticsDashboard = lazy(() => import('@/pages/admin/AnalyticsDashboard').then((m) => ({ default: m.AnalyticsDashboard })))
const AuditLog = lazy(() => import('@/pages/admin/AuditLog').then((m) => ({ default: m.AuditLog })))
const ErrorLog = lazy(() => import('@/pages/admin/ErrorLog').then((m) => ({ default: m.ErrorLog })))
const AdminSettings = lazy(() => import('@/pages/admin/Settings').then((m) => ({ default: m.Settings })))
const AdminSecurityPage = lazy(() => import('@/pages/admin/AdminSecurityPage').then((m) => ({ default: m.AdminSecurityPage })))

// Admin Console — part 3 (Task 44). The remaining global-admin pages ported in
// this task: Platform Branding, Integrations (tabbed: Carjam / Stripe / SMS /
// Email / Calendar Sync / Xero — the SMS/Email/Calendar/Xero pages render as
// tabs inside Integrations, not as standalone routes), Migration Tool, Live
// Migration Tool, HA Replication, Reports (imported as AdminReports to avoid a
// name clash), Notification Manager, Global Branch Overview (branches), and the
// Global Admin Profile. Lazy-loaded for per-route code-splitting, mirroring the
// original frontend/src/App.tsx admin route tree.
const BrandingConfig = lazy(() => import('@/pages/admin/BrandingConfig').then((m) => ({ default: m.BrandingConfig })))
const Integrations = lazy(() => import('@/pages/admin/Integrations').then((m) => ({ default: m.Integrations })))
const MigrationTool = lazy(() => import('@/pages/admin/MigrationTool').then((m) => ({ default: m.MigrationTool })))
const LiveMigrationTool = lazy(() => import('@/pages/admin/LiveMigrationTool').then((m) => ({ default: m.LiveMigrationTool })))
const HAReplication = lazy(() => import('@/pages/admin/HAReplication').then((m) => ({ default: m.HAReplication })))
const AdminReports = lazy(() => import('@/pages/admin/Reports').then((m) => ({ default: m.Reports })))
const NotificationManager = lazy(() => import('@/pages/admin/NotificationManager'))
const GlobalBranchOverview = lazy(() => import('@/pages/admin/GlobalBranchOverview'))
const GlobalAdminProfile = lazy(() => import('@/pages/admin/GlobalAdminProfile').then((m) => ({ default: m.GlobalAdminProfile })))

// Invoices (Tasks 19, 20) — InvoiceList is the split-panel list+detail+create
// page; the original frontend mounts it at /invoices, /invoices/new and
// /invoices/:id. The standalone create/edit form (InvoiceCreate, Task 20) is
// the full ported invoice form (line items, GST/discount/total math, vehicle
// pickers, QR/issue/mark-paid, attachments) mounted at /invoices/:id/edit and
// also rendered inline by InvoiceList for the /invoices/new panel. InvoiceDetail
// (Task 20) is the standalone read-only detail page — the original router sends
// /invoices/:id to the InvoiceList split-panel (NOT to InvoiceDetail), so we
// mirror that exactly here; InvoiceDetail is ported for parity and reachable
// design. Lazy-loaded for per-route code-splitting.
const InvoiceList = lazy(() => import('@/pages/invoices/InvoiceList'))
const InvoiceCreate = lazy(() => import('@/pages/invoices/InvoiceCreate'))
// RecurringInvoices (Task 79 audit) — the standalone invoices/RecurringInvoices
// page (distinct from the routed recurring/RecurringList). The original router
// never routes it (only its test renders it), so a reachable route is added
// here (FR-2b) at /invoices/recurring.
const RecurringInvoices = lazy(() => import('@/pages/invoices/RecurringInvoices'))

// Quotes (Task 21) — like invoices, the original router sends /quotes,
// /quotes/new and /quotes/:id to the split-panel QuoteList; only /quotes/:id/edit
// renders the standalone QuoteCreate form. All quote routes are gated by the
// `quotes` module (ModuleRoute moduleSlug="quotes"). QuoteDetail is the
// standalone detail page the original router does NOT route to (ported for
// parity/reachable design). Lazy-loaded for per-route code-splitting.
const QuoteList = lazy(() => import('@/pages/quotes/QuoteList'))
const QuoteCreate = lazy(() => import('@/pages/quotes/QuoteCreate'))

// Customers (Task 23) — no module gate / no trade-family gate in the original
// router (frontend/src/App.tsx mounts /customers, /customers/new, /customers/:id
// ungated). CustomerList is the paginated list with the Receivables + Unused
// Credits columns (ISSUE-036) + Configure-Reminders modal; CustomerCreate is the
// always-open create modal route; CustomerProfile is the full detail page
// (KPIs, vehicles/invoices/claims tabs, notify/merge/export/delete + reminder
// modals). Lazy-loaded for per-route code-splitting.
const CustomerList = lazy(() => import('@/pages/customers/CustomerList'))
const CustomerCreate = lazy(() => import('@/pages/customers/CustomerCreate'))
const CustomerProfile = lazy(() => import('@/pages/customers/CustomerProfile'))

// Customer sub-pages (Task 24) — FleetAccounts + DiscountRules. The original
// frontend/src/App.tsx does NOT route these (they're reached only via tests /
// the customers API), so reachable routes are added here (FR-2b) under
// /customers/* using static paths that score above the dynamic /customers/:id.
const FleetAccounts = lazy(() => import('@/pages/customers/FleetAccounts'))
const DiscountRules = lazy(() => import('@/pages/customers/DiscountRules'))

// Vehicles (Task 25) — trade-family gated (automotive) AND module-gated
// (`vehicles`), mirroring frontend/src/App.tsx. VehicleList is the paginated
// list (bulk refresh, manual entry, CarJam onboard); VehicleProfile is the
// detail page (expiry indicators, module-gated PpsrCard, customers/odometer/
// service-history tabs). Lazy-loaded for per-route code-splitting.
const VehicleList = lazy(() => import('@/pages/vehicles/VehicleList'))
const VehicleProfile = lazy(() => import('@/pages/vehicles/VehicleProfile'))

// Jobs (Task 26) — module-gated (`jobs`), mirroring frontend/src/App.tsx.
// JobsPage is the active job-card list (live timers, confirm-done, assign/take-
// over); JobBoard is the kanban/hierarchy/resource-timeline board; JobDetail is
// the detail/create page. JobList (alternate filterable list) is built + routed
// at /jobs/list for reachability (FR-2b — the original router doesn't route it).
const JobsPage = lazy(() => import('@/pages/jobs/JobsPage'))
const JobBoard = lazy(() => import('@/pages/jobs/JobBoard'))
const JobList = lazy(() => import('@/pages/jobs/JobList'))
const JobDetail = lazy(() => import('@/pages/jobs/JobDetail'))

// Job Cards (Task 27) — module-gated (`jobs`), mirroring frontend/src/App.tsx:
// /job-cards (list w/ per-row timers + inline assignee), /job-cards/new (create
// w/ customer search, vehicle lookup, service-types, line items, attachments),
// /job-cards/:id (detail w/ status workflow, timer, convert-to-invoice).
const JobCardList = lazy(() => import('@/pages/job-cards/JobCardList'))
const JobCardCreate = lazy(() => import('@/pages/job-cards/JobCardCreate'))
const JobCardDetail = lazy(() => import('@/pages/job-cards/JobCardDetail'))

// Bookings (Task 28) — module-gated (`bookings`), mirroring frontend/src/App.tsx:
// /bookings (BookingCalendarPage). /bookings/list (alternate BookingList) and
// /book/:orgSlug (public BookingPage) are routed for reachability (FR-2b).
const BookingCalendarPage = lazy(() => import('@/pages/bookings/BookingCalendarPage'))
const BookingList = lazy(() => import('@/pages/bookings/BookingList'))
const BookingPage = lazy(() => import('@/pages/bookings/BookingPage'))

// Customer portal pages (Tasks 56-58) — PUBLIC, token-based (no auth). The
// original frontend/src/App.tsx routes PortalPage directly at /portal/:token
// (NOT under a route-level PortalLayout — PortalPage renders its own branded
// header / summary cards / tabbed content / "Powered by OraInvoice" footer).
// PaymentSuccess is the Stripe redirect result page; PortalRecover is the
// "forgot your link?" recovery page; PortalSignedOut is the post-logout
// confirmation. All four are named exports (the `.then(m => …)` form). Lazy-
// loaded for per-route code-splitting (PortalPage pulls in every tab component).
// PaymentPage is NOT routed standalone — it's a component used inside
// PortalPage's InvoiceHistory flow (takes an `invoice` prop + `onBack`, not
// useParams), mirroring the original.
const PortalPage = lazy(() => import('@/pages/portal/PortalPage').then((m) => ({ default: m.PortalPage })))
const PaymentSuccess = lazy(() => import('@/pages/portal/PaymentSuccess').then((m) => ({ default: m.PaymentSuccess })))
const PortalRecover = lazy(() => import('@/pages/portal/PortalRecover').then((m) => ({ default: m.PortalRecover })))
const PortalSignedOut = lazy(() => import('@/pages/portal/PortalSignedOut').then((m) => ({ default: m.PortalSignedOut })))

// Inventory (Task 35) — module-gated (`inventory`), mirroring frontend/src/App.tsx:
// /inventory → InventoryPage (tabbed: Stock Levels / Usage History / Stock Update
// Log / Reorder Alerts / Suppliers). ProductList / ProductDetail / StockMovements
// are ported in this task and routed for reachability (FR-2b; the original router
// only routes /inventory). ProductDetail reads :id (or none for create) so it's
// wrapped by a small route component. Static product paths score above the
// dynamic /inventory/products/:id.
const InventoryPage = lazy(() => import('@/pages/inventory/InventoryPage'))
const ProductList = lazy(() => import('@/pages/inventory/ProductList'))
const ProductDetail = lazy(() => import('@/pages/inventory/ProductDetail'))
const StockMovements = lazy(() => import('@/pages/inventory/StockMovements'))

// Inventory — remaining pages (Task 36). The original frontend/src/App.tsx only
// routes StockTransfers (as `BranchStockTransfers` at /branch-transfers, gated
// by `branch_management`); the rest (StockAdjustment, StockTake, PurchaseOrders,
// CSVImport, PricingRules, CategoryTree) aren't routed there — they're consumed
// only via tests / standalone components — so reachable routes are added here
// (FR-2b) under /inventory/* gated by the `inventory` module. The StockTransfers
// import keeps the original's `BranchStockTransfers` alias + /branch-transfers
// path + `branch_management` gate to mirror frontend/src/App.tsx exactly.
const StockAdjustment = lazy(() => import('@/pages/inventory/StockAdjustment'))
const StockTake = lazy(() => import('@/pages/inventory/StockTake'))
const PurchaseOrders = lazy(() => import('@/pages/inventory/PurchaseOrders'))
const CSVImport = lazy(() => import('@/pages/inventory/CSVImport'))
const PricingRules = lazy(() => import('@/pages/inventory/PricingRules'))
const CategoryTree = lazy(() => import('@/pages/inventory/CategoryTree'))
const BranchStockTransfers = lazy(() => import('@/pages/inventory/StockTransfers'))

// Items (Task 37) — module-gated (`inventory`), mirroring frontend/src/App.tsx
// exactly: /items → ItemsPage (tabbed container: Items catalogue / Labour Rates
// / Service Types for plumbing-gas orgs). The package builder, cost roll-ups and
// service-type editor are ported verbatim. Lazy-loaded for per-route splitting.
const ItemsPage = lazy(() => import('@/pages/items/ItemsPage'))

// Catalogue (Task 38) — module-gated (`inventory`), mirroring frontend/src/App.tsx
// exactly: /catalogue → CataloguePage (tabbed container: Parts / Fluids-Oils for
// automotive-transport orgs; non-automotive orgs see an empty state pointing at
// the Items page). PartsCatalogue, FluidOilForm and the Services-tab page
// (ServiceCatalogue, retained in the barrel for parity though CataloguePage no
// longer renders a Services tab) are ported verbatim. Lazy-loaded for per-route
// code-splitting.
const CataloguePage = lazy(() => import('@/pages/catalogue/CataloguePage'))

// Staff (Task 30) — module-gated (`staff`), mirroring frontend/src/App.tsx:
// /staff (StaffList) + /staff/:id (StaffDetail via StaffDetailRoute). StaffList
// is the paginated list with add/edit modal + delete; StaffDetail is the tabbed
// shell (Overview / Roster / Payslips / Documents) that falls back to the
// legacy single-form view when the `staff_management` module is disabled. The
// static /staff scores above the dynamic /staff/:id.
const StaffList = lazy(() => import('@/pages/staff/StaffList'))
const StaffDetail = lazy(() => import('@/pages/staff/StaffDetail'))

// Staff self-service (Task 31) — mirrors frontend/src/App.tsx exactly:
// /staff/me/clock (SelfServiceClockScreen, gated `staff_management`) and
// /staff/me/payslips (MyPayslipsPage, gated `payroll`). The server enforces
// ownership via the resolved staff_members.user_id relationship; these are
// authenticated org-user routes (not directly linked from the staff list).
const SelfServiceClockScreen = lazy(() => import('@/pages/staff/me/SelfServiceClockScreen'))
const MyPayslipsPage = lazy(() => import('@/pages/staff/me/MyPayslipsPage'))

// Schedule + Staff Schedule + Roster Grid editor (Task 32) — mirrors
// frontend/src/App.tsx exactly:
//   /schedule              → ScheduleCalendar (gated `scheduling`)
//   /staff-schedule/grid   → RosterGridPage  (gated `scheduling`)
//   /staff-schedule        → StaffSchedule   (gated `branch_management`)
// Lazy-loaded for per-route code-splitting (ScheduleCalendar pulls in
// @dnd-kit; RosterGridPage dynamically imports the resize util).
const ScheduleCalendar = lazy(() => import('@/pages/schedule/ScheduleCalendar'))
const RosterGridPage = lazy(() => import('@/pages/staff-schedule/RosterGridPage'))
const StaffSchedule = lazy(() => import('@/pages/scheduling/StaffSchedule'))

// Shift swaps + cover, leave approvals, timesheet (Task 33) — mirrors
// frontend/src/App.tsx exactly:
//   /shift-swaps    → ShiftSwapPage  (gated `staff_management`)
//   /shift-cover    → ShiftCoverPage (gated `staff_management`)
//   /leave/approvals → ApprovalQueue (gated `staff_management`)
//   /time-tracking  → TimeSheet      (gated `time_tracking`)
// Lazy-loaded for per-route code-splitting.
const ShiftSwapPage = lazy(() => import('@/pages/swaps/ShiftSwapPage'))
const ShiftCoverPage = lazy(() => import('@/pages/swaps/ShiftCoverPage'))
const ApprovalQueue = lazy(() => import('@/pages/leave/ApprovalQueue'))
const TimeSheet = lazy(() => import('@/pages/time-tracking/TimeSheet'))

// Staff Timesheets (Phase A3) — module-gated (`timesheets`):
//   /timesheets          → TimesheetsPage (tabbed: Clocked In / Timesheets)
//   /timesheets/settings → TimesheetSettings (org + branch override config)
const TimesheetsPage = lazy(() => import('@/pages/staff-timesheets/TimesheetsPage'))
const TimesheetSettings = lazy(() => import('@/pages/staff-timesheets/TimesheetSettings'))

// Settings (Task 41) — the Settings container composes every settings tab
// (org/branches/users/security/billing/accounting/currency/language/printer/
// invoice-template/webhooks/modules/notifications + the people sub-pages) and
// is mounted at /settings. /settings/online-payments and the two payroll
// people routes (pay-periods, allowance-types) are standalone routes mirroring
// frontend/src/App.tsx exactly. Lazy-loaded for per-route code-splitting.
const Settings = lazy(() => import('@/pages/settings/Settings').then(m => ({ default: m.Settings })))
const OnlinePaymentsSettings = lazy(() => import('@/pages/settings/OnlinePaymentsSettings'))
const PayPeriodsPage = lazy(() => import('@/pages/settings/people/PayPeriodsPage'))
const AllowanceTypesPage = lazy(() => import('@/pages/settings/people/AllowanceTypesPage'))
const ShiftTemplatesSettings = lazy(() => import('@/pages/schedule/ShiftTemplates'))

// Reports (Task 46) — the org Reports hub + financial reports.
//   ReportsPage   → /reports (ungated tabbed container: Revenue / Invoice
//                   Status / Outstanding / Top Services / GST Return / Customer
//                   Statement / Carjam (vehicles-gated) / SMS / Storage / Fleet
//                   (vehicles-gated)). The tab pages are imported directly by
//                   ReportsPage (not lazy here).
//   ReportBuilder → /reports/builder (FR-2b reachability; the original router
//                   does NOT route the builder, so a reachable route is added).
//   ProfitAndLoss / BalanceSheet / AgedReceivables → /reports/* gated by the
//                   `accounting` module, mirroring frontend/src/App.tsx exactly.
// Lazy-loaded for per-route code-splitting.
const ReportsPage = lazy(() => import('@/pages/reports/ReportsPage'))
const ReportBuilder = lazy(() => import('@/pages/reports/ReportBuilder'))
const ProfitAndLoss = lazy(() => import('@/pages/reports/ProfitAndLoss'))
const BalanceSheet = lazy(() => import('@/pages/reports/BalanceSheet'))
const AgedReceivables = lazy(() => import('@/pages/reports/AgedReceivables'))

// Reports (Tasks 47-48) — the remaining org report pages.
//   WageVariancePage → /reports/wage-variance, gated by the `payroll` module
//                      (ModuleRoute moduleSlug="payroll"), mirroring
//                      frontend/src/App.tsx exactly — the ONLY one of these the
//                      original router routes.
//   InventoryReport / JobReport / HospitalityReport / POSReport /
//   ProjectReport / TaxReturnReport / ScheduledReports → NOT routed in the
//                      original (reached only via tests); reachable ungated
//                      /reports/* routes are added here (FR-2b). Each page
//                      handles its own empty/error states. Lazy-loaded for
//                      per-route code-splitting.
const InventoryReport = lazy(() => import('@/pages/reports/InventoryReport'))
const JobReport = lazy(() => import('@/pages/reports/JobReport'))
const HospitalityReport = lazy(() => import('@/pages/reports/HospitalityReport'))
const POSReport = lazy(() => import('@/pages/reports/POSReport'))
const ProjectReport = lazy(() => import('@/pages/reports/ProjectReport'))
const TaxReturnReport = lazy(() => import('@/pages/reports/TaxReturnReport'))
const ScheduledReports = lazy(() => import('@/pages/reports/ScheduledReports'))
const WageVariancePage = lazy(() => import('@/pages/reports/WageVariancePage'))

// Reports — in-hub tab routes (Task 20.1). The rebuilt ReportsPage (Task 19.2)
// is now a landing — it no longer renders the Tabs UI — so the grouped
// ReportLibrary (Task 20.1) deep-links to standalone routes for each in-hub
// tab. Each route renders the existing tab component wrapped in a thin
// ReportTabPage wrapper that adds a "Back to Reports" link + heading. The
// `vehicles`/`sms` modules gate Carjam / Fleet / SMS routes to mirror the
// original ReportsPage's per-tab gating; the rest are ungated.
const ReportTabPage = lazy(() => import('@/pages/reports/ReportTabPage'))
const RevenueSummary = lazy(() => import('@/pages/reports/RevenueSummary'))
const InvoiceStatus = lazy(() => import('@/pages/reports/InvoiceStatus'))
const OutstandingInvoices = lazy(() => import('@/pages/reports/OutstandingInvoices'))
const TopServices = lazy(() => import('@/pages/reports/TopServices'))
const GstReturnSummary = lazy(() => import('@/pages/reports/GstReturnSummary'))
const CustomerStatement = lazy(() => import('@/pages/reports/CustomerStatement'))
const CarjamUsage = lazy(() => import('@/pages/reports/CarjamUsage'))
const SmsUsage = lazy(() => import('@/pages/reports/SmsUsage'))
const StorageUsage = lazy(() => import('@/pages/reports/StorageUsage'))
const FleetReport = lazy(() => import('@/pages/reports/FleetReport'))

// Accounting + Banking + Tax + Expenses (Tasks 49-51) — mirrors
// frontend/src/App.tsx exactly. Expenses is gated by the `expenses` module;
// everything else (Chart of Accounts, Journal Entries + detail, Accounting
// Periods, GST periods + filing detail, Tax Wallets / Position, Bank Accounts /
// Transactions / Reconciliation) is gated by the `accounting` module. The two
// detail pages (JournalEntryDetail, GstFilingDetail) read their `:id` via
// useParams internally, so they're routed directly (no wrapper needed). Lazy-
// loaded for per-route code-splitting.
const ExpenseList = lazy(() => import('@/pages/expenses/ExpenseList'))
const ChartOfAccounts = lazy(() => import('@/pages/accounting/ChartOfAccounts'))
const JournalEntries = lazy(() => import('@/pages/accounting/JournalEntries'))
const JournalEntryDetail = lazy(() => import('@/pages/accounting/JournalEntryDetail'))
const AccountingPeriods = lazy(() => import('@/pages/accounting/AccountingPeriods'))
const GstPeriods = lazy(() => import('@/pages/tax/GstPeriods'))
const GstFilingDetail = lazy(() => import('@/pages/tax/GstFilingDetail'))
const TaxWallets = lazy(() => import('@/pages/tax/TaxWallets'))
const TaxPosition = lazy(() => import('@/pages/tax/TaxPosition'))
const BankAccounts = lazy(() => import('@/pages/banking/BankAccounts'))
const BankTransactions = lazy(() => import('@/pages/banking/BankTransactions'))
const ReconciliationDashboard = lazy(() => import('@/pages/banking/ReconciliationDashboard'))

// Notifications + SMS (Tasks 52, 53) — mirrors frontend/src/App.tsx + its
// ModuleRouter. NotificationsPage (settings hub) + InboxPage (in-app inbox) are
// UNGATED, matching the original org routes (/notifications, /notifications/inbox).
// SmsChat is routed under /sms gated by the `sms` module (the original
// ModuleRouter maps `/sms/*` → SmsChat; SmsChat is a single page with no nested
// routing, so v2 uses `sms` with no splat). WofRegoReminders (a notifications
// sub-section) and SmsUsageSummary (reached elsewhere in the original) aren't
// routed standalone in the original; reachable routes are added here (FR-2b):
// /notifications/wof-rego-reminders and /sms/usage (gated by `sms`). Lazy-loaded
// for per-route code-splitting.
const NotificationsPage = lazy(() => import('@/pages/notifications/NotificationsPage'))
const InboxPage = lazy(() => import('@/pages/notifications/InboxPage'))
const WofRegoReminders = lazy(() => import('@/pages/notifications/WofRegoReminders'))
const SmsChat = lazy(() => import('@/pages/sms/SmsChat'))
const SmsUsageSummary = lazy(() => import('@/pages/sms/SmsUsageSummary'))

// Hospitality / POS pages (Tasks 54, 55) — mirrors frontend/src/App.tsx:
//   /pos        → POSScreen   (gated `pos`)
//   /floor-plan → FloorPlan   (gated `tables`)
//   /kitchen    → KitchenDisplay (gated `kitchen_display`)
// ReservationList is NOT routed standalone in the original (it's reached from
// FloorPlan / embedded); a reachable /reservations route is added here (FR-2b),
// gated by `tables`. OrderPanel / PaymentPanel / ProductGrid / SyncStatus /
// TipPrompt are POSScreen sub-components (not routed). Lazy-loaded for per-route
// code-splitting (POSScreen pulls in the offline-store / sync-manager / barcode
// scanner / receipt-printer modules).
const POSScreen = lazy(() => import('@/pages/pos/POSScreen'))
const FloorPlan = lazy(() => import('@/pages/floor-plan/FloorPlan'))
const KitchenDisplay = lazy(() => import('@/pages/kitchen/KitchenDisplay'))
const ReservationList = lazy(() => import('@/pages/floor-plan/ReservationList'))

// Kiosk (Tasks 59, 60) — standalone full-screen touch UI, mirrors
// frontend/src/App.tsx which routes /kiosk → KioskPage directly under
// RequireAuth + NoIndexRoute (NOT under OrgLayout, NOT under a route-level
// KioskLayout — KioskPage renders its own full-screen branded chrome). The
// multi-step vehicle check-in orchestrator (welcome → rego → vehicle summary →
// check-in form → success + QR popup) is ported verbatim. KioskClockScreen is
// the staff clock-in/out flow — it is NOT composed by KioskPage and NOT routed
// in the original, so a reachable /kiosk/clock route is added here (FR-2b).
const KioskPage = lazy(() => import('@/pages/kiosk/KioskPage'))
const KioskClockScreen = lazy(() => import('@/pages/kiosk/KioskClockScreen').then((m) => ({ default: m.KioskClockScreen })))

// Public marketing pages (Task 61) — lazy-loaded; only needed for
// unauthenticated visitors. Each is wrapped in <ManagedPage>, which
// transparently swaps in published Puck content from the visual page editor
// when present (Requirement 14.4, 14.5) and falls back to the original React
// component otherwise. Mirrors frontend/src/App.tsx exactly.
const LandingPage = lazy(() => import('@/pages/public/LandingPage'))
const PrivacyPage = lazy(() => import('@/pages/public/PrivacyPage'))
const TradesPage = lazy(() => import('@/pages/public/TradesPage'))
const WorkshopPage = lazy(() => import('@/pages/public/WorkshopPage'))

// ManagedPage wrapper (Task 61) — swaps in published Puck content when present,
// otherwise renders the React fallback. Lazy-loaded to keep the resolve-fetch
// logic and its (lazy) Puck dependency out of the initial chunk for routes that
// don't render published content. PERFORMANCE_AUDIT.md §F-H2.
const ManagedPage = lazy(() => import('@/pages/public/ManagedPage').then((m) => ({ default: m.ManagedPage })))

// Public catch-all renderer (Task 62) — resolves slugs against the editor
// backend; renders published Puck content, a redirect, or its own 404.
const PublicPageRenderer = lazy(() =>
  import('@/pages/public/PublicPageRenderer').then((m) => ({ default: m.PublicPageRenderer })),
)

// Invoice payment page (Task 62, public, token-based — lazy to keep Stripe
// bundles out of the main chunk).
const InvoicePaymentPage = lazy(() => import('@/pages/public/InvoicePaymentPage'))

// Public staff roster viewer (Task 62 — token-gated, no auth).
const StaffRosterPublicView = lazy(() => import('@/pages/public/StaffRosterPublicView'))

// QR payment result pages (Task 62 — public, rendered on customer's phone
// after Stripe redirect).
const QrPaymentSuccess = lazy(() => import('@/pages/payments/QrPaymentSuccess'))
const QrPaymentCancel = lazy(() => import('@/pages/payments/QrPaymentCancel'))

// Construction (Task 63) — module-gated, mirroring frontend/src/App.tsx:
//   /progress-claims → ProgressClaimList (gated `progress_claims`)
//   /variations      → VariationList     (gated `variations`)
//   /retentions      → RetentionSummary  (gated `retentions`)
// ProgressClaimForm + VariationForm are NOT routed standalone in the original
// (the lists embed inline create forms), so they aren't lazy-imported here.
const ProgressClaimList = lazy(() => import('@/pages/construction/ProgressClaimList'))
const VariationList = lazy(() => import('@/pages/construction/VariationList'))
const RetentionSummary = lazy(() => import('@/pages/construction/RetentionSummary'))

// Claims (Task 64) — module-gated (`customer_claims`), mirroring
// frontend/src/App.tsx: /claims (ClaimsList), /claims/new (ClaimCreateForm),
// /claims/reports (ClaimsReports), /claims/:id (ClaimDetail, reads :id via
// useParams). Static /claims/new + /claims/reports score above /claims/:id.
const ClaimsList = lazy(() => import('@/pages/claims/ClaimsList'))
const ClaimCreateForm = lazy(() => import('@/pages/claims/ClaimCreateForm'))
const ClaimsReports = lazy(() => import('@/pages/claims/ClaimsReports'))
const ClaimDetail = lazy(() => import('@/pages/claims/ClaimDetail'))

// Compliance (Task 65) — module-gated (`compliance_docs`), mirroring
// frontend/src/App.tsx: /compliance → ComplianceDashboard (composes the
// SummaryCards / DocumentTable / UploadForm / Edit + Delete + Preview modals).
const ComplianceDashboard = lazy(() => import('@/pages/compliance/ComplianceDashboard'))

// Projects (Task 67) — module-gated (`projects`), mirroring frontend/src/App.tsx:
// /projects → ProjectList (filterable list) and /projects/:id →
// ProjectDashboard (via ProjectDashboardRoute, which reads :id and passes it as
// the `projectId` prop — mirroring the original's ProjectDashboardRoute wrapper).
const ProjectList = lazy(() => import('@/pages/projects/ProjectList'))
const ProjectDashboard = lazy(() => import('@/pages/projects/ProjectDashboard'))

// Franchise (Task 66) — module-gated (`franchise`), mirroring frontend/src/App.tsx:
// /franchise → FranchiseDashboard (head-office + franchise aggregate metrics),
// /locations → LocationList, /locations/:id → LocationDetail (via
// LocationDetailRoute, reads :id → `locationId` prop), /stock-transfers →
// StockTransfers, /stock-transfers/:id → TransferDetail (via TransferDetailRoute,
// reads :id → `transferId` prop). The two detail-route wrappers mirror the
// original's LocationDetailRoute / TransferDetailRoute. Lazy-loaded for
// per-route code-splitting.
const FranchiseDashboard = lazy(() => import('@/pages/franchise/FranchiseDashboard'))
const LocationList = lazy(() => import('@/pages/franchise/LocationList'))
const LocationDetail = lazy(() => import('@/pages/franchise/LocationDetail'))
const StockTransfers = lazy(() => import('@/pages/franchise/StockTransfers'))
const TransferDetail = lazy(() => import('@/pages/franchise/TransferDetail'))

// Ecommerce (Task 68) — module-gated (`ecommerce`), mirroring frontend/src/App.tsx:
// /ecommerce → WooCommerceSetup (connection form + sync log). SkuMappings +
// ApiKeys are NOT routed standalone in the original (they're separate ecommerce
// sub-pages reached internally / via tests, not composed as tabs by
// WooCommerceSetup), so reachable routes are added here (FR-2b) at
// /ecommerce/sku-mappings + /ecommerce/api-keys. Static segments score above any
// future dynamic /ecommerce segment.
const WooCommerceSetup = lazy(() => import('@/pages/ecommerce/WooCommerceSetup'))
const SkuMappings = lazy(() => import('@/pages/ecommerce/SkuMappings'))
const ApiKeys = lazy(() => import('@/pages/ecommerce/ApiKeys'))

// Data Import/Export (Task 68) — UNGATED, mirroring frontend/src/App.tsx:
// /data → DataPage (tabbed container: CSV Import / JSON Import / Export).
// DataImport, JsonBulkImport and DataExport are composed as TABS inside DataPage
// (the parent page renders them via the Tabs primitive), so — exactly like the
// original frontend/src/App.tsx — they are NOT routed standalone here. Only the
// DataPage container is lazy-imported + routed.
const DataPage = lazy(() => import('@/pages/data/DataPage'))

// Payroll (Task 69) — module-gated (`payroll`), mirroring frontend/src/App.tsx:
// /payroll/run → PayRunPage (bulk pay-run console) and /payroll/payslips/:id →
// PayslipDetail (imported as PayslipDetailPage to mirror the original's import
// alias; reads :id via useParams internally). Lazy-loaded for per-route
// code-splitting (PayRunPage lazy-loads PayslipDetail for its drawer).
const PayRunPage = lazy(() => import('@/pages/payroll/PayRunPage'))
const PayslipDetailPage = lazy(() => import('@/pages/payroll/PayslipDetail'))

// Recurring invoices (Task 70) — module-gated (`recurring_invoices`), mirroring
// frontend/src/App.tsx: /recurring → RecurringList (schedule management list +
// create dialog).
const RecurringList = lazy(() => import('@/pages/recurring/RecurringList'))

// Purchase Orders (Task 70) — module-gated (`purchase_orders`), mirroring
// frontend/src/App.tsx: /purchase-orders → POList (list + create / add-supplier
// / add-part modals) and /purchase-orders/:id → PODetail (reads :id via
// useParams internally). Lazy-loaded for per-route code-splitting.
const POList = lazy(() => import('@/pages/purchase-orders/POList'))
const PODetail = lazy(() => import('@/pages/purchase-orders/PODetail'))

// PPSR (Task 71) — module-gated (`ppsr`), mirroring frontend/src/App.tsx:
// /ppsr/search → PPSRSearchPage (quota strip + search form + result panel +
// history table). PPSRSearchPage is a named export (the `.then(m => …)` form).
const PPSRSearchPage = lazy(() =>
  import('@/pages/ppsr/PPSRSearchPage').then((m) => ({ default: m.PPSRSearchPage })),
)

// Assets (Task 71) — module-gated (`assets`), mirroring frontend/src/App.tsx:
// /assets → AssetList (list + create modal; self-guards via useModules +
// <Navigate>) and /assets/:id → AssetDetail (takes an `assetId` prop, wrapped by
// AssetDetailRoute below which reads :id — mirrors the original's
// AssetDetailRoute wrapper). Lazy-loaded for per-route code-splitting.
const AssetList = lazy(() => import('@/pages/assets/AssetList'))
const AssetDetail = lazy(() => import('@/pages/assets/AssetDetail'))

// Loyalty (Task 71) — module-gated (`loyalty`), mirroring frontend/src/App.tsx:
// /loyalty → LoyaltyConfig (earn-rate config, tiers, customer balance lookup +
// analytics / points-adjustment tabs).
const LoyaltyConfig = lazy(() => import('@/pages/loyalty/LoyaltyConfig'))

// Onboarding + Setup (Task 72) — UNGATED, mirroring frontend/src/App.tsx:
//   /setup       → SetupWizard (5-step business setup: Business / Branding /
//                  Modules→redirect / Catalogue / Ready; composes StepIndicator
//                  + InvoicePreview + the 7 steps).
//   /setup-guide → SetupGuide (module-enable Q&A flow composing WelcomeScreen /
//                  QuestionCard / SummaryScreen).
//   /onboarding  → OnboardingWizard (6-step workshop onboarding wizard).
// SetupWizard + OnboardingWizard are named exports (the `.then(m => …)` form);
// SetupGuide is a default export. The wizard sub-components (steps, indicators,
// previews, screens, question card) are NOT routed standalone. Lazy-loaded for
// per-route code-splitting.
const SetupWizard = lazy(() => import('@/pages/setup/SetupWizard').then((m) => ({ default: m.SetupWizard })))
const SetupGuide = lazy(() => import('@/pages/setup-guide/SetupGuide'))
const OnboardingWizard = lazy(() => import('@/pages/onboarding/OnboardingWizard').then((m) => ({ default: m.OnboardingWizard })))

/**
 * basename for React Router v7.
 *
 * Vite injects import.meta.env.BASE_URL from `base: '/new/'` in
 * vite.config.ts. React Router expects a basename WITHOUT a trailing slash
 * (except the root case "/"), so strip a single trailing slash here. This
 * keeps every route resolving under /new/ without the dev server and the
 * router disagreeing about the prefix.
 */
function getBasename(): string {
  const base = import.meta.env.BASE_URL || '/'
  if (base === '/') return '/'
  return base.endsWith('/') ? base.slice(0, -1) : base
}

/** Minimal Suspense fallback while a lazy chunk loads. */
function SuspenseFallback() {
  return (
    <div className="flex min-h-screen items-center justify-center" role="status" aria-live="polite">
      <Spinner size="lg" label="Loading page" />
    </div>
  )
}

/** Wrap a lazy page element in the shared Suspense boundary. */
function Lazy({ children }: { children: ReactNode }) {
  return <Suspense fallback={<SuspenseFallback />}>{children}</Suspense>
}

/* ── Route guards — copied from frontend/src/App.tsx (logic unchanged) ── */

/** Gate authenticated areas; redirect to /login when no session. */
function RequireAuth() {
  const { isAuthenticated, isLoading } = useAuth()
  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner size="lg" label="Loading session" />
      </div>
    )
  }
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return <Outlet />
}

/** Guest-only areas (login etc.); redirect authenticated users by role. */
function GuestOnly() {
  const { isAuthenticated, isLoading, isGlobalAdmin, isKiosk } = useAuth()
  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner size="lg" label="Loading session" />
      </div>
    )
  }
  if (isAuthenticated) {
    if (isKiosk) return <Navigate to="/kiosk" replace />
    return <Navigate to={isGlobalAdmin ? '/admin/dashboard' : '/dashboard'} replace />
  }
  return (
    <div className="h-full overflow-y-auto">
      <Outlet />
    </div>
  )
}

/** global_admin-only areas (Admin Console). */
function RequireGlobalAdmin() {
  const { isGlobalAdmin, isLoading } = useAuth()
  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner size="lg" label="Loading session" />
      </div>
    )
  }
  if (!isGlobalAdmin) return <Navigate to="/dashboard" replace />
  return <Outlet />
}

/** Redirect branch_admin users away from org-level settings to /dashboard. */
function RequireOrgAdmin() {
  const { isBranchAdmin } = useAuth()
  if (isBranchAdmin) return <Navigate to="/dashboard" replace />
  return <Outlet />
}

/** Trade-family gate — automotive-only routes (null treated as automotive). */
function RequireAutomotive() {
  const { tradeFamily } = useTenant()
  const isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'
  if (!isAutomotive) return <Navigate to="/dashboard" replace />
  return <Outlet />
}

/**
 * JobDetailRoute — reads the :id route param and passes it to JobDetail as the
 * `jobId` prop (mirrors frontend/src/App.tsx's JobDetailRoute wrapper).
 */
function JobDetailRoute() {
  const { id } = useParams<{ id: string }>()
  return <JobDetail jobId={id!} />
}

/**
 * BookingPageRoute — reads the :orgSlug route param and passes it to the public
 * BookingPage. The original frontend doesn't route BookingPage; added here for
 * reachability (FR-2b) as a public (no-auth) page.
 */
function BookingPageRoute() {
  const { orgSlug } = useParams<{ orgSlug: string }>()
  return <BookingPage orgSlug={orgSlug!} />
}

/**
 * StaffDetailRoute — reads the :id route param and passes it to StaffDetail as
 * the `staffId` prop (mirrors frontend/src/App.tsx's StaffDetailRoute wrapper).
 */
function StaffDetailRoute() {
  const { id } = useParams<{ id: string }>()
  return <StaffDetail staffId={id!} />
}

/**
 * ProductDetailRoute — reads the optional :id route param and passes it to
 * ProductDetail as the `productId` prop (undefined for the /inventory/products/new
 * create route). Mirrors the original ProductDetail's `{ productId }` prop API.
 */
function ProductDetailRoute() {
  const { id } = useParams<{ id: string }>()
  return <ProductDetail productId={id} />
}

/**
 * ProjectDashboardRoute — reads the :id route param and passes it to
 * ProjectDashboard as the `projectId` prop (mirrors frontend/src/App.tsx's
 * ProjectDashboardRoute wrapper).
 */
function ProjectDashboardRoute() {
  const { id } = useParams<{ id: string }>()
  return <ProjectDashboard projectId={id!} />
}

/**
 * LocationDetailRoute — reads the :id route param and passes it to
 * LocationDetail as the `locationId` prop (mirrors frontend/src/App.tsx's
 * LocationDetailRoute wrapper).
 */
function LocationDetailRoute() {
  const { id } = useParams<{ id: string }>()
  return <LocationDetail locationId={id!} />
}

/**
 * TransferDetailRoute — reads the :id route param and passes it to
 * TransferDetail as the `transferId` prop (mirrors frontend/src/App.tsx's
 * TransferDetailRoute wrapper).
 */
function TransferDetailRoute() {
  const { id } = useParams<{ id: string }>()
  return <TransferDetail transferId={id!} />
}

/**
 * AssetDetailRoute — reads the :id route param and passes it to AssetDetail as
 * the `assetId` prop (mirrors frontend/src/App.tsx's AssetDetailRoute wrapper).
 */
function AssetDetailRoute() {
  const { id } = useParams<{ id: string }>()
  return <AssetDetail assetId={id!} />
}

function AppRoutes() {
  return (
    <Routes>
      {/* Public marketing pages (Task 61) — accessible regardless of auth
          state. Each hand-coded page is wrapped in <ManagedPage>, which
          transparently swaps in published Puck content from the visual page
          editor when present (Requirement 14.4, 14.5) and falls back to the
          original React component otherwise. Mirrors frontend/src/App.tsx
          exactly: /privacy, /trades and /workshop are PUBLIC (not GuestOnly);
          the landing `/` route is GuestOnly (declared in the GuestOnly block
          below). */}
      <Route path="/privacy" element={<ManagedPage page_key="privacy"><PrivacyPage /></ManagedPage>} />
      <Route path="/trades" element={<ManagedPage page_key="trades"><TradesPage /></ManagedPage>} />
      <Route path="/workshop" element={<ManagedPage page_key="workshop"><WorkshopPage /></ManagedPage>} />
      {/* SEO: /mechanics and /garage are alias routes that redirect to the
          canonical /workshop URL. This consolidates link-equity to a single
          URL (plus the <link rel="canonical"> on WorkshopPage itself). */}
      <Route path="/mechanics" element={<Navigate to="/workshop" replace />} />
      <Route path="/garage" element={<Navigate to="/workshop" replace />} />

      {/* Guest routes — authenticated users are redirected by role.
          Auth pages use the AuthLayout split-screen shell.
          Tasks 13–14: Login, Signup wizard, MFA verify, password reset
          (request + complete), and email verification — paths mirror the
          original frontend/src/App.tsx GuestOnly auth routes exactly. */}
      <Route element={<GuestOnly />}>
        {/* Landing page (Task 61) — the public `/` route. GuestOnly redirects
            authenticated users by role (kiosk → /kiosk, global admin →
            /admin/dashboard, others → /dashboard); unauthenticated visitors see
            the LandingPage. Mirrors frontend/src/App.tsx, which places `/` under
            GuestOnly wrapped in <ManagedPage page_key="landing">. Declared as a
            GuestOnly route OUTSIDE AuthLayout (its own element). */}
        <Route path="/" element={<ManagedPage page_key="landing"><LandingPage /></ManagedPage>} />
        <Route element={<AuthLayout />}>
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<SignupWizard />} />
          <Route path="/mfa-verify" element={<MfaVerify />} />
          <Route path="/forgot-password" element={<PasswordResetRequest />} />
          <Route path="/reset-password" element={<PasswordResetComplete />} />
          <Route path="/verify-email" element={<VerifyEmail />} />
        </Route>
      </Route>

      {/* Customer portal (public, token-based access) — PortalPage is a
          self-contained page (it renders its own branded header / summary
          cards / tabbed content / "Powered by OraInvoice" footer), so it's
          routed directly here as a top-level public route (NOT under
          RequireAuth, NOT under OrgLayout / PortalLayout) — mirroring
          frontend/src/App.tsx. The static /portal/signed-out + /portal/recover
          paths are declared BEFORE the dynamic /portal/:token so they win the
          match (React Router v7 score-based matching already favours static
          segments; declared first for clarity). */}
      <Route path="/portal/signed-out" element={<PortalSignedOut />} />
      <Route path="/portal/recover" element={<PortalRecover />} />
      <Route path="/portal/:token/payment-success" element={<PaymentSuccess />} />
      <Route path="/portal/:token" element={<PortalPage />} />

      {/* Public booking page (Task 28) — no auth; org-branded slot picker.
          Not in the original router; added for reachability (FR-2b). */}
      <Route path="/book/:orgSlug" element={<BookingPageRoute />} />

      {/* Public token pages (Task 62) — top-level, no auth (like /portal),
          mirroring frontend/src/App.tsx. The invoice payment page (Stripe
          Elements), the public staff roster viewer (token-gated), and the two
          QR payment result pages rendered on the customer's phone after a
          Stripe redirect. */}
      <Route path="/pay/:token" element={<InvoicePaymentPage />} />
      <Route path="/public/staff-roster/:token" element={<StaffRosterPublicView />} />
      <Route path="/payments/qr-success" element={<QrPaymentSuccess />} />
      <Route path="/payments/qr-cancel" element={<QrPaymentCancel />} />

      {/* Authenticated areas — gated by RequireAuth (real session state). */}
      <Route element={<RequireAuth />}>
        {/* Passkey enrolment — authenticated post-login setup page rendered in
            the AuthLayout split-screen shell. The original frontend doesn't
            expose a route for it (it's reached programmatically), so /passkey-
            setup is added here (FR-2b) so the ported page is reachable. */}
        <Route element={<AuthLayout />}>
          <Route path="/passkey-setup" element={<PasskeySetup />} />
        </Route>

        {/* Kiosk (standalone, outside OrgLayout) — KioskPage renders its own
            full-screen, touch-optimized branded chrome (welcome → rego →
            vehicle summary → check-in form → success + QR popup). Mirrors
            frontend/src/App.tsx which routes /kiosk → KioskPage directly under
            RequireAuth (the original also wraps it in NoIndexRoute; v2 has no
            NoIndexRoute wrapper yet, so the route sits directly under
            RequireAuth here). /kiosk/clock → KioskClockScreen is the staff
            clock-in/out flow, NOT composed by KioskPage and NOT routed in the
            original — added here for reachability (FR-2b). The static
            /kiosk/clock scores above any future dynamic /kiosk segment. */}
        <Route path="/kiosk" element={<KioskPage />} />
        <Route
          path="/kiosk/clock"
          element={
            <div className="flex min-h-screen flex-col items-center justify-center bg-canvas px-4">
              <KioskClockScreen />
            </div>
          }
        />

        {/* Global admin — RequireGlobalAdmin. The global_admin lands here
            (GuestOnly redirect → /admin/dashboard). Task 42 wires the full
            Admin Console under AdminLayout: the five pages ported in this task
            render real components; the remaining admin pages point at
            PlaceholderPage until Tasks 43-45 port them. The AdminLayout nav
            links to every child path below, so all routes are reachable. The
            relative child paths mirror frontend/src/App.tsx's `path="/admin"`
            block exactly. GlobalAdminDashboard (Task 17) is mounted as the
            `dashboard` child here, mirroring the original which renders the
            Dashboard dispatcher there. */}
        <Route element={<RequireGlobalAdmin />}>
          <Route path="/admin" element={<AdminLayout />}>
            {/* Core — Dashboard (real), Organisations (real), Branches
                (placeholder), Users (real admin UserManagement). */}
            <Route path="dashboard" element={<GlobalAdminDashboard />} />
            <Route path="organisations/:orgId" element={<OrganisationDetail />} />
            <Route path="organisations" element={<Organisations />} />
            <Route path="branches" element={<GlobalBranchOverview />} />
            <Route path="users" element={<AdminUserManagement />} />

            {/* Configuration — Subscription Management (real), Trade Families
                (real); the rest are placeholders until Tasks 43-45. */}
            <Route path="plans" element={<SubscriptionPlans />} />
            <Route path="trade-families" element={<TradeFamilies />} />
            <Route path="feature-flags" element={<FeatureFlags />} />
            <Route path="branding" element={<BrandingConfig />} />
            <Route path="integrations" element={<Integrations />} />
            <Route path="settings" element={<AdminSettings />} />
            <Route path="security" element={<AdminSecurityPage />} />

            {/* Content — Page Editor + Redirects (no ported pages yet). */}
            <Route path="page-editor/redirects" element={<PlaceholderPage title="Redirects" />} />
            <Route path="page-editor" element={<PlaceholderPage title="Page Editor" />} />

            {/* Monitoring */}
            <Route path="analytics" element={<AnalyticsDashboard />} />
            <Route path="reports" element={<AdminReports />} />
            <Route path="audit-log" element={<AuditLog />} />
            <Route path="errors" element={<ErrorLog />} />
            <Route path="notifications" element={<NotificationManager />} />

            {/* Tools */}
            <Route path="migration" element={<MigrationTool />} />
            <Route path="live-migration" element={<LiveMigrationTool />} />
            <Route path="ha-replication" element={<HAReplication />} />

            {/* Profile — reached from the AdminLayout user menu. */}
            <Route path="profile" element={<GlobalAdminProfile />} />

            {/* Index — redirect /admin to the dashboard. */}
            <Route index element={<Navigate to="dashboard" replace />} />
          </Route>
        </Route>

        {/* Authenticated org app — OrgLayout sidebar + topbar shell.
            TODO(Task 77): full org route table (invoices, quotes, customers, …). */}
        <Route path="/" element={<OrgLayout />}>
          {/* No `/` index here — the public landing owns `/` under GuestOnly
              (Task 61), which redirects authenticated users to /dashboard
              (or /admin/dashboard / /kiosk by role), mirroring the original
              frontend/src/App.tsx where OrgLayout is a pathless layout and `/`
              is a GuestOnly route. */}
          {/* Dashboard (Task 16) — role-dispatching entry rendering the ported
              prototype layout (KPI row, revenue chart, recent invoices,
              activity, upcoming bookings) for org users. The role-variant
              dispatch (GlobalAdmin/OrgAdmin/Salesperson) is deferred to Task 17;
              global_admin sessions are sent to /admin/dashboard by GuestOnly. */}
          <Route path="dashboard" element={<Dashboard />} />

          {/* Invoices (Tasks 19, 20) — no module gate in the original router.
              The split-panel InvoiceList serves the list, detail (/invoices/:id)
              and create (/invoices/new) panels; /invoices/:id/edit renders the
              full standalone InvoiceCreate form (Task 20). Paths mirror
              frontend/src/App.tsx exactly (which also routes /invoices/:id to
              the InvoiceList split-panel, not the standalone InvoiceDetail). */}
          <Route path="invoices" element={<InvoiceList />} />
          <Route path="invoices/new" element={<InvoiceList />} />
          <Route path="invoices/recurring" element={<RecurringInvoices />} />
          <Route path="invoices/:id/edit" element={<InvoiceCreate />} />
          <Route path="invoices/:id" element={<InvoiceList />} />

          {/* Quotes (Task 21) — gated by the `quotes` module (ModuleRoute).
              Mirrors frontend/src/App.tsx exactly: the split-panel QuoteList
              serves /quotes, /quotes/new and /quotes/:id; /quotes/:id/edit
              renders the standalone QuoteCreate form. */}
          <Route
            path="quotes"
            element={<ModuleRoute moduleSlug="quotes"><QuoteList /></ModuleRoute>}
          />
          <Route
            path="quotes/new"
            element={<ModuleRoute moduleSlug="quotes"><QuoteList /></ModuleRoute>}
          />
          <Route
            path="quotes/:id/edit"
            element={<ModuleRoute moduleSlug="quotes"><QuoteCreate /></ModuleRoute>}
          />
          <Route
            path="quotes/:id"
            element={<ModuleRoute moduleSlug="quotes"><QuoteList /></ModuleRoute>}
          />

          {/* Customers (Task 23) — ungated in the original router. Mirrors
              frontend/src/App.tsx exactly: /customers (list), /customers/new
              (create modal route), /customers/:id (profile). */}
          <Route path="customers" element={<CustomerList />} />
          <Route path="customers/new" element={<CustomerCreate />} />
          {/* Customer sub-pages (Task 24) — static paths declared BEFORE the
              dynamic /customers/:id. React Router v7 score-based matching ranks
              static segments above dynamic, so order is not strictly required,
              but keeping them first documents the intent. Not in the original
              router (FR-2b reachability). */}
          <Route path="customers/fleet-accounts" element={<FleetAccounts />} />
          <Route path="customers/discount-rules" element={<DiscountRules />} />
          <Route path="customers/:id" element={<CustomerProfile />} />

          {/* Vehicles — trade-family gated (automotive only) AND module-gated
              (`vehicles`), mirroring frontend/src/App.tsx exactly. VehicleList
              (list) + VehicleProfile (/vehicles/:id detail). */}
          <Route element={<RequireAutomotive />}>
            <Route
              path="vehicles"
              element={<ModuleRoute moduleSlug="vehicles"><VehicleList /></ModuleRoute>}
            />
            <Route
              path="vehicles/:id"
              element={<ModuleRoute moduleSlug="vehicles"><VehicleProfile /></ModuleRoute>}
            />
          </Route>

          {/* PPSR (Task 71) — module-gated (`ppsr`), mirroring
              frontend/src/App.tsx exactly: /ppsr/search → PPSRSearchPage. The
              original routes this OUTSIDE the RequireAutomotive gate (PPSR is
              available to any trade family with the module), so v2 declares it
              here at the OrgLayout level, not nested under RequireAutomotive. */}
          <Route
            path="ppsr/search"
            element={<ModuleRoute moduleSlug="ppsr"><PPSRSearchPage /></ModuleRoute>}
          />

          {/* Jobs (Task 26) — module-gated (`jobs`), mirroring frontend/src/App.tsx:
              /jobs (JobsPage), /jobs/board (JobBoard), /jobs/:id (JobDetail via
              JobDetailRoute). /jobs/list is the alternate filterable JobList,
              routed for reachability (FR-2b; not in the original router). The
              static /jobs/board + /jobs/list score above the dynamic /jobs/:id. */}
          <Route
            path="jobs"
            element={<ModuleRoute moduleSlug="jobs"><JobsPage /></ModuleRoute>}
          />
          <Route
            path="jobs/board"
            element={<ModuleRoute moduleSlug="jobs"><JobBoard /></ModuleRoute>}
          />
          <Route
            path="jobs/list"
            element={<ModuleRoute moduleSlug="jobs"><JobList /></ModuleRoute>}
          />
          <Route
            path="jobs/:id"
            element={<ModuleRoute moduleSlug="jobs"><JobDetailRoute /></ModuleRoute>}
          />

          {/* Job Cards (Task 27) — module-gated (`jobs`), mirroring
              frontend/src/App.tsx: /job-cards (list), /job-cards/new (create),
              /job-cards/:id (detail). Static /job-cards/new scores above the
              dynamic /job-cards/:id. */}
          <Route
            path="job-cards"
            element={<ModuleRoute moduleSlug="jobs"><JobCardList /></ModuleRoute>}
          />
          <Route
            path="job-cards/new"
            element={<ModuleRoute moduleSlug="jobs"><JobCardCreate /></ModuleRoute>}
          />
          <Route
            path="job-cards/:id"
            element={<ModuleRoute moduleSlug="jobs"><JobCardDetail /></ModuleRoute>}
          />

          {/* Bookings (Task 28) — module-gated (`bookings`), mirroring
              frontend/src/App.tsx: /bookings (BookingCalendarPage). /bookings/list
              is the alternate paginated BookingList, routed for reachability
              (FR-2b; not in the original router). */}
          <Route
            path="bookings"
            element={<ModuleRoute moduleSlug="bookings"><BookingCalendarPage /></ModuleRoute>}
          />
          <Route
            path="bookings/list"
            element={<ModuleRoute moduleSlug="bookings"><BookingList /></ModuleRoute>}
          />

          {/* Inventory (Task 35) — module-gated (`inventory`), mirroring
              frontend/src/App.tsx: /inventory (InventoryPage tabbed container).
              ProductList / ProductDetail / StockMovements are ported in this
              task and routed for reachability (FR-2b; the original router only
              routes /inventory). Static /inventory/products + /inventory/products/new
              + /inventory/movements score above the dynamic
              /inventory/products/:id. */}
          <Route
            path="inventory"
            element={<ModuleRoute moduleSlug="inventory"><InventoryPage /></ModuleRoute>}
          />
          <Route
            path="inventory/products"
            element={<ModuleRoute moduleSlug="inventory"><ProductList /></ModuleRoute>}
          />
          <Route
            path="inventory/products/new"
            element={<ModuleRoute moduleSlug="inventory"><ProductDetailRoute /></ModuleRoute>}
          />
          <Route
            path="inventory/products/:id"
            element={<ModuleRoute moduleSlug="inventory"><ProductDetailRoute /></ModuleRoute>}
          />
          <Route
            path="inventory/movements"
            element={<ModuleRoute moduleSlug="inventory"><StockMovements /></ModuleRoute>}
          />

          {/* Inventory — remaining pages (Task 36). StockTransfers mirrors
              frontend/src/App.tsx exactly (the `BranchStockTransfers` alias at
              /branch-transfers, gated by `branch_management`; the page itself
              also self-guards via useModules + <Navigate>). The original router
              does NOT route StockAdjustment / StockTake / PurchaseOrders /
              CSVImport / PricingRules / CategoryTree (they're consumed via tests
              / standalone components), so reachable routes are added here (FR-2b)
              under /inventory/* gated by the `inventory` module. Static segments
              score above the dynamic /inventory/products/:id. */}
          <Route
            path="inventory/adjustment"
            element={<ModuleRoute moduleSlug="inventory"><StockAdjustment /></ModuleRoute>}
          />
          <Route
            path="inventory/stocktake"
            element={<ModuleRoute moduleSlug="inventory"><StockTake /></ModuleRoute>}
          />
          <Route
            path="inventory/purchase-orders"
            element={<ModuleRoute moduleSlug="inventory"><PurchaseOrders /></ModuleRoute>}
          />
          <Route
            path="inventory/csv-import"
            element={<ModuleRoute moduleSlug="inventory"><CSVImport /></ModuleRoute>}
          />
          <Route
            path="inventory/pricing-rules"
            element={<ModuleRoute moduleSlug="inventory"><PricingRules /></ModuleRoute>}
          />
          <Route
            path="inventory/categories"
            element={<ModuleRoute moduleSlug="inventory"><CategoryTree /></ModuleRoute>}
          />

          {/* Branch Stock Transfers (Task 36) — mirrors frontend/src/App.tsx
              exactly: /branch-transfers gated by the `branch_management` module
              (the original imports the inventory StockTransfers page under the
              `BranchStockTransfers` alias). */}
          <Route
            path="branch-transfers"
            element={<ModuleRoute moduleSlug="branch_management"><BranchStockTransfers /></ModuleRoute>}
          />

          {/* Items (Task 37) — module-gated (`inventory`), mirroring
              frontend/src/App.tsx exactly: /items → ItemsPage (tabbed container
              with Items catalogue / Labour Rates / Service Types). */}
          <Route
            path="items"
            element={<ModuleRoute moduleSlug="inventory"><ItemsPage /></ModuleRoute>}
          />

          {/* Catalogue (Task 38) — module-gated (`inventory`), mirroring
              frontend/src/App.tsx exactly: /catalogue → CataloguePage (tabbed
              Parts / Fluids-Oils container, automotive trade-family gated within
              the page itself). */}
          <Route
            path="catalogue"
            element={<ModuleRoute moduleSlug="inventory"><CataloguePage /></ModuleRoute>}
          />

          {/* Onboarding + Setup (Task 72) — UNGATED, mirroring
              frontend/src/App.tsx exactly: /setup → SetupWizard, /setup-guide →
              SetupGuide, /onboarding → OnboardingWizard. The wizard
              sub-components (7 setup steps + StepIndicator + InvoicePreview +
              WelcomeScreen / SummaryScreen / QuestionCard) are composed inside
              the wizards, NOT routed standalone. v2 uses relative child paths
              under the OrgLayout `path="/"` parent. */}
          <Route path="setup" element={<SetupWizard />} />
          <Route path="setup-guide" element={<SetupGuide />} />
          <Route path="onboarding" element={<OnboardingWizard />} />

          {/* Construction (Task 63) — module-gated, mirroring
              frontend/src/App.tsx exactly: /progress-claims (ProgressClaimList,
              gated `progress_claims`), /variations (VariationList, gated
              `variations`), /retentions (RetentionSummary, gated `retentions`).
              ProgressClaimForm + VariationForm are NOT routed standalone in the
              original — the lists embed inline create forms, so no /new routes
              are added. v2 uses relative child paths under the OrgLayout
              `path="/"` parent. */}
          <Route
            path="progress-claims"
            element={<ModuleRoute moduleSlug="progress_claims"><ProgressClaimList /></ModuleRoute>}
          />
          <Route
            path="variations"
            element={<ModuleRoute moduleSlug="variations"><VariationList /></ModuleRoute>}
          />
          <Route
            path="retentions"
            element={<ModuleRoute moduleSlug="retentions"><RetentionSummary /></ModuleRoute>}
          />

          {/* Claims (Task 64) — module-gated (`customer_claims`), mirroring
              frontend/src/App.tsx exactly: /claims (ClaimsList), /claims/new
              (ClaimCreateForm), /claims/reports (ClaimsReports), /claims/:id
              (ClaimDetail, reads :id via useParams). The static /claims/new +
              /claims/reports score above the dynamic /claims/:id. v2 uses
              relative child paths under the OrgLayout `path="/"` parent. */}
          <Route
            path="claims"
            element={<ModuleRoute moduleSlug="customer_claims"><ClaimsList /></ModuleRoute>}
          />
          <Route
            path="claims/new"
            element={<ModuleRoute moduleSlug="customer_claims"><ClaimCreateForm /></ModuleRoute>}
          />
          <Route
            path="claims/reports"
            element={<ModuleRoute moduleSlug="customer_claims"><ClaimsReports /></ModuleRoute>}
          />
          <Route
            path="claims/:id"
            element={<ModuleRoute moduleSlug="customer_claims"><ClaimDetail /></ModuleRoute>}
          />

          {/* Compliance (Task 65) — module-gated (`compliance_docs`), mirroring
              frontend/src/App.tsx exactly: /compliance → ComplianceDashboard
              (the main page composing SummaryCards / DocumentTable / UploadForm
              + Edit / Delete / Preview modals). v2 uses a relative child path
              under the OrgLayout `path="/"` parent. */}
          <Route
            path="compliance"
            element={<ModuleRoute moduleSlug="compliance_docs"><ComplianceDashboard /></ModuleRoute>}
          />

          {/* Projects (Task 67) — module-gated (`projects`), mirroring
              frontend/src/App.tsx exactly: /projects (ProjectList) + /projects/:id
              (ProjectDashboard via ProjectDashboardRoute, which reads :id and
              passes it as the `projectId` prop). v2 uses relative child paths
              under the OrgLayout `path="/"` parent. */}
          <Route
            path="projects"
            element={<ModuleRoute moduleSlug="projects"><ProjectList /></ModuleRoute>}
          />
          <Route
            path="projects/:id"
            element={<ModuleRoute moduleSlug="projects"><ProjectDashboardRoute /></ModuleRoute>}
          />

          {/* Franchise (Task 66) — module-gated (`franchise`), mirroring
              frontend/src/App.tsx exactly: /franchise (FranchiseDashboard),
              /locations (LocationList), /locations/:id (LocationDetail via
              LocationDetailRoute → `locationId` prop), /stock-transfers
              (StockTransfers), /stock-transfers/:id (TransferDetail via
              TransferDetailRoute → `transferId` prop). The static /locations +
              /stock-transfers score above their dynamic /:id siblings. v2 uses
              relative child paths under the OrgLayout `path="/"` parent. */}
          <Route
            path="franchise"
            element={<ModuleRoute moduleSlug="franchise"><FranchiseDashboard /></ModuleRoute>}
          />
          <Route
            path="locations"
            element={<ModuleRoute moduleSlug="franchise"><LocationList /></ModuleRoute>}
          />
          <Route
            path="locations/:id"
            element={<ModuleRoute moduleSlug="franchise"><LocationDetailRoute /></ModuleRoute>}
          />
          <Route
            path="stock-transfers"
            element={<ModuleRoute moduleSlug="franchise"><StockTransfers /></ModuleRoute>}
          />
          <Route
            path="stock-transfers/:id"
            element={<ModuleRoute moduleSlug="franchise"><TransferDetailRoute /></ModuleRoute>}
          />

          {/* Ecommerce (Task 68) — module-gated (`ecommerce`), mirroring
              frontend/src/App.tsx exactly: /ecommerce → WooCommerceSetup
              (connection form + sync log). SkuMappings + ApiKeys are NOT routed
              standalone in the original and WooCommerceSetup does NOT compose
              them as tabs — they're separate ecommerce sub-pages reached
              internally / via tests. Reachable routes are added here (FR-2b) at
              /ecommerce/sku-mappings + /ecommerce/api-keys (gated by `ecommerce`).
              The static segments score above any future dynamic /ecommerce
              segment. */}
          <Route
            path="ecommerce"
            element={<ModuleRoute moduleSlug="ecommerce"><WooCommerceSetup /></ModuleRoute>}
          />
          <Route
            path="ecommerce/sku-mappings"
            element={<ModuleRoute moduleSlug="ecommerce"><SkuMappings /></ModuleRoute>}
          />
          <Route
            path="ecommerce/api-keys"
            element={<ModuleRoute moduleSlug="ecommerce"><ApiKeys /></ModuleRoute>}
          />

          {/* Data Import/Export (Task 68) — UNGATED, mirroring
              frontend/src/App.tsx exactly: /data → DataPage (tabbed container
              with CSV Import / JSON Import / Export). DataImport, JsonBulkImport
              and DataExport are composed as TABS inside DataPage, NOT routed
              standalone — matching the original. v2 uses a relative child path
              under the OrgLayout `path="/"` parent. */}
          <Route path="data" element={<DataPage />} />

          {/* Payroll (Task 69) — module-gated (`payroll`), mirroring
              frontend/src/App.tsx exactly: /payroll/run → PayRunPage (bulk
              pay-run console) and /payroll/payslips/:id → PayslipDetail
              (imported as PayslipDetailPage; reads :id via useParams
              internally). v2 uses relative child paths under the OrgLayout
              `path="/"` parent. */}
          <Route
            path="payroll/run"
            element={<ModuleRoute moduleSlug="payroll"><PayRunPage /></ModuleRoute>}
          />
          <Route
            path="payroll/payslips/:id"
            element={<ModuleRoute moduleSlug="payroll"><PayslipDetailPage /></ModuleRoute>}
          />

          {/* Recurring Invoices (Task 70) — module-gated (`recurring_invoices`),
              mirroring frontend/src/App.tsx exactly: /recurring → RecurringList. */}
          <Route
            path="recurring"
            element={<ModuleRoute moduleSlug="recurring_invoices"><RecurringList /></ModuleRoute>}
          />

          {/* Purchase Orders (Task 70) — module-gated (`purchase_orders`),
              mirroring frontend/src/App.tsx exactly: /purchase-orders → POList
              and /purchase-orders/:id → PODetail (reads :id via useParams
              internally). v2 uses relative child paths under the OrgLayout
              `path="/"` parent. */}
          <Route
            path="purchase-orders"
            element={<ModuleRoute moduleSlug="purchase_orders"><POList /></ModuleRoute>}
          />
          <Route
            path="purchase-orders/:id"
            element={<ModuleRoute moduleSlug="purchase_orders"><PODetail /></ModuleRoute>}
          />

          {/* Assets (Task 71) — module-gated (`assets`), mirroring
              frontend/src/App.tsx exactly: /assets → AssetList and /assets/:id →
              AssetDetail (via AssetDetailRoute, which reads :id and passes it as
              the `assetId` prop — mirroring the original's AssetDetailRoute
              wrapper). The static /assets scores above the dynamic /assets/:id.
              v2 uses relative child paths under the OrgLayout `path="/"`
              parent. */}
          <Route
            path="assets"
            element={<ModuleRoute moduleSlug="assets"><AssetList /></ModuleRoute>}
          />
          <Route
            path="assets/:id"
            element={<ModuleRoute moduleSlug="assets"><AssetDetailRoute /></ModuleRoute>}
          />

          {/* Loyalty (Task 71) — module-gated (`loyalty`), mirroring
              frontend/src/App.tsx exactly: /loyalty → LoyaltyConfig. */}
          <Route
            path="loyalty"
            element={<ModuleRoute moduleSlug="loyalty"><LoyaltyConfig /></ModuleRoute>}
          />

          {/* Staff (Task 30) — module-gated (`staff`), mirroring
              frontend/src/App.tsx: /staff (StaffList) + /staff/:id (StaffDetail
              via StaffDetailRoute). Static /staff scores above /staff/:id. */}
          <Route
            path="staff"
            element={<ModuleRoute moduleSlug="staff"><StaffList /></ModuleRoute>}
          />
          <Route
            path="staff/:id"
            element={<ModuleRoute moduleSlug="staff"><StaffDetailRoute /></ModuleRoute>}
          />

          {/* Staff self-service (Task 31) — mirrors frontend/src/App.tsx:
              /staff/me/clock gated by `staff_management` (server also gates by
              self_service_clock_enabled), /staff/me/payslips gated by `payroll`
              (server enforces ownership via staff_members.user_id). Static
              /staff/me/* paths score above the dynamic /staff/:id. */}
          <Route
            path="staff/me/clock"
            element={<ModuleRoute moduleSlug="staff_management"><SelfServiceClockScreen /></ModuleRoute>}
          />
          <Route
            path="staff/me/payslips"
            element={<ModuleRoute moduleSlug="payroll"><MyPayslipsPage /></ModuleRoute>}
          />

          {/* Schedule + Staff Schedule + Roster Grid (Task 32) — mirrors
              frontend/src/App.tsx exactly: /staff-schedule/grid (RosterGridPage)
              gated by `scheduling`; /staff-schedule (StaffSchedule) gated by
              `branch_management`. /schedule redirects to the grid view (the
              roster grid is now the default Schedule landing). The legacy
              calendar view is still available at /schedule/calendar.
              Static /staff-schedule/grid scores above /staff-schedule. */}
          <Route
            path="schedule"
            element={<Navigate to="/staff-schedule/grid" replace />}
          />
          <Route
            path="schedule/calendar"
            element={<ModuleRoute moduleSlug="scheduling"><ScheduleCalendar /></ModuleRoute>}
          />
          <Route
            path="staff-schedule/grid"
            element={<ModuleRoute moduleSlug="scheduling"><RosterGridPage /></ModuleRoute>}
          />
          <Route
            path="staff-schedule"
            element={<ModuleRoute moduleSlug="branch_management"><StaffSchedule /></ModuleRoute>}
          />

          {/* Shift swaps + open-shift cover (Task 33) — module-gated
              (`staff_management`), mirroring frontend/src/App.tsx exactly:
              /shift-swaps (ShiftSwapPage) + /shift-cover (ShiftCoverPage). */}
          <Route
            path="shift-swaps"
            element={<ModuleRoute moduleSlug="staff_management"><ShiftSwapPage /></ModuleRoute>}
          />
          <Route
            path="shift-cover"
            element={<ModuleRoute moduleSlug="staff_management"><ShiftCoverPage /></ModuleRoute>}
          />

          {/* Leave approvals (Task 33) — module-gated (`staff_management`),
              mirroring frontend/src/App.tsx exactly: /leave/approvals
              (ApprovalQueue). */}
          <Route
            path="leave/approvals"
            element={<ModuleRoute moduleSlug="staff_management"><ApprovalQueue /></ModuleRoute>}
          />

          {/* Time tracking (Task 33) — module-gated (`time_tracking`),
              mirroring frontend/src/App.tsx exactly: /time-tracking
              (TimeSheet). */}
          <Route
            path="time-tracking"
            element={<ModuleRoute moduleSlug="time_tracking"><TimeSheet /></ModuleRoute>}
          />

          {/* Staff Timesheets (Phase A3) — module-gated (`timesheets`):
              /timesheets (tabbed Clocked In + Timesheets list),
              /timesheets/settings (org + branch override config). */}
          <Route
            path="timesheets"
            element={<ModuleRoute moduleSlug="timesheets"><TimesheetsPage /></ModuleRoute>}
          />
          <Route
            path="timesheets/settings"
            element={<ModuleRoute moduleSlug="timesheets"><TimesheetSettings /></ModuleRoute>}
          />

          {/* Reports (Task 46) — the org Reports hub at /reports is UNGATED
              (mirrors frontend/src/App.tsx, which mounts ReportsPage with no
              ModuleRoute). The tabbed container self-gates the Carjam + Fleet
              tabs on the `vehicles` module via useModules. The financial
              reports (/reports/profit-loss, /reports/balance-sheet,
              /reports/aged-receivables) are gated by the `accounting` module
              with ModuleRoute, mirroring the original exactly. ReportBuilder
              isn't routed in the original; a reachable /reports/builder route is
              added here (FR-2b). Static /reports/* paths score above any future
              dynamic segment. v2 uses relative child paths under the OrgLayout
              `path="/"` parent. */}
          <Route path="reports" element={<ReportsPage />} />
          <Route path="reports/builder" element={<ReportBuilder />} />
          <Route
            path="reports/profit-loss"
            element={<ModuleRoute moduleSlug="accounting"><ProfitAndLoss /></ModuleRoute>}
          />
          <Route
            path="reports/balance-sheet"
            element={<ModuleRoute moduleSlug="accounting"><BalanceSheet /></ModuleRoute>}
          />
          <Route
            path="reports/aged-receivables"
            element={<ModuleRoute moduleSlug="accounting"><AgedReceivables /></ModuleRoute>}
          />

          {/* Reports (Tasks 47-48) — the remaining report pages.
              /reports/wage-variance is gated by the `payroll` module
              (ModuleRoute moduleSlug="payroll"), mirroring frontend/src/App.tsx
              exactly — the only one of these the original router routes. The
              other seven (inventory, jobs, hospitality, pos, projects,
              tax-return, scheduled) aren't routed in the original (reached only
              via tests); reachable ungated /reports/* routes are added here
              (FR-2b). Each page handles its own empty/error states. Static
              /reports/* paths score above any dynamic segment. */}
          <Route path="reports/inventory" element={<InventoryReport />} />
          <Route path="reports/jobs" element={<JobReport />} />
          <Route path="reports/hospitality" element={<HospitalityReport />} />
          <Route path="reports/pos" element={<POSReport />} />
          <Route path="reports/projects" element={<ProjectReport />} />
          <Route path="reports/tax-return" element={<TaxReturnReport />} />
          <Route path="reports/scheduled" element={<ScheduledReports />} />
          <Route
            path="reports/wage-variance"
            element={<ModuleRoute moduleSlug="payroll"><WageVariancePage /></ModuleRoute>}
          />

          {/* Reports — in-hub tab routes (Task 20.1). The rebuilt
              ReportsPage (Task 19.2) is a landing now and no longer renders
              the Tabs UI; the grouped ReportLibrary navigates to these direct
              routes. Each tab component (RevenueSummary, InvoiceStatus, …) is
              wrapped in ReportTabPage to add a "Back to Reports" link and a
              page heading. Carjam + Fleet are gated by the `vehicles` module
              (mirroring the original ReportsPage which conditionally rendered
              those tabs only when `vehicles` was enabled). The other tabs
              (revenue, invoice-status, outstanding, top-services, gst-return,
              customer-statement, sms-usage, storage) are ungated, matching
              the original ReportsPage which always rendered them. Static
              /reports/* paths score above any dynamic segment. */}
          <Route
            path="reports/revenue"
            element={
              <ReportTabPage
                title="Revenue summary"
                description="Total revenue, GST collected, and monthly breakdown."
              >
                <RevenueSummary />
              </ReportTabPage>
            }
          />
          <Route
            path="reports/invoice-status"
            element={
              <ReportTabPage
                title="Invoice status"
                description="Pipeline of invoices by status."
              >
                <InvoiceStatus />
              </ReportTabPage>
            }
          />
          <Route
            path="reports/outstanding"
            element={
              <ReportTabPage
                title="Outstanding invoices"
                description="Unpaid and overdue invoices."
              >
                <OutstandingInvoices />
              </ReportTabPage>
            }
          />
          <Route
            path="reports/top-services"
            element={
              <ReportTabPage
                title="Top services"
                description="Best-sellers ranked by revenue."
              >
                <TopServices />
              </ReportTabPage>
            }
          />
          <Route
            path="reports/gst-return"
            element={
              <ReportTabPage
                title="GST return"
                description="Period summary for IRD GST filing."
              >
                <GstReturnSummary />
              </ReportTabPage>
            }
          />
          <Route
            path="reports/customer-statement"
            element={
              <ReportTabPage
                title="Customer statement"
                description="Per-account statement of activity."
              >
                <CustomerStatement />
              </ReportTabPage>
            }
          />
          <Route
            path="reports/carjam-usage"
            element={
              <ModuleRoute moduleSlug="vehicles">
                <ReportTabPage
                  title="CARJAM usage"
                  description="Vehicle data lookups and overage."
                >
                  <CarjamUsage />
                </ReportTabPage>
              </ModuleRoute>
            }
          />
          <Route
            path="reports/sms-usage"
            element={
              <ReportTabPage
                title="SMS usage"
                description="Messages sent, packages, and spend."
              >
                <SmsUsage />
              </ReportTabPage>
            }
          />
          <Route
            path="reports/storage"
            element={
              <ReportTabPage
                title="Storage usage"
                description="Files, attachments, and storage breakdown."
              >
                <StorageUsage />
              </ReportTabPage>
            }
          />
          <Route
            path="reports/fleet"
            element={
              <ModuleRoute moduleSlug="vehicles">
                <ReportTabPage
                  title="Fleet report"
                  description="Spend, vehicles serviced, and outstanding balance per fleet account."
                >
                  <FleetReport />
                </ReportTabPage>
              </ModuleRoute>
            }
          />

          {/* Expenses (Task 51) — gated by the `expenses` module, mirroring
              frontend/src/App.tsx exactly: /expenses → ExpenseList. */}
          <Route
            path="expenses"
            element={<ModuleRoute moduleSlug="expenses"><ExpenseList /></ModuleRoute>}
          />

          {/* Accounting (Task 49) — gated by the `accounting` module, mirroring
              frontend/src/App.tsx exactly: /accounting (ChartOfAccounts),
              /accounting/journal-entries (JournalEntries),
              /accounting/journal-entries/:id (JournalEntryDetail, reads :id via
              useParams internally), /accounting/periods (AccountingPeriods).
              Static /accounting/periods + /accounting/journal-entries score
              above the dynamic /accounting/journal-entries/:id. v2 uses relative
              child paths under the OrgLayout `path="/"` parent. */}
          <Route
            path="accounting"
            element={<ModuleRoute moduleSlug="accounting"><ChartOfAccounts /></ModuleRoute>}
          />
          <Route
            path="accounting/journal-entries"
            element={<ModuleRoute moduleSlug="accounting"><JournalEntries /></ModuleRoute>}
          />
          <Route
            path="accounting/journal-entries/:id"
            element={<ModuleRoute moduleSlug="accounting"><JournalEntryDetail /></ModuleRoute>}
          />
          <Route
            path="accounting/periods"
            element={<ModuleRoute moduleSlug="accounting"><AccountingPeriods /></ModuleRoute>}
          />

          {/* GST / Tax (Task 51) — gated by the `accounting` module, mirroring
              frontend/src/App.tsx exactly: /tax/gst-periods (GstPeriods),
              /tax/gst-periods/:id (GstFilingDetail, reads :id via useParams
              internally), /tax/wallets (TaxWallets), /tax/position
              (TaxPosition). Static /tax/gst-periods scores above the dynamic
              /tax/gst-periods/:id. */}
          <Route
            path="tax/gst-periods"
            element={<ModuleRoute moduleSlug="accounting"><GstPeriods /></ModuleRoute>}
          />
          <Route
            path="tax/gst-periods/:id"
            element={<ModuleRoute moduleSlug="accounting"><GstFilingDetail /></ModuleRoute>}
          />
          <Route
            path="tax/wallets"
            element={<ModuleRoute moduleSlug="accounting"><TaxWallets /></ModuleRoute>}
          />
          <Route
            path="tax/position"
            element={<ModuleRoute moduleSlug="accounting"><TaxPosition /></ModuleRoute>}
          />

          {/* Banking (Task 50) — gated by the `accounting` module, mirroring
              frontend/src/App.tsx exactly: /banking/accounts (BankAccounts),
              /banking/transactions (BankTransactions), /banking/reconciliation
              (ReconciliationDashboard). */}
          <Route
            path="banking/accounts"
            element={<ModuleRoute moduleSlug="accounting"><BankAccounts /></ModuleRoute>}
          />
          <Route
            path="banking/transactions"
            element={<ModuleRoute moduleSlug="accounting"><BankTransactions /></ModuleRoute>}
          />
          <Route
            path="banking/reconciliation"
            element={<ModuleRoute moduleSlug="accounting"><ReconciliationDashboard /></ModuleRoute>}
          />

          {/* Notifications (Task 52) — UNGATED, mirroring frontend/src/App.tsx
              exactly: /notifications (NotificationsPage settings hub) and
              /notifications/inbox (InboxPage in-app inbox). Both static paths
              are declared; React Router v7 score-based matching resolves the
              more specific /notifications/inbox above /notifications regardless
              of order. WofRegoReminders is a notifications sub-section not routed
              standalone in the original — a reachable route is added here (FR-2b)
              at /notifications/wof-rego-reminders. v2 uses relative child paths
              under the OrgLayout `path="/"` parent. */}
          <Route path="notifications" element={<NotificationsPage />} />
          <Route path="notifications/inbox" element={<InboxPage />} />
          <Route path="notifications/wof-rego-reminders" element={<WofRegoReminders />} />

          {/* SMS (Task 53) — gated by the `sms` module (ModuleRoute
              moduleSlug="sms"), mirroring the original ModuleRouter which maps
              `/sms/*` → SmsChat. SmsChat is a single page (no useParams/useRoutes
              nested routing), so v2 routes `sms` with NO splat. SmsUsageSummary
              isn't routed standalone in the original (it's reached elsewhere);
              a reachable route is added here (FR-2b) at /sms/usage, declared
              alongside /sms — the static /sms/usage scores above /sms, and since
              /sms has no splat it won't swallow /sms/usage. Both gated by `sms`. */}
          <Route
            path="sms"
            element={<ModuleRoute moduleSlug="sms"><SmsChat /></ModuleRoute>}
          />
          <Route
            path="sms/usage"
            element={<ModuleRoute moduleSlug="sms"><SmsUsageSummary /></ModuleRoute>}
          />

          {/* POS (Task 54) — gated by the `pos` module (ModuleRoute
              moduleSlug="pos"), mirroring frontend/src/App.tsx exactly:
              /pos → POSScreen (full-screen touch POS). OrderPanel / PaymentPanel
              / ProductGrid / SyncStatus / TipPrompt are POSScreen sub-components,
              not routed. v2 uses relative child paths under the OrgLayout
              `path="/"` parent. */}
          <Route
            path="pos"
            element={<ModuleRoute moduleSlug="pos"><POSScreen /></ModuleRoute>}
          />

          {/* Floor Plan / Tables + Kitchen Display (Task 55) — mirrors
              frontend/src/App.tsx exactly: /floor-plan → FloorPlan (gated
              `tables`), /kitchen → KitchenDisplay (gated `kitchen_display`).
              ReservationList isn't routed standalone in the original (reached
              from FloorPlan / embedded); a reachable /reservations route is
              added here (FR-2b), gated by `tables`. The static /reservations
              path scores above any future dynamic segment. */}
          <Route
            path="floor-plan"
            element={<ModuleRoute moduleSlug="tables"><FloorPlan /></ModuleRoute>}
          />
          <Route
            path="reservations"
            element={<ModuleRoute moduleSlug="tables"><ReservationList /></ModuleRoute>}
          />
          <Route
            path="kitchen"
            element={<ModuleRoute moduleSlug="kitchen_display"><KitchenDisplay /></ModuleRoute>}
          />

          {/* Settings — org_admin only (branch_admin redirected to /dashboard).
              Mirrors frontend/src/App.tsx exactly: /settings (Settings
              container), /settings/online-payments (OnlinePaymentsSettings),
              and the two payroll people routes gated by the `payroll` module.
              The other settings tabs (webhooks, feature flags, printer, leave
              types, clock-in policy, people permissions, etc.) are reached as
              TABS inside the Settings container, not as standalone routes. v2
              uses relative child paths under the OrgLayout `path="/"` parent. */}
          <Route element={<RequireOrgAdmin />}>
            <Route path="settings" element={<Settings />} />
            <Route path="settings/online-payments" element={<OnlinePaymentsSettings />} />
            <Route path="settings/shift-templates" element={<ShiftTemplatesSettings />} />
            <Route
              path="settings/people/pay-periods"
              element={<ModuleRoute moduleSlug="payroll"><PayPeriodsPage /></ModuleRoute>}
            />
            <Route
              path="settings/people/allowance-types"
              element={<ModuleRoute moduleSlug="payroll"><AllowanceTypesPage /></ModuleRoute>}
            />
          </Route>
        </Route>
      </Route>

      {/* Public catch-all (Task 62) — replaces the old
          `<Navigate to="/dashboard" replace />` placeholder. Mirrors the
          original's editor-created-page catch-all: PublicPageRenderer resolves
          the slug against the editor backend and renders published Puck
          content, follows a redirect, or renders its own 404 — preserving its
          logic verbatim. */}
      <Route path="*" element={<PublicPageRenderer />} />
    </Routes>
  )
}

function App() {
  return (
    <ErrorBoundary level="app" name="root">
      <BrowserRouter basename={getBasename()}>
        <LocaleProvider>
          <PlatformBrandingProvider>
            <ThemeProvider>
              <AuthProvider>
                <TenantProvider>
                  <ModuleProvider>
                    <FeatureFlagProvider>
                      <BranchProvider>
                        <Lazy>
                          <AppRoutes />
                        </Lazy>
                      </BranchProvider>
                    </FeatureFlagProvider>
                  </ModuleProvider>
                </TenantProvider>
              </AuthProvider>
            </ThemeProvider>
          </PlatformBrandingProvider>
        </LocaleProvider>
      </BrowserRouter>
    </ErrorBoundary>
  )
}

export default App
