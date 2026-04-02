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

/* ── Org pages (lazy loaded) ── */
const CustomerList = lazy(() => import('@/pages/customers/CustomerList'))
const CustomerCreate = lazy(() => import('@/pages/customers/CustomerCreate'))
const CustomerProfile = lazy(() => import('@/pages/customers/CustomerProfile'))
const VehicleList = lazy(() => import('@/pages/vehicles/VehicleList'))
const VehicleProfile = lazy(() => import('@/pages/vehicles/VehicleProfile'))
const InvoiceList = lazy(() => import('@/pages/invoices/InvoiceList'))
const InvoiceCreate = lazy(() => import('@/pages/invoices/InvoiceCreate'))
const InvoiceDetail = lazy(() => import('@/pages/invoices/InvoiceDetail'))
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
const JobList = lazy(() => import('@/pages/jobs/JobList'))
const JobDetail = lazy(() => import('@/pages/jobs/JobDetail'))
const JobBoard = lazy(() => import('@/pages/jobs/JobBoard'))
const JobsPage = lazy(() => import('@/pages/jobs/JobsPage'))

/* Portal pages (public, token-based) */
const PortalPage = lazy(() => import('@/pages/portal/PortalPage').then(m => ({ default: m.PortalPage })))

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
            <Route path="organisations" element={<SafePage name="admin-organisations"><Organisations /></SafePage>} />
            <Route path="users" element={<SafePage name="admin-users"><UserManagement /></SafePage>} />
            <Route path="plans" element={<SafePage name="admin-plans"><SubscriptionPlans /></SafePage>} />
            <Route path="feature-flags" element={<SafePage name="admin-feature-flags"><FeatureFlags /></SafePage>} />
            <Route path="analytics" element={<SafePage name="admin-analytics"><AnalyticsDashboard /></SafePage>} />
            <Route path="settings" element={<SafePage name="admin-settings"><AdminSettings /></SafePage>} />
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
            <Route path="/vehicles" element={<SafePage name="vehicles"><VehicleList /></SafePage>} />
            <Route path="/vehicles/:id" element={<SafePage name="vehicle-profile"><VehicleProfile /></SafePage>} />
          </Route>

          {/* Invoices */}
          <Route path="/invoices" element={<SafePage name="invoices"><InvoiceList /></SafePage>} />
          <Route path="/invoices/new" element={<SafePage name="invoice-create"><InvoiceList /></SafePage>} />
          <Route path="/invoices/:id/edit" element={<SafePage name="invoice-edit"><InvoiceCreate /></SafePage>} />
          <Route path="/invoices/:id" element={<SafePage name="invoice-detail"><InvoiceList /></SafePage>} />

          {/* Quotes */}
          <Route path="/quotes" element={<SafePage name="quotes"><QuoteList /></SafePage>} />
          <Route path="/quotes/new" element={<SafePage name="quote-create"><QuoteCreate /></SafePage>} />
          <Route path="/quotes/:id/edit" element={<SafePage name="quote-edit"><QuoteCreate /></SafePage>} />
          <Route path="/quotes/:id" element={<SafePage name="quote-detail"><QuoteDetailRoute /></SafePage>} />

          {/* Job Cards */}
          <Route path="/job-cards" element={<SafePage name="job-cards"><JobCardList /></SafePage>} />
          <Route path="/job-cards/new" element={<SafePage name="job-card-create"><JobCardCreate /></SafePage>} />
          <Route path="/job-cards/:id" element={<SafePage name="job-card-detail"><JobCardDetail /></SafePage>} />

          {/* Bookings */}
          <Route path="/bookings" element={<SafePage name="bookings"><BookingCalendarPage /></SafePage>} />

          {/* Inventory */}
          <Route path="/inventory" element={<SafePage name="inventory"><InventoryPage /></SafePage>} />

          {/* Reports */}
          <Route path="/reports" element={<SafePage name="reports"><ReportsPage /></SafePage>} />

          {/* Settings */}
          <Route path="/settings" element={<SafePage name="settings"><OrgSettingsPage /></SafePage>} />

          {/* Notifications */}
          <Route path="/notifications" element={<SafePage name="notifications"><NotificationsPage /></SafePage>} />

          {/* Staff */}
          <Route path="/staff" element={<SafePage name="staff"><StaffList /></SafePage>} />

          {/* Projects */}
          <Route path="/projects" element={<SafePage name="projects"><ProjectList /></SafePage>} />
          <Route path="/projects/:id" element={<SafePage name="project-detail"><ProjectDashboardRoute /></SafePage>} />

          {/* Expenses */}
          <Route path="/expenses" element={<SafePage name="expenses"><ExpenseList /></SafePage>} />

          {/* Time Tracking */}
          <Route path="/time-tracking" element={<SafePage name="time-tracking"><TimeSheet /></SafePage>} />

          {/* POS */}
          <Route path="/pos" element={<SafePage name="pos"><POSScreen /></SafePage>} />

          {/* Schedule */}
          <Route path="/schedule" element={<SafePage name="schedule"><ScheduleCalendar /></SafePage>} />

          {/* Recurring Invoices */}
          <Route path="/recurring" element={<SafePage name="recurring"><RecurringList /></SafePage>} />

          {/* Purchase Orders */}
          <Route path="/purchase-orders" element={<SafePage name="purchase-orders"><POList /></SafePage>} />
          <Route path="/purchase-orders/:id" element={<SafePage name="po-detail"><PODetail /></SafePage>} />

          {/* Data Import/Export */}
          <Route path="/data" element={<SafePage name="data"><DataPage /></SafePage>} />

          {/* Construction */}
          <Route path="/progress-claims" element={<SafePage name="progress-claims"><ProgressClaimList /></SafePage>} />
          <Route path="/variations" element={<SafePage name="variations"><VariationList /></SafePage>} />
          <Route path="/retentions" element={<SafePage name="retentions"><RetentionSummary /></SafePage>} />

          {/* Floor Plan / Tables */}
          <Route path="/floor-plan" element={<SafePage name="floor-plan"><FloorPlan /></SafePage>} />

          {/* Kitchen Display */}
          <Route path="/kitchen" element={<SafePage name="kitchen"><KitchenDisplay /></SafePage>} />

          {/* Franchise */}
          <Route path="/franchise" element={<SafePage name="franchise"><FranchiseDashboard /></SafePage>} />
          <Route path="/locations" element={<SafePage name="locations"><LocationList /></SafePage>} />
          <Route path="/stock-transfers" element={<SafePage name="stock-transfers"><StockTransfers /></SafePage>} />

          {/* Branch Stock Transfers */}
          <Route path="/branch-transfers" element={<SafePage name="branch-transfers"><BranchStockTransfers /></SafePage>} />

          {/* Claims */}
          <Route path="/claims" element={<SafePage name="claims"><ClaimsList /></SafePage>} />
          <Route path="/claims/new" element={<SafePage name="claim-create"><ClaimCreateForm /></SafePage>} />
          <Route path="/claims/reports" element={<SafePage name="claims-reports"><ClaimsReports /></SafePage>} />
          <Route path="/claims/:id" element={<SafePage name="claim-detail"><ClaimDetail /></SafePage>} />

          {/* Staff Schedule (branch-scoped) */}
          <Route path="/staff-schedule" element={<SafePage name="staff-schedule"><StaffSchedule /></SafePage>} />

          {/* Assets */}
          <Route path="/assets" element={<SafePage name="assets"><AssetList /></SafePage>} />
          <Route path="/assets/:id" element={<SafePage name="asset-detail"><AssetDetailRoute /></SafePage>} />

          {/* Compliance */}
          <Route path="/compliance" element={<SafePage name="compliance"><ComplianceDashboard /></SafePage>} />

          {/* Loyalty */}
          <Route path="/loyalty" element={<SafePage name="loyalty"><LoyaltyConfig /></SafePage>} />

          {/* Ecommerce */}
          <Route path="/ecommerce" element={<SafePage name="ecommerce"><WooCommerceSetup /></SafePage>} />

          {/* Setup Wizard */}
          <Route path="/setup" element={<SafePage name="setup"><SetupWizard /></SafePage>} />

          {/* Jobs v2 */}
          <Route path="/jobs" element={<SafePage name="jobs"><JobsPage /></SafePage>} />
          <Route path="/jobs/board" element={<SafePage name="job-board"><JobBoard /></SafePage>} />
          <Route path="/jobs/:id" element={<SafePage name="job-detail"><JobDetailRoute /></SafePage>} />

          {/* Items */}
          <Route path="/items" element={<SafePage name="items"><ItemsPage /></SafePage>} />

          {/* Catalogue */}
          <Route path="/catalogue" element={<SafePage name="catalogue"><CataloguePage /></SafePage>} />

          {/* Onboarding */}
          <Route path="/onboarding" element={<SafePage name="onboarding"><OnboardingWizard /></SafePage>} />

          {/* Staff detail */}
          <Route path="/staff/:id" element={<SafePage name="staff-detail"><StaffDetailRoute /></SafePage>} />

          {/* Franchise location detail */}
          <Route path="/locations/:id" element={<SafePage name="location-detail"><LocationDetailRoute /></SafePage>} />

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
