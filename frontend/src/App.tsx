import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate, Outlet, useParams } from 'react-router-dom'
import { AuthProvider, useAuth } from '@/contexts/AuthContext'
import { TenantProvider, useTenant } from '@/contexts/TenantContext'
import { ModuleProvider } from '@/contexts/ModuleContext'
import { FeatureFlagProvider } from '@/contexts/FeatureFlagContext'
import { BranchProvider } from '@/contexts/BranchContext'
import { LocaleProvider } from '@/contexts/LocaleContext'
import { PlatformBrandingProvider } from '@/contexts/PlatformBrandingContext'
import { ThemeProvider } from '@/contexts/ThemeContext'
import { Spinner } from '@/components/ui'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { ModuleRoute } from '@/components/common/ModuleRoute'
import { Login, MfaVerify, PasswordResetRequest, PasswordResetComplete, VerifyEmail } from '@/pages/auth'

/* Fleet Portal — separate SPA mounted at /fleet/* (or fleet.<domain>).
   Renders its own provider tree and route table; never shares chrome
   with the staff app. See .kiro/specs/b2b-fleet-portal/. */
import { FleetPortalRouter, isFleetPortalRoute } from '@/fleet-portal/FleetPortalRouter'

/* Signup is lazy-loaded because it imports @stripe/stripe-js and
   @stripe/react-stripe-js at the top level.  Eager loading would pull
   those heavy Stripe bundles into the initial chunk and — critically —
   if an ad-blocker or network issue blocks the Stripe script, the
   entire App module fails to evaluate, crashing every page. */
const LazySignup = lazy(() =>
  import('@/pages/auth/SignupWizard').then((m) => ({ default: m.SignupWizard })),
)
import { AdminLayout } from '@/layouts/AdminLayout'
import { OrgLayout } from '@/layouts/OrgLayout'
import { NoIndexRoute } from '@/components/common/NoIndexRoute'

/* ── Dashboard (lazy — Dashboard transitively imports recharts via
   CashFlowChartWidget, ~274 KB. Lazy-loading keeps it out of the main
   chunk so unauthenticated landing-page visitors do not pay for it.
   PERFORMANCE_AUDIT.md §F-H3.) ── */
const Dashboard = lazy(() => import('@/pages/dashboard').then(m => ({ default: m.Dashboard })))

/* ── Admin pages (lazy — touched by ~5 of 2500 users.
   PERFORMANCE_AUDIT.md §F-H4. Expected main-chunk reduction: 250–400 KB.) ── */
const Organisations = lazy(() => import('@/pages/admin/Organisations').then(m => ({ default: m.Organisations })))
const AnalyticsDashboard = lazy(() => import('@/pages/admin/AnalyticsDashboard').then(m => ({ default: m.AnalyticsDashboard })))
const AdminSettings = lazy(() => import('@/pages/admin/Settings').then(m => ({ default: m.Settings })))
const ErrorLog = lazy(() => import('@/pages/admin/ErrorLog').then(m => ({ default: m.ErrorLog })))
const NotificationManager = lazy(() => import('@/pages/admin/NotificationManager'))
const BrandingConfig = lazy(() => import('@/pages/admin/BrandingConfig').then(m => ({ default: m.BrandingConfig })))
const MigrationTool = lazy(() => import('@/pages/admin/MigrationTool').then(m => ({ default: m.MigrationTool })))
const LiveMigrationTool = lazy(() => import('@/pages/admin/LiveMigrationTool').then(m => ({ default: m.LiveMigrationTool })))
const HAReplication = lazy(() => import('@/pages/admin/HAReplication').then(m => ({ default: m.HAReplication })))
const AuditLog = lazy(() => import('@/pages/admin/AuditLog').then(m => ({ default: m.AuditLog })))
const AdminReports = lazy(() => import('@/pages/admin/Reports').then(m => ({ default: m.Reports })))
const Integrations = lazy(() => import('@/pages/admin/Integrations').then(m => ({ default: m.Integrations })))
const UserManagement = lazy(() => import('@/pages/admin/UserManagement').then(m => ({ default: m.UserManagement })))
const SubscriptionPlans = lazy(() => import('@/pages/admin/SubscriptionPlans').then(m => ({ default: m.SubscriptionPlans })))
const FeatureFlags = lazy(() => import('@/pages/admin/FeatureFlags').then(m => ({ default: m.FeatureFlags })))
const GlobalAdminProfile = lazy(() => import('@/pages/admin/GlobalAdminProfile').then(m => ({ default: m.GlobalAdminProfile })))
const TradeFamilies = lazy(() => import('@/pages/admin/TradeFamilies'))
const AdminSecurityPage = lazy(() => import('@/pages/admin/AdminSecurityPage').then(m => ({ default: m.AdminSecurityPage })))
const OrganisationDetail = lazy(() => import('@/pages/admin/OrganisationDetail').then(m => ({ default: m.OrganisationDetail })))

/* ── Org pages (lazy loaded) ── */
const CustomerList = lazy(() => import('@/pages/customers/CustomerList'))
const CustomerCreate = lazy(() => import('@/pages/customers/CustomerCreate'))
const CustomerProfile = lazy(() => import('@/pages/customers/CustomerProfile'))
const VehicleList = lazy(() => import('@/pages/vehicles/VehicleList'))
const VehicleProfile = lazy(() => import('@/pages/vehicles/VehicleProfile'))
const PPSRSearchPage = lazy(() => import('@/pages/ppsr/PPSRSearchPage'))
const InvoiceList = lazy(() => import('@/pages/invoices/InvoiceList'))
const InvoiceCreate = lazy(() => import('@/pages/invoices/InvoiceCreate'))
const QuoteList = lazy(() => import('@/pages/quotes/QuoteList'))
const QuoteCreate = lazy(() => import('@/pages/quotes/QuoteCreate'))
const JobCardList = lazy(() => import('@/pages/job-cards/JobCardList'))
const JobCardCreate = lazy(() => import('@/pages/job-cards/JobCardCreate'))
const JobCardDetail = lazy(() => import('@/pages/job-cards/JobCardDetail'))
const BookingCalendarPage = lazy(() => import('@/pages/bookings/BookingCalendarPage'))
const InventoryPage = lazy(() => import('@/pages/inventory/InventoryPage'))
const ReportsPage = lazy(() => import('@/pages/reports/ReportsPage'))

