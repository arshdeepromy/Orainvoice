import { Routes, Route, useNavigate } from 'react-router-dom'
import { Suspense, lazy, useEffect, useState } from 'react'
import type { ComponentType } from 'react'
import { useModules } from '@/contexts/ModuleContext'
import { useFlag, useFeatureFlags } from '@/contexts/FeatureFlagContext'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import { ErrorBoundaryWithRetry } from '@/components/common/ErrorBoundaryWithRetry'
import { Spinner } from '@/components/ui'

const LazyFeatureNotAvailable = lazy(() => import('@/pages/common/FeatureNotAvailable'))

/* ------------------------------------------------------------------ */
/*  Lazy-loaded page components                                        */
/* ------------------------------------------------------------------ */

// Core routes
const LazyDashboard = lazy(() =>
  import('@/pages/dashboard/Dashboard').then((m) => ({ default: m.Dashboard }))
)
const LazyInvoiceList = lazy(() => import('@/pages/invoices/InvoiceList'))
const LazyCustomerList = lazy(() => import('@/pages/customers/CustomerList'))
const LazySettings = lazy(() =>
  import('@/pages/settings/Settings').then((m) => ({ default: m.Settings }))
)
const LazyReportsPage = lazy(() => import('@/pages/reports/ReportsPage'))
const LazyNotificationsPage = lazy(() => import('@/pages/notifications/NotificationsPage'))
const LazyDataPage = lazy(() => import('@/pages/data/DataPage'))

// Module routes
const LazyInventoryPage = lazy(() => import('@/pages/inventory/InventoryPage'))
const LazyJobCardList = lazy(() => import('@/pages/job-cards/JobCardList'))
const LazyJobBoard = lazy(() => import('@/pages/jobs/JobBoard'))
const LazyQuoteList = lazy(() => import('@/pages/quotes/QuoteList'))
const LazyBookingList = lazy(() => import('@/pages/bookings/BookingList'))
const LazyVehicleList = lazy(() => import('@/pages/vehicles/VehicleList'))
const LazyStaffList = lazy(() => import('@/pages/staff/StaffList'))
const LazyProjectList = lazy(() => import('@/pages/projects/ProjectList'))
const LazyExpenseList = lazy(() => import('@/pages/expenses/ExpenseList'))
const LazyTimeSheet = lazy(() => import('@/pages/time-tracking/TimeSheet'))
const LazyScheduleCalendar = lazy(() => import('@/pages/schedule/ScheduleCalendar'))
const LazyPOSScreen = lazy(() => import('@/pages/pos/POSScreen'))
const LazyRecurringList = lazy(() => import('@/pages/recurring/RecurringList'))
const LazyPOList = lazy(() => import('@/pages/purchase-orders/POList'))
const LazyProgressClaimList = lazy(() => import('@/pages/construction/ProgressClaimList'))
const LazyVariationList = lazy(() => import('@/pages/construction/VariationList'))
const LazyRetentionSummary = lazy(() => import('@/pages/construction/RetentionSummary'))
const LazyFloorPlan = lazy(() => import('@/pages/floor-plan/FloorPlan'))
const LazyKitchenDisplay = lazy(() => import('@/pages/kitchen/KitchenDisplay'))
const LazyFranchiseDashboard = lazy(() => import('@/pages/franchise/FranchiseDashboard'))
const LazyLocationList = lazy(() => import('@/pages/franchise/LocationList'))
const LazyStockTransfers = lazy(() => import('@/pages/franchise/StockTransfers'))
const LazyAssetList = lazy(() => import('@/pages/assets/AssetList'))
const LazyComplianceDashboard = lazy(() => import('@/pages/compliance/ComplianceDashboard'))
const LazyLoyaltyConfig = lazy(() => import('@/pages/loyalty/LoyaltyConfig'))
const LazyWooCommerceSetup = lazy(() => import('@/pages/ecommerce/WooCommerceSetup'))
const LazyCataloguePage = lazy(() => import('@/pages/catalogue/CataloguePage'))

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export interface RouteConfig {
  path: string
  component: ComponentType
}

/* ------------------------------------------------------------------ */
/*  Loading fallback                                                   */
/* ------------------------------------------------------------------ */

