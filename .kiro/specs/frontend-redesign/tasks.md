# Frontend Redesign — Tasks

## Phase 0: Project Scaffold

- [x] Task 1: Create `frontend-v2/` project skeleton — package.json, tsconfig.json, vite.config.ts (base: '/new/'), postcss.config.js, index.html entry point
- [x] Task 2: Create design token stylesheet `frontend-v2/src/styles/tokens.css` — map all tokens from `OraInvoice_Handoff/app/ds.css` into Tailwind v4 `@theme` block (colors, spacing, radii, shadows, sidebar palette)
- [x] Task 3: Add IBM Plex Sans + IBM Plex Mono fonts — create `src/styles/fonts.css` with @font-face or Google Fonts import, configure `.mono` utility class with `font-feature-settings: "tnum" 1`
- [x] Task 4: Create `frontend-v2/src/main.tsx` entry point + `App.tsx` with React Router skeleton (lazy routes, layout wrappers)
- [x] Task 5: Create API client `frontend-v2/src/api/client.ts` — axios instance with baseURL '/api/v1', interceptors for auth token, typed request helpers

## Phase 1: App Shell (OrgLayout)

- [x] Task 6: Create `frontend-v2/src/layouts/OrgLayout.tsx` — flex container (sidebar + main), 100vh, overflow hidden. Reference: `OraInvoice_Handoff/app/shell.js` structure
- [x] Task 7: Create `frontend-v2/src/components/shell/Sidebar.tsx` — 264px wide, ink bg, flex column (header/scroll/footer), grouped nav with NavLink active state, count pills, alert dots. Reference: `OraInvoice_Handoff/app/ds.css` sidebar classes
- [x] Task 8: Create `frontend-v2/src/components/shell/TopBar.tsx` — 64px, search field with ⌘K hint, branch chip, notifications icon button with badge, "New" primary button, avatar. Reference: `.topbar` in ds.css
- [x] Task 9: Implement responsive shell — mobile drawer (≤860px), hamburger toggle, scrim overlay, nav item closes drawer, search collapses to icon, branch chip hidden, "New" icon-only
- [x] Task 10: Create `frontend-v2/src/components/shell/OrgSwitcher.tsx` — gradient avatar, org name + plan line, chevron, Headless UI Menu dropdown
- [x] Task 11: Create shared UI primitives — Button (primary/ghost/quiet/danger/sm/icon variants), Card (card/card-head/card-body), IconButton, Badge/Pill (status variants: paid/sent/overdue/draft)

## Phase 2: Auth Layout + Pages

- [x] Task 12: Create `frontend-v2/src/layouts/AuthLayout.tsx` — split-screen (ink brand panel + form column), brand panel hides ≤900px, mobile logo in form head. Reference: `OraInvoice_Handoff/app/auth.css`
- [x] Task 13: Port auth pages (Login, Signup/SignupWizard/SignupForm, ConfirmationStep, PaymentStep) — copy all logic from `frontend/src/pages/auth/`, apply design from `Login.html` + `Signup.html`
- [x] Task 14: Port auth pages (MfaChallenge, MfaVerify, PasskeySetup, PasswordResetRequest, PasswordResetComplete, VerifyEmail) — copy logic, apply design from `MfaVerify.html`, `PasskeySetup.html`, `PasswordReset.html`, `VerifyEmail.html`
- [x] Task 15: Copy auth contexts + hooks — AuthContext, useAuth, Firebase config, JWT handling, MFA state. Verbatim copy from `frontend/src/contexts/` and `frontend/src/hooks/`

## Phase 3: Dashboard

- [x] Task 16: Port Dashboard page — KPI row (4 cards), revenue chart (Recharts AreaChart), recent invoices table, activity feed, upcoming bookings. Copy logic from `frontend/src/pages/dashboard/Dashboard.tsx`, apply design from `OraInvoice_Handoff/app/Dashboard.html`
- [x] Task 17: Port dashboard variants (GlobalAdminDashboard, OrgAdminDashboard, SalespersonDashboard) — copy logic, apply same design patterns
- [x] Task 18: Port dashboard widgets (all 12) — ActiveStaff, CashFlowChart, ExpiryReminders, InventoryOverview, PublicHolidays, RecentClaims, RecentCustomers, RecentInvoices, ReminderConfig, TodaysBookings, WidgetCard, WidgetGrid

## Phase 4: Invoices + Quotes

- [x] Task 19: Port InvoiceList page — table with status badges, filters, pagination. Copy logic from `frontend/src/pages/invoices/InvoiceList.tsx`, apply design from `Invoices.html`
- [x] Task 20: Port InvoiceCreate + InvoiceDetail pages — full form with line items, calculations, GST. Copy ALL math logic verbatim. Design from `InvoiceCreate.html`, `InvoiceDetail.html`
- [x] Task 21: Port QuoteList + QuoteCreate + QuoteDetail pages — copy logic from `frontend/src/pages/quotes/`, apply design from `Quotes.html`
- [x] Task 22: Port invoice/quote modals — IssueInvoiceModal, QrPaymentAmountModal, QrPaymentWaitingPopup, CreditNoteModal, RefundModal, CancelQuoteModal, InventoryPickerModal

