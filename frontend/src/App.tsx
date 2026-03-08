import { Component, type ReactNode, lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate, Outlet, useParams } from 'react-router-dom'
import { AuthProvider, useAuth } from '@/contexts/AuthContext'
import { TenantProvider } from '@/contexts/TenantContext'
import { ModuleProvider } from '@/contexts/ModuleContext'
import { FeatureFlagProvider } from '@/contexts/FeatureFlagContext'
import { Spinner } from '@/components/ui'
import { Login, MfaVerify, PasswordResetRequest, PasswordResetComplete, Signup, VerifyEmail } from '@/pages/auth'
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
import { AuditLog } from '@/pages/admin/AuditLog'
import { Reports as AdminReports } from '@/pages/admin/Reports'
import { Integrations } from '@/pages/admin/Integrations'
import { UserManagement } from '@/pages/admin/UserManagement'
import { SubscriptionPlans } from '@/pages/admin/SubscriptionPlans'
import { FeatureFlags } from '@/pages/admin/FeatureFlags'

/* ── Org pages (lazy loaded) ── */
const CustomerList = lazy(() => import('@/pages/customers/CustomerList'))
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

/* Portal pages (public, token-based) */
const PortalPage = lazy(() => import('@/pages/portal/PortalPage').then(m => ({ default: m.PortalPage })))

/* Catalogue pages */
const CataloguePage = lazy(() => import('@/pages/catalogue/CataloguePage'))

/* Onboarding */
const OnboardingWizard = lazy(() => import('@/pages/onboarding/OnboardingWizard').then(m => ({ default: m.OnboardingWizard })))

/* Staff detail */
const StaffDetail = lazy(() => import('@/pages/staff/StaffDetail'))

/* Franchise location detail */
const LocationDetail = lazy(() => import('@/pages/franchise/LocationDetail'))

function LazyFallback() {
  return (
    <div className="flex items-center justify-center p-8">
      <Spinner size="lg" label="Loading page" />
    </div>
  )
}