/* Settings pages */
const OrgSettingsPage = lazy(() => import('@/pages/settings/Settings').then(m => ({ default: m.Settings })))
const OnlinePaymentsSettings = lazy(() => import('@/pages/settings/OnlinePaymentsSettings'))
const NotificationsPage = lazy(() => import('@/pages/notifications/NotificationsPage'))
const InboxPage = lazy(() => import('@/pages/notifications/InboxPage'))

/* Extended org pages */
const StaffList = lazy(() => import('@/pages/staff/StaffList'))
const ProjectList = lazy(() => import('@/pages/projects/ProjectList'))
const ProjectDashboard = lazy(() => import('@/pages/projects/ProjectDashboard'))
const ExpenseList = lazy(() => import('@/pages/expenses/ExpenseList'))
const TimeSheet = lazy(() => import('@/pages/time-tracking/TimeSheet'))
const POSScreen = lazy(() => import('@/pages/pos/POSScreen'))
const ScheduleCalendar = lazy(() => import('@/pages/schedule/ScheduleCalendar'))
const RosterGridPage = lazy(() => import('@/pages/staff-schedule/RosterGridPage'))
const RecurringList = lazy(() => import('@/pages/recurring/RecurringList'))
const POList = lazy(() => import('@/pages/purchase-orders/POList'))
const PODetail = lazy(() => import('@/pages/purchase-orders/PODetail'))
const DataPage = lazy(() => import('@/pages/data/DataPage'))

/* Construction pages */
const ProgressClaimList = lazy(() => import('@/pages/construction/ProgressClaimList'))
const VariationList = lazy(() => import('@/pages/construction/VariationList'))
const RetentionSummary = lazy(() => import('@/pages/construction/RetentionSummary'))

/* Hospitality / POS pages */
const FloorPlan = lazy(() => import('@/pages/floor-plan/FloorPlan'))
const KitchenDisplay = lazy(() => import('@/pages/kitchen/KitchenDisplay'))

/* Additional module pages */
const FranchiseDashboard = lazy(() => import('@/pages/franchise/FranchiseDashboard'))
const LocationList = lazy(() => import('@/pages/franchise/LocationList'))
const StockTransfers = lazy(() => import('@/pages/franchise/StockTransfers'))
const AssetList = lazy(() => import('@/pages/assets/AssetList'))
const AssetDetail = lazy(() => import('@/pages/assets/AssetDetail'))
const ComplianceDashboard = lazy(() => import('@/pages/compliance/ComplianceDashboard'))
const LoyaltyConfig = lazy(() => import('@/pages/loyalty/LoyaltyConfig'))
const WooCommerceSetup = lazy(() => import('@/pages/ecommerce/WooCommerceSetup'))
const SetupWizard = lazy(() => import('@/pages/setup/SetupWizard').then(m => ({ default: m.SetupWizard })))
const SetupGuide = lazy(() => import('@/pages/setup-guide/SetupGuide'))

/* Jobs v2 pages */
const JobDetail = lazy(() => import('@/pages/jobs/JobDetail'))
const JobBoard = lazy(() => import('@/pages/jobs/JobBoard'))
const JobsPage = lazy(() => import('@/pages/jobs/JobsPage'))

/* Portal pages (public, token-based) */
const PortalPage = lazy(() => import('@/pages/portal/PortalPage').then(m => ({ default: m.PortalPage })))
const PaymentSuccess = lazy(() => import('@/pages/portal/PaymentSuccess').then(m => ({ default: m.PaymentSuccess })))
const PortalSignedOut = lazy(() => import('@/pages/portal/PortalSignedOut').then(m => ({ default: m.PortalSignedOut })))
const PortalRecover = lazy(() => import('@/pages/portal/PortalRecover').then(m => ({ default: m.PortalRecover })))

/* Invoice payment page (public, token-based — lazy to keep Stripe bundles out of main chunk) */
const InvoicePaymentPage = lazy(() => import('@/pages/public/InvoicePaymentPage'))

/* Public staff roster viewer (Phase 1 task E9 — token-gated, no auth) */
const StaffRosterPublicView = lazy(() => import('@/pages/public/StaffRosterPublicView'))

/* QR payment result pages (public — rendered on customer's phone after Stripe redirect) */
const QrPaymentSuccess = lazy(() => import('@/pages/payments/QrPaymentSuccess'))
const QrPaymentCancel = lazy(() => import('@/pages/payments/QrPaymentCancel'))

/* Public marketing pages (lazy-loaded — only needed for unauthenticated visitors) */
const LandingPage = lazy(() => import('@/pages/public/LandingPage'))
const PrivacyPage = lazy(() => import('@/pages/public/PrivacyPage'))
const TradesPage = lazy(() => import('@/pages/public/TradesPage'))
const WorkshopPage = lazy(() => import('@/pages/public/WorkshopPage'))

/* Visual page editor (lazy — Puck CSS is large and admin-only) */
const PageEditorList = lazy(() => import('@/admin/page-editor/pages/PageEditorList').then(m => ({ default: m.PageEditorList })))
const PageEditorEdit = lazy(() => import('@/admin/page-editor/pages/PageEditorEdit').then(m => ({ default: m.PageEditorEdit })))
const PageEditorRedirects = lazy(() => import('@/admin/page-editor/pages/PageEditorRedirects').then(m => ({ default: m.PageEditorRedirects })))

/* Public catch-all renderer (resolves slugs against the editor backend) */
const PublicPageRenderer = lazy(() => import('@/pages/public/PublicPageRenderer').then(m => ({ default: m.PublicPageRenderer })))