## Phase 5: Customers + Vehicles

- [x] Task 23: Port CustomerList + CustomerCreate + CustomerProfile pages — copy logic, apply design from `Customers.html`, `CustomerDetail.html`
- [x] Task 24: Port DiscountRules + FleetAccounts pages — copy logic, apply design from `FleetAccounts.html`
- [x] Task 25: Port VehicleList + VehicleProfile pages + customer modals (CustomerCreateModal, CustomerEditModal, CustomerViewModal, VehiclePickerModal) — copy logic, apply design from `Vehicles.html`, `VehicleDetail.html`

## Phase 6: Jobs + Job Cards + Bookings

- [x] Task 26: Port JobBoard + JobList + JobsPage + JobDetail + JobTimer — copy logic, apply design from `Jobs.html`, `JobBoard.html`, `JobDetail.html`
- [x] Task 27: Port JobCardList + JobCardCreate + JobCardDetail — copy logic, apply design from `JobCards.html`, `JobCardCreate.html`, `JobCardDetail.html`
- [x] Task 28: Port BookingPage + BookingCalendar + BookingCalendarPage + BookingForm + BookingList + BookingListPanel — copy logic, apply design from `Bookings.html`
- [x] Task 29: Port job/booking modals — TakeOverDialog, JobCreationModal

## Phase 7: Staff + Schedule + Time Tracking

- [x] Task 30: Port StaffList + StaffDetail + all staff tabs (Overview, Hours, Roster, Payslips, Documents) — copy logic, apply design from `Staff.html`, `StaffDetail.html`
- [x] Task 31: Port staff leave (LeaveTab, BalanceCardsRow, LedgerTable, CasualLeaveBanner) + self-service (MyPayslipsPage, SelfServiceClockScreen) — copy logic, apply design from `MyPayslips.html`, `ClockScreen.html`
- [x] Task 32: Port ScheduleCalendar + ShiftTemplates + StaffSchedule + RosterGridPage + components — copy logic, apply design from `Schedule.html`, `StaffSchedule.html`
- [x] Task 33: Port ShiftSwapPage + ShiftCoverPage + ApprovalQueue + TimeSheet — copy logic, apply design from `ShiftSwaps.html`, `LeaveApprovals.html`, `TimeTracking.html`
- [x] Task 34: Port staff modals (all 12) — AddRecurringAllowance, ApproveWeek, FlagForReview, ManualEntry, MinimumWageWarning, OvertimeRequest, RunningLateSheet, Termination, AdjustBalance, RequestLeave, CopyWeekConfirm, LeaveOverlapConfirmation

## Phase 8: Inventory + Items + Catalogue

- [x] Task 35: Port InventoryPage + ProductList + ProductDetail + StockLevels + StockMovements — copy logic, apply design from `Inventory.html`
- [x] Task 36: Port StockAdjustment + StockTake + StockTransfers + StockUpdateLog + PurchaseOrders + SupplierList + ReorderAlerts + PricingRules + CategoryTree + CSVImport + UsageHistory — copy logic, apply design from `StockTransfers.html`, `PurchaseOrders.html`
- [x] Task 37: Port ItemsPage + ItemsCatalogue + LabourRates + ServiceTypesTab + PackageBuilder + PackagePreview — copy logic, apply design from `Items.html`
- [x] Task 38: Port CataloguePage + PartsCatalogue + ServiceCatalogue + FluidOilForm + inventory/items modals (AddToStockModal, ServiceTypeModal, StockSourceModal) — copy logic, apply design from `Catalogue.html`

## Phase 9: Settings

- [x] Task 39: Port Settings + OrgSettings + BusinessSettings + BranchManagement + BranchSettings + Billing + Profile + SecuritySettings + MfaSettings — copy logic, apply design from `Settings.html`
- [x] Task 40: Port UserManagement + ModuleConfiguration + InvoiceTemplateTab + CurrencySettings + LanguageSwitcher + OnlinePaymentsSettings + IntegrationsSettings + AccountingIntegrations — copy logic, apply design from `Settings.html`, `OnlinePaymentsSettings.html`
- [x] Task 41: Port WebhookManagement + WebhookSettings + FeatureFlagSettings + PrinterSettings + people sub-pages (AllowanceTypes, ClockInPolicy, LeaveTypes, PayPeriods, Permissions) — copy logic

## Phase 10: Admin Console