function LoadingFallback() {
  return (
    <div
      className="flex items-center justify-center p-8"
      data-testid="route-loading-fallback"
    >
      <Spinner size="lg" label="Loading page" />
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Suspense + ErrorBoundary wrapper for lazy components               */
/* ------------------------------------------------------------------ */

function SuspenseWithBoundary({ children }: { children: React.ReactNode }) {
  return (
    <ErrorBoundaryWithRetry>
      <Suspense fallback={<LoadingFallback />}>{children}</Suspense>
    </ErrorBoundaryWithRetry>
  )
}

/* ------------------------------------------------------------------ */
/*  Flag-to-route mapping                                              */
/* ------------------------------------------------------------------ */

/**
 * Maps route path prefixes to feature flag keys.
 * A route renders only if both the module is enabled AND the corresponding flag is true.
 */
export const FLAG_ROUTE_MAP: Record<string, string> = {
  '/quotes': 'quotes',
  '/jobs': 'jobs',
  '/job-cards': 'jobs',
  '/projects': 'projects',
  '/time-tracking': 'time_tracking',
  '/expenses': 'expenses',
  '/inventory': 'inventory',
  '/purchase-orders': 'purchase_orders',
  '/pos': 'pos',
  '/floor-plan': 'tables',
  '/kitchen': 'kitchen_display',
  '/schedule': 'scheduling',
  '/staff': 'staff',
  '/bookings': 'bookings',
  '/progress-claims': 'progress_claims',
  '/retentions': 'retentions',
  '/variations': 'variations',
  '/compliance': 'compliance_docs',
  '/loyalty': 'loyalty',
  '/franchise': 'franchise',
  '/ecommerce': 'ecommerce',
  '/assets': 'assets',
  '/recurring': 'recurring',
}

/**
 * Resolves a route path to its feature flag key using FLAG_ROUTE_MAP.
 * Strips trailing wildcards and matches the path prefix.
 */
function getFlagKeyForPath(routePath: string): string | undefined {
  const cleanPath = routePath.replace(/\/?\*$/, '')
  return FLAG_ROUTE_MAP[cleanPath]
}

/* ------------------------------------------------------------------ */
/*  FlagGatedRoute                                                     */
/* ------------------------------------------------------------------ */

/**
 * Wrapper component that gates a route behind a feature flag.
 * If the flag is disabled, redirects to /dashboard with a toast notification.
 */
function FlagGatedRoute({
  flagKey,
  component: Component,
}: {
  flagKey: string
  component: ComponentType
}) {
  const flagEnabled = useFlag(flagKey)
  const navigate = useNavigate()
  const { toasts, addToast, dismissToast } = useToast()
  const [redirected, setRedirected] = useState(false)

  useEffect(() => {
    if (!flagEnabled && !redirected) {
      addToast('warning', `This feature is currently disabled.`)
      setRedirected(true)
      navigate('/dashboard', { replace: true })
    }
  }, [flagEnabled, redirected, navigate, addToast])

  if (!flagEnabled) {
    return <ToastContainer toasts={toasts} onDismiss={dismissToast} />
  }

  return (
    <>
      <SuspenseWithBoundary>
        <Component />
      </SuspenseWithBoundary>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </>
  )
}

/* ------------------------------------------------------------------ */
/*  Route tables                                                       */
/* ------------------------------------------------------------------ */

/**
 * Maps module slugs to their route configurations.
 * Only routes for enabled modules will be rendered.
 */
const MODULE_ROUTES: Record<string, RouteConfig[]> = {
  inventory: [
    { path: '/inventory/*', component: LazyInventoryPage },
  ],
  jobs: [
    { path: '/job-cards/*', component: LazyJobCardList },
    { path: '/jobs/*', component: LazyJobBoard },
  ],
  quotes: [
    { path: '/quotes/*', component: LazyQuoteList },
  ],
  bookings: [
    { path: '/bookings/*', component: LazyBookingList },
  ],
  vehicles: [
    { path: '/vehicles/*', component: LazyVehicleList },
  ],
  staff: [
    { path: '/staff/*', component: LazyStaffList },
  ],
  projects: [
    { path: '/projects/*', component: LazyProjectList },
  ],
  expenses: [
    { path: '/expenses/*', component: LazyExpenseList },
  ],
  time_tracking: [
    { path: '/time-tracking/*', component: LazyTimeSheet },
  ],
  scheduling: [
    { path: '/schedule/*', component: LazyScheduleCalendar },
  ],
  pos: [
    { path: '/pos/*', component: LazyPOSScreen },
  ],
  recurring_invoices: [
    { path: '/recurring/*', component: LazyRecurringList },
  ],
  purchase_orders: [
    { path: '/purchase-orders/*', component: LazyPOList },
  ],
  progress_claims: [
    { path: '/progress-claims/*', component: LazyProgressClaimList },
  ],
  variations: [
    { path: '/variations/*', component: LazyVariationList },
  ],
  retentions: [
    { path: '/retentions/*', component: LazyRetentionSummary },
  ],
  tables: [
    { path: '/floor-plan/*', component: LazyFloorPlan },
  ],
  kitchen_display: [
    { path: '/kitchen/*', component: LazyKitchenDisplay },
  ],
  franchise: [
    { path: '/franchise/*', component: LazyFranchiseDashboard },
    { path: '/locations/*', component: LazyLocationList },
    { path: '/stock-transfers/*', component: LazyStockTransfers },
  ],
  assets: [
    { path: '/assets/*', component: LazyAssetList },
  ],
  compliance_docs: [
    { path: '/compliance/*', component: LazyComplianceDashboard },
  ],
  loyalty: [
    { path: '/loyalty/*', component: LazyLoyaltyConfig },
  ],
  ecommerce: [
    { path: '/ecommerce/*', component: LazyWooCommerceSetup },
  ],
  catalogue: [
    { path: '/catalogue/*', component: LazyCataloguePage },
  ],
}

/**
 * Core routes that are always available regardless of module enablement.
 */
const CORE_ROUTES: RouteConfig[] = [
  { path: '/dashboard/*', component: LazyDashboard },
  { path: '/invoices/*', component: LazyInvoiceList },
  { path: '/customers/*', component: LazyCustomerList },
  { path: '/settings/*', component: LazySettings },
  { path: '/reports/*', component: LazyReportsPage },
  { path: '/notifications/*', component: LazyNotificationsPage },
  { path: '/data/*', component: LazyDataPage },
]

/* ------------------------------------------------------------------ */
/*  ModuleRouter                                                       */
/* ------------------------------------------------------------------ */

/**
 * Collects all route path prefixes for disabled modules so we can
 * render a "Feature not available" catch-all for direct URL access.
 */
function getDisabledModuleRoutes(enabledModules: string[]): string[] {
  const paths: string[] = []
  for (const [moduleSlug, routes] of Object.entries(MODULE_ROUTES)) {
    if (!enabledModules.includes(moduleSlug)) {
      for (const r of routes) {
        paths.push(r.path)
      }
    }
  }
  return paths
}

/**
 * In development mode, log any disabled module routes to the console
 * to help developers identify remaining gaps.
 */
function useDevModeLogging(enabledModules: string[]) {
  useEffect(() => {
    if (import.meta.env.DEV) {
      const disabledSlugs = Object.keys(MODULE_ROUTES).filter(
        (slug) => !enabledModules.includes(slug),
      )
      if (disabledSlugs.length > 0) {
        console.info(
          '[ModuleRouter] Disabled modules (routes will show "Feature not available"):',
          disabledSlugs,
        )
      }

      // Log flag-gated route mappings for developer awareness
      if (Object.keys(FLAG_ROUTE_MAP).length > 0) {
        console.info(
          '[ModuleRouter] Flag-gated route mappings:',
          FLAG_ROUTE_MAP,
        )
      }
    }
  }, [enabledModules])
}

export function ModuleRouter() {
  const { enabledModules } = useModules()
  const { flags } = useFeatureFlags()

  // Dev-mode logging for disabled modules and flag-gated routes
  useDevModeLogging(enabledModules)

  // Log disabled flags in dev mode
  useEffect(() => {
    if (import.meta.env.DEV) {
      const disabledFlags = Object.entries(flags)
        .filter(([, enabled]) => !enabled)
        .map(([key]) => key)
      if (disabledFlags.length > 0) {
        console.info(
          '[ModuleRouter] Disabled feature flags (associated menu items hidden):',
          disabledFlags,
        )
      }
    }
  }, [flags])

  const disabledRoutes = getDisabledModuleRoutes(enabledModules)

  return (
    <Routes>
      {/* Core routes always available — wrapped in Suspense + ErrorBoundary */}
      {CORE_ROUTES.map((r) => (
        <Route
          key={r.path}
          path={r.path}
          element={
            <SuspenseWithBoundary>
              <r.component />
            </SuspenseWithBoundary>
          }
        />
      ))}

      {/* Module routes conditionally rendered with flag gating */}
      {Object.entries(MODULE_ROUTES).map(([moduleSlug, routes]) =>
        enabledModules.includes(moduleSlug)
          ? routes.map((r) => {
              const flagKey = getFlagKeyForPath(r.path)
              if (flagKey) {
                return (
                  <Route
                    key={r.path}
                    path={r.path}
                    element={
                      <FlagGatedRoute flagKey={flagKey} component={r.component} />
                    }
                  />
                )
              }
              return (
                <Route
                  key={r.path}
                  path={r.path}
                  element={
                    <SuspenseWithBoundary>
                      <r.component />
                    </SuspenseWithBoundary>
                  }
                />
              )
            })
          : null,
      )}

      {/* Disabled module routes show "Feature not available" page */}
      {disabledRoutes.map((path) => (
        <Route
          key={`disabled-${path}`}
          path={path}
          element={
            <SuspenseWithBoundary>
              <LazyFeatureNotAvailable />
            </SuspenseWithBoundary>
          }
        />
      ))}
    </Routes>
  )
}

export { MODULE_ROUTES, CORE_ROUTES }