/* ManagedPage wrapper — swaps in published Puck content when present, otherwise
   renders the React fallback. Lazy-loaded to keep the resolve-fetch logic and
   its (lazy) Puck dependency out of the initial chunk for routes that don't
   render published content. PERFORMANCE_AUDIT.md §F-H2. */
const ManagedPage = lazy(() => import('@/pages/public/ManagedPage').then(m => ({ default: m.ManagedPage })))

/* Catalogue pages */
const CataloguePage = lazy(() => import('@/pages/catalogue/CataloguePage'))

/* Items page */
const ItemsPage = lazy(() => import('@/pages/items/ItemsPage'))

/* Onboarding */
const OnboardingWizard = lazy(() => import('@/pages/onboarding/OnboardingWizard').then(m => ({ default: m.OnboardingWizard })))

/* Staff detail */
const StaffDetail = lazy(() => import('@/pages/staff/StaffDetail'))

/* Self-service clock-in (web) — Phase 3 D3 */
const SelfServiceClockScreen = lazy(() => import('@/pages/staff/me/SelfServiceClockScreen'))

/* Self-service Payslips (web) — Phase 4 D11 / G9 */
const MyPayslipsPage = lazy(() => import('@/pages/staff/me/MyPayslipsPage'))

/* Shift swaps + cover (Phase 3 D6) */
const ShiftSwapPage = lazy(() => import('@/pages/swaps/ShiftSwapPage'))
const ShiftCoverPage = lazy(() => import('@/pages/swaps/ShiftCoverPage'))

/* Payroll (Phase 4 D1 / D2 / D7 / D8) */
const PayRunPage = lazy(() => import('@/pages/payroll/PayRunPage'))
const PayslipDetailPage = lazy(() => import('@/pages/payroll/PayslipDetail'))

/* Payroll settings + report pages (Phase 4 D5 / D6) */
const PayPeriodsPage = lazy(() => import('@/pages/settings/people/PayPeriodsPage'))
const AllowanceTypesPage = lazy(() => import('@/pages/settings/people/AllowanceTypesPage'))
const WageVariancePage = lazy(() => import('@/pages/reports/WageVariancePage'))

/* Leave engine (Phase 2) */
const ApprovalQueue = lazy(() => import('@/pages/leave/ApprovalQueue'))

/* Franchise location detail */
const LocationDetail = lazy(() => import('@/pages/franchise/LocationDetail'))

/* Franchise transfer detail */
const TransferDetail = lazy(() => import('@/pages/franchise/TransferDetail'))

/* Kiosk (standalone, outside OrgLayout) */
const KioskPage = lazy(() => import('@/pages/kiosk/KioskPage'))

/* Accounting pages */
const ChartOfAccounts = lazy(() => import('@/pages/accounting/ChartOfAccounts'))
const JournalEntries = lazy(() => import('@/pages/accounting/JournalEntries'))
const JournalEntryDetail = lazy(() => import('@/pages/accounting/JournalEntryDetail'))
const AccountingPeriods = lazy(() => import('@/pages/accounting/AccountingPeriods'))

/* Financial report pages */
const ProfitAndLoss = lazy(() => import('@/pages/reports/ProfitAndLoss'))
const BalanceSheet = lazy(() => import('@/pages/reports/BalanceSheet'))
const AgedReceivables = lazy(() => import('@/pages/reports/AgedReceivables'))

/* Banking pages */
const BankAccounts = lazy(() => import('@/pages/banking/BankAccounts'))
const BankTransactions = lazy(() => import('@/pages/banking/BankTransactions'))
const ReconciliationDashboard = lazy(() => import('@/pages/banking/ReconciliationDashboard'))

/* GST / Tax pages */
const GstPeriods = lazy(() => import('@/pages/tax/GstPeriods'))
const GstFilingDetail = lazy(() => import('@/pages/tax/GstFilingDetail'))
const TaxWallets = lazy(() => import('@/pages/tax/TaxWallets'))
const TaxPosition = lazy(() => import('@/pages/tax/TaxPosition'))

/* Branch management pages */
const BranchStockTransfers = lazy(() => import('@/pages/inventory/StockTransfers'))
const StaffSchedule = lazy(() => import('@/pages/scheduling/StaffSchedule'))
const GlobalBranchOverview = lazy(() => import('@/pages/admin/GlobalBranchOverview'))

/* Claims pages */
const ClaimsList = lazy(() => import('@/pages/claims/ClaimsList'))
const ClaimDetail = lazy(() => import('@/pages/claims/ClaimDetail'))
const ClaimCreateForm = lazy(() => import('@/pages/claims/ClaimCreateForm'))
const ClaimsReports = lazy(() => import('@/pages/claims/ClaimsReports'))

/* Fleet Portal Admin (workshop-staff view — module-gated) */
const FleetPortalAdmin = lazy(() => import('@/fleet-portal-admin/pages/FleetPortalAdminDashboard'))
const FleetPortalAdminBookings = lazy(() => import('@/fleet-portal-admin/pages/BookingQueue'))
const FleetPortalAdminQuotes = lazy(() => import('@/fleet-portal-admin/pages/QuoteQueue'))
const FleetPortalAdminAccountDetail = lazy(() => import('@/fleet-portal-admin/pages/AccountDetail'))
const FleetPortalAdminSecuritySettings = lazy(() => import('@/fleet-portal-admin/pages/SecuritySettings'))
const FleetPortalAdminAccountsList = lazy(() => import('@/fleet-portal-admin/pages/AccountsList'))
const FleetPortalAdminFailures = lazy(() => import('@/fleet-portal-admin/pages/ChecklistFailures'))

function LazyFallback() {
  return (
    <div className="flex items-center justify-center p-8">
      <Spinner size="lg" label="Loading page" />
    </div>
  )
}

/** Wrap a lazy-loaded page with Suspense + page-level error boundary */
function SafePage({ children, name }: { children: React.ReactNode; name?: string }) {
  return (
    <ErrorBoundary level="page" name={name ?? 'page'}>
      <Suspense fallback={<LazyFallback />}>
        {children}
      </Suspense>
    </ErrorBoundary>
  )
}

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