- [x] Task 42: Port Organisations + OrganisationDetail + UserManagement + SubscriptionPlans + TradeFamilies — copy logic, apply design from `AdminOrganisations.html`, `AdminOrgDetail.html`, `AdminUserManagement.html`, `AdminSubscriptionPlans.html`, `AdminTradeFamilies.html`
- [x] Task 43: Port FeatureFlags + AnalyticsDashboard + AuditLog + ErrorLog + AdminSettings + AdminSecurityPage — copy logic, apply design from `AdminFeatureFlags.html`, `AdminAnalytics.html`, `AdminAuditLog.html`, `AdminErrorLog.html`, `AdminSettings.html`, `AdminSecurity.html`
- [x] Task 44: Port BrandingConfig + CalendarSync + EmailDeliveryHealth + EmailProviders + SmsProviders + GlobalAdminProfile + GlobalBranchOverview + HAReplication + Integrations + LiveMigrationTool + MigrationTool + NotificationManager + AdminReports + XeroCredentials — copy logic, apply design from corresponding `Admin*.html` files
- [x] Task 45: Port admin modals (ApplyCouponModal, DeleteModal, MovePlanModal, SuspendModal) — copy logic, apply design

## Phase 11: Reports

- [x] Task 46: Port ReportsPage + ReportBuilder + RevenueSummary + ProfitAndLoss + BalanceSheet + AgedReceivables + OutstandingInvoices + CustomerStatement — copy logic, apply design from `Reports.html`, `ReportBuilder.html`, `RevenueSummary.html`, `ProfitLoss.html`, `BalanceSheet.html`, `AgedReceivables.html`, `OutstandingInvoices.html`, `CustomerStatement.html`
- [x] Task 47: Port GstReturnSummary + InvoiceStatus + InventoryReport + JobReport + FleetReport + HospitalityReport + POSReport + ProjectReport — copy logic, apply design from corresponding report HTML files
- [x] Task 48: Port CarjamUsage + SmsUsage + StorageUsage + TaxReturnReport + ScheduledReports + WageVariancePage + TopServices — copy logic, apply design from `CarjamUsage.html`, `SmsUsage.html`, `StorageUsage.html`, `TaxReturnReport.html`, `ScheduledReports.html`, `WageVariance.html`, `TopServices.html`

## Phase 12: Accounting + Banking + Tax + Expenses

- [x] Task 49: Port AccountingPeriods + ChartOfAccounts + JournalEntries + JournalEntryDetail — copy logic, apply design from `Accounting.html`, `AccountingPeriods.html`, `JournalEntries.html`, `JournalEntryDetail.html`
- [x] Task 50: Port BankAccounts + BankTransactions + ReconciliationDashboard — copy logic, apply design from `BankAccounts.html`, `Banking.html`, `Reconciliation.html`
- [x] Task 51: Port GstPeriods + GstFilingDetail + TaxPosition + TaxWallets + ExpenseList — copy logic, apply design from `GstPeriods.html`, `GstFilingDetail.html`, `Tax.html`, `TaxPosition.html`, `TaxWallets.html`, `Expenses.html`

## Phase 13: Notifications + SMS

- [x] Task 52: Port NotificationsPage + InboxPage + NotificationLog + NotificationPreferences + OverdueRules + Reminders + TemplateEditor + WofRegoReminders — copy logic, apply design from `Notifications.html`, `Inbox.html`
- [x] Task 53: Port SmsChat + SmsUsageSummary — copy logic, apply design from `SmsChat.html`, `SmsUsage.html`

## Phase 14: POS + Kitchen + Floor Plan

- [x] Task 54: Port POSScreen + OrderPanel + PaymentPanel + ProductGrid + SyncStatus + TipPrompt + PrinterErrorModal — copy logic, apply design from `POS.html`
- [x] Task 55: Port KitchenDisplay + FloorPlan + ReservationList — copy logic, apply design from `Kitchen.html`, `FloorPlan.html`

## Phase 15: Portal

- [x] Task 56: Create `frontend-v2/src/layouts/PortalLayout.tsx` — branded header, summary cards, tabbed content, "Powered by OraInvoice" footer. Reference: `Portal.html`
- [x] Task 57: Port PortalPage + MyDetails + MyPrivacy + InvoiceHistory + VehicleHistory + AssetHistory + BookingManager + ClaimsTab + DocumentsTab + JobsTab — copy logic, apply design from `Portal.html`
- [x] Task 58: Port LoyaltyBalance + MessagesTab + PaymentPage + PaymentSuccess + ProjectsTab + ProgressClaimsTab + QuoteAcceptance + RecurringTab + PortalRecover + PortalSignedOut — copy logic

## Phase 16: Kiosk

