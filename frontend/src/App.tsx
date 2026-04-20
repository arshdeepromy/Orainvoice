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
import { Dashboard } from '@/pages/dashboard'

/* ── Admin pages (eagerly loaded — small set) ── */
import { Organisations } from '@/pages/admin/Organisations'
import { AnalyticsDashboard } from '@/pages/admin/AnalyticsDashboard'
import { Settings as AdminSettings } from '@/pages/admin/Settings'
import { ErrorLog } from '@/pages/admin/ErrorLog'
import NotificationManager from '@/pages/admin/NotificationManager'
import { BrandingConfig } from '@/pages/admin/BrandingConfig'
import { MigrationTool } from '@/pages/admin/MigrationTool'
import { LiveMigrationTool } from '@/pages/admin/LiveMigrationTool'
import { HAReplication } from '@/pages/admin/HAReplication'
import { AuditLog } from '@/pages/admin/AuditLog'
import { Reports as AdminReports } from '@/pages/admin/Reports'
import { Integrations } from '@/pages/admin/Integrations'
import { UserManagement } from '@/pages/admin/UserManagement'
import { SubscriptionPlans } from '@/pages/admin/SubscriptionPlans'
import { FeatureFlags } from '@/pages/admin/FeatureFlags'
import { GlobalAdminProfile } from '@/pages/admin/GlobalAdminProfile'
import TradeFamilies from '@/pages/admin/TradeFamilies'
import { AdminSecurityPage } from '@/pages/admin/AdminSecurityPage'
import { OrganisationDetail } from '@/pages/admin/OrganisationDetail'

/* ── Org pages (lazy loaded) ── */
const CustomerList = lazy(() => import('@/pages/customers/CustomerList'))
const CustomerCreate = lazy(() => import('@/pages/customers/CustomerCreate'))
const CustomerProfile = lazy(() => import('@/pages/customers/CustomerProfile'))
const VehicleList = lazy(() => import('@/pages/vehicles/VehicleList'))
const VehicleProfile = lazy(() => import('@/pages/vehicles/VehicleProfile'))
const InvoiceList = lazy(() => import('@/pages/invoices/InvoiceList'))
const InvoiceCreate = lazy(() => import('@/pages/invoices/InvoiceCreate'))
const QuoteList = lazy(() => import('@/pages/quotes/QuoteList'))
const QuoteCreate = lazy(() => import('@/pages/quotes/QuoteCreate'))
const QuoteDetail = lazy(() => import('@/pages/quotes/QuoteDetail'))
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

/* Extended org pages */
const StaffList = lazy(() => import('@/pages/staff/StaffList'))
const ProjectList = lazy(() => import('@/pages/projects/ProjectList'))
const ProjectDashboard = lazy(() => import('@/pages/projects/ProjectDashboard'))
const ExpenseList = lazy(() => import('@/pages/expenses/ExpenseList'))
const TimeSheet = lazy(() => import('@/pages/time-tracking/TimeSheet'))
const POSScreen = lazy(() => import('@/pages/pos/POSScreen'))
const ScheduleCalendar = lazy(() => import('@/pages/schedule/ScheduleCalendar'))
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

/* Jobs v2 pages */
const JobDetail = lazy(() => import('@/pages/jobs/JobDetail'))
const JobBoard = lazy(() => import('@/pages/jobs/JobBoard'))
const JobsPage = lazy(() => import('@/pages/jobs/JobsPage'))

/* Portal pages (public, token-based) */
const PortalPage = lazy(() => import('@/pages/portal/PortalPage').then(m => ({ default: m.PortalPage })))

/* Invoice payment page (public, token-based — lazy to keep Stripe bundles out of main chunk) */
const InvoicePaymentPage = lazy(() => import('@/pages/public/InvoicePaymentPage'))

/* Catalogue pages */
const CataloguePage = lazy(() => import('@/pages/catalogue/CataloguePage'))

/* Items page */
const ItemsPage = lazy(() => import('@/pages/items/ItemsPage'))

/* Onboarding */
const OnboardingWizard = lazy(() => import('@/pages/onboarding/OnboardingWizard').then(m => ({ default: m.OnboardingWizard })))

/* Staff detail */
const StaffDetail = lazy(() => import('@/pages/staff/StaffDetail'))

/* Franchise location detail */
const LocationDetail = lazy(() => import('@/pages/franchise/LocationDetail'))

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
function QuoteDetailRoute() {
  const { id } = useParams<{ id: string }>()
  return <QuoteDetail quoteId={id!} />
}

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