/** Redirect branch_admin users away from org-level settings to /dashboard */
function RequireOrgAdmin() {
  const { isBranchAdmin } = useAuth()
  if (isBranchAdmin) return <Navigate to="/dashboard" replace />
  return <Outlet />
}

function RequireAutomotive() {
  const { tradeFamily } = useTenant()
  const isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'
  if (!isAutomotive) return <Navigate to="/dashboard" replace />
  return <Outlet />
}

/* ── Route wrappers for components that expect props instead of useParams ── */
function ProjectDashboardRoute() {
  const { id } = useParams<{ id: string }>()
  return <ProjectDashboard projectId={id!} />
}

function AssetDetailRoute() {
  const { id } = useParams<{ id: string }>()
  return <AssetDetail assetId={id!} />
}

function JobDetailRoute() {
  const { id } = useParams<{ id: string }>()
  return <JobDetail jobId={id!} />
}

function StaffDetailRoute() {
  const { id } = useParams<{ id: string }>()
  return <StaffDetail staffId={id!} />
}

function LocationDetailRoute() {
  const { id } = useParams<{ id: string }>()
  return <LocationDetail locationId={id!} />
}

function TransferDetailRoute() {
  const { id } = useParams<{ id: string }>()
  return <TransferDetail transferId={id!} />
}