- [x] Task 59: Create `frontend-v2/src/layouts/KioskLayout.tsx` — full-screen, touch-optimized, branded, 44px+ hit targets. Reference: `Kiosk.html`
- [x] Task 60: Port KioskPage + KioskWelcome + KioskRegoEntry + KioskVehicleSummary + KioskCheckInForm + KioskClockScreen + KioskSuccess + KioskQrPopup — copy logic, apply design from `Kiosk.html`

## Phase 17: Public Pages

- [x] Task 61: Port LandingPage + TradesPage + WorkshopPage + ManagedPage + PrivacyPage — copy logic, apply design from `LandingPage.html`, `Trades.html`, `Workshop.html`, `Managed.html`, `Privacy.html`
- [x] Task 62: Port InvoicePaymentPage + PublicPageRenderer + PageShell + StaffRosterPublicView + QrPaymentSuccess + QrPaymentCancel + DemoRequestModal — copy logic, apply design from `InvoicePayment.html`, `QrPayment.html`, `QrPaymentSuccess.html`, `QrPaymentCancel.html`

## Phase 18: Construction + Claims + Compliance

- [x] Task 63: Port ProgressClaimForm + ProgressClaimList + RetentionSummary + VariationForm + VariationList — copy logic, apply design from `ProgressClaims.html`, `Retentions.html`, `Variations.html`
- [x] Task 64: Port ClaimsList + ClaimCreateForm + ClaimDetail + ClaimsReports + claims modals (ClaimNoteModal, ClaimResolveModal) — copy logic, apply design from `Claims.html`, `ClaimCreate.html`, `ClaimDetail.html`, `ClaimsReports.html`
- [x] Task 65: Port ComplianceDashboard + DocumentTable + FilePreview + SummaryCards + UploadForm + compliance modals (DeleteConfirmation, EditModal) — copy logic, apply design from `Compliance.html`

## Phase 19: Franchise + Projects + E-commerce + Data

- [x] Task 66: Port FranchiseDashboard + LocationList + LocationDetail + StockTransfers + TransferDetail — copy logic, apply design from `Franchise.html`, `Locations.html`, `LocationDetail.html`, `StockTransfers.html`, `TransferDetail.html`
- [x] Task 67: Port ProjectDashboard + ProjectList — copy logic, apply design from `Projects.html`, `ProjectDetail.html`
- [x] Task 68: Port WooCommerceSetup + SkuMappings + ApiKeys + DataPage + DataExport + DataImport + JsonBulkImport — copy logic, apply design from `Ecommerce.html`, `Data.html`

## Phase 20: Remaining Pages

- [x] Task 69: Port PayRunPage + PayslipDetail — copy logic, apply design from `Payroll.html`, `PayslipDetail.html`
- [x] Task 70: Port RecurringList + POList + PODetail — copy logic, apply design from `Recurring.html`, `PurchaseOrders.html`, `PODetail.html`
- [x] Task 71: Port AssetList + AssetDetail + LoyaltyConfig + PPSRSearchPage + PpsrHistoryTable + PpsrResultPanel + PpsrDetailDrawer — copy logic, apply design from `Assets.html`, `AssetDetail.html`, `Loyalty.html`, `PPSRSearch.html`
- [x] Task 72: Port OnboardingWizard + SetupWizard + setup steps (7) + SetupGuide + WelcomeScreen + SummaryScreen — copy logic, apply design from `SetupWizard.html`, `SetupGuide.html`

## Phase 21: UI Base Components + Shared

- [x] Task 73: Create base Modal component + ConfirmDialog — Headless UI Dialog with design tokens, backdrop, transitions. Used by all modals
- [x] Task 74: Port remaining shared components — MfaModal, BlockingPaymentModal, ExpiringPaymentWarningModal, PasswordConfirmModal, ConflictResolutionModal, ScheduleEntryModal. Copy logic, apply design

## Phase 22: Docker + Nginx Wiring

- [x] Task 75: Create `docker-compose.frontend-v2.yml` — new service `frontend-v2` running Vite dev server on port 5174, volume-mounted to `./frontend-v2`, no interference with existing services
- [x] Task 76: Create nginx config snippet for `/new/` location block — proxy to frontend-v2 container, ensure `/api/` still routes to backend, document how to enable

## Phase 23: Integration + Polish + Final Audit

- [x] Task 77: Wire all routes in App.tsx — ensure every page from the tracker is reachable, lazy-loaded, with correct layout wrapper and route guards
- [x] Task 78: Run `npm install && npm run build` in frontend-v2, fix all TypeScript errors, confirm pages render
- [x] Task 79: **Final Audit** — Walk every entry in REDESIGN_TRACKER.md and confirm ✅. Cross-reference the original frontend router to find any missing routes. Cross-reference all modals/popups/drawers. Cross-reference all shared widgets/components. For each page: verify all buttons, API calls, forms, calculations, gates, and states are present. Document findings in `docs/REDESIGN_AUDIT.md`. Implement any gaps found.