function AppRoutes() {
  const { isGlobalAdmin, isKiosk, isAuthenticated } = useAuth()

  return (
    <Routes>
      {/* Guest routes */}
      <Route element={<GuestOnly />}>
        <Route path="/login" element={<SafePage name="login"><Login /></SafePage>} />
        <Route path="/mfa-verify" element={<SafePage name="mfa-verify"><MfaVerify /></SafePage>} />
        <Route path="/forgot-password" element={<SafePage name="forgot-password"><PasswordResetRequest /></SafePage>} />
        <Route path="/reset-password" element={<SafePage name="reset-password"><PasswordResetComplete /></SafePage>} />
        <Route path="/signup" element={<SafePage name="signup"><LazySignup /></SafePage>} />
        <Route path="/verify-email" element={<SafePage name="verify-email"><VerifyEmail /></SafePage>} />
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

          {/* Invoices */}
          <Route path="/invoices" element={<SafePage name="invoices"><InvoiceList /></SafePage>} />
          <Route path="/invoices/new" element={<SafePage name="invoice-create"><InvoiceList /></SafePage>} />
          <Route path="/invoices/:id/edit" element={<SafePage name="invoice-edit"><InvoiceCreate /></SafePage>} />
          <Route path="/invoices/:id" element={<SafePage name="invoice-detail"><InvoiceList /></SafePage>} />

          {/* Quotes */}
          <Route path="/quotes" element={<SafePage name="quotes"><ModuleRoute moduleSlug="quotes"><QuoteList /></ModuleRoute></SafePage>} />
          <Route path="/quotes/new" element={<SafePage name="quote-create"><ModuleRoute moduleSlug="quotes"><QuoteCreate /></ModuleRoute></SafePage>} />
          <Route path="/quotes/:id/edit" element={<SafePage name="quote-edit"><ModuleRoute moduleSlug="quotes"><QuoteCreate /></ModuleRoute></SafePage>} />
          <Route path="/quotes/:id" element={<SafePage name="quote-detail"><ModuleRoute moduleSlug="quotes"><QuoteDetailRoute /></ModuleRoute></SafePage>} />

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
          </Route>

          {/* Notifications */}
          <Route path="/notifications" element={<SafePage name="notifications"><NotificationsPage /></SafePage>} />

          {/* Staff */}
          <Route path="/staff" element={<SafePage name="staff"><ModuleRoute moduleSlug="staff"><StaffList /></ModuleRoute></SafePage>} />

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

          {/* Branch Stock Transfers */}
          <Route path="/branch-transfers" element={<SafePage name="branch-transfers"><ModuleRoute moduleSlug="branch_management"><BranchStockTransfers /></ModuleRoute></SafePage>} />

          {/* Claims */}
          <Route path="/claims" element={<SafePage name="claims"><ModuleRoute moduleSlug="customer_claims"><ClaimsList /></ModuleRoute></SafePage>} />
          <Route path="/claims/new" element={<SafePage name="claim-create"><ModuleRoute moduleSlug="customer_claims"><ClaimCreateForm /></ModuleRoute></SafePage>} />
          <Route path="/claims/reports" element={<SafePage name="claims-reports"><ModuleRoute moduleSlug="customer_claims"><ClaimsReports /></ModuleRoute></SafePage>} />
          <Route path="/claims/:id" element={<SafePage name="claim-detail"><ModuleRoute moduleSlug="customer_claims"><ClaimDetail /></ModuleRoute></SafePage>} />

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

          {/* Franchise location detail */}
          <Route path="/locations/:id" element={<SafePage name="location-detail"><ModuleRoute moduleSlug="franchise"><LocationDetailRoute /></ModuleRoute></SafePage>} />

          {/* Catch-all */}
          <Route
            path="*"
            element={<Navigate to={isGlobalAdmin ? '/admin/dashboard' : '/dashboard'} replace />}
          />
        </Route>
      </Route>

      {/* Kiosk (standalone, outside OrgLayout) */}
      <Route element={<RequireAuth />}>
        <Route path="/kiosk" element={<SafePage name="kiosk"><KioskPage /></SafePage>} />
      </Route>

      {/* Customer portal (public, token-based access) */}
      <Route path="/portal/:token" element={<SafePage name="portal"><PortalPage /></SafePage>} />

      {/* Invoice payment page (public, token-based access — Stripe Elements) */}
      <Route path="/pay/:token" element={<SafePage name="invoice-payment"><InvoicePaymentPage /></SafePage>} />

      {/* Fallback */}
      <Route
        path="*"
        element={
          <Navigate to={isAuthenticated ? (isKiosk ? '/kiosk' : isGlobalAdmin ? '/admin/dashboard' : '/dashboard') : '/login'} replace />
        }
      />
    </Routes>
  )
}

function App() {
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