function AppRoutes() {
  const { isGlobalAdmin, isKiosk } = useAuth()

  return (
    <Routes>
      {/* Public pages — accessible regardless of auth state.
          Each hand-coded page is wrapped in <ManagedPage>, which transparently
          swaps in published Puck content from the visual page editor when present
          (Requirement 14.4, 14.5) and falls back to the original React component
          otherwise. */}
      <Route path="/privacy" element={<SafePage name="privacy"><ManagedPage page_key="privacy"><PrivacyPage /></ManagedPage></SafePage>} />
      <Route path="/trades" element={<SafePage name="trades"><ManagedPage page_key="trades"><TradesPage /></ManagedPage></SafePage>} />
      <Route path="/workshop" element={<SafePage name="workshop"><ManagedPage page_key="workshop"><WorkshopPage /></ManagedPage></SafePage>} />
      {/* SEO: /mechanics and /garage are alias routes that redirect to the
          canonical /workshop URL. This consolidates link-equity to a single
          URL (plus the <link rel="canonical"> on WorkshopPage itself). */}
      <Route path="/mechanics" element={<Navigate to="/workshop" replace />} />
      <Route path="/garage" element={<Navigate to="/workshop" replace />} />

      {/* Guest routes — authenticated users are redirected by role.
          The landing page is publicly indexable; all auth-related pages
          must be marked noindex to keep them out of search results. */}
      <Route element={<GuestOnly />}>
        <Route path="/" element={<SafePage name="landing"><ManagedPage page_key="landing"><LandingPage /></ManagedPage></SafePage>} />
        <Route element={<NoIndexRoute />}>
          <Route path="/login" element={<SafePage name="login"><Login /></SafePage>} />
          <Route path="/mfa-verify" element={<SafePage name="mfa-verify"><MfaVerify /></SafePage>} />
          <Route path="/forgot-password" element={<SafePage name="forgot-password"><PasswordResetRequest /></SafePage>} />
          <Route path="/reset-password" element={<SafePage name="reset-password"><PasswordResetComplete /></SafePage>} />
          <Route path="/signup" element={<SafePage name="signup"><LazySignup /></SafePage>} />
          <Route path="/verify-email" element={<SafePage name="verify-email"><VerifyEmail /></SafePage>} />
        </Route>
      </Route>

      {/* Global admin routes */}
      <Route element={<RequireAuth />}>
        <Route element={<RequireGlobalAdmin />}>
          <Route path="/admin" element={<AdminLayout />}>
            <Route path="dashboard" element={<SafePage name="admin-dashboard"><Dashboard /></SafePage>} />
            <Route path="organisations/:orgId" element={<SafePage name="admin-org-detail"><OrganisationDetail /></SafePage>} />
            <Route path="organisations" element={<SafePage name="admin-organisations"><Organisations /></SafePage>} />
            <Route path="users" element={<SafePage name="admin-users"><UserManagement /></SafePage>} />
            <Route path="plans" element={<SafePage name="admin-plans"><SubscriptionPlans /></SafePage>} />
            <Route path="feature-flags" element={<SafePage name="admin-feature-flags"><FeatureFlags /></SafePage>} />
            <Route path="analytics" element={<SafePage name="admin-analytics"><AnalyticsDashboard /></SafePage>} />
            <Route path="settings" element={<SafePage name="admin-settings"><AdminSettings /></SafePage>} />
            <Route path="security" element={<SafePage name="admin-security"><AdminSecurityPage /></SafePage>} />
            <Route path="errors" element={<SafePage name="admin-errors"><ErrorLog /></SafePage>} />
            <Route path="notifications" element={<SafePage name="admin-notifications"><NotificationManager /></SafePage>} />
            <Route path="branding" element={<SafePage name="admin-branding"><BrandingConfig /></SafePage>} />
            <Route path="migration" element={<SafePage name="admin-migration"><MigrationTool /></SafePage>} />
            <Route path="live-migration" element={<SafePage name="admin-live-migration"><LiveMigrationTool /></SafePage>} />
            <Route path="ha-replication" element={<SafePage name="admin-ha-replication"><HAReplication /></SafePage>} />
            <Route path="audit-log" element={<SafePage name="admin-audit-log"><AuditLog /></SafePage>} />
            <Route path="reports" element={<SafePage name="admin-reports"><AdminReports /></SafePage>} />
            <Route path="integrations" element={<SafePage name="admin-integrations"><Integrations /></SafePage>} />
            <Route path="trade-families" element={<SafePage name="admin-trade-families"><TradeFamilies /></SafePage>} />
            <Route path="branches" element={<SafePage name="admin-branches"><GlobalBranchOverview /></SafePage>} />
            <Route path="profile" element={<SafePage name="admin-profile"><GlobalAdminProfile /></SafePage>} />
            {/* Visual page editor (global_admin only — Requirement 13.1) */}
            <Route path="page-editor" element={<SafePage name="page-editor-list"><PageEditorList /></SafePage>} />
            <Route path="page-editor/redirects" element={<SafePage name="page-editor-redirects"><PageEditorRedirects /></SafePage>} />
            <Route path="page-editor/:pageKey" element={<SafePage name="page-editor-edit"><PageEditorEdit /></SafePage>} />
            <Route index element={<Navigate to="dashboard" replace />} />
          </Route>
        </Route>

        {/* Org-level routes */}
        <Route element={<OrgLayout />}>
          <Route
            path="/dashboard"
            element={isKiosk ? <Navigate to="/kiosk" replace /> : isGlobalAdmin && !sessionStorage.getItem('admin_view_as_org') ? <Navigate to="/admin/dashboard" replace /> : <SafePage name="dashboard"><Dashboard /></SafePage>}
          />

          {/* Customers */}
          <Route path="/customers" element={<SafePage name="customers"><CustomerList /></SafePage>} />
          <Route path="/customers/new" element={<SafePage name="customer-create"><CustomerCreate /></SafePage>} />
          <Route path="/customers/:id" element={<SafePage name="customer-profile"><CustomerProfile /></SafePage>} />

          {/* Vehicles */}
          <Route element={<RequireAutomotive />}>
            <Route path="/vehicles" element={<SafePage name="vehicles"><ModuleRoute moduleSlug="vehicles"><VehicleList /></ModuleRoute></SafePage>} />
            <Route path="/vehicles/:id" element={<SafePage name="vehicle-profile"><ModuleRoute moduleSlug="vehicles"><VehicleProfile /></ModuleRoute></SafePage>} />
          </Route>

          {/* PPSR */}
          <Route path="/ppsr/search" element={<SafePage name="ppsr-search"><ModuleRoute moduleSlug="ppsr"><PPSRSearchPage /></ModuleRoute></SafePage>} />

          {/* Invoices */}
          <Route path="/invoices" element={<SafePage name="invoices"><InvoiceList /></SafePage>} />
          <Route path="/invoices/new" element={<SafePage name="invoice-create"><InvoiceList /></SafePage>} />
          <Route path="/invoices/:id/edit" element={<SafePage name="invoice-edit"><InvoiceCreate /></SafePage>} />
          <Route path="/invoices/:id" element={<SafePage name="invoice-detail"><InvoiceList /></SafePage>} />

          {/* Quotes */}
          <Route path="/quotes" element={<SafePage name="quotes"><ModuleRoute moduleSlug="quotes"><QuoteList /></ModuleRoute></SafePage>} />
          <Route path="/quotes/new" element={<SafePage name="quote-create"><ModuleRoute moduleSlug="quotes"><QuoteList /></ModuleRoute></SafePage>} />
          <Route path="/quotes/:id/edit" element={<SafePage name="quote-edit"><ModuleRoute moduleSlug="quotes"><QuoteCreate /></ModuleRoute></SafePage>} />
          <Route path="/quotes/:id" element={<SafePage name="quote-detail"><ModuleRoute moduleSlug="quotes"><QuoteList /></ModuleRoute></SafePage>} />

          {/* Job Cards */}
          <Route path="/job-cards" element={<SafePage name="job-cards"><ModuleRoute moduleSlug="jobs"><JobCardList /></ModuleRoute></SafePage>} />
          <Route path="/job-cards/new" element={<SafePage name="job-card-create"><ModuleRoute moduleSlug="jobs"><JobCardCreate /></ModuleRoute></SafePage>} />
          <Route path="/job-cards/:id" element={<SafePage name="job-card-detail"><ModuleRoute moduleSlug="jobs"><JobCardDetail /></ModuleRoute></SafePage>} />

          {/* Bookings */}
          <Route path="/bookings" element={<SafePage name="bookings"><ModuleRoute moduleSlug="bookings"><BookingCalendarPage /></ModuleRoute></SafePage>} />

          {/* Inventory */}
          <Route path="/inventory" element={<SafePage name="inventory"><ModuleRoute moduleSlug="inventory"><InventoryPage /></ModuleRoute></SafePage>} />

          {/* Reports */}
          <Route path="/reports" element={<SafePage name="reports"><ReportsPage /></SafePage>} />

          {/* Settings (org_admin only — branch_admin redirected to /dashboard) */}
          <Route element={<RequireOrgAdmin />}>
            <Route path="/settings" element={<SafePage name="settings"><OrgSettingsPage /></SafePage>} />
            <Route path="/settings/online-payments" element={<SafePage name="online-payments-settings"><OnlinePaymentsSettings /></SafePage>} />
            <Route path="/settings/people/pay-periods" element={<SafePage name="pay-periods-settings"><ModuleRoute moduleSlug="payroll"><PayPeriodsPage /></ModuleRoute></SafePage>} />
            <Route path="/settings/people/allowance-types" element={<SafePage name="allowance-types-settings"><ModuleRoute moduleSlug="payroll"><AllowanceTypesPage /></ModuleRoute></SafePage>} />
          </Route>

          {/* Notifications */}
          <Route path="/notifications/inbox" element={<SafePage name="notifications-inbox"><InboxPage /></SafePage>} />
          <Route path="/notifications" element={<SafePage name="notifications"><NotificationsPage /></SafePage>} />

          {/* Staff */}
          <Route path="/staff" element={<SafePage name="staff"><ModuleRoute moduleSlug="staff"><StaffList /></ModuleRoute></SafePage>} />

          {/* Leave engine (Phase 2) — approval queue is module-gated by
              staff_management. The backend scopes the queue per role
              (org_admin sees all; branch_admin scoped via location
              assignments; managers scoped via reporting_to). Salespeople
              with no managed staff get an empty list. */}
          <Route path="/leave/approvals" element={<SafePage name="leave-approvals"><ModuleRoute moduleSlug="staff_management"><ApprovalQueue /></ModuleRoute></SafePage>} />

          {/* Projects */}
          <Route path="/projects" element={<SafePage name="projects"><ModuleRoute moduleSlug="projects"><ProjectList /></ModuleRoute></SafePage>} />
          <Route path="/projects/:id" element={<SafePage name="project-detail"><ModuleRoute moduleSlug="projects"><ProjectDashboardRoute /></ModuleRoute></SafePage>} />

          {/* Expenses */}
          <Route path="/expenses" element={<SafePage name="expenses"><ModuleRoute moduleSlug="expenses"><ExpenseList /></ModuleRoute></SafePage>} />

          {/* Accounting */}
          <Route path="/accounting" element={<SafePage name="chart-of-accounts"><ModuleRoute moduleSlug="accounting"><ChartOfAccounts /></ModuleRoute></SafePage>} />
          <Route path="/accounting/journal-entries" element={<SafePage name="journal-entries"><ModuleRoute moduleSlug="accounting"><JournalEntries /></ModuleRoute></SafePage>} />
          <Route path="/accounting/journal-entries/:id" element={<SafePage name="journal-entry-detail"><ModuleRoute moduleSlug="accounting"><JournalEntryDetail /></ModuleRoute></SafePage>} />
          <Route path="/accounting/periods" element={<SafePage name="accounting-periods"><ModuleRoute moduleSlug="accounting"><AccountingPeriods /></ModuleRoute></SafePage>} />

          {/* Financial Reports (accounting module) */}
          <Route path="/reports/profit-loss" element={<SafePage name="profit-and-loss"><ModuleRoute moduleSlug="accounting"><ProfitAndLoss /></ModuleRoute></SafePage>} />
          <Route path="/reports/balance-sheet" element={<SafePage name="balance-sheet"><ModuleRoute moduleSlug="accounting"><BalanceSheet /></ModuleRoute></SafePage>} />
          <Route path="/reports/aged-receivables" element={<SafePage name="aged-receivables"><ModuleRoute moduleSlug="accounting"><AgedReceivables /></ModuleRoute></SafePage>} />

          {/* Payroll Reports (Phase 4 D6) */}
          <Route path="/reports/wage-variance" element={<SafePage name="wage-variance"><ModuleRoute moduleSlug="payroll"><WageVariancePage /></ModuleRoute></SafePage>} />

          {/* GST / Tax */}
          <Route path="/tax/gst-periods" element={<SafePage name="gst-periods"><ModuleRoute moduleSlug="accounting"><GstPeriods /></ModuleRoute></SafePage>} />
          <Route path="/tax/gst-periods/:id" element={<SafePage name="gst-filing-detail"><ModuleRoute moduleSlug="accounting"><GstFilingDetail /></ModuleRoute></SafePage>} />
          <Route path="/tax/wallets" element={<SafePage name="tax-wallets"><ModuleRoute moduleSlug="accounting"><TaxWallets /></ModuleRoute></SafePage>} />
          <Route path="/tax/position" element={<SafePage name="tax-position"><ModuleRoute moduleSlug="accounting"><TaxPosition /></ModuleRoute></SafePage>} />

          {/* Banking */}
          <Route path="/banking/accounts" element={<SafePage name="bank-accounts"><ModuleRoute moduleSlug="accounting"><BankAccounts /></ModuleRoute></SafePage>} />
          <Route path="/banking/transactions" element={<SafePage name="bank-transactions"><ModuleRoute moduleSlug="accounting"><BankTransactions /></ModuleRoute></SafePage>} />
          <Route path="/banking/reconciliation" element={<SafePage name="reconciliation-dashboard"><ModuleRoute moduleSlug="accounting"><ReconciliationDashboard /></ModuleRoute></SafePage>} />

          {/* Time Tracking */}
          <Route path="/time-tracking" element={<SafePage name="time-tracking"><ModuleRoute moduleSlug="time_tracking"><TimeSheet /></ModuleRoute></SafePage>} />

          {/* POS */}
          <Route path="/pos" element={<SafePage name="pos"><ModuleRoute moduleSlug="pos"><POSScreen /></ModuleRoute></SafePage>} />

          {/* Schedule */}
          <Route path="/schedule" element={<SafePage name="schedule"><ModuleRoute moduleSlug="scheduling"><ScheduleCalendar /></ModuleRoute></SafePage>} />
          <Route path="/staff-schedule/grid" element={<SafePage name="roster-grid"><ModuleRoute moduleSlug="scheduling"><RosterGridPage /></ModuleRoute></SafePage>} />

          {/* Recurring Invoices */}
          <Route path="/recurring" element={<SafePage name="recurring"><ModuleRoute moduleSlug="recurring_invoices"><RecurringList /></ModuleRoute></SafePage>} />

          {/* Purchase Orders */}
          <Route path="/purchase-orders" element={<SafePage name="purchase-orders"><ModuleRoute moduleSlug="purchase_orders"><POList /></ModuleRoute></SafePage>} />
          <Route path="/purchase-orders/:id" element={<SafePage name="po-detail"><ModuleRoute moduleSlug="purchase_orders"><PODetail /></ModuleRoute></SafePage>} />

          {/* Data Import/Export */}
          <Route path="/data" element={<SafePage name="data"><DataPage /></SafePage>} />

          {/* Construction */}
          <Route path="/progress-claims" element={<SafePage name="progress-claims"><ModuleRoute moduleSlug="progress_claims"><ProgressClaimList /></ModuleRoute></SafePage>} />
          <Route path="/variations" element={<SafePage name="variations"><ModuleRoute moduleSlug="variations"><VariationList /></ModuleRoute></SafePage>} />
          <Route path="/retentions" element={<SafePage name="retentions"><ModuleRoute moduleSlug="retentions"><RetentionSummary /></ModuleRoute></SafePage>} />

          {/* Floor Plan / Tables */}
          <Route path="/floor-plan" element={<SafePage name="floor-plan"><ModuleRoute moduleSlug="tables"><FloorPlan /></ModuleRoute></SafePage>} />

          {/* Kitchen Display */}
          <Route path="/kitchen" element={<SafePage name="kitchen"><ModuleRoute moduleSlug="kitchen_display"><KitchenDisplay /></ModuleRoute></SafePage>} />

          {/* Franchise */}
          <Route path="/franchise" element={<SafePage name="franchise"><ModuleRoute moduleSlug="franchise"><FranchiseDashboard /></ModuleRoute></SafePage>} />
          <Route path="/locations" element={<SafePage name="locations"><ModuleRoute moduleSlug="franchise"><LocationList /></ModuleRoute></SafePage>} />
          <Route path="/stock-transfers" element={<SafePage name="stock-transfers"><ModuleRoute moduleSlug="franchise"><StockTransfers /></ModuleRoute></SafePage>} />
          <Route path="/stock-transfers/:id" element={<SafePage name="transfer-detail"><ModuleRoute moduleSlug="franchise"><TransferDetailRoute /></ModuleRoute></SafePage>} />

          {/* Branch Stock Transfers */}
          <Route path="/branch-transfers" element={<SafePage name="branch-transfers"><ModuleRoute moduleSlug="branch_management"><BranchStockTransfers /></ModuleRoute></SafePage>} />

          {/* Claims */}
          <Route path="/claims" element={<SafePage name="claims"><ModuleRoute moduleSlug="customer_claims"><ClaimsList /></ModuleRoute></SafePage>} />
          <Route path="/claims/new" element={<SafePage name="claim-create"><ModuleRoute moduleSlug="customer_claims"><ClaimCreateForm /></ModuleRoute></SafePage>} />
          <Route path="/claims/reports" element={<SafePage name="claims-reports"><ModuleRoute moduleSlug="customer_claims"><ClaimsReports /></ModuleRoute></SafePage>} />
          <Route path="/claims/:id" element={<SafePage name="claim-detail"><ModuleRoute moduleSlug="customer_claims"><ClaimDetail /></ModuleRoute></SafePage>} />

          {/* Fleet Portal Admin (workshop-staff view of fleet portal activity) */}
          <Route element={<RequireOrgAdmin />}>
            <Route path="/fleet-portal-admin" element={<SafePage name="fleet-portal-admin"><ModuleRoute moduleSlug="b2b-fleet-management"><FleetPortalAdmin /></ModuleRoute></SafePage>} />
            <Route path="/fleet-portal-admin/bookings" element={<SafePage name="fleet-portal-admin-bookings"><ModuleRoute moduleSlug="b2b-fleet-management"><FleetPortalAdminBookings /></ModuleRoute></SafePage>} />
            <Route path="/fleet-portal-admin/quotes" element={<SafePage name="fleet-portal-admin-quotes"><ModuleRoute moduleSlug="b2b-fleet-management"><FleetPortalAdminQuotes /></ModuleRoute></SafePage>} />
            <Route path="/fleet-portal-admin/accounts" element={<SafePage name="fleet-portal-admin-accounts"><ModuleRoute moduleSlug="b2b-fleet-management"><FleetPortalAdminAccountsList /></ModuleRoute></SafePage>} />
            <Route path="/fleet-portal-admin/accounts/:accountId" element={<SafePage name="fleet-portal-admin-account"><ModuleRoute moduleSlug="b2b-fleet-management"><FleetPortalAdminAccountDetail /></ModuleRoute></SafePage>} />
            <Route path="/fleet-portal-admin/checklist-failures" element={<SafePage name="fleet-portal-admin-failures"><ModuleRoute moduleSlug="b2b-fleet-management"><FleetPortalAdminFailures /></ModuleRoute></SafePage>} />
            <Route path="/fleet-portal-admin/settings" element={<SafePage name="fleet-portal-admin-settings"><ModuleRoute moduleSlug="b2b-fleet-management"><FleetPortalAdminSecuritySettings /></ModuleRoute></SafePage>} />
          </Route>

          {/* Staff Schedule (branch-scoped) */}
          <Route path="/staff-schedule" element={<SafePage name="staff-schedule"><ModuleRoute moduleSlug="branch_management"><StaffSchedule /></ModuleRoute></SafePage>} />

          {/* Assets */}
          <Route path="/assets" element={<SafePage name="assets"><ModuleRoute moduleSlug="assets"><AssetList /></ModuleRoute></SafePage>} />
          <Route path="/assets/:id" element={<SafePage name="asset-detail"><ModuleRoute moduleSlug="assets"><AssetDetailRoute /></ModuleRoute></SafePage>} />

          {/* Compliance */}
          <Route path="/compliance" element={<SafePage name="compliance"><ModuleRoute moduleSlug="compliance_docs"><ComplianceDashboard /></ModuleRoute></SafePage>} />

          {/* Loyalty */}
          <Route path="/loyalty" element={<SafePage name="loyalty"><ModuleRoute moduleSlug="loyalty"><LoyaltyConfig /></ModuleRoute></SafePage>} />

          {/* Ecommerce */}
          <Route path="/ecommerce" element={<SafePage name="ecommerce"><ModuleRoute moduleSlug="ecommerce"><WooCommerceSetup /></ModuleRoute></SafePage>} />

          {/* Setup Wizard */}
          <Route path="/setup" element={<SafePage name="setup"><SetupWizard /></SafePage>} />

          {/* Setup Guide */}
          <Route path="/setup-guide" element={<SafePage name="setup-guide"><SetupGuide /></SafePage>} />

          {/* Jobs v2 */}
          <Route path="/jobs" element={<SafePage name="jobs"><ModuleRoute moduleSlug="jobs"><JobsPage /></ModuleRoute></SafePage>} />
          <Route path="/jobs/board" element={<SafePage name="job-board"><ModuleRoute moduleSlug="jobs"><JobBoard /></ModuleRoute></SafePage>} />
          <Route path="/jobs/:id" element={<SafePage name="job-detail"><ModuleRoute moduleSlug="jobs"><JobDetailRoute /></ModuleRoute></SafePage>} />

          {/* Items */}
          <Route path="/items" element={<SafePage name="items"><ModuleRoute moduleSlug="inventory"><ItemsPage /></ModuleRoute></SafePage>} />

          {/* Catalogue */}
          <Route path="/catalogue" element={<SafePage name="catalogue"><ModuleRoute moduleSlug="inventory"><CataloguePage /></ModuleRoute></SafePage>} />

          {/* Onboarding */}
          <Route path="/onboarding" element={<SafePage name="onboarding"><OnboardingWizard /></SafePage>} />

          {/* Staff detail */}
          <Route path="/staff/:id" element={<SafePage name="staff-detail"><ModuleRoute moduleSlug="staff"><StaffDetailRoute /></ModuleRoute></SafePage>} />

          {/* Self-service clock-in (Phase 3 D3) — gated server-side by self_service_clock_enabled */}
          <Route path="/staff/me/clock" element={<SafePage name="self-service-clock"><ModuleRoute moduleSlug="staff_management"><SelfServiceClockScreen /></ModuleRoute></SafePage>} />

          {/* Self-service payslips (Phase 4 D11 / G9) — server enforces ownership via staff_members.user_id */}
          <Route path="/staff/me/payslips" element={<SafePage name="my-payslips"><ModuleRoute moduleSlug="payroll"><MyPayslipsPage /></ModuleRoute></SafePage>} />

          {/* Shift swaps + open-shift cover (Phase 3 D6) */}
          <Route path="/shift-swaps" element={<SafePage name="shift-swaps"><ModuleRoute moduleSlug="staff_management"><ShiftSwapPage /></ModuleRoute></SafePage>} />
          <Route path="/shift-cover" element={<SafePage name="shift-cover"><ModuleRoute moduleSlug="staff_management"><ShiftCoverPage /></ModuleRoute></SafePage>} />

          {/* Payroll (Phase 4 D1 / D2 / D7 / D8) */}
          <Route path="/payroll/run" element={<SafePage name="payroll-run"><ModuleRoute moduleSlug="payroll"><PayRunPage /></ModuleRoute></SafePage>} />
          <Route path="/payroll/payslips/:id" element={<SafePage name="payslip-detail"><ModuleRoute moduleSlug="payroll"><PayslipDetailPage /></ModuleRoute></SafePage>} />

          {/* Franchise location detail */}
          <Route path="/locations/:id" element={<SafePage name="location-detail"><ModuleRoute moduleSlug="franchise"><LocationDetailRoute /></ModuleRoute></SafePage>} />

          {/* No internal catch-all here — unknown paths fall through to the
              top-level public catch-all (PublicPageRenderer) so editor-created
              pages can serve every visitor regardless of auth state.
              See the bottom of <Routes> for the public catch-all. */}
        </Route>
      </Route>

      {/* Kiosk (standalone, outside OrgLayout) — noindex */}
      <Route element={<RequireAuth />}>
        <Route element={<NoIndexRoute />}>
          <Route path="/kiosk" element={<SafePage name="kiosk"><KioskPage /></SafePage>} />
        </Route>
      </Route>

      {/* Customer portal (public, token-based access) — noindex, tokens should
          never be crawled or indexed. */}
      <Route element={<NoIndexRoute />}>
        <Route path="/portal/signed-out" element={<SafePage name="portal-signed-out"><PortalSignedOut /></SafePage>} />
        <Route path="/portal/recover" element={<SafePage name="portal-recover"><PortalRecover /></SafePage>} />
        <Route path="/portal/:token/payment-success" element={<SafePage name="payment-success"><PaymentSuccess /></SafePage>} />
        <Route path="/portal/:token" element={<SafePage name="portal"><PortalPage /></SafePage>} />

        {/* Invoice payment page (public, token-based access — Stripe Elements) */}
        <Route path="/pay/:token" element={<SafePage name="invoice-payment"><InvoicePaymentPage /></SafePage>} />

        {/* Public staff roster viewer (Phase 1 E9 — token-gated, no auth, R9.4) */}
        <Route path="/public/staff-roster/:token" element={<SafePage name="staff-roster-public"><StaffRosterPublicView /></SafePage>} />

        {/* QR payment result pages (public — customer's phone after Stripe Checkout redirect) */}
        <Route path="/payments/qr-success" element={<SafePage name="qr-payment-success"><QrPaymentSuccess /></SafePage>} />
        <Route path="/payments/qr-cancel" element={<SafePage name="qr-payment-cancel"><QrPaymentCancel /></SafePage>} />
      </Route>

      {/* Public catch-all — resolves the path against editor_pages /
          editor_page_redirects via the backend. Renders published Puck
          content, follows redirects, or shows the 404 page when no
          slug matches. Must remain the LAST route so it only fires
          when no explicit route matched. (Requirement 7.2, 14.5) */}
      <Route
        path="*"
        element={<SafePage name="public-page-renderer"><PublicPageRenderer /></SafePage>}
      />
    </Routes>
  )
}

function App() {
  // Fleet Portal — short-circuit to its own provider tree when the
  // request is for /fleet/* or a fleet.<domain> host. The staff
  // AuthProvider / OrgLayout are never instantiated for these requests
  // (Req 2.2, 2.7).
  if (isFleetPortalRoute()) {
    return (
      <ErrorBoundary level="app" name="fleet-portal-root">
        <BrowserRouter>
          <ThemeProvider>
            <FleetPortalRouter />
          </ThemeProvider>
        </BrowserRouter>
      </ErrorBoundary>
    )
  }

  return (
    <ErrorBoundary level="app" name="root">
      <BrowserRouter>
        <LocaleProvider>
          <PlatformBrandingProvider>
            <ThemeProvider>
            <AuthProvider>
              <TenantProvider>
                <ModuleProvider>
                  <FeatureFlagProvider>
                    <BranchProvider>
                    <AppRoutes />
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