/** Catch rendering errors so the page doesn't go blank */
class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null }
  static getDerivedStateFromError(error: Error) {
    return { error }
  }
  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 32, fontFamily: 'sans-serif' }}>
          <h1 style={{ color: '#dc2626' }}>Something went wrong</h1>
          <pre style={{ whiteSpace: 'pre-wrap', marginTop: 16, color: '#374151' }}>
            {this.state.error.message}
          </pre>
          <pre style={{ whiteSpace: 'pre-wrap', marginTop: 8, fontSize: 12, color: '#6b7280' }}>
            {this.state.error.stack}
          </pre>
          <button
            onClick={() => window.location.reload()}
            style={{ marginTop: 16, padding: '8px 16px', cursor: 'pointer' }}
          >
            Reload
          </button>
        </div>
      )
    }
    return this.props.children
  }
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
  const { isAuthenticated, isLoading, isGlobalAdmin } = useAuth()
  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner size="lg" label="Loading session" />
      </div>
    )
  }
  if (isAuthenticated) {
    return <Navigate to={isGlobalAdmin ? '/admin/dashboard' : '/dashboard'} replace />
  }
  return <Outlet />
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
  const { isGlobalAdmin, isAuthenticated } = useAuth()

  return (
    <Routes>
      {/* Guest routes */}
      <Route element={<GuestOnly />}>
        <Route path="/login" element={<Login />} />
        <Route path="/mfa-verify" element={<MfaVerify />} />
        <Route path="/forgot-password" element={<PasswordResetRequest />} />
        <Route path="/reset-password" element={<PasswordResetComplete />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="/verify-email" element={<VerifyEmail />} />
      </Route>

      {/* Global admin routes */}
      <Route element={<RequireAuth />}>
        <Route element={<RequireGlobalAdmin />}>
          <Route path="/admin" element={<AdminLayout />}>
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="organisations" element={<Organisations />} />
            <Route path="users" element={<UserManagement />} />
            <Route path="plans" element={<SubscriptionPlans />} />
            <Route path="feature-flags" element={<FeatureFlags />} />
            <Route path="analytics" element={<AnalyticsDashboard />} />
            <Route path="settings" element={<AdminSettings />} />
            <Route path="errors" element={<ErrorLog />} />
            <Route path="notifications" element={<NotificationManager />} />
            <Route path="branding" element={<BrandingConfig />} />
            <Route path="migration" element={<MigrationTool />} />
            <Route path="audit-log" element={<AuditLog />} />
            <Route path="reports" element={<AdminReports />} />
            <Route path="integrations" element={<Integrations />} />
            <Route index element={<Navigate to="dashboard" replace />} />
          </Route>
        </Route>

        {/* Org-level routes */}
        <Route element={<OrgLayout />}>
          <Route
            path="/dashboard"
            element={isGlobalAdmin && !sessionStorage.getItem('admin_view_as_org') ? <Navigate to="/admin/dashboard" replace /> : <Dashboard />}
          />

          {/* Customers */}
          <Route path="/customers" element={<Suspense fallback={<LazyFallback />}><CustomerList /></Suspense>} />
          <Route path="/customers/:id" element={<Suspense fallback={<LazyFallback />}><CustomerProfile /></Suspense>} />

          {/* Vehicles */}
          <Route path="/vehicles" element={<Suspense fallback={<LazyFallback />}><VehicleList /></Suspense>} />
          <Route path="/vehicles/:id" element={<Suspense fallback={<LazyFallback />}><VehicleProfile /></Suspense>} />

          {/* Invoices */}
          <Route path="/invoices" element={<Suspense fallback={<LazyFallback />}><InvoiceList /></Suspense>} />
          <Route path="/invoices/new" element={<Suspense fallback={<LazyFallback />}><InvoiceCreate /></Suspense>} />
          <Route path="/invoices/:id" element={<Suspense fallback={<LazyFallback />}><InvoiceDetail /></Suspense>} />

          {/* Quotes */}
          <Route path="/quotes" element={<Suspense fallback={<LazyFallback />}><QuoteList /></Suspense>} />
          <Route path="/quotes/new" element={<Suspense fallback={<LazyFallback />}><QuoteCreate /></Suspense>} />
          <Route path="/quotes/:id" element={<Suspense fallback={<LazyFallback />}><QuoteDetailRoute /></Suspense>} />

          {/* Job Cards */}
          <Route path="/job-cards" element={<Suspense fallback={<LazyFallback />}><JobCardList /></Suspense>} />
          <Route path="/job-cards/new" element={<Suspense fallback={<LazyFallback />}><JobCardCreate /></Suspense>} />
          <Route path="/job-cards/:id" element={<Suspense fallback={<LazyFallback />}><JobCardDetail /></Suspense>} />

          {/* Bookings */}
          <Route path="/bookings" element={<Suspense fallback={<LazyFallback />}><BookingCalendarPage /></Suspense>} />

          {/* Inventory */}
          <Route path="/inventory" element={<Suspense fallback={<LazyFallback />}><InventoryPage /></Suspense>} />

          {/* Reports */}
          <Route path="/reports" element={<Suspense fallback={<LazyFallback />}><ReportsPage /></Suspense>} />

          {/* Settings */}
          <Route path="/settings" element={<Suspense fallback={<LazyFallback />}><OrgSettingsPage /></Suspense>} />

          {/* Notifications */}
          <Route path="/notifications" element={<Suspense fallback={<LazyFallback />}><NotificationsPage /></Suspense>} />

          {/* Staff */}
          <Route path="/staff" element={<Suspense fallback={<LazyFallback />}><StaffList /></Suspense>} />

          {/* Projects */}
          <Route path="/projects" element={<Suspense fallback={<LazyFallback />}><ProjectList /></Suspense>} />
          <Route path="/projects/:id" element={<Suspense fallback={<LazyFallback />}><ProjectDashboardRoute /></Suspense>} />

          {/* Expenses */}
          <Route path="/expenses" element={<Suspense fallback={<LazyFallback />}><ExpenseList /></Suspense>} />

          {/* Time Tracking */}
          <Route path="/time-tracking" element={<Suspense fallback={<LazyFallback />}><TimeSheet /></Suspense>} />

          {/* POS */}
          <Route path="/pos" element={<Suspense fallback={<LazyFallback />}><POSScreen /></Suspense>} />

          {/* Schedule */}
          <Route path="/schedule" element={<Suspense fallback={<LazyFallback />}><ScheduleCalendar /></Suspense>} />

          {/* Recurring Invoices */}
          <Route path="/recurring" element={<Suspense fallback={<LazyFallback />}><RecurringList /></Suspense>} />

          {/* Purchase Orders */}
          <Route path="/purchase-orders" element={<Suspense fallback={<LazyFallback />}><POList /></Suspense>} />

          {/* Data Import/Export */}
          <Route path="/data" element={<Suspense fallback={<LazyFallback />}><DataPage /></Suspense>} />

          {/* Construction */}
          <Route path="/progress-claims" element={<Suspense fallback={<LazyFallback />}><ProgressClaimList /></Suspense>} />
          <Route path="/variations" element={<Suspense fallback={<LazyFallback />}><VariationList /></Suspense>} />
          <Route path="/retentions" element={<Suspense fallback={<LazyFallback />}><RetentionSummary /></Suspense>} />

          {/* Floor Plan / Tables */}
          <Route path="/floor-plan" element={<Suspense fallback={<LazyFallback />}><FloorPlan /></Suspense>} />

          {/* Kitchen Display */}
          <Route path="/kitchen" element={<Suspense fallback={<LazyFallback />}><KitchenDisplay /></Suspense>} />

          {/* Franchise */}
          <Route path="/franchise" element={<Suspense fallback={<LazyFallback />}><FranchiseDashboard /></Suspense>} />
          <Route path="/locations" element={<Suspense fallback={<LazyFallback />}><LocationList /></Suspense>} />
          <Route path="/stock-transfers" element={<Suspense fallback={<LazyFallback />}><StockTransfers /></Suspense>} />

          {/* Assets */}
          <Route path="/assets" element={<Suspense fallback={<LazyFallback />}><AssetList /></Suspense>} />
          <Route path="/assets/:id" element={<Suspense fallback={<LazyFallback />}><AssetDetailRoute /></Suspense>} />

          {/* Compliance */}
          <Route path="/compliance" element={<Suspense fallback={<LazyFallback />}><ComplianceDashboard /></Suspense>} />

          {/* Loyalty */}
          <Route path="/loyalty" element={<Suspense fallback={<LazyFallback />}><LoyaltyConfig /></Suspense>} />

          {/* Ecommerce */}
          <Route path="/ecommerce" element={<Suspense fallback={<LazyFallback />}><WooCommerceSetup /></Suspense>} />

          {/* Setup Wizard */}
          <Route path="/setup" element={<Suspense fallback={<LazyFallback />}><SetupWizard /></Suspense>} />

          {/* Jobs v2 */}
          <Route path="/jobs" element={<Suspense fallback={<LazyFallback />}><JobList /></Suspense>} />
          <Route path="/jobs/board" element={<Suspense fallback={<LazyFallback />}><JobBoard /></Suspense>} />
          <Route path="/jobs/:id" element={<Suspense fallback={<LazyFallback />}><JobDetailRoute /></Suspense>} />

          {/* Catalogue */}
          <Route path="/catalogue" element={<Suspense fallback={<LazyFallback />}><CataloguePage /></Suspense>} />

          {/* Onboarding */}
          <Route path="/onboarding" element={<Suspense fallback={<LazyFallback />}><OnboardingWizard /></Suspense>} />

          {/* Staff detail */}
          <Route path="/staff/:id" element={<Suspense fallback={<LazyFallback />}><StaffDetailRoute /></Suspense>} />

          {/* Franchise location detail */}
          <Route path="/locations/:id" element={<Suspense fallback={<LazyFallback />}><LocationDetailRoute /></Suspense>} />

          {/* Catch-all */}
          <Route
            path="*"
            element={<Navigate to={isGlobalAdmin ? '/admin/dashboard' : '/dashboard'} replace />}
          />
        </Route>
      </Route>

      {/* Customer portal (public, token-based access) */}
      <Route path="/portal/:token" element={<Suspense fallback={<LazyFallback />}><PortalPage /></Suspense>} />

      {/* Fallback */}
      <Route
        path="*"
        element={
          <Navigate to={isAuthenticated ? (isGlobalAdmin ? '/admin/dashboard' : '/dashboard') : '/login'} replace />
        }
      />
    </Routes>
  )
}

function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <AuthProvider>
          <TenantProvider>
            <ModuleProvider>
              <FeatureFlagProvider>
                <AppRoutes />
              </FeatureFlagProvider>
            </ModuleProvider>
          </TenantProvider>
        </AuthProvider>
      </BrowserRouter>
    </ErrorBoundary>
  )
}

export default App
